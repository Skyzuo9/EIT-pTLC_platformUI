"""动作泵通道构建器
==================
功能:
    把 PLC L2 注射泵动作的"语义参数"(体积/比例/次数/坐标/速度/延时) 映射为 PLC 通道字典
    ({变量名: 值}). 通道字典直接交给 PlcController.execute -> driver.write_many 写入;
    字符串数组 (如 Sampling_clean_instructions) 以 list 形式传入, 由 write_many 整体写.
设计 (单一真源):
    语义参数的声明 (名称/类型/范围/默认/标签) 唯一真源 = 动作 YAML 的 params (registry),
    executor 据此校验并强转后, 把 coerced dict 交给本表的 builder. 本表只持 build,
    不再重复声明参数 (历史 SemanticParam/PumpProfile.params 已删, 见派发单 A3).
    YAML 参数集 == builder 实际消费集 的一致性由 tests/test_pump_contract_offline.py 守护
    (访问追踪 dict: 死参数与缺声明都会被它挡住).
V/M 显式传参 (派发单 A2 + config.pump 持久化):
    各泵动作可选暴露 asp_speed/disp_speed/(spot_disp_speed)/step_delay (DT 指令 V/M);
    缺省 (未在 YAML 传入) 时回退链 = config.pump 持久值 (live-read, bootstrap 注入
    provider) > translator 模块常量 (各站常量: sampling 250/100/1500 · collect
    500/500/1000 · develop 100/100/500)。运行默认的实际真源是 config.pump (app.yaml
    播种初值 = 常量), 常量降级为缺键/读失败兜底; YAML 仅声明"可覆写"而不复制数值默认.
    PumpProfile    - 一个动作的通道构建器 (语义 dict -> 通道 dict)
    PUMP_PROFILES  - 动作名 -> PumpProfile; 不在表中的动作走 registry 已声明参数 (channels=coerced)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from eit_ptlc.tools.pump import collect_translator as ct
from eit_ptlc.tools.pump import develop_translator as dt
from eit_ptlc.tools.pump import sample_translator_v2 as s2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PumpProfile:
    """一个泵动作的通道构建器: 语义 dict -> {PLC变量名: 值} 通道字典.

    字段:
        build: 语义 dict (已由 executor 按 YAML params 校验强转) -> {PLC变量名: 值}
    """
    build: Callable[[dict], dict]


# ----------------------------------------------------------------------
# 持久化泵档 provider (config.pump live-read, spec 2026-07-14-pump-defaults)
# ----------------------------------------------------------------------
# bootstrap 注入 lambda: _parse_pump(cfg_svc.read_section("pump")) —— 返回已清洗的
# {工位: {参数名: int}}。本模块不 import config.loader (清洗职责在闭包里, 保持层间解耦)。
# 未注入 (离线测试/脚本直调) / 读失败 → 回退 translator 常量, 行为与历史完全一致。
_pump_defaults_provider: Callable[[], dict] | None = None


def set_pump_defaults_provider(provider: Callable[[], dict] | None) -> None:
    """注入 config.pump live-read provider (None 撤销, 供测试复位)。"""
    global _pump_defaults_provider
    _pump_defaults_provider = provider


def _config_default(station: str, key: str) -> int | float | None:
    """查 config.pump 持久默认; 未注入/读失败/缺键 → None (调用方回退常量)。

    读失败只 warning 不抛出 —— 泵档缺省绝不能阻断派发。
    值类型由 provider 侧 _parse_pump 已清洗 (速度/延时 int, PUMP_FLOAT_ML_KEYS float),
    本函数原样透传, 调用方按语义自行 cast。
    """
    if _pump_defaults_provider is None:
        return None
    try:
        section = _pump_defaults_provider() or {}
    except Exception as exc:
        log.warning("config.pump 读取失败, 回退 translator 常量: %s", exc)
        return None
    return section.get(station, {}).get(key)


def _speed_kwargs(values: dict, mapping: dict, station: str) -> dict:
    """从语义 dict 抽取已提供的 V/M 覆写 -> translator kwargs.

    mapping: {YAML参数名: translator_kwarg名}; station: 泵工位 (sampling/collect/develop)。
    回退链: values 传值 > config.pump 持久值 (_config_default) > 不传 kwarg
    (由 translator 模块常量兜底)。
    对每个键都经 values.get 访问, 供 test_pump_contract_offline 记账 (声明即须被消费).
    """
    out: dict = {}
    for yaml_name, kw in mapping.items():
        v = values.get(yaml_name)
        if v is None:
            v = _config_default(station, yaml_name)
        if v is not None:
            out[kw] = int(v)
    return out


# 上样三个吸/打动作共用的 V/M 覆写映射 (asp/disp 速度 + 步间延时)
_ASP_DISP_DELAY = {"asp_speed": "asp_speed", "disp_speed": "disp_speed", "step_delay": "step_delay"}


def _ratios_from(values: dict) -> list[float]:
    """从语义 dict 抽取 4 个物理溶剂入口的比例列表 (缺省按 0)."""
    return [float(values.get(f"solvent_ratio_{i}", 0.0)) for i in range(1, 5)]


# ----------------------------------------------------------------------
# 上样点样 (sample_translator_v2)
# ----------------------------------------------------------------------
def _build_sampling_clean(values: dict) -> dict:
    """清洗: 内/外壁清洗指令数组 + 重复次数."""
    return {
        "Sampling_clean_instructions": s2.build_clean_array(
            float(values["wash_volume_ml"]),
            **_speed_kwargs(values, _ASP_DISP_DELAY, "sampling"),
        ),
        "Sampling_clean_count": int(values["cleaning_count"]),
        "Sampling_clean_mode": 0,  # 防陈旧: 与 flush 共用通道, 每次派发显式写 (spec §3.1)
    }


# 轻清洗充液的 V/M 覆写映射 (充液/外壁与点样头两档打速独立)
_FLUSH_SPEED_KWARGS = {
    "asp_speed": "asp_speed",
    "flush_disp_speed": "flush_disp_speed",
    "spot_head_disp_speed": "spot_head_disp_speed",
    "step_delay": "step_delay",
}


def _build_sampling_flush(values: dict) -> dict:
    """轻清洗充液: 复用 clean 通道 (action_code 20), mode=1 + count=1。

    entry1 链式[吸满+充上样流路+冲外壁] / entry2 [冲点样头至A0];
    PLC 在 entry 边界切三通。契约: specs/2026-07-14-sampling-light-flush §3。
    """
    return {
        "Sampling_clean_instructions": s2.build_flush_array(
            float(values["flush_volume_ml"]),
            float(values["outer_wash_volume_ml"]),
            float(values["spot_head_volume_ml"]),
            **_speed_kwargs(values, _FLUSH_SPEED_KWARGS, "sampling"),
        ),
        "Sampling_clean_count": 1,
        "Sampling_clean_mode": 1,
    }


def _build_sampling_prep(values: dict) -> dict:
    """上样准备: 从已清洗输出管路回抽并保留驱动清洗液。"""
    return {
        "Sampling_prep_instructions": s2.build_prep_array(
            float(values["air_buffer_ml"]),
            **_speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling"),
        ),
    }


def _build_sampling_aspirate(values: dict) -> dict:
    """上样吸液: 移孔位前先绝对吸气隔断([2]), 下探后用 P<n> 相对叠加样品([1])。

    孔位 xy 不再走裸索引 (Sampling_X/Y_coordinate 已被 PLC A50 弃用): 由执行器据
    (plate_spec, plate_no, well) 取标定经仿射算出, 触发前写 Sampling_4X/3Y_Target
    (见 executor.PLATE_WELL_PARAMS 孔位寻址块); 本 builder 只翻译注射泵指令。

    air_gap_ml 未传时 [2] 为空串, PLC 跳过吸气段 (兼容先调 sampling.prep 的旧编排)。
    """
    air_gap = values.get("air_gap_ml")
    return {
        "Sampling_sample_instructions": s2.build_sample_array(
            float(values["sample_volume_ml"]),
            float(air_gap) if air_gap is not None else None,
            **_speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling"),
        ),
    }


def _build_sampling_rinse_mix(values: dict) -> dict:
    """点样后回原孔：回打余量、加润洗液、抬针吸气隔断并循环吹打，终态 A{gap}。"""
    mix_count = int(values["mix_count"])
    if not 1 <= mix_count <= 20:
        raise ValueError(f"吹打次数必须在 [1, 20] 范围内，收到 {mix_count}")
    air_gap = values.get("air_gap_ml")
    return {
        "Sampling_rinse_mix_instructions": s2.build_rinse_mix_array(
            float(values["rinse_volume_ml"]),
            float(values["mix_volume_ml"]),
            float(air_gap) if air_gap is not None else s2.DEFAULT_RINSE_AIR_GAP_ML,
            **_speed_kwargs(values, _ASP_DISP_DELAY, "sampling"),
        ),
        "Sampling_rinse_mix_count": mix_count,
    }


def _build_sampling_spot(values: dict) -> dict:
    """点样: 抽取驱动空气 + 打气点样(含回抽释压)指令数组.

    点样打液速度 spot_disp_speed (DT V) 回退链: 传值 > config.pump >
    DEFAULT_DISPENSE_DISP_SPEED (=50, 精度优先), 而非 translator 的 0->跟随 disp_speed。
    """
    spot = values.get("spot_disp_speed")
    if spot is None:
        spot = _config_default("sampling", "spot_disp_speed")
    kwargs = _speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling")
    kwargs["dispense_disp_speed"] = int(spot) if spot is not None else s2.DEFAULT_DISPENSE_DISP_SPEED
    return {
        "Sampling_dispense_instructions": s2.build_dispense_array(
            float(values["sample_volume_ml"]), **kwargs,
        ),
    }


def _build_sampling_spot_band_layer(values: dict) -> dict:
    """单条带点样+连续吹干: 生成泵供液指令与轴/吹扫参数。

    PLC 侧负责强同步: 先发有限 A{N}R, 6X 一程到位后在同一泵总线占位内
    发 T 停泵并以 ? 查询真活塞位；有效位置仍大于 N 才释放总线进入吹干，
    继续下一程，直到位置回到 N(+5 步容差)，再移动到清洗位关气。
    N = spot_end_position_ml (死体积补偿, 缺省 0 = 旧行为)。
    """
    spot = values.get("spot_disp_speed")
    if spot is None:
        spot = _config_default("sampling", "spot_disp_speed")
    delay = values.get("step_delay")
    if delay is None:
        delay = _config_default("sampling", "step_delay")
    end_raw = values.get("spot_end_position_ml")
    if end_raw is None:
        end_raw = _config_default("sampling", "spot_end_position_ml")
    end_ml = float(end_raw) if end_raw is not None else 0.0
    return {
        "Sampling_band_run_instruction": s2.build_spot_band_run_cmd(
            disp_speed=int(spot) if spot is not None else s2.DEFAULT_DISPENSE_DISP_SPEED,
            step_delay=int(delay) if delay is not None else s2.STEP_DELAY,
            end_position_ml=end_ml,
        ),
        "Sampling_band_end_position": s2.spot_band_end_steps(end_ml),
        "Sampling_band_spot_speed": float(values["spot_speed_mm_s"]),
        "Sampling_band_dry_speed": float(values["dry_speed_mm_s"]),
        "Sampling_band_dry_cycles": int(values["dry_cycles"]),
    }


# ----------------------------------------------------------------------
# 收集 (collect_translator)
# ----------------------------------------------------------------------
def _build_collect_collect(values: dict) -> dict:
    """收集加液: 单溶剂吸打复合指令 + 重复打液次数."""
    return {
        "collect_forward_instructions": ct.translate_collect_cmd(
            float(values["solvent_volume_ml"]),
            **_speed_kwargs(values, _ASP_DISP_DELAY, "collect"),
        ),
        "collect_count": int(values["liquid_repeat_count"]),
    }


# ----------------------------------------------------------------------
# 展缸 (develop_translator); rinse 与 fill 复用同一组配比语义, 写入不同子集
# ----------------------------------------------------------------------
def _build_develop_rinse(values: dict, *, rinse_mode: str) -> dict:
    """润洗注液/清洗管路: 目标缸 + (动作固定)模式 + 转发指令 + 次数.

    模式由动作类型固定 (clean_line=line, rinse_fill=cylinder), 不再交互选择,
    避免现场误选 cylinder 清洗管路 / line 润洗缸.
    """
    translated = dt.translate_develop_params(
        ratios=_ratios_from(values),
        total_volume_ml=float(values["solvent_volume_ml"]),
        rinse_mode=rinse_mode,
        target_tank=int(values["target_tank"]),
        rinse_repeat_count=int(values.get("rinse_repeat_count", 1)),
        **_speed_kwargs(values, _ASP_DISP_DELAY, "develop"),
    )
    # 润洗动作只消费缸号/模式/转发指令/润洗次数
    return {
        key: translated[key]
        for key in (
            "Expand_Target_Tank",
            "Expand_Mode_Flag",
            "Expand_forward_instructions",
            "Expand_rinse_count",
        )
    }


def _build_develop_fill(values: dict) -> dict:
    """上液: 目标缸 + 转发指令 + 上液次数."""
    translated = dt.translate_develop_params(
        ratios=_ratios_from(values),
        total_volume_ml=float(values["solvent_volume_ml"]),
        target_tank=int(values["target_tank"]),
        up_liquid_repeat_count=int(values.get("up_liquid_repeat_count", 1)),
        **_speed_kwargs(values, _ASP_DISP_DELAY, "develop"),
    )
    # 上液动作只消费缸号/转发指令/上液次数
    return {
        key: translated[key]
        for key in (
            "Expand_Target_Tank",
            "Expand_forward_instructions",
            "Expand_up_liquid_count",
        )
    }


# ----------------------------------------------------------------------
# 动作名 -> 通道构建器 (不在表中的动作走 registry 已声明参数, channels=coerced)
# ----------------------------------------------------------------------
PUMP_PROFILES: dict[str, PumpProfile] = {
    "sampling.clean": PumpProfile(_build_sampling_clean),
    "sampling.flush": PumpProfile(_build_sampling_flush),
    "sampling.prep": PumpProfile(_build_sampling_prep),
    "sampling.aspirate": PumpProfile(_build_sampling_aspirate),
    "sampling.rinse_mix": PumpProfile(_build_sampling_rinse_mix),
    "sampling.spot": PumpProfile(_build_sampling_spot),
    "sampling.spot_band_layer": PumpProfile(_build_sampling_spot_band_layer),
    "collect.collect": PumpProfile(_build_collect_collect),
    "develop.clean_line": PumpProfile(lambda v: _build_develop_rinse(v, rinse_mode="line")),
    "develop.rinse_fill": PumpProfile(lambda v: _build_develop_rinse(v, rinse_mode="cylinder")),
    "develop.fill": PumpProfile(_build_develop_fill),
}


# ----------------------------------------------------------------------
# 泵档默认 (V/M) 的 UI 提示 (派发单 A2 显示侧)
# ----------------------------------------------------------------------
# 常量兜底层: 数字只引用 translator 常量 (s2/ct/dt), 不重新键入 -> 与执行兜底同源。
# pump_default_hint 先查 config.pump (live-read, 与执行回退链同一 _config_default),
# 缺键才落本表 —— UI 占位与实际执行值恒同源, 用户改 config 即时跟随。
_PUMP_CONSTANT_HINTS: dict[str, dict[str, int | float]] = {
    "sampling": {"asp_speed": s2.ASP_SPEED, "disp_speed": s2.DISP_SPEED,
                 "spot_disp_speed": s2.DEFAULT_DISPENSE_DISP_SPEED, "step_delay": s2.STEP_DELAY,
                 "flush_disp_speed": s2.FLUSH_DISP_SPEED,
                 "spot_head_disp_speed": s2.FLUSH_SPOT_HEAD_DISP_SPEED,
                 "spot_end_position_ml": 0.0},  # 死体积补偿终点 (mL); 常量兜底=0=打到底
    "collect":  {"asp_speed": ct.ASP_SPEED, "disp_speed": ct.DISP_SPEED, "step_delay": ct.STEP_DELAY},
    "develop":  {"asp_speed": dt.ASP_SPEED, "disp_speed": dt.DISP_SPEED, "step_delay": dt.STEP_DELAY},
}


def pump_default_hint(station: str, param_name: str) -> int | float | None:
    """返回某工位某泵参数"未覆写时实际执行值" (无则 None).

    功能:
        供 UI 占位展示; 与执行回退链同源 —— 先查 config.pump 持久值 (_config_default),
        缺键回退 translator 常量兜底表。非泵参数 / 非泵工位返回 None。
    参数:
        station: 动作工位名 (sampling/collect/develop)
        param_name: 参数名 (asp_speed/disp_speed/spot_disp_speed/step_delay/...)
    返回:
        int 泵档默认值, 无对应项返回 None
    """
    hints = _PUMP_CONSTANT_HINTS.get(station, {})
    if param_name not in hints:
        return None   # 非泵参数/工位: 不查 config, 保持 None 语义
    cfg = _config_default(station, param_name)
    return cfg if cfg is not None else hints[param_name]
