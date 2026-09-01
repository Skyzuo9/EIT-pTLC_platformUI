"""PLC 编排说明书加载器
======================
功能:
    加载 mock/behavior/specs/*.yaml —— 从 CODESYS 现役工程逐字提取的 PLC 内部工序记录
    (段号表 / 互锁门 / 错误码 / 时序常量 + POU 锚点与 ST 哈希)。虚拟 PLC 的行为层从
    这里取数, **不在 Python 里复抄任何数字**: 两份真源必然漂移。

    spec 同时是漂移看门狗的比对基准:
      离线层 (tests/test_plc_spec_offline.py): spec ↔ config/actions/**/plc_*.yaml ↔
        行为模块码表 三方一致性, 不碰 CODESYS;
      在线层 (tools/plc_spec_drift.py): 经文件 IPC 拉现役 ST 重算哈希与 spec 比对。

主要接口:
    load_station_spec(station) -> StationSpec
    load_all_specs() -> dict[str, StationSpec]
    normalize_st(text) -> str        # 与提取侧同一规范化口径 (哈希可复现的前提)
    st_sha256(decl, impl) -> str
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

log = logging.getLogger(__name__)

_SPEC_DIR = Path(__file__).resolve().parent / "specs"
_SCHEMA_KEY = "ptlc.plc_choreography/v1"

# 动作性质闭集 (行为层按此选实现策略; 未知值加载即失败, 防拼写漂移)
KINDS = (
    "instant",        # 写输出即同扫描 DONE, 不等反馈
    "cylinder",       # 写气缸自动位 + 等到位反馈
    "axis_seq",       # 有序轴移动 (目标来自 flat 通道或 ST 常量)
    "jog_search",     # JOG 搜索传感器边沿 + 稳定确认 + 抖动重捕获
    "pump_seq",       # 下发泵指令串 + 轮询泵空闲
    "valve_seq",      # 阀位切换 + 计时相位
    "cnc_blackbox",   # CNC 插补 (不复刻 SoftMotion, 按行程估时)
    "composite",      # 以上多者组合
)


@dataclass(frozen=True)
class ActionSpec:
    """单个 L2 动作的编排记录."""
    code: int
    name: str
    pou: str
    sha256: str
    kind: str
    summary: str
    steps: tuple = ()             # ({step: int, phase: str}, ...) 按 ST 出现顺序
    gate: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)   # {错误码: 含义}
    notes: str = ""

    @property
    def step_values(self) -> tuple:
        """该动作会写进 <Station>_L2_Step 的全部值 (去重保序)."""
        seen = []
        for item in self.steps:
            value = int(item["step"])
            if value not in seen:
                seen.append(value)
        return tuple(seen)


@dataclass(frozen=True)
class StationSpec:
    """一个 L2 工位的完整编排说明书."""
    station: str
    codesys_project: str
    extracted_at: str
    dispatcher_pou: str
    dispatcher_sha256: str
    accepts: tuple
    unknown_code_error: int
    gate_errors: dict = field(default_factory=dict)
    dispatcher_notes: str = ""
    constants: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)     # {动作码 int: ActionSpec}
    extras: dict = field(default_factory=dict)      # 非标准顶层块 (如 pump.yaml 的 aggregator)

    def action(self, code: int) -> Optional[ActionSpec]:
        """按动作码取记录; 未登记返回 None (调用方据此回 REJECTED)."""
        return self.actions.get(int(code))

    def anchors(self) -> dict:
        """全部 POU 锚点 {pou 路径: sha256} (漂移看门狗用; 同一 POU 多次引用去重)."""
        out = {self.dispatcher_pou: self.dispatcher_sha256}
        for spec in self.actions.values():
            out.setdefault(spec.pou, spec.sha256)
        for block in self.extras.values():
            if isinstance(block, dict) and block.get("pou") and block.get("sha256"):
                out.setdefault(block["pou"], block["sha256"])
        return out


def normalize_st(text: str) -> str:
    """规范化 ST 文本供哈希: CRLF->LF, 去行尾空白, 去尾部空行.

    参数:
        text: 原始 ST 文本 (声明或实现)
    返回:
        str, 规范化后的文本
    """
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def st_sha256(declaration: str, implementation: str) -> str:
    """按提取侧同一口径计算 POU 的 ST 哈希 (声明与实现以 \\n---\\n 相连)."""
    payload = normalize_st(declaration) + "\n---\n" + normalize_st(implementation)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_action(code_key: Any, raw: dict, station: str) -> ActionSpec:
    """把一条 actions 记录转成 ActionSpec; 字段缺失或取值非法即抛错."""
    try:
        code = int(code_key)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{station} spec: 动作键 {code_key!r} 不是整数码") from exc
    for required in ("name", "pou", "sha256", "kind", "summary"):
        if not raw.get(required):
            raise ValueError(f"{station} spec: 动作 {code} 缺字段 {required}")
    kind = str(raw["kind"])
    if kind not in KINDS:
        raise ValueError(f"{station} spec: 动作 {code} 的 kind {kind!r} 不在 {KINDS}")
    steps = tuple({"step": int(item["step"]), "phase": str(item.get("phase") or "")}
                  for item in (raw.get("steps") or []))
    errors = {int(key): str(value) for key, value in (raw.get("errors") or {}).items()}
    return ActionSpec(
        code=code, name=str(raw["name"]), pou=str(raw["pou"]),
        sha256=str(raw["sha256"]), kind=kind, summary=str(raw["summary"]),
        steps=steps, gate=dict(raw.get("gate") or {}), errors=errors,
        notes=str(raw.get("notes") or ""),
    )


def load_station_spec(station: str, *, spec_dir: Path | None = None) -> StationSpec:
    """加载某工位的编排说明书.

    参数:
        station: 工位名 (L2 节点前缀, 如 FeedLift); 文件名取其蛇形小写
        spec_dir: 覆盖 spec 目录 (测试用); 缺省 mock/behavior/specs
    返回:
        StationSpec
    Raises:
        FileNotFoundError: 无该工位 spec
        ValueError: schema 不符 / 必填缺失 / 动作键与 accepts 不双射
    """
    directory = spec_dir or _SPEC_DIR
    path = directory / (_file_stem(station) + ".yaml")
    if not path.exists():
        raise FileNotFoundError(f"未找到工位 {station} 的编排说明书: {path}")
    doc = yaml.safe_load(path.read_bytes().decode("utf-8")) or {}
    schema = str(doc.get("schema") or "")
    if schema != _SCHEMA_KEY:
        raise ValueError(f"{path.name}: schema 应为 {_SCHEMA_KEY}, 实际 {schema!r}")
    if str(doc.get("station") or "") != station:
        raise ValueError(f"{path.name}: station 应为 {station}, 实际 {doc.get('station')!r}")

    dispatcher = doc.get("dispatcher") or {}
    for required in ("pou", "sha256", "accepts", "unknown_code_error"):
        if dispatcher.get(required) in (None, "", []):
            raise ValueError(f"{path.name}: dispatcher 缺字段 {required}")
    accepts = tuple(int(code) for code in dispatcher["accepts"])

    actions = {}
    for code_key, raw in (doc.get("actions") or {}).items():
        spec = _parse_action(code_key, raw, station)
        actions[spec.code] = spec
    # 双射校验: 派发器接受的码必须条条有记录, 记录也不许多出来 —— 这是行为层
    # "未登记码回 REJECTED" 的正确性前提
    missing = sorted(set(accepts) - set(actions))
    extra = sorted(set(actions) - set(accepts))
    if missing or extra:
        raise ValueError(
            f"{path.name}: 动作键与 accepts 不双射 (缺 {missing}, 多 {extra})")

    known_top = {"schema", "station", "codesys_project", "extracted_at",
                 "dispatcher", "constants", "actions"}
    extras = {key: value for key, value in doc.items() if key not in known_top}
    return StationSpec(
        station=station,
        codesys_project=str(doc.get("codesys_project") or ""),
        extracted_at=str(doc.get("extracted_at") or ""),
        dispatcher_pou=str(dispatcher["pou"]),
        dispatcher_sha256=str(dispatcher["sha256"]),
        accepts=accepts,
        unknown_code_error=int(dispatcher["unknown_code_error"]),
        gate_errors={int(k): str(v) for k, v in (dispatcher.get("gate_errors") or {}).items()},
        dispatcher_notes=str(dispatcher.get("notes") or ""),
        constants=dict(doc.get("constants") or {}),
        actions=actions,
        extras=extras,
    )


def load_all_specs(*, spec_dir: Path | None = None) -> dict:
    """加载全部工位 spec, 返回 {station: StationSpec}."""
    directory = spec_dir or _SPEC_DIR
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        doc = yaml.safe_load(path.read_bytes().decode("utf-8")) or {}
        station = str(doc.get("station") or "")
        if not station:
            raise ValueError(f"{path.name}: 缺 station 字段")
        out[station] = load_station_spec(station, spec_dir=directory)
    return out


def _file_stem(station: str) -> str:
    """工位名 -> 文件名主干 (StagingA -> staging_a, PhotoScrape -> photoscrape)."""
    special = {"StagingA": "staging_a"}
    if station in special:
        return special[station]
    return station.lower()
