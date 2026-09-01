"""PLC L2 验收工具离线测试 (语义档案 builder + 通道写入)
=========================================================
功能:
    启动 Mock OPC UA + 三工位 L2 FSM, 验证 plc_l2_acceptance 工具的注射泵语义档案
    PUMP_PROFILES[*].build 能把语义参数 (体积/比例/次数/坐标) 转成 PLC 通道字典, 并经
    PlcController.execute 写入预留变量 (字符串数组整体写) 后动作走到 DONE。
    覆盖上样清洗/上样吸液 (Sampling) · 收集加液 (Collect) · 展缸上液/润洗 (Develop)。
    展缸排液 v2 全相位/Cap挟持/非法态拒绝 (develop 排液语义桥)。

运行:
    E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.controller.plc_controller import PLCActionError, PLCActionState, PlcController
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.mock.plc_server import build_mock_server, mock_read, mock_write, run_l2_fsm, run_tank_drain_fsm
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES

_URL = "opc.tcp://127.0.0.1:48479/eit_ptlc/mock/"
_NODES = Path(__file__).resolve().parent.parent / "config" / "plc_nodes.yaml"


def _is_nonempty_str_array(value: object, length: int) -> bool:
    """断言辅助: value 为定长非空字符串数组。"""
    return (
        isinstance(value, (list, tuple))
        and len(value) == length
        and all(isinstance(item, str) and item.strip() for item in value)
    )


async def _run() -> int:
    node_map = load_plc_nodes(_NODES)
    server = await build_mock_server(_URL, node_map)
    failures: list[str] = []
    checks = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    async with server:
        stop = asyncio.Event()
        # 三工位各起一个 L2 FSM (默认全部动作码 -> DONE)
        fsms = [
            asyncio.create_task(run_l2_fsm(server, prefix, stop))
            for prefix in ("Sampling", "Collect")
        ]
        fsms.append(asyncio.create_task(
            run_l2_fsm(server, "Develop", stop, develop_tank_semantics=True)))
        fsms.append(asyncio.create_task(run_tank_drain_fsm(server, stop)))
        driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=5.0, subscription_period_ms=20)
        await driver.connect()
        ctrl = PlcController(driver, poll_interval=0.02, action_timeout=5.0)
        try:
            # ── 上样清洗 (动作码 20): 清洗指令数组 + 次数 ──
            clean = PUMP_PROFILES["sampling.clean"].build(
                {"wash_volume_ml": 25.0, "cleaning_count": 3},
            )
            r = await ctrl.execute("sampling", 20, clean)
            check("sampling_clean_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_clean_instructions",
                _is_nonempty_str_array(await mock_read(server, "Sampling_clean_instructions"), 2),
                str(await mock_read(server, "Sampling_clean_instructions")),
            )
            check(
                "sampling_clean_count",
                int(await mock_read(server, "Sampling_clean_count")) == 3,
                str(await mock_read(server, "Sampling_clean_count")),
            )

            # ── 上样轻清洗充液 (动作码 20, mode=1): 复用 clean 通道 ──
            flush = PUMP_PROFILES["sampling.flush"].build(
                {"flush_volume_ml": 17.0, "outer_wash_volume_ml": 5.0,
                 "spot_head_volume_ml": 3.0},
            )
            r = await ctrl.execute("sampling", 20, flush)
            check("sampling_flush_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_flush_instructions",
                _is_nonempty_str_array(await mock_read(server, "Sampling_clean_instructions"), 2),
                str(await mock_read(server, "Sampling_clean_instructions")),
            )
            check(
                "sampling_flush_count",
                int(await mock_read(server, "Sampling_clean_count")) == 1,
                str(await mock_read(server, "Sampling_clean_count")),
            )
            check(
                "sampling_flush_mode",
                int(await mock_read(server, "Sampling_clean_mode")) == 1,
                str(await mock_read(server, "Sampling_clean_mode")),
            )
            # 防陈旧: 重清洗再派发, mode 必须被显式打回 0
            clean_again = PUMP_PROFILES["sampling.clean"].build(
                {"wash_volume_ml": 25.0, "cleaning_count": 3},
            )
            r = await ctrl.execute("sampling", 20, clean_again)
            check("sampling_clean_again_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_clean_mode_reset",
                int(await mock_read(server, "Sampling_clean_mode")) == 0,
                str(await mock_read(server, "Sampling_clean_mode")),
            )
            check(
                "sampling_clean_count_reset",
                int(await mock_read(server, "Sampling_clean_count")) == 3,
                str(await mock_read(server, "Sampling_clean_count")),
            )

            # ── 上样吸液 (动作码 50): 上样指令数组; 孔位坐标由 ActionExecutor 孔位寻址块写 Target ──
            aspirate = PUMP_PROFILES["sampling.aspirate"].build(
                {"sample_volume_ml": 5.0},
            )
            r = await ctrl.execute("sampling", 50, aspirate)
            check("sampling_aspirate_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_aspirate_no_coordinate",
                int(await mock_read(server, "Sampling_X_coordinate")) == 0
                and int(await mock_read(server, "Sampling_Y_coordinate")) == 0,
                f"X={await mock_read(server, 'Sampling_X_coordinate')} Y={await mock_read(server, 'Sampling_Y_coordinate')}",
            )
            sample_cmds = await mock_read(server, "Sampling_sample_instructions")
            check(
                "sampling_aspirate_relative_instruction",
                isinstance(sample_cmds, (list, tuple)) and len(sample_cmds) == 2
                and isinstance(sample_cmds[0], str) and "P1200" in sample_cmds[0]
                and "A0" not in sample_cmds[0] and sample_cmds[1] == "",
                str(sample_cmds),
            )
            # 同动作带 air_gap_ml: [2] 填绝对 A{gap}, A50 在移孔位前先消费它建立气隔断
            aspirate_gap = PUMP_PROFILES["sampling.aspirate"].build(
                {"sample_volume_ml": 3.5, "air_gap_ml": 0.2},
            )
            r = await ctrl.execute("sampling", 50, aspirate_gap)
            check("sampling_aspirate_with_gap_done", r.state is PLCActionState.DONE, str(r))
            gap_cmds = await mock_read(server, "Sampling_sample_instructions")
            check(
                "sampling_aspirate_air_gap_slot_two",
                _is_nonempty_str_array(gap_cmds, 2)
                and "P840" in gap_cmds[0]
                and "A48" in gap_cmds[1] and "P" not in gap_cmds[1],
                str(gap_cmds),
            )
            # ── 点样后润洗吹打 (动作码 55): [1][2]以A0收尾, [3][4]以A{gap}收尾, PLC 循环第4条 ──
            rinse_mix = PUMP_PROFILES["sampling.rinse_mix"].build(
                {"rinse_volume_ml": 2.0, "mix_volume_ml": 1.5, "mix_count": 3},
            )
            r = await ctrl.execute("sampling", 55, rinse_mix)
            check("sampling_rinse_mix_done", r.state is PLCActionState.DONE, str(r))
            rinse_mix_cmds = await mock_read(server, "Sampling_rinse_mix_instructions")
            check(
                "sampling_rinse_mix_instructions",
                _is_nonempty_str_array(rinse_mix_cmds, 4)
                and all("A0" in cmd for cmd in rinse_mix_cmds[:2])
                and all("A48" in cmd for cmd in rinse_mix_cmds[2:]),
                str(rinse_mix_cmds),
            )
            check(
                "sampling_rinse_mix_count",
                int(await mock_read(server, "Sampling_rinse_mix_count")) == 3,
                str(await mock_read(server, "Sampling_rinse_mix_count")),
            )
            # ── 收集加液 (动作码 30): 单溶剂转发指令 + 重复次数 ──
            collect = PUMP_PROFILES["collect.collect"].build(
                {"solvent_volume_ml": 2.0, "liquid_repeat_count": 4},
            )
            r = await ctrl.execute("collect", 30, collect)
            check("collect_collect_done", r.state is PLCActionState.DONE, str(r))
            fwd = await mock_read(server, "collect_forward_instructions")
            check(
                "collect_forward_and_count",
                isinstance(fwd, str) and fwd.strip()
                and int(await mock_read(server, "collect_count")) == 4,
                f"fwd={fwd!r} count={await mock_read(server, 'collect_count')}",
            )

            # ── 展缸上液 (动作码 22): 目标缸 + 转发指令 + 上液次数 (不写 Mode_Flag/rinse_count) ──
            fill = PUMP_PROFILES["develop.fill"].build(
                {"target_tank": 3, "solvent_volume_ml": 2.0,
                 "solvent_ratio_1": 1.0, "up_liquid_repeat_count": 1},
            )
            check(
                "develop_fill_channel_keys",
                set(fill) == {"Expand_Target_Tank", "Expand_forward_instructions", "Expand_up_liquid_count"},
                str(sorted(fill)),
            )
            r = await ctrl.execute("develop", 22, fill)
            check("develop_fill_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_fill_values",
                int(await mock_read(server, "Expand_Target_Tank")) == 3
                and str(await mock_read(server, "Expand_forward_instructions")).strip() != ""
                and int(await mock_read(server, "Expand_up_liquid_count")) == 1,
                "目标缸/转发指令/上液次数 校验",
            )

            # ── 展缸清洗管路 (动作码 20): 润洗模式 line -> Mode_Flag=1 ──
            rinse = PUMP_PROFILES["develop.clean_line"].build(
                {"rinse_mode": "line", "target_tank": 1, "solvent_volume_ml": 2.0,
                 "solvent_ratio_1": 1.0, "rinse_repeat_count": 2},
            )
            check(
                "develop_rinse_channel_keys",
                set(rinse) == {"Expand_Target_Tank", "Expand_Mode_Flag",
                               "Expand_forward_instructions", "Expand_rinse_count"},
                str(sorted(rinse)),
            )
            r = await ctrl.execute("develop", 20, rinse)
            check("develop_rinse_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_rinse_mode_flag",
                int(await mock_read(server, "Expand_Mode_Flag")) == 1
                and int(await mock_read(server, "Expand_rinse_count")) == 2,
                f"mode={await mock_read(server, 'Expand_Mode_Flag')} count={await mock_read(server, 'Expand_rinse_count')}",
            )

            # ── 展缸排液 v2 (动作码 50): 全相位 50→55→56→98 + 时长通道写入 (spec 2026-07-14) ──
            drain_channels = {
                "Expand_Target_Tank": 3,
                "Tank_Drain_S": 0.05, "Tank_Drain_Cap_S": 1.0,
                "Tank_Blow_S": 0.05, "Tank_Dry_S": 0.05,
            }
            r = await ctrl.execute("develop", 50, drain_channels)
            check("develop_drain_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_drain_duration_channels",
                abs(float(await mock_read(server, "Tank_Drain_S")) - 0.05) < 1e-9
                and abs(float(await mock_read(server, "Tank_Dry_S")) - 0.05) < 1e-9,
                f"Drain_S={await mock_read(server, 'Tank_Drain_S')} Dry_S={await mock_read(server, 'Tank_Dry_S')}",
            )
            tanks = await mock_read(server, "Tank_State")
            check("develop_drain_state_98", int(tanks[2]) == 98, str(tanks))
            check(
                "develop_drain_caphit_false",
                not bool((await mock_read(server, "Tank_Drain_CapHit"))[2]),
                str(await mock_read(server, "Tank_Drain_CapHit")),
            )

            # ── 排液释放 (动作码 51): 98 → 0 ──
            r = await ctrl.execute("develop", 51, {"Expand_Target_Tank": 3})
            check("develop_release_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_release_state_0",
                int((await mock_read(server, "Tank_State"))[2]) == 0,
                str(await mock_read(server, "Tank_State")),
            )

            # ── Cap 挟持: 组1 废液线持续有液 → Phase A 走硬上限 + CapHit 锁存 ──
            server._eit_drain_wet_groups = {1}
            drain_cap = dict(drain_channels)
            drain_cap["Expand_Target_Tank"] = 2
            drain_cap["Tank_Drain_Cap_S"] = 0.2
            r = await ctrl.execute("develop", 50, drain_cap)
            check("develop_drain_cap_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_drain_cap_hit",
                bool((await mock_read(server, "Tank_Drain_CapHit"))[1])
                and int((await mock_read(server, "Tank_State"))[1]) == 98,
                f"CapHit={await mock_read(server, 'Tank_Drain_CapHit')} State={await mock_read(server, 'Tank_State')}",
            )
            server._eit_drain_wet_groups = set()
            r = await ctrl.execute("develop", 51, {"Expand_Target_Tank": 2})
            check("develop_release_after_cap", r.state is PLCActionState.DONE, str(r))

            # ── 非法态拒绝: 缸4 置 10 (Prepping) → 50 REJECT 501 / 51 REJECT 511 ──
            tanks = list(await mock_read(server, "Tank_State"))
            tanks[3] = 10
            await mock_write(server, "Tank_State", tanks)
            try:
                await ctrl.execute("develop", 50, {"Expand_Target_Tank": 4})
                check("develop_drain_reject_501", False, "缸态 10 未被拒绝")
            except PLCActionError as e:
                check(
                    "develop_drain_reject_501",
                    e.result.state is PLCActionState.REJECTED and e.result.error_code == 501,
                    str(e.result),
                )
            try:
                await ctrl.execute("develop", 51, {"Expand_Target_Tank": 4})
                check("develop_release_reject_511", False, "缸态 10 未被拒绝")
            except PLCActionError as e:
                check(
                    "develop_release_reject_511",
                    e.result.state is PLCActionState.REJECTED and e.result.error_code == 511,
                    str(e.result),
                )
            tanks[3] = 0
            await mock_write(server, "Tank_State", tanks)

            # ── 幂等直通: 缸5 直接置 98 → code 50 不再排液直接 DONE; code 51 从 99 也可释放 ──
            tanks = list(await mock_read(server, "Tank_State"))
            tanks[4] = 98
            await mock_write(server, "Tank_State", tanks)
            r = await ctrl.execute("develop", 50, {"Expand_Target_Tank": 5})
            check("develop_drain_idempotent_98", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_drain_idempotent_state_kept",
                int((await mock_read(server, "Tank_State"))[4]) == 98,
                str(await mock_read(server, "Tank_State")),
            )
            tanks = list(await mock_read(server, "Tank_State"))
            tanks[4] = 99
            await mock_write(server, "Tank_State", tanks)
            r = await ctrl.execute("develop", 51, {"Expand_Target_Tank": 5})
            check("develop_release_legacy_99", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_release_legacy_99_state_0",
                int((await mock_read(server, "Tank_State"))[4]) == 0,
                str(await mock_read(server, "Tank_State")),
            )
        finally:
            stop.set()
            for fsm in fsms:
                await fsm
            await driver.disconnect()

    print(f"\n共 {checks} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
