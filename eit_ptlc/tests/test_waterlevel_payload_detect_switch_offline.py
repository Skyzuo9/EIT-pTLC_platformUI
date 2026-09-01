"""香橙派 --no-detect 开关冒烟测试 (P3.1)
==========================================
功能:
    验证 MultiChannelManager 的 detect_enabled 开关:
      - detect_enabled=False → 字段为 False (CAPTURE 只抓帧不检测)
      - 默认 → True (保持旧行为, 可回退)
    仅构造冒烟 (不开相机/不连 MQTT); run() 主循环依赖相机+显示器, 不在离线范围。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_payload_detect_switch_offline
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PAYLOAD = (Path(__file__).resolve().parent.parent
            / "driver" / "water_level_payload" / "water_level_8ch_compress_mqtt.py")
_spec = importlib.util.spec_from_file_location("wl_payload", _PAYLOAD)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MultiChannelManager = _mod.MultiChannelManager


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # detect_enabled=False: 只抓帧不检测 (enable_mqtt=False 避免连 broker; 不 start_capture 不开相机)
    mgr_off = MultiChannelManager(["/dev/null"], 15.0, enable_mqtt=False, detect_enabled=False)
    check("detect_off", mgr_off.detect_enabled is False, str(mgr_off.detect_enabled))
    check("channels_built", mgr_off.num_channels == 1, str(mgr_off.num_channels))

    # 默认保持检测开 (可回退)
    mgr_def = MultiChannelManager(["/dev/null"], 15.0, enable_mqtt=False)
    check("detect_default_on", mgr_def.detect_enabled is True, str(mgr_def.detect_enabled))

    total = 3
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
