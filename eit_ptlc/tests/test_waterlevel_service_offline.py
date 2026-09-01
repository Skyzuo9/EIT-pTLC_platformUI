"""液位拉帧检测服务端到端离线测试
===================================
功能:
    把香橙派单帧端点 (mjpeg_streamer, fake 帧源) 与上位机拉帧检测服务接起来, 验证完整链路:
      GET /frame/chN → imdecode → detect_level → snapshot percent
    覆盖: 参考图捕获、半湿→percent≈50、不可达通道 reachable=False、非活跃通道不拉帧。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_service_offline
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np

from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, LevelResult, WaterLevelDetectParams
from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
from eit_ptlc.controller.waterlevel_store import ChannelConfig, save_channel_configs

_PAYLOAD = (Path(__file__).resolve().parent.parent
            / "driver" / "water_level_payload" / "mjpeg_streamer.py")
_spec = importlib.util.spec_from_file_location("mjpeg_streamer", _PAYLOAD)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MJPEGStreamer = _mod.MJPEGStreamer

# 与 P0 同几何: frame 200x300, ROI=(50,50,200,100), crop0.1 → 检测 ROI 原图[60:140,70:230] 宽160
_ROI = (50, 50, 200, 100)


def _dry():
    return np.full((200, 300, 3), 200, np.uint8)


def _half_wet():
    f = _dry()
    f[60:140, 70:150] = 100   # ROI 左半浸润 → ~50%
    return f


class _FakeDetector:
    def __init__(self):
        self.frame = None

    def get_frame(self):
        return None if self.frame is None else self.frame.copy()


class _FakeManager:
    def __init__(self, detectors):
        self.channels = detectors
        self.num_channels = len(detectors)


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    det = _FakeDetector()
    det.frame = _dry()
    streamer = MJPEGStreamer(port=0, multi_channel_manager=_FakeManager([det]))
    streamer.start()
    port = streamer._server.server_address[1]

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "calib.json"
        save_channel_configs(cfg_path, {
            1: ChannelConfig(
                ChannelCalibration(rotation_angle_deg=0.0, roi_bbox=_ROI,
                                   flow_direction="left_to_right"),
                WaterLevelDetectParams()),
        })
        svc = WaterLevelDetectService("127.0.0.1", port, cfg_path, interval=0.05,
                                      ref_frames=3)
        svc.set_active_channels({1})

        # 1) 参考窗口捕获 (N=3 帧逐像素 median; 帧序 200/210/200 → median 200)
        svc.request_reference(1)
        await svc._tick()
        check("ref_window_accumulating", 1 not in svc._refs and 1 in svc._ref_pending,
              f"refs={list(svc._refs)} pending={svc._ref_pending}")
        # 参考窗口暗帧地板: 冷相机曝光爬坡的近黑帧不入 median (防毒参考基线)
        det.frame = np.full((200, 300, 3), 5, np.uint8)   # 均亮 5 < REF_DARK_FLOOR
        await svc._tick()
        check("ref_window_dark_skipped",
              len(svc._ref_accum.get(1, [])) == 1 and 1 in svc._ref_pending,
              f"accum={len(svc._ref_accum.get(1, []))} pending={svc._ref_pending}")
        det.frame = np.full((200, 300, 3), 210, np.uint8)
        await svc._tick()
        det.frame = _dry()
        await svc._tick()
        check("ref_captured_after_window", 1 in svc._refs, str(list(svc._refs.keys())))
        check("ref_median_value",
              1 in svc._refs and 199 <= float(np.median(svc._refs[1].plate_gray)) <= 201,
              "" if 1 not in svc._refs else str(float(np.median(svc._refs[1].plate_gray))))
        check("ref_tick_no_result", 1 not in svc._results, "ref 窗口期不应产出检测结果")

        # 1b) has_reference / cancel_reference (capture_reference 轮询与超时撤销用)
        check("has_reference_true", svc.has_reference(1) is True, "")
        svc.request_reference(1)                       # 重开窗口 → pending
        check("has_reference_pending_false", svc.has_reference(1) is False,
              "窗口进行中不算已有 — capture_reference 重拍不得被旧参考短路")
        svc.cancel_reference(1)
        check("cancel_clears_pending", 1 not in svc._ref_pending and 1 not in svc._ref_accum,
              f"pending={svc._ref_pending}")
        check("has_reference_after_cancel_true", svc.has_reference(1) is True,
              "撤销窗口后旧参考仍在 _refs (供检测连续性)")

        # 2) 半湿 → 检测出 percent≈50
        det.frame = _half_wet()
        await svc._tick()
        snap = svc.snapshot()
        c1 = snap["channels"].get(1)
        check("ch1_valid", c1 is not None and c1["valid"], str(c1))
        check("ch1_front_50", c1 is not None and c1["front_percent"] is not None
              and 45 <= c1["front_percent"] <= 55,
              None if c1 is None else str(c1["front_percent"]))
        check("ch1_front_50", c1 is not None and c1["front_percent"] is not None
              and 45 <= c1["front_percent"] <= 55, None if c1 is None else str(c1["front_percent"]))
        check("ch1_reachable", c1 is not None and c1["reachable"], "")
        check("ch1_has_ref", c1 is not None and c1["has_ref"], "")
        check("ch1_observed_at", c1 is not None and bool(c1.get("observed_at")), str(c1))
        check("reachable_any", snap["reachable_any"] is True, str(snap["reachable_any"]))
        # log 模式快照暴露 gain (无干区 → 1.0) 与守卫冻结态
        check("snapshot_gain", c1 is not None and c1.get("gain") is not None
              and 0.95 <= c1["gain"] <= 1.05, None if c1 is None else str(c1.get("gain")))
        check("snapshot_gain_frozen", c1 is not None and c1.get("gain_frozen") is False,
              None if c1 is None else str(c1.get("gain_frozen")))

        # 2b) 暗帧守卫: 相机重开曝光爬坡的近黑帧 → frame_dark 无效帧, 不喂 front_max
        front_max_before = svc._front_max.get(1)
        det.frame = np.full((200, 300, 3), 20, np.uint8)   # 均亮 20 << 0.35×参考(~200)
        await svc._tick()
        c1 = svc.snapshot()["channels"].get(1)
        check("dark_frame_reason", c1 is not None and not c1["valid"]
              and c1["reason"] == "frame_dark", str(c1))
        check("dark_frame_front_max_kept", svc._front_max.get(1) == front_max_before,
              f"{svc._front_max.get(1)} != {front_max_before}")
        det.frame = _half_wet()
        await svc._tick()
        c1 = svc.snapshot()["channels"].get(1)
        check("dark_frame_recovery", c1 is not None and c1["valid"], str(c1))

        # 3) 不可达通道 (越界 → 404) → reachable=False, 不产出结果
        svc.set_active_channels({3})
        await svc._tick()
        check("ch3_unreachable", svc._reachable.get(3) is False, str(svc._reachable.get(3)))
        check("ch3_no_result", 3 not in svc._results, "")

        # 4) 空活跃集 → tick 直接返回, 不报错
        svc.set_active_channels(set())
        await svc._tick()
        check("empty_active_ok", svc.snapshot()["active"] == [], "")

        # 5) 快照暴露 drift, get_params 暴露 front_gap_frac
        r_drift = LevelResult(valid=True, front_percent=50.0, wet_ratio=0.5,
                              diff_mean=8.0, drift=5.5, roi_size=(100, 50))
        svc._results[1] = r_drift
        snap_ch = svc.snapshot()["channels"][1]
        check("snapshot_exposes_drift", snap_ch.get("drift") == 5.5, f"got={snap_ch.get('drift')}")
        check("get_params_front_gap", "front_gap_frac" in svc.get_params(1),
              str(svc.get_params(1).keys()))

        # 6) update_params 白名单收 front_gap_frac (读写对称, 不落盘)
        svc.update_params(1, {"front_gap_frac": 0.22}, save=False)
        check("update_params_front_gap", svc.get_params(1)["front_gap_frac"] == 0.22,
              str(svc.get_params(1).get("front_gap_frac")))

        # 7) log 域三字段: get_params 暴露 + update_params 白名单 + 非法 mode 拒收
        gp = svc.get_params(1)
        check("get_params_log_fields",
              all(k in gp for k in ("separation_mode", "wet_rel_threshold",
                                    "front_gap_frac")), str(gp.keys()))
        svc.update_params(1, {"separation_mode": "abs", "wet_rel_threshold": 0.08,
                              "front_gap_frac": 0.22}, save=False)
        gp = svc.get_params(1)
        check("update_params_log_fields",
              gp["separation_mode"] == "abs" and gp["wet_rel_threshold"] == 0.08
              and gp["front_gap_frac"] == 0.22, str(gp))
        svc.update_params(1, {"separation_mode": "banana"}, save=False)
        check("update_params_mode_invalid_ignored",
              svc.get_params(1)["separation_mode"] == "abs",
              str(svc.get_params(1).get("separation_mode")))

    streamer.shutdown()

    total = 30
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
