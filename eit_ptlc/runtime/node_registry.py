"""设备节点注册表 (设备节点健康 + 遥测)
=========================================
功能:
    把已装配的控制器抽象为统一"节点" (机器人 / 各 PLC 工位), 提供节点清单、单节点快照、
    全节点快照与健康派生; 并提供周期遥测循环把快照经事件总线推送前端常驻监视器.
    节点快照取值器复用控制器既有只读接口 (robot.query / plc.snapshot), 不新增设备访问路径.

健康派生 (derive_health, 纯函数):
    plc_station: State 30/40/50 或 SafeState 90 -> error; State 10 -> busy; 其余 -> ok
    robot:       未连接 -> offline; 有报警/check_result!=0 -> error; 其余 -> ok
    取快照抛错 -> offline (由 _read_spec 统一兜底)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

HEALTH_OK = "ok"
HEALTH_BUSY = "busy"
HEALTH_ERROR = "error"
HEALTH_OFFLINE = "offline"

# 工位 L2 前缀 -> 节点显示名 (sim/real 共用)
# 命名规范 2026-07-29: 四个工艺工位带"工站"后缀; FeedLift/StagingA 叫"位"。
# StagingA 节点即 StagingA_L2 通道, 一个通道管中转A/B 两个托盘位的定位缸
# (动作码 24=A / 25=B), 故节点名不带 A/B 后缀; 点位树按 A/B 细分 (stations.yaml
# 的 中转托盘位A/B)。覆盖 _ALL_L2_STATIONS 全集, 不再回落英文工位名。
STATION_LABELS = {
    "Sampling": "上样工站",
    "Collect": "收集工站",
    "Develop": "展开工站",
    "PhotoScrape": "拍照刮板工站",
    "FeedLift": "上下料位",
    "Pump": "泵站",
    "Rail": "地轨",
    "StagingA": "中转托盘位",
}


def derive_health(kind: str, snap: dict) -> str:
    """由原始快照派生节点健康 (纯函数, 便于离线测试).

    参数:
        kind: 节点类型 (plc_station / robot / ...)
        snap: 该节点原始快照字段
    返回:
        健康字符串 (ok / busy / error / offline)
    """
    if kind == "plc_station":
        state = int(snap.get("State", 0))
        safe_state = int(snap.get("SafeState", 0))
        if state in (30, 40, 50) or safe_state == 90:
            return HEALTH_ERROR
        if state == 10:
            return HEALTH_BUSY
        return HEALTH_OK
    if kind == "robot":
        if not snap.get("connected", True):
            return HEALTH_OFFLINE
        if snap.get("error_ids") or int(snap.get("check_result", 0)) != 0:
            return HEALTH_ERROR
        return HEALTH_OK
    return HEALTH_OK


@dataclass(frozen=True)
class NodeSpec:
    """节点描述: 标识 + 异步快照取值器."""
    id: str
    label: str
    kind: str
    reader: Callable[[], Awaitable[dict]]


class NodeRegistry:
    """设备节点注册表: 节点清单 + 快照 + 健康派生."""

    def __init__(self, specs: list[NodeSpec], *, time_fn: Callable[[], float] = time.time) -> None:
        self._specs: dict[str, NodeSpec] = {s.id: s for s in specs}
        self._order: list[str] = [s.id for s in specs]
        self._time = time_fn

    def list_ids(self) -> list[str]:
        """节点 id 列表 (装配顺序)."""
        return list(self._order)

    def descriptors(self) -> list[dict]:
        """节点静态描述 (id/label/kind), 不读设备."""
        return [{"id": s.id, "label": s.label, "kind": s.kind}
                for s in (self._specs[i] for i in self._order)]

    async def snapshot(self, node_id: str) -> dict | None:
        """读取单节点快照 + 健康; 未知节点返回 None."""
        spec = self._specs.get(node_id)
        if spec is None:
            return None
        return await self._read_spec(spec)

    async def snapshot_all(self) -> list[dict]:
        """并发读取全部节点快照 (单节点失败不影响其它)."""
        return await asyncio.gather(*[self._read_spec(self._specs[i]) for i in self._order])

    async def _read_spec(self, spec: NodeSpec) -> dict:
        """执行取值器并组装节点快照; 取值抛错则判 offline."""
        ts = self._time()
        try:
            data = await spec.reader()
            health = derive_health(spec.kind, data)
        except Exception as exc:  # 取快照失败 -> 该节点离线, 不影响整体
            log.debug("[node:%s] 取快照失败: %s", spec.id, exc)
            data = {"error": str(exc)}
            health = HEALTH_OFFLINE
        return {"id": spec.id, "label": spec.label, "kind": spec.kind,
                "health": health, "data": data, "ts": ts}


def _robot_feedback_to_dict(feedback) -> dict:
    """RobotFeedback -> JSON 可序列化快照字段."""
    return {
        "pose": list(feedback.pose),
        "joint": list(feedback.joint),
        "check_result": feedback.check_result,
        "last_action": feedback.last_action,
        "robot_mode": feedback.robot_mode,
        "error_ids": list(feedback.error_ids),
        "connected": feedback.connected,
        "tool_state": dataclasses.asdict(feedback.tool_state),
    }


# 地轨站位判定容差(mm): 实际位置距站位坐标在此内即判定"在该站"; 远小于最小站距100, 不跨站误判
RAIL_STATION_TOL_MM = 10.0

# 工位附加诊断镜像: 设备页在 L2 12 字段外补充的 Host_Computer 镜像变量
# (PLC 侧 PLC_Pump_泵管理 每扫描镜像; 402 复盘可直读废液传感器/泵命令态)
_STATION_EXTRA_MIRRORS: dict[str, tuple[str, ...]] = {
    "Develop": ("Expand_Waste_Empty_G1", "Expand_Waste_Empty_G2"),
    "Pump": ("Pump_Vacuum_On",),
    # 伺服轴实际位置镜像 (mm): 三维视图据此驱动各轴滑块; 1Hz 采样 + 前端插值即可,
    # 伺服动作多为数秒级单轴运动, 观感上足够连续. 未下装的符号(如 5Z)按既有惯例回落
    # 为 None 并只告警一次, 三维侧对 None 轴保持静止, 不报错.
    "Sampling": ("Sampling_4X_ActPos", "Sampling_3Y_ActPos", "Sampling_5Z_ActPos",
                 "Spot_6X_ActPos", "Spot_7Y_ActPos"),
    "PhotoScrape": ("PhotoScrape_9X_ActPos", "PhotoScrape_10Z_ActPos", "Photo_8Y_ActPos"),
    "FeedLift": ("FeedLift_1Z_ActPos", "FeedLift_2Z_ActPos"),
}

# 工位附加数组镜像: per-tank 生命周期 (下标 0 = 1 号缸)
# Tank_State / Tank_Drain_Done 正是 develop.drain (code 50) 完成判据的两个来源
# (Tank_State∈{98,99} OR Tank_Drain_Done); 排液"秒 DONE"时凭它们区分真排液与幂等直通
_STATION_EXTRA_ARRAYS: dict[str, tuple[str, ...]] = {
    "Develop": ("Tank_State", "Tank_Drain_Done"),
}
_extra_mirror_warned: set[str] = set()


def build_node_registry(*, robot=None, plc=None, stations: tuple[str, ...] = (),
                        rail_stations: dict[int, float] | None = None) -> NodeRegistry:
    """按已装配控制器构建节点注册表.

    参数:
        robot: RobotController (有则纳入 "robot" 节点); plc: PlcController;
        stations: 纳入的 L2 工位前缀 (需 plc 非空);
        rail_stations: 地轨站位码->坐标(mm) (rail.yaml 真源), 供 Rail 节点据实际位置映射所在站
    返回:
        NodeRegistry
    """
    specs: list[NodeSpec] = []
    _rail_coords = dict(rail_stations or {})
    if robot is not None:
        async def robot_reader(_robot=robot) -> dict:
            # robot.query 同步阻塞 (且占动作锁) -> 交线程池, 避免阻塞事件循环
            feedback = await asyncio.get_running_loop().run_in_executor(None, _robot.query)
            data = _robot_feedback_to_dict(feedback)
            # 全局速度比 (主控已设值) 随遥测回显, 供维护页点动面板初始化速度输入
            data["speed_factor"] = _robot.speed_factor
            return data
        specs.append(NodeSpec("robot", "机械臂", "robot", robot_reader))
    if plc is not None:
        for station in stations:
            label = STATION_LABELS.get(station, station)
            if station == "Rail":
                # Rail 节点据实际位置(Rail_ActPos)映射所在站(可多个重位); 后端算, 坐标用 rail.yaml;
                # 未回零/读不到/未下载 -> [] (前端显「—」)。位1≡位2、位5≡位6 同坐标 -> 返回多个站码。
                # 站点置空原因仅在"变化时"记一次日志 (遥测每秒调用 rail_reader, 防刷屏);
                # 用默认参数绑定可变 holder 保存上轮原因, 区分 读失败/未回零/超容差 三类, 便于现场定位
                _rail_diag: dict[str, object] = {"last": None}

                async def rail_reader(_plc=plc, _coords=_rail_coords, _diag=_rail_diag) -> dict:
                    data = {k: v for k, v in (await _plc.snapshot("Rail")).items()}
                    slots: list[int] = []
                    reason = None   # 非 None 即本轮站点置空原因 (仅供变化时记日志, 不改返回行为)
                    # 地轨实际位置(mm): 站位判定本就要读它, 顺带透出供三维视图驱动小车;
                    # 读失败时保持 None, 三维侧退化为按 current_positions 吸附到站位
                    data["Rail_ActPos"] = None
                    try:
                        pos, homed = await _plc.read_rail_pose()
                        data["Rail_ActPos"] = pos
                        if not homed:
                            reason = "地轨未回零 (Rail_Homed=FALSE), 实际位不可信"
                        else:
                            slots = sorted(s for s, v in _coords.items()
                                           if v > 0 and abs(pos - v) <= RAIL_STATION_TOL_MM)
                            if not slots:
                                reason = (f"实际位 {pos:.2f}mm 不在任一站位 ±{RAIL_STATION_TOL_MM:.0f}mm 内 "
                                          f"(站位坐标={_coords})")
                    except Exception as exc:
                        reason = (f"读地轨实际位失败 ({type(exc).__name__}: {exc}); "
                                  f"常见于 PLC 未在符号配置发布 Rail_ActPos/Rail_Homed")
                    if reason != _diag["last"]:
                        if reason is not None:
                            log.warning("[node:plc.rail] 站点置空: %s", reason)
                        else:
                            log.info("[node:plc.rail] 站点恢复, 命中站位 %s", slots)
                        _diag["last"] = reason
                    data["current_positions"] = slots
                    return data
                specs.append(NodeSpec("plc.rail", label, "plc_station", rail_reader))
            else:
                async def plc_reader(_station=station, _plc=plc) -> dict:
                    # L2 字段 + 附加诊断镜像合并成一次批读: 逐个读是每工位十余次串行往返 ×
                    # 8 工位并发, 那些往返本身就足以把 PLC 服务端压到应答超时。未下装的镜像
                    # 由驱动侧负缓存挡掉 (零往返填 None), 不会再每秒浏览一遍容器去确认它不存在。
                    extras = _STATION_EXTRA_MIRRORS.get(_station, ())
                    data = dict(await _plc.snapshot_with_mirrors(_station, extras))
                    # 镜像取空 -> 保持既有容错惯例 (字段 None + 仅首次告警, 遥测 1Hz 防刷屏)
                    for extra in extras:
                        if data.get(extra) is not None or extra in _extra_mirror_warned:
                            continue
                        _extra_mirror_warned.add(extra)
                        log.warning("[node:plc.%s] 附加镜像 %s 读取失败 (PLC 未下装新符号?): %s",
                                    _station.lower(), extra,
                                    _plc.host_var_missing_reason(extra) or "读取返回空值")
                    # 附加数组镜像: 同上容错惯例, 单个数组读失败不打掉整个工位节点遥测
                    for extra in _STATION_EXTRA_ARRAYS.get(_station, ()):
                        try:
                            data[extra] = await _plc.read_host_array(extra)
                        except Exception as exc:
                            data[extra] = None
                            if extra not in _extra_mirror_warned:
                                _extra_mirror_warned.add(extra)
                                log.warning("[node:plc.%s] 附加数组镜像 %s 读取失败 (PLC 未下装新符号?): %s",
                                            _station.lower(), extra, exc)
                    return data
                specs.append(NodeSpec(f"plc.{station.lower()}", label, "plc_station", plc_reader))
    return NodeRegistry(specs)


async def telemetry_loop(registry: NodeRegistry, bus, stop: asyncio.Event, *, interval: float = 1.0) -> None:
    """周期遥测循环: 约 interval 秒读全部节点快照并经总线推送 telemetry 事件.

    参数:
        registry: 节点注册表; bus: EventBus (publish 投递); stop: 退出信号; interval: 采样周期秒
    """
    log.info("[telemetry] 启动: 周期 %.2fs, 节点 %s", interval, registry.list_ids())
    while not stop.is_set():
        try:
            for snap in await registry.snapshot_all():
                bus.publish({"type": "telemetry", "node": snap["id"], "health": snap["health"],
                             "data": snap["data"], "ts": snap["ts"]})
        except Exception:  # 单轮采样异常不应终止循环
            log.exception("[telemetry] 采样失败")
        # 可被 stop 立即唤醒的等待
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    log.info("[telemetry] 退出")
