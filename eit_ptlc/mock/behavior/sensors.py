"""虚拟 PLC 的输入信号合成 (阶段③)
==================================
功能:
    沙盒里**唯一**写 IX8~IX12 输入字节的地方。此前这些字节恒 0, 于是
    feedlift.preflight 必报空仓、photoscrape.wait_rot 必超时、物料在位对账全是假信号。

    合成的数据源都是沙盒内已有的"现场事实", 不编造 —— 逐位的出处见 BIT_SPECS 表。

单一真源纪律:
    位定义只在 BIT_SPECS 里写一遍。合成 (compose) 与观测 (decode_bytes) 共读这张表,
    于是"动作看到的位"与"诊断面板显示的位"结构上不可能对不上。
    要新增一位, 只加一条 BitSpec 并在 compose_bits 里给出取值, 不要在别处再解一次位。

单写者纪律:
    整字节合成后一次写入。若多处各写各位, 后写的会把先写的抹掉 (读-改-写竞态),
    这正是 run_tank_drain_fsm 那段数组读-改-写注释警告过的同一类坑。
    本模块是**只读合成器**: 它读模型与账本, 绝不反过来改它们
    (板堆的增减在 behavior/feedlift.py 里, 那是物理事件的属主)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from eit_ptlc.controller.feedlift_count import _IX8_PHOTO_BIT, _IX8_PROX_BIT
from eit_ptlc.mock.plc_server import mock_write

log = logging.getLogger(__name__)

_TICK_S = 0.05

#: 沙盒合成的全部输入字节 (run_sensor_loop 每拍整字节写这五个)
SENSOR_BYTES = ("IX8", "IX9", "IX10", "IX11", "IX12")

#: 恒 0 的位段与依据 —— 供观测面如实标注"这里不是没信号, 是真机就没接"
CONSTANT_ZERO = (
    ("IX11.0-7 / IX12.0-3", "料库 12 路检测: 2026-07-26 实测真机该 12 路未供电, "
                            "与物理零耦合; 沙盒复刻真机而非复刻愿望"),
)


@dataclass(frozen=True)
class BitSpec:
    """一个具名输入位的定义.

    参数:
        name: 位标识 (诊断面板与测试用的稳定键)
        label: PLC 侧的信号名 (与点表/ST 逐字相同, 现场能对上)
        byte: 所属输入字节名; bit: 位号 (0-7)
        source: 该位在沙盒里由什么推导 —— 出处而非取值
    """
    name: str
    label: str
    byte: str
    bit: int
    source: str


#: 位字典 (来自 config/material_topology.yaml、config/plc_nodes.yaml:175-187
#: 与 config/manual_points.yaml 的传感器声明; 位号与 PLC 的 %IX 地址逐字对应)
BIT_SPECS: tuple[BitSpec, ...] = (
    BitSpec("collect_bottle", "收集平台瓶子有无传感器", "IX8", 1, "物料账本 payload_seat"),
    BitSpec("staging_b", "收集平台暂存工位 (中转B)", "IX8", 2, "物料账本 staging_occupancy"),
    BitSpec("feed_photo", "玻璃升降光电开关1", "IX8", _IX8_PHOTO_BIT["feed"],
            "板堆模型 photo(feed): 顶板是否升到取料位"),
    BitSpec("waste_photo", "玻璃升降光电开关2", "IX8", _IX8_PHOTO_BIT["waste"],
            "板堆模型 photo(waste): 顶板是否升到接料位"),
    BitSpec("feed_proximity", "玻璃升降接近开关1 (仓底有板)", "IX8", _IX8_PROX_BIT["feed"],
            "板堆模型 proximity(feed): 上料仓张数 > 0"),
    BitSpec("waste_proximity", "玻璃升降接近开关2 (仓底有板)", "IX8", _IX8_PROX_BIT["waste"],
            "板堆模型 proximity(waste): 下料仓张数 > 0"),
    BitSpec("feed_rack_1", "上样料架检测1", "IX9", 0, "现场事实 (无软件账, 可经 /api/sim/state 设)"),
    BitSpec("feed_rack_2", "上样料架检测2", "IX9", 1, "现场事实 (无软件账, 可经 /api/sim/state 设)"),
    BitSpec("ps_rotate_home", "翻料缸原点", "IX9", 6, "manual FSM 的 ps_rotate fb_off (同一物理源镜像)"),
    BitSpec("ps_rotate_work", "翻料缸动点", "IX9", 7, "manual FSM 的 ps_rotate fb_on (同一物理源镜像)"),
    BitSpec("ps_press_up", "刮板拍照下压气缸上位", "IX10", 0,
            "manual FSM 的 ps_press fb_off (该缸未接下压到位传感器, 故只有上位)"),
    BitSpec("staging_a", "刮板拍照暂存工位 (中转A)", "IX10", 2, "物料账本 staging_occupancy"),
    BitSpec("tool_detect_1", "机器人工具检测1", "IX12", 4, "机器人权威工具态 mounted_tool (推定极性)"),
    BitSpec("tool_detect_2", "机器人工具检测2", "IX12", 5, "机器人权威工具态 mounted_tool (推定极性)"),
    BitSpec("tool_detect_3", "机器人工具检测3", "IX12", 6, "机器人权威工具态 mounted_tool (推定极性)"),
)

BIT_BY_NAME = {spec.name: spec for spec in BIT_SPECS}


def _bit(value: int, index: int, on: bool) -> int:
    """把整数 value 的第 index 位置成 on."""
    if on:
        return value | (1 << index)
    return value & ~(1 << index)


def fold_bits(bits: dict) -> dict:
    """把具名位折成整字节 (纯函数; 未列出的字节为 0).

    参数:
        bits: {位名: bool}
    返回:
        Dict {字节名: 0..255}
    """
    out = {name: 0 for name in SENSOR_BYTES}
    for spec in BIT_SPECS:
        out[spec.byte] = _bit(out[spec.byte], spec.bit, bool(bits.get(spec.name)))
    return out


def decode_bytes(values: dict) -> list:
    """把已写入的输入字节按 BIT_SPECS 反解成具名位 (供只读观测面).

    参数:
        values: {字节名: 整数值}
    返回:
        List[dict], 每项 {name, label, byte, bit, on, source}; 字节缺席时 on 为 None

    与 fold_bits 共读同一张表, 所以"合成写进去的"与"观测读出来的"必然一致。
    刻意读回写值而不是重算: 重算会与循环上一拍差一拍, 于是"我看到的"和"动作看到的"
    就不是同一个东西了。
    """
    out = []
    for spec in BIT_SPECS:
        raw = values.get(spec.byte)
        on = None if raw is None else bool(int(raw) >> spec.bit & 1)
        out.append({"name": spec.name, "label": spec.label, "byte": spec.byte,
                    "bit": spec.bit, "on": on, "source": spec.source})
    return out


class SensorModel:
    """把沙盒内的现场事实合成成 PLC 输入字节.

    参数:
        material_store: 沙盒物料账本 (:memory:); feedlift_model: 板堆模型
        read_axis: async (板仓) -> float, 读升降轴当前位置
        read_cylinder: async (机构 id, 'fb_on'|'fb_off') -> bool | None,
            读气缸到位反馈 (缺该口时给 None); 缺省 None 表示不合成气缸镜像位
        mounted_tool: () -> int, 机器人腕上工具号 (0=裸腕); 缺省 None 表示工具位恒 0
    """

    def __init__(self, material_store, feedlift_model, read_axis, read_cylinder=None,
                 mounted_tool=None):
        self.material_store = material_store
        self.feedlift = feedlift_model
        self.read_axis = read_axis
        self.read_cylinder = read_cylinder
        self.mounted_tool = mounted_tool
        # 上样料架两处: 拓扑刻意不建软件账 (原文"两处都有可用传感器, 现值即真值"),
        # 所以它是沙盒里少数几个没有别的属主的现场事实 —— 就地存放, 由 apply_state 写。
        # 默认 True: 给 False 会让依赖它的动作凭空卡住。
        self.feed_rack_present: dict = {1: True, 2: True}

    async def compose_bits(self) -> dict:
        """算出全部具名位的当前值 (纯读, 不写节点).

        参数:
            无
        返回:
            Dict {位名: bool}
        """
        bits: dict = {}
        for magazine in ("feed", "waste"):
            z_mm = await self.read_axis(magazine)
            bits[f"{magazine}_photo"] = self.feedlift.photo(magazine, z_mm)
            bits[f"{magazine}_proximity"] = self.feedlift.proximity(magazine)

        grid = self.material_store.grid()
        staging = grid.get("staging") or {}
        bits["staging_a"] = (staging.get("staging-a") or {}).get("plate") is not None
        bits["staging_b"] = (staging.get("staging-b") or {}).get("plate") is not None
        seated = {row.get("seat") for row in (grid.get("payload_seats") or [])}
        bits["collect_bottle"] = "collect-bottle" in seated

        bits["feed_rack_1"] = bool(self.feed_rack_present.get(1, True))
        bits["feed_rack_2"] = bool(self.feed_rack_present.get(2, True))

        if self.read_cylinder is not None:
            # 翻料缸与下压缸: 镜像 manual FSM 的到位反馈 (同一物理源, 不另建第二套状态)
            bits["ps_rotate_home"] = bool(await self.read_cylinder("ps_rotate", "fb_off"))
            bits["ps_rotate_work"] = bool(await self.read_cylinder("ps_rotate", "fb_on"))
            bits["ps_press_up"] = bool(await self.read_cylinder("ps_press", "fb_off"))

        if self.mounted_tool is not None:
            # ⚠ 推定极性: "位 N = 1 即 N 号刀在刀架上" —— 与 runtime/material_audit.tool_state_row
            # 是同一条推定 (依据: 三位曾同时读到 [1,1,0], 若是腕侧挂载检测不可能两位同时为 1),
            # 该族未现场实证。之所以按推定合成而不是继续给 0: 给 0 等于"三把刀都在架上",
            # 在腕上挂着刀时是**可证伪的错**, 而恒 0 的实测依据 (未供电) 只覆盖料库那 12 路。
            mounted = int(self.mounted_tool() or 0)
            for tool in (1, 2, 3):
                bits[f"tool_detect_{tool}"] = tool != mounted
        return bits

    async def compose(self) -> dict:
        """算出各输入字节的当前值 (纯读, 不写节点).

        参数:
            无
        返回:
            Dict {字节名: 值}
        """
        return fold_bits(await self.compose_bits())


async def run_sensor_loop(server, model: SensorModel, stop_event, *, clock=None,
                          tick: float = _TICK_S) -> None:
    """周期合成并写入输入字节 (沙盒唯一的 IX 写者).

    参数:
        server: Mock OPC 服务器; model: SensorModel; stop_event: 停机事件
        clock: SimClock (给了则吃时间倍率; 传感器刷新本是扫描节奏, 不给也可以)
        tick: 合成周期 (秒)
    返回:
        None
    """
    import asyncio
    while not stop_event.is_set():
        try:
            values = await model.compose()
            for name, value in values.items():
                await mock_write(server, name, int(value) & 0xFF)
        except Exception:
            log.debug("[沙盒·传感器] 合成异常", exc_info=True)
        if clock is not None:
            await clock.sleep(tick)
        else:
            await asyncio.sleep(tick)
