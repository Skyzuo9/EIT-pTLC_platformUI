"""test_cnc_e2e.py — CNC 刮取端到端测试脚本

复用真实 sample 数据（data/samples/<sample_id>/analysis/<sample_id>/summary.json）
通过 OPC UA 写入 ScrapeCNC 12 个变量，触发 scrape FSM 完整时序：
    start_stage → await_step(15) → confirm → await_done

不依赖 scheduler / vision / camera / sample_store / NiceGUI。
契约见 docs/PLC_ScrapeCNC_Interface.md，PLC ST 实现见 PLCsoftware/pTLC_Template/。

运行：
    cd UI-Upper
    python scripts/test_cnc_e2e.py --list-samples
    python scripts/test_cnc_e2e.py --sample S1 --band band_01 --passes 3
    python scripts/test_cnc_e2e.py --safe-placeholder
    python scripts/test_cnc_e2e.py --url opc.tcp://192.168.1.100:4840 --sample S5 --band band_02
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

# 让本脚本能 import core 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cnc_path_generator import (  # noqa: E402
    generate_scrape_arrays,
    safe_placeholder_arrays,
)
from core.config import GCodeCfg  # noqa: E402
from core.plc_client import PLCClient  # noqa: E402

log = logging.getLogger("test_cnc_e2e")

DEFAULT_URL = "opc.tcp://localhost:4840"
SAMPLES_ROOT = ROOT / "data" / "samples"
STEP_PHOTO = 15  # scrape FSM 唯一乒乓等待点（A10 FB 内部等 Confirm）


# ---------------------------------------------------------------------------
# Sample / band 发现
# ---------------------------------------------------------------------------

def _summary_path(sample_id: str) -> Path:
    """构造 summary.json 路径：data/samples/<id>/analysis/<id>/summary.json。"""
    return SAMPLES_ROOT / sample_id / "analysis" / sample_id / "summary.json"


def list_available_samples() -> list[tuple[str, list[str]]]:
    """扫描 data/samples/，返回所有含 summary.json 的样品及其 band_id 列表。"""
    if not SAMPLES_ROOT.is_dir():
        return []
    out: list[tuple[str, list[str]]] = []
    for child in sorted(SAMPLES_ROOT.iterdir()):
        if not child.is_dir():
            continue
        sp = _summary_path(child.name)
        if not sp.is_file():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            bands = [b.get("band_id", "") for b in data.get("bands", []) if b.get("band_id")]
        except (OSError, json.JSONDecodeError):
            bands = []
        out.append((child.name, bands))
    return out


# ---------------------------------------------------------------------------
# GCodeCfg 覆盖（命令行 --total-depth / --safe-z / --passes）
# ---------------------------------------------------------------------------

def _build_gcode_cfg(args: argparse.Namespace) -> GCodeCfg:
    """以 GCodeCfg() 默认值为底板，按 CLI 参数覆盖工艺参数。"""
    cfg = GCodeCfg()
    if args.safe_z is not None:
        cfg = replace(cfg, safe_z_mm=float(args.safe_z))
    # scrape 是嵌套 dataclass，单独覆盖
    scrape = cfg.scrape
    if args.passes is not None:
        scrape = replace(scrape, num_passes=int(args.passes))
    if args.total_depth is not None:
        scrape = replace(scrape, total_depth_mm=float(args.total_depth))
    cfg = replace(cfg, scrape=scrape)
    # contour 策略需要的 keep_ratio（其他策略无感）
    if args.keep_ratio is not None:
        cfg = replace(cfg, scrape_keep_ratio=float(args.keep_ratio))
    if args.strategy is not None:
        cfg = replace(cfg, path_strategy=str(args.strategy).strip().lower())
    return cfg


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def run_e2e(args: argparse.Namespace) -> int:
    gcode_cfg = _build_gcode_cfg(args)

    # 1. 生成点位数组（真实 sample / 安全占位）
    if args.safe_placeholder:
        arrays = safe_placeholder_arrays(gcode_cfg)
        log.info("[E2E] 安全占位模式：g_pass_count=0，全 0 数组")
    else:
        if not args.sample or not args.band:
            log.error("[E2E] 必须指定 --sample 与 --band（或用 --safe-placeholder / --list-samples）")
            return 2
        sp = _summary_path(args.sample)
        if not sp.is_file():
            log.error("[E2E] summary.json 不存在: %s", sp)
            return 2
        try:
            arrays = generate_scrape_arrays(sp, args.band, gcode_cfg)
        except (FileNotFoundError, KeyError) as e:
            log.error("[E2E] 点位生成失败: %s", e)
            return 2
        log.info(
            "[E2E] sample=%s band=%s pass_count=%d total_depth=%.2fmm",
            args.sample, args.band, arrays.g_pass_count, arrays.g_total_depth,
        )

    # 2. 连接 PLC
    plc = PLCClient(url=args.url, reconnect_wait_timeout=10.0)
    try:
        await plc.connect()
    except Exception as e:
        log.error("[E2E] PLC 连接失败 (%s): %s", args.url, e)
        return 3

    try:
        # 3. batch 写 12 变量
        plc_params = arrays.as_plc_dict()
        await plc.send_recipe_params(plc_params)
        log.info("[E2E] 已 batch 写入 %d 个 ScrapeCNC 变量", len(plc_params))

        # 4. 50ms 稳定时间
        await asyncio.sleep(0.05)

        # 5. 启动 scrape FSM
        await plc.start_stage("scrape")
        log.info("[E2E] scrape_Enable=TRUE，等待 Step=%d（A10 拍照+乒乓）...", STEP_PHOTO)

        # 6. 等待 Step 15（唯一乒乓点，A10 FB 内部等 Confirm）
        async def _on_step(step: int) -> None:
            log.info("[E2E] scrape_Step → %d", step)

        await plc.await_stage_step(
            "scrape", STEP_PHOTO,
            on_step_change=_on_step,
            timeout=args.step_timeout,
        )

        # 7. 写 Confirm → A10 返回 → PLC 自动走 20(CNC)→30(机器人)→Done
        await plc.confirm_stage("scrape")
        log.info("[E2E] scrape_Confirm=TRUE → PLC 进入 CNC 流程")

        # 8. 等整个流程完成
        await plc.await_stage_done(
            "scrape",
            on_step_change=_on_step,
            timeout=args.done_timeout,
        )
        log.info("[E2E] scrape_Done=TRUE，端到端测试通过 ✓")
        return 0

    except (RuntimeError, TimeoutError) as e:
        log.error("[E2E] 失败: %s", e)
        return 1
    finally:
        try:
            await plc.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_samples() -> int:
    samples = list_available_samples()
    if not samples:
        print(f"未在 {SAMPLES_ROOT} 下发现含 summary.json 的样品")
        return 1
    print(f"可用样品（{len(samples)} 个）:")
    for sid, bands in samples:
        print(f"  {sid}  bands={bands}")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CNC 刮取端到端测试（复用真实 sample 数据）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--url", default=DEFAULT_URL, help="OPC UA 服务器地址")
    p.add_argument("--sample", help="样品 ID（如 S1, SDB002），与 --band 配合使用")
    p.add_argument("--band", help="band 名（如 band_01, band_02）")
    p.add_argument("--passes", type=int, default=None, help="覆盖 scrape.num_passes")
    p.add_argument("--total-depth", type=float, default=None, help="覆盖 scrape.total_depth_mm")
    p.add_argument("--safe-z", type=float, default=None, help="覆盖 GCodeCfg.safe_z_mm")
    p.add_argument(
        "--strategy", default=None,
        choices=["zigzag", "boustrophedon", "contour"],
        help="覆盖 GCodeCfg.path_strategy（默认走 GCodeCfg 默认值）",
    )
    p.add_argument(
        "--keep-ratio", type=float, default=None,
        help="contour 策略下的每列保留比例（0,1]；其他策略无感",
    )
    p.add_argument(
        "--safe-placeholder", action="store_true",
        help="发安全占位（g_pass_count=0），验证 PLC 跳过 SMC pipeline",
    )
    p.add_argument("--list-samples", action="store_true", help="列出可用样品后退出")
    p.add_argument("--step-timeout", type=float, default=120.0, help="await_stage_step 超时秒数")
    p.add_argument("--done-timeout", type=float, default=600.0, help="await_stage_done 超时秒数")
    p.add_argument("--verbose", "-v", action="store_true", help="DEBUG 日志")
    return p


def main() -> int:
    args = _build_arg_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.list_samples:
        return _print_samples()
    return asyncio.run(run_e2e(args))


if __name__ == "__main__":
    sys.exit(main())
