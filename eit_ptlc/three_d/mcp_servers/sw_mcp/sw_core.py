"""
功能: SolidWorks COM 自动化核心封装. 负责连接正在运行的 SolidWorks 实例, 打开装配体,
      配置 STEP 导出选项并导出中性格式文件, 供三维可视化资产管线使用.

设计原则(安全第一, 因为用户的 SolidWorks 里可能正开着未保存的设计):
  1. 只读打开: 所有文档均以 Silent + ReadOnly 方式打开;
  2. 绝不保存用户文档: 只调用 SaveAs 导出到 exports 目录, 从不对原始 SLDASM/SLDPRT 落盘;
  3. 只关自己开的文档: 记录本会话打开过的文档路径, 关闭时只关这些, 用户原本开着的一律不动;
  4. 常量不硬编码: 全部通过 sw_constants 从 swconst.tlb 读取.

本模块被 server.py(MCP 服务器)和 pipeline 脚本共用; 也可直接当命令行工具使用:
    python sw_core.py info
    python sw_core.py export --input <装配体.SLDASM> --output <输出.STEP>

参数: 见各函数签名
返回值: 见各函数说明
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import pythoncom
import win32com.client
from win32com.client import VARIANT, gencache

import sw_constants as swc

# ---------------------------------------------------------------------------
# 常量(从 swconst.tlb 读取, 此处仅做惰性缓存)
# ---------------------------------------------------------------------------

DOC_TYPE_BY_EXT = {
    ".sldprt": "swDocPART",
    ".sldasm": "swDocASSEMBLY",
    ".slddrw": "swDocDRAWING",
}

STEP_AP_VALUES = {203: "swAP_203", 214: "swAP_214", 242: "swAP_242"}

# SolidWorks 自带 XR 导出器插件的 CLSID(取自 SWXRExporter.tlb 的 COCLASS).
# 它提供 GLTF_FileSave_Assembly / GLTF_FileSave_Part, 是把 SLDASM 直接导成 glTF 的入口 ——
# 比走 STEP 少丢一大截信息(实例名/中文名/材质颜色), 还省掉 OCCT 那 11 分钟转换.
XR_EXPORTER_CLSID = "{87B557C0-E5DB-4894-A448-76609C3B4D8E}"


def _ensure_early_binding() -> bool:
    """
    功能: 在本进程加载 SolidWorks 的 makepy 包装, 启用早期绑定.

    这一步是整套 COM 调用能否正常工作的前提, 且**必须在 Dispatch 之前做**:
    pywin32 是在 Dispatch 那一刻决定用早期还是后期绑定的 —— 若此时本进程还没加载
    类型库包装, 拿到的就是泛型 CDispatch, 之后所有挂在具体接口上的方法(GetActiveConfiguration、
    GetRootComponent3 等)一律"找不到成员", 且后补包装也救不回来.

    参数: 无
    返回值: bool, 是否成功启用早期绑定
    """
    try:
        typelib = pythoncom.LoadTypeLib(os.path.join(swc.find_sw_dir(), "sldworks.tlb"))
        attr = typelib.GetLibAttr()
        gencache.EnsureModule(str(attr[0]), attr[1], attr[3], attr[4])
        return True
    except Exception:  # noqa: BLE001 - 装不上就退回后期绑定, 功能受限但不至于完全不能用
        return False


# 各接口的探针方法: 包装完实调一次, 验证这个接口确实适用于该对象.
# 选的都是无副作用、无参数的读方法.
_INTERFACE_PROBE = {
    "IModelDoc2": "GetPathName",
    "IComponent2": "GetPathName",
    "IConfiguration": "GetName",
    "IAssemblyDoc": "GetPathName",
    "ISldWorks": "RevisionNumber",
}


@functools.lru_cache(maxsize=1)
def _gen_module() -> Any:
    """
    功能: 取 SolidWorks 类型库的 makepy 生成模块(里面有 IModelDoc2/IComponent2 等接口类).
    参数: 无
    返回值: module | None, 未生成时返回 None
    """
    try:
        return gencache.GetModuleForProgID("SldWorks.Application")
    except Exception:  # noqa: BLE001
        return None


def _wrap(obj: Any, *interfaces: str, force: bool = False) -> Any:
    """
    功能: 把 COM 方法返回的原始 IDispatch 转换成早期绑定的具体接口包装.

    这是使用 SolidWorks COM 最容易踩空的一处: 即使为应用对象生成了 makepy 包装,
    从它的方法返回的对象(文档、组件、配置)仍是**未包装的原始 IDispatch** ——
    对它们调 GetActiveConfiguration 之类挂在具体接口上的方法, 会报"找不到成员".
    必须显式 CastTo 到 IModelDoc2 / IComponent2 等接口, 方法才可见.

    参数:
        obj: COM 对象
        interfaces: 候选接口名, 按优先级依次尝试
        force: 已是早期绑定包装时是否仍然重新转换. 同一个文档对象既是 IModelDoc2
               又是 IAssemblyDoc/IPartDoc, 想从前者换到后者就必须置 True ——
               默认的防双重包装守卫会把这种转换直接跳过.
    返回值: Any, 包装后的对象; 全部失败则原样返回(至少不会更糟)
    """
    if obj is None:
        return None

    # 已经是早期绑定包装的对象绝不能再套一层: 会产生一个 _oleobj_ 指向 Python 包装
    # 而非 PyIDispatch 的坏代理, 之后任何调用都报 "no attribute 'InvokeTypes'".
    # (force 时下面会从 _oleobj_ 取出原始 PyIDispatch 重包, 不构成双重包装)
    if not force and type(obj).__module__.startswith("win32com.gen_py"):
        return obj

    # 首选: 直接用 makepy 生成的接口类去包.
    # CastTo 在 SolidWorks 上基本不管用 —— 它依赖对象自报 CLSID, 而 SolidWorks 从方法
    # 返回的对象普遍不带这个信息, 于是静默退回后期绑定, 表现就是"接口方法找不到成员",
    # 而基础成员(Name2/GetPathName)却能用, 极具迷惑性.
    #
    # 两个必须注意的细节:
    #   1. DispatchBaseClass 的构造函数只认原始 PyIDispatch, 传 CDispatch 进去会把
    #      包装对象存成 _oleobj_, 得到一个调什么都报 "no attribute 'InvokeTypes'" 的坏代理;
    #   2. 构造成功不等于接口正确 —— 必须实调一次探针方法验证, 否则坏代理会一路传下去,
    #      直到某个深处才炸, 排查成本极高.
    raw = getattr(obj, "_oleobj_", obj)
    module = _gen_module()
    if module is not None:
        for interface in interfaces:
            klass = getattr(module, interface, None)
            if klass is None:
                continue
            try:
                wrapped = klass(raw)
                probe = _INTERFACE_PROBE.get(interface)
                if probe:
                    # 探针可能是方法也可能是属性, 用 _prop 统一处理
                    _prop(wrapped, probe)
                return wrapped
            except Exception:  # noqa: BLE001 - 该接口不适用就换下一个
                continue

    # 退路: CastTo, 再退到泛型 Dispatch
    try:
        dispatched = win32com.client.Dispatch(obj)
    except Exception:  # noqa: BLE001
        return obj
    for interface in interfaces:
        try:
            return win32com.client.CastTo(dispatched, interface)
        except Exception:  # noqa: BLE001
            continue
    return dispatched


def _prop(obj: Any, name: str, *args: Any) -> Any:
    """
    功能: 取一个 COM 成员的值, 兼容"属性"与"方法"两种暴露方式.

    pywin32 的动态派发对同一个 COM 成员, 有时给出属性(直接是值), 有时给出方法(要调用),
    取决于类型库里的声明方式与是否走了 makepy 缓存. SolidWorks 的 RevisionNumber
    就是典型 —— 直接当方法调会报 "'str' object is not callable".

    参数:
        obj: COM 对象
        name: 成员名
        args: 若是方法则传入的参数
    返回值: Any, 成员的值
    """
    member = getattr(obj, name)
    if callable(member):
        return member(*args)
    return member


def _addin_dll_path(clsid: str) -> str | None:
    """
    功能: 从注册表查一个 COM 组件的实现 DLL 路径.

    用于 LoadAddIn —— 它要的是 DLL 绝对路径而不是 CLSID.

    参数:
        clsid: 形如 "{87B557C0-...}"
    返回值: str | None, DLL 绝对路径; 查不到返回 None
    """
    import winreg

    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CLASSES_ROOT):
        for prefix in (r"SOFTWARE\Classes\CLSID", r"CLSID"):
            try:
                with winreg.OpenKey(root, rf"{prefix}\{clsid}\InprocServer32") as key:
                    value = winreg.QueryValueEx(key, "")[0]
                    if value:
                        return str(value).strip('"')
            except OSError:
                continue
    return None


def _byref_long(initial: int = 0) -> VARIANT:
    """
    功能: 构造一个可作为 COM 输出参数(ByRef Long)使用的 VARIANT.
    参数:
        initial: 初始值
    返回值: VARIANT, 调用后通过 .value 读取被写回的值
    """
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, initial)


def _call_with_outs(obj: Any, name: str, *args: Any, out_count: int = 0) -> tuple:
    """
    功能: 调用一个带 [out] 参数的 COM 方法, 兼容早期绑定与后期绑定两种约定.

    两者对 [out] 参数的处理完全不同:
      后期绑定(dynamic): 要自己传 VARIANT(VT_BYREF|VT_I4) 进去, 调用后读 .value
      早期绑定(makepy):  传普通占位值, 返回值变成 (retval, out1, out2, ...) 元组
    同一份代码要在装没装 makepy 缓存的机器上都能跑, 就得两条路都试.
    先走早期绑定(它更准), 失败再退回后期绑定.

    参数:
        obj: COM 对象
        name: 方法名
        args: 输入参数
        out_count: [out] 参数个数
    返回值: tuple, (返回值, out1, out2, ...); out_count 为 0 时只有返回值
    """
    method = getattr(obj, name)

    # 早期绑定: out 参数传 0 占位, 结果以元组形式返回
    try:
        result = method(*args, *([0] * out_count))
        if out_count == 0:
            return (result,)
        if isinstance(result, tuple):
            # 元组长度可能是 1+out_count(带返回值)或 out_count(void 方法)
            if len(result) >= out_count + 1:
                return tuple(result[: out_count + 1])
            return (None, *result)
        # 方法确实接受了占位参数但只回了单值, 说明 out 没被回传
        return (result, *([0] * out_count))
    except TypeError:
        pass

    # 后期绑定: 自备 VARIANT byref
    outs = [_byref_long() for _ in range(out_count)]
    result = method(*args, *outs)
    return (result, *[int(o.value) for o in outs])


@dataclass
class DocumentInfo:
    """功能: 描述一个 SolidWorks 文档的基本信息."""

    title: str
    path: str
    doc_type: int
    opened_by_us: bool = False

    def to_dict(self) -> dict[str, Any]:
        """功能: 转成可 JSON 序列化的字典. 参数: 无. 返回值: dict"""
        return {
            "title": self.title,
            "path": self.path,
            "doc_type": self.doc_type,
            "opened_by_us": self.opened_by_us,
        }


@dataclass
class SolidWorksSession:
    """
    功能: 一次 SolidWorks 自动化会话. 持有 COM 应用对象并跟踪本会话打开的文档.

    典型用法:
        with SolidWorksSession() as sw:
            sw.set_step_options(ap=214, appearances=True)
            sw.export_step(asm_path, out_path)
    """

    visible: bool = True
    _app: Any = field(default=None, init=False, repr=False)
    _opened_paths: list[str] = field(default_factory=list, init=False, repr=False)
    _com_initialized: bool = field(default=False, init=False, repr=False)
    _early_binding: bool = field(default=False, init=False, repr=False)
    # 路径(规范化) -> 文档 COM 对象.
    # 这个缓存是必需的而不是优化: OpenDoc6 的返回值在类型库里有声明返回类型, 因此在早期
    # 绑定下是正确包装的 IModelDoc2, 文档级方法(Extension / GetActiveConfiguration)全可用;
    # 而 GetDocuments 返回的是无类型信息的原始 IDispatch, 拿到的是泛型 CDispatch,
    # 那些方法一律"找不到成员". 所以打开时拿到的那个对象必须留住, 不能事后再去枚举。
    _models: dict = field(default_factory=dict, init=False, repr=False)

    # -- 生命周期 ----------------------------------------------------------

    def __enter__(self) -> SolidWorksSession:
        """功能: 上下文管理器入口, 建立连接. 参数: 无. 返回值: self"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """功能: 上下文管理器出口, 关闭本会话打开的文档并释放 COM. 参数: 标准异常三元组. 返回值: None"""
        self.close_all_opened()
        self.release()

    def connect(self) -> dict[str, Any]:
        """
        功能: 连接到正在运行的 SolidWorks; 若没有在运行则启动一个新实例.
        参数: 无
        返回值: dict, 含 revision(版本号) / visible / open_documents(当前已打开文档数)
        """
        if not self._com_initialized:
            pythoncom.CoInitialize()
            self._com_initialized = True

        if self._app is None:
            # 必须先加载类型库包装再 Dispatch, 顺序反了就只能拿到泛型 CDispatch
            self._early_binding = _ensure_early_binding()
            try:
                # 优先接管正在运行的实例, 避免另起进程抢占许可证
                self._app = win32com.client.GetActiveObject("SldWorks.Application")
            except pythoncom.com_error:
                self._app = win32com.client.Dispatch("SldWorks.Application")
            self._app = _wrap(self._app, "ISldWorks")
            # 设可见性纯属方便观察, 失败不影响任何功能 —— 早期绑定下这个属性的
            # setter 未必暴露, 不值得为它中断整个会话
            try:
                self._app.Visible = self.visible
            except Exception:  # noqa: BLE001
                pass

        visible = True
        try:
            visible = bool(self._app.Visible)
        except Exception:  # noqa: BLE001
            pass

        return {
            "revision": str(_prop(self._app, "RevisionNumber")),
            "install_dir": swc.find_sw_dir(),
            "early_binding": self._early_binding,
            "app_type": type(self._app).__name__,
            "visible": visible,
            "open_documents": len(self.list_open_documents()),
        }

    def release(self) -> None:
        """功能: 释放 COM 引用(不退出 SolidWorks 进程). 参数: 无. 返回值: None"""
        self._app = None
        if self._com_initialized:
            pythoncom.CoUninitialize()
            self._com_initialized = False

    @property
    def app(self) -> Any:
        """功能: 取 COM 应用对象, 未连接时自动连接. 参数: 无. 返回值: SldWorks.Application COM 对象"""
        if self._app is None:
            self.connect()
        return self._app

    # -- 查询 --------------------------------------------------------------

    def _iter_open_models(self) -> list[Any]:
        """
        功能: 取当前已打开的全部文档对象, 兼容多种 COM 派发方式.

        pywin32 的动态派发对 SolidWorks 的枚举接口支持并不一致: 有的机器上
        GetFirstDocument2 直接 AttributeError, 有的上 GetDocuments 是属性而非方法.
        因此按可靠性依次尝试三条路, 任意一条通了就用它 —— 与其为某台机器写死一种调法,
        不如让代码自己找到能走的那条.

        参数: 无
        返回值: list, 文档 COM 对象列表
        """
        # 路线一: GetDocuments 一次性返回数组, 最省事
        try:
            docs = _prop(self.app, "GetDocuments")
            if docs:
                return [_wrap(d, "IModelDoc2") for d in docs if d is not None]
            return []
        except (AttributeError, pythoncom.com_error):
            pass

        # 路线二: 链式枚举(GetFirstDocument2 -> GetNext)
        for starter in ("GetFirstDocument2", "GetFirstDocument"):
            try:
                model = _prop(self.app, starter)
            except (AttributeError, pythoncom.com_error):
                continue
            models = []
            # 加个上限防止 GetNext 因异常实现而死循环
            while model is not None and len(models) < 4096:
                models.append(_wrap(model, "IModelDoc2"))
                try:
                    model = _prop(model, "GetNext")
                except (AttributeError, pythoncom.com_error):
                    break
            return models

        # 路线三: 只能拿到当前活动文档
        try:
            active = self.app.ActiveDoc
            return [_wrap(active, "IModelDoc2")] if active is not None else []
        except (AttributeError, pythoncom.com_error):
            return []

    def list_open_documents(self) -> list[DocumentInfo]:
        """
        功能: 列出 SolidWorks 中当前已打开的所有文档(含用户自己打开的).
        参数: 无
        返回值: list[DocumentInfo]
        """
        docs: list[DocumentInfo] = []
        for model in self._iter_open_models():
            try:
                path = _prop(model, "GetPathName") or ""
                docs.append(
                    DocumentInfo(
                        title=_prop(model, "GetTitle"),
                        path=path,
                        doc_type=int(_prop(model, "GetType")),
                        opened_by_us=os.path.normcase(path) in self._opened_set(),
                    )
                )
            except pythoncom.com_error:
                pass
        return docs

    def _opened_set(self) -> set[str]:
        """功能: 本会话打开过的文档路径集合(规范化). 参数: 无. 返回值: set[str]"""
        return {os.path.normcase(p) for p in self._opened_paths}

    def get_step_options(self) -> dict[str, Any]:
        """
        功能: 读取当前 STEP 导出相关的用户选项.
        参数: 无
        返回值: dict, 含 ap / appearances / configuration_data / face_edge_props
        """
        app = self.app
        ap_raw = app.GetUserPreferenceIntegerValue(swc.get("swStepAP"))
        ap_map = {swc.get(name): value for value, name in STEP_AP_VALUES.items()}
        return {
            "ap_raw": int(ap_raw),
            "ap": ap_map.get(int(ap_raw)),
            "appearances": bool(
                app.GetUserPreferenceToggle(swc.get("swStepExportAppearances"))
            ),
            "configuration_data": bool(
                app.GetUserPreferenceToggle(swc.get("swStepExportConfigurationData"))
            ),
            "face_edge_props": bool(
                app.GetUserPreferenceToggle(swc.get("swStepExportFaceEdgeProps"))
            ),
        }

    def set_step_options(
        self,
        ap: int = 214,
        appearances: bool = True,
        face_edge_props: bool = False,
    ) -> dict[str, Any]:
        """
        功能: 设置 STEP 导出选项并回读校验.

        AP203 不携带颜色(现有整机 STEP 就是 AP203, 转出来全是灰模), AP214 才带外观,
        因此本管线固定使用 AP214 + 导出外观.

        参数:
            ap: STEP 应用协议, 可选 203 / 214 / 242
            appearances: 是否导出外观(颜色)
            face_edge_props: 是否导出面/边属性(体积大且本管线用不上, 默认关)
        返回值: dict, 回读后的实际选项; 若与期望不符会在 mismatch 字段中列出
        异常: ValueError, ap 取值非法时抛出
        """
        if ap not in STEP_AP_VALUES:
            raise ValueError(f"不支持的 STEP AP: {ap}; 可选 {sorted(STEP_AP_VALUES)}")

        app = self.app
        app.SetUserPreferenceIntegerValue(
            swc.get("swStepAP"), swc.get(STEP_AP_VALUES[ap])
        )
        app.SetUserPreferenceToggle(swc.get("swStepExportAppearances"), bool(appearances))
        app.SetUserPreferenceToggle(
            swc.get("swStepExportFaceEdgeProps"), bool(face_edge_props)
        )

        actual = self.get_step_options()
        mismatch = {}
        if actual["ap"] != ap:
            mismatch["ap"] = {"want": ap, "got": actual["ap"]}
        if actual["appearances"] != bool(appearances):
            mismatch["appearances"] = {"want": appearances, "got": actual["appearances"]}
        actual["mismatch"] = mismatch
        return actual

    # -- 打开 / 关闭 -------------------------------------------------------

    def open_document(
        self, path: str, lightweight: bool = False, read_only: bool = True
    ) -> dict[str, Any]:
        """
        功能: 以静默只读方式打开一个 SolidWorks 文档; 若已打开则直接复用.

        参数:
            path: 文档绝对路径(.SLDASM / .SLDPRT)
            lightweight: 是否轻量化打开. 轻量化打开快, 但导出 STEP 需要实体几何,
                         SolidWorks 会按需还原, 大装配体建议 False 以免中途弹窗
            read_only: 是否只读打开(默认 True, 保护用户设计文件)
        返回值: dict, 含 title / path / reused(是否复用已打开文档) / elapsed_s / errors / warnings
        异常: FileNotFoundError / RuntimeError
        """
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"文档不存在: {path}")

        ext = os.path.splitext(path)[1].lower()
        if ext not in DOC_TYPE_BY_EXT:
            raise ValueError(f"不支持的文档类型: {ext}")

        # 已经打开过就直接复用, 避免重复加载超大装配体.
        # 刻意不调 ActivateDoc3: 激活只是把窗口切到前台, 对读数据毫无必要,
        # 反而会因为 out 参数在早期/后期绑定下传法不同而平添一个失败点.
        existing = self._find_open_model(path)
        if existing is not None:
            return {
                "title": _prop(existing, "GetTitle"),
                "path": path,
                "reused": True,
                "elapsed_s": 0.0,
                "errors": 0,
                "warnings": 0,
            }

        options = swc.get("swOpenDocOptions_Silent")
        if read_only:
            options |= swc.get("swOpenDocOptions_ReadOnly")
        if lightweight:
            options |= swc.get("swOpenDocOptions_LoadLightweight")

        started = time.time()
        model, errors, warnings = _call_with_outs(
            self.app, "OpenDoc6", path, swc.get(DOC_TYPE_BY_EXT[ext]), options, "", out_count=2
        )
        elapsed = time.time() - started

        if model is None:
            raise RuntimeError(f"打开失败: {path}; errors={errors} warnings={warnings}")

        self._opened_paths.append(path)
        # 留住这个对象 —— 它是唯一一份带完整类型信息的文档句柄
        self._models[os.path.normcase(path)] = _wrap(model, "IModelDoc2")
        return {
            "title": _prop(model, "GetTitle"),
            "path": path,
            "reused": False,
            "elapsed_s": round(elapsed, 1),
            "errors": errors,
            "warnings": warnings,
        }

    def _find_open_model(self, path: str) -> Any:
        """功能: 在已打开文档中按路径查找. 参数: path 绝对路径. 返回值: COM 模型对象或 None"""
        target = os.path.normcase(os.path.abspath(path))

        # 一等来源: 本会话打开时留下的对象, 它是带完整类型信息的
        cached = self._models.get(target)
        if cached is not None:
            return cached

        # 二等来源: 活动文档. ISldWorks.ActiveDoc 在类型库里有声明返回类型,
        # 所以早期绑定下也是正确包装的
        try:
            active = self.app.ActiveDoc
            if active is not None:
                active = _wrap(active, "IModelDoc2")
                if os.path.normcase(_prop(active, "GetPathName") or "") == target:
                    self._models[target] = active
                    return active
        except (AttributeError, pythoncom.com_error):
            pass

        # 末等来源: 枚举出来的对象可能缺类型信息, 只够读 GetTitle/GetPathName 这类
        # 基础成员; 文档级的高级方法在它上面多半调不通
        for model in self._iter_open_models():
            try:
                if os.path.normcase(_prop(model, "GetPathName") or "") == target:
                    return model
            except pythoncom.com_error:
                continue
        return None

    def close_document(self, path: str) -> bool:
        """
        功能: 关闭指定文档(不保存). 仅当该文档是本会话打开的才会真正关闭.
        参数:
            path: 文档绝对路径
        返回值: bool, True 表示已关闭; False 表示不是本会话打开的, 出于安全未关闭
        """
        path = os.path.abspath(path)
        if os.path.normcase(path) not in self._opened_set():
            return False
        self.app.CloseDoc(os.path.basename(path))
        self._opened_paths = [
            p for p in self._opened_paths if os.path.normcase(p) != os.path.normcase(path)
        ]
        # 文档已关, 缓存里的句柄随之失效, 留着只会在下次误用时抛 COM 异常
        self._models.pop(os.path.normcase(path), None)
        return True

    def close_all_opened(self) -> list[str]:
        """
        功能: 关闭本会话打开过的全部文档(不保存), 用户原本开着的不动.
        参数: 无
        返回值: list[str], 实际关闭的路径列表
        """
        closed: list[str] = []
        for path in list(self._opened_paths):
            try:
                if self.close_document(path):
                    closed.append(path)
            except pythoncom.com_error:
                pass
        return closed

    # -- 装配结构 ----------------------------------------------------------

    def list_components(self, path: str | None = None, max_depth: int = 1) -> list[dict[str, Any]]:
        """
        功能: 列出装配体的组件树(默认只列顶层), 用于确定按模块导出的切分点.

        参数:
            path: 装配体路径; 为 None 时使用当前活动文档
            max_depth: 递归深度, 1 表示只列顶层子装配/零件
        返回值: list[dict], 每项含 name / path / depth / is_assembly / suppressed / visible / children_count
        """
        model = self._find_open_model(path) if path else self.app.ActiveDoc
        if model is None:
            raise RuntimeError("目标装配体未打开; 请先调用 open_document")

        config = _wrap(_prop(model, "GetActiveConfiguration"), "IConfiguration")
        root = _wrap(_prop(config, "GetRootComponent3", True), "IComponent2")
        result: list[dict[str, Any]] = []

        def walk(component: Any, depth: int) -> None:
            children = _prop(component, "GetChildren")
            if not children:
                return
            for raw in children:
                child = _wrap(raw, "IComponent2")
                try:
                    child_path = _prop(child, "GetPathName") or ""
                    kids = _prop(child, "GetChildren")
                    result.append(
                        {
                            "name": child.Name2,
                            "path": child_path,
                            "depth": depth,
                            "is_assembly": child_path.lower().endswith(".sldasm"),
                            "suppressed": int(_prop(child, "GetSuppression")),
                            "visible": int(child.Visible),
                            "children_count": len(kids) if kids else 0,
                        }
                    )
                except pythoncom.com_error:
                    continue
                if depth < max_depth:
                    walk(child, depth + 1)

        walk(root, 1)
        return result

    def get_bounding_box(self, path: str | None = None) -> dict:
        """
        功能: 取模型包围盒(米), 用于确认整机尺寸是否合理.
        参数:
            path: 文档路径; None 表示活动文档
        返回值: dict, 含 x_min..z_max 及 size_x/size_y/size_z(单位 mm);
                取不到时返回 {"error": ...} 而不抛异常(包围盒是锦上添花,
                不能把 list_components 这类主功能一起拖死)
        """
        model = self._find_open_model(path) if path else self.app.ActiveDoc
        if model is None:
            raise RuntimeError("目标文档未打开")
        # 2025 型库的 IModelDocExtension 没有 GetBox; 正确入口按文档类型分派:
        # 装配体 IAssemblyDoc::GetBox(0), 零件 IPartDoc::GetPartBox(True)
        doc_model = _wrap(model, "IModelDoc2")
        box = None
        for iface, member, args in (
            ("IAssemblyDoc", "GetBox", (0,)),
            ("IPartDoc", "GetPartBox", (True,)),
        ):
            try:
                box = _prop(_wrap(doc_model, iface, force=True), member, *args)
            except Exception:  # noqa: BLE001
                continue
            if box:
                break
        if not box:
            return {"error": "包围盒不可用(文档类型不支持或型库缺成员)"}
        values = [float(v) * 1000.0 for v in box]  # SolidWorks 内部单位为米, 统一换成 mm
        keys = ["x_min", "y_min", "z_min", "x_max", "y_max", "z_max"]
        result = dict(zip(keys, values))
        result["size_x"] = result["x_max"] - result["x_min"]
        result["size_y"] = result["y_max"] - result["y_min"]
        result["size_z"] = result["z_max"] - result["z_min"]
        return {k: round(v, 2) for k, v in result.items()}

    # -- 导出 --------------------------------------------------------------

    def activate_document(self, path: str) -> bool:
        """
        功能: 把某个已打开的文档切换为**当前激活文档**.

        读数据不需要激活(所以 open_document 刻意不做), 但 XR/glTF 导出器是个 UI 插件,
        它导的是"当前激活的那个文档" —— 不激活就静默地什么都不产出.

        参数:
            path: 文档绝对路径
        返回值: bool, 是否激活成功
        """
        model = self._find_open_model(path)
        if model is None:
            return False
        try:
            title = str(_prop(model, "GetTitle") or "")
        except Exception:  # noqa: BLE001
            title = ""
        title = title or os.path.basename(path)

        try:
            _call_with_outs(
                self.app,
                "ActivateDoc3",
                title,
                False,  # UseUserPreferences
                swc.get("swRebuildActiveDoc", 2),
                out_count=1,
            )
        except Exception:  # noqa: BLE001 - 激活失败让调用方按产物有无来判断
            return False
        return True

    def get_addin(
        self, clsid: str, interface: str | None = None, dll_path: str | None = None
    ) -> Any:
        """
        功能: 取到一个 SolidWorks 插件对象; 未加载时先按需加载.

        插件(如自带的 XR/glTF 导出器)不是 ISldWorks 的成员, 只能经 GetAddInObject 按 CLSID 要,
        而且**必须已加载**才拿得到. XR 导出器虽然注册了(HKLM\\SOLIDWORKS\\Addins), 但用户侧的
        启动开关(HKCU\\SOLIDWORKS\\AddInsStartup)是 0, 不会随 SolidWorks 启动 ——
        所以这里在拿不到时用 LoadAddIn 现场加载一次.

        参数:
            clsid: 插件 CLSID, 形如 "{87B557C0-...}"
            interface: 可选的目标接口名, 传了就再包一层早期绑定
            dll_path: 插件 DLL 路径; 留空则从注册表 CLSID\\InprocServer32 里查
        返回值: Any, 插件的 IDispatch; 拿不到返回 None
        """
        addin = _prop(self.app, "GetAddInObject", clsid)
        if addin is None:
            path = dll_path or _addin_dll_path(clsid)
            if path and os.path.isfile(path):
                try:
                    _prop(self.app, "LoadAddIn", path)
                except Exception:  # noqa: BLE001 - 加载失败下面再取一次也是 None, 不必中断
                    pass
                addin = _prop(self.app, "GetAddInObject", clsid)
        if addin is None:
            return None
        if interface:
            return _wrap(addin, interface)
        return addin

    def export_gltf(
        self,
        input_path: str,
        output_path: str,
        keep_open: bool = False,
        lightweight: bool = False,
    ) -> dict[str, Any]:
        """
        功能: 用 SolidWorks 自带的 XR 导出器把装配体/零件直接导成 glTF/GLB.

        为什么比走 STEP 好: STEP(AP203)会丢掉装配实例名、中文名、材质与颜色、配合关系,
        逼得 01 步要顺 `NAUO→PRODUCT` 链回填真名、另开 COM 通道逐零件读材质;
        而 glTF 原生就带节点名、层级、变换与 PBR 外观, 还省掉 02 步 11 分钟的 OCCT 转换.

        走的是**常规 SaveAs 通道**, 不是插件自己的 GLTF_FileSave_Assembly/Part ——
        后者虽然在接口上暴露着, 但实测各种参数写法都是 0.2 秒空返回、不产出文件
        (它的 EnablePMP() 返回 0, 说明插件认为自己当前不可用, 应是缺少 UI 上下文).
        插件真正的作用是把 .glb 注册成一种 SaveAs 目标格式, 所以必须先确保它已加载.

        实测要点:
            * **只有 .glb 可用**; .gltf 会静默不产出文件(ok=True 但没有东西写出来)
            * 产物自带: 原始中文节点名、带名字的 PBR 材质、Solidworks_custom_properties 扩展
            * 几何是 KHR_draco_mesh_compression 压缩的, 下游读取方须支持 Draco

        参数:
            input_path: 源文件绝对路径(.SLDASM / .SLDPRT)
            output_path: 目标 .glb 绝对路径; 目录不存在会自动创建
            keep_open: 导出后是否保留文档打开
            lightweight: 是否轻量化打开(轻量化组件可能导不出几何, 默认关)
        返回值: dict, 含 output / size_mb / elapsed_s / open_info
        异常: RuntimeError, 插件拿不到、扩展名不对或文件没产出时抛出
        """
        output_path = os.path.abspath(output_path)
        if not output_path.lower().endswith(".glb"):
            raise RuntimeError(
                f"glTF 导出只支持 .glb: {output_path}"
                "(.gltf 在本环境下 SaveAs 返回成功却不产出文件)"
            )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 插件是 .glb 这个 SaveAs 格式的处理器, 没加载 SaveAs 就不认这个扩展名
        if self.get_addin(XR_EXPORTER_CLSID, "ISWXRExporter") is None:
            raise RuntimeError(
                f"取不到 XR 导出器插件 {XR_EXPORTER_CLSID}; "
                "它已在 HKLM\\SOLIDWORKS\\Addins 注册但默认不随启动加载, "
                "本应由 get_addin 自动 LoadAddIn —— 检查 SWXRExporter.dll 是否存在"
            )

        open_info = self.open_document(input_path, lightweight=lightweight)
        activated = self.activate_document(input_path)

        if os.path.isfile(output_path):
            # 靠"文件有没有被重新写出来"判断成败, 所以先删干净
            os.remove(output_path)

        model = self._find_open_model(input_path)
        if model is None:
            raise RuntimeError(f"打开后仍未找到文档: {input_path}")

        started = time.time()
        ok, errors, warnings = _call_with_outs(
            model.Extension,
            "SaveAs",
            output_path,
            0,  # swSaveAsCurrentVersion
            swc.get("swSaveAsOptions_Silent") | swc.get("swSaveAsOptions_Copy"),
            None,
            out_count=2,
        )
        elapsed = time.time() - started

        if not keep_open:
            self.close_document(input_path)

        if not ok or not os.path.isfile(output_path):
            raise RuntimeError(
                f"glTF 导出未产出文件: {input_path} -> {output_path} "
                f"(ok={ok} errors={errors} warnings={warnings}, "
                f"耗时 {round(elapsed, 1)}s, 文档已激活={activated})"
            )

        return {
            "input": os.path.abspath(input_path),
            "output": output_path,
            "size_mb": round(os.path.getsize(output_path) / 1024 / 1024, 2),
            "elapsed_s": round(elapsed, 1),
            "errors": int(errors),
            "warnings": int(warnings),
            "activated": activated,
            "open_info": open_info,
        }

    def export_step(
        self,
        input_path: str,
        output_path: str,
        ap: int = 214,
        appearances: bool = True,
        keep_open: bool = False,
        lightweight: bool = False,
    ) -> dict[str, Any]:
        """
        功能: 把一个装配体/零件导出为 STEP 文件. 这是资产管线 Step A 的入口.

        参数:
            input_path: 源文件绝对路径(.SLDASM / .SLDPRT)
            output_path: 目标 STEP 绝对路径(.STEP/.step); 目录不存在会自动创建
            ap: STEP 应用协议, 默认 214(带颜色)
            appearances: 是否导出外观
            keep_open: 导出后是否保留文档打开状态(连续导出多个模块时置 True 更快)
            lightweight: 是否轻量化打开源文档
        返回值: dict, 含 output / size_mb / elapsed_s / step_options / open_info
        异常: RuntimeError, SolidWorks 返回失败时抛出
        """
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        step_options = self.set_step_options(ap=ap, appearances=appearances)
        open_info = self.open_document(input_path, lightweight=lightweight)

        model = self._find_open_model(input_path)
        if model is None:
            raise RuntimeError(f"打开后仍未找到文档: {input_path}")

        started = time.time()
        ok, errors, warnings = _call_with_outs(
            model.Extension,
            "SaveAs",
            output_path,
            0,  # swSaveAsCurrentVersion
            swc.get("swSaveAsOptions_Silent") | swc.get("swSaveAsOptions_Copy"),
            None,
            out_count=2,
        )
        elapsed = time.time() - started

        if not keep_open:
            self.close_document(input_path)

        if not ok or not os.path.isfile(output_path):
            raise RuntimeError(
                f"STEP 导出失败: {input_path} -> {output_path}; "
                f"errors={errors} warnings={warnings}"
            )

        return {
            "input": os.path.abspath(input_path),
            "output": output_path,
            "size_mb": round(os.path.getsize(output_path) / 1024 / 1024, 2),
            "elapsed_s": round(elapsed, 1),
            "errors": int(errors),
            "warnings": int(warnings),
            "step_options": step_options,
            "open_info": open_info,
        }

    def screenshot(
        self,
        output_path: str,
        path: str | None = None,
        view: str = "*Isometric",
        width: int = 1600,
        height: int = 1200,
    ) -> dict[str, Any]:
        """
        功能: 对当前(或指定)文档截图, 供 AI 与用户目视核对模型是否正确.

        参数:
            output_path: 输出图片绝对路径(.bmp/.png, SolidWorks 按扩展名决定格式)
            path: 目标文档路径; None 表示活动文档
            view: 命名视图, 如 "*Isometric" / "*Front" / "*Top"
            width / height: 图片像素尺寸
        返回值: dict, 含 output / exists / size_kb
        """
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        model = self._find_open_model(path) if path else self.app.ActiveDoc
        if model is None:
            raise RuntimeError("目标文档未打开")

        model.ShowNamedView2(view, -1)
        model.ViewZoomtofit2()
        model.SaveBMP(output_path, width, height)

        exists = os.path.isfile(output_path)
        return {
            "output": output_path,
            "exists": exists,
            "size_kb": round(os.path.getsize(output_path) / 1024, 1) if exists else 0,
        }


# ---------------------------------------------------------------------------
# 命令行入口 —— 便于在没有 MCP 的场景下直接跑, 也便于把操作固化进管线脚本
# ---------------------------------------------------------------------------


def _cmd_info(args: argparse.Namespace) -> dict[str, Any]:
    """功能: info 子命令, 输出连接信息/已开文档/STEP 选项. 参数: args. 返回值: dict"""
    with SolidWorksSession() as sw:
        return {
            "connection": sw.connect(),
            "open_documents": [d.to_dict() for d in sw.list_open_documents()],
            "step_options": sw.get_step_options(),
        }


def _cmd_components(args: argparse.Namespace) -> dict[str, Any]:
    """功能: components 子命令, 列出装配体顶层组件. 参数: args. 返回值: dict"""
    with SolidWorksSession() as sw:
        sw.open_document(args.input, lightweight=args.lightweight)
        components = sw.list_components(args.input, max_depth=args.depth)
        box = sw.get_bounding_box(args.input)
        if not args.keep_open:
            sw.close_document(args.input)
        return {"input": args.input, "bounding_box_mm": box, "components": components}


def _cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    """功能: export 子命令, 导出单个 STEP. 参数: args. 返回值: dict"""
    with SolidWorksSession() as sw:
        return sw.export_step(
            args.input,
            args.output,
            ap=args.ap,
            appearances=not args.no_appearances,
            keep_open=args.keep_open,
            lightweight=args.lightweight,
        )


def _cmd_screenshot(args: argparse.Namespace) -> dict[str, Any]:
    """功能: screenshot 子命令. 参数: args. 返回值: dict"""
    with SolidWorksSession() as sw:
        sw.open_document(args.input, lightweight=True)
        result = sw.screenshot(args.output, path=args.input, view=args.view)
        if not args.keep_open:
            sw.close_document(args.input)
        return result


def main() -> None:
    """功能: 命令行主入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="SolidWorks 自动化导出工具")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="显示连接信息与当前 STEP 选项").set_defaults(func=_cmd_info)

    p_comp = sub.add_parser("components", help="列出装配体组件树")
    p_comp.add_argument("--input", required=True)
    p_comp.add_argument("--depth", type=int, default=1)
    p_comp.add_argument("--lightweight", action="store_true")
    p_comp.add_argument("--keep-open", action="store_true")
    p_comp.set_defaults(func=_cmd_components)

    p_exp = sub.add_parser("export", help="导出 STEP")
    p_exp.add_argument("--input", required=True)
    p_exp.add_argument("--output", required=True)
    p_exp.add_argument("--ap", type=int, default=214, choices=[203, 214, 242])
    p_exp.add_argument("--no-appearances", action="store_true")
    p_exp.add_argument("--lightweight", action="store_true")
    p_exp.add_argument("--keep-open", action="store_true")
    p_exp.set_defaults(func=_cmd_export)

    p_shot = sub.add_parser("screenshot", help="对模型截图")
    p_shot.add_argument("--input", required=True)
    p_shot.add_argument("--output", required=True)
    p_shot.add_argument("--view", default="*Isometric")
    p_shot.add_argument("--keep-open", action="store_true")
    p_shot.set_defaults(func=_cmd_screenshot)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
