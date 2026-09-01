"""验收: 把每根直线轴推到 range_mm 两端, 算滑块是否还留在它自己的导轨里。

为什么需要它: `gen_twin_manifest.check_axis_limits` 查的是 range_mm 的**跨度**
(不小于控制侧示教值、不大于 stroke_mm), 查不到**位置**。跨度对而位置错的轴照样会
把滑车推出导轨 —— 2026-08-04 就是这么抓到 axis_3y 的: 跨度 319 完全正确, 但配上
zero_offset 的 0.0 占位后, 动作页拉到示教上界 245 会让滑块冲出导轨 139.85 mm。
(修法不是改 range, 而是由几何+控制侧联立推出 zero_offset 首值, 见 rig_map axis_3y。)

判据(逐字镜像 web/src/three-d/anim/MachineStateDriver.js 的 setAxisMm):
    offset(m) = (mm - zeroOffsetMm) * sign * mmToUnit
    位置       = 加载态 + axis方向 * offset
把 mm 取 range_mm 两端, 得滑块在导轨轴向上的两个极限落点, 与导轨条实测区间比对。

用法:
    python verify_axis_travel.py            # 退出码 0 = 全部在导轨内
    python verify_axis_travel.py --tol 2    # 收紧容差

⚠ 下表 GEOMETRY 是在 `work/machine.full.glb`(前端加载的那份, 零位 = 其加载态)上
逐顶点实测的 mm 值, 坐标系是 **Blender 世界系**。三个注意:
  1. 只有地轨的滑车在 full 链里被挪到了参考轨位, 其余十根都还停在 CAD 位 —— 所以量
     raw 与量 full 只有地轨会不一致(静态件两份逐件相同, 可用来核对坐标系);
  2. glTF→Blender 方向映射: gl(1,0,0)→+X, gl(0,1,0)→+Z, gl(0,0,1)→**−Y**;
  3. **从 SolidWorks 重导 GLB 后 OCC 编号可能重排**(同 docs/CLAUDE.md 第 29 条),
     必须重新认一遍导轨条与滑块块再信任本表。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

#: 轴 -> (Blender 轴向索引, gl→bl 方向符号, 导轨条 R0, R1, 滑块 C0, C1, 端块余量 m, 依据件号)
#: 端块余量 m = (导轨净长 − 滑块长 − stroke_mm) / 2, 是推算量而非实测量, 故容差按它取。
GEOMETRY: dict[str, tuple] = {
    "axis_11y": (0, +1, -701.58, 448.42, -316.43, -146.43, 40.000, "19.1.7 钢带 / 19.1.14 滑台板"),
    "axis_1z":  (2, +1, -726.00, 85.00, -668.77, -467.28, 4.875, "133.1.7 导轨 / 133.1.5.1.4 滑台"),
    "axis_2z":  (2, +1, -726.00, 85.00, -663.14, -461.64, 4.875, "同 1Z 的 .001 副本"),
    # ⚠ 2026-08-05: 3Y 与 4X 的**身份**互换了(此前把带上样针的同步带轴叫 3Y、把带物料盘的
    #   CFC30B 叫 4X, 认反了; 判据见 rig_map.yaml axis_4x 条目顶部与 AXIS_ZERO_CALIBRATION §5)。
    #   几何数据本身没变, 只是换了 key —— 本表恰好也是那次订正的物证之一: X 族轴(4X/6X/9X)
    #   的 Blender 轴索引恒为 1、Y 族(3Y/7Y/8Y/11Y)恒为 0, 订正前只有这两行违例且互为对方。
    "axis_4x":  (1, -1, -246.10, 103.90, -113.95, -82.95, 0.000, "_LRM9RLX350 导轨 / _LRM9BK 滑块"),
    "axis_3y":  (0, +1, 822.42, 1238.42, 906.04, 1012.04, 5.000, "181.1.1.1 导轨 / 181.2.1.5 滑块"),
    "axis_5z":  (2, +1, 158.50, 338.50, 181.01, 212.01, 0.000, "_LRM9RLX180 导轨 / _LRM9BK 滑块"),
    "axis_6x":  (1, -1, -306.10, 133.90, -281.10, -191.10, 25.000, "2.1.7 导轨 / 2.1.15 滑块"),
    "axis_7y":  (0, +1, 922.42, 1162.42, 1047.42, 1137.42, 25.000, "138.1.3 导轨 / 138.1.41 滑块"),
    "axis_8y":  (0, +1, 532.42, 1222.42, 556.77, 672.77, 12.000, "82.1.4 导轨 / 82.1.5.1.5 滑块"),
    "axis_9x":  (1, -1, 107.90, 623.90, 112.90, 218.90, 5.000, "178.1.1.1 导轨 / 178.2.1.5 滑块"),
    "axis_10z": (2, +1, 281.00, 471.00, 356.00, 446.00, 25.000, "18.1.13 导轨 / 18.1.42 滑块"),
}

#: 容差缺省 5 mm —— 端块余量 m 是推算量, 认错导轨条或滑块块的误差同量级。
#: 已知残差: axis_2z 3.36(几何窗口比控制侧限位短 8.2, 按覆盖控制侧优先),
#:           axis_8y 2.52(gcode 板原点 −74.982 比几何下界低 9.5, 按 gcode 优先)。
DEFAULT_TOL_MM = 5.0

DEFAULT_MANIFEST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "models", "device-manifest.official-cr5.json"
)


def travel_span(axis: dict) -> tuple[float, float]:
    """把该轴推到 range_mm 两端, 返回滑块在导轨轴向上的 [最小, 最大] 落点(mm)。"""
    _idx, dir_sign, _r0, _r1, c0, c1, _m, _src = GEOMETRY[axis["id"]]
    lo, hi = axis["rangeMm"]
    zero = float(axis.get("zeroOffsetMm", 0.0))
    sign = float(axis.get("sign", 1))
    ends = [(mm - zero) * sign * dir_sign for mm in (lo, hi)]
    return min(c0 + d for d in ends), max(c1 + d for d in ends)


def main() -> int:
    parser = argparse.ArgumentParser(description="验直线轴推到 range 两端时滑块是否仍在导轨内")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="device-manifest 路径")
    parser.add_argument("--tol", type=float, default=DEFAULT_TOL_MM, help="出轨容差(mm)")
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as handle:
        axes = json.load(handle)["axes"]

    print(f"{'轴':<10}{'推到两端的滑块落点':>30}{'导轨条':>24}{'出轨mm':>8}  依据")
    worst = 0.0
    failures: list[str] = []
    unknown: list[str] = []
    for axis in axes:
        axis_id = axis["id"]
        if axis_id not in GEOMETRY:
            unknown.append(axis_id)
            continue
        _idx, _dir, r0, r1, _c0, _c1, _m, src = GEOMETRY[axis_id]
        low, high = travel_span(axis)
        over = max(r0 - low, high - r1, 0.0)
        worst = max(worst, over)
        if over > args.tol:
            failures.append(f"{axis_id} 出轨 {over:.2f}mm(容差 {args.tol}mm)")
        print(
            f"{axis_id:<10}{f'[{low:9.2f}, {high:9.2f}]':>30}"
            f"{f'[{r0:8.2f},{r1:8.2f}]':>24}{over:8.2f}  {src}"
        )

    for axis_id in unknown:
        # 新轴没量过几何就静默放行等于假绿灯, 必须显式挡住
        failures.append(f"{axis_id} 在 GEOMETRY 表里没有实测条目, 请先量导轨与滑块")

    print(f"\n最大出轨 {worst:.2f} mm / 容差 {args.tol} mm")
    if failures:
        for line in failures:
            print(f"失败: {line}")
        return 1
    print("通过: 全部直线轴在 range_mm 两端都留在自己的导轨内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
