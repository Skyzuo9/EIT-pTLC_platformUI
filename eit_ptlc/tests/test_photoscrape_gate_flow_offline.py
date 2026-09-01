"""拍照刮板统一下发门 — VM 端到端离线驱动。

用真 VM 跑**真** photoscrape_process.yaml(伪执行器给 analyze/cnc_path 结构化结果), 验证:
  - auto 视觉成功 → 无门直发; auto 视觉失败 → **降级人工**(1b, 仍进门)。
  - manual → 统一门(choose): 下发 / 手绘 / 跳过 / 中止 各分支控制流正确。
  - 门事件带 options + context(供前端渲染按钮/取板参照)。
  - 中止分支释放下压+定位气缸(板不卡压头下)后 raise。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_align_loop_flow_offline import READOUT
from eit_ptlc.tests.test_vm_debug_offline import wait_status

_PROC = Path("eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml")

# start_x_mm/start_y_mm: B7 起 cnc 结果带路径首点标量 (= g_sx[0]/g_sy[0]); D3 对位内环走起点靠它 (VM 无数组下标)
CNC = {"g_sx": [1.0] * 400, "g_sy": [1.0] * 400, "g_cx": [1.0] * 400, "g_cy": [1.0] * 400,
       "g_scrape_feed": 800, "pass_count": 1, "pass_z_list": [8.0],
       "start_x_mm": 1.0, "start_y_mm": 1.0,
       "preview_url": "/api/vision/image/x/band_01_cnc_preview.png"}
FIXED_SUMMARY = "/fixed/summary.json"
ANALYZE_OK = {"ok": True, "reason": "ok", "message": "", "summary_path": "/x/summary.json",
              "case_dir": "/x", "band_ids": ["band_01"], "annotated_url": "/api/vision/image/x.png"}
ANALYZE_FAIL = {"ok": False, "reason": "no_bands", "message": "未检出条带", "summary_path": "/x/summary.json",
                "case_dir": "/x", "band_ids": [], "annotated_url": "/api/vision/image/x.png"}


class PhotoExecutor:
    """伪执行器: analyze/cnc_path 给结构化结果, 其余给 DONE(capture 带 image_path)。"""

    def __init__(self, analyze=ANALYZE_OK):
        self.calls: list[tuple] = []
        self._analyze = analyze

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        self.calls.append((name, params))
        if name == "photoscrape.analyze":
            res = self._analyze
        elif name == "photoscrape.cnc_path":
            res = {**CNC, "pass_count": 0, "pass_z_list": []} if params.get("placeholder") else CNC
        elif name == "photoscrape.align_readout":
            res = READOUT               # D3 对位内环回读 (align_z/move/home 走 else 回 DONE)
        else:
            res = {"echo": params, "image_path": "/x/after.jpg"}
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=res)


class MultiPassExecutor(PhotoExecutor):
    """cnc_path 返回 3 层 pass_z_list, 逼 VM 真正走多刀循环(现役 num_passes=1 走不到)。"""

    PASS_Z = [8.0, 8.33, 8.67]

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        if name == "photoscrape.cnc_path" and not params.get("placeholder"):
            self.calls.append((name, params))
            return ActionResult(
                action=name, request_id="x", status=ActionStatus.DONE, accepted=True, message="ok",
                result={**CNC, "pass_count": len(self.PASS_Z), "pass_z_list": list(self.PASS_Z)})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


class SketchCncFailExecutor(PhotoExecutor):
    """手绘重试的 cnc_path 失败 (REJECTED, res.ok=False): 复现审阅 #1 的触发条件。

    被拒动作 result 默认 {}; 用于验证"失败动作不得污染它的 assign 目标"这条 VM 不变量 ——
    失败重试不得把上一份有效的 cnc 冲空 (否则守卫仍 true, 下发喂空 dict → 卡板)。
    """

    def __init__(self, analyze=ANALYZE_OK, bad_summary="/bad/summary.json"):
        super().__init__(analyze)
        self._bad = bad_summary

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        if name == "photoscrape.cnc_path" and params.get("summary_path") == self._bad:
            self.calls.append((name, params))
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="几何非法(测试注入)", result={})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


def _doc():
    return yaml.safe_load(_PROC.read_text(encoding="utf-8"))


def _resolve_ps(n):
    # D3 align 分支 run_script 靠它把 photoscrape_align_loop 真子脚本载进 VM
    return yaml.safe_load(
        Path(f"eit_ptlc/config/operation/03_photoscrape/{n}.yaml").read_text(encoding="utf-8"))


def _names(ex):
    return [c[0] for c in ex.calls]


def _latest_req(events, replied):
    reqs = [e for e in events if e["type"] == "vm_human_request" and e["req_id"] not in replied]
    return reqs[-1] if reqs else None


async def _drive(mode, replies, terminal, analyze=ANALYZE_OK, executor=None, extra_vars=None,
                 resolve_script=None):
    ex = executor if executor is not None else PhotoExecutor(analyze)
    events: list[dict] = []
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append,
                     resolve_script=resolve_script)
    start_vars = {"mode": mode, "sample_id": "T", "save_dir": "/x", "before_path": "/x/before.jpg"}
    if extra_vars:
        start_vars.update(extra_vars)
    s = await c.start(_doc(), start_vars, mode_run="run")
    rid = s["run_id"]
    replied: set = set()
    for payload in replies:
        assert await wait_status(c, rid, "WAITING_HUMAN"), f"未挂起等待人工: {c.state(rid)}"
        req = _latest_req(events, replied)
        assert req is not None, "无待回复的人工请求"
        replied.add(req["req_id"])
        await c.human_reply(rid, req["req_id"], payload)
    assert await wait_status(c, rid, terminal), f"未到终态 {terminal}: {c.state(rid)}"
    return ex, events


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# 分刀 (num_passes > 1) 的 VM 循环
# --------------------------------------------------------------------------
# ⚠️ 现役 app.yaml 的 num_passes 恒为 1, 这条循环从来只跑过 1 次迭代。分刀是治粉末崩飞的
#    工艺手段(每刀切削力 ∝ 切深), 用户随时会在设备参数里把它调到 2/3 —— 循环错了直接废板。

def test_multi_pass_alternates_write_z_and_scrape_in_order():
    """N 刀 = 严格交替的 (写本层 Z → 刮一刀) × N, 且 Z 递增下刀。

    交替顺序是硬要求: 若先把 3 层 Z 连写再刮 3 次, 前两刀会全刮在最深的那一层,
    分刀就完全失效(等同一刀切到底)且第一刀就吃满切深。
    """
    ex, _ = _run(_drive("auto", [], "DONE", executor=MultiPassExecutor()))
    seq = [(n, p) for n, p in ex.calls
           if n in ("photoscrape.write_pass_z", "photoscrape.scrape")]

    assert [n for n, _ in seq] == ["photoscrape.write_pass_z", "photoscrape.scrape"] * 3, \
        f"未严格交替: {[n for n, _ in seq]}"
    assert [p["z"] for n, p in seq if n == "photoscrape.write_pass_z"] == MultiPassExecutor.PASS_Z


def test_multi_pass_writes_the_path_block_only_once():
    """4 数组块写在循环外, 只写 1 次 —— 分刀只换 Z, 路径不重写(重写=每刀 400×4 点白跑)。"""
    ex, _ = _run(_drive("auto", [], "DONE", executor=MultiPassExecutor()))

    assert _names(ex).count("photoscrape.write_cnc_path") == 1
    assert _names(ex).count("photoscrape.scrape") == 3


def test_multi_pass_finishes_vacuum_once_after_all_passes():
    """收尾只在全部刀次跑完后调一次 —— 刀间关真空/电机会让中间刀无吸力, 正是崩飞的成因。"""
    ex, _ = _run(_drive("auto", [], "DONE", executor=MultiPassExecutor()))
    names = _names(ex)

    assert names.count("photoscrape.scrape_finish") == 1
    last_scrape = len(names) - 1 - names[::-1].index("photoscrape.scrape")
    assert names.index("photoscrape.scrape_finish") > last_scrape, "收尾早于最后一刀"


def test_production_confirms_the_flip_actually_happened():
    """生产收尾后必须确认翻料缸到位。

    A41 是开环(同扫描周期返回 DONE, 不等气缸反馈), 生产此前从不确认 —— 气压不足/机构卡滞
    导致压根没翻是完全看不见的哑故障(粉留在转运路径上, 后续掉出去)。这里只确认不复位:
    复位落在 collect_load, 要等机器人把粉桶取走之后。
    """
    ex, _ = _run(_drive("auto", [], "DONE"))
    names = _names(ex)

    assert "photoscrape.wait_rot" in names, "生产收尾漏了到位确认"
    assert names.index("photoscrape.scrape_finish") < names.index("photoscrape.wait_rot")
    assert "photoscrape.retr_stoprot" not in names, "复位归 collect_load, 不该在这里"


def test_auto_dispatches_without_gate_when_vision_ok():
    ex, events = _run(_drive("auto", [], "DONE"))
    # auto + 候选有效: 无任何人工门
    assert not any(e["type"] == "vm_human_request" for e in events)
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape_finish" in _names(ex)


def test_auto_escalates_to_human_when_vision_fails():
    # analyze 失败(no_bands): auto 不盲跑, 降级进门(1b); 门里选跳过收尾
    ex, events = _run(_drive("auto", [{"choice": "skip"}], "DONE", analyze=ANALYZE_FAIL))
    gate = [e for e in events if e["type"] == "vm_human_request" and e.get("kind") == "choose"]
    assert len(gate) == 1, "auto 失败应降级到统一门"
    ph = [c for c in ex.calls if c[0] == "photoscrape.cnc_path" and c[1].get("placeholder")]
    assert len(ph) == 1, "跳过应走 cnc_path(placeholder)"
    assert "photoscrape.write_cnc_path" in _names(ex)


def test_manual_gate_dispatch_reaches_scrape():
    ex, events = _run(_drive("manual", [{"values": {"band_id": "band_01"}}, {"choice": "dispatch"}], "DONE"))
    # 门事件带 options(5 选项) + context(源 summary)
    gate = next(e for e in events if e.get("kind") == "choose")
    assert {o["value"] for o in gate["options"]} == {"dispatch", "align", "reanalyze", "sketch", "skip", "abort"}
    assert gate["context"] == "/x/summary.json"
    # #9: cand_valid 时门 prompt 含下发前数值复核 (pass/Z切深/进给/点数); 2D 叠加图看不出 Z
    assert "复核 pass=1" in gate["prompt"]
    assert "Z切深=[8.0]" in gate["prompt"] and "进给=800" in gate["prompt"] and "点数=400" in gate["prompt"]
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape" in _names(ex)
    assert "photoscrape.scrape_finish" in _names(ex)


def test_manual_gate_abort_releases_both_cylinders():
    ex, _ = _run(_drive("manual", [{"values": {"band_id": "band_01"}}, {"choice": "abort"}], "ERROR"))
    press = [c for c in ex.calls if c[0] == "photoscrape.press_cylinder"]
    locate = [c for c in ex.calls if c[0] == "photoscrape.locate_cylinder"]
    assert press and press[0][1].get("pressed") is True, "首个 press 是压下开拍"
    assert press[-1][1].get("pressed") is False, "中止释放下压气缸"
    assert locate and locate[-1][1].get("clamped") is False, "中止释放定位气缸"
    assert "photoscrape.write_cnc_path" not in _names(ex), "中止不得下发路径"


def test_manual_gate_skip_uses_placeholder_and_no_scrape():
    ex, _ = _run(_drive("manual", [{"values": {"band_id": "band_01"}}, {"choice": "skip"}], "DONE"))
    ph = [c for c in ex.calls if c[0] == "photoscrape.cnc_path" and c[1].get("placeholder")]
    assert len(ph) == 1
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape" not in _names(ex), "跳过刮板: pass_z_list 空, scrape 一次不跑"
    assert "photoscrape.scrape_finish" in _names(ex)


def test_manual_gate_sketch_then_dispatch_uses_manual_summary():
    ex, events = _run(_drive(
        "manual",
        [{"values": {"band_id": "band_01"}},
         {"choice": "sketch"},
         {"choice": "ok", "values": {"sketch_summary_path": "/m/summary.json",
                                     "sketch_band_id": "manual_01",
                                     "sketch_annotated_url": "/api/vision/image/m.png"}},
         {"choice": "dispatch"}],
        "DONE",
    ))
    # 手绘门被打开
    assert any(e.get("kind") == "sketch" for e in events), "应打开手绘门"
    # 手绘带回的 summary_path 被交给 cnc_path
    cnc_summaries = [c[1].get("summary_path") for c in ex.calls if c[0] == "photoscrape.cnc_path"]
    assert "/m/summary.json" in cnc_summaries, "应据手绘 summary 重算路径"
    assert "photoscrape.write_cnc_path" in _names(ex)


def test_manual_gate_reanalyze_then_dispatch_uses_reanalyzed_summary():
    # 门内"重新识别": 打开 reanalyze 门, 前端带回重识别 summary/band → cnc_path 据其重算 → 下发到刮取。
    ex, events = _run(_drive(
        "manual",
        [{"values": {"band_id": "band_01"}},
         {"choice": "reanalyze"},
         {"choice": "ok", "values": {"reanalyze_summary_path": "/r/summary.json",
                                     "reanalyze_band_id": "band_02",
                                     "reanalyze_annotated_url": "/api/vision/image/r.png"}},
         {"choice": "dispatch"}],
        "DONE",
    ))
    assert any(e.get("kind") == "reanalyze" for e in events), "应打开重识别门"
    cnc_summaries = [c[1].get("summary_path") for c in ex.calls if c[0] == "photoscrape.cnc_path"]
    assert "/r/summary.json" in cnc_summaries, "应据重识别 summary 重算路径"
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape" in _names(ex)


# ---- D3 门环 align 选项 (spec 0716 §6 D3): 内环失败吞错回门 --------------------------


class AlignReadoutFailExecutor(PhotoExecutor):
    """D3 内环失败注入: 第 N 次 align_readout 起 REJECTED (readout 不在内层 try →
    冒泡到 D1 外层 catch → align_home → ALIGN_FAILED → D3 catch 吞 → 回外门)。"""

    def __init__(self, analyze=ANALYZE_OK, fail_readout_after=2):
        super().__init__(analyze)
        self._fail_readout_after = fail_readout_after
        self._readout_n = 0

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        if name == "photoscrape.align_readout":
            self._readout_n += 1
            if self._readout_n >= self._fail_readout_after:
                self.calls.append((name, dict(params or {})))
                return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                    accepted=False, message="回读失败(测试注入)", result={})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


def test_gate_align_option_runs_loop_and_returns_to_gate():
    # manual + 视觉OK: 选带 input 门 → 外门 align → 内环 readout 门 finish → 回外门 → dispatch → DONE
    ex, events = _run(_drive("manual", [
        {"values": {"band_id": "band_01"}},        # 选带 input 门 (照既有 manual 用例回复形态)
        {"choice": "align"},                       # 外门: 对位检查
        {"choice": "finish", "values": {}},        # 内环 readout 门: 直接结束对位
        {"choice": "dispatch"},                    # 回外门: 正常下发
    ], "DONE", resolve_script=_resolve_ps))
    n = _names(ex)
    assert "photoscrape.align_readout" in n and "photoscrape.align_home" in n
    # 段首唯一 press(true); align 分支纯对位不碰气缸 (裁定③)
    assert [c[1] for c in ex.calls if c[0] == "photoscrape.press_cylinder"] == [{"pressed": True}]
    assert "photoscrape.write_cnc_path" in n         # 检查完仍正常下发
    assert "photoscrape.scrape_finish" in n


def test_gate_align_failure_swallowed_back_to_gate():
    # 内环第二次 readout REJECTED (fail_readout_after=2) → D1 回零 raise → D3 catch 吞 → 外门仍可 skip 收尾
    ex, events = _run(_drive("manual", [
        {"values": {"band_id": "band_01"}},        # 选带 input 门
        {"choice": "align"},                       # 外门: 对位检查
        {"choice": "go_origin", "values": {}},     # 内环门#1 (readout#1 OK) → 走位 → 回环 → readout#2 REJECTED
        {"choice": "skip"},                         # 吞错回外门后: 跳过收尾
    ], "DONE", executor=AlignReadoutFailExecutor(fail_readout_after=2), resolve_script=_resolve_ps))
    n = _names(ex)
    # 唯一硬断言: 外门在 align 失败后仍能 skip 收尾 (裁定②)
    assert "photoscrape.scrape_finish" in n
    # align 内环已回零 + 失败被吞未阻断门
    assert "photoscrape.align_home" in n
    ph = [c for c in ex.calls if c[0] == "photoscrape.cnc_path" and c[1].get("placeholder")]
    assert len(ph) == 1, "跳过收尾应走 cnc_path(placeholder)"
    # align 分支不新增气缸调用: 全程只有段首 press(true) (裁定③)
    assert [c[1] for c in ex.calls if c[0] == "photoscrape.press_cylinder"] == [{"pressed": True}]


def test_failed_sketch_retry_preserves_prior_valid_cnc():
    """审阅 #1: 先有有效候选(视觉成功), 手绘重试的 cnc_path 失败(REJECTED)不得污染 cnc。

    失败前(旧 bug): VM 在 raise 前先把被拒结果 {} 写进 cnc → cand_valid 仍 true → 之后 dispatch
    喂空 dict 给 write_cnc_path → KeyError 卡板。修后: 失败动作不写 assign, cnc 保持旧有效路径,
    dispatch 用旧 400 点路径正常到达 scrape_finish。
    """
    ex = SketchCncFailExecutor(bad_summary="/bad/summary.json")
    _ex, events = _run(_drive(
        "manual",
        [{"values": {"band_id": "band_01"}},
         {"choice": "sketch"},
         {"choice": "ok", "values": {"sketch_summary_path": "/bad/summary.json",
                                     "sketch_band_id": "manual_01",
                                     "sketch_annotated_url": "/api/vision/image/bad.png"}},
         {"choice": "dispatch"}],
        "DONE",
        executor=ex,
    ))
    # 手绘 summary 确实被拿去算过路径并失败一次
    bad = [c for c in ex.calls if c[0] == "photoscrape.cnc_path" and c[1].get("summary_path") == "/bad/summary.json"]
    assert len(bad) == 1, "应尝试用手绘 summary 算路径并失败"
    # 关键: 下发用的是旧有效路径 → 到达 scrape_finish; write_cnc_path 收到非空 400 点而非被污染的空 dict
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape_finish" in _names(ex)
    wcp = next(c for c in ex.calls if c[0] == "photoscrape.write_cnc_path")
    assert len(wcp[1].get("sx") or []) == 400, "下发的是旧有效路径的 400 点, 非被污染冲空的 cnc"


def test_fixed_summary_path_dispatches_without_gate():
    # B1: 传入 fixed_summary_path → 用它算路径, 直接下发, 无人工门
    ex = PhotoExecutor()
    events: list[dict] = []
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
    s = _run(c.start(_doc(), {"mode": "manual", "sample_id": "T", "save_dir": "/x",
                              "before_path": "/x/before.jpg",
                              "fixed_summary_path": FIXED_SUMMARY,
                              "fixed_band_id": "fixed_01"}, mode_run="run"))
    rid = s["run_id"]
    assert _run(wait_status(c, rid, "DONE")), f"未到 DONE: {c.state(rid)}"
    # 无任何人工门(即便 mode=manual)
    assert not any(e["type"] == "vm_human_request" for e in events)
    # cnc_path 用固定 summary 算过, 且真机块写发生(走到刮取收尾)
    cnc_calls = [p for (n, p) in ex.calls if n == "photoscrape.cnc_path"]
    # 固定路径实验跳过(3)视觉候选 → cnc_path **仅** 在(3b)以固定 summary 调用一次,
    # 不再有 step(3) 对视觉 summary 的无效调用(生产日志洁净; 离线 stub 曾掩盖它)。
    assert cnc_calls == [{"summary_path": FIXED_SUMMARY, "band_id": "fixed_01"}], \
        f"cnc_path 应仅用固定 summary 调用一次, 实际: {cnc_calls}"
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape_finish" in _names(ex)


def test_empty_fixed_summary_path_keeps_manual_gate():
    # B1 默认: fixed_summary_path 缺省("") → 原 manual 门流程不变(仍进门)
    ex, events = _run(_drive("manual",
                             [{"values": {"band_id": "band_01"}}, {"choice": "dispatch"}], "DONE"))
    assert any(e["type"] == "vm_human_request" and e.get("kind") == "choose" for e in events)


class ScrapedCaptureFailExecutor(PhotoExecutor):
    """刮后补拍 capture 失败注入: 对账是哨兵, 失败不得 fault 主流程。"""

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        if name == "photoscrape.capture" and params.get("filename") == "scraped.jpg":
            self.calls.append((name, params))
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="相机故障(注入)", result={})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


def test_reconcile_photo_captured_after_scrape_before_finish():
    ex, _ = _run(_drive("auto", [], "DONE"))
    names = _names(ex)
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 2, f"应有 段首after + 刮后scraped 两次拍照: {captures}"
    assert captures[1][1].get("filename") == "scraped.jpg"
    # 顺序: 最后一次 scrape → 补拍 → 对账叠加 → scrape_finish
    assert "photoscrape.scraped_overlay" in names
    last_scrape = max(i for i, n in enumerate(names) if n == "photoscrape.scrape")
    assert last_scrape < names.index("photoscrape.scraped_overlay") < names.index("photoscrape.scrape_finish")


def test_reconcile_photo_knob_off_skips_block():
    ex, _ = _run(_drive("auto", [], "DONE", extra_vars={"reconcile_photo": False}))
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 1                      # 只有段首 after.jpg
    assert "photoscrape.scraped_overlay" not in _names(ex)


def test_reconcile_photo_skipped_when_skip_scrape():
    # manual 模式 vis.ok 先过选带 input 门, 再于统一门选跳过刮板 → skip_scrape=true 联动关补拍块。
    ex, _ = _run(_drive("manual", [{"values": {"band_id": "band_01"}}, {"choice": "skip"}], "DONE"))
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 1
    assert "photoscrape.scraped_overlay" not in _names(ex)


def test_reconcile_capture_failure_does_not_fault_run():
    ex, _ = _run(_drive("auto", [], "DONE", executor=ScrapedCaptureFailExecutor()))
    names = _names(ex)
    assert "photoscrape.scrape_finish" in names          # 主流程照常收尾
    # catch 内 best-effort 收相机: 失败 capture 之后仍有 cam_photohome
    fail_idx = max(i for i, c in enumerate(ex.calls)
                   if c[0] == "photoscrape.capture" and c[1].get("filename") == "scraped.jpg")
    assert any(i > fail_idx for i, n in enumerate(names) if n == "photoscrape.cam_photohome")
