"""API 数据传输对象 (pydantic)
=============================
功能:
    动作目录 / 动作结果 / 运行请求的 HTTP 序列化模型, 以及与 action 层 dataclass 的转换.
    (流程编排已由 VM 脚本承接, 见 api/vm_dto.py; 旧扁平 operation DTO 已退役.)
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from eit_ptlc.action.models import ActionResult
from eit_ptlc.action.registry import ActionDef
from eit_ptlc.controller.plc_controller import STATION_PREFIX
from eit_ptlc.tools.pump.profiles import pump_default_hint
from eit_ptlc.value_domain import enum_payload


# 引用机器人点位的参数名 (UI 据此渲染"跳转到点位管理页"链接)
POINT_PARAM_NAMES = {"point_id_or_robot_name", "point_id"}


class ActionParamDTO(BaseModel):
    name: str
    type: str
    required: bool
    default: Any = None
    label: str
    options: list = []          # 有限取值域 [{value, label}]; 空=自由输入
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    is_point: bool = False  # True = 该参数引用点位, UI 渲染跳转链接
    # 只读: 无 YAML default 的泵速度/延时参数, 其"未覆写时实际执行值"(泵档常量), 仅供 UI 占位展示.
    # 与校验用的 default (仍为 None/权威) 区分; 数字源自 translator 常量 (单一真源, 见 profiles).
    default_hint: Optional[float] = None
    # 数值参数"显示缩放"皮肤 (仅前端渲染: 显示值 = 值 × scale, 单位 unit, 步进取 scale; 存/发/校验仍是原值)
    scale: Optional[float] = None
    unit: str = ""


class ActionDefDTO(BaseModel):
    name: str
    kind: str
    label: str
    desc: str = ""                # 动作详细说明 (YAML desc 唯一真源; UI 右栏展示/编辑)
    hint: str = ""                # 操作员向一句话短说明 (三维常用操作区; 空=沿用 desc 平铺)
    method: str = ""
    station: str = ""
    action_code: int = 0
    preload_targets: list = []     # plc_l2 Start 前固定下发并回读确认的目标点位 key
    group: str = ""               # 所属设备文件夹 (UI 按目录分组用)
    modes: list = []
    retryable: bool = False
    plc_link: str = ""            # 自动生成: 该动作如何与 PLC 关联 (由 kind/station/action_code 推导)
    params: list[ActionParamDTO] = []


class ActionDescriptionUpdate(BaseModel):
    """动作详细说明的定点更新请求。"""
    desc: str


class ActionLabelUpdate(BaseModel):
    """动作显示名的定点更新请求。"""
    label: str


class RunRequest(BaseModel):
    params: dict = {}
    mode: Optional[str] = None
    # Optional external idempotency key.  It becomes request_id so a facade
    # can reconcile an action outcome without inventing a second identity.
    command_id: Optional[str] = None


class ActionResultDTO(BaseModel):
    action: str
    request_id: str
    status: str
    accepted: bool
    reject_code: Optional[str] = None
    error_code: int = 0
    message: str = ""
    step: int = 0
    progress: float = 0.0
    retryable: bool = False
    safe_state: str = ""
    result: dict = {}
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


def _plc_link(adef: ActionDef) -> str:
    """自动生成动作与 PLC 的关联说明 (供 UI「动作详情」展示).

    功能:
        按动作类别 (kind) 推导该动作如何作用到 PLC: plc_l2 经 {prefix}_L2_* 通道下发到工位
        状态机; servo_target/plc_write 写 PLC flat 节点; 其余类别 (robot/camera/vision/
        water_level) 标注不经 PLC. 文案全部从动作元数据推导, 不手写, 始终与动作定义同步.
    参数:
        adef: 动作定义 (含 kind/station/action_code/method)
    返回:
        str, 中文关联说明; 无可述关联时返回空串
    """
    kind = adef.kind
    if kind == "plc_l2":
        # 工位名 -> L2 变量前缀 (与 PlcController._prefix 同源, 未命中按精确前缀)
        prefix = STATION_PREFIX.get(adef.station.strip().lower(), adef.station.strip())
        return (
            f"下发动作码 {adef.action_code} (工位 {prefix}) -> 写 {prefix}_L2_ActionCode={adef.action_code} "
            f"与 {prefix}_L2_RequestSeq, 置 {prefix}_L2_Start 上升沿; 由 PLC 程序 50_action/{prefix}_L2 "
            f"执行, 上位机轮询 {prefix}_L2_State 至 DONE(20)."
        )
    if kind == "servo_target":
        return "下发伺服目标点位到 PLC *_Target flat 节点 (单写者, 不经 L2 状态机)."
    if kind == "plc_write":
        return "块写参数到 PLC flat 节点并逐字段回读确认 (单写者; 如 CNC 路径下发)."
    if kind == "robot":
        return f"调用机器人控制器方法 {adef.method}(); 不经 PLC L2 通道."
    if kind == "camera":
        return "相机拍照; 不经 PLC."
    if kind == "vision":
        return "视觉/条带检测; 不经 PLC."
    return ""


def action_def_to_dto(adef: ActionDef, target_keys: Optional[list] = None) -> ActionDefDTO:
    """ActionDef -> ActionDefDTO.

    参数:
        adef: 动作定义
        target_keys: 可下发的 plc_servo_target 点位 key 列表; 用于把 point_ref 参数的 options 填成
            点位下拉 (供前端"选用哪个点位")。None = 不填 (前端回退为文本输入)。
    """
    def _options(p) -> list:
        # 统一下发 [{value, label}] —— 与脚本变量 enum 的下发形状一致, 前端一个 enumOf 通吃。
        # value 保留 YAML 原类型 (不字符串化): 动作参数面板写的是表达式字面量 {lit: …},
        # int 参数必须拿回 int (与运行前设置面板的 draft 全字符串刻意不同)。
        # point_ref 参数: 选项 = 可下发点位 key (动态注入的取值域范式)。
        if p.type == "point_ref" and target_keys is not None:
            return [{"value": k, "label": k} for k in target_keys]
        return enum_payload(p.options)
    return ActionDefDTO(
        name=adef.name, kind=adef.kind, label=adef.label, desc=adef.desc, hint=adef.hint,
        method=adef.method,
        station=adef.station, action_code=adef.action_code, group=adef.group, modes=list(adef.modes),
        preload_targets=list(adef.preload_targets),
        retryable=adef.retryable, plc_link=_plc_link(adef),
        params=[
            ActionParamDTO(name=p.name, type=p.type, required=p.required, default=p.default,
                           label=p.label, options=_options(p), minimum=p.minimum, maximum=p.maximum,
                           is_point=p.name in POINT_PARAM_NAMES,
                           scale=p.scale, unit=p.unit,
                           # 仅"无默认"参数透出泵档提示 (非泵参数 pump_default_hint 自然返回 None)
                           default_hint=(pump_default_hint(adef.station, p.name)
                                         if p.default is None else None))
            for p in adef.params
        ],
    )


def action_result_to_dto(r: ActionResult) -> ActionResultDTO:
    """ActionResult -> ActionResultDTO."""
    return ActionResultDTO(
        action=r.action, request_id=r.request_id, status=r.status.value, accepted=r.accepted,
        reject_code=r.reject_code, error_code=r.error_code, message=r.message, step=r.step,
        progress=r.progress, retryable=r.retryable, safe_state=r.safe_state, result=r.result,
        started_at=r.started_at, finished_at=r.finished_at,
    )
