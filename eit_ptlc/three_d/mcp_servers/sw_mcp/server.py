"""
功能: SolidWorks MCP 服务器. 把 sw_core 的自动化能力暴露成 MCP 工具,
      让 AI 助手可以直接打开装配体、查看结构、导出 STEP、截图, 而无需人工操作 SolidWorks.

线程模型(关键):
    COM 是有单元(apartment)概念的: 在 A 线程创建的 COM 对象不能直接在 B 线程使用,
    否则会报 RPC_E_WRONG_THREAD 之类的错误. 而 MCP 服务器基于 asyncio, 工具函数可能
    在不同的线程上被调用. 因此本模块把所有 COM 操作固定在一个专用工作线程里执行,
    工具函数只负责把请求投递进队列并等待结果.

安全约束(与 sw_core 一致, 在此重申):
    - 一律只读打开用户的设计文件, 绝不保存原始 SLDASM/SLDPRT;
    - 只关闭本会话自己打开的文档, 用户原本开着的文档不动;
    - 导出只写入 three_d/exports 目录.

启动:
    python server.py                 # 由 MCP 客户端以 stdio 方式拉起
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
from typing import Any, Callable

# 允许以脚本方式直接运行(MCP 客户端通常不会设置 PYTHONPATH)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pythoncom  # noqa: E402
# MCP Python SDK 2.x 把高层服务器类改名为 MCPServer(1.x 时叫 FastMCP), 装饰器用法不变
from mcp.server.mcpserver import MCPServer  # noqa: E402

from sw_core import SolidWorksSession  # noqa: E402

mcp = MCPServer("solidworks")

# 默认导出目录: three_d/exports
DEFAULT_EXPORT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "exports")
)


class ComWorker:
    """
    功能: 单线程 COM 执行器. 所有 SolidWorks 调用都在这个线程里串行执行.

    串行化同时带来一个额外好处: SolidWorks 本身不是线程安全的, 串行执行天然避免了
    多个工具调用同时操作同一个装配体导致的状态错乱.
    """

    def __init__(self):
        """功能: 启动工作线程. 参数: 无. 返回值: None"""
        self._requests: queue.Queue = queue.Queue()
        self._session: SolidWorksSession | None = None
        self._thread = threading.Thread(target=self._run, name="sw-com-worker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """功能: 工作线程主循环. 参数: 无. 返回值: None"""
        pythoncom.CoInitialize()
        try:
            while True:
                job = self._requests.get()
                if job is None:
                    break
                func, result_queue = job
                try:
                    if self._session is None:
                        self._session = SolidWorksSession()
                        self._session.connect()
                    result_queue.put(("ok", func(self._session)))
                except Exception as exc:  # noqa: BLE001 - 需要把任何异常回传给调用方
                    result_queue.put(("error", f"{exc}\n{traceback.format_exc()}"))
        finally:
            if self._session is not None:
                try:
                    self._session.close_all_opened()
                except Exception:  # noqa: BLE001 - 清理阶段的异常不应掩盖真正的错误
                    pass
            pythoncom.CoUninitialize()

    def call(self, func: Callable[[SolidWorksSession], Any], timeout: float = 3600.0) -> Any:
        """
        功能: 把一个操作投递到 COM 线程执行并等待结果.
        参数:
            func: 接收 SolidWorksSession 的可调用对象
            timeout: 超时秒数(打开超大装配体可能耗时数分钟, 默认给足)
        返回值: Any, func 的返回值
        异常: RuntimeError, 执行失败或超时
        """
        result_queue: queue.Queue = queue.Queue()
        self._requests.put((func, result_queue))
        try:
            status, payload = result_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError(f"SolidWorks 操作超时({timeout}s); 可能有模态对话框在等待响应") from exc
        if status == "error":
            raise RuntimeError(payload)
        return payload


_worker = ComWorker()


def _ok(payload: Any) -> str:
    """
    功能: 把结果序列化为 JSON 字符串返回给 MCP 客户端.
    参数:
        payload: 任意可序列化对象
    返回值: str, JSON 文本
    """
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fail(message: str) -> str:
    """
    功能: 构造统一的错误返回.
    参数:
        message: 错误说明
    返回值: str, JSON 文本
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# MCP 工具
# ---------------------------------------------------------------------------


@mcp.tool()
def sw_info() -> str:
    """
    查询 SolidWorks 连接状态: 版本号、安装目录、当前已打开的文档列表、当前 STEP 导出选项.

    在做任何导出之前应先调用本工具, 确认 SolidWorks 可用且没有别的任务正占用它
    (若 open_documents 里有带未保存标记的文档, 说明有人/别的程序正在使用).
    """
    try:
        return _ok(
            _worker.call(
                lambda sw: {
                    "ok": True,
                    "connection": sw.connect(),
                    "open_documents": [d.to_dict() for d in sw.list_open_documents()],
                    "step_options": sw.get_step_options(),
                }
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_list_components(input_path: str, depth: int = 1, keep_open: bool = True) -> str:
    """
    列出装配体的组件树, 用于确定"按模块导出"的切分点.

    参数:
        input_path: 装配体绝对路径(.SLDASM)
        depth: 递归深度, 1 表示只列顶层子装配/零件
        keep_open: 列完后是否保持文档打开(连续操作同一装配体时置 True 可省去重复加载)
    """
    try:
        def job(sw: SolidWorksSession) -> dict:
            """功能: 在 COM 线程中执行组件列举. 参数: sw 会话. 返回值: dict"""
            sw.open_document(input_path)
            result = {
                "ok": True,
                "input": input_path,
                "bounding_box_mm": sw.get_bounding_box(input_path),
                "components": sw.list_components(input_path, max_depth=depth),
            }
            if not keep_open:
                sw.close_document(input_path)
            return result

        return _ok(_worker.call(job))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_export_gltf(input_path: str, output_name: str = "", keep_open: bool = False) -> str:
    """
    用 SolidWorks 自带的 XR 导出器把装配体/零件直接导成 GLB, 写入 three_d/exports 目录.

    **这是资产管线的首选入口**, 比走 STEP 少丢一大截信息(实测对比):

        走 STEP(AP203)          原生 GLB
        节点名全是 NAUO1234       真实装配实例名, 如 `电磁阀总装-2`(带 -N 后缀区分多实例)
        中文变裸 cp936 字节        中文原样保留
        材质 0 个                 具名 PBR 材质, 如 `polished steel`
        自定义属性丢失             随 Solidworks_custom_properties 扩展带出
        OCCT 转换 11 分钟          子装配 2.1 秒

    因此走这条路可以跳过 01(命名回填) 与 02(STEP→GLB) 两步.

    实测要点(踩过的坑):
        * **只支持 .glb**; .gltf 会返回成功却不产出任何文件
        * 插件默认不随 SolidWorks 启动, 由 get_addin 自动 LoadAddIn
        * 插件自带的 GLTF_FileSave_Assembly/Part 是死的(空返回不产出), 真正入口是常规 SaveAs
        * 几何是 Draco 压缩的; Blender 能直接读(已验证层级/材质/单位全对)
        * 产物含一个名为 `current` 的相机/视图节点, 下游需删掉

    参数:
        input_path: 源文件绝对路径(.SLDASM / .SLDPRT)
        output_name: 输出文件名(不含目录, 需以 .glb 结尾); 留空则用源文件名
        keep_open: 导出后是否保持源文档打开(连续导出多个模块时置 True 更快)
    """
    try:
        name = output_name or (os.path.splitext(os.path.basename(input_path))[0] + ".glb")
        if not name.lower().endswith(".glb"):
            name += ".glb"
        output_path = os.path.join(DEFAULT_EXPORT_DIR, name)

        return _ok(
            _worker.call(
                lambda sw: {
                    "ok": True,
                    **sw.export_gltf(input_path, output_path, keep_open=keep_open),
                }
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_export_step(
    input_path: str,
    output_name: str = "",
    ap: int = 214,
    appearances: bool = True,
    keep_open: bool = False,
) -> str:
    """
    把装配体或零件导出为 STEP 文件, 写入 three_d/exports 目录.

    这是三维资产管线的入口. 默认使用 AP214 并导出外观(颜色) —— AP203 不携带颜色,
    转换出的模型会是一片均匀灰模.

    参数:
        input_path: 源文件绝对路径(.SLDASM / .SLDPRT)
        output_name: 输出文件名(不含目录); 留空则用源文件名. 建议使用纯 ASCII 文件名,
                     因为 OCCT 在 Windows 上无法打开含中文的路径
        ap: STEP 应用协议, 214(推荐) / 203 / 242
        appearances: 是否导出外观颜色
        keep_open: 导出后是否保持源文档打开(连续导出多个模块时置 True 更快)
    """
    try:
        name = output_name or (os.path.splitext(os.path.basename(input_path))[0] + ".STEP")
        if not name.lower().endswith((".step", ".stp")):
            name += ".STEP"
        output_path = os.path.join(DEFAULT_EXPORT_DIR, name)

        return _ok(
            _worker.call(
                lambda sw: {
                    "ok": True,
                    **sw.export_step(
                        input_path,
                        output_path,
                        ap=ap,
                        appearances=appearances,
                        keep_open=keep_open,
                    ),
                }
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_export_modules(input_path: str, component_names: list[str], ap: int = 214) -> str:
    """
    按模块批量导出: 对装配体中指定的若干子装配, 各自导出一个 STEP 文件.

    分模块导出的价值在于让三维模型天然带有"工位"边界, 后续 Blender 侧无需再靠
    包围盒猜测哪个零件属于哪个工位.

    参数:
        input_path: 顶层装配体路径, 用于解析各子装配的实际文件路径
        component_names: 子装配名列表(取自 sw_list_components 的 name 字段)
        ap: STEP 应用协议
    """
    try:
        def job(sw: SolidWorksSession) -> dict:
            """功能: 在 COM 线程中批量导出模块. 参数: sw 会话. 返回值: dict"""
            sw.open_document(input_path)
            components = sw.list_components(input_path, max_depth=1)
            by_name = {c["name"]: c for c in components}

            results = []
            for name in component_names:
                component = by_name.get(name)
                if component is None or not component["path"]:
                    results.append({"name": name, "ok": False, "error": "未找到该组件或其路径为空"})
                    continue
                stem = os.path.splitext(os.path.basename(component["path"]))[0]
                # 文件名只保留 ASCII 可打印字符, 避免 OCCT 打不开中文路径
                safe = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in stem)
                output_path = os.path.join(DEFAULT_EXPORT_DIR, f"{safe}.STEP")
                try:
                    info = sw.export_step(component["path"], output_path, ap=ap, keep_open=False)
                    results.append({"name": name, "ok": True, **info})
                except Exception as exc:  # noqa: BLE001
                    results.append({"name": name, "ok": False, "error": str(exc)})
            return {"ok": True, "exported": results}

        return _ok(_worker.call(job))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_screenshot(input_path: str, output_name: str = "", view: str = "*Isometric") -> str:
    """
    对模型截图, 便于 AI 与用户目视核对导出的是不是预期的那台设备/模块.

    参数:
        input_path: 文档绝对路径
        output_name: 输出图片名(不含目录), 留空则用源文件名; 扩展名决定格式(.bmp/.png)
        view: 命名视图, 可选 *Isometric / *Front / *Back / *Left / *Right / *Top / *Bottom
    """
    try:
        name = output_name or (os.path.splitext(os.path.basename(input_path))[0] + ".png")
        output_path = os.path.join(DEFAULT_EXPORT_DIR, "screenshots", name)

        def job(sw: SolidWorksSession) -> dict:
            """功能: 在 COM 线程中截图. 参数: sw 会话. 返回值: dict"""
            sw.open_document(input_path, lightweight=True)
            return {"ok": True, **sw.screenshot(output_path, path=input_path, view=view)}

        return _ok(_worker.call(job))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_extract_materials(
    input_path: str = "", limit: int = 0, resume: bool = True, skip: str = ""
) -> str:
    """
    读取整机每个零件在 SolidWorks 里的材质名与外观颜色, 产出 work/part_colors.json.

    这是"把 CAD 里真实的材质区分映射进三维演示"的取数入口. 产物交给
    pipeline/build_materials.py, 经 material_semantics.yaml 转成 materials.yaml.

    实现上有三处必须照办, 否则不是拿不到数据就是跑不完(详见 docs/CLAUDE.md 第 16~18 条):
      * 材质在**零件**上, 不在组件上 —— IComponent2 的 MaterialPropertyValues 只返回
        组件级覆盖, 整机 1544 个组件里只有 3 个有;
      * 大装配默认轻量化载入, 必须先 ResolveAllLightWeightComponents 批量解析,
        否则逐个零件冷开要 34.9 秒, 749 个跑 7.3 小时;
      * 绝不能用 IAssemblyDoc::GetComponents 取全量组件, 该调用在本装配上会自旋不返回.

    另外 SolidWorks 会在某些组件上自旋不返回, 因此本工具每读 50 个零件就增量落盘, 并把
    "正在读哪个"写进 work/part_colors.trace.log —— 卡住时那份日志的最后一行就是元凶,
    用 skip 绕开后配合 resume 续跑即可.

    参数:
        input_path: 装配体绝对路径; 留空则用整机总装
        limit: 只处理前 N 个组件(用于小样本量成本), 0 表示全量
        resume: 是否复用 part_colors.json 里已取到的零件, 只补缺失的
        skip: 要跳过的零件路径片段, 逗号分隔
    """
    try:
        import extract_part_colors as extractor

        target = input_path or extractor.DEFAULT_ASM
        skip_parts = tuple(s.strip() for s in skip.split(",") if s.strip())

        def job(sw: SolidWorksSession) -> dict:
            """功能: 在 COM 线程中遍历取材质. 参数: sw 会话. 返回值: dict"""
            result = extractor.collect(
                sw, target, limit=limit, resume=resume, skip=skip_parts
            )
            extractor.save(result)
            return {"ok": True, **extractor.summary_of(result)}

        return _ok(_worker.call(job))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def sw_close_opened() -> str:
    """
    关闭本会话打开过的全部文档(不保存). 用户原本就开着的文档不会被动到.

    长时间批量导出后调用本工具释放 SolidWorks 的内存.
    """
    try:
        return _ok(_worker.call(lambda sw: {"ok": True, "closed": sw.close_all_opened()}))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


if __name__ == "__main__":
    mcp.run()
