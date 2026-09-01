"""视觉控制器离线测试 (mock 路径 + 容错结构化结果)
=================================
功能:
    验证 controller/vision_controller 迁移后 mock 模式可用: 双帧分析返回 3 条 band,
    before 缺失返回 ok=False. 真机路径 (tlc_analyze + cv2 + 真图) 现场验收.

    容错化契约 (本次新增):
      - analyze_action 始终返回结构化 dict {ok, reason, message, summary_path,
        case_dir, band_ids, annotated_url}, 对可恢复失败**不再抛 ValueError**。
      - reason ∈ {ok, no_bands, before_invalid, analyze_error}。
      - no_bands / before_invalid 经 ActionExecutor 归一为 DONE (非 REJECTED/raise),
        VM 据此分支到人工菜单, 不再是致命错误。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vision_controller_offline
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from eit_ptlc.action.models import ActionStatus
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.controller.vision_controller import AnalysisResult, BandInfo, VisionService

_ACTIONS_DIR = Path(__file__).resolve().parents[1] / "config" / "actions"


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        before, after = td / "before.jpg", td / "after.jpg"
        before.write_bytes(b"x")
        after.write_bytes(b"x")

        svc = VisionService(output_dir=td, mock_mode=True)
        r = await svc.analyze_full("S1", before, after)
        check("mock_full_ok", r.ok and len(r.bands) == 3, f"ok={r.ok} bands={len(r.bands)}")
        check("mock_full_reason_ok", r.reason == "ok", r.reason)
        check("band_fields", isinstance(r.bands[0], BandInfo) and r.bands[0].band_id == "band_01"
              and r.bands[0].centroid_cm is not None, str(r.bands[0].band_id if r.bands else None))

        r2 = await svc.analyze_full("S1", None, after)
        check("mock_no_before", isinstance(r2, AnalysisResult) and not r2.ok, str(r2.ok))
        check("mock_no_before_reason", r2.reason == "before_invalid", r2.reason)

        # analyze_action: 成功路径返回结构化 dict (含 reason/契约键)
        d_ok = await svc.analyze_action("S1", str(before), str(after))
        contract_keys = {"ok", "reason", "message", "summary_path", "case_dir", "band_ids", "annotated_url"}
        check("action_ok_shape", contract_keys <= set(d_ok) and d_ok["ok"] is True and d_ok["reason"] == "ok",
              str(sorted(d_ok)))
        check("action_ok_bands", d_ok["band_ids"] == ["band_01", "band_02", "band_03"], str(d_ok["band_ids"]))

        # analyze_action: before 无效**不抛异常**, 返回 ok=False / reason=before_invalid (可分支)
        raised = False
        try:
            d_bad = await svc.analyze_action("S1", "", str(after))
        except Exception as exc:  # noqa: BLE001
            raised = True
            d_bad = {"err": str(exc)}
        check("action_before_invalid_nonfatal",
              not raised and d_bad.get("ok") is False and d_bad.get("reason") == "before_invalid",
              f"raised={raised} d={d_bad}")

        # 手绘门底图兜底: before 无效但 after 存在 → annotated_url 非空且指向 output_dir 下可服务图,
        # 供手绘门当底图画 (视觉未框到板走 4 角标板); summary_path 仍为空 (不伪造 case, 失败语义不变)。
        d_bd = await svc.analyze_action("SBD", "", str(after))
        bd_url = d_bd.get("annotated_url", "")
        check("backdrop_url_nonempty", bool(bd_url) and bd_url.startswith("/api/vision/image/"), str(bd_url))
        check("backdrop_summary_empty", d_bd.get("summary_path") == "", str(d_bd.get("summary_path")))
        bd_rel = bd_url.split("/api/vision/image/", 1)[-1] if bd_url else ""
        check("backdrop_file_servable", bool(bd_rel) and (td / bd_rel).is_file(), f"rel={bd_rel}")

        # no_bands 非致命: 打桩 analyze_full 返回 no_bands, analyze_action 不抛且 reason=no_bands
        async def _fake_no_bands(sample_id, before_p, after_p, *, overrides=None, output_dir=None):
            return AnalysisResult(ok=False, case_name=sample_id, case_dir=td / sample_id,
                                  summary={}, reason="no_bands", message="零非原点条带", bands=[])
        svc.analyze_full = _fake_no_bands  # type: ignore[assignment]
        d_nb = await svc.analyze_action("S1", str(before), str(after))
        check("action_no_bands_nonfatal", d_nb["ok"] is False and d_nb["reason"] == "no_bands",
              str(d_nb))

        # 经 ActionExecutor 端到端: no_bands 归一为 DONE (非 REJECTED/raise) → VM 可分支
        from eit_ptlc.action.executor import ActionExecutor
        registry = ActionRegistry.load(_ACTIONS_DIR)
        executor = ActionExecutor(registry, vision_methods={"analyze": svc.analyze_action})
        res = await executor.execute("photoscrape.analyze",
                                     {"sample_id": "S1", "before_path": str(before),
                                      "after_path": str(after)})
        check("executor_no_bands_is_done",
              res.status == ActionStatus.DONE and res.result.get("reason") == "no_bands"
              and res.result.get("ok") is False,
              f"status={res.status} result={res.result}")

    print(f"\n共 12 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_vision_controller_offline():
    """pytest 入口: 结构化容错结果 + no_bands/before_invalid 非致命。"""
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
