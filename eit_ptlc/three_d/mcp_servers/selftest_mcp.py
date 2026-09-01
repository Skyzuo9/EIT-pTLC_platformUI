"""
功能: MCP 服务器自检. 验证两个服务器能被解释器成功加载、工具已注册、依赖齐备.

不实际建立 stdio 连接(那需要 MCP 客户端), 只做静态可用性验证 —— 这已经能拦住
绝大多数问题: 依赖缺失、语法错误、导入路径不对、工具装饰器写错.

用法: python selftest_mcp.py
参数: 无
返回值: 无(打印结果); 失败时退出码非零
"""

from __future__ import annotations

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_module(name: str, path: str):
    """
    功能: 从文件路径加载模块.
    参数:
        name: 模块名
        path: 文件路径
    返回值: module
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def list_tools(server) -> list[str]:
    """
    功能: 取出服务器已注册的工具名.

    注: MCPServer.list_tools 的类型标注写的是同步返回, 实际是协程, 因此这里统一
    用 asyncio.run 驱动, 并对两种情况都做兼容.

    参数:
        server: MCPServer 实例
    返回值: list[str]
    """
    import asyncio
    import inspect

    result = server.list_tools()
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return [tool.name for tool in result]


def check(label: str, directory: str, module_name: str) -> bool:
    """
    功能: 检查一个 MCP 服务器.
    参数:
        label: 显示名
        directory: 服务器目录
        module_name: 模块名
    返回值: bool, 是否通过
    """
    print(f"\n=== {label} ===")
    path = os.path.join(HERE, directory, "server.py")
    if not os.path.isfile(path):
        print(f"  失败: 找不到 {path}")
        return False

    sys.path.insert(0, os.path.join(HERE, directory))
    try:
        module = load_module(module_name, path)
        tools = list_tools(module.mcp)
        print("  模块加载: 通过")
        print(f"  已注册工具 ({len(tools)}): {', '.join(tools)}")
        return len(tools) > 0
    except Exception as exc:  # noqa: BLE001
        print(f"  失败: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        return False


def main() -> None:
    """功能: 主入口. 参数: 无. 返回值: None"""
    print(f"Python: {sys.executable}")

    results = [
        check("SolidWorks MCP", "sw_mcp", "sw_mcp_server"),
        check("Blender MCP", "blender_mcp", "blender_mcp_server"),
    ]

    print("\n" + "=" * 50)
    if all(results):
        print("MCP 自检全部通过")
        print("提示: .mcp.json 已注册这两个服务器, 需重启 Claude Code 后才会生效")
    else:
        print("MCP 自检存在失败项")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
