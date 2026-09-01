"""逐件闭合值消费端(ClipBuilder._close_value_for)的判定锁。

真源在 fit_item_grips(瓶颈=销面贴颈 0.25432, 粉桶=弧口袋摇篮同心 0.817195, 经
manifest payload.closeValue 透传), 编译器只透传+校验。这里锁三条判定:
  1. 逐件值直通 + 越界硬死;
  2. 有 grabFeature 却缺 closeValue 硬死 —— gen_twin_manifest 白名单断链的症状,
     决不许静默退 holdValue(粉桶退 0.101 弧臂只动 1.26mm, 正是 2026-08-07 用户报障);
  3. 无特征载荷(整板托盘/plate96)显式回落 manifest holdValue, 与旧行为逐字节一致。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three_d" / "pipeline"))

MANIFEST = {"linkages": [
    {"id": "rob_grip_vial", "inputRange": [0, 1], "holdValue": 0.101},
]}


def _call(record: dict) -> float:
    from clip_compiler import ClipBuilder

    builder = object.__new__(ClipBuilder)  # _close_value_for 只读 manifest 与 record
    builder.manifest = MANIFEST
    return ClipBuilder._close_value_for(builder, record)


def test_per_payload_close_passthrough():
    assert _call({"id": "X", "grip": "rob_grip_vial",
                  "grabFeature": "neck", "closeValue": 0.25432}) == 0.25432
    assert _call({"id": "X", "grip": "rob_grip_vial",
                  "grabFeature": "barrel", "closeValue": 0.817195}) == 0.817195


def test_out_of_range_close_dies():
    from clip_compiler import CompileError

    with pytest.raises(CompileError):
        _call({"id": "X", "grip": "rob_grip_vial", "grabFeature": "neck", "closeValue": 1.5})
    with pytest.raises(CompileError):
        _call({"id": "X", "grip": "rob_grip_vial", "grabFeature": "neck", "closeValue": 0.0})


def test_feature_without_close_dies():
    from clip_compiler import CompileError

    with pytest.raises(CompileError):
        _call({"id": "X", "grip": "rob_grip_vial", "grabFeature": "neck", "closeValue": None})


def test_fallback_to_hold_for_trays():
    assert _call({"id": "T", "grip": "rob_grip_vial",
                  "grabFeature": None, "closeValue": None}) == 0.101
