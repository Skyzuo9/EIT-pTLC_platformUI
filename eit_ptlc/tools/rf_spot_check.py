"""rf_spot_check —— Rf spot 检测调试叠加 CLI。

相机锁定后拿真 UV 板图肉眼核验 spot 分割/排序/Rf。用法::

    python -m eit_ptlc.tools.rf_spot_check plate.png \\
        --x 100 --y 80 --w 900 --h 900 --origin-frac 0.9 --d-f 0.8 \\
        [--axis v] [--direction -1] [--out overlay.png]
"""

from __future__ import annotations

import argparse
import sys

from eit_ptlc.controller import rf_measure


def render_overlay(image_bgr, plate_bbox, results, *, origin_frac, axis="v"):
    """在图上画 bbox / 原点线 / 斑点圈 + Rf 文本, 返回叠加图。"""
    import cv2

    out = image_bgr.copy()
    x, y, w, h = plate_bbox["x"], plate_bbox["y"], plate_bbox["w"], plate_bbox["h"]
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
    # 原点线 (沿非展开轴画一条)
    if axis == "v":
        oy = int(y + origin_frac * h)
        cv2.line(out, (x, oy), (x + w, oy), (255, 0, 0), 2)
    else:
        ox = int(x + origin_frac * w)
        cv2.line(out, (ox, y), (ox, y + h), (255, 0, 0), 2)
    for r in results:
        cx, cy = int(x + r.u * w), int(y + r.v * h)
        cv2.circle(out, (cx, cy), 10, (0, 255, 255), 2)
        label = f"Rf={r.rf:.2f}" if r.rf is not None else "Rf=NA"
        cv2.putText(out, label, (cx + 12, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rf spot 检测调试叠加")
    p.add_argument("image")
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--w", type=int, required=True)
    p.add_argument("--h", type=int, required=True)
    p.add_argument("--origin-frac", type=float, required=True)
    p.add_argument("--d-f", type=float, required=True)
    p.add_argument("--axis", default="v", choices=["u", "v"])
    p.add_argument("--direction", type=int, default=-1, choices=[-1, 1])
    p.add_argument("--out", default="rf_overlay.png")
    args = p.parse_args(argv)

    import cv2

    img = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if img is None:
        print(f"无法读取图像: {args.image}", file=sys.stderr)
        return 2
    bbox = {"x": args.x, "y": args.y, "w": args.w, "h": args.h}
    results = rf_measure.analyze_rf(
        img, bbox, origin_frac=args.origin_frac, d_f=args.d_f,
        axis=args.axis, direction=args.direction,
    )
    for r in results:
        rf_str = f"{r.rf:.3f}" if r.rf is not None else "NA"
        print(f"idx={r.index} u={r.u:.3f} v={r.v:.3f} d_s={r.d_s:.3f} rf={rf_str}")
    overlay = render_overlay(img, bbox, results, origin_frac=args.origin_frac, axis=args.axis)
    cv2.imwrite(args.out, overlay)
    print(f"overlay={args.out} spots={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
