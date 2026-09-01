#!/usr/bin/env python3
"""展缸/下料点位吸附基准预置横向分量补齐脚本 (一次性数据迁移 v3, 入库留审计).

功能:
    补齐 v2 遗漏的横向分量。基准差 (P65-P64) = (20.9, 7.1)mm 是刚体向量, 会随
    手腕 yaw 整体旋转: 正确的世界系修正 = Rz(目标点rz - P64rz) · (vx, vy)。
    缸塔法兰 yaw 与刮板位差约 ±90°, 映射结果为 塔A (+6.80, -21.00) / 塔B (-6.85, +20.98)
    —— 其中 ~21 是插入分量 (v2 给 22.07, 差 1.07mm, 真机看不出), ±6.8 是横向分量
    (v2 给 0, 即真机实测的"左右偏了一些"); 下料 P22 yaw 与刮板位几乎相同, 应得
    (20.96, +6.92), v2 给 (22.07, 0) 同缺 +6.9 横向。
    佐证: 用实际示教 yaw 差旋转 (20.9, 7.1) 恰得 (6.8, -21.0) 圆整值, 与 P19/P20
    的 20.9/7.1 同源, 即该旋转关系正是原始设计手输偏移的构造方式。

做法:
    从原始示教值锚定重算 (不在 v2 结果上累积): 新 xy = 原始 xy + Rz(dyaw)·(vx, vy),
    z 维持原始示教值 (v 的 z 分量 0.16mm 低于示教分辨率, 忽略)。
    rx/ry/rz 与 joint 原样保留, 不盖 calibrated_at。

防重跑守卫:
    执行前逐点核对当前 xyz 与 post-v2 快照一致, 不符即拒绝写盘并退出非 0。

用法:
    python -m eit_ptlc.tools.preset_basis_shift_v3 --dry-run   # 只打印 老pose -> 新pose
    python -m eit_ptlc.tools.preset_basis_shift_v3             # 全量校验通过后落盘

返回:
    退出码 0 = 成功(或 dry-run 通过); 1 = 前置/回归校验失败, 未写盘.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import tempfile
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402

_POINTS_FILE = _PKG / "config" / "points" / "robot" / "robot_points.json"
_META_FILE = _PKG / "config" / "points" / "robot" / "robot_points_meta.json"
_SOURCE_VERSION = "v0.11"

# post-v2 状态快照 (x, y, z): 防重跑锚
_EXPECTED_POST_V2_XYZ = {
    "P11": (-576.140015, -216.548383, -56.330429),
    "P12": (-575.140015, -215.748380, 125.391556),
    "P13": (-574.540039, -214.748380, 304.791565),
    "P14": (-572.939819, -214.148175, 484.791748),
    "P15": (-592.978027, 213.256040, -55.533272),
    "P16": (-591.477905, 212.955960, 124.466713),
    "P17": (-590.977905, 212.456143, 303.466675),
    "P18": (-589.477905, 211.756146, 484.966675),
    "P22": (586.998135, -423.338806, -92.365082),
}
# 原始示教值 (v1 执行前) —— 锚定基准, 新值 = 原始 xy + 映射向量, z = 原始 z
_ORIGINAL_XYZ = {
    "P11": (-576.140015, -194.474686, -56.330429),
    "P12": (-575.140015, -193.674683, 125.391556),
    "P13": (-574.540039, -192.674683, 304.791565),
    "P14": (-572.939819, -192.074478, 484.791748),
    "P15": (-592.978027, 191.182343, -55.533272),
    "P16": (-591.477905, 190.882263, 124.466713),
    "P17": (-590.977905, 190.382446, 303.466675),
    "P18": (-589.477905, 189.682449, 484.966675),
    "P22": (564.924438, -423.338806, -92.365082),
}
# 期望的映射向量分量符号与量级 (粗核对, 防 yaw 读取/符号错误):
#   塔A x≈+6.8 y≈-21.0; 塔B x≈-6.8 y≈+21.0; P22 x≈+21.0 y≈+6.9
_EXPECTED_MAPPED_SIGN = {
    "P11": (1, -1), "P12": (1, -1), "P13": (1, -1), "P14": (1, -1),
    "P15": (-1, 1), "P16": (-1, 1), "P17": (-1, 1), "P18": (-1, 1),
    "P22": (1, 1),
}
_EXPECTED_SHIFT_MM = 22.0737
_TOL_MM = 0.001

logger = logging.getLogger("preset_basis_shift_v3")


def _find_record(points_data: list, name: str) -> dict:
    """按 name 在点表数组中取记录, 缺失即抛错。"""
    for record in points_data:
        if str(record.get("name")) == name:
            return record
    raise KeyError(f"点表中缺少 {name}")


def _basis_vector(points_data: list) -> tuple[float, float, float]:
    """从点表现算基准差向量 (P65-P64 的 x/y 分量) 与 P64 的 yaw, 并核对模长。"""
    p64 = _find_record(points_data, "P64")["pose"]
    p65 = _find_record(points_data, "P65")["pose"]
    vx = float(p65[0]) - float(p64[0])
    vy = float(p65[1]) - float(p64[1])
    norm = math.hypot(vx, vy)
    if abs(norm - _EXPECTED_SHIFT_MM) > 0.02:
        raise ValueError(
            f"P65-P64 基准差水平模长 {norm:.4f}mm 与期望 {_EXPECTED_SHIFT_MM}mm 不符, "
            "点表可能已变更, 拒绝继续")
    return vx, vy, float(p64[5])


def _validate_with_registry(points_data: list) -> str:
    """把改后的点表落临时文件, 用 PointRegistry.load 全量校验, 通过才返回落盘文本。"""
    points_text = json.dumps(points_data, ensure_ascii=False)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(points_text)
            tmp_path = Path(f.name)
        PointRegistry.load(tmp_path, source_version=_SOURCE_VERSION, meta_path=_META_FILE)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return points_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="展缸/下料点位预置横向分量补齐 (一次性 v3)")
    parser.add_argument("--dry-run", action="store_true", help="只打印 老pose -> 新pose, 不写盘")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    points_data = json.loads(_POINTS_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(points_data, list):
        logger.error("robot_points.json 顶层必须是数组")
        return 1

    try:
        vx, vy, yaw_ref = _basis_vector(points_data)
    except (KeyError, ValueError) as exc:
        logger.error("基准差向量计算失败: %s", exc)
        return 1
    logger.info("基准差向量 v = (%.6f, %.6f) mm, 参考 yaw(P64) = %.6f deg", vx, vy, yaw_ref)

    # 防重跑守卫: 全部目标点当前 xyz 必须等于 post-v2 快照
    errors: list[str] = []
    for name, expected_xyz in _EXPECTED_POST_V2_XYZ.items():
        try:
            pose = _find_record(points_data, name)["pose"]
        except KeyError as exc:
            errors.append(str(exc))
            continue
        for idx, expected in enumerate(expected_xyz):
            if abs(float(pose[idx]) - expected) > 1e-6:
                errors.append(
                    f"{name} 当前 {'xyz'[idx]}={pose[idx]} 与 post-v2 快照 {expected} 不符 "
                    "(疑似已纠正过或点表已变更)")
    if len(errors) > 0:
        for line in errors:
            logger.error(line)
        logger.error("前置校验失败, 未做任何修改")
        return 1

    # 逐点: 新 xy = 原始 xy + Rz(点rz - P64rz)·(vx, vy), z = 原始 z
    for name, original in _ORIGINAL_XYZ.items():
        record = _find_record(points_data, name)
        old_pose = [float(v) for v in record["pose"]]
        dyaw = math.radians(old_pose[5] - yaw_ref)
        mapped_x = vx * math.cos(dyaw) - vy * math.sin(dyaw)
        mapped_y = vx * math.sin(dyaw) + vy * math.cos(dyaw)
        # 模长守恒 + 分量符号粗核对, 防 yaw 读取/符号错误
        if abs(math.hypot(mapped_x, mapped_y) - math.hypot(vx, vy)) > _TOL_MM:
            logger.error("%s 映射后模长漂移, 中止", name)
            return 1
        sign_x, sign_y = _EXPECTED_MAPPED_SIGN[name]
        if mapped_x * sign_x <= 0 or mapped_y * sign_y <= 0:
            logger.error("%s 映射向量 (%.3f, %.3f) 分量符号与期望 (%d, %d) 不符, 中止",
                         name, mapped_x, mapped_y, sign_x, sign_y)
            return 1
        new_xyz = [
            round(original[0] + mapped_x, 6),
            round(original[1] + mapped_y, 6),
            round(original[2], 6),
        ]
        for i in range(3):
            record["pose"][i] = new_xyz[i]
        logger.info(
            "%s: dyaw=%.3f deg, 映射=(%.4f, %.4f) | (%.6f, %.6f, %.6f) -> (%.6f, %.6f, %.6f)",
            name, math.degrees(dyaw), mapped_x, mapped_y,
            old_pose[0], old_pose[1], old_pose[2], new_xyz[0], new_xyz[1], new_xyz[2])

    if args.dry_run is True:
        logger.info("dry-run: 未写盘")
        return 0

    try:
        points_text = _validate_with_registry(points_data)
    except Exception as exc:  # 校验失败必须留现场, 不写盘
        logger.error("PointRegistry 全量校验失败, 未写盘: %s", exc)
        return 1
    _POINTS_FILE.write_text(points_text, encoding="utf-8")
    logger.info("已写盘 %s (单行 JSON, %d 个点)", _POINTS_FILE, len(points_data))
    logger.info("提醒: joint 未刷新, allowed_motion 维持 move_l, 真机复核后逐点 capture->commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
