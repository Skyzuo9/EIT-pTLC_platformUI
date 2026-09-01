"""
功能: 从 SolidWorks 自带的 swconst.tlb 类型库中读取全部枚举常量, 避免在代码里硬编码魔数.

SolidWorks 的 API 常量分散在数百个枚举里(swDocumentTypes_e / swOpenDocOptions_e /
swUserPreferenceIntegerValue_e 等), 不同版本取值可能变化. 直接读类型库是唯一可靠的做法.

参数: 无(模块级函数见下)
返回值: 见各函数说明
"""

from __future__ import annotations

import functools
import glob
import os

import pythoncom

# 常见的 SolidWorks 安装目录, 按优先级排列; 也可通过环境变量 SW_INSTALL_DIR 覆盖
_DEFAULT_SEARCH_GLOBS = (
    r"D:\sw*\SOLIDWORKS",
    r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    r"C:\Program Files\SolidWorks Corp\SolidWorks",
    r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
)


def find_sw_dir() -> str:
    """
    功能: 定位 SolidWorks 安装目录(含 swconst.tlb 的那一层).
    参数: 无
    返回值: str, 安装目录绝对路径
    异常: FileNotFoundError, 未找到时抛出
    """
    env_dir = os.environ.get("SW_INSTALL_DIR")
    if env_dir and os.path.isfile(os.path.join(env_dir, "swconst.tlb")):
        return env_dir

    # 优先使用注册表里 COM 服务器登记的真实路径
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID") as key:
            clsid = winreg.QueryValueEx(key, "")[0]
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32"
        ) as key:
            exe = winreg.QueryValueEx(key, "")[0].strip('"')
        candidate = os.path.dirname(exe)
        if os.path.isfile(os.path.join(candidate, "swconst.tlb")):
            return candidate
    except OSError:
        pass

    for pattern in _DEFAULT_SEARCH_GLOBS:
        for candidate in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(os.path.join(candidate, "swconst.tlb")):
                return candidate

    raise FileNotFoundError(
        "未找到 SolidWorks 安装目录; 请设置环境变量 SW_INSTALL_DIR 指向含 swconst.tlb 的目录"
    )


@functools.lru_cache(maxsize=1)
def load_constants() -> dict[str, int]:
    """
    功能: 加载 swconst.tlb 中所有枚举成员, 展平成 {常量名: 整数值} 字典.
    参数: 无
    返回值: dict[str, int], 例如 {"swDocASSEMBLY": 2, "swStepAP": 195, ...}
    """
    tlb_path = os.path.join(find_sw_dir(), "swconst.tlb")
    typelib = pythoncom.LoadTypeLib(tlb_path)

    constants: dict[str, int] = {}
    for index in range(typelib.GetTypeInfoCount()):
        # TKIND_ENUM == 0; 只关心枚举类型
        if typelib.GetTypeInfoType(index) != pythoncom.TKIND_ENUM:
            continue
        type_info = typelib.GetTypeInfo(index)
        attr = type_info.GetTypeAttr()
        for var_index in range(attr.cVars):
            var_desc = type_info.GetVarDesc(var_index)
            name = type_info.GetNames(var_desc.memid)[0]
            value = var_desc.value
            if isinstance(value, int):
                constants[name] = value
    return constants


def get(name: str, default: int | None = None) -> int:
    """
    功能: 按名称取一个 SolidWorks 常量.
    参数:
        name: 常量名, 如 "swDocASSEMBLY"
        default: 找不到时的回退值; 为 None 时找不到会抛 KeyError
    返回值: int, 常量值
    """
    constants = load_constants()
    if name in constants:
        return constants[name]
    if default is not None:
        return default
    raise KeyError(f"swconst.tlb 中不存在常量: {name}")


def search(keyword: str) -> dict[str, int]:
    """
    功能: 按关键字(不区分大小写)模糊查找常量, 用于排查 API 选项名.
    参数:
        keyword: 关键字子串, 如 "step"
    返回值: dict[str, int], 匹配到的 {常量名: 值}
    """
    lowered = keyword.lower()
    return {k: v for k, v in load_constants().items() if lowered in k.lower()}


if __name__ == "__main__":  # pragma: no cover - 手工排查入口
    import sys

    keyword = sys.argv[1] if len(sys.argv) > 1 else "step"
    hits = search(keyword)
    print(f"SolidWorks 目录: {find_sw_dir()}")
    print(f"常量总数: {len(load_constants())}; 匹配 '{keyword}': {len(hits)}")
    for key in sorted(hits):
        print(f"  {key} = {hits[key]}")
