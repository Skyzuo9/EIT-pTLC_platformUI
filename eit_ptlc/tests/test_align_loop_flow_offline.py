"""对位内环 — VM 端到端离线 (真 photoscrape_align_loop.yaml + 伪执行器)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_debug_offline import wait_status

_LOOP = Path("eit_ptlc/config/operation/03_photoscrape/photoscrape_align_loop.yaml")
_TOOL = Path("eit_ptlc/config/operation/03_photoscrape/photoscrape_tool_align.yaml")
READOUT = {"x_mm": 91.0, "y_mm": -75.0, "z_mm": 0.0, "origin_x_mm": 91.24, "origin_y_mm": -75.2,
           "inspect_z_mm": 18.0, "dx_vs_origin_mm": -0.24, "dy_vs_origin_mm": 0.2, "text": "T"}


class AlignExecutor:
    def __init__(self, fail_move=False, fail_readout_after=None):
        # fail_readout_after=N: 第 N 次 align_readout 起返回 REJECTED (D2 内环失败注入; readout 不在
        # 内层 try, 冒泡到 D1 外层 catch → align_home → ALIGN_FAILED, 比 go_origin 分支注入更可靠)。
        self.calls, self._fail = [], fail_move
        self._fail_readout_after = fail_readout_after
        self._readout_n = 0

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append((name, dict(params or {})))
        if name == "photoscrape.align_move" and self._fail:
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="软限位拒动(测试注入)", result={})
        if name == "photoscrape.align_readout":
            self._readout_n += 1
            if self._fail_readout_after is not None and self._readout_n >= self._fail_readout_after:
                return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                    accepted=False, message="回读失败(测试注入)", result={})
        res = READOUT if name == "photoscrape.align_readout" else {}
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=res)


def _drive(replies, terminal, executor=None, start_vars=None):
    async def run():
        ex = executor or AlignExecutor()
        events = []
        c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
        s = await c.start(yaml.safe_load(_LOOP.read_text(encoding="utf-8")),
                          start_vars or {}, mode_run="run")
        rid, replied = s["run_id"], set()
        for payload in replies:
            assert await wait_status(c, rid, "WAITING_HUMAN")
            req = [e for e in events if e["type"] == "vm_human_request" and e["req_id"] not in replied][-1]
            replied.add(req["req_id"])
            await c.human_reply(rid, req["req_id"], payload)
        assert await wait_status(c, rid, terminal), c.state(rid)
        return ex
    return asyncio.run(run())


def _drive_tool(replies, terminal, executor=None, start_vars=None):
    """驱动 D2 对刀业务 photoscrape_tool_align.yaml (主文档), resolve_script 载入 D1 真子脚本。"""
    async def run():
        ex = executor or AlignExecutor()
        events = []
        c = VmController(
            executor=ex, res_gate=ResourceGate(), event_sink=events.append,
            resolve_script=lambda n: yaml.safe_load(
                Path(f"eit_ptlc/config/operation/03_photoscrape/{n}.yaml").read_text(encoding="utf-8")))
        s = await c.start(yaml.safe_load(_TOOL.read_text(encoding="utf-8")),
                          start_vars or {}, mode_run="run")
        rid, replied = s["run_id"], set()
        for payload in replies:
            assert await wait_status(c, rid, "WAITING_HUMAN")
            req = [e for e in events if e["type"] == "vm_human_request" and e["req_id"] not in replied][-1]
            replied.add(req["req_id"])
            await c.human_reply(rid, req["req_id"], payload)
        assert await wait_status(c, rid, terminal), c.state(rid)
        return ex
    return asyncio.run(run())


def _names(ex):
    return [c[0] for c in ex.calls]


def test_finish_immediately_homes():
    ex = _drive([{"choice": "finish", "values": {}}], "DONE")
    assert _names(ex) == ["photoscrape.align_readout", "photoscrape.align_home"]


def test_go_origin_lifts_z_then_moves_then_loop():
    ex = _drive([{"choice": "go_origin", "values": {}}, {"choice": "finish", "values": {}}], "DONE")
    n = _names(ex)
    assert n[:3] == ["photoscrape.align_readout", "photoscrape.align_z", "photoscrape.align_move"]
    mv = [c for c in ex.calls if c[0] == "photoscrape.align_move"][0][1]
    assert mv == {"x_mm": 91.24, "y_mm": -75.2}
    assert n[-1] == "photoscrape.align_home"


def test_jog_lifts_z_then_adds_delta_to_actpos():
    ex = _drive([{"choice": "jog", "values": {}},
                 {"choice": "ok", "values": {"dx_mm": "0.5", "dy_mm": "-0.3"}},
                 {"choice": "finish", "values": {}}], "DONE")
    n = _names(ex)
    # B1修正: jog 先 align_z(0) 再 align_move
    assert n.index("photoscrape.align_z") < n.index("photoscrape.align_move")
    z = [c for c in ex.calls if c[0] == "photoscrape.align_z"][0][1]
    assert z == {"z_mm": 0.0}
    mv = [c for c in ex.calls if c[0] == "photoscrape.align_move"][0][1]
    assert round(mv["x_mm"], 3) == 91.5 and round(mv["y_mm"], 3) == -75.3


def test_rejected_move_returns_to_gate_not_fault():
    ex = _drive([{"choice": "go_origin", "values": {}}, {"choice": "finish", "values": {}}],
                "DONE", executor=AlignExecutor(fail_move=True))
    assert _names(ex)[-1] == "photoscrape.align_home"   # 拒动被分支 catch 吞掉, 环存活到 finish


def test_go_start_without_valid_start_stays_in_loop():
    ex = _drive([{"choice": "go_start", "values": {}}, {"choice": "finish", "values": {}}], "DONE")
    assert "photoscrape.align_move" not in _names(ex)


# ---- D2 独立对刀业务 photoscrape_tool_align (spec 0716 §6 D2) --------------------------


def test_tool_align_full_flow_pairs_cylinders():
    ex = _drive_tool([{"choice": "ok", "values": {}},        # 首门确认
                      {"choice": "finish", "values": {}}],   # 内环直接结束
                     "DONE")
    n = _names(ex)
    assert n.count("photoscrape.press_cylinder") == 2 and n.count("photoscrape.locate_cylinder") == 2
    press_args = [c[1]["pressed"] for c in ex.calls if c[0] == "photoscrape.press_cylinder"]
    assert press_args == [True, False]
    locate_args = [c[1]["clamped"] for c in ex.calls if c[0] == "photoscrape.locate_cylinder"]
    assert locate_args == [True, False]
    assert "photoscrape.align_home" in n


def test_tool_align_cancel_at_confirm_releases_nothing():
    # 裁定③: confirm 取消回复 payload 以 HitlModal 行为为准 = {"choice": "cancel", "values": {}}。
    # 取消在首门抛出 → 未夹持任何气缸 → 终态 ERROR。
    ex = _drive_tool([{"choice": "cancel", "values": {}}], "ERROR")
    n = _names(ex)
    assert "photoscrape.locate_cylinder" not in n
    assert "photoscrape.press_cylinder" not in n


def test_tool_align_inner_failure_releases_and_aborts():
    # 裁定②: 首门 ok → 内环第一门 go_origin(正常) → 第二次 readout REJECTED (不在内层 try) →
    # 冒泡到 D1 外层 catch → align_home → ALIGN_FAILED → D2 catch 释放气缸 → TOOL_ALIGN_ABORTED → ERROR。
    ex = _drive_tool([{"choice": "ok", "values": {}}, {"choice": "go_origin", "values": {}}],
                     "ERROR", executor=AlignExecutor(fail_readout_after=2))
    n = _names(ex)
    # 硬断言: 气缸配对释放 (夹→放)
    press_args = [c[1]["pressed"] for c in ex.calls if c[0] == "photoscrape.press_cylinder"]
    assert press_args == [True, False]
    # 软断言: 释放 press(False) 之前已回零 align_home (刀头绝不悬板上方)
    home_i = n.index("photoscrape.align_home")
    last_press_i = len(n) - 1 - n[::-1].index("photoscrape.press_cylinder")
    assert home_i < last_press_i
