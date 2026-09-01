"""无 before 手绘兜底: after 单图姿态归一化 backdrop 离线测试
================================================================
根因 (memory[photoscrape-vision-frame-consistency]):
    无 before 时 process_pair(成对)不跑 → 不做 rot180+deskew 归一化 → 手绘门画在 raw 帧,
    而 CNC 标定活在归一化(=机床对齐)帧 → 实刮走反向 (rot180)。

修复契约 (本测试锁定):
    analyze_full(before=None, after=<真实图>) 仍对 after **单图**跑同一套
    rot180+deskew+找板, 落 case_dir/after_normalized.jpg (归一化帧, 非 raw 拷贝) +
    最小 summary.json(plate_bbox_px, 无 bands)。手绘门据此画在归一化帧 → 所见即所跑。

    向后兼容: after 不可读(mock/占位)时回落旧行为(无 case, summary_path 空)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_vision_backdrop_normalize_offline
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from eit_ptlc.controller.vision_controller import VisionService

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_AFTER = _REPO_ROOT / "data" / "samples" / "case1" / "after.jpg"


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    if not _SAMPLE_AFTER.is_file():
        print(f"SKIP: 缺样图 {_SAMPLE_AFTER}")
        return 0
    try:
        import cv2  # type: ignore  # noqa: F401
    except ImportError:
        print("SKIP: cv2 不可用")
        return 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # rot180 归一化 (与真机 app.yaml 同): 无 before 时也应对 after 单图归一化
        svc = VisionService(
            output_dir=td, mock_mode=False,
            image_plate_orientation="rot180",
            image_plate_rotation_deg=-2.43,
            auto_rectify_tilt=True,
            rectify_min_angle_deg=0.5,
        )

        r = await svc.analyze_full("NB", None, _SAMPLE_AFTER)

        # 核心: 无 before 仍产出真实 case_dir + 归一化 backdrop
        check("no_before_reason", r.reason == "before_invalid", r.reason)
        has_case = str(r.case_dir) not in ("", ".")
        check("no_before_case_dir", has_case and Path(r.case_dir).is_dir(), str(r.case_dir))
        norm = Path(r.case_dir) / "after_normalized.jpg"
        check("backdrop_normalized_exists", norm.is_file(), str(norm))

        # backdrop 必须是归一化帧 (非 raw 拷贝): rot180 后与原图逐像素不同
        if norm.is_file():
            import cv2  # type: ignore
            raw = cv2.imread(str(_SAMPLE_AFTER), cv2.IMREAD_COLOR)
            got = cv2.imread(str(norm), cv2.IMREAD_COLOR)
            differs = raw is not None and got is not None and not np.array_equal(raw, got)
            check("backdrop_is_normalized_not_raw", differs,
                  "after_normalized 与 raw 逐像素相同 → 未做归一化")

        # summary.json 落盘且可被手绘门 (read_plate_bbox) 消费, 含 plate_bbox_px
        summary_file = Path(r.case_dir) / "summary.json" if has_case else None
        summary = json.loads(summary_file.read_text(encoding="utf-8")) if (summary_file and summary_file.is_file()) else {}
        check("summary_has_plate_bbox", isinstance(summary.get("plate_bbox_px"), dict),
              str(summary.get("plate_bbox_px")))

        # analyze_action: summary_path 非空指向该 summary; annotated_url 指向归一化 backdrop
        d = await svc.analyze_action("NB2", "", str(_SAMPLE_AFTER))
        sp = d.get("summary_path", "")
        check("action_summary_path_nonempty", bool(sp) and Path(sp).is_file(), str(sp))
        au = d.get("annotated_url", "")
        check("action_backdrop_is_normalized", au.endswith("after_normalized.jpg"), str(au))

        # 向后兼容: after 不可读 (占位) → 回落旧行为 (无 case, summary_path 空)
        fake_after = td / "fake.jpg"
        fake_after.write_bytes(b"x")
        d_fb = await svc.analyze_action("FB", "", str(fake_after))
        check("fallback_summary_empty_when_unreadable", d_fb.get("summary_path") == "",
              str(d_fb.get("summary_path")))

    print(f"\n共 8 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_vision_backdrop_normalize_offline():
    """pytest 入口: 无 before 手绘兜底走 after 单图归一化 backdrop。"""
    assert asyncio.run(_run()) == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
