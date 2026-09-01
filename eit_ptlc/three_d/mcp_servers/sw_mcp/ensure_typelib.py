"""
功能: 为 SolidWorks 生成 pywin32 的早期绑定包装(makepy), 一次性根治动态派发认不出接口方法的问题.

背景: pywin32 默认走后期绑定(IDispatch::GetIDsOfNames). SolidWorks 的对象模型层级很深,
很多方法挂在具体接口(IModelDoc2 / IAssemblyDoc / IComponent2)上而不是默认派发接口, 后期绑定
会报 "找不到成员" 或 AttributeError —— GetFirstDocument2、GetActiveConfiguration 都栽在这里.
生成早期绑定包装后, pywin32 直接按类型库调用, 全部方法可见.

代价: 首次生成需要解析 2 MB 的 sldworks.tlb, 约一到几分钟; 生成物缓存在
win32com/gen_py 下, 之后所有会话都直接复用.

用法:
    python ensure_typelib.py           # 生成(已存在则跳过)
    python ensure_typelib.py --force   # 清缓存重新生成

参数: 见 argparse
返回值: 无(打印结果); 失败时退出码非零
"""

from __future__ import annotations

import argparse
import os
import shutil
import time

import pythoncom
import win32com.client
from win32com.client import gencache

import sw_constants as swc

# SolidWorks 的两个类型库: 接口在 sldworks.tlb, 常量在 swconst.tlb
TYPELIBS = ("sldworks.tlb", "swconst.tlb")


def gen_py_dir() -> str:
    """
    功能: 取 pywin32 生成物的缓存目录.
    参数: 无
    返回值: str, 目录路径
    """
    return gencache.GetGeneratePath()


def build_from_tlb(tlb_path: str) -> dict:
    """
    功能: 为一个类型库生成早期绑定包装.
    参数:
        tlb_path: .tlb 文件路径
    返回值: dict, 生成结果(含 guid/version/耗时)
    """
    started = time.time()
    typelib = pythoncom.LoadTypeLib(tlb_path)
    attr = typelib.GetLibAttr()
    guid, lcid, major, minor = str(attr[0]), attr[1], attr[3], attr[4]

    gencache.EnsureModule(guid, lcid, major, minor)
    return {
        "tlb": os.path.basename(tlb_path),
        "guid": guid,
        "version": f"{major}.{minor}",
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="生成 SolidWorks 早期绑定包装")
    parser.add_argument("--force", action="store_true", help="清空缓存重新生成")
    args = parser.parse_args()

    install_dir = swc.find_sw_dir()
    print(f"SolidWorks 安装目录: {install_dir}")
    print(f"pywin32 生成物目录: {gen_py_dir()}")

    if args.force:
        cache = gen_py_dir()
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)
            print("已清空缓存")

    pythoncom.CoInitialize()
    try:
        for name in TYPELIBS:
            path = os.path.join(install_dir, name)
            if not os.path.isfile(path):
                print(f"  跳过(不存在): {name}")
                continue
            print(f"  生成 {name} … (首次可能需要几分钟)")
            info = build_from_tlb(path)
            print(f"    完成: {info['guid']} v{info['version']}  耗时 {info['elapsed_s']}s")

        # 验证: 早期绑定后, 之前认不出的成员应当可见
        print("\n验证早期绑定是否生效:")
        try:
            app = win32com.client.GetActiveObject("SldWorks.Application")
        except pythoncom.com_error:
            app = win32com.client.Dispatch("SldWorks.Application")
        print(f"  应用对象类型: {type(app).__name__}")

        for member in ("GetFirstDocument2", "GetDocuments", "ActiveDoc", "RevisionNumber"):
            print(f"  {member}: {'可见' if hasattr(app, member) else '仍不可见'}")
    finally:
        pythoncom.CoUninitialize()

    print("\n完成. 之后所有会话都会自动使用早期绑定, 不需要再跑本脚本.")


if __name__ == "__main__":
    main()
