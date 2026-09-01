#!/usr/bin/env python3
"""展缸/下料点位吸附基准预置脚本 (一次性数据迁移, 入库留审计).

功能:
    刮板位取放板统一到 P65(板中心基准)后, 展缸 P11-P18 与下料 P22 的示教仍
    建立在旧"偏下"基准上, 需整体抬高一个基准差模长。这些工位均为 rotary-down
    竖直持板且工艺要求板上缘朝上, 板面"上缘方向" = 机器人系 +Z, 故修正为纯 Z 平移:
        新 pose.z = 旧 pose.z + |P65.xyz - P64.xyz|  (约 22.0737 mm)
    rx/ry/rz 与 joint 原样保留 (joint 由真机复核 capture->commit 刷新),
    不盖 calibrated_at (数值预置不是现场标定)。

防重跑守卫:
    执行前逐点核对当前 z 与预期原值一致, 不一致(疑似已执行过或点表已变更)则
    拒绝写盘并退出非 0。

用法:
    python -m eit_ptlc.tools.preset_basis_shift --dry-run   # 只打印 老pose -> 新pose
    python -m eit_ptlc.tools.preset_basis_shift             # 全量校验通过后落盘

返回:
    退出码 0 = 成功(或 dry-run 通过); 1 = 前置/回归校验失败, 未写盘。
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
# 与 app.yaml point_source_version 一致 (离线契约测试同款写法)
_SOURCE_VERSION = "v0.11"

# 待平移点与其预期原始 z 值 (2026-07-25 快照): 一次性迁移的防重跑锚
_EXPECTED_ORIGINAL_Z = {
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
# 基准差模长的期望值 (P65-P64 的 xyz 模), 用于防止点表被改后误算平移量
_EXPECTED_SHIFT_MM = 22.0737
_TOL_MM = 0.001

logger = logging.getLogger("preset_basis_shift")


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
    parser = argparse.ArgumentParser(description="展缸/下料点位吸附基准预置 (一次性)")
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
    logger.info("基准差模长 |P65-P64| = %.6f mm, 修正方向 = 机器人系 +Z", shift)

    # 防重跑守卫: 全部目标点的当前 z 必须等于预期原值
    errors: list[str] = []
    for name, expected_z in _EXPECTED_ORIGINAL_Z.items():
        try:
            pose = _find_record(points_data, name)["pose"]
        except KeyError as exc:
            errors.append(str(exc))
            continue
        if abs(float(pose[2]) - expected_z) > 1e-6:
            errors.append(
                f"{name} 当前 z={pose[2]} 与预期原值 {expected_z} 不符 (疑似已执行过预置)")
    if len(errors) > 0:
        for line in errors:
            logger.error(line)
        logger.error("前置校验失败, 未做任何修改")
        return 1

    # 应用纯 Z 平移并逐点断言实际位移量
    for name in _EXPECTED_ORIGINAL_Z:
        record = _find_record(points_data, name)
        old_pose = [float(v) for v in record["pose"]]
        new_z = round(old_pose[2] + shift, 6)
        applied = abs(new_z - old_pose[2])
        if abs(applied - shift) > _TOL_MM:
            logger.error("%s 实际位移 %.4f 与平移量 %.4f 不符, 中止", name, applied, shift)
            return 1
        record["pose"][2] = new_z
        logger.info(
            "%s: z %.6f -> %.6f (dx=dy=0, 姿态/joint 不变)", name, old_pose[2], new_z)

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
    logger.info("提醒: joint 未刷新, allowed_motion 已收窄 move_l, 真机复核后逐点 capture->commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
