"""沙盒诊断: "门为什么不满足"的结构化答案
========================================
功能:
    把八个工位的 L2 快照、前置门的逐条求值、以及传感器位的语义解读拼成一份只读诊断,
    供 /api/sim/diagnostics 与 /3d/sim 的诊断面板。

它要回答的是用户 2026-08-12 在截图里问的那个问题: 报了 301, 到底哪一项没满足?
真机上上位机答不出来 (bHomed 与 Alarm 都没有 OPC 节点, 只能给"依次去查这两项"的话术);
**沙盒答得出来** —— 板堆张数就是那个因, 它就在模型里。所以这里给的是**真因**,
不是排查指引。

三条纪律:
    * `because` 一律由**已有的合成规则原地求值**, 不新建第二套推断:
      板堆类直接调 FeedLiftModel 的同名方法 (与 feedlift._wait_gate 调的是同一批),
      传感器位复用 sensors.BIT_SPECS —— 结构上不可能与实际行为漂移。
    * **value=None 与 value=False 必须分开**: 把"读不到"(Alarm.0 无 OPC 节点)
      画成"不满足", 会把人引到错误的地方查。
    * 传感器位**永不折算极性**: PLC 的 ST 是裸位直接当 BOOL 用 (feedlift_count 的
      注释警告过), 折算了就与门对不上。物料在位对账那边按极性折算是另一回事。
"""

from __future__ import annotations

import logging

from eit_ptlc.mock.behavior.sensors import CONSTANT_ZERO, SENSOR_BYTES, decode_bytes

log = logging.getLogger(__name__)

#: 门项 -> 沙盒里由什么推导。键是 spec.gate 的键名 (逐字来自编排说明书)。
#: 未列出的门项一律给 value=None + "沙盒不合成", 不猜。
_FEEDLIFT_GATE_SOURCES = ("homed", "proximity", "feed_sensor", "out_sensor", "alarm")


def _feedlift_gate_rows(gate: dict, magazine: str, model) -> list:
    """FeedLift 某动作的前置门逐条求值 (含真因).

    参数:
        gate: spec.action(code).gate 原文; magazine: feed | waste; model: FeedLiftModel
    返回:
        List[dict] {key, spec, value, because}
    """
    rows = []
    count = int((model.counts or {}).get(magazine, 0))
    for key, text in (gate or {}).items():
        if key == "timeout_error":
            continue
        value = None
        because = "沙盒不合成该量"
        if key == "homed":
            value = bool((model.homed or {}).get(magazine, False))
            because = f"板堆模型 homed.{magazine} = {value}"
        elif key in ("proximity", "feed_sensor"):
            value = bool(model.proximity(magazine))
            because = (f"板堆模型 counts.{magazine} = {count} 张"
                       f"{' (仓是空的)' if count <= 0 else ''}")
            if key == "feed_sensor":
                because += "; 进料传感器是 PLC 内部量, 沙盒与接近开关简并映射"
        elif key == "out_sensor":
            because = ("下料出料传感器是 PLC 内部量, 沙盒无对应现场事实, 按恒成立处理 "
                       "(A21 的门刻意不查接近开关2, 空仓也要能升到接料位)")
        elif key == "alarm":
            value = bool(model.alarm_ok(magazine))
            capacity = (model.capacity or {}).get(magazine)
            if magazine == "feed":
                because = f"⚠ 推定: 按「上料机构无物料」字面含义由张数推导 ({count} 张)"
            else:
                because = (f"⚠ 推定: 按「下料机构已满料」字面含义由张数推导 "
                           f"({count}/{capacity} 张)")
        rows.append({"key": key, "spec": str(text), "value": value, "because": because})
    return rows


def station_rows(snapshots: dict, specs: dict, *, feedlift_model=None,
                 describe=None, context: str = "sim") -> list:
    """八个工位的 L2 现状 + 段号/错误码释义 + 前置门逐条.

    参数:
        snapshots: {工位: PLC L2 快照 dict 或 {"error": 原因}}
        specs: {工位: StationSpec}
        feedlift_model: FeedLiftModel (给了才求 FeedLift 的门真值)
        describe: (station, action_code, error_code, step, context) -> str
        context: 释义语境
    返回:
        List[dict]
    """
    out = []
    for station in sorted(snapshots):
        snap = snapshots[station] or {}
        row = {"station": station, "l2": snap, "action_name": "", "step_text": "",
               "error_text": "", "gate": []}
        if "error" in snap:
            out.append(row)
            continue
        spec = specs.get(station)
        code = int(snap.get("ActiveCode") or 0)
        step = int(snap.get("Step") or 0)
        error_code = int(snap.get("ErrorCode") or 0)
        action_spec = spec.action(code) if spec is not None else None
        if action_spec is not None:
            row["action_name"] = action_spec.name
            for item in action_spec.steps:
                if int(item["step"]) == step:
                    row["step_text"] = f"{step} · {item['phase']}"
                    break
        if describe is not None and error_code:
            try:
                row["error_text"] = describe(station, code, error_code, step, context=context)
            except Exception:
                log.debug("[沙盒·诊断] 释义失败 %s/%s", station, error_code, exc_info=True)
        if station == "FeedLift" and action_spec is not None and feedlift_model is not None:
            magazine = "feed" if code in (10, 11, 12, 13) else "waste"
            row["gate"] = _feedlift_gate_rows(action_spec.gate, magazine, feedlift_model)
        elif action_spec is not None and action_spec.gate:
            # 其余工位的门在 spec 里有原文, 但沙盒没有对应的可求值量 —— 如实给 None
            row["gate"] = [
                {"key": key, "spec": str(text), "value": None,
                 "because": "该工位的门条件沙盒不合成 (spec 有原文, 无对应现场事实)"}
                for key, text in action_spec.gate.items() if key != "timeout_error"]
        out.append(row)
    return out


def sensor_block(values: dict) -> dict:
    """传感器字节与具名位 (语义在前、裸位在后, 供面板并排显示).

    参数:
        values: {字节名: 整数值}
    返回:
        Dict {bytes: {名: {value, bits}}, bits: [...], constant_zero: [...]}
    """
    byte_rows = {}
    for name in SENSOR_BYTES:
        raw = values.get(name)
        byte_rows[name] = {
            "value": None if raw is None else int(raw),
            "bits": None if raw is None else format(int(raw) & 0xFF, "08b"),
        }
    return {
        "bytes": byte_rows,
        "bits": decode_bytes(values),
        "constant_zero": [{"range": rng, "reason": why} for rng, why in CONSTANT_ZERO],
    }


def feedlift_block(model, positions: dict) -> dict:
    """板堆模型现状 (张数/容量/回零/触发位/两个开关的推导值).

    参数:
        model: FeedLiftModel; positions: {板仓: 当前轴位 mm}
    返回:
        Dict {板仓: {...}}
    """
    out = {}
    for magazine in sorted(model.counts or {}):
        z_mm = positions.get(magazine)
        entry = {
            "count": int(model.counts[magazine]),
            "capacity": int((model.capacity or {}).get(magazine, 0)),
            "calibration_source": str(
                (getattr(model, "calibration_source", {}) or {}).get(magazine, "unknown")
            ),
            "homed": bool((model.homed or {}).get(magazine, False)),
            "z_mm": None if z_mm is None else round(float(z_mm), 3),
            "z_trigger_mm": None,
            "photo": None,
            "proximity": bool(model.proximity(magazine)),
            "alarm_ok": bool(model.alarm_ok(magazine)),
        }
        if magazine in (model.calib or {}):
            entry["z_trigger_mm"] = round(float(model.z_trigger(magazine)), 3)
            if z_mm is not None:
                entry["photo"] = bool(model.photo(magazine, float(z_mm)))
        out[magazine] = entry
    return out
