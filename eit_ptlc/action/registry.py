"""动作注册表
============
功能:
    从 config/actions/<设备>/*.yaml (按设备分子目录) 递归构建声明式动作目录,
    供 UI 左栏列表 / 右栏参数 / executor 调度.
    每个动作声明: 名称 / 类别 / 控制器绑定 / 参数 schema / 模式门控 / 可重试默认.

动作类别 (kind):
    robot        - 机器人原子动作 (调用 RobotController 方法)
    plc_l2       - PLC L2 工位动作 (调用 PlcController.execute, 需 station + action_code)
    servo_target - PC 侧 flat 目标点位下发 (B方案单写者: 写 points.yaml plc_servo_target 的
                   value 到 PLC *_Target flat 节点; 不进 L2 FSM; 需 targets[] 引用点位 key)
    plc_l2       - 可声明 preload_targets[]: 在 Start 前把固定 plc_servo_target 点位块写并回读确认
    plc_write    - PC 侧 flat 节点块写 + 回读确认 (单写者: 把动作 args 按 fields[].key 映射到
                   fields[].node 写入 PLC, 写后逐字段回读比对; 数组/标量混合; 用于 CNC 路径下发)
    device       - PLC 设备原子 (伺服/气缸, 后续 P2d/P4)
    camera       - 相机拍照; vision - 视觉/条带检测
    water_level  - 液位检测外设 (香橙派) MQTT 命令下发 (method=命令名, params→payload)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from eit_ptlc.value_domain import normalize_enum

log = logging.getLogger(__name__)

VALID_KINDS = {"robot", "plc_l2", "servo_target", "plc_write", "device", "camera", "vision", "host",
               "rail_ensure"}
# rail_ensure - 地轨按槽确认/补移协调动作 (executor._exec_rail_ensure): 幂等, 复用 rail.move 的 P1
#               硬门 + L2 管线; 供原子 enter 处 (臂在 P1) 按点 rail 自动移轨 (Win B)。
# point_ref: 值为一个 plc_servo_target 点位 key; plc_l2 动作用它声明"用哪个点位", executor 在触发前
#            据此取点表值写入 PLC *_Target flat 节点 (不作为 PLC 通道下发, 见 executor._exec_plc_l2)。
VALID_PARAM_TYPES = {"int", "float", "bool", "string", "enum", "point_ref"}


@dataclass(frozen=True)
class ActionParam:
    """动作参数声明 (供右栏渲染与校验)."""
    name: str
    type: str = "string"
    required: bool = False
    default: object = None
    label: str = ""
    options: tuple = ()          # 有限取值域 (EnumOption 元组; YAML 键 enum, 别名 options)
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    # 声明式 channel 别名 (A4): 用户面语义参数名 name -> PLC 通道键 channel。
    # 仅 kind=plc_l2 无 profile 的动作生效 (executor 下发前把 coerced[name] 重映射为 channel);
    # 空=参数名即通道名 (原行为)。让不同工位"目标缸号"等概念用统一语义名而非裸 PLC 节点名。
    channel: str = ""
    # 数值参数可选"显示缩放"元数据 (仅 UI 皮肤, 不改存储/校验/下发单位):
    # 显示值 = 存储值 × scale, 单位标 unit, 步进取 scale。存的/发的/校验的仍是底层原值 (min/max 同域)。
    scale: Optional[float] = None
    unit: str = ""


@dataclass(frozen=True)
class PlcWriteField:
    """kind=plc_write 的单字段映射: 动作 args[key] → PLC 变量 node.

    类型/数组维度由 PLC 节点表决定 (driver.variant_of / _array_len), 此处不重复声明,
    仅做 args↔node 的命名绑定与 UI 标签。
    """
    key: str                     # 动作 args 里的键
    node: str                    # PLC 变量名
    label: str = ""


@dataclass(frozen=True)
class ActionDef:
    """单个动作定义."""
    name: str
    kind: str
    label: str = ""
    desc: str = ""               # 动作详细说明 (UI 右栏可定点编辑, YAML desc 为唯一真源)
    hint: str = ""               # 操作员向一句话短说明 (常用操作区展示; 空=沿用 desc 平铺)
    method: str = ""             # kind=robot: RobotController 方法名
    station: str = ""            # kind=plc_l2: 工位名
    action_code: int = 0         # kind=plc_l2: 动作码
    # kind=plc_l2: per-action 看门狗覆盖 (None=回退全局 plc.action_stall_timeout/action_timeout)。
    # 静默窗口长的动作 (如 CNC 单 pass 刮取: PLC 内部 SoftMotion 全程无 L2 字段推进) 在自己的
    # 动作 YAML 里声明 stall_timeout, 单独放大停滞预算, 不牵动全局阈值 (免其它动作看门狗变迟钝)。
    stall_timeout: Optional[float] = None
    action_timeout: Optional[float] = None
    preload_targets: tuple = ()  # kind=plc_l2: L2 Start 前固定下发并回读确认的 plc_servo_target key
    # kind=plc_l2: 该动作 L2 Start 前机械臂必须在此锚点, 否则拒发 (UNSAFE)。用于移轨类动作 ——
    # 地轨带着整臂平移, 臂不在安全位(伸展姿态)随之平移有碰撞风险。断言式硬门, 任何调用方不可绕过。
    safety_anchor: Optional[str] = None
    targets: tuple = ()          # kind=servo_target: 要下发的 plc_servo_target 点位 key 序列
    fields: tuple = ()           # kind=plc_write: tuple[PlcWriteField] (args.key → PLC node)
    atol: Optional[float] = None  # kind=plc_write: 浮点回读容差 (None=用 driver 默认)
    group: str = ""              # 所属设备文件夹 (config/actions/<NN_设备>/), 供 UI 按目录分组
    params: tuple = ()           # tuple[ActionParam]
    modes: tuple = ()            # 允许的控制模式 (空=不限)
    retryable: bool = False

    def param(self, name: str) -> Optional[ActionParam]:
        for p in self.params:
            if p.name == name:
                return p
        return None


class ActionRegistry:
    """动作目录 (不可变)."""

    def __init__(self, actions: dict[str, ActionDef]) -> None:
        self._actions = dict(actions)

    @classmethod
    def load(cls, actions_dir: str | Path) -> "ActionRegistry":
        """从目录加载全部 *.yaml 动作声明.

        参数:
            actions_dir: config/actions 目录 (递归遍历其下 <设备>/ 子目录)
        返回:
            ActionRegistry
        """
        actions_dir = Path(actions_dir)
        if not actions_dir.is_dir():
            raise FileNotFoundError(f"动作目录不存在: {actions_dir}")
        actions: dict[str, ActionDef] = {}
        # 递归遍历: 动作按设备分子目录存放 (config/actions/<NN_device>/*.yaml)
        for path in sorted(actions_dir.glob("**/*.yaml")):
            # 组 = actions_dir 下的顶层子目录名 (直接位于根则空)
            rel_parts = path.relative_to(actions_dir).parts
            group = rel_parts[0] if len(rel_parts) > 1 else ""
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path} 根节点必须是 mapping")
            for name, spec in raw.items():
                if name in actions:
                    raise ValueError(f"重复动作名: {name} (见 {path})")
                actions[name] = cls._parse_action(str(name), spec, path, group)
        log.info("[Action] 加载 %d 个动作 (来自 %d 个文件)", len(actions), len(list(actions_dir.glob('**/*.yaml'))))
        return cls(actions)

    @staticmethod
    def _parse_action(name: str, spec: dict, path: Path, group: str = "") -> ActionDef:
        if not isinstance(spec, dict):
            raise ValueError(f"动作 {name} 定义必须是 mapping ({path})")
        kind = str(spec.get("kind", ""))
        if kind not in VALID_KINDS:
            raise ValueError(f"动作 {name} kind 非法: {kind!r} (合法 {sorted(VALID_KINDS)})")
        desc_raw = spec.get("desc")
        if not isinstance(desc_raw, str) or not desc_raw.strip():
            raise ValueError(f"动作 {name} 必须声明非空 desc ({path})")
        params = tuple(ActionRegistry._parse_param(name, p) for p in (spec.get("params") or []))
        fields = tuple(ActionRegistry._parse_field(name, f) for f in (spec.get("fields") or []))
        atol_raw = spec.get("atol")
        stall_raw = spec.get("stall_timeout")
        act_to_raw = spec.get("action_timeout")
        sa_raw = spec.get("safety_anchor")
        action = ActionDef(
            name=name,
            kind=kind,
            label=str(spec.get("label", name)),
            desc=desc_raw.strip(),
            hint=str(spec.get("hint", "")).strip(),
            method=str(spec.get("method", "")),
            station=str(spec.get("station", "")),
            action_code=int(spec.get("action_code", 0)),
            stall_timeout=float(stall_raw) if stall_raw is not None else None,
            action_timeout=float(act_to_raw) if act_to_raw is not None else None,
            preload_targets=tuple(str(t) for t in (spec.get("preload_targets") or [])),
            safety_anchor=str(sa_raw).strip() if sa_raw else None,
            targets=tuple(str(t) for t in (spec.get("targets") or [])),
            fields=fields,
            atol=float(atol_raw) if atol_raw is not None else None,
            group=group,
            params=params,
            modes=tuple(str(m) for m in (spec.get("modes") or [])),
            retryable=bool(spec.get("retryable", False)),
        )
        # 类别一致性校验
        if kind == "robot" and not action.method:
            raise ValueError(f"robot 动作 {name} 必须声明 method")
        if kind == "plc_l2" and (not action.station or not action.action_code):
            raise ValueError(f"plc_l2 动作 {name} 必须声明 station 与 action_code")
        if action.preload_targets and kind != "plc_l2":
            raise ValueError(f"动作 {name} 只有 plc_l2 可声明 preload_targets")
        if action.safety_anchor and kind != "plc_l2":
            raise ValueError(f"动作 {name} 只有 plc_l2 可声明 safety_anchor")
        if kind == "servo_target" and not action.targets:
            raise ValueError(f"servo_target 动作 {name} 必须声明非空 targets (plc_servo_target 点位 key)")
        if kind == "plc_write" and not action.fields:
            raise ValueError(f"plc_write 动作 {name} 必须声明非空 fields (args.key → PLC node)")
        return action

    @staticmethod
    def _parse_field(action_name: str, f: dict) -> PlcWriteField:
        if not isinstance(f, dict) or "key" not in f or "node" not in f:
            raise ValueError(f"plc_write 动作 {action_name} 的 fields 项必须含 key 与 node")
        return PlcWriteField(
            key=str(f["key"]),
            node=str(f["node"]),
            label=str(f.get("label", f["key"])),
        )

    @staticmethod
    def _parse_param(action_name: str, p: dict) -> ActionParam:
        if not isinstance(p, dict) or "name" not in p:
            raise ValueError(f"动作 {action_name} 参数项必须含 name")
        ptype = str(p.get("type", "string"))
        if ptype not in VALID_PARAM_TYPES:
            raise ValueError(f"动作 {action_name} 参数 {p['name']} 类型非法: {ptype}")
        return ActionParam(
            name=str(p["name"]),
            type=ptype,
            required=bool(p.get("required", False)),
            default=p.get("default"),
            label=str(p.get("label", p["name"])),
            # 取值域: 正名是 enum (与脚本变量同一个词、同一套规范化), options 保留为别名 —— 既有
            # 23 处动作 YAML 写的都是 options, 不必为改词动它们。
            options=normalize_enum(p.get("enum") if p.get("enum") is not None else p.get("options"),
                                   where=f"动作 {action_name} 参数 {p['name']}"),
            minimum=p.get("min"),
            maximum=p.get("max"),
            channel=str(p.get("channel", "")),
            scale=p.get("scale"),
            unit=str(p.get("unit", "")),
        )

    def get(self, name: str) -> ActionDef:
        try:
            return self._actions[name]
        except KeyError as exc:
            raise KeyError(f"未知动作: {name}") from exc

    def list(self) -> list[ActionDef]:
        return list(self._actions.values())

    def by_kind(self, kind: str) -> list[ActionDef]:
        return [a for a in self._actions.values() if a.kind == kind]

    def __len__(self) -> int:
        return len(self._actions)
