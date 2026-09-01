"""液位标定几何纯函数离线测试
============================================
- angle_to_make_line_vertical: 用同一 cv2.getRotationMatrix2D 复核 —— 把返回增量角作用到方向
  向量上, 结果应竖直 (x 分量≈0)。此举把符号约定钉死在 cv2 上。
- box_to_roi_frac: 与 ChannelCalibration.roi_pixels 往返一致。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_geom_offline
"""

from __future__ import annotations

import sys

import cv2

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    angle_to_make_line_vertical,
    box_to_roi_frac,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) 角度: 作用增量角到方向向量后应竖直 (x≈0)
    for dx, dy in [(10.0, 1.0), (10.0, -1.0), (1.0, 10.0), (-3.0, 20.0), (5.0, 5.0), (-5.0, 5.0)]:
        delta = angle_to_make_line_vertical(dx, dy)
        M = cv2.getRotationMatrix2D((0.0, 0.0), delta, 1.0)
        vx = M[0, 0] * dx + M[0, 1] * dy      # 旋转后向量的 x 分量
        check(f"vertical_dx{dx}_dy{dy}", abs(vx) < 1e-6, f"delta={delta} vx={vx}")

    # 2) 已竖直的线增量角为 0
    check("already_vertical", abs(angle_to_make_line_vertical(0.0, 10.0)) < 1e-9,
          str(angle_to_make_line_vertical(0.0, 10.0)))

    # 3) box_to_roi_frac 与 roi_pixels 往返一致
    rot_w, rot_h = 400, 480
    frac = box_to_roi_frac(200, 0, 80, 249, rot_w, rot_h)
    calib = ChannelCalibration(roi_frac=frac)
    px = calib.roi_pixels(rot_w, rot_h)
    check("roi_roundtrip", px == (200, 0, 80, 249), f"frac={frac} px={px}")

    total = 6 + 1 + 1
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
