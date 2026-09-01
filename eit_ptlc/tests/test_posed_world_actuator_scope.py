"""`_actuator_overrides_for` 的作用域锁: 机构覆盖必须含**节点自身**, 不只是祖先。

为什么值得一条独立用例: `_put_payload` 用 `_posed_world(destination["parent"])` 求 dock 的
局部系, 而单件的目的父级**往往就是那只气缸节点本身** —— 收集瓶的父级是
`ST_COLLECT/ACTUATOR_COL_EXTEND`, 收集架是 `ACTUATOR_COL_LIFT`, 中转A的桶是
`…/ACTUATOR_PS_ROTATE`。只上溯严格祖先时这三个座位漏掉自己的行程: 编译器按缩回位烤
dock, 前端把同一个 dock 挂在伸出位的节点下, 落点整整差一个行程。

2026-08-07 实测: 收集瓶落位差 80.00mm(= PB10x80 全行程), 前端报"距落位目标 85.1mm"。
之所以以前没炸, 是因为源与目的两边都没摆姿态、误差自相抵消; 姿态账(C)只补了目的一侧的
子节点, 反而把抵消打破了。原地重现: 把 `chain: set[int] = {index}` 改回 `set()`, 本文件
第一条用例立刻红。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three_d" / "pipeline"))


class _FakeScene:
    """够 `_actuator_overrides_for` 用的最小场景: 路径→下标 + 下标→父下标。"""

    def __init__(self, names: list[str], parent: dict[int, int]):
        self._names = names
        self.parent = parent

    def index_of(self, path: str) -> int:
        try:
            return self._names.index(path)
        except ValueError as exc:
            raise KeyError(path) from exc


class _FakePosture:
    """只记账不算数 —— 本用例锁的是"问了哪几只执行器", 不是行程矩阵怎么算。"""

    def __init__(self):
        self.asked: list[tuple[str, float]] = []

    def actuator_override(self, spec, value):
        self.asked.append((str(spec["id"]), value))
        return {spec["id"]: value}


# 缩略版真实拓扑: 站座骑在气缸上, 气缸骑在滑车上
NAMES = [
    "ROOT",                                  # 0
    "ST_COLLECT",                            # 1
    "ST_COLLECT/ACTUATOR_COL_EXTEND",        # 2  ← 收集瓶的**目的父级**
    "ST_COLLECT/ACTUATOR_COL_EXTEND/BOTTLE",  # 3  ← 座位子节点
    "ST_OTHER",                              # 4
    "GRIPPER/FINGER_L",                      # 5  ← 联动组指节
]
PARENT = {0: None, 1: 0, 2: 1, 3: 2, 4: 0, 5: 0}
MANIFEST = {
    "actuators": [
        {"id": "col_extend", "node": "ST_COLLECT/ACTUATOR_COL_EXTEND"},
    ],
    "linkages": [
        {"id": "rob_grip_vial", "members": [{"node": "GRIPPER/FINGER_L"}]},
    ],
}


def _builder():
    from clip_compiler import ClipBuilder

    builder = object.__new__(ClipBuilder)  # 绕过 __init__ 的重资产装载
    builder.scene = _FakeScene(NAMES, PARENT)
    builder.posture = _FakePosture()
    builder.manifest = MANIFEST
    builder._actuator_value_of = lambda key: 1.0
    return builder


def test_node_itself_is_in_scope():
    """目的父级**就是**气缸时, 它自己的行程必须算进去(80mm 回归的锁)。"""
    builder = _builder()
    result = builder._actuator_overrides_for("ST_COLLECT/ACTUATOR_COL_EXTEND")
    assert builder.posture.asked == [("col_extend", 1.0)], (
        "气缸节点自己的行程被漏了 —— dock 会按缩回位烤, 前端挂在伸出位下, 差一个全行程")
    assert result, "应回传非空覆盖表"


def test_descendant_still_in_scope():
    """祖先链上的覆盖是原有行为, 不许被自身那一项挤掉。"""
    builder = _builder()
    builder._actuator_overrides_for("ST_COLLECT/ACTUATOR_COL_EXTEND/BOTTLE")
    assert builder.posture.asked == [("col_extend", 1.0)]


def test_unrelated_branch_untouched():
    builder = _builder()
    assert builder._actuator_overrides_for("ST_OTHER") == {}
    assert builder.posture.asked == []


def test_linkage_member_itself_is_rejected():
    """联动组的指节同样按"自身及祖先"判 —— 骑在指上的载荷是未实现的姿态账, 要硬死。"""
    from clip_compiler import CompileError

    builder = _builder()
    with pytest.raises(CompileError, match="联动组"):
        builder._actuator_overrides_for("GRIPPER/FINGER_L")


# --- 起手态那一半: 姿态账算得再准, 机构值取错档一样白搭 ------------------------------

def test_standalone_bottle_transfers_declare_extended_cylinder():
    """两条收集瓶取放脚本单编时必须自报 col_extend=1。

    出处是上层流程的排序(collect_load.yaml 的 collect.extend 紧排在本脚本前一行;
    collect_unload.yaml 的 collect.retract 排在本脚本之后), 两个方向取放时治具都是伸出的。
    漏掉就是"瓶按缩回位摆着、拿伸出位的示教点去抓": 2026-08-07 实测抓取修正 87.60mm
    (X 分量 −85.44mm ≈ PB10x80 全行程), 逼近 100mm 护栏, 观感是瓶被隔空吸进爪里。
    补上后与内联跑法逐字同值(取 21.14mm / 放 34.51mm)。
    """
    from clip_compiler import PHASE_ENTRY_STATE

    for operation in ("transfer_bottle_staging_b_to_collect",
                      "transfer_bottle_collect_to_staging_b"):
        entry = PHASE_ENTRY_STATE.get(operation)
        assert entry is not None, f"{operation} 缺起手态声明 —— 单编会退回 MECHANISM_HOME 的 0"
        values = {name: value for name, value, _why in entry.mechanisms}
        assert values.get("col_extend") == 1.0, f"{operation} 的 col_extend 起手必须是 1"


def test_every_phase_entry_mechanism_cites_a_source():
    """表里每条机构声明都要带出处 —— 与 PhaseEntry.why 同一条纪律, 不许写裸数字。"""
    from clip_compiler import PHASE_ENTRY_STATE

    for operation, entry in PHASE_ENTRY_STATE.items():
        for name, _value, why in entry.mechanisms:
            assert why.strip(), f"{operation} 的机构 {name} 没写出处"
