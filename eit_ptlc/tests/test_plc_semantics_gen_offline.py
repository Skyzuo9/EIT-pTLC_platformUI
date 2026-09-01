"""PLC 语义表生成物的漂移看门狗
===============================
功能:
    web/src/three-d/twin/plcSemantics.generated.js 是由 specs/*.yaml 渲染出来的提交物。
    本测试重新渲染一遍并**逐字节**比对 —— 手改生成物、或改了 specs 忘了重生成, 都必红。

    与 materialGrid.contract.json 同一手法: 两侧一份字节流, 不给"我记得改过了"留空间。
"""

from __future__ import annotations

from pathlib import Path

from eit_ptlc.tools.gen_plc_semantics import build_payload, render

_OUT = (Path(__file__).resolve().parent.parent
        / "web" / "src" / "three-d" / "twin" / "plcSemantics.generated.js")

_HINT = ('运行 & "C:/ProgramData/miniforge3/python.exe" '
         "-m eit_ptlc.tools.gen_plc_semantics 重生成")


def test_generated_file_exists():
    assert _OUT.exists(), f"生成物缺失 —— {_HINT}"


def test_generated_file_is_byte_identical():
    assert _OUT.read_text(encoding="utf-8") == render(build_payload()), (
        f"plcSemantics.generated.js 与 specs 不一致 —— {_HINT}")


def test_payload_covers_every_station_and_action():
    """每个工位都要有动作, 每个动作都要有名字 —— 空壳表比没有表更误导人."""
    payload = build_payload()
    assert len(payload) >= 8, "工位数少于 8, specs 可能没加载全"
    for station, block in payload.items():
        assert block["actions"], f"{station} 没有任何动作记录"
        for code, action in block["actions"].items():
            assert action["name"], f"{station}/{code} 缺 name"
            assert action["summary"], f"{station}/{code} 缺 summary"


def test_steps_keep_english_phase_verbatim():
    """phase 必须是原文蛇形 —— 一旦有人在生成器里"顺手翻译", 就造出了没有看门狗的第二真源."""
    for station, block in build_payload().items():
        for code, action in block["actions"].items():
            for step, phase in action["steps"]:
                assert isinstance(step, int), f"{station}/{code} 段号不是整数"
                if phase:
                    assert phase.isascii(), (
                        f"{station}/{code} 的 phase {phase!r} 含非 ASCII —— "
                        "phase 应保持 CODESYS 原文, 中文释义只走 errors/summary")
