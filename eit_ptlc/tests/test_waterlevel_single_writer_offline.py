"""液位单写者离线测试 (服务 reload + CLI 并入真源的探测/分层写)
==================================================================
功能:
    验证"运行中检测服务 = calib 文件唯一写者"的两侧:
      - 服务 reload(): 从盘重读全部通道 (外部离线写盘后同步 / 安全阀)。
      - CLI commit_to_source(): 后端在线 → 拒绝写盘 (后端是唯一写者); 后端离线 →
        经 apply_commit 分层写盘 (判据+尺寸广播全通道, 位置仅本路)。无 ROI 拒写。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_single_writer_offline
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
from eit_ptlc.controller.waterlevel_store import ChannelConfig, save_channel_configs
from eit_ptlc.tools.wl_replay_tune import commit_to_source


def _cfg(rotation: float, diff: float) -> ChannelConfig:
    """已标定通道 (有 roi_frac → 可作全局层来源), wet_pixel_threshold 作可辨识判据值。"""
    return ChannelConfig(
        ChannelCalibration(rotation_angle_deg=rotation, roi_frac=(0.1, 0.1, 0.5, 0.5),
                           flow_direction="left_to_right"),
        WaterLevelDetectParams(wet_pixel_threshold=diff))


def _diff_on_disk(path: Path, ch: int) -> float:
    from eit_ptlc.controller.waterlevel_store import load_channel_configs
    return load_channel_configs(path)[ch].params.wet_pixel_threshold


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "calib.json"
        save_channel_configs(cfg_path, {1: _cfg(0.0, 10.0), 2: _cfg(3.0, 10.0)})

        # ---- 服务 reload: 外部改盘 → reload 同步进内存 ----
        svc = WaterLevelDetectService("127.0.0.1", 0, cfg_path, interval=1.0)
        save_channel_configs(cfg_path, {1: _cfg(0.0, 77.0), 2: _cfg(3.0, 10.0)})
        check("before_reload_stale", svc.get_params(1)["wet_pixel_threshold"] == 10.0,
              str(svc.get_params(1)["wet_pixel_threshold"]))
        svc.reload()
        check("reload_syncs", svc.get_params(1)["wet_pixel_threshold"] == 77.0,
              str(svc.get_params(1)["wet_pixel_threshold"]))

        # 复位盘为已知态供 CLI 测试
        save_channel_configs(cfg_path, {1: _cfg(0.0, 10.0), 2: _cfg(3.0, 10.0)})

        tuned_calib = ChannelCalibration(rotation_angle_deg=5.0, roi_frac=(0.1, 0.1, 0.5, 0.5),
                                         flow_direction="left_to_right")
        tuned_params = WaterLevelDetectParams(wet_pixel_threshold=99.0)

        # ---- 后端在线 → 拒绝写盘, 盘不变 ----
        wrote = commit_to_source(cfg_path, 1, tuned_calib, tuned_params,
                                 confirm=lambda: True, alive=lambda: True)
        check("refuse_when_backend_alive", wrote is False, str(wrote))
        check("alive_no_write", _diff_on_disk(cfg_path, 1) == 10.0, str(_diff_on_disk(cfg_path, 1)))

        # ---- confirm 取消 → 不写 ----
        wrote = commit_to_source(cfg_path, 1, tuned_calib, tuned_params,
                                 confirm=lambda: False, alive=lambda: False)
        check("cancel_no_write", wrote is False and _diff_on_disk(cfg_path, 1) == 10.0,
              str((wrote, _diff_on_disk(cfg_path, 1))))

        # ---- 后端离线 + 确认 → apply_commit 分层写: 判据广播全通道, 位置仅本路 ----
        wrote = commit_to_source(cfg_path, 1, tuned_calib, tuned_params,
                                 confirm=lambda: True, alive=lambda: False)
        check("offline_commit_ok", wrote is True, str(wrote))
        from eit_ptlc.controller.waterlevel_store import load_channel_configs
        disk = load_channel_configs(cfg_path)
        check("judgment_broadcast_ch1", disk[1].params.wet_pixel_threshold == 99.0,
              str(disk[1].params.wet_pixel_threshold))
        check("judgment_broadcast_ch2", disk[2].params.wet_pixel_threshold == 99.0,
              str(disk[2].params.wet_pixel_threshold))
        check("pose_only_ch1", round(disk[1].calib.rotation_angle_deg, 3) == 5.0,
              str(disk[1].calib.rotation_angle_deg))
        check("pose_ch2_untouched", round(disk[2].calib.rotation_angle_deg, 3) == 3.0,
              str(disk[2].calib.rotation_angle_deg))

        # ---- 无 ROI 的 tuned → 拒写 ----
        wrote = commit_to_source(
            cfg_path, 1, ChannelCalibration(rotation_angle_deg=0.0, roi_frac=None),
            WaterLevelDetectParams(), confirm=lambda: True, alive=lambda: False)
        check("no_roi_refused", wrote is False, str(wrote))

    total = 10
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_waterlevel_single_writer():
    """pytest 桥: 使 `pytest eit_ptlc/tests` 套件亦收集本 main 式离线测试。"""
    assert _run() == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
