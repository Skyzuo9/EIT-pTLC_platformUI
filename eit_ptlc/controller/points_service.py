"""统一点位目录服务
==================
功能:
    把两类"点位"聚合为上位机统一视图, 供点位管理页展示/编辑/跳转:
      - robot     : 机器人点位 (来自 PointRegistry, 含派生点; 真源 points/robot/robot_points.json + meta)
      - plc_servo : PLC 伺服点位 (按工位分散于 points/plc/<工位>.yaml; 含 struct 槽位点与 PC 侧 flat 目标点)

    磁盘组织 = UI 分组 (目录即分组):
      points/
        stations.yaml          工位登记表 (workstation->显示名 + PLC 伺服 OPC 容器), 非点位本身
        plc/<工位>.yaml         该工位的 plc_servo / plc_servo_target (文件名即 workstation, 不在条目里重复)
        robot/robot_points.json + robot_points_meta.json   机器人点表真源 (设备导出, 不按工位拆)

    本服务不持有机器人位姿真源 (仍在 PointRegistry); plc/*.yaml 仅承载新数据 (伺服绑定 + flat 目标值)。
    CNC 几何/进给为 app.yaml gcode 段的参数 (非点位), 已由设备参数页维护, 不在点位目录出现。
"""

from __future__ import annotations

import inspect
import json
import math
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from eit_ptlc.controller.point_registry import PointRegistry, RobotPoint

ROBOT_CATEGORY = "robot"
PLC_SERVO_CATEGORY = "plc_servo"
PLC_SERVO_TARGET_CATEGORY = "plc_servo_target"
PLC_SERVO_COMPOSITE_CATEGORY = "plc_servo_composite"
CATEGORIES = (ROBOT_CATEGORY, PLC_SERVO_CATEGORY, PLC_SERVO_TARGET_CATEGORY,
              PLC_SERVO_COMPOSITE_CATEGORY)

# 磁盘布局
STATIONS_FILE = "stations.yaml"      # 工位登记表 (相对 points/)
PLC_SUBDIR = "plc"                   # 按工位分散的 PLC 伺服点位目录
ROBOT_POINTS_KIND = "robot/robot_points.json"
ROBOT_META_KIND = "robot/robot_points_meta.json"
ROBOT_LABELS_KIND = "robot/labels.yaml"   # 机器人点位中文显示名 (纯展示, 不参与寻址)

_SLOT_MIN, _SLOT_MAX = 1, 10
_UNGROUPED = "未分组"

# 双源同步邮箱码 (与 Rail_Sync POU / docs/PLC交付_地轨双源同步 契约一致)
SYNC_REQ_IDLE, SYNC_REQ_PUSH, SYNC_REQ_PULL = 0, 1, 2
SYNC_ACK_IDLE, SYNC_ACK_DONE, SYNC_ACK_WAIT_PC, SYNC_ACK_REJECT = 0, 1, 2, 3
SYNC_SRC_PC, SYNC_SRC_HMI = 1, 2
# diff 默认偏差阈值 (mm); D-C 细化未定具体值前的工作默认, 可经接口覆盖
DEFAULT_SYNC_DIFF_THRESHOLD = 0.5


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# 示教复核 (teach-verify) 参数
_TEACH_MAX_REACH_MM = 500.0    # 复核运动安全包络: 临时进近点离当前目标最大位移 (超则拒发, 防误算大范围运动)
_TEACH_DRIFT_MM_TOL = 1.0      # 回位漂移告警阈 (mm)
_TEACH_DRIFT_DEG_TOL = 0.5     # 回位漂移告警阈 (deg)


def _norm_deg(delta: float) -> float:
    """角度差归一化到 (-180, 180] (deg)。"""
    return math.fmod(delta + 540.0, 360.0) - 180.0


class PointsCatalogError(ValueError):
    """points/ 目录结构或取值非法。"""


@dataclass(frozen=True)
class PlcServoPoint:
    """PLC 「离散召回位」点位 (struct 槽位模型, 如地轨 11Y 的 6 个固定工位)。

    value (双源同步收编后): 站点坐标的 PC 真源 (canonical)。None = 未收编 (纯召回展示)。
        收编工位 (其 workstation 有 sync 块) 经 push/pull/diff 与 HMI 工作副本对账;
        slot 即同步 flat 数组 (target/mirror) 的下标。
    """
    key: str
    label: str
    node: str
    workstation: str
    role: str
    slot: int
    min_limit: float
    max_limit: float
    backup: float | None
    value: float | None = None

    def within_limits(self, v: float) -> bool:
        """目标值是否在软限位 [min, max] 内 (写前钳制的单一判定, 防越程撞机)。"""
        return self.min_limit <= v <= self.max_limit


@dataclass(frozen=True)
class ServoSyncGroup:
    """工位级双源同步契约 (PC↔HMI 经 PLC flat 数组 + 邮箱对账; 见 Rail_Sync POU)。

    HMI struct (position[]) OPC 逐成员读写不可行 → PLC 当桥只暴露 flat 数组:
        target_node     仅 PC 写: 站点真源数组 (自动派发器读 + PUSH 源)。
        hmi_mirror_node 仅 PLC 写: 每扫描镜像 HMI position[] (diff/pull 读, PC 不碰 struct)。
        req/ack/src     同步邮箱 (PUSH/PULL 请求-应答握手)。
    该工位的 plc_servo 点以 slot (1..array_len) 索引这些数组。
    """
    workstation: str
    target_node: str
    hmi_mirror_node: str
    req_node: str
    ack_node: str
    src_node: str
    array_len: int
    diff_threshold: float | None = None  # 软"需确认"阈值 (yaml diff_threshold_mm); None → 用 DEFAULT


@dataclass(frozen=True)
class PlcServoTarget:
    """PC 侧 flat 目标点位 (B 方案 / 路径 T 单写者): 值存于 plc/<工位>.yaml, PC 写到 PLC *_Target flat 节点。

    路径 T (单一真源 = *_Target, HMI 改读它, position[] 退役): 每根连续伺服轴以一个本类表达,
    上位机示教即 jog 读 actpos → 存 value (PC 真值, 因 flat 节点不 retain) → 下发 *_Target。

    元数据字段 (非读写真源, 仅记录/展示):
        hmi_node : 对应 HMI 物理轴 struct 标签 (召回参照 + 路径 T 迁移映射来源)。
        hmi_slot : 本 *_Target 取代的 HMI position[槽位] (None = 仿射/无固定槽, 如硬编码常量)。
        pending  : PLC 端 *_Target/*_ActPos flat 节点尚未建 → 可离线存值, 但禁"读实际位/下发"。
    """
    key: str
    node: str
    actpos: str
    label: str
    workstation: str
    value: float
    min_limit: float
    max_limit: float
    limit_source: bool  # True=仅作软限位数据源 (如上样仿射轴): value 占位, 禁止手动存值/下发
    hmi_node: str = ""
    hmi_slot: int | None = None
    pending: bool = False

    def within_limits(self, v: float) -> bool:
        """目标值是否在软限位 [min, max] 内 (写前钳制的单一判定, 防越程撞机)。"""
        return self.min_limit <= v <= self.max_limit


@dataclass(frozen=True)
class PlcServoCompositeMember:
    """组合点位的单个子坐标 (即一个 flat 目标轴位): 语义同 PlcServoTarget 的读写真源字段。

    成员 key 仅在所属组合点位内唯一 (如 x_start/x_end/y_height); node/actpos 仍是全局 PLC flat 节点。
    """
    key: str
    label: str
    node: str
    actpos: str
    value: float
    min_limit: float
    max_limit: float

    def within_limits(self, v: float) -> bool:
        """子坐标值是否在软限位 [min, max] 内 (写前钳制的单一判定, 防越程撞机)。"""
        return self.min_limit <= v <= self.max_limit


@dataclass(frozen=True)
class PlcServoComposite:
    """组合点位 (一个语义点位聚合多根 flat 目标轴位): 如「点样位置」= X起点/X终点/Y高度。

    路径 T 下每根连续轴本是一个 PlcServoTarget; 当多根轴共同定义一个工艺位姿时, 用本类把它们聚为
    单一可示教/可引用的点位: 示教在同一面板逐成员 jog 采点 -> 存各子坐标真值; 动作以一个 point_ref
    引用本组合, 触发前按成员序整体下发各 *_Target。值同样持久化于 plc/<工位>.yaml (flat 节点不 retain)。
    """
    key: str
    label: str
    workstation: str
    members: tuple[PlcServoCompositeMember, ...]


@dataclass(frozen=True)
class PointsCatalog:
    servo_container: tuple[str, ...]
    servo_points: tuple[PlcServoPoint, ...]
    servo_targets: tuple[PlcServoTarget, ...]
    station_labels: dict[str, str]
    sync_groups: tuple[ServoSyncGroup, ...] = ()
    composites: tuple[PlcServoComposite, ...] = ()
    # 工位分组展示顺序 (stations.yaml group_order): 按流程走向排, 未列出的按 key 字母序沉底
    station_order: tuple[str, ...] = ()


class PointsService:
    """统一点位目录服务 (挂 app.state.points)。"""

    def __init__(self, points_dir, registry: PointRegistry, *, driver=None,
                 robot=None, robot_points_file=None, robot_meta_file=None,
                 point_source_version: str = "v0.11") -> None:
        """参数:
        points_dir: config/points 目录; registry: 运行期机器人点表 (含派生点);
        driver: OpcUaDriver (伺服 flat 读写); robot: RobotController (robot 点位保存后热替换其 registry);
        robot_points_file/robot_meta_file: 机器人点表真源 (原始 json 读写);
        point_source_version: PointRegistry.load 的版本号。
        """
        self._dir = Path(points_dir)
        self._registry = registry
        self._driver = driver
        self._robot = robot
        self._robot_points_file = None if robot_points_file is None else Path(robot_points_file)
        self._robot_meta_file = None if robot_meta_file is None else Path(robot_meta_file)
        self._point_source_version = point_source_version
        # _target_files: 目标点 key -> 所在工位 (即 plc/<工位>.yaml), 供 set_target_value 定位回写文件
        self._catalog, self._target_files = self._load()

    @property
    def _robot_labels_file(self) -> Path | None:
        """机器人点位中文名真源 (robot/labels.yaml)。

        必须在每处 PointRegistry.load 显式传入: 本服务的热替换路径 (原文保存 / 单点片段保存 /
        示教 commit) 用临时文件充当 points/meta, 若让 registry 按 meta 同目录推断, 重建后
        全部中文名会静默丢失 (临时目录里没有 labels.yaml)。
        """
        return None if self._robot_meta_file is None else self._robot_meta_file.parent / "labels.yaml"

    # ------------------------------------------------------------------
    # 加载 / 校验 / 重载
    # ------------------------------------------------------------------

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    @staticmethod
    def _read_dir(points_dir: Path) -> tuple[dict, dict[str, dict]]:
        """读取 points/ 下的原始内容 -> (stations_raw, {workstation: plc_file_raw})。"""
        stations_path = points_dir / STATIONS_FILE
        if not stations_path.exists():
            raise PointsCatalogError(f"点位登记表不存在: {stations_path}")
        stations_raw = PointsService._read_yaml(stations_path)
        plc_raws: dict[str, dict] = {}
        plc_dir = points_dir / PLC_SUBDIR
        if plc_dir.is_dir():
            for f in sorted(plc_dir.glob("*.yaml")):
                plc_raws[f.stem] = PointsService._read_yaml(f)
        return stations_raw, plc_raws

    def _load(self) -> tuple[PointsCatalog, dict[str, str]]:
        """从 self._dir 读取并装配 (供 __init__ / reload)。"""
        stations_raw, plc_raws = self._read_dir(self._dir)
        return self._assemble(stations_raw, plc_raws)

    @classmethod
    def load_catalog(cls, points_dir) -> PointsCatalog:
        """从目录加载并校验 -> PointsCatalog (失败抛 PointsCatalogError; 供外部/测试)。"""
        stations_raw, plc_raws = cls._read_dir(Path(points_dir))
        catalog, _ = cls._assemble(stations_raw, plc_raws)
        return catalog

    @staticmethod
    def _assemble(stations_raw, plc_raws: dict[str, dict]) -> tuple[PointsCatalog, dict[str, str]]:
        """合并 stations.yaml + 各 plc/<工位>.yaml -> (PointsCatalog, target_files)。

        workstation 由 plc 文件名注入 (条目内不再声明); 跨文件 key 全局唯一。
        """
        container, labels, station_order = PointsService._parse_stations(stations_raw)

        servo: list[PlcServoPoint] = []
        targets: list[PlcServoTarget] = []
        composites: list[PlcServoComposite] = []
        sync_groups: list[ServoSyncGroup] = []
        servo_keys: set[str] = set()
        target_keys: set[str] = set()
        composite_keys: set[str] = set()
        target_files: dict[str, str] = {}

        for workstation in sorted(plc_raws):
            s_list, t_list, c_list, sync = PointsService._parse_plc_file(workstation, plc_raws[workstation])
            for s in s_list:
                if s.key in servo_keys:
                    raise PointsCatalogError(f"plc_servo key 跨工位文件重复: {s.key}")
                servo_keys.add(s.key)
                servo.append(s)
            for t in t_list:
                if t.key in target_keys:
                    raise PointsCatalogError(f"plc_servo_target key 跨工位文件重复: {t.key}")
                target_keys.add(t.key)
                targets.append(t)
                target_files[t.key] = workstation
            for c in c_list:
                # 组合点位 key 与 target/composite 同处 point_ref 选项与单点路由命名空间 -> 全局唯一
                if c.key in composite_keys or c.key in target_keys:
                    raise PointsCatalogError(f"plc_servo_composite key 与目标点位/组合点位重复: {c.key}")
                composite_keys.add(c.key)
                composites.append(c)
                target_files[c.key] = workstation   # _target_files: key -> 所在 plc 文件 (target 与 composite 共用)
            if sync is not None:
                # sync 工位的 plc_servo 点须有 value (真源) 且 slot 在数组范围内
                for s in s_list:
                    if s.value is None:
                        raise PointsCatalogError(
                            f"plc/{workstation}.yaml 含 sync 块时 plc_servo[{s.key}] 必须有 value (PC 真源)")
                    if not (1 <= s.slot <= sync.array_len):
                        raise PointsCatalogError(
                            f"plc/{workstation}.yaml plc_servo[{s.key}].slot {s.slot} 超出 sync.array_len {sync.array_len}")
                sync_groups.append(sync)

        if servo and not container:
            raise PointsCatalogError(
                "存在 plc_servo 条目时 stations.yaml plc_servo_container.gvl_path 必填 (非空列表)")

        catalog = PointsCatalog(
            servo_container=container,
            servo_points=tuple(servo),
            servo_targets=tuple(targets),
            station_labels=labels,
            sync_groups=tuple(sync_groups),
            composites=tuple(composites),
            station_order=station_order,
        )
        return catalog, target_files

    @staticmethod
    def _parse_stations(raw) -> tuple[tuple[str, ...], dict[str, str], tuple[str, ...]]:
        """校验 stations.yaml -> (gvl_path 容器, workstation 显示名, 工位展示顺序)。"""
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise PointsCatalogError("stations.yaml version 必须为 1")
        container = raw.get("plc_servo_container") or {}
        gvl = container.get("gvl_path") if isinstance(container, dict) else None
        if gvl is not None and not isinstance(gvl, list):
            raise PointsCatalogError("stations.yaml plc_servo_container.gvl_path 必须是列表")
        labels = raw.get("labels") or {}
        if not isinstance(labels, dict):
            raise PointsCatalogError("stations.yaml labels 必须是 mapping")
        order = raw.get("group_order") or []
        if not isinstance(order, list) or any(not isinstance(k, str) for k in order):
            raise PointsCatalogError("stations.yaml group_order 必须是字符串列表")
        container_tuple = tuple(str(p) for p in gvl) if isinstance(gvl, list) else ()
        return container_tuple, {str(k): str(v) for k, v in labels.items()}, tuple(order)

    @staticmethod
    def _parse_plc_file(
        workstation: str, raw
    ) -> tuple[list[PlcServoPoint], list[PlcServoTarget], list[PlcServoComposite], ServoSyncGroup | None]:
        """校验单个 plc/<工位>.yaml -> (servo 点列表, target 点列表, 组合点位列表, 同步契约); workstation 由文件名注入。"""
        if not isinstance(raw, dict):
            raise PointsCatalogError(f"plc/{workstation}.yaml 顶层必须是 mapping")
        servo_raw = raw.get("plc_servo") or []
        if not isinstance(servo_raw, list):
            raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo 必须是列表")

        servo: list[PlcServoPoint] = []
        seen: set[str] = set()
        for i, e in enumerate(servo_raw):
            if not isinstance(e, dict):
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo[{i}] 必须是 mapping")
            for k in ("key", "label", "node", "slot", "limits"):
                if k not in e:
                    raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo[{i}] 缺少字段 {k!r}")
            key = str(e["key"])
            if key in seen:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo key 重复: {key}")
            seen.add(key)
            slot = int(e["slot"])
            if not (_SLOT_MIN <= slot <= _SLOT_MAX):
                raise PointsCatalogError(
                    f"plc/{workstation}.yaml plc_servo[{key}].slot 必须在 {_SLOT_MIN}..{_SLOT_MAX}, 得到 {slot}")
            limits = e["limits"]
            if not isinstance(limits, dict) or "min" not in limits or "max" not in limits:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo[{key}].limits 必须含 min/max")
            lo, hi = float(limits["min"]), float(limits["max"])
            if lo >= hi:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo[{key}].limits min({lo}) 必须小于 max({hi})")
            backup = e.get("backup")
            value = e.get("value")
            if value is not None:
                value = float(value)
                if not (lo <= value <= hi):
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo[{key}].value {value} 超出限位 [{lo}, {hi}]")
            servo.append(PlcServoPoint(
                key=key, label=str(e["label"]), node=str(e["node"]),
                workstation=workstation, role=str(e.get("role", "")),
                slot=slot, min_limit=lo, max_limit=hi,
                backup=None if backup is None else float(backup),
                value=value,
            ))

        targets = PointsService._parse_servo_targets(workstation, raw.get("plc_servo_target") or [])
        composites = PointsService._parse_servo_composites(workstation, raw.get("plc_servo_composite") or [])
        sync = PointsService._parse_sync(workstation, raw.get("sync"))
        return servo, targets, composites, sync

    @staticmethod
    def _parse_sync(workstation: str, raw) -> ServoSyncGroup | None:
        """校验单文件 sync 块 (工位级双源同步契约); 缺省 None (该工位不参与同步)。"""
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise PointsCatalogError(f"plc/{workstation}.yaml sync 必须是 mapping")
        required = ("target_node", "hmi_mirror_node", "req_node", "ack_node", "src_node", "array_len")
        for k in required:
            if k not in raw:
                raise PointsCatalogError(f"plc/{workstation}.yaml sync 缺少字段 {k!r}")
        array_len = int(raw["array_len"])
        if array_len < 1:
            raise PointsCatalogError(f"plc/{workstation}.yaml sync.array_len 必须 >= 1, 得到 {array_len}")
        thr_raw = raw.get("diff_threshold_mm")
        if thr_raw is not None:
            thr = float(thr_raw)
            if thr < 0:
                raise PointsCatalogError(f"plc/{workstation}.yaml sync.diff_threshold_mm 必须 >= 0, 得到 {thr}")
        else:
            thr = None
        return ServoSyncGroup(
            workstation=workstation,
            target_node=str(raw["target_node"]),
            hmi_mirror_node=str(raw["hmi_mirror_node"]),
            req_node=str(raw["req_node"]),
            ack_node=str(raw["ack_node"]),
            src_node=str(raw["src_node"]),
            array_len=array_len,
            diff_threshold=thr,
        )

    @staticmethod
    def _parse_servo_targets(workstation: str, raw) -> list[PlcServoTarget]:
        """校验单文件 plc_servo_target 列表; workstation 由文件名注入 (条目内不声明)。"""
        if not isinstance(raw, list):
            raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target 必须是列表")
        out: list[PlcServoTarget] = []
        seen: set[str] = set()
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target[{i}] 必须是 mapping")
            for k in ("key", "node", "label", "value", "limits"):
                if k not in e:
                    raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target[{i}] 缺少字段 {k!r}")
            key = str(e["key"])
            if key in seen:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target key 重复: {key}")
            seen.add(key)
            limits = e["limits"]
            if not isinstance(limits, dict) or "min" not in limits or "max" not in limits:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target[{key}].limits 必须含 min/max")
            lo, hi = float(limits["min"]), float(limits["max"])
            if lo >= hi:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target[{key}].limits min({lo}) 必须小于 max({hi})")
            value = float(e["value"])
            if not (lo <= value <= hi):
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_target[{key}].value {value} 超出限位 [{lo}, {hi}]")
            slot_raw = e.get("hmi_slot")
            out.append(PlcServoTarget(
                key=key, node=str(e["node"]), actpos=str(e.get("actpos", "")),
                label=str(e["label"]), workstation=workstation,
                value=value, min_limit=lo, max_limit=hi,
                limit_source=bool(e.get("limit_source", False)),
                hmi_node=str(e.get("hmi_node", "")),
                hmi_slot=None if slot_raw is None else int(slot_raw),
                pending=bool(e.get("pending", False)),
            ))
        return out

    @staticmethod
    def _parse_servo_composites(workstation: str, raw) -> list[PlcServoComposite]:
        """校验单文件 plc_servo_composite 列表 (组合点位); workstation 由文件名注入 (条目内不声明)。"""
        if not isinstance(raw, list):
            raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_composite 必须是列表")
        out: list[PlcServoComposite] = []
        seen: set[str] = set()
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_composite[{i}] 必须是 mapping")
            for k in ("key", "label", "members"):
                if k not in e:
                    raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_composite[{i}] 缺少字段 {k!r}")
            key = str(e["key"])
            if key in seen:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_composite key 重复: {key}")
            seen.add(key)
            members_raw = e["members"]
            if not isinstance(members_raw, list) or not members_raw:
                raise PointsCatalogError(f"plc/{workstation}.yaml plc_servo_composite[{key}].members 必须是非空列表")
            members: list[PlcServoCompositeMember] = []
            mseen: set[str] = set()
            for j, m in enumerate(members_raw):
                if not isinstance(m, dict):
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{j}] 必须是 mapping")
                for k in ("key", "label", "node", "actpos", "value", "limits"):
                    if k not in m:
                        raise PointsCatalogError(
                            f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{j}] 缺少字段 {k!r}")
                mkey = str(m["key"])
                if mkey in mseen:
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}] 成员 key 重复: {mkey}")
                mseen.add(mkey)
                limits = m["limits"]
                if not isinstance(limits, dict) or "min" not in limits or "max" not in limits:
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{mkey}].limits 必须含 min/max")
                lo, hi = float(limits["min"]), float(limits["max"])
                if lo >= hi:
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{mkey}].limits min({lo}) 必须小于 max({hi})")
                value = float(m["value"])
                if not (lo <= value <= hi):
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{mkey}].value {value} 超出限位 [{lo}, {hi}]")
                node, actpos = str(m["node"]), str(m["actpos"])
                if not node or not actpos:
                    raise PointsCatalogError(
                        f"plc/{workstation}.yaml plc_servo_composite[{key}].members[{mkey}] node/actpos 不可为空")
                members.append(PlcServoCompositeMember(
                    key=mkey, label=str(m["label"]), node=node, actpos=actpos,
                    value=value, min_limit=lo, max_limit=hi,
                ))
            out.append(PlcServoComposite(
                key=key, label=str(e["label"]), workstation=workstation, members=tuple(members)))
        return out

    def reload(self) -> None:
        """重新加载 points/ 目录 (编辑保存后调用)。"""
        self._catalog, self._target_files = self._load()

    def set_registry(self, registry: PointRegistry) -> None:
        """热替换机器人点表 (robot 点位编辑保存后)。"""
        self._registry = registry

    @property
    def points_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # 原始 yaml/json 读写 (浏览 + 校验后落盘): 原始编辑器 = points/ 的文件视图
    # ------------------------------------------------------------------

    def list_raw_files(self) -> list[dict]:
        """枚举 points/ 下可浏览/编辑的真实文件 (登记表 + 各工位 plc + 机器人真源)。"""
        files: list[dict] = [{"kind": STATIONS_FILE, "label": "stations.yaml (工位登记表)"}]
        plc_dir = self._dir / PLC_SUBDIR
        if plc_dir.is_dir():
            for f in sorted(plc_dir.glob("*.yaml")):
                files.append({"kind": f"{PLC_SUBDIR}/{f.name}", "label": f"plc/{f.name} ({f.stem} 伺服点位)"})
        if self._robot_points_file is not None:
            files.append({"kind": ROBOT_POINTS_KIND, "label": "robot_points.json (示教点真源)"})
        if self._robot_meta_file is not None:
            files.append({"kind": ROBOT_META_KIND, "label": "robot_points_meta.json (覆盖+派生点)"})
        labels_file = self._robot_labels_file
        if labels_file is not None and labels_file.exists():
            files.append({"kind": ROBOT_LABELS_KIND, "label": "labels.yaml (点位中文显示名)"})
        return files

    def _valid_yaml_kinds(self) -> set[str]:
        """当前磁盘上可编辑的 yaml 文件 kind 集合 (防路径穿越: 只接受枚举到的真实文件)。"""
        kinds = {STATIONS_FILE}
        plc_dir = self._dir / PLC_SUBDIR
        if plc_dir.is_dir():
            kinds |= {f"{PLC_SUBDIR}/{f.name}" for f in plc_dir.glob("*.yaml")}
        return kinds

    def _raw_path(self, kind: str) -> Path:
        if kind == ROBOT_POINTS_KIND:
            if self._robot_points_file is None:
                raise PointsCatalogError("robot_points 文件未配置")
            return self._robot_points_file
        if kind == ROBOT_META_KIND:
            if self._robot_meta_file is None:
                raise PointsCatalogError("robot_meta 文件未配置")
            return self._robot_meta_file
        if kind == ROBOT_LABELS_KIND:
            labels_file = self._robot_labels_file
            if labels_file is None:
                raise PointsCatalogError("labels 文件未配置")
            return labels_file
        if kind in self._valid_yaml_kinds():
            return self._dir / kind
        raise PointsCatalogError(f"未知原始文件: {kind}")

    def read_raw(self, kind: str) -> dict:
        """读取底层原始文件内容供浏览/编辑。"""
        path = self._raw_path(kind)
        return {"kind": kind, "path": str(path), "text": path.read_text(encoding="utf-8")}

    def save_raw(self, kind: str, text: str) -> dict:
        """校验 text 后落盘; 不过校验抛错绝不写坏文件。

        - stations.yaml / plc/*.yaml : yaml 解析 + 全目录装配校验 (跨文件 key 唯一/限位等) -> 写盘 -> reload()。
        - robot_*                    : 写临时配对文件过 PointRegistry.load 全量校验 -> 写盘 -> 热替换 RobotController.registry。
        - robot/labels.yaml          : 先写临时 labels 文件过 PointRegistry.load (结构校验) -> 写盘 -> 热替换。
        """
        if kind == ROBOT_LABELS_KIND:
            return self._save_robot_labels_raw(text)
        if kind in (ROBOT_POINTS_KIND, ROBOT_META_KIND):
            return self._save_robot_raw(kind, text)

        path = self._raw_path(kind)                      # 校验 kind 合法 (防穿越)
        parsed = yaml.safe_load(text)                    # YAML 语法 (失败抛 YAMLError)
        self._assemble_from_disk(override_kind=kind, override_raw=parsed)  # 全量装配校验
        path.write_text(text, encoding="utf-8")
        self.reload()
        return {"kind": kind, "saved": True}

    def _assemble_from_disk(self, *, override_kind: str, override_raw) -> tuple[PointsCatalog, dict[str, str]]:
        """以磁盘现状为基, 用 override_raw 替换 override_kind 对应文件后整体装配校验 (不落盘)。"""
        stations_raw, plc_raws = self._read_dir(self._dir)
        if override_kind == STATIONS_FILE:
            stations_raw = override_raw
        else:  # plc/<工位>.yaml
            plc_raws[Path(override_kind).stem] = override_raw
        return self._assemble(stations_raw, plc_raws)

    def _save_robot_labels_raw(self, text: str) -> dict:
        """robot/labels.yaml: 用临时 labels 文件过 PointRegistry.load 结构校验, 通过才落盘热替换。

        中文名是纯展示字段, 校验只为挡住结构错误 (version/section 类型), 不校验覆盖率 ——
        未登记的点自动回退英文 alias, 允许现场逐步补名。
        """
        path = self._raw_path(ROBOT_LABELS_KIND)
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置, 无法保存")
        yaml.safe_load(text)  # YAML 语法 (失败抛 YAMLError)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = Path(f.name)
        try:
            new_reg = PointRegistry.load(
                self._robot_points_file, source_version=self._point_source_version,
                meta_path=self._robot_meta_file, labels_path=tmp)
        finally:
            tmp.unlink(missing_ok=True)

        path.write_text(text, encoding="utf-8")
        self._registry = new_reg
        if self._robot is not None:
            self._robot.registry = new_reg
        return {"kind": ROBOT_LABELS_KIND, "saved": True, "points": len(new_reg.points)}

    def _save_robot_raw(self, kind: str, text: str) -> dict:
        """robot_points / robot_meta: 先语法校验, 再用临时配对文件过 PointRegistry.load, 通过才落盘热替换。"""
        path = self._raw_path(kind)
        json.loads(text)  # JSON 语法 (失败抛 ValueError)
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置, 无法保存")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = Path(f.name)
        try:
            if kind == ROBOT_POINTS_KIND:
                new_reg = PointRegistry.load(
                    tmp, source_version=self._point_source_version, meta_path=self._robot_meta_file,
                    labels_path=self._robot_labels_file)
            else:  # robot_meta
                new_reg = PointRegistry.load(
                    self._robot_points_file, source_version=self._point_source_version, meta_path=tmp,
                    labels_path=self._robot_labels_file)
        finally:
            tmp.unlink()

        # 校验通过 -> 落盘 + 热替换运行期点表
        path.write_text(text, encoding="utf-8")
        self._registry = new_reg
        if self._robot is not None:
            self._robot.registry = new_reg
        return {"kind": kind, "saved": True, "points": len(new_reg.points)}

    # ------------------------------------------------------------------
    # 单点原始片段读写 (机器人): 只看/只改当前点对应的源条目, 避免整文件冗长
    # ------------------------------------------------------------------
    #
    # 机器人点的"原始内容"横跨两个真源文件, 故片段以带标签的 JSON 包装:
    #   - 基础点 (示教点): {"point": <robot_points.json 条目>, "meta": <overrides[Pxx] 或 {}>}
    #   - 派生点         : {"supplement": <supplement[] 中 point_id 匹配的条目>}
    # 保存时把片段拼回完整结构, 写临时配对文件过 PointRegistry.load 全量校验, 通过才落盘热替换。

    def _find_robot_point(self, point_id: str) -> RobotPoint | None:
        try:
            return self._registry.get(point_id)
        except KeyError:
            return None

    def _read_points_json(self) -> list:
        data = json.loads(self._robot_points_file.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise PointsCatalogError("robot_points.json 顶层必须是数组")
        return data

    def _read_meta_json(self) -> dict:
        data = json.loads(self._robot_meta_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PointsCatalogError("robot_points_meta.json 顶层必须是对象")
        return data

    @staticmethod
    def _coerce_robot_vector(values, *, field: str) -> list[float]:
        if not isinstance(values, (list, tuple)) or len(values) != 6:
            raise ValueError(f"{field} 必须是 6 元数组")
        try:
            return [float(v) for v in values]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须全为数值") from exc

    @staticmethod
    def _robot_delta(new_values, old_values) -> list[float]:
        return [
            round(float(new_values[i]) - float(old_values[i]), 4)
            for i in range(6)
        ]

    def _load_robot_registry_from_data(self, points_data: list, meta_data: dict):
        """用临时配对文件全量校验 robot_points + meta, 通过才返回落盘文本。"""
        points_text = json.dumps(points_data, ensure_ascii=False)
        meta_text = json.dumps(meta_data, ensure_ascii=False, indent=2)
        tmps: list[Path] = []
        try:
            for content in (points_text, meta_text):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                    f.write(content)
                    tmps.append(Path(f.name))
            new_reg = PointRegistry.load(
                tmps[0], source_version=self._point_source_version, meta_path=tmps[1],
                labels_path=self._robot_labels_file)
        finally:
            for t in tmps:
                t.unlink(missing_ok=True)
        return new_reg, points_text, meta_text

    def _require_base_robot_point(self, point_id: str) -> tuple[RobotPoint, list, int]:
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置")
        p = self._find_robot_point(point_id)
        if p is None:
            raise PointsCatalogError(f"未知机器人点位: {point_id}")
        points_data = self._read_points_json()
        idx = next((i for i, r in enumerate(points_data)
                    if str(r.get("name")) == p.robot_name), None)
        if p.derived_from is not None or idx is None:
            raise PermissionError(
                f"点位 {p.point_id} 不是 robot_points.json 基础示教点, 不支持直接覆盖坐标; "
                "请改其 base 点或 supplement offset")
        return p, points_data, idx

    # ------------------------------------------------------------------
    # 示教复核 (teach-verify): 当前点示教 → 退到进近点 → 二次进入 → 回位漂移 → 提交
    #   支持基础示教点 (写 robot_points.json) 与网格库位 (写 meta.grids); 进近点用"新"捕获位算。
    # ------------------------------------------------------------------

    def _query_feedback(self, p: RobotPoint):
        """读机器人当前反馈 (兼容 query 是否接受 user/tool 参数)。"""
        query = self._robot.query
        params = inspect.signature(query).parameters
        accepts_frame = (
            "user" in params
            or "tool" in params
            or any(v.kind == inspect.Parameter.VAR_KEYWORD for v in params.values())
        )
        return query(user=p.user, tool=p.tool) if accepts_frame else query()

    def _find_grid_slot(self, robot_name: str):
        """按 robot_name 在 meta.grids 找 (grid, slot, is_anchor); 非网格库位返回 None。"""
        if self._robot_meta_file is None:
            return None
        for g in (self._read_meta_json().get("grids") or []):
            anchors = {
                (int(a["row"]), int(a["col"]))
                for a in (g.get("anchors") or [])
                if "row" in a and "col" in a
            }
            for s in (g.get("slots") or []):
                if str(s.get("name")) == robot_name:
                    is_anchor = (int(s.get("row", -1)), int(s.get("col", -1))) in anchors
                    return g, s, is_anchor
        return None

    def _approach_points(self, robot_name: str) -> list[RobotPoint]:
        """该点的进近点 = registry 中 derived_from==本点 且 role 以 approach 开头的派生点。"""
        return [
            q for q in self._registry.points
            if q.derived_from == robot_name and str(q.role).startswith("approach")
        ]

    def _resolve_teachable(self, point_id: str) -> RobotPoint:
        """解析可示教目标 (基础示教点 或 网格库位); offset 派生接近点不可独立示教。"""
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置")
        p = self._find_robot_point(point_id)
        if p is None:
            raise PointsCatalogError(f"未知机器人点位: {point_id}")
        if p.derived_from is not None and self._find_grid_slot(p.robot_name) is None:
            raise PermissionError(
                f"点位 {p.point_id} 是 offset 派生接近点, 不能独立示教; 请示教其 base 点")
        return p

    def capture_robot_point(self, point_id: str) -> dict:
        """读当前机器人反馈, 生成覆盖前预览 (不落盘)。支持基础示教点与网格库位。"""
        # 先做可示教/权限校验 (offset 派生接近点即拒 PermissionError, 与机器人是否就绪无关)
        p = self._resolve_teachable(point_id)
        if self._robot is None:
            raise PointsCatalogError("机器人控制器未就绪, 无法采集当前位置")
        grid_slot = self._find_grid_slot(p.robot_name)
        feedback = self._query_feedback(p)
        pose = self._coerce_robot_vector(feedback.pose, field="pose")
        joint = self._coerce_robot_vector(feedback.joint, field="joint")
        current_pose = list(p.pose)
        current_joint = [] if p.joint is None else list(p.joint)
        return {
            "point_id": p.point_id,
            "robot_name": p.robot_name,
            "is_grid": grid_slot is not None,
            "is_anchor": bool(grid_slot[2]) if grid_slot is not None else False,
            "has_approach": bool(self._approach_points(p.robot_name)),
            "source_file": str(self._robot_points_file),
            "meta_file": str(self._robot_meta_file),
            "current": {
                "pose": current_pose,
                "joint": current_joint,
                "user": p.user,
                "tool": p.tool,
                "calibrated_at": p.calibrated_at,
            },
            "captured": {
                "pose": pose,
                "joint": joint,
                "user": p.user,
                "tool": p.tool,
            },
            "delta": {
                "pose": self._robot_delta(pose, current_pose),
                "joint": self._robot_delta(joint, current_joint) if current_joint else None,
            },
        }

    def teach_plan(self, point_id: str, captured_pose) -> dict:
        """据"新"捕获位算退出/二次进入的临时进近点 (捕获位 + 各进近点相对当前目标的偏移)。

        waypoints 按到目标距离 near→far 排序; 前端正向走=退出, 反向+目标=二次进入。
        无进近点 (home/过渡位) → waypoints 空, 前端隐藏退/进两步。
        """
        p = self._resolve_teachable(point_id)
        cap = self._coerce_robot_vector(captured_pose, field="captured_pose")
        cur = list(p.pose)
        wps: list[dict] = []
        for q in self._approach_points(p.robot_name):
            offset = [q.pose[k] - cur[k] for k in range(6)]
            temp = [round(cap[k] + offset[k], 4) for k in range(6)]
            wps.append({
                "role": q.role,
                "label": q.point_id,
                "pose": temp,
                "dist_mm": round(math.hypot(offset[0], offset[1], offset[2]), 3),
            })
        wps.sort(key=lambda w: w["dist_mm"])
        return {
            "point_id": p.point_id,
            "target_pose": [round(v, 4) for v in cap],
            "has_approach": bool(wps),
            "waypoints": wps,
        }

    def teach_move(self, point_id: str, pose, motion: str = "move_l") -> dict:
        """示教复核: 运动到给定临时位姿 (默认 move_l 限速)。安全包络内; 阻塞式 (路由经 executor 调)。"""
        if self._robot is None:
            raise PointsCatalogError("机器人控制器未就绪")
        p = self._resolve_teachable(point_id)
        target = self._coerce_robot_vector(pose, field="pose")
        reach = max(abs(target[k] - p.pose[k]) for k in range(3))
        if reach > _TEACH_MAX_REACH_MM:
            raise ValueError(
                f"复核目标离当前点 {reach:.1f}mm 超上限 {_TEACH_MAX_REACH_MM}mm, 拒绝运动 (疑似误算)")
        if motion not in {"move_j", "move_l"}:
            raise ValueError(f"不支持的运动类型: {motion}")
        self._robot.move_to_pose(target, motion, user=p.user, tool=p.tool)
        return {"point_id": p.point_id, "moved_to": [round(v, 4) for v in target], "status": "DONE"}

    def teach_drift(self, point_id: str, captured_pose) -> dict:
        """二次进入到位后读实际位, 与捕获位比 → 回位漂移 (暴露重复性/示教一致性)。"""
        if self._robot is None:
            raise PointsCatalogError("机器人控制器未就绪")
        p = self._resolve_teachable(point_id)
        cap = self._coerce_robot_vector(captured_pose, field="captured_pose")
        fb = self._query_feedback(p)
        actual = self._coerce_robot_vector(fb.pose, field="pose")
        drift_mm = round(max(abs(actual[k] - cap[k]) for k in range(3)), 3)
        drift_deg = round(max(abs(_norm_deg(actual[k] - cap[k])) for k in range(3, 6)), 3)
        return {
            "point_id": p.point_id,
            "actual": [round(v, 4) for v in actual],
            "captured": [round(v, 4) for v in cap],
            "drift_mm": drift_mm,
            "drift_deg": drift_deg,
            "over": drift_mm > _TEACH_DRIFT_MM_TOL or drift_deg > _TEACH_DRIFT_DEG_TOL,
            "tol_mm": _TEACH_DRIFT_MM_TOL,
            "tol_deg": _TEACH_DRIFT_DEG_TOL,
        }

    def commit_robot_point_capture(
        self,
        point_id: str,
        *,
        pose,
        joint,
        confirm: bool = False,
        note: str | None = None,
    ) -> dict:
        """把已预览的当前位置写回真源; confirm=False 拒绝。基础点→robot_points.json; 网格库位→meta.grids。"""
        if not confirm:
            raise PermissionError("覆盖机器人点位必须 confirm=true")
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置")
        new_pose = self._coerce_robot_vector(pose, field="pose")
        target = self._find_robot_point(point_id)
        grid_slot = None if target is None else self._find_grid_slot(target.robot_name)
        if grid_slot is not None:
            return self._commit_grid_teach(target, grid_slot, new_pose, note)
        # 基础示教点: 覆盖 robot_points.json 的 pose/joint
        p, points_data, idx = self._require_base_robot_point(point_id)
        new_joint = self._coerce_robot_vector(joint, field="joint")

        old_record = dict(points_data[idx])
        updated = dict(old_record)
        updated["pose"] = new_pose
        updated["joint"] = new_joint
        points_data[idx] = updated

        meta_data = self._read_meta_json()
        overrides = meta_data.setdefault("overrides", {})
        meta_entry = dict(overrides.get(p.robot_name) or {})
        meta_entry["calibrated_at"] = _utc_timestamp()
        if note is not None and str(note).strip():
            meta_entry["notes"] = str(note).strip()
        overrides[p.robot_name] = meta_entry

        new_reg, points_text, meta_text = self._load_robot_registry_from_data(points_data, meta_data)
        self._robot_points_file.write_text(points_text, encoding="utf-8")
        self._robot_meta_file.write_text(meta_text, encoding="utf-8")
        self._registry = new_reg
        if self._robot is not None:
            self._robot.registry = new_reg

        new_p = next((q for q in new_reg.points if q.source_id == p.source_id), None)
        return {
            "category": ROBOT_CATEGORY,
            "point_id": (new_p.point_id if new_p else p.point_id),
            "robot_name": p.robot_name,
            "saved": True,
            "points": len(new_reg.points),
            "old": {
                "pose": list(p.pose),
                "joint": [] if p.joint is None else list(p.joint),
            },
            "captured": {
                "pose": new_pose,
                "joint": new_joint,
                "user": p.user,
                "tool": p.tool,
            },
            "delta": {
                "pose": self._robot_delta(new_pose, p.pose),
                "joint": self._robot_delta(new_joint, p.joint) if p.joint is not None else None,
            },
            "calibrated_at": (new_p.calibrated_at if new_p else meta_entry["calibrated_at"]),
        }

    def _commit_grid_teach(self, p: RobotPoint, grid_slot, new_pose, note) -> dict:
        """网格库位示教提交: 锚点→改 anchor 位姿 (整架重解); 非锚位→改该 slot 的 offset。写 meta.grids 热重载。"""
        from eit_ptlc.controller.point_grid import GridAnchor, grid_pose, solve_grid_planes

        grid, slot, is_anchor = grid_slot
        meta_data = self._read_meta_json()
        g = next((x for x in (meta_data.get("grids") or [])
                  if str(x.get("id")) == str(grid.get("id"))), None)
        if g is None:
            raise PointsCatalogError(f"meta.grids 中未找到网格 {grid.get('id')}")
        row, col = int(slot["row"]), int(slot["col"])
        if is_anchor:
            # 锚点: 直接改其示教位姿, 整架随之重解 (PointRegistry.load 重新 solve)
            anchor = next((a for a in (g.get("anchors") or [])
                           if int(a["row"]) == row and int(a["col"]) == col), None)
            if anchor is None:
                raise PointsCatalogError(f"网格 {g.get('id')} 未找到锚点 r{row}c{col}")
            anchor["pose"] = [round(float(v), 6) for v in new_pose]
            mode = "anchor"
        else:
            # 非锚位: offset = 捕获位 − 当前锚点解出的网格标称位
            anchors = [GridAnchor(int(a["row"]), int(a["col"]), tuple(float(v) for v in a["pose"]))
                       for a in (g.get("anchors") or [])]
            nominal = grid_pose(solve_grid_planes(anchors), row, col, ndigits=None)
            entry = next((s for s in (g.get("slots") or []) if str(s.get("name")) == p.robot_name), None)
            if entry is None:
                raise PointsCatalogError(f"网格 {g.get('id')} 未找到库位 {p.robot_name}")
            entry["offset"] = [round(float(new_pose[k]) - nominal[k], 6) for k in range(6)]
            mode = "offset"
        if note is not None and str(note).strip():
            for s in (g.get("slots") or []):
                if str(s.get("name")) == p.robot_name:
                    s["notes"] = str(note).strip()

        points_data = self._read_points_json()
        new_reg, points_text, meta_text = self._load_robot_registry_from_data(points_data, meta_data)
        self._robot_points_file.write_text(points_text, encoding="utf-8")
        self._robot_meta_file.write_text(meta_text, encoding="utf-8")
        self._registry = new_reg
        if self._robot is not None:
            self._robot.registry = new_reg

        new_p = next((q for q in new_reg.points if q.robot_name == p.robot_name), None)
        return {
            "category": ROBOT_CATEGORY,
            "point_id": (new_p.point_id if new_p else p.point_id),
            "robot_name": p.robot_name,
            "saved": True,
            "grid": str(g.get("id")),
            "commit_mode": mode,
            "points": len(new_reg.points),
            "old": {"pose": list(p.pose)},
            "captured": {"pose": [round(float(v), 6) for v in new_pose]},
            "delta": {"pose": self._robot_delta(new_pose, p.pose)},
        }

    def read_point_raw(self, category: str, point_id: str) -> dict:
        """返回单个机器人点位对应的原始源片段 (供详情页只看/编辑)。"""
        if category != ROBOT_CATEGORY:
            raise PointsCatalogError("单点片段编辑当前仅支持机器人点位")
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置")
        p = self._find_robot_point(point_id)
        if p is None:
            raise PointsCatalogError(f"未知机器人点位: {point_id}")
        is_derived = p.derived_from is not None
        if is_derived:
            sup = next((r for r in (self._read_meta_json().get("supplement") or [])
                        if str(r.get("point_id")) == p.point_id), None)
            if sup is None:
                raise PointsCatalogError(f"supplement 中未找到派生点: {p.point_id}")
            fragment = {"supplement": sup}
            files = {"meta": str(self._robot_meta_file)}
        else:
            base = next((r for r in self._read_points_json()
                         if str(r.get("name")) == p.robot_name), None)
            if base is None:
                raise PointsCatalogError(f"robot_points.json 中未找到点: {p.robot_name}")
            meta = self._read_meta_json().get("overrides", {}).get(p.robot_name)
            fragment = {"point": base, "meta": meta or {}}
            files = {"points": str(self._robot_points_file), "meta": str(self._robot_meta_file)}
        return {
            "category": category,
            "point_id": p.point_id,
            "robot_name": p.robot_name,
            "is_derived": is_derived,
            "files": files,
            "text": json.dumps(fragment, ensure_ascii=False, indent=2),
        }

    def save_point_raw(self, category: str, point_id: str, text: str) -> dict:
        """把编辑后的单点片段拼回真源 -> 全量校验 -> 落盘热替换。

        约束: 不允许经此路径改 name (基础点) / point_id (派生点) 作为重定位键;
        其余字段由 PointRegistry.load 校验 (status/allowed_motion/pose/joint 等)。
        """
        if category != ROBOT_CATEGORY:
            raise PointsCatalogError("单点片段编辑当前仅支持机器人点位")
        if self._robot_points_file is None or self._robot_meta_file is None:
            raise PointsCatalogError("机器人点表真源未配置, 无法保存")
        p = self._find_robot_point(point_id)
        if p is None:
            raise PointsCatalogError(f"未知机器人点位: {point_id}")

        fragment = json.loads(text)  # JSON 语法 (失败抛 ValueError)
        if not isinstance(fragment, dict):
            raise PointsCatalogError("片段必须是 JSON 对象")

        points_data = self._read_points_json()
        meta_data = self._read_meta_json()

        if p.derived_from is not None:
            sup = fragment.get("supplement")
            if not isinstance(sup, dict):
                raise PointsCatalogError("派生点片段必须含 'supplement' 对象")
            if str(sup.get("point_id")) != p.point_id:
                raise PointsCatalogError(f"不允许修改 point_id (应保持 {p.point_id})")
            arr = meta_data.get("supplement") or []
            idx = next((i for i, r in enumerate(arr)
                        if str(r.get("point_id")) == p.point_id), None)
            if idx is None:
                raise PointsCatalogError("supplement 中未找到该派生点")
            arr[idx] = sup
            meta_data["supplement"] = arr
        else:
            pt = fragment.get("point")
            if not isinstance(pt, dict):
                raise PointsCatalogError("基础点片段必须含 'point' 对象")
            if str(pt.get("name")) != p.robot_name:
                raise PointsCatalogError(f"不允许修改 name (应保持 {p.robot_name})")
            idx = next((i for i, r in enumerate(points_data)
                        if str(r.get("name")) == p.robot_name), None)
            if idx is None:
                raise PointsCatalogError("robot_points.json 中未找到该点")
            points_data[idx] = pt
            meta_frag = fragment.get("meta")
            overrides = meta_data.setdefault("overrides", {})
            if meta_frag in (None, {}):
                overrides.pop(p.robot_name, None)
            elif isinstance(meta_frag, dict):
                overrides[p.robot_name] = meta_frag
            else:
                raise PointsCatalogError("'meta' 必须是 JSON 对象")

        # 写临时配对文件过 PointRegistry.load 全量校验 (保留各文件磁盘风格: points 紧凑, meta 缩进)
        new_reg, points_text, meta_text = self._load_robot_registry_from_data(points_data, meta_data)

        # 校验通过 -> 落盘 + 热替换运行期点表
        self._robot_points_file.write_text(points_text, encoding="utf-8")
        self._robot_meta_file.write_text(meta_text, encoding="utf-8")
        self._registry = new_reg
        if self._robot is not None:
            self._robot.registry = new_reg

        # 编辑 alias 会改 point_id; 用稳定的 source_id 回溯新 id 供前端重定位
        new_p = next((q for q in new_reg.points if q.source_id == p.source_id), None)
        return {
            "category": category,
            "point_id": (new_p.point_id if new_p else p.point_id),
            "saved": True,
            "points": len(new_reg.points),
        }

    @property
    def servo_container(self) -> tuple[str, ...]:
        return self._catalog.servo_container

    def servo_entry(self, key: str) -> PlcServoPoint | None:
        for s in self._catalog.servo_points:
            if s.key == key:
                return s
        return None

    def rail_slot_mm(self, slot: int) -> float | None:
        """地轨槽码 (1-6) → 站点坐标 mm (PC 真源 value); 无此槽/未收编值 → None。

        供 auto_rail 原语判「实际 mm 与目标槽 mm 之差」: 位1=位2=168、位5=位6=600 槽码→mm
        不可逆, 故按 mm 判是否已在位 (同 mm 异槽不无谓移轨)。地轨为唯一离散召回工位。
        """
        for s in self._catalog.servo_points:
            if s.workstation == "rail" and s.slot == slot:
                return s.value
        return None

    # ------------------------------------------------------------------
    # 机器人点位 (来自 registry, 含派生点)
    # ------------------------------------------------------------------

    @staticmethod
    def _robot_dto(p: RobotPoint) -> dict:
        return {
            "category": ROBOT_CATEGORY,
            "id": p.point_id,
            "robot_name": p.robot_name,
            "alias": p.alias,
            "label": p.label,          # 中文显示名 (labels.yaml); 空串时前端回退 alias
            "workstation": p.workstation,
            "role": p.role,
            "status": p.status,
            "allowed_motion": list(p.allowed_motion),
            "pose": [round(v, 4) for v in p.pose],
            "joint": None if p.joint is None else [round(v, 4) for v in p.joint],
            "user": p.user,
            "tool": p.tool,
            "acc": p.acc,
            "vel": p.vel,
            "cp": p.cp,
            "derived_from": p.derived_from,
            "derivation": p.derivation,
            "is_derived": p.derived_from is not None,
            "notes": p.notes,
            "calibrated_at": p.calibrated_at,
        }

    def list_robot(self) -> list[dict]:
        return [self._robot_dto(p) for p in self._registry.points]

    def list_grids(self) -> list[dict]:
        """仿射网格库位布局 (供点位页示意图): meta.grids 结构 + 运行期算得位姿/偏置。

        每个 grid -> {id, workstation, rows, cols, notes, slots:[{name, alias, row, col,
        is_anchor, offset(6), offset_mm(xyz模), pose}]}。pose 取自运行期 registry (算出的
        库位); 前端据此画网格图 (锚点高亮 + 每格偏置), 无需解析派生式字符串。
        """
        if self._robot_meta_file is None:
            return []
        grids = self._read_meta_json().get("grids") or []
        out: list[dict] = []
        for g in grids:
            anchors = {
                (int(a["row"]), int(a["col"]))
                for a in (g.get("anchors") or [])
                if "row" in a and "col" in a
            }
            slots: list[dict] = []
            for s in g.get("slots") or []:
                name = str(s.get("name"))
                row, col = int(s.get("row", 0)), int(s.get("col", 0))
                offset = [float(v) for v in (s.get("offset") or [0.0] * 6)]
                off_mm = round((offset[0] ** 2 + offset[1] ** 2 + offset[2] ** 2) ** 0.5, 3)
                p = self._find_robot_point(name)
                slots.append({
                    "name": name,
                    "alias": str(s.get("alias", name)),
                    "row": row,
                    "col": col,
                    "is_anchor": (row, col) in anchors,
                    "offset": [round(v, 4) for v in offset],
                    "offset_mm": off_mm,
                    "pose": None if p is None else [round(v, 4) for v in p.pose],
                })
            out.append({
                "id": str(g.get("id", "grid")),
                "workstation": str(g.get("workstation", "")),
                "rows": int(g.get("rows", 0)),
                "cols": int(g.get("cols", 0)),
                "notes": str(g.get("notes", "")),
                "slots": slots,
            })
        return out

    # ------------------------------------------------------------------
    # PLC 伺服点位 (B 方案: 只读配置展示; struct 槽位点不经 OPC 读写)
    # ------------------------------------------------------------------

    def _servo_dto(self, s: PlcServoPoint) -> dict:
        # 槽位/限位/角色语义 + (收编后) PC 真源 value。sync=True 表示该工位经 push/pull/diff 对账。
        return {
            "category": PLC_SERVO_CATEGORY,
            "id": s.key,
            "label": s.label,
            "node": s.node,
            "workstation": s.workstation,
            "role": s.role,
            "slot": s.slot,
            "value": s.value,
            "limits": {"min": s.min_limit, "max": s.max_limit},
            "backup": s.backup,
            "sync": self.sync_group(s.workstation) is not None,
        }

    def list_plc_servo(self) -> list[dict]:
        return [self._servo_dto(s) for s in self._catalog.servo_points]

    # ------------------------------------------------------------------
    # 双源同步 (push/pull/diff): 收编工位 (plc_servo + sync 块) 的 PC↔HMI 对账
    #   承重墙: 自动只读 PC 真源 (target_node 数组), 永不读 HMI position[]; PC 经 PLC flat 镜像
    #   (hmi_mirror_node) 做 diff/pull, 不直访 struct。详见 docs/点位双源同步设计 §5。
    # ------------------------------------------------------------------

    def sync_group(self, workstation: str) -> ServoSyncGroup | None:
        for g in self._catalog.sync_groups:
            if g.workstation == workstation:
                return g
        return None

    def _servo_points_in(self, workstation: str) -> list[PlcServoPoint]:
        """按 slot 升序返回该工位的 plc_servo 点 (同步数组按 slot 索引)。"""
        pts = [s for s in self._catalog.servo_points if s.workstation == workstation]
        return sorted(pts, key=lambda s: s.slot)

    def _require_sync(self, workstation: str) -> ServoSyncGroup:
        g = self.sync_group(workstation)
        if g is None:
            raise PointsCatalogError(f"工位 {workstation} 未配置 sync 同步契约")
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        return g

    def _target_array(self, workstation: str, g: ServoSyncGroup) -> list[float]:
        """按 slot 把各 plc_servo 点的 PC 真源 value 摆进定长数组 (空槽补 0.0)。"""
        arr = [0.0] * g.array_len
        for s in self._servo_points_in(workstation):
            if s.value is not None:
                arr[s.slot - 1] = s.value
        return arr

    async def diff_sync(self, workstation: str, *,
                        threshold: float | None = None) -> dict:
        """逐点对照 PC 真源 value ↔ HMI 工作副本 (经 PLC flat 镜像读), 列出超阈点 (只读, 安全)。

        阈值优先级: 显式入参 > 工位 sync.diff_threshold_mm (yaml 真源) > DEFAULT_SYNC_DIFF_THRESHOLD。
        注 (见设计 §4): 比的是「基准值」; 多带运行的逐带偏移不算故障/代差。
        """
        g = self._require_sync(workstation)
        if threshold is None:
            threshold = g.diff_threshold if g.diff_threshold is not None else DEFAULT_SYNC_DIFF_THRESHOLD
        mirror = await self._driver.read_variable(g.hmi_mirror_node)
        if not isinstance(mirror, (list, tuple)):
            raise PointsCatalogError(f"{g.hmi_mirror_node} 非数组 (得到 {type(mirror).__name__})")
        rows: list[dict] = []
        any_over = False
        for s in self._servo_points_in(workstation):
            idx = s.slot - 1
            hmi_val = float(mirror[idx]) if idx < len(mirror) else None
            delta = None if (hmi_val is None or s.value is None) else abs(s.value - hmi_val)
            over = delta is not None and delta > threshold
            any_over = any_over or over
            rows.append({
                "key": s.key, "label": s.label, "slot": s.slot,
                "pc_value": s.value, "hmi_value": hmi_val,
                "delta": delta, "over": over,
            })
        return {"workstation": workstation, "threshold": threshold,
                "any_over": any_over, "points": rows}

    async def ensure_target_confirmed(self, workstation: str) -> dict:
        """把 PC 真源数组写入 target_node 并逐元素回读确认 (单写者; L2 派发器消费前保证已落地)。

        只保证自动正确性 —— 不触发 HMI 邮箱握手 (那是 push_sync 的事)。复用 driver 的
        write_block_confirmed (与 plc_write 同原语): 写后回读, 不符有界重写, 仍不符抛 PLCWriteConfirmError。
        用途: ① push_sync 的第一步; ② 每次地轨 L2 移动前的即时重建 —— PLC 重启后 Rail_Pos_Target
        归 0, 派发器会把 0 当目标移到底端; 移动前回读确认即可兜底 (免 retain / 启动 push / 重连钩子)。
        """
        g = self._require_sync(workstation)
        for s in self._servo_points_in(workstation):
            if s.value is not None and not s.within_limits(s.value):
                raise ValueError(f"地轨点 {s.key} 真源值 {s.value} 超出限位 [{s.min_limit}, {s.max_limit}]")
        arr = self._target_array(workstation, g)
        await self._driver.write_block_confirmed({g.target_node: arr})        # 写真源 + 回读确认
        return {"workstation": workstation, "target_node": g.target_node, "written": arr}

    async def push_sync(self, workstation: str, *,
                        timeout: float = 2.0, poll: float = 0.05) -> dict:
        """PUSH: 把 PC 真源数组写入 target_node 并回读确认 (自动派发器即读它), 再触发 PLC 拷进 HMI 工作副本。

        安全 (只覆盖工作副本): 写真源 (write_block_confirmed, 单写者) + 置 Req=PUSH → 轮询 PLC 置 Ack=DONE.
        target 写入是自动正确性的关键; 邮箱握手仅为同步 HMI 面板显示, 超时不致命 (如 sim 无 POU)。
        """
        res = await self.ensure_target_confirmed(workstation)                 # 写真源 + 回读确认
        g = self._require_sync(workstation)
        await self._driver.write_many({g.src_node: SYNC_SRC_PC,
                                       g.req_node: SYNC_REQ_PUSH})            # 触发 POU 拷进 position[]
        ack = await self._poll_ack_done(g, timeout, poll)
        return {**res, "mirror_synced": ack == SYNC_ACK_DONE, "ack": ack}

    async def _poll_ack_done(self, g: ServoSyncGroup, timeout: float, poll: float) -> int:
        """轮询 ack_node 直到 PLC 置 DONE —— Rail_Sync POU 完成 PUSH 拷贝 (position[]:=Target) 的唯一可信信号。
        返回末次读到的 Ack (超时即返回未完成的当前值, 不抛错: target 已写, 握手失败不致命)。

        不能用 Req==IDLE 判完成: 真机 Rail_Sync POU 未就绪时, PC 写 Req:=PUSH 根本没落到节点
        (节点未建 / 写被丢弃), 回读恒为 IDLE, 会被误判为"已同步"。Ack 只由 POU 置位, 故为准。"""
        import asyncio

        loops = max(1, int(timeout / poll))
        for _ in range(loops):
            ack = int(await self._driver.read_variable(g.ack_node))
            if ack == SYNC_ACK_DONE:
                return ack
            await asyncio.sleep(poll)
        return int(await self._driver.read_variable(g.ack_node))

    async def pull_sync(self, workstation: str, *, confirm: bool = False) -> dict:
        """PULL (危险, 改写真源): 把 HMI 现场教值 (经 flat 镜像读) 收回 PC, 持久化 + 重算 target。

        恒为 PC 提交: 读 hmi_mirror_node → 限位校验 (越限置 Ack=REJECT 并拒绝) → 须 confirm=True
        二次确认 → 写回各点 value 到 plc/<工位>.yaml → 写 target_node (重算自动真源)。
        diff 应在 pull 前由调用方展示; 本方法只在 confirm 后落盘。
        """
        g = self._require_sync(workstation)
        mirror = await self._driver.read_variable(g.hmi_mirror_node)
        if not isinstance(mirror, (list, tuple)):
            raise PointsCatalogError(f"{g.hmi_mirror_node} 非数组 (得到 {type(mirror).__name__})")

        pts = self._servo_points_in(workstation)
        new_values: dict[str, float] = {}
        for s in pts:
            idx = s.slot - 1
            if idx >= len(mirror):
                continue
            v = float(mirror[idx])
            if not s.within_limits(v):
                await self._driver.write_many({g.ack_node: SYNC_ACK_REJECT})
                raise ValueError(
                    f"地轨点 {s.key} 教出值 {v} 超出限位 [{s.min_limit}, {s.max_limit}], 已拒绝 (Ack=REJECT)")
            new_values[s.key] = v

        if not confirm:
            # 仅预览 (不落盘): 列出将提交的值, 供 UI 二次确认
            return {"workstation": workstation, "committed": False,
                    "preview": new_values, "note": "须 confirm=true 才写真源"}

        self._persist_servo_values(workstation, new_values)   # 写 plc/<工位>.yaml (含校验 + reload)
        g = self._require_sync(workstation)                   # reload 后重取 (driver 不变)
        await self._driver.write_many({g.target_node: self._target_array(workstation, g)})
        await self._driver.write_many({g.req_node: SYNC_REQ_IDLE, g.ack_node: SYNC_ACK_DONE})
        return {"workstation": workstation, "committed": True, "values": new_values}

    def set_servo_value(self, key: str, value) -> dict:
        """限位校验后把单个 plc_servo 点的 PC 真源 value 持久化回其 plc/<工位>.yaml (保留注释)。

        与 set_target_value 同范式 (ruamel round-trip + 写前全量校验); 仅改真源, 不下发 (下发走 push_sync)。
        """
        s = self.servo_entry(key)
        if s is None:
            raise PointsCatalogError(f"未知 plc_servo 点位: {key}")
        if self.sync_group(s.workstation) is None:
            raise ValueError(f"plc_servo 点 {key} 所在工位无 sync 契约, 不支持存真源 value")
        v = float(value)
        if not s.within_limits(v):
            raise ValueError(f"plc_servo 点 {key} 值 {v} 超出限位 [{s.min_limit}, {s.max_limit}]")
        self._persist_servo_values(s.workstation, {key: v})
        return {"key": key, "node": s.node, "value": v}

    def _persist_servo_values(self, workstation: str, values: dict[str, float]) -> None:
        """ruamel round-trip 仅改指定 plc_servo 点的 value (保留结构/注释); 写前全量校验, 不通过不落盘。"""
        kind = f"{PLC_SUBDIR}/{workstation}.yaml"
        path = self._dir / kind

        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        with path.open("r", encoding="utf-8") as f:
            doc = ryaml.load(f)
        entries = (doc.get("plc_servo") if isinstance(doc, dict) else None) or []
        by_key = {str(e.get("key")): e for e in entries}
        for k, v in values.items():
            if k not in by_key:
                raise PointsCatalogError(f"{kind} plc_servo 中未找到 {k}")
            by_key[k]["value"] = v

        import io
        buf = io.StringIO()
        ryaml.dump(doc, buf)
        text = buf.getvalue()
        self._assemble_from_disk(override_kind=kind, override_raw=yaml.safe_load(text))
        path.write_text(text, encoding="utf-8")
        self.reload()

    # 说明: B 方案单写者下不提供 plc_servo 的 OPC 实时读写。
    #   HMI struct (HMI_*.position[]) 是"示教槽位"真值, 默认不进 PLC 符号配置 → OPC browse 不到;
    #   且铁律为 PC 不动 HMI position[] (只 PLC/HMI 面板示教维护)。上位机对 PLC 位置的"示教"统一
    #   走 plc_servo_target 的 flat 流程 (读 *_ActPos → 存 value → 下发 *_Target); 地轨/5Z 当前
    #   OPC 不开放可读实际位/可写目标位, 示教在 HMI 面板维护。故 plc_servo 在点位页仅作只读配置展示。

    # ------------------------------------------------------------------
    # PC 侧 flat 目标点位 (B 方案单写者): 值存 plc/<工位>.yaml, 写 PLC *_Target flat 节点
    # ------------------------------------------------------------------

    def target_entry(self, key: str) -> PlcServoTarget | None:
        for t in self._catalog.servo_targets:
            if t.key == key:
                return t
        return None

    def composite_entry(self, key: str) -> PlcServoComposite | None:
        for c in self._catalog.composites:
            if c.key == key:
                return c
        return None

    @staticmethod
    def _target_dto(t: PlcServoTarget, live=None) -> dict:
        return {
            "category": PLC_SERVO_TARGET_CATEGORY,
            "id": t.key,
            "label": t.label,
            "node": t.node,
            "actpos": t.actpos,
            "workstation": t.workstation,
            "value": t.value,
            "limits": {"min": t.min_limit, "max": t.max_limit},
            "limit_source": t.limit_source,
            "hmi_node": t.hmi_node,
            "hmi_slot": t.hmi_slot,
            "pending": t.pending,
            "live": live,
        }

    def list_plc_servo_target(self) -> list[dict]:
        return [self._target_dto(t) for t in self._catalog.servo_targets]

    async def read_target_actpos(self, key: str) -> float:
        """读该目标点位所在轴的实际位置镜像 (*_ActPos flat 节点), 供 jog 采点微调。"""
        t = self.target_entry(key)
        if t is None:
            raise PointsCatalogError(f"未知目标点位: {key}")
        if t.pending:
            raise PointsCatalogError(f"目标 {key} 的 PLC flat 节点待建 (pending), 暂不可读实际位; 可手动存值离线预示教")
        if not t.actpos:
            raise PointsCatalogError(f"目标点位 {key} 未声明 actpos 镜像节点")
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        return float(await self._driver.read_variable(t.actpos))

    def set_target_value(self, key: str, value) -> dict:
        """限位校验后把目标点位的 value 持久化回其所在 plc/<工位>.yaml (PC 侧真值; 保留注释)。

        用 ruamel round-trip 仅改该条 value, 不动其余结构/注释; 写前过全目录装配校验,
        不通过不落盘; 落盘后 reload()。注意: 仅更新存储真值, 不下发到 PLC (下发走 push_target)。
        """
        t = self.target_entry(key)
        if t is None:
            raise PointsCatalogError(f"未知目标点位: {key}")
        if t.limit_source:
            raise ValueError(f"目标 {key} 为限位源点位 (value 仅作软限位), 不可手动存值; 真实下发走 push_well")
        # 注: pending 目标允许存值 —— value 是 PC 侧真源, 可在 PLC flat 节点就绪前离线预示教;
        #     仅"读实际位/下发"(需 OPC) 在 pending 时被拦 (见 read_target_actpos / push_target)。
        v = float(value)
        if not t.within_limits(v):
            raise ValueError(f"目标 {key} 值 {v} 超出限位 [{t.min_limit}, {t.max_limit}]")

        workstation = self._target_files.get(key)
        if workstation is None:
            raise PointsCatalogError(f"目标点位 {key} 无法定位所在 plc 文件")
        kind = f"{PLC_SUBDIR}/{workstation}.yaml"
        path = self._dir / kind

        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        with path.open("r", encoding="utf-8") as f:
            doc = ryaml.load(f)
        entries = (doc.get("plc_servo_target") if isinstance(doc, dict) else None) or []
        target_entry = next((e for e in entries if str(e.get("key")) == key), None)
        if target_entry is None:
            raise PointsCatalogError(f"{kind} plc_servo_target 中未找到 {key}")
        target_entry["value"] = v

        # 写前全量校验 (复用 PyYAML 装配路径), 不通过不落盘
        import io
        buf = io.StringIO()
        ryaml.dump(doc, buf)
        text = buf.getvalue()
        self._assemble_from_disk(override_kind=kind, override_raw=yaml.safe_load(text))
        path.write_text(text, encoding="utf-8")
        self.reload()
        return {"key": key, "node": t.node, "value": v}

    def _require_pushable_target(self, key: str) -> PlcServoTarget:
        """返回可下发的普通目标点位; pending/limit_source/越限一律在写 PLC 前拒绝。"""
        t = self.target_entry(key)
        if t is None:
            raise PointsCatalogError(f"未知目标点位: {key}")
        if t.pending:
            raise ValueError(f"目标 {key} 的 PLC flat 节点待建 (pending), 暂不可下发")
        if t.limit_source:
            raise ValueError(f"目标 {key} 为限位源点位, 不可手动下发; 真实下发走 push_well (仿射按孔)")
        if not t.within_limits(t.value):
            raise ValueError(f"目标 {key} 存储值 {t.value} 超出限位 [{t.min_limit}, {t.max_limit}]")
        return t

    async def push_target(self, key: str) -> dict:
        """把目标点位的存储 value (限位校验后) 写入 PLC flat 节点 (*_Target)。

        B 方案单写者: 仅 PC 写 *_Target。由 servo_target 原子在消费它的 L2 触发前调用,
        保证写在 Start 之前 (见 PLC 交付文档「写/读时序契约」)。
        """
        t = self._require_pushable_target(key)
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        await self._driver.write_variable(t.node, t.value)
        return {"key": key, "node": t.node, "written": t.value}

    async def push_targets_confirmed(self, keys: tuple[str, ...] | list[str]) -> dict:
        """块写固定目标点位并回读确认, 供 plc_l2.preload_targets 在 Start 前调用。

        与 point_ref/servo_target 的普通逐点下发分开: 本方法是生产 L2 的前置安全条件,
        必须在同一写锁事务内逐字段回读确认, 任一失败即不触发 L2。
        """
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        fields: dict[str, float] = {}
        written: list[dict] = []
        for key in keys:
            t = self._require_pushable_target(str(key))
            if t.node in fields:
                raise PointsCatalogError(f"preload_targets 含重复 PLC 节点 {t.node}")
            fields[t.node] = t.value
            written.append({"key": t.key, "node": t.node, "written": t.value})
        if not fields:
            return {"written": [], "confirm": {}}
        report = await self._driver.write_block_confirmed(fields)
        return {"written": written, "confirm": report}

    # ------------------------------------------------------------------
    # 组合点位 (一个语义点位聚合多根 flat 目标轴位; 如点样位置 = X起点/X终点/Y高度)
    # ------------------------------------------------------------------

    def _composite_dto(self, c: PlcServoComposite) -> dict:
        return {
            "category": PLC_SERVO_COMPOSITE_CATEGORY,
            "id": c.key,
            "label": c.label,
            "workstation": c.workstation,
            "members": [
                {"key": m.key, "label": m.label, "node": m.node, "actpos": m.actpos,
                 "value": m.value, "limits": {"min": m.min_limit, "max": m.max_limit}}
                for m in c.members
            ],
        }

    def list_plc_servo_composite(self) -> list[dict]:
        return [self._composite_dto(c) for c in self._catalog.composites]

    def _composite_member(self, comp_key: str, member_key: str):
        """定位 (组合点位, 成员); 任一不存在抛 PointsCatalogError。"""
        c = self.composite_entry(comp_key)
        if c is None:
            raise PointsCatalogError(f"未知组合点位: {comp_key}")
        m = next((x for x in c.members if x.key == member_key), None)
        if m is None:
            raise PointsCatalogError(f"组合点位 {comp_key} 无成员: {member_key}")
        return c, m

    async def read_composite_member_actpos(self, comp_key: str, member_key: str) -> float:
        """读组合点位某成员所在轴的实际位置镜像 (*_ActPos flat 节点), 供逐成员 jog 采点微调。"""
        _c, m = self._composite_member(comp_key, member_key)
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        return float(await self._driver.read_variable(m.actpos))

    def set_composite_member_value(self, comp_key: str, member_key: str, value) -> dict:
        """限位校验后把组合点位某成员的 value 持久化回其 plc/<工位>.yaml (PC 侧真值; 保留注释)。

        用 ruamel round-trip 仅改该成员 value, 不动其余结构/注释; 写前过全目录装配校验,
        不通过不落盘; 落盘后 reload()。仅更新存储真值, 不下发到 PLC (下发走 push_composite)。
        """
        _c, m = self._composite_member(comp_key, member_key)
        v = float(value)
        if not m.within_limits(v):
            raise ValueError(f"组合点位 {comp_key}.{member_key} 值 {v} 超出限位 [{m.min_limit}, {m.max_limit}]")

        workstation = self._target_files.get(comp_key)
        if workstation is None:
            raise PointsCatalogError(f"组合点位 {comp_key} 无法定位所在 plc 文件")
        kind = f"{PLC_SUBDIR}/{workstation}.yaml"
        path = self._dir / kind

        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        with path.open("r", encoding="utf-8") as f:
            doc = ryaml.load(f)
        comps = (doc.get("plc_servo_composite") if isinstance(doc, dict) else None) or []
        comp_entry = next((e for e in comps if str(e.get("key")) == comp_key), None)
        if comp_entry is None:
            raise PointsCatalogError(f"{kind} plc_servo_composite 中未找到 {comp_key}")
        member_entry = next((e for e in (comp_entry.get("members") or []) if str(e.get("key")) == member_key), None)
        if member_entry is None:
            raise PointsCatalogError(f"{kind} plc_servo_composite[{comp_key}] 中未找到成员 {member_key}")
        member_entry["value"] = v

        # 写前全量校验 (复用 PyYAML 装配路径), 不通过不落盘
        import io
        buf = io.StringIO()
        ryaml.dump(doc, buf)
        text = buf.getvalue()
        self._assemble_from_disk(override_kind=kind, override_raw=yaml.safe_load(text))
        path.write_text(text, encoding="utf-8")
        self.reload()
        return {"key": comp_key, "member": member_key, "node": m.node, "value": v}

    async def push_composite(self, key: str, member_overrides: dict | None = None) -> dict:
        """把组合点位各成员的生效值 (逐个限位校验后) 按序写入各自 PLC flat 节点 (*_Target)。

        B 方案单写者: 仅 PC 写 *_Target。由消费它的 L2 触发前经 push_point_ref 调用,
        保证各目标都在 Start 之前稳定 (见 PLC 交付文档「写/读时序契约」)。任一成员越限即整体不下发。

        member_overrides (成员 key -> 值): 运行前临时覆盖 (如点样几何逐带覆写), **仅用于本次下发**,
        校验/写入均用生效值; catalog 里的 m.value (示教基准) 纹丝不动 (点表唯一写者仍是
        set_composite_member_value)。未覆盖的成员 → 用 m.value (base-by-read)。未知覆盖键即报错 (防喂错成员)。
        """
        c = self.composite_entry(key)
        if c is None:
            raise PointsCatalogError(f"未知组合点位: {key}")
        overrides = dict(member_overrides or {})
        unknown = set(overrides) - {m.key for m in c.members}
        if unknown:
            raise PointsCatalogError(f"组合点位 {key} 无成员: {sorted(unknown)} (可覆盖: {[m.key for m in c.members]})")
        # 生效值 = 覆盖优先, 否则示教基准; 越限校验与下发都对生效值 (临时覆盖亦受软限位闸把关)
        effective = {m.key: (float(overrides[m.key]) if m.key in overrides else m.value) for m in c.members}
        for m in c.members:
            v = effective[m.key]
            if not m.within_limits(v):
                tag = "覆盖值" if m.key in overrides else "存储值"
                raise ValueError(f"组合点位 {key}.{m.key} {tag} {v} 超出限位 [{m.min_limit}, {m.max_limit}]")
        if self._driver is None:
            raise PointsCatalogError("PLC 驱动未就绪")
        written = []
        for m in c.members:
            v = effective[m.key]
            await self._driver.write_variable(m.node, v)
            written.append({"member": m.key, "node": m.node, "written": v, "overridden": m.key in overrides})
        return {"key": key, "written": written}

    async def push_point_ref(self, key: str, member_overrides: dict | None = None) -> dict:
        """point_ref 引用下发派发: 组合点位走 push_composite (展开各成员, 可带成员覆盖), 普通目标点走 push_target。

        普通目标点无成员, 若误带 member_overrides 即报错 (只有组合点位/点样才有可覆盖的几何成员)。
        """
        if self.composite_entry(key) is not None:
            return await self.push_composite(key, member_overrides=member_overrides)
        if member_overrides:
            raise PointsCatalogError(f"目标点位 {key} 非组合点位, 不支持成员覆盖: {sorted(member_overrides)}")
        return await self.push_target(key)

    # ------------------------------------------------------------------
    # 树 (category -> workstation 分组) 与单点详情
    # ------------------------------------------------------------------

    def _group(self, points: list[dict]) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for p in points:
            ws = p.get("workstation") or _UNGROUPED
            groups.setdefault(ws, []).append(p)
        labels = self._catalog.station_labels
        # 顺序: stations.yaml group_order 声明的流程走向优先; 未列出的 (含 _UNGROUPED) 按 key 字母序沉底
        order = {key: i for i, key in enumerate(self._catalog.station_order)}
        return [
            {"key": ws, "label": labels.get(ws, ws), "points": pts}
            for ws, pts in sorted(groups.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))
        ]

    def tree(self) -> dict:
        # PLC 伺服点位为单一顶层类别: struct 槽位点 (plc_servo, 值在 PLC retain) 与 PC 侧 flat
        # 目标点 (plc_servo_target, 值在 plc/<工位>.yaml) 都是"伺服点位", 持久化机制只是点的行为属性,
        # 不应割成平级分支 → 按 workstation 合并聚合, 每个工位只出现一次。读写仍按各点自身 category 分派。
        return {
            ROBOT_CATEGORY: {"label": "机器人点位", "groups": self._group(self.list_robot())},
            PLC_SERVO_CATEGORY: {
                "label": "PLC 伺服点位",
                "groups": self._group(self.list_plc_servo() + self.list_plc_servo_target()
                                      + self.list_plc_servo_composite()),
            },
        }

    def get(self, category: str, point_id: str) -> dict | None:
        if category == ROBOT_CATEGORY:
            for p in self._registry.points:
                if p.point_id == point_id or p.robot_name == point_id:
                    return self._robot_dto(p)
        elif category == PLC_SERVO_CATEGORY:
            entry = self.servo_entry(point_id)
            if entry is not None:
                return self._servo_dto(entry)
        elif category == PLC_SERVO_TARGET_CATEGORY:
            t = self.target_entry(point_id)
            if t is not None:
                return self._target_dto(t)
        elif category == PLC_SERVO_COMPOSITE_CATEGORY:
            c = self.composite_entry(point_id)
            if c is not None:
                return self._composite_dto(c)
        return None
