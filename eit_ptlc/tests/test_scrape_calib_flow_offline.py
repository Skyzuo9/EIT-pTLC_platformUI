"""刮痕标定 operation — VM 端到端离线 (真 photoscrape_scrape_calib.yaml + 伪执行器)。

关键钉子:
    1. 首门取消 → 不落任何气缸 (板未夹持, 无需释放)
    2. action=go 一轮 = cnc_path → 块写 → pass 循环 → 补拍 → scraped_overlay, 顺序不乱
    3. action=finish → 退环收尾, 气缸**配对释放**(板不留压头下)
    4. 面板硬闸走的就是 finish 这条路 (判据不通过时不刮下一轮, 但仍干净放板)
    5. 任意动作失败 → catch 先释放两个气缸再抛, 板绝不卡在压头下
    6. 建帧用 before=after=同一张 (空白板无带, 省一次拍照)
    7. 取桶门: 翻料到位 → 松接粉桶定位 → **等人取桶** → 才复位翻料缸; 任何应答都复位;
       中止路径不设门 (无人值守也必须收敛)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_debug_offline import wait_status

_CALIB = Path("eit_ptlc/config/operation/03_photoscrape/photoscrape_scrape_calib.yaml")

_CNC = {"g_sx": [1.0], "g_sy": [2.0], "g_cx": [3.0], "g_cy": [4.0],
        "g_scrape_feed": 800, "pass_count": 1, "pass_z_list": [21.5],
        "start_x_mm": 1.0, "start_y_mm": 2.0}
_VIS = {"ok": False, "reason": "no_bands", "message": "空白板无带(预期)",
        "summary_path": "vision_output/CAL/summary.json", "case_dir": "vision_output/CAL",
        "band_ids": [], "annotated_url": ""}


class CalibExecutor:
    def __init__(self, fail_action: str | None = None, pass_z: list[float] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._fail = fail_action
        self._pass_z = pass_z

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append((name, dict(params or {})))
        if name == self._fail:
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="测试注入失败", result={})
        result: dict = {}
        if name == "photoscrape.capture":
            result = {"image_path": f"/tmp/{params.get('filename', 'x.jpg')}"}
        elif name == "photoscrape.analyze":
            result = dict(_VIS)
        elif name == "photoscrape.cnc_path":
            result = dict(_CNC)
            if self._pass_z is not None:
                result.update(pass_count=len(self._pass_z), pass_z_list=list(self._pass_z))
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=result)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)


def _drive(replies, terminal, executor=None, start_vars=None):
    async def run():
        ex = executor or CalibExecutor()
        events: list[dict] = []
        c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
        s = await c.start(yaml.safe_load(_CALIB.read_text(encoding="utf-8")),
                          start_vars or {"sample_id": "CAL", "save_dir": "/tmp/cal"},
                          mode_run="run")
        rid, replied = s["run_id"], set()
        for payload in replies:
            assert await wait_status(c, rid, "WAITING_HUMAN"), c.state(rid)
            req = [e for e in events
                   if e["type"] == "vm_human_request" and e["req_id"] not in replied][-1]
            replied.add(req["req_id"])
            await c.human_reply(rid, req["req_id"], payload)
        assert await wait_status(c, rid, terminal), c.state(rid)
        return ex
    return asyncio.run(run())


_OK = {"choice": "ok", "values": {}}
_GO = {"choice": "ok", "values": {"calib_summary_path": "vision_output/CAL_calib_r1/summary.json",
                                  "action": "go"}}
_GO2 = {"choice": "ok", "values": {"calib_summary_path": "vision_output/CAL_calib_r2/summary.json",
                                   "action": "go"}}
_FINISH = {"choice": "ok", "values": {"action": "finish"}}
_TAKEN = {"choice": "ok", "values": {}}    # 取桶门: 已取下接粉桶


# --------------------------------------------------------------------------
# 首门
# --------------------------------------------------------------------------

def test_first_gate_cancel_touches_no_cylinder():
    """取消时板还没夹持 —— 不得落任何气缸, 也不必释放。"""
    ex = _drive([{"choice": "cancel", "values": {}}], "ERROR")

    assert ex.count("photoscrape.locate_cylinder") == 0
    assert ex.count("photoscrape.press_cylinder") == 0


def test_first_gate_ok_clamps_then_builds_frame():
    """确认后: 先落定位+下压, 再拍一张空白板建帧 (before=after=同一张, 省一次拍照)。"""
    ex = _drive([_OK, _FINISH, _TAKEN], "DONE")
    names = ex.names()

    assert names.index("photoscrape.locate_cylinder") < names.index("photoscrape.capture")
    assert names.index("photoscrape.press_cylinder") < names.index("photoscrape.capture")
    assert ex.count("photoscrape.capture") == 1          # 建帧只拍一张
    analyze = [p for n, p in ex.calls if n == "photoscrape.analyze"][0]
    assert analyze["before_path"] == analyze["after_path"], "建帧应复用同一张, 不多拍"


def test_prepare_actions_run_before_clamping():
    """2026-07-26 粉末飞溅复盘: init/cam_x335/locator_a 必须在落气缸之前, 顺序不可乱。

    init 清上一轮 A41 留下的旋转气缸(翻料位)残留; cam_x335 满足 A41 翻料的 9X>330 互锁;
    locator_a 是接粉桶定位气缸 %QX7.5 的唯一驱动者。
    """
    ex = _drive([_OK, _FINISH, _TAKEN], "DONE")
    names = ex.names()

    for act in ("photoscrape.init", "photoscrape.cam_x335", "staging_a.locator_a"):
        assert act in names, f"缺准备动作 {act}"
    assert names.index("photoscrape.init") < names.index("photoscrape.cam_x335")
    assert names.index("photoscrape.cam_x335") < names.index("staging_a.locator_a")
    assert names.index("staging_a.locator_a") < names.index("photoscrape.locate_cylinder")
    # 接粉桶定位配对: 开头 true, 收尾 false
    locator = [p for n, p in ex.calls if n == "staging_a.locator_a"]
    assert locator == [{"target": True}, {"target": False}]


def test_finish_stops_rotation_cylinder():
    """收尾必须复位旋转气缸 —— A41 会把它置 TRUE(翻料), 不清则永停动点, 下轮在'已翻倒'状态下刮。"""
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    names = ex.names()

    assert "photoscrape.retr_stoprot" in names
    assert names.index("photoscrape.scrape_finish") < names.index("photoscrape.retr_stoprot")


def test_finish_waits_for_flip_before_resetting_it():
    """开翻料 → **等到位** → 才复位。

    ⚠️ 2026-07-27 真机复盘的回归钉子: A41/A52 都是开环(同扫描周期返回 DONE, 不等气缸反馈),
       紧挨着调等于毫秒级一开一关, 缸走不完行程 —— 粉没倒进桶, 后续会掉出去。
       这条钉住"中间必须夹着 wait_rot", 防止日后图省事又把它删回去。
    """
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    names = ex.names()

    assert "photoscrape.wait_rot" in names, "收尾缺 wait_rot: 翻料缸会被瞬间复位, 等于没翻"
    fin = names.index("photoscrape.scrape_finish")
    wait = names.index("photoscrape.wait_rot")
    stop = names.index("photoscrape.retr_stoprot")
    assert fin < wait < stop, f"wait_rot 必须夹在开翻料与复位之间: {names}"
    # 等的是动点(翻倒), 不是原点 —— 等错端会立刻满足, 退化成没等
    assert [p for n, p in ex.calls if n == "photoscrape.wait_rot"][0]["target"] == "extend"


# --------------------------------------------------------------------------
# 取桶门 (2026-07-28 操作员反馈的回归钉子)
# --------------------------------------------------------------------------
# 现场: 翻料后瞬间翻回, 人根本来不及取接粉桶 —— 翻料等于白翻; 且桶被定位气缸夹着取不下来。
# 钉住三件事: ① 门开着时翻料保持(不复位) ② 门前必须先松桶定位气缸 ③ 任何应答都复位。


def test_bucket_gate_holds_flip_until_operator_confirms():
    """翻料到位 → 松桶定位 → **停在取桶门**(不复位); 确认后才 retr_stoprot。"""
    async def run():
        ex = CalibExecutor()
        events: list[dict] = []
        c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
        s = await c.start(yaml.safe_load(_CALIB.read_text(encoding="utf-8")),
                          {"sample_id": "CAL", "save_dir": "/tmp/cal"}, mode_run="run")
        rid, replied = s["run_id"], set()

        async def reply(payload):
            assert await wait_status(c, rid, "WAITING_HUMAN"), c.state(rid)
            req = [e for e in events
                   if e["type"] == "vm_human_request" and e["req_id"] not in replied][-1]
            replied.add(req["req_id"])
            await c.human_reply(rid, req["req_id"], payload)

        await reply(_OK)
        await reply(_FINISH)
        # 第三门 = 取桶门: 翻料已开、已等到位、桶定位已松, 但**还没有**复位翻料缸
        assert await wait_status(c, rid, "WAITING_HUMAN"), c.state(rid)
        names = ex.names()
        assert names.index("photoscrape.scrape_finish") < names.index("photoscrape.wait_rot")
        assert {"target": False} in [p for n, p in ex.calls if n == "staging_a.locator_a"], \
            "取桶门前必须松接粉桶定位气缸, 否则桶被夹着取不下来"
        assert "photoscrape.retr_stoprot" not in names, "人未确认取桶就复位翻料 = 白翻"

        await reply(_TAKEN)
        assert await wait_status(c, rid, "DONE"), c.state(rid)
        assert "photoscrape.retr_stoprot" in ex.names()
        return ex
    asyncio.run(run())


def test_bucket_gate_cancel_still_resets_rotation():
    """取桶门点取消也必须复位翻料缸 —— 缸悬在动点会让下一轮在'已翻倒'状态下刮。"""
    ex = _drive([_OK, _FINISH, {"choice": "cancel", "values": {}}], "DONE")
    names = ex.names()

    assert "photoscrape.retr_stoprot" in names
    assert names.index("photoscrape.wait_rot") < names.index("photoscrape.retr_stoprot")


def test_bucket_locator_release_sits_between_flip_wait_and_reset():
    """松桶定位夹在 wait_rot 与 retr_stoprot 之间: 翻料到位才松(粉先倒完), 复位前已可取桶。"""
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    seq = [(n, tuple(sorted(p.items()))) for n, p in ex.calls]
    release_i = seq.index(("staging_a.locator_a", (("target", False),)))
    names = ex.names()

    assert names.index("photoscrape.wait_rot") < release_i < names.index("photoscrape.retr_stoprot")


# --------------------------------------------------------------------------
# 轮次门
# --------------------------------------------------------------------------

def test_one_round_sequence_is_ordered():
    """一轮 = 算路径 → 块写 → 写切深+刮 → 补拍 → 叠加, 顺序不可乱。"""
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    names = ex.names()

    seq = ["photoscrape.cnc_path", "photoscrape.write_cnc_path",
           "photoscrape.write_pass_z", "photoscrape.scrape",
           "photoscrape.scraped_overlay"]
    idx = [names.index(n) for n in seq]
    assert idx == sorted(idx), f"轮内顺序错乱: {names}"


def test_round_overlay_targets_that_rounds_workspace():
    """叠加必须落在**本轮**工作区 —— 落错目录则该轮测不了。"""
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    ov = [p for n, p in ex.calls if n == "photoscrape.scraped_overlay"][0]

    assert ov["summary_path"] == "vision_output/CAL_calib_r1/summary.json"


def test_two_rounds_use_distinct_workspaces():
    """两轮各自的 summary 不同 —— 共用目录会让 preview_payload/刮后帧互相覆盖。"""
    ex = _drive([_OK, _GO, _GO2, _FINISH, _TAKEN], "DONE")
    ovs = [p["summary_path"] for n, p in ex.calls if n == "photoscrape.scraped_overlay"]

    assert ovs == ["vision_output/CAL_calib_r1/summary.json",
                   "vision_output/CAL_calib_r2/summary.json"]
    assert ex.count("photoscrape.scrape") == 2


def test_finish_releases_cylinders_in_pairs():
    """收尾必须配对释放下压+定位 —— 板不留压头下。"""
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE")
    press = [p for n, p in ex.calls if n == "photoscrape.press_cylinder"]
    locate = [p for n, p in ex.calls if n == "photoscrape.locate_cylinder"]

    assert press == [{"pressed": True}, {"pressed": False}]
    assert locate == [{"clamped": True}, {"clamped": False}]
    assert ex.count("photoscrape.scrape_finish") == 1


def test_hard_gate_path_scrapes_nothing_but_still_releases():
    """面板硬闸(判据不通过)走 finish: 一刀不刮, 但气缸照样配对释放。"""
    ex = _drive([_OK, _FINISH, _TAKEN], "DONE")

    assert ex.count("photoscrape.scrape") == 0
    assert {"pressed": False} in [p for n, p in ex.calls if n == "photoscrape.press_cylinder"]
    assert {"clamped": False} in [p for n, p in ex.calls if n == "photoscrape.locate_cylinder"]


def test_unknown_action_is_treated_as_finish():
    """空/未知指令一律收敛退环 —— 不得当作 go 盲刮。"""
    ex = _drive([_OK, {"choice": "ok", "values": {"action": "???"}}, _TAKEN], "DONE")

    assert ex.count("photoscrape.scrape") == 0


# --------------------------------------------------------------------------
# 分刀 (num_passes > 1)
# --------------------------------------------------------------------------
# 标定跟随全局 num_passes(与生产同工艺, 否则标出来的 plate_origin 含不同的刀具链分量),
# 所以生产一旦调大分刀次数, 标定这条循环也必须跟着可靠。现役恒为 1, 从未跑过。

_PASS_Z = [21.5, 21.83, 22.17]


def test_multi_pass_alternates_write_z_and_scrape_in_order():
    """一轮 N 刀 = 严格交替的 (写本层 Z → 刮一刀) × N, Z 递增下刀。

    若先连写 3 层 Z 再刮 3 次, 前两刀会全刮在最深那层, 分刀失效且首刀就吃满切深。
    """
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE", executor=CalibExecutor(pass_z=_PASS_Z))
    seq = [(n, p) for n, p in ex.calls
           if n in ("photoscrape.write_pass_z", "photoscrape.scrape")]

    assert [n for n, _ in seq] == ["photoscrape.write_pass_z", "photoscrape.scrape"] * 3, \
        f"未严格交替: {[n for n, _ in seq]}"
    assert [p["z"] for n, p in seq if n == "photoscrape.write_pass_z"] == _PASS_Z


def test_multi_pass_writes_path_block_once_per_round():
    """块写在 pass 循环外: 每轮只写 1 次 4 数组; 两轮共 2 次, 刮 6 刀。"""
    ex = _drive([_OK, _GO, _GO2, _FINISH, _TAKEN], "DONE", executor=CalibExecutor(pass_z=_PASS_Z))

    assert ex.count("photoscrape.write_cnc_path") == 2      # 每轮一次, 与轮数同步
    assert ex.count("photoscrape.scrape") == 6              # 2 轮 × 3 刀
    assert ex.count("photoscrape.scraped_overlay") == 2     # 补拍仍是每轮一次, 不随刀次


def test_multi_pass_captures_reconcile_frame_only_after_last_pass():
    """刮后对账帧必须在**最后一刀**之后才拍 —— 中间刀拍会把没刮透的槽当成结果去测。

    注意用 calib_scraped.jpg 这次拍照定位, 不能用 cam_photopos: 它在开头建帧时也调过一次。
    """
    ex = _drive([_OK, _GO, _FINISH, _TAKEN], "DONE", executor=CalibExecutor(pass_z=_PASS_Z))
    names = ex.names()
    seq = [(n, p) for n, p in ex.calls]

    last_scrape = len(names) - 1 - names[::-1].index("photoscrape.scrape")
    reconcile = [i for i, (n, p) in enumerate(seq)
                 if n == "photoscrape.capture" and p.get("filename") == "calib_scraped.jpg"]
    assert len(reconcile) == 1, f"对账帧应只拍一次(不随刀次), 实拍 {len(reconcile)} 次"
    assert reconcile[0] > last_scrape, "对账帧早于最后一刀, 测的是没刮透的槽"
    assert names.index("photoscrape.scraped_overlay") > last_scrape


# --------------------------------------------------------------------------
# 失败路径
# --------------------------------------------------------------------------

def test_scrape_failure_releases_plate_before_raising():
    """刮取失败: catch 先释放两个气缸再抛, 板绝不卡在压头下。"""
    ex = _drive([_OK, _GO], "ERROR", executor=CalibExecutor(fail_action="photoscrape.scrape"))
    press = [p for n, p in ex.calls if n == "photoscrape.press_cylinder"]
    locate = [p for n, p in ex.calls if n == "photoscrape.locate_cylinder"]

    assert {"pressed": False} in press
    assert {"clamped": False} in locate


def test_failure_path_also_stops_vacuum_and_motor():
    """catch 必须先调 scrape_finish 再放板 —— 否则 A40 开的真空阀与吸粉电机永久保持 TRUE。"""
    ex = _drive([_OK, _GO], "ERROR", executor=CalibExecutor(fail_action="photoscrape.scrape"))
    seq = [(n, tuple(sorted(p.items()))) for n, p in ex.calls]

    assert "photoscrape.scrape_finish" in ex.names(), "异常路径漏了收尾, 真空/电机会一直开着"
    finish_i = ex.names().index("photoscrape.scrape_finish")
    release_i = seq.index(("photoscrape.press_cylinder", (("pressed", False),)))
    assert finish_i < release_i, "必须先关真空/电机再放板"


def test_failure_path_also_waits_for_the_flip():
    """异常路径同样要等翻料到位 —— 中止时桶里往往正有粉, 更不能白翻。"""
    ex = _drive([_OK, _GO], "ERROR", executor=CalibExecutor(fail_action="photoscrape.scrape"))
    names = ex.names()

    assert "photoscrape.wait_rot" in names, "catch 里漏了 wait_rot: 翻料缸瞬间被复位"
    fin = names.index("photoscrape.scrape_finish")
    wait = names.index("photoscrape.wait_rot")
    stop = names.index("photoscrape.retr_stoprot")
    assert fin < wait < stop, f"catch 里 wait_rot 位置错: {names}"


def test_finish_action_failure_still_releases_plate():
    """收尾动作自己失败也不能挡住放板 —— 板不留压头下优先于输出复位。"""
    ex = _drive([_OK, _GO, _FINISH], "ERROR",
                executor=CalibExecutor(fail_action="photoscrape.scrape_finish"))

    assert {"pressed": False} in [p for n, p in ex.calls if n == "photoscrape.press_cylinder"]
    assert {"clamped": False} in [p for n, p in ex.calls if n == "photoscrape.locate_cylinder"]
    assert {"target": False} in [p for n, p in ex.calls if n == "staging_a.locator_a"]


def test_overlay_failure_is_not_swallowed():
    """叠加失败不吞: 标定的全部依据就是这张回放帧, 拿不到就不该继续下一轮。"""
    ex = _drive([_OK, _GO], "ERROR",
                executor=CalibExecutor(fail_action="photoscrape.scraped_overlay"))

    assert {"pressed": False} in [p for n, p in ex.calls if n == "photoscrape.press_cylinder"]
