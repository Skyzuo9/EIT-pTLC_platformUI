"""test_cnc_minimal.py — PLC CNC 刮取最小验证脚本

目标：纯验证 PLC 侧 SMC_CNC_REF pipeline 能否完成多 pass 刮取，
     不依赖上位机的 vision / gcode_generator / config / sample_store。

仅依赖 core.plc_client（OPC UA 通信），坐标用硬编码矩形锯齿。

用法：
    cd UI-Upper

    # 1) 列出当前 PLC 上可用的 ScrapeCNC 变量（自检）
    python scripts/test_cnc_minimal.py --probe

    # 2) 默认矩形 3 pass 刮取（mock 或实机均可）
    python scripts/test_cnc_minimal.py --passes 3

    # 3) 自定义矩形范围 + 实机地址
    python scripts/test_cnc_minimal.py \\
        --url opc.tcp://192.168.1.100:4840 \\
        --passes 2 --depth 0.5 \\
        --x0 10 --x1 50 --y0 20 --y1 40

    # 4) 安全占位（g_pass_count=0，PLC 应跳过 SMC pipeline）
    python scripts/test_cnc_minimal.py --safe

契约参考: docs/PLC_ScrapeCNC_Interface.md
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.plc_client import PLCClient  # noqa: E402

log = logging.getLogger("test_cnc_min")

N = 400  # 数组长度，与 ScrapeCNC ARRAY[1..400] 对齐

# ── 默认 Z 参数（mm）──
DEFAULT_SAFE_Z = 5.0
DEFAULT_APPROACH_Z = 6.5
DEFAULT_PLATE_SURFACE_Z = 7.0
DEFAULT_SCRAPE_FEED = 800   # mm/min
DEFAULT_PLUNGE_FEED = 200   # mm/min


# ---------------------------------------------------------------------------
# 矩形锯齿坐标生成（纯 Python，无外部依赖）
# ---------------------------------------------------------------------------

def rect_zigzag(
    x0: float, y0: float, x1: float, y1: float, n: int = N,
) -> tuple[list[float], list[float]]:
    """在 (x0,y0)-(x1,y1) 矩形内生成 n 点锯齿路径。

    X 均分 n-1 段，Y 交替 y1/y0。
    返回 (xs, ys) 两个长度=n 的 list。
    """
    if n < 2:
        raise ValueError("n must >= 2")
    step = (x1 - x0) / (n - 1)
    xs = [x0 + i * step for i in range(n)]
    ys = [y1 if i % 2 == 0 else y0 for i in range(n)]
    return xs, ys


def build_plc_params(
    *,
    x0: float, y0: float, x1: float, y1: float,
    passes: int,
    depth: float,
    safe_z: float = DEFAULT_SAFE_Z,
    approach_z: float = DEFAULT_APPROACH_Z,
    plate_surface_z: float = DEFAULT_PLATE_SURFACE_Z,
    scrape_feed: int = DEFAULT_SCRAPE_FEED,
    plunge_feed: int = DEFAULT_PLUNGE_FEED,
) -> dict:
    """构造 12 个 ScrapeCNC 变量的 dict，可直接传给 send_recipe_params。"""
    sx, sy = rect_zigzag(x0, y0, x1, y1)
    # 收集路径：同矩形，X 偏移 -2mm 模拟瓶口偏移
    cx, cy = rect_zigzag(x0 - 2.0, y0, x1 - 2.0, y1)

    pass_count = max(0, passes)
    # 首 pass Z = 板面 + 总深度 / pass 数
    pass_z = plate_surface_z + depth / pass_count if pass_count > 0 else safe_z

    return {
        "g_sx":              sx,
        "g_sy":              sy,
        "g_cx":              cx,
        "g_cy":              cy,
        "g_safe_z":          safe_z,
        "g_approach_z":      approach_z,
        "g_pass_z":          pass_z,
        "g_pass_count":      pass_count,
        "g_total_depth":     depth,
        "g_plate_surface_z": plate_surface_z,
        "g_scrape_feed":     scrape_feed,
        "g_plunge_feed":     plunge_feed,
    }


def build_safe_params() -> dict:
    """安全占位：pass_count=0，全 0 坐标，PLC 应跳过 SMC pipeline。"""
    zeros = [0.0] * N
    return {
        "g_sx": zeros, "g_sy": zeros,
        "g_cx": zeros, "g_cy": zeros,
        "g_safe_z":          DEFAULT_SAFE_Z,
        "g_approach_z":      DEFAULT_APPROACH_Z,
        "g_pass_z":          DEFAULT_SAFE_Z,
        "g_pass_count":      0,
        "g_total_depth":     1.0,
        "g_plate_surface_z": DEFAULT_PLATE_SURFACE_Z,
        "g_scrape_feed":     DEFAULT_SCRAPE_FEED,
        "g_plunge_feed":     DEFAULT_PLUNGE_FEED,
    }


# ---------------------------------------------------------------------------
# PLC 探测：列出 ScrapeCNC 变量是否可见
# ---------------------------------------------------------------------------

async def probe_plc(url: str) -> int:
    """连接 PLC 并检查 12 个 ScrapeCNC 变量是否存在。"""
    plc = PLCClient(url=url, reconnect_wait_timeout=5.0)
    try:
        await plc.connect()
    except Exception as e:
        log.error("PLC 连接失败 (%s): %s", url, e)
        return 3

    try:
        cnc_vars = [
            "g_sx", "g_sy", "g_cx", "g_cy",
            "g_safe_z", "g_approach_z", "g_pass_z",
            "g_pass_count", "g_total_depth",
            "g_plate_surface_z", "g_scrape_feed", "g_plunge_feed",
        ]
        found = [v for v in cnc_vars if v in plc._nodes]
        missing = [v for v in cnc_vars if v not in plc._nodes]
        print(f"PLC 已连接 ({url})")
        print(f"  ScrapeCNC 变量: {len(found)}/12 可见")
        if found:
            print(f"  ✓ {', '.join(found)}")
        if missing:
            print(f"  ✗ {', '.join(missing)}")
        # scrape FSM 变量
        fsm_vars = ["scrape_Enable", "scrape_Step", "scrape_Done",
                     "scrape_Error", "scrape_Reset", "scrape_Confirm", "scrape_Busy"]
        fsm_found = [v for v in fsm_vars if v in plc._nodes]
        fsm_missing = [v for v in fsm_vars if v not in plc._nodes]
        print(f"  scrape FSM 变量: {len(fsm_found)}/7 可见")
        if fsm_found:
            print(f"  ✓ {', '.join(fsm_found)}")
        if fsm_missing:
            print(f"  ✗ {', '.join(fsm_missing)}")
        return 0 if not missing and not fsm_missing else 1
    finally:
        try:
            await plc.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Readback 校验：写完必须读回确认 PLC 侧拿到的是本次值
# ---------------------------------------------------------------------------

# 标量变量 — 精确比对
_SCALAR_KEYS = (
    "g_safe_z", "g_approach_z", "g_pass_z",
    "g_pass_count", "g_total_depth",
    "g_plate_surface_z", "g_scrape_feed", "g_plunge_feed",
)
# 数组变量 — 校验长度 + 首尾元素
_ARRAY_KEYS = ("g_sx", "g_sy", "g_cx", "g_cy")


def _close_enough(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) < tol


async def verify_readback(plc: PLCClient, params: dict) -> bool:
    """读回刚写入的 ScrapeCNC 变量，与期望值逐一比对。

    Returns:
        True = 全部一致；False = 至少一个不匹配（已打印差异）。
    """
    ok = True

    # ── 标量 ──
    for key in _SCALAR_KEYS:
        if key not in params:
            continue
        expected = params[key]
        try:
            actual = await plc.read_variable(key)
        except Exception as e:
            log.error("[VERIFY] 读取 %s 失败: %s", key, e)
            ok = False
            continue
        # g_pass_count 是 INT，其余是 LREAL
        if isinstance(expected, int):
            match = int(actual) == expected
        else:
            match = _close_enough(float(actual), float(expected))
        if not match:
            log.error("[VERIFY] %s 不匹配: 写入=%s  读回=%s", key, expected, actual)
            ok = False
        else:
            log.debug("[VERIFY] %s = %s ✓", key, actual)

    # ── 数组 ──
    for key in _ARRAY_KEYS:
        if key not in params:
            continue
        expected = params[key]
        try:
            actual = await plc.read_variable(key)
        except Exception as e:
            log.error("[VERIFY] 读取 %s 失败: %s", key, e)
            ok = False
            continue
        actual_list = list(actual) if not isinstance(actual, list) else actual
        if len(actual_list) != len(expected):
            log.error(
                "[VERIFY] %s 长度不匹配: 期望=%d  读回=%d",
                key, len(expected), len(actual_list),
            )
            ok = False
            continue
        # 校验首尾 + 中间一个点
        probe_indices = [0, len(expected) // 2, len(expected) - 1]
        for idx in probe_indices:
            if not _close_enough(float(actual_list[idx]), float(expected[idx])):
                log.error(
                    "[VERIFY] %s[%d] 不匹配: 写入=%.6f  读回=%.6f",
                    key, idx, expected[idx], actual_list[idx],
                )
                ok = False
        if ok:
            log.debug(
                "[VERIFY] %s len=%d first=%.4f last=%.4f ✓",
                key, len(actual_list), actual_list[0], actual_list[-1],
            )

    return ok


# ---------------------------------------------------------------------------
# 主流程：写参数 → readback 校验 → 触发 FSM → 等待完成
# ---------------------------------------------------------------------------

async def run_scrape(args: argparse.Namespace) -> int:
    # 1. 构造参数
    if args.safe:
        params = build_safe_params()
        log.info("[MIN] 安全占位模式: g_pass_count=0")
    else:
        params = build_plc_params(
            x0=args.x0, y0=args.y0, x1=args.x1, y1=args.y1,
            passes=args.passes, depth=args.depth,
        )
        log.info(
            "[MIN] 矩形 [%.1f,%.1f]-[%.1f,%.1f]mm  passes=%d  depth=%.2fmm",
            args.x0, args.y0, args.x1, args.y1, args.passes, args.depth,
        )

    # 2. 连接 PLC
    plc = PLCClient(url=args.url, reconnect_wait_timeout=10.0)
    try:
        await plc.connect()
    except Exception as e:
        log.error("PLC 连接失败 (%s): %s", args.url, e)
        return 3

    try:
        # 3. batch 写 12 个 ScrapeCNC 变量
        await plc.send_recipe_params(params)
        log.info("[MIN] 已写入 %d 个 ScrapeCNC 变量", len(params))

        # 4. readback 校验：确认 PLC 侧值与写入值一致
        await asyncio.sleep(0.05)  # 写入后短暂等待，确保 PLC 侧刷新
        if not await verify_readback(plc, params):
            log.error("[MIN] readback 校验失败，中止（不触发 FSM）")
            return 4
        log.info("[MIN] readback 校验通过 ✓  12 个变量全部一致")

        # 5. 显式写 scrape_PhotoMode=0（完整刮取路径）
        #    防止 PLC 残留 PhotoMode=1（BeforePhotoStage 写入）导致 A10 完成后路由到 before-photo
        await plc.write_variable("scrape_PhotoMode", 0)
        log.info("[MIN] scrape_PhotoMode=0（强制完整刮取路径）")

        # 6. 50ms 稳定时间（契约要求参数写完到 Enable 间 ≥50ms）
        await asyncio.sleep(0.05)

        # 7. 启动 scrape FSM
        await plc.start_stage("scrape")
        log.info("[MIN] scrape_Enable=TRUE，等待 Step=15（A10 拍照+乒乓）...")

        # 8. 等 Step 15（唯一乒乓点，A10 FB 内部等 Confirm）
        async def _on_step(step: int) -> None:
            log.info("[MIN]   scrape_Step → %d", step)

        await plc.await_stage_step(
            "scrape", 15,
            on_step_change=_on_step,
            timeout=args.step_timeout,
        )

        # 9. 写 Confirm → A10 返回 → PLC 自动走 20(CNC)→30(机器人)→Done
        await plc.confirm_stage("scrape")
        log.info("[MIN] scrape_Confirm=TRUE → PLC 进入 CNC 流程")

        # 10. 等 Done
        await plc.await_stage_done(
            "scrape",
            on_step_change=_on_step,
            timeout=args.done_timeout,
        )
        log.info("[MIN] scrape_Done=TRUE ✓  PLC CNC 刮取验证通过")
        return 0

    except (RuntimeError, TimeoutError) as e:
        log.error("[MIN] 失败: %s", e)
        return 1
    finally:
        try:
            await plc.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="PLC CNC 刮取最小验证（仅依赖 PLCClient，坐标硬编码矩形锯齿）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--url", default="opc.tcp://localhost:4840",
                   help="OPC UA 服务器地址")
    p.add_argument("--probe", action="store_true",
                   help="仅探测 PLC 变量可见性后退出")

    # 刮取参数
    p.add_argument("--passes", type=int, default=3,
                   help="刮取 pass 次数（g_pass_count）")
    p.add_argument("--depth", type=float, default=1.0,
                   help="总刮取深度 (mm)")

    # 矩形范围（mm 机床坐标）
    p.add_argument("--x0", type=float, default=10.0, help="矩形 X 起点 (mm)")
    p.add_argument("--y0", type=float, default=20.0, help="矩形 Y 下界 (mm)")
    p.add_argument("--x1", type=float, default=50.0, help="矩形 X 终点 (mm)")
    p.add_argument("--y1", type=float, default=40.0, help="矩形 Y 上界 (mm)")

    # 安全模式
    p.add_argument("--safe", action="store_true",
                   help="发安全占位（pass_count=0），验证 PLC 跳过逻辑")

    # 超时
    p.add_argument("--step-timeout", type=float, default=120.0,
                   help="await_stage_step 超时 (s)")
    p.add_argument("--done-timeout", type=float, default=600.0,
                   help="await_stage_done 超时 (s)")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")

    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.probe:
        return asyncio.run(probe_plc(args.url))
    return asyncio.run(run_scrape(args))


if __name__ == "__main__":
    sys.exit(main())
