"""录制通道的精度策略。

每个通道声明**物理量化步长**与**死区**, 这既是压缩率的来源, 也是回放精度的契约:

    |解码值 - 原始值| <= (deadband + 0.5) * quantum

量化步长按物理意义定而不按数值范围定 —— 轴位置定 0.01 mm 不是因为 int32 装得下,
而是因为 0.01 mm 已远细于本机任何有意义的公差 (整机上真正咬人的偏差是 7 mm 量级的
抓取基准差、4–21 mm 量级的板面内残差)。

死区的作用不止省空间: 编码器噪声 (实测 ±0.004 mm) 会让静止的轴在量化边界上反复翻
两个相邻整数, 不做死区的话回放里一根停着的轴会不停抖 —— 死区是**保真**手段, 不是
有损妥协。

本模块只管精度策略, 不做通道白名单: 编解码器对未知通道一律按默认策略照录, 绝不丢
弃。原因是机构目录会随工程演进 (今天 55 个, 明天可能 57 个), 白名单式设计会让新增
通道静默消失, 而录像里"少了一路"事后无法补救。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelSpec:
    """单个通道的编码策略。

    quantum:  物理量化步长 (该通道的单位)
    deadband: 死区, 单位是"量化步"; 变化小于该步数则保持上一个值。0 = 不做死区
    kind:     num=连续量 | bool=布尔 | tri=三态(True/False/None) | enum=离散取值
    unit:     物理单位, 仅用于人读与前端标注
    """

    quantum: float
    deadband: int
    kind: str
    unit: str = ""


# 连续量默认策略: 未知数值通道按 0.001 精度录, 宁可多存也不要事后发现精度不够。
_DEFAULT_NUM = ChannelSpec(quantum=0.001, deadband=0, kind="num")
_BOOL = ChannelSpec(quantum=1.0, deadband=0, kind="bool")
_TRI = ChannelSpec(quantum=1.0, deadband=0, kind="tri")
_ENUM = ChannelSpec(quantum=1.0, deadband=0, kind="enum")

# 轴位置: 0.01 mm 量化 + 2 步死区 -> 最差 0.025 mm 误差
_AXIS_POS = ChannelSpec(quantum=0.01, deadband=2, kind="num", unit="mm")
# 轴速度: 精度要求远低于位置, 且噪声更大, 死区放宽
_AXIS_VEL = ChannelSpec(quantum=0.1, deadband=3, kind="num", unit="mm/s")
# 关节角: 0.001° 在 CR5 臂展上约合 0.01 mm 末端位移, 与位置精度同量级
_JOINT = ChannelSpec(quantum=0.001, deadband=5, kind="num", unit="deg")
_POSE_XYZ = ChannelSpec(quantum=0.01, deadband=2, kind="num", unit="mm")
_POSE_RPY = ChannelSpec(quantum=0.001, deadband=5, kind="num", unit="deg")
# 机构预期时长: 0.01 s 足够, 且它是刻意粘滞量, 不该被死区改写
_EXPECTED_S = ChannelSpec(quantum=0.01, deadband=0, kind="num", unit="s")

# (stream, field) -> spec。field 是流内的字段名, 不含机构/轴 id。
_RULES: dict[tuple[str, str], ChannelSpec] = {
    ("axis_pose", "position"): _AXIS_POS,
    ("axis_pose", "velocity"): _AXIS_VEL,
    ("robot_pose", "joint"): _JOINT,
    ("robot_pose", "pose_xyz"): _POSE_XYZ,
    ("robot_pose", "pose_rpy"): _POSE_RPY,
    ("robot_pose", "tool"): _ENUM,
    ("robot_pose", "mode"): _ENUM,
    # 机构: commanded/available/moving 是布尔; confirmed 是**三态** ——
    # None 表示"两个到位信号都不成立", 前端据此回退 commanded+estimated。
    # 把 None 压成 False 会让回放把"运动途中"错画成"已到位"。
    ("mechanism_state", "commanded"): _BOOL,
    ("mechanism_state", "confirmed"): _TRI,
    ("mechanism_state", "available"): _BOOL,
    ("mechanism_state", "moving"): _BOOL,
    ("mechanism_state", "source"): _ENUM,
    ("mechanism_state", "expectedS"): _EXPECTED_S,
    ("signal_light", "red"): _BOOL,
    ("signal_light", "yellow"): _BOOL,
    ("signal_light", "green"): _BOOL,
    ("signal_light", "buzzer"): _BOOL,
    ("signal_light", "flash"): _BOOL,
    ("signal_light", "mode"): _ENUM,
}


def spec_for(stream: str, field: str) -> ChannelSpec:
    """取 (流, 字段) 的编码策略; 未声明的通道回落到按值类型推断的默认策略。

    未知通道**照录不误**, 只是精度用默认值 —— 见模块 docstring 说明为何不做白名单。
    """
    spec = _RULES.get((stream, field))
    if spec is not None:
        return spec
    return _DEFAULT_NUM


def spec_for_value(stream: str, field: str, sample) -> ChannelSpec:
    """带样值的策略选取: 未声明通道按样值类型挑 bool/enum/num, 比纯按名字更准。"""
    spec = _RULES.get((stream, field))
    if spec is not None:
        return spec
    if isinstance(sample, bool):
        return _BOOL
    if isinstance(sample, str):
        return _ENUM
    if sample is None:
        return _TRI
    return _DEFAULT_NUM


def tolerance(spec: ChannelSpec) -> float:
    """该通道的往返误差上界, 即回放精度契约。单测直接断言这个值。"""
    return (spec.deadband + 0.5) * spec.quantum
