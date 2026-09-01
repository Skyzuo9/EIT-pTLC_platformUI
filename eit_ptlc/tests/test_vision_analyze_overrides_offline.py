"""analyze_action 每-run 识别参数覆盖 (step 0a) 的离线单测。

契约: analyze_action 收关键字识别参数, 仅把**非 None** 项汇成 overrides 转 analyze_full;
全缺省 → overrides=None (走 VisionService 烘定基线, 即生产 config.vision)。
这条链是"门内重识别(下发前调参)"与"中控 param-sweep"以及 bootstrap 实时基线注入的公共通道。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eit_ptlc.controller.vision_controller import AnalysisResult, VisionService


def _svc_with_capture(tmp_path: Path) -> tuple[VisionService, dict]:
    """构造一个 VisionService, 用假 analyze_full 截获 overrides (不触真分析/文件)。"""
    svc = VisionService(output_dir=tmp_path, mock_mode=True)
    captured: dict = {}

    async def fake_analyze_full(sample_id, before, after, *, overrides=None, output_dir=None):
        captured["overrides"] = overrides
        captured["before"] = before
        return AnalysisResult(
            ok=True, case_name=sample_id, case_dir=tmp_path / sample_id, summary={}, bands=[]
        )

    svc.analyze_full = fake_analyze_full  # type: ignore[assignment]
    return svc, captured


def test_overrides_collect_only_non_none(tmp_path):
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(
        svc.analyze_action(
            "s1", "before.jpg", "after.jpg",
            min_row_score=7.5, image_plate_orientation="rot90cw",
        )
    )
    assert captured["overrides"] == {
        "min_row_score": 7.5,
        "image_plate_orientation": "rot90cw",
    }


def test_no_overrides_forwards_none(tmp_path):
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(svc.analyze_action("s2", "before.jpg", "after.jpg"))
    assert captured["overrides"] is None


def test_all_four_overrides_forwarded(tmp_path):
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(
        svc.analyze_action(
            "s3", "before.jpg", "after.jpg",
            image_plate_orientation="rot180",
            auto_rectify_tilt=True,
            rectify_min_angle_deg=1.25,
            min_row_score=3.0,
        )
    )
    assert captured["overrides"] == {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 1.25,
        "min_row_score": 3.0,
    }


def test_before_path_empty_becomes_none(tmp_path):
    """before_path 空串 → before=None (双帧缺 before 的既有语义不被覆盖改动破坏)。"""
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(svc.analyze_action("s4", "", "after.jpg", min_row_score=9.0))
    assert captured["before"] is None
    assert captured["overrides"] == {"min_row_score": 9.0}


def test_analyze_action_rotation_none_passes_through(tmp_path):
    # 显式 None(=每帧自动估) 必须进 overrides — 不得被 None 过滤丢弃回落烘定值 (终审 Critical #1)
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(
        svc.analyze_action(
            "s5", "before.jpg", "after.jpg",
            image_plate_rotation_deg=None,
        )
    )
    assert captured["overrides"]["image_plate_rotation_deg"] is None


def test_analyze_action_rotation_omitted_stays_unset(tmp_path):
    # 未传该 kwarg → 走 _UNSET 哨兵, 不得进 overrides (回落 VisionService 烘定基线)
    svc, captured = _svc_with_capture(tmp_path)
    asyncio.run(svc.analyze_action("s6", "before.jpg", "after.jpg"))
    assert "image_plate_rotation_deg" not in (captured["overrides"] or {})
