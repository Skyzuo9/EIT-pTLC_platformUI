"""展缸液量模型 (八缸各一份体积)
================================
功能:
    给"缸里此刻有多少毫升"这个量一个**后端真源**。此前它在后端完全不存在:
    develop.py 只写阀与计时, 三维里那条涨落的液面是前端按动作包络编出来的
    (TankLiquidModel.js 文件头自陈"时长不是真实流量")。于是"板在 3 号缸泡着、
    液面到哪"这个物理状态既设不了也读不出, 从它出发的推演无从谈起。

    为什么缸可以建模而瓶不可以 (与 material_store 的瓶体积刻意不同):
      真机的缸**有液位相机** (develop.wait_level 读溶剂前沿百分比), 缸内液量是真机
      的可观测量, 沙盒复刻它是补上一个真实存在的传感通道;
      真机的瓶**没有流量计**, 账本按动作参数扣本来就是真机的真实盲区 —— 沙盒去按泵
      的实际排出量扣, 就成了"沙盒比真机准", 真机会漏的账在沙盒里漏不出来, 与
      parity 纪律 (真机能拦住的缺陷沙盒必须也拦得住, 反过来也不许更严) 方向相反。

模型形状 —— **读物理状态, 不读动作码**:
    进液 = 泵的累计排出量增量, 路由到"该组里进液阀开着的那个缸"。哪个 FSM 开的阀、
      走的哪个动作码, 本模型一概不问 —— 手动开阀 + 手动发泵指令一样会灌进去。
    排液 = 排液阀开着就按速率往下走。A26 抽吸 / A50·A51 排液桥 / 人手开阀三条路
      因此天然都覆盖到, 不必在三个地方各挂一次钩。

⚠ 全模型唯一的显式近似是**排液速率**: 真机排液既无流量计也无时长通道。这里取三维
    manifest 里 `tankLiquid.actions['develop.drain'].rampS` 折算 —— 那是个被人调过、
    与实际观感对上的数, 比新编一个强; 但它终究是动画常量借来的, 故在此写明。
    进液侧没有近似 (泵推了多少就是多少)。

容量与几何一律读 manifest.tankLiquid.cavity (03 管线实测: 溶液槽 210×40×25mm,
    满 102.48 mL), **不在后端抄第二份数字** —— 抄了就会与三维分叉。
"""

from __future__ import annotations

import logging
import time

from eit_ptlc.mock.behavior.cylinders import valve_state

log = logging.getLogger("eit_ptlc.mock.tank_liquid")

TANK_COUNT = 8
#: 积分节奏 (名义秒, 经 clock 缩放)。它只决定采样粗细, **不决定积分量** ——
#: 量按实际经过的名义秒算 (见 run_tank_liquid_loop), 所以循环跟不上也不失真。
_TICK_S = 0.2
_PUBLISH_MIN_ML = 0.05        # 变化小于这个量不广播 (省事件, 液面看不出来)
_DEFAULT_DRAIN_RAMP_S = 10.0  # manifest 缺 rampS 时的兜底 (与其 develop.drain 同值)

#: 组号 -> 该组的泵 id (DT 站号 1/2 = DEV1/DEV2, 与 pump.ADDR_TO_PUMP_ID 同源)
GROUP_PUMP = {1: "DEV1", 2: "DEV2"}


def tank_group(tank: int) -> int:
    """缸号 -> 组号 (1..4 属 1 组, 5..8 属 2 组; 与 develop._tank_context 同式)."""
    return (int(tank) - 1) // 4 + 1


def tank_number(tank: int) -> int:
    """缸号 -> 组内序号 (与 develop._tank_context 同式)."""
    return (int(tank) - 1) % 4 + 1


class TankLiquidModel:
    """八个展缸的液量 (mL) + 溶剂前沿推导.

    参数:
        cavity: manifest.tankLiquid.cavity (需含 capacityMl); 缺失则容量按 0 处理
        drain_ramp_s: 排空一满缸的名义时长 (唯一显式近似, 见模块头)
    """

    def __init__(self, cavity: dict | None = None,
                 drain_ramp_s: float = _DEFAULT_DRAIN_RAMP_S) -> None:
        self.cavity = dict(cavity or {})
        self.capacity_ml = float(self.cavity.get("capacityMl") or 0.0)
        self.drain_ramp_s = float(drain_ramp_s) if drain_ramp_s else _DEFAULT_DRAIN_RAMP_S
        self.volume_ml = {tank: 0.0 for tank in range(1, TANK_COUNT + 1)}
        #: 每缸已浸泡的**名义秒** (由积分循环按 clock 步长累加, 空缸清零)。
        #: 刻意不用 time.monotonic 记起算时刻: 挂钟不随 time_scale 缩放, 20 倍速下
        #: wait_level 仍要等真实几分钟, 而沙盒里"跑得快"是第一位的可用性。
        self.soak_s = {tank: 0.0 for tank in range(1, TANK_COUNT + 1)}

    # ------------------------------------------------------------------
    # 写面
    # ------------------------------------------------------------------
    def set_volume(self, tank: int, volume_ml: float) -> None:
        """直写某缸液量 (设初态用), 夹逼到 [0, 容量].

        参数:
            tank: 缸号 1..8; volume_ml: 目标体积 mL
        返回:
            None
        Raises:
            ValueError: 缸号越界
        """
        index = int(tank)
        if index not in self.volume_ml:
            raise ValueError(f"缸号应为 1..{TANK_COUNT}, 收到 {tank!r}")
        # 容量为 0 (读不到 manifest) 时一律夹到 0 —— 没有容量真源就不凭空生出液体,
        # 与 build_model 的 warning 同一句话。不给"容量未知即无限"这种兜底。
        capped = min(max(float(volume_ml), 0.0), self.capacity_ml)
        self.volume_ml[index] = capped
        self._touch_soak(index)

    def fill(self, tank: int, delta_ml: float) -> float:
        """往某缸加液, 返回真正加进去的量 (满了就溢不进去).

        参数:
            tank: 缸号; delta_ml: 想加多少 mL
        返回:
            float, 实际加入量 mL
        """
        index = int(tank)
        if index not in self.volume_ml or delta_ml <= 0 or self.capacity_ml <= 0:
            return 0.0
        room = self.capacity_ml - self.volume_ml[index]
        taken = min(float(delta_ml), max(room, 0.0))
        self.volume_ml[index] += taken
        self._touch_soak(index)
        return taken

    def drain(self, tank: int, seconds: float) -> float:
        """按排液速率排一段时间, 返回真正排掉的量.

        参数:
            tank: 缸号; seconds: 这一拍过了多少秒
        返回:
            float, 实际排出量 mL
        """
        index = int(tank)
        if index not in self.volume_ml or seconds <= 0 or self.capacity_ml <= 0:
            return 0.0
        rate = self.capacity_ml / self.drain_ramp_s          # mL/s, 见模块头的近似声明
        taken = min(self.volume_ml[index], rate * float(seconds))
        self.volume_ml[index] -= taken
        self._touch_soak(index)
        return taken

    def tick(self, seconds: float) -> None:
        """推进浸泡计时 (由积分循环按 clock 步长调, 故自动随 time_scale 缩放).

        参数:
            seconds: 本拍过了多少**名义**秒
        返回:
            None
        """
        for tank, volume in self.volume_ml.items():
            if volume > 0:
                self.soak_s[tank] += float(seconds)

    def _touch_soak(self, tank: int) -> None:
        """缸空了就把浸泡计时清零 (前沿从头算)."""
        if self.volume_ml[tank] <= 0:
            self.soak_s[tank] = 0.0

    # ------------------------------------------------------------------
    # 读面
    # ------------------------------------------------------------------
    def level_ratio(self, tank: int) -> float:
        """液面占可用深度的比例 0~1 (与前端 levelFromMl 同式: 体积 / 容量)."""
        if self.capacity_ml <= 0:
            return 0.0
        return min(max(self.volume_ml.get(int(tank), 0.0) / self.capacity_ml, 0.0), 1.0)

    def front_percent(self, tank: int, *, climb_s: float) -> float:
        """溶剂前沿爬升百分比 0~100 —— develop.wait_level 的合成源.

        参数:
            tank: 缸号
            climb_s: 前沿爬满整块板的名义时长 (调用方给, 本模型不编这个数)
        返回:
            float, 0~100

        判据是**两件事的合取**: 缸里有液 (没液就恒 0, 与真机一致 —— 空缸永远等不到)
        且泡够了时间。液面越浅爬得越慢, 按液面比例线性折减。
        """
        index = int(tank)
        if climb_s <= 0:
            return 0.0
        ratio = self.level_ratio(index)
        if ratio <= 0:
            return 0.0
        return min(100.0, max(0.0, self.soak_s.get(index, 0.0) / climb_s * 100.0 * ratio))

    def snapshot(self) -> dict:
        """只读快照 (供 /api/sim/state 与诊断面板).

        参数:
            无
        返回:
            Dict {capacity_ml, drain_ramp_s, volumes: {缸号: {volume_ml, level, soaking}}}

        逐缸量放在 `volumes` 而不是 `tanks` 下, 是为了与写面 {"tanks": {"3": {...}}}
        不同名 —— 同名会诱出"读面整个回灌写面"的错觉, 而外层那两项元数据是只读的。
        """
        return {
            "capacity_ml": round(self.capacity_ml, 3),
            "drain_ramp_s": self.drain_ramp_s,
            "volumes": {
                str(tank): {
                    "volume_ml": round(self.volume_ml[tank], 3),
                    "level": round(self.level_ratio(tank), 4),
                    "soak_s": round(self.soak_s[tank], 2),
                }
                for tank in sorted(self.volume_ml)
            },
        }


async def run_tank_liquid_loop(server, model: TankLiquidModel, pumps: dict, *,
                               manual_map, manual_paths, clock, stop_event,
                               publish=None) -> None:
    """液量积分循环: 泵排出 × 进液阀 -> 加; 排液阀 -> 减.

    参数:
        model: TankLiquidModel; pumps: {泵 id: PumpModel}
        publish: 可选 (dict) -> None, 发 tank_liquid 事件
    返回:
        None (随 stop_event 结束)

    **只读物理状态, 不读动作码**: 哪个 FSM 开的阀无所谓 —— A26 抽吸 / A50·A51 排液桥 /
    人手在面板上开阀, 三条路天然都覆盖到, 不必在三处各挂一次钩。这也是它能被
    "设完状态直接看"的原因: 设个阀位它就动。
    """
    seen_dispensed = {pump_id: model_ref.dispensed_ml
                      for pump_id, model_ref in pumps.items()}
    seq = 0
    last_published: dict[int, float] = {}
    last_at = clock.mark()
    while not stop_event.is_set():
        await clock.sleep(_TICK_S)
        # 这一拍实际过了多少名义秒 —— **不是**直接加 _TICK_S, 理由见 SimClock.elapsed
        nominal_s = clock.elapsed(last_at)
        last_at = clock.mark()
        model.tick(nominal_s)
        changed = False

        # ① 进液: 各组泵的排出增量, 灌进该组里进液阀开着的那个缸
        for group, pump_id in GROUP_PUMP.items():
            pump = pumps.get(pump_id)
            if pump is None:
                continue
            delta = pump.dispensed_ml - seen_dispensed.get(pump_id, 0.0)
            seen_dispensed[pump_id] = pump.dispensed_ml
            if delta <= 0:
                continue
            for tank in range(1, TANK_COUNT + 1):
                if tank_group(tank) != group:
                    continue
                state = await valve_state(
                    server, manual_map, manual_paths,
                    f"dev_t{group}_fill{tank_number(tank)}")
                if state:                       # None (无从判定) 一律不灌, 见模块头
                    if model.fill(tank, delta) > 0:
                        changed = True
                    break                       # 一组同时只该有一个缸在进液

        # ② 排液: 阀开着就往下走
        for tank in range(1, TANK_COUNT + 1):
            if model.volume_ml[tank] <= 0:
                continue
            state = await valve_state(
                server, manual_map, manual_paths,
                f"dev_t{tank_group(tank)}_drain{tank_number(tank)}")
            if state and model.drain(tank, nominal_s) > 0:
                changed = True

        if not changed or publish is None:
            continue
        for tank, volume in model.volume_ml.items():
            if abs(volume - last_published.get(tank, -1.0)) < _PUBLISH_MIN_ML:
                continue
            last_published[tank] = volume
            seq += 1
            publish({"type": "tank_liquid", "tank": tank,
                     "volume_ml": round(volume, 3),
                     "level": round(model.level_ratio(tank), 4),
                     "capacity_ml": round(model.capacity_ml, 3),
                     "ts": time.time(), "seq": seq})


def build_model(manifest: dict | None) -> TankLiquidModel:
    """从三维 manifest 建模型 (容量与排液时长都取那一份, 后端不抄第二遍).

    参数:
        manifest: device-manifest 的整份 dict; None 或缺段则容量为 0 (液量恒 0)
    返回:
        TankLiquidModel
    """
    block = ((manifest or {}).get("tankLiquid") or {})
    cavity = block.get("cavity") or {}
    ramp = ((block.get("actions") or {}).get("develop.drain") or {}).get("rampS")
    if not cavity:
        log.warning("[沙盒·展缸] manifest 无 tankLiquid.cavity, 缸液量将恒为 0")
    return TankLiquidModel(cavity, float(ramp or _DEFAULT_DRAIN_RAMP_S))
