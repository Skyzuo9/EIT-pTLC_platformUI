"""
功能: blender_mcp 自检脚本. 验证 Blender 可定位、可无界面执行、可回传结构化结果.
用法: python selftest.py [模型路径]
参数: 可选的模型路径, 提供则额外测试检查与渲染
返回值: 无(打印结果); 失败时退出码非零
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import blender_core as core


def main() -> None:
    """功能: 依次执行各项自检. 参数: 无. 返回值: None"""
    print("=== 1. 定位 Blender ===")
    blender = core.find_blender()
    print(f"blender.exe: {blender}")

    print("\n=== 2. 无界面执行与结果回传 ===")
    result = core.run_script(
        core.PRELUDE + '\nemit({"ok": True, "version": bpy.app.version_string})',
        timeout=180,
    )
    payload = core.extract_json_result(result["stdout"])
    print(f"退出码: {result['returncode']}; 回传: {payload}")
    if payload is None:
        print("stdout 尾部:")
        print("\n".join(result["stdout"].splitlines()[-20:]))
        print("stderr 尾部:")
        print("\n".join(result["stderr"].splitlines()[-20:]))
        raise SystemExit("自检失败: Blender 未回传结果")

    model = sys.argv[1] if len(sys.argv) > 1 else None
    if not model:
        print("\n未提供模型路径, 跳过检查与渲染测试")
        print("\n自检通过")
        return

    if not os.path.isfile(model):
        raise SystemExit(f"模型不存在: {model}")

    print(f"\n=== 3. 检查模型 {model} ===")
    result = core.run_script(core.script_inspect(model, "", 8), timeout=1800)
    payload = core.extract_json_result(result["stdout"])
    if payload is None:
        print("\n".join(result["stdout"].splitlines()[-25:]))
        raise SystemExit("自检失败: 检查模型未回传结果")
    print(json.dumps(payload["stats"], ensure_ascii=False))
    print("面数最多的对象:")
    for item in payload["objects"][:8]:
        print(f"  {item['name']:<44} 面 {item['polygons']:>7}  尺寸 {item['dimensions']}")

    print("\n=== 4. 渲染预览 ===")
    output = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "work", "previews", "selftest.png"
    )
    output = os.path.normpath(output)
    result = core.run_script(
        core.script_render(model, output.replace("\\", "/"), 1000, 700, "iso"), timeout=1800
    )
    payload = core.extract_json_result(result["stdout"])
    if payload is None:
        print("\n".join(result["stdout"].splitlines()[-25:]))
        raise SystemExit("自检失败: 渲染未回传结果")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    print("\n自检通过")


if __name__ == "__main__":
    main()
