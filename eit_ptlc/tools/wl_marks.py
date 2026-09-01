"""液位标记板真值标注 + %↔cm 物理刻度计算 (纯函数, 无 cv2/numpy)
====================================================================
职责:
    整定台 (wl_replay_tune) 的标记板打标数据层与计算层。标记板 = 距板顶
    5/4/3/2/1cm 画横标线的 TLC 板; 人在整定台拖帧到前沿越线帧按数字键打标,
    本模块负责真值文件 (<stem>.marks.json) 读写与报告计算。

设计决策 (spec 2026-07-17-waterlevel-marked-board-calibration-design.md):
    - marks.json 只存纯真值 {cm, frame_idx, ts}; front_percent 由调用方在
      出报告时用**当前参数**现算后经 build_report 传入 —— 改参数后标定自动
      跟新, 真值永不过期 (与整定台 ref_frame_idx 每次现算参考图同一哲学)。
    - 缺标线内建: 拟合 ≥2 点即出; 区间速度按实际 Δcm 相邻分段; ts 缺失段跳过。
    - 本模块纯 stdlib, 离线测试零重依赖 (test_waterlevel_marks_offline.py)。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MARKS_SCHEMA = "ptlc.wl-marks/v1"
REPORT_SCHEMA = "ptlc.wl-marks-report/v1"
DEFAULT_MARKS_CM = (5.0, 4.0, 3.0, 2.0, 1.0)


# ---- 旁挂路径 (与 waterlevel_recorder._sidecar_paths 同构; 双点后缀手拼) ----
def _stem(avi_path) -> Path:
    return Path(avi_path).with_suffix("")


def jsonl_path(avi_path) -> Path:
    return _stem(avi_path).with_suffix(".jsonl")


def marks_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".marks.json")


def report_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".marks_report.json")


def curve_png_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".curve.png")


# ---- jsonl 时间戳 ----
def load_timestamps(path) -> dict[int, float]:
    """录制 .jsonl → {frame_idx: epoch_seconds}; 缺文件→空, 坏行跳过。"""
    path = Path(path)
    stamps: dict[int, float] = {}
    if not path.is_file():
        return stamps
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            stamps[int(row["i"])] = float(row["t"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return stamps


# ---- marks 文件 ----
def new_marks(channel, recording, marks_cm=DEFAULT_MARKS_CM) -> dict:
    return {
        "schema": MARKS_SCHEMA,
        "channel": int(channel) if channel is not None else None,
        "recording": str(recording),
        "marks_cm": [float(c) for c in marks_cm],
        "events": [],
        "updated_at": None,
    }


def load_marks(path) -> Optional[dict]:
    """缺文件 → None; 坏 JSON / schema 不符 → ValueError (调用方决定怎么提示)。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"marks 文件不可解析: {path} ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema") != MARKS_SCHEMA:
        raise ValueError(f"marks schema 不符: {path} ({data.get('schema')!r})")
    data.setdefault("events", [])
    data.setdefault("marks_cm", list(DEFAULT_MARKS_CM))
    return data


def get_event(marks: dict, cm) -> Optional[dict]:
    for ev in marks["events"]:
        if float(ev["cm"]) == float(cm):
            return ev
    return None


def toggle_event(marks: dict, cm, frame_idx: int, ts) -> str:
    """打标语义: 无 → set; 换帧 → moved (覆盖); 同帧重按 → cleared (取消)。"""
    ev = get_event(marks, cm)
    if ev is not None and int(ev["frame_idx"]) == int(frame_idx):
        marks["events"].remove(ev)
        return "cleared"
    if ev is not None:
        ev["frame_idx"] = int(frame_idx)
        ev["ts"] = float(ts) if ts is not None else None
        return "moved"
    marks["events"].append({"cm": float(cm), "frame_idx": int(frame_idx),
                            "ts": float(ts) if ts is not None else None})
    marks["events"].sort(key=lambda e: -float(e["cm"]))
    return "set"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, path)


def save_marks(path, marks: dict) -> None:
    marks["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(Path(path), marks)


def save_report(path, report: dict) -> None:
    _write_json_atomic(Path(path), report)


# ====================================================================
# 计算层: %↔cm 拟合 / 残差 / 区间速度 / 报告 (全部内建缺标线支持)
# ====================================================================
def linear_fit(pairs) -> Optional[dict]:
    """最小二乘 front_percent = a·d + b (d = 距板顶 cm)。

    n<2 或 d 全同 → None (不拟合); r2 仅 n≥3 且 front 有方差时给出。
    """
    pts = [(float(d), float(f)) for d, f in pairs]
    n = len(pts)
    if n < 2:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
    intercept = my - slope * mx
    r2 = None
    if n >= 3:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in pts)
        ss_tot = sum((y - my) ** 2 for _, y in pts)
        if ss_tot > 0:
            r2 = 1.0 - ss_res / ss_tot
    return {"slope_pct_per_cm": slope, "intercept_pct": intercept,
            "r2": r2, "n": n}


def invert_fit(fit: dict, front_percent) -> float:
    """反演读数器: d(front%) = (front% − b) / a  [cm, 距板顶]。"""
    a = float(fit["slope_pct_per_cm"])
    if abs(a) < 1e-9:
        raise ValueError("拟合斜率≈0, 无法反演 d(front%)")
    return (float(front_percent) - float(fit["intercept_pct"])) / a


def residuals(pairs, fit: dict) -> list[dict]:
    a, b = float(fit["slope_pct_per_cm"]), float(fit["intercept_pct"])
    return [{"cm": float(d), "front_percent": float(f),
             "residual": float(f) - (a * float(d) + b)} for d, f in pairs]


def segment_velocities(events) -> list[dict]:
    """相邻已标线对 (cm 降序 = 时间正序) → 实际 Δcm/Δt。

    ts 缺失或 dt≤0 (时序倒挂) 的段跳过并注明 —— 缺 1cm/跳档 (只标 5/3/2)
    自动适配, 不假设标线齐全。
    """
    evs = sorted(events, key=lambda e: -float(e["cm"]))
    out: list[dict] = []
    for hi, lo in zip(evs, evs[1:]):
        seg: dict[str, Any] = {"from_cm": float(hi["cm"]), "to_cm": float(lo["cm"])}
        t_hi, t_lo = hi.get("ts"), lo.get("ts")
        if t_hi is None or t_lo is None:
            seg["skipped"] = "ts_missing"
        else:
            dt = float(t_lo) - float(t_hi)
            if dt <= 0:
                seg["skipped"] = f"dt_nonpositive:{dt:.3f}"
            else:
                seg["dt_s"] = round(dt, 3)
                seg["cm_per_min"] = (float(hi["cm"]) - float(lo["cm"])) / dt * 60.0
        out.append(seg)
    return out


def build_report(marks: dict, fronts: dict, calib_snapshot=None,
                 params_snapshot=None, r2_warn: float = 0.98,
                 ref_frame_idx=None) -> dict:
    """组装报告 (纯函数)。fronts = {cm: front_percent|None}, 由调用方现算传入。

    front 为 None 的线 (未设参考/检测 invalid) 不入拟合但保留在 marks 行。
    ref_frame_idx = 现算 front 所用参考(干板)帧号; 落进报告使标定可复现 (缺→None)。
    """
    rows: list[dict] = []
    pairs: list[tuple[float, float]] = []
    for ev in sorted(marks["events"], key=lambda e: -float(e["cm"])):
        cm = float(ev["cm"])
        front = fronts.get(cm)
        rows.append({"cm": cm, "frame_idx": ev["frame_idx"], "ts": ev.get("ts"),
                     "front_percent": front, "residual": None})
        if front is not None:
            pairs.append((cm, float(front)))
    fit = linear_fit(pairs)
    if fit is not None:
        res_by_cm = {r["cm"]: r["residual"] for r in residuals(pairs, fit)}
        for row in rows:
            if row["front_percent"] is not None:
                row["residual"] = res_by_cm.get(row["cm"])
    vels = segment_velocities(marks["events"])
    suggestion = None
    if fit is not None:
        usable = [v for v in vels if "cm_per_min" in v]
        if usable:
            top = min(usable, key=lambda v: v["to_cm"])   # 最靠板顶的可用段
            speed = top["cm_per_min"] / 60.0 * abs(fit["slope_pct_per_cm"])
            suggestion = {
                "segment": [top["from_cm"], top["to_cm"]],
                "speed_pct_per_s": round(speed, 5),
                "formula": (f"t1_offset ≈ 就位时间(s) × {speed:.4f} %/s"
                            f" (如 60s → {60 * speed:.1f}%)"),
            }
    r2 = fit.get("r2") if fit else None
    return {
        "schema": REPORT_SCHEMA,
        "channel": marks.get("channel"),
        "recording": marks.get("recording"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "marks": rows,
        "fit": fit,
        "r2_warning": bool(r2 is not None and r2 < r2_warn),
        "velocities": vels,
        "suggestion": suggestion,
        "front_source": "single_frame",
        "ref_frame_idx": ref_frame_idx,
        "calib_snapshot": calib_snapshot,
        "params_snapshot": params_snapshot,
    }


def format_report(report: dict) -> str:
    """终端可读多行文本 (报告头带物理前提)。"""
    lines = [f"[标记板报告] CH{report.get('channel')} {report.get('recording')}"
             f"  (前提: 标记与板同框进干板参考, 参考窗口后未改动)"]
    for row in report["marks"]:
        f, r = row["front_percent"], row["residual"]
        lines.append(f"  {row['cm']:g}cm @f{row['frame_idx']}  front="
                     + (f"{f:.2f}%" if f is not None else "—")
                     + (f"  残差 {r:+.2f}%" if r is not None else ""))
    fit = report["fit"]
    if fit is None:
        lines.append("  ! 可用 front <2 点, 无拟合"
                     " (未设参考帧 r / 检测 invalid / 标注不足)"
                     if report["marks"] else
                     "  (尚无标注: 拖帧到前沿越线时刻按数字键打标)")
    else:
        a, b = fit["slope_pct_per_cm"], fit["intercept_pct"]
        r2_txt = f", R²={fit['r2']:.4f}" if fit["r2"] is not None else ""
        lines.append(f"  拟合 front% = {a:.3f}·d + {b:.2f}  (n={fit['n']}{r2_txt})")
        lines.append(f"  反演 d(front%) = (front% − {b:.2f}) / ({a:.3f})  [cm, 距板顶]")
        if report["r2_warning"]:
            lines.append("  ⚠ R² 偏低: 可能透视/ROI 不正, 物理映射慎用")
    for v in report["velocities"]:
        if "cm_per_min" in v:
            lines.append(f"  速度 {v['from_cm']:g}→{v['to_cm']:g}cm:"
                         f" {v['cm_per_min']:.3f} cm/min (Δt={v['dt_s']:.0f}s)")
        else:
            lines.append(f"  速度 {v['from_cm']:g}→{v['to_cm']:g}cm:"
                         f" 跳过 ({v['skipped']})")
    if report["suggestion"]:
        lines.append("  建议(参考): " + report["suggestion"]["formula"])
    return "\n".join(lines)


def format_hud_line(marks: dict) -> str:
    """HUD 单行: 已标 `5cm@f210`, 缺标聚合括号注明。"""
    parts: list[str] = []
    missing: list[str] = []
    for cm in sorted((float(c) for c in marks["marks_cm"]), reverse=True):
        ev = get_event(marks, cm)
        if ev is None:
            missing.append(f"{cm:g}cm")
        else:
            parts.append(f"{cm:g}cm@f{ev['frame_idx']}")
    line = "marks: " + (" ".join(parts) if parts else "(无)")
    if missing:
        line += f" ({'/'.join(missing)} 缺)"
    return line
