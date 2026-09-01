#!/usr/bin/env python3
"""展缸/下料点位吸附基准预置轴向纠正脚本 (一次性数据迁移 v2, 入库留审计).

功能:
    纠正 v1 (preset_basis_shift) 的轴向映射错误。v1 假设 22.07mm 吸附偏移沿
    "板上缘方向"(竖直持板时 = +Z), 做了纯 Z 平移; 真机实测证明该偏移沿板宽方向,
    rotary-down 竖直持板时它是水平的插入轴(现象: Z 被错误抬高 22mm, 插入深度未加深)。
    本脚本在 post-v1 状态上施加纠正, 使净效果 = "沿各工位插入方向前进 22.0737mm, Z 回归原值":
        缸塔A P11-P14: y -= 22.0737, z -= 22.0737   (插入方向 -Y)
        缸塔B P15-P18: y += 22.0737, z -= 22.0737   (插入方向 +Y)
        下料  P22:     x += 22.0737, z -= 22.0737   (插入方向 +X)
    rx/ry/rz 与 joint 原样保留 (joint 由真机复核 capture->commit 刷新), 不盖 calibrated_at。

防重跑守卫:
    执行前逐点核对当前 xyz 与 post-v1 快照一致 (z 已抬 22.07, x/y 仍为原值),
    不一致(疑似已纠正过或点表已变更)则拒绝写盘并退出非 0;
    纠正后另断言 z 恢复为原始示教值。

用法:
    python -m eit_ptlc.tools.preset_basis_shift_v2 --dry-run   # 只打印 老pose -> 新pose
    python -m eit_ptlc.tools.preset_basis_shift_v2             # 全量校验通过后落盘

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

# post-v1 状态快照 (x, y, z): v1 已抬 z, x/y 仍为原始示教值 —— 防重跑锚
_EXPECTED_POST_V1_XYZ = {
    "P11": (-576.140015, -194.474686, -34.256732),
    "P12": (-575.140015, -193.674683, 147.465253),
    "P13": (-574.540039, -192.674683, 326.865262),
    "P14": (-572.939819, -192.074478, 506.865445),
    "P15": (-592.978027, 191.182343, -33.459575),
    "P16": (-591.477905, 190.882263, 146.540410),
    "P17": (-590.977905, 190.382446, 325.540372),
    "P18": (-589.477905, 189.682449, 507.040372),
    "P22": (564.924438, -423.338806, -70.291385),
}
# 原始示教 z (v1 执行前): 纠正后 z 必须回归到它
_ORIGINAL_Z = {
    "P11": -56.330429,
    "P12": 125.391556,
    "P13": 304.791565,
    "P14": 484.791748,
    "P15": -55.533272,
    "P16": 124.466713,
    "P17": 303.466675,
    "P18": 484.966675,
    "P22": -92.365082,
}
# 各点插入方向单位向量 (世界系): 缸塔A -Y, 缸塔B +Y, 下料 +X
_INSERT_DIR = {
    "P11": (0.0, -1.0, 0.0),
    "P12": (0.0, -1.0, 0.0),
    "P13": (0.0, -1.0, 0.0),
    "P14": (0.0, -1.0, 0.0),
    "P15": (0.0, 1.0, 0.0),
    "P16": (0.0, 1.0, 0.0),
    "P17": (0.0, 1.0, 0.0),
    "P18": (0.0, 1.0, 0.0),
    "P22": (1.0, 0.0, 0.0),
}
_EXPECTED_SHIFT_MM = 22.0737
_TOL_MM = 0.001

logger = logging.getLogger("preset_basis_shift_v2")


def _find_record(points_data: list, name: str) -> dict:
    """按 name 在点表数组中取记录, 缺失即抛错。"""
    for record in points_data:
        if str(record.get("name")) == name:
            return record
    raise KeyError(f"点表中缺少 {name}")


def _compute_shift(points_data: list) -> float:
    """从同一份点表现算 |P65.xyz - P64.xyz|, 并与期望模长核对。"""
    p64 = _find_record(points_data, "P64")["pose"]
    p65 = _find_record(points_data, "P65")["pose"]
    shift = math.sqrt(sum((float(p65[i]) - float(p64[i])) ** 2 for i in range(3)))
    if abs(shift - _EXPECTED_SHIFT_MM) > _TOL_MM:
        raise ValueError(
            f"P65-P64 基准差模长 {shift:.4f}mm 与期望 {_EXPECTED_SHIFT_MM}mm 不符, "
            "点表可能已变更, 拒绝继续")
    return shift


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
    parser = argparse.ArgumentParser(description="展缸/下料点位预置轴向纠正 (一次性 v2)")
    parser.add_argument("--dry-run", action="store_true", help="只打印 老pose -> 新pose, 不写盘")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    points_data = json.loads(_POINTS_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(points_data, list):
        logger.error("robot_points.json 顶层必须是数组")
        return 1

    try:
        shift = _compute_shift(points_data)
    except (KeyError, ValueError) as exc:
        logger.error("平移量计算失败: %s", exc)
        return 1
    logger.info("基准差模长 |P65-P64| = %.6f mm, 纠正 = 插入方向前进 + Z 回归", shift)

    # 防重跑守卫: 全部目标点当前 xyz 必须等于 post-v1 快照
    errors: list[str] = []
    for name, expected_xyz in _EXPECTED_POST_V1_XYZ.items():
        try:
            pose = _find_record(points_data, name)["pose"]
        except KeyError as exc:
            errors.append(str(exc))
            continue
        for axis, expected in zip("xyz", expected_xyz):
            idx = "xyz".index(axis)
            if abs(float(pose[idx]) - expected) > 1e-6:
                errors.append(
                    f"{name} 当前 {axis}={pose[idx]} 与 post-v1 快照 {expected} 不符 "
                    "(疑似已纠正过或点表已变更)")
    if len(errors) > 0:
        for line in errors:
            logger.error(line)
        logger.error("前置校验失败, 未做任何修改")
        return 1

    # 施加纠正: 插入方向 +shift, Z -shift; 逐点断言实际位移与 z 回归
    for name, direction in _INSERT_DIR.items():
        record = _find_record(points_data, name)
        old_pose = [float(v) for v in record["pose"]]
        delta = (direction[0] * shift, direction[1] * shift, -shift)
        new_xyz = [round(old_pose[i] + delta[i], 6) for i in range(3)]
        for i in range(3):
            applied = new_xyz[i] - old_pose[i]
            if abs(applied - delta[i]) > 1e-5:
                logger.error("%s 轴 %s 实际位移 %.6f 与期望 %.6f 不符, 中止",
                             name, "xyz"[i], applied, delta[i])
                return 1
        if abs(new_xyz[2] - _ORIGINAL_Z[name]) > 1e-5:
            logger.error("%s 纠正后 z=%.6f 未回归原始示教值 %.6f, 中止",
                         name, new_xyz[2], _ORIGINAL_Z[name])
            return 1
        for i in range(3):
            record["pose"][i] = new_xyz[i]
        logger.info(
            "%s: (%.6f, %.6f, %.6f) -> (%.6f, %.6f, %.6f)",
            name, old_pose[0], old_pose[1], old_pose[2],
            new_xyz[0], new_xyz[1], new_xyz[2])

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
