"""液位配置一致性看板 + 提交/广播台 (CLI, 上位机侧)
====================================================
与 wl_replay_tune 同级同类。唯一改真源 water_level_calib.json 的入口 (不可逆动作集中一处, 可审计)。

只读 (默认):
    python -m eit_ptlc.tools.wl_config_board
    读真源 → 打印 8 通道 × 各全局层参数对齐表; 不一致字段行首标 ✗ + 期望值(多数)/无共识全值 +
    偏离通道号; 未标定通道 (无 ROI) 单列告警; 位姿层不判漂 (下期由网页走网关)。

提交/广播:
    python -m eit_ptlc.tools.wl_config_board --commit <stem>.tuned.json [--broadcast] [--with-pose] [--dry-run] [--yes]
    读某通道调好的 tuned.json → 逐字段 diff → (确认) → 备份 → 写 → 自动重跑只读看板证明"绿了"。
    --broadcast: 全局层落 8 路 (各按自身 rotation 重算 frac)。--with-pose: 额外把位姿写入该通道 (显式越权)。
    --dry-run: 走到 diff 即停, 不备份不写。--yes: 跳过交互确认 (脚本/测试)。

所有权 (spec §6): CLI commit 默认只落全局层; 回放时画的角/拖的框只算本地草稿, 非 --with-pose 不写。
网页永远只写位姿 (下期通过网关强制)。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from eit_ptlc.controller.waterlevel_config_tiers import (
    GLOBAL_JUDGMENT_FIELDS,
    REFERENCE_CAPTURE,
    apply_commit,
    audit,
    split_tiers,
)
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _default_calib_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"


def load_true_source(path: Path) -> dict[int, ChannelConfig]:
    """读真源; 不存在/空/解析失败 → 明确报错退出 (不静默造默认)。"""
    if not path.is_file():
        raise SystemExit(f"[看板] 真源不存在: {path}")
    configs = load_channel_configs(path)
    if not configs:
        raise SystemExit(f"[看板] 真源为空或解析失败: {path}")
    return configs


def render_report(configs: dict[int, ChannelConfig],
                  capture: tuple[int, int] = REFERENCE_CAPTURE) -> list[str]:
    """把只读看板渲染成文本行 (纯函数, 供打印与测试)。不一致字段行首 ✗。"""
    rep = audit(configs, capture)
    chans = sorted(configs)
    lines = [f"液位配置看板 (参考分辨率 {capture[0]}x{capture[1]}; 通道 {chans})", ""]
    header = "  " + "字段".ljust(18) + "".join(f"CH{ch}".rjust(8) for ch in chans) + "   判据"
    lines.append(header)
    lines.append("-" * (len(header) + 4))
    for fa in rep.fields:
        mark = "  " if fa.consistent else "✗ "
        row = mark + fa.field.ljust(18)
        for ch in chans:
            v = fa.values.get(ch)
            row += ("-" if v is None else f"{v}").rjust(8)
        if fa.consistent:
            verdict = "一致"
        elif fa.expected is not None:
            verdict = f"期望(多数)={fa.expected}, 偏离 CH{sorted(fa.deviants)}"
        else:
            byval: dict = {}
            for ch, v in sorted(fa.values.items()):
                byval.setdefault(v, []).append(ch)
            verdict = "无共识: " + "; ".join(f"{v}→CH{chs}" for v, chs in byval.items())
        lines.append(row + "   " + verdict)
    if rep.uncalibrated:
        lines.append("")
        lines.append(f"⚠ 未标定通道 (无 ROI): {rep.uncalibrated}")
    return lines


def cmd_show(path: Path, capture: tuple[int, int] = REFERENCE_CAPTURE) -> int:
    for line in render_report(load_true_source(path), capture):
        print(line)
    return 0


def diff_lines(old_configs: dict[int, ChannelConfig], new_configs: dict[int, ChannelConfig],
               capture: tuple[int, int] = REFERENCE_CAPTURE) -> list[str]:
    """逐通道逐字段 diff (现值 → 新值), 只列有变化的。"""
    lines: list[str] = []
    for ch in sorted(new_configs):
        old = split_tiers(old_configs[ch], capture) if ch in old_configs else None
        new = split_tiers(new_configs[ch], capture)
        changes: list[str] = []
        for f in GLOBAL_JUDGMENT_FIELDS:
            ov = getattr(old.judgment, f) if old else None
            nv = getattr(new.judgment, f)
            if ov != nv:
                changes.append(f"{f}: {ov} → {nv}")
        old_size = old.size_px if old else None
        if old_size != new.size_px:
            changes.append(f"size_px: {old_size} → {new.size_px}")
        old_pose = (old.pose.rotation_deg, old.pose.flow, old.pose.xy_px) if old else None
        new_pose = (new.pose.rotation_deg, new.pose.flow, new.pose.xy_px)
        if old_pose != new_pose:
            changes.append(f"pose(rot,flow,xy): {old_pose} → {new_pose}")
        if changes:
            lines.append(f"CH{ch}:")
            lines.extend(f"    {c}" for c in changes)
    return lines or ["(无变化)"]


def _backup(path: Path, now: str) -> Path:
    """备份真源 → <stem>.<now>.bak.json; 失败抛 OSError (调用方据此中止)。"""
    bak = path.with_name(f"{path.stem}.{now}.bak.json")
    shutil.copy2(path, bak)
    return bak


def cmd_commit(path: Path, tuned_path: Path, *, broadcast: bool, with_pose: bool,
               dry_run: bool, yes: bool, now: Optional[str] = None,
               capture: tuple[int, int] = REFERENCE_CAPTURE,
               confirm: Callable[[str], str] = input) -> int:
    """唯一改真源的入口。返回码: 0 成功/dry-run, 1 用户取消, 2 输入非法/退化, 3 备份失败中止。"""
    configs = load_true_source(path)
    tuned_map = load_channel_configs(tuned_path)
    if len(tuned_map) != 1:
        print(f"[看板] tuned 文件应恰含 1 个通道, 实含 {sorted(tuned_map)}", file=sys.stderr)
        return 2
    ch, tuned = next(iter(tuned_map.items()))
    if ch not in configs:
        print(f"[看板] CH{ch} 越界/不在真源 (真源含 {sorted(configs)})", file=sys.stderr)
        return 2

    try:
        new_configs = apply_commit(configs, ch, tuned,
                                   broadcast_global=broadcast, with_pose=with_pose, capture=capture)
    except ValueError as exc:
        print(f"[看板] 生成失败 (退化/越权): {exc}", file=sys.stderr)
        return 2

    print(f"[看板] 提交源 CH{ch}  广播={broadcast}  含位姿={with_pose}")
    print("---- 逐字段 diff (真源现值 → 新值) ----")
    for line in diff_lines(configs, new_configs, capture):
        print(line)

    if dry_run:
        print("[看板] --dry-run: 到此为止, 不备份不写。")
        return 0

    if not yes:
        ans = confirm("确认写入真源? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[看板] 已取消, 未写入。")
            return 1

    ts = now or datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        bak = _backup(path, ts)
    except OSError as exc:
        print(f"[看板] 备份失败, 中止 (不写真源): {exc}", file=sys.stderr)
        return 3
    print(f"[看板] 已备份 → {bak}")

    save_channel_configs(path, new_configs)
    print(f"[看板] 已写入真源 → {path}")

    print("\n---- 写后自动复核 ----")
    for line in render_report(load_true_source(path), capture):
        print(line)
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="液位配置一致性看板 + 提交/广播台")
    ap.add_argument("--calib", default=None, help="真源路径 (默认 config/water_level_calib.json)")
    ap.add_argument("--commit", metavar="TUNED", default=None, help="某通道 <stem>.tuned.json; 进入提交模式")
    ap.add_argument("--broadcast", action="store_true", help="全局层落 8 路 (各按自身 rotation 重算 frac)")
    ap.add_argument("--with-pose", action="store_true", help="额外把位姿写入该通道 (显式越权逃生口)")
    ap.add_argument("--dry-run", action="store_true", help="走到 diff 即停, 不备份不写")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认 (脚本/测试)")
    args = ap.parse_args(argv)
    path = Path(args.calib) if args.calib else _default_calib_path()
    if args.commit:
        return cmd_commit(path, Path(args.commit), broadcast=args.broadcast,
                          with_pose=args.with_pose, dry_run=args.dry_run, yes=args.yes)
    return cmd_show(path)


if __name__ == "__main__":
    raise SystemExit(main())
