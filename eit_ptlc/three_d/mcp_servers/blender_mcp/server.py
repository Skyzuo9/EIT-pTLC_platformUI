"""
功能: Blender MCP 服务器. 以无界面方式驱动 Blender, 让 AI 可以检查模型、执行任意 bpy 脚本、
      渲染预览图、以及运行资产管线的清理步骤 —— 用户无需亲自打开 Blender.

与社区 GUI 插件式 blender-mcp 的取舍见 blender_core 模块的说明: 本实现每次调用都是
一个干净的一次性 Blender 进程, 更适合无人值守的资产管线, 代价是没有常驻场景,
因此多步操作要靠"输入文件 -> 输出文件"串联.

启动:
    python server.py                 # 由 MCP 客户端以 stdio 方式拉起
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# MCP Python SDK 2.x 把高层服务器类改名为 MCPServer(1.x 时叫 FastMCP), 装饰器用法不变
from mcp.server.mcpserver import MCPServer  # noqa: E402

import blender_core as core  # noqa: E402

mcp = MCPServer("blender")

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WORK_DIR = os.path.join(ROOT, "work")
PIPELINE_DIR = os.path.join(ROOT, "pipeline")


def _ok(payload: object) -> str:
    """
    功能: 序列化成功结果.
    参数:
        payload: 可序列化对象
    返回值: str, JSON 文本
    """
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fail(message: str, detail: str = "") -> str:
    """
    功能: 构造统一的错误返回.
    参数:
        message: 错误说明
        detail: 附加细节(通常是 Blender 的 stderr 尾部)
    返回值: str, JSON 文本
    """
    return json.dumps(
        {"ok": False, "error": message, "detail": detail[-3000:] if detail else ""},
        ensure_ascii=False,
        indent=2,
    )


def _tail(text: str, lines: int = 40) -> str:
    """
    功能: 取文本末尾若干行(Blender 输出很长, 只有末尾有用).
    参数:
        text: 原始文本
        lines: 行数
    返回值: str
    """
    return "\n".join(text.strip().splitlines()[-lines:])


@mcp.tool()
def blender_info() -> str:
    """
    查询 Blender 可用性: 可执行文件路径与版本号.

    在做任何模型操作之前先调用本工具确认环境就绪.
    """
    try:
        blender = core.find_blender()
        result = core.run_script(
            core.PRELUDE + '\nemit({"ok": True, "version": bpy.app.version_string})',
            timeout=120,
        )
        payload = core.extract_json_result(result["stdout"]) or {}
        return _ok(
            {
                "ok": result["ok"],
                "blender": blender,
                "version": payload.get("version"),
                "work_dir": WORK_DIR,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def blender_inspect(model_path: str, name_filter: str = "", limit: int = 60) -> str:
    """
    检查一个模型文件(GLB/GLTF/BLEND/OBJ/STL): 回传场景统计与对象清单(按面数从多到少排序).

    这是排查"删减是否生效""哪些零件最重""某个零件是否还在"的首选工具.

    参数:
        model_path: 模型绝对路径
        name_filter: 只列出名字含该子串的对象(不区分大小写); 留空表示全部
        limit: 最多回传多少个对象
    """
    if not os.path.isfile(model_path):
        return _fail(f"文件不存在: {model_path}")
    try:
        result = core.run_script(core.script_inspect(model_path, name_filter, limit))
        payload = core.extract_json_result(result["stdout"])
        if payload is None:
            return _fail("Blender 未回传结果", _tail(result["stdout"]) + "\n" + _tail(result["stderr"]))
        return _ok(payload)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def blender_render(
    model_path: str,
    output_name: str = "preview.png",
    view: str = "iso",
    width: int = 1280,
    height: int = 900,
) -> str:
    """
    渲染一张模型预览图(自动取景 + 三点布光 + 深色背景), 输出到 work/previews/ 目录.

    渲染出来的 PNG 可以直接用 Read 工具查看, 是 AI 自查模型外观的主要手段:
    删减是否删过头、材质配色是否合理、装配朝向是否正确, 看图比读统计数字直观得多.

    参数:
        model_path: 模型绝对路径
        output_name: 输出文件名(不含目录)
        view: 机位, 可选 iso / front / left / top
        width / height: 分辨率
    """
    if not os.path.isfile(model_path):
        return _fail(f"文件不存在: {model_path}")
    try:
        output_path = os.path.join(WORK_DIR, "previews", output_name)
        result = core.run_script(
            core.script_render(model_path, output_path.replace("\\", "/"), width, height, view)
        )
        payload = core.extract_json_result(result["stdout"])
        if payload is None:
            return _fail("Blender 未回传结果", _tail(result["stdout"]) + "\n" + _tail(result["stderr"]))
        payload["hint"] = "可用 Read 工具直接查看该 PNG"
        return _ok(payload)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def blender_run_script(code: str, timeout: int = 1800) -> str:
    """
    在无界面 Blender 中执行任意 Python(bpy)代码, 回传标准输出.

    这是探索性操作的通用出口 —— 试删减规则、量某个零件的尺寸、试材质参数、
    调整层级结构, 都可以先用本工具试出来, 确认无误后再固化进 pipeline 的脚本.

    代码里可直接使用以下预置辅助(无需自己定义):
        load_model(path)  清空场景并导入模型
        mesh_objects()    取全部网格对象
        scene_stats()     统计对象/网格/三角形/材质数量
        emit(payload)     把结构化结果回传给调用方(推荐用它而不是 print)

    参数:
        code: 要执行的 Python 源码
        timeout: 超时秒数
    """
    try:
        result = core.run_script(core.PRELUDE + "\n" + code, timeout=timeout)
        payload = core.extract_json_result(result["stdout"])
        return _ok(
            {
                "ok": result["ok"],
                "returncode": result["returncode"],
                "result": payload,
                "stdout_tail": _tail(result["stdout"], 60),
                "stderr_tail": _tail(result["stderr"], 30),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@mcp.tool()
def blender_clean_model(
    input_path: str = "",
    output_path: str = "",
    stage: str = "minimal",
    decimate: bool = False,
) -> str:
    """
    运行资产管线的清理步骤(03_clean_model): 按 prune_list.yaml 删减零件、
    按 materials.yaml 赋 PBR 材质, minimal 阶段还会按材质合并以压低绘制调用数.

    参数:
        input_path: 输入 GLB 路径; 留空则用管线默认(work 目录下 02 步的产物)
        output_path: 输出 GLB 路径; 留空则用 work/machine.clean.glb
        stage: minimal(M0: 只删减+赋材质+合并) 或 full(M1: 另按 rig_map 重组与装配)
        decimate: 是否启用 prune_list 中的减面规则
    """
    import subprocess

    script = os.path.join(PIPELINE_DIR, "03_clean_model.py")
    if not os.path.isfile(script):
        return _fail(f"未找到管线脚本: {script}")

    command = [sys.executable, script, "--stage", stage]
    if input_path:
        command += ["--input", input_path]
    if output_path:
        command += ["--output", output_path]
    if decimate:
        command.append("--decimate")

    try:
        completed = subprocess.run(
            command,
            cwd=PIPELINE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10800,
        )
        return _ok(
            {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout_tail": _tail(completed.stdout, 60),
                "stderr_tail": _tail(completed.stderr, 30),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


if __name__ == "__main__":
    mcp.run()
