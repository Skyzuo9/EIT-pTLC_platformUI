"""升降板仓行程盘点 — 换算/判定/标定/端点/编排离线测试。

覆盖 controller/feedlift_count.py 的全部判定分支、plc_controller.read_feedlift_pos
的节点名、两步标定端点, 以及两个 feedlift cycle 的接线 (reconcile 位置是本特性最容易
写错的一处: 放在取板后会与 cycle 终态的账本 −1 叠加成双倍扣减)。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.controller.feedlift_count import (
    CLEAR_ACTION, MIN_APPROACH_MM, PITCH_DRIFT_LIMIT, RESIDUAL_LIMIT, SEARCH_ACTION,
    MagazineCalib, count_from_pos, evaluate, fit_calib, load_calib, save_calib)
from eit_ptlc.controller.plc_controller import PlcController

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
_ACTIONS_DIR = _PKG / "config" / "actions"
_OPS_DIR = _PKG / "config" / "operation" / "07_feedlift"

# 标定基准: 空仓位 500mm, 节距 2.25mm (玻璃 2.0 + 硅胶涂层), 容量 30, 低料线 5
_FEED = MagazineCalib(magazine="feed", z_empty_mm=500.0, pitch_mm=2.25,
                      capacity=30, warn_threshold=5)
_WASTE = MagazineCalib(magazine="waste", z_empty_mm=500.0, pitch_mm=2.25,
                       capacity=30, warn_threshold=25)


def _z_for(count: int, calib: MagazineCalib = _FEED) -> float:
    """给定张数反推光电触发时的轴位置(mm) —— 测试里造读数用."""
    return calib.z_empty_mm - count * calib.pitch_mm


# ──────────────────────────────────────────────────────────────────────────
# 换算
# ──────────────────────────────────────────────────────────────────────────

def test_count_from_pos_roundtrip():
    """整数张位置正反算无残差."""
    for n in (0, 1, 15, 29, 30):
        count, residual = count_from_pos(_z_for(n), _FEED)
        assert count == n
        assert residual == 0.0


def test_count_from_pos_half_plate_residual():
    """半张位置的残差应为 0.5 (读数不可信的极端)."""
    count, residual = count_from_pos(_z_for(29) - _FEED.pitch_mm / 2, _FEED)
    assert count in (29, 30)
    assert abs(residual - 0.5) < 1e-9


def test_nominal_2mm_would_drift_one_plate_by_eighth():
    """钉住"名义 2.0mm 不能替代实测节距": 同一读数按 2.0 换算, 第 8 张即差满一张。"""
    nominal = MagazineCalib(magazine="feed", z_empty_mm=500.0, pitch_mm=2.0,
                            capacity=60, warn_threshold=5)
    wrong, _ = count_from_pos(_z_for(8), nominal)
    assert wrong == 9        # 真实 8 张被算成 9 张
    assert count_from_pos(_z_for(8), _FEED)[0] == 8


# ──────────────────────────────────────────────────────────────────────────
# 判定
# ──────────────────────────────────────────────────────────────────────────

def test_evaluate_rejects_uncalibrated():
    """pitch_mm=0 = 未标定: 直接不通过, 绝不退回名义值."""
    raw = MagazineCalib(magazine="feed", z_empty_mm=0.0, pitch_mm=0.0,
                        capacity=30, warn_threshold=5)
    res = evaluate(437.0, raw)
    assert res["ok"] is False
    assert "尚未标定" in res["text"]


def test_evaluate_absolute_only():
    """不给 z_prev: 只做绝对盘点, 差分字段为 None."""
    res = evaluate(_z_for(29), _FEED)
    assert res["ok"] is True
    assert res["count"] == 29
    assert res["residual"] == 0.0
    assert res["taken"] is None and res["delta_mm"] is None
    assert res["warn"] is False


def test_evaluate_taken_one_is_ok():
    """取走恰好一张: 行程差 = 一个节距."""
    res = evaluate(_z_for(29), _FEED, z_prev=_z_for(30), expect_taken=1)
    assert res["ok"] is True
    assert res["taken"] == 1
    assert res["delta_mm"] == 2.25
    assert res["count"] == 29
    assert "本次取走 1 张" in res["text"]


def test_evaluate_double_pick_fails():
    """双张: 行程差两个节距, 判定不通过并点名"双张"."""
    res = evaluate(_z_for(28), _FEED, z_prev=_z_for(30), expect_taken=1)
    assert res["ok"] is False
    assert res["taken"] == 2
    assert res["delta_mm"] == 4.5
    assert "双张" in res["text"]


def test_evaluate_empty_pick_fails():
    """空吸: 行程差为 0, 判定不通过并点名"空吸"."""
    res = evaluate(_z_for(30), _FEED, z_prev=_z_for(30), expect_taken=1)
    assert res["ok"] is False
    assert res["taken"] == 0
    assert "空吸" in res["text"]


def test_evaluate_residual_over_limit_fails():
    """残差越界 (半张位置): 读数不可信, 优先于差分判定报出."""
    z = _z_for(29) - _FEED.pitch_mm / 2
    res = evaluate(z, _FEED)
    assert res["ok"] is False
    assert res["residual"] > RESIDUAL_LIMIT
    assert "不可信" in res["text"]


def test_evaluate_count_out_of_range_fails():
    """换算张数超量程 (含负数): 判定不通过, 且不做截断掩盖."""
    over = evaluate(_z_for(31), _FEED)
    assert over["ok"] is False and over["count"] == 31 and "超出量程" in over["text"]
    under = evaluate(_z_for(-1), _FEED)
    assert under["ok"] is False and under["count"] == -1


def test_evaluate_warns_low_feed_and_full_waste():
    """预警不影响 ok: 上料仓看低料下限, 下料仓看快满上限."""
    low = evaluate(_z_for(5), _FEED)
    assert low["ok"] is True and low["warn"] is True and "补料" in low["text"]
    assert evaluate(_z_for(6), _FEED)["warn"] is False

    full = evaluate(_z_for(25, _WASTE), _WASTE)
    assert full["ok"] is True and full["warn"] is True and "清仓" in full["text"]
    assert evaluate(_z_for(24, _WASTE), _WASTE)["warn"] is False


def test_evaluate_pitch_drift_flagged_but_not_fatal():
    """实测节距偏离标定值超限: 只提示重标, 不判失败, 也不改标定值."""
    res = evaluate(_z_for(30) + 2.5, _FEED, z_prev=_z_for(30), expect_taken=1)
    assert res["ok"] is True
    assert res["taken"] == 1
    assert res["measured_pitch_mm"] == 2.5
    assert abs(res["measured_pitch_mm"] - _FEED.pitch_mm) > PITCH_DRIFT_LIMIT
    assert res["pitch_drift"] is True and "重新标定" in res["text"]


# ──────────────────────────────────────────────────────────────────────────
# 标定常量存取
# ──────────────────────────────────────────────────────────────────────────

def _calib_file(tmp_path: Path) -> Path:
    """未标定的临时标定文件; 刻意不写 samples 键 —— 兼验旧版文件缺该键时按空处理."""
    path = tmp_path / "feedlift_calib.json"
    path.write_text(json.dumps({
        "feed": {"z_empty_mm": 0.0, "pitch_mm": 0.0, "warn_threshold": 5},
        "waste": {"z_empty_mm": 0.0, "pitch_mm": 0.0, "warn_threshold": 25},
    }), encoding="utf-8")
    return path


def test_save_calib_is_partial_update(tmp_path):
    """两步标定分两次写: 第二步不能冲掉第一步的 z_empty_mm."""
    path = _calib_file(tmp_path)
    save_calib(path, "feed", z_empty_mm=500.0)
    save_calib(path, "feed", pitch_mm=2.25)
    calib = load_calib(path, "feed", 30)
    assert calib.z_empty_mm == 500.0 and calib.pitch_mm == 2.25
    assert calib.calibrated is True
    # 另一个板仓不受影响
    assert load_calib(path, "waste", 30).calibrated is False


def test_load_calib_capacity_comes_from_caller(tmp_path):
    """容量不在标定文件里重复定义, 由调用方 (物料拓扑) 传入."""
    path = _calib_file(tmp_path)
    assert load_calib(path, "feed", 42).capacity == 42


def test_save_calib_rejects_unknown_field(tmp_path):
    path = _calib_file(tmp_path)
    try:
        save_calib(path, "feed", pitch_cm=0.225)
    except ValueError as exc:
        assert "标定字段名非法" in str(exc)
    else:
        raise AssertionError("非法字段名应被拒绝")


def test_shipped_calib_file_is_uncalibrated():
    """随仓库发布的标定文件必须是未标定态 —— 绝不带一个别人机器上的节距上线。

    z_empty_mm 允许非 0 (现场跑过空仓采样就会写上), 但只要 pitch_mm 为 0,
    probe_stack 就一律拒动作, 不会拿半份标定去换算。
    """
    shipped = json.loads((_PKG / "config" / "feedlift_calib.json").read_text(encoding="utf-8"))
    assert set(shipped) == {"feed", "waste"}
    for section in shipped.values():
        assert section["pitch_mm"] == 0.0
        assert isinstance(section["samples"], list)


# ──────────────────────────────────────────────────────────────────────────
# 测量原语与动作注册
# ──────────────────────────────────────────────────────────────────────────

class _FakeDriver:
    """最小伪驱动: read_variable 从预置字典取值 (照 test_align_check_offline.py)."""

    def __init__(self, vals: dict[str, object]) -> None:
        self._vals = vals

    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        return self._vals[name]


def test_read_feedlift_pos_maps_axis_to_node():
    plc = PlcController(_FakeDriver({
        "FeedLift_1Z_ActPos": 434.75,
        "FeedLift_2Z_ActPos": 121.5,
    }))
    assert asyncio.run(plc.read_feedlift_pos(1)) == 434.75
    assert asyncio.run(plc.read_feedlift_pos(2)) == 121.5


def test_read_feedlift_pos_rejects_bad_axis():
    plc = PlcController(_FakeDriver({}))
    try:
        asyncio.run(plc.read_feedlift_pos(3))
    except ValueError as exc:
        assert "升降轴号" in str(exc)
    else:
        raise AssertionError("非法轴号应被拒绝")


def test_probe_stack_action_registered():
    reg = ActionRegistry.load(_ACTIONS_DIR)
    adef = reg.get("feedlift.probe_stack")
    assert adef.kind == "host"
    assert adef.method == "feedlift_probe"
    params = {p.name: p for p in adef.params}
    assert set(params) == {"magazine", "z_prev", "expect_taken", "reconcile", "z_clear"}
    assert params["magazine"].required is True
    assert [o.value for o in params["magazine"].options] == ["feed", "waste"]
    # 差分与对账都必须是可选的: 下料仓只调绝对盘点那一路
    assert params["z_prev"].required is False
    assert params["reconcile"].default is False
    # 陈旧读数自校验也是可选的: cycle 内的探测不给清零位 (那里由编排保证顺序)
    assert params["z_clear"].required is False


# ──────────────────────────────────────────────────────────────────────────
# 编排接线 (本特性最易写错的一处)
# ──────────────────────────────────────────────────────────────────────────

def _probe_calls(script_name: str) -> list[dict]:
    """取某 cycle 脚本里全部 feedlift.probe_stack 调用节点 (按出现顺序)."""
    doc = yaml.safe_load((_OPS_DIR / f"{script_name}.yaml").read_text(encoding="utf-8"))
    return [n for n in doc["body"]
            if n.get("op") == "call" and n.get("action") == "feedlift.probe_stack"]


def _body_actions(script_name: str) -> list[str]:
    doc = yaml.safe_load((_OPS_DIR / f"{script_name}.yaml").read_text(encoding="utf-8"))
    return [n.get("action", "") for n in doc["body"] if n.get("op") == "call"]


def test_load_cycle_probes_before_and_after_pick():
    """上料 cycle: 取板前探测负责对账, 取板后探测负责差分判定, 二者不可对调."""
    probes = _probe_calls("feedlift_load_cycle")
    assert len(probes) == 2

    before, after = probes
    assert before["args"]["reconcile"] == {"lit": True}
    assert "z_prev" not in before["args"]          # 前一次探测无前值可比
    assert before["assign"] == {"var": "p0"}

    # 取板后这次绝不能对账: 账本 −1 要到 cycle 终态才提交, 此刻对账会双倍扣减
    assert "reconcile" not in after["args"]
    assert after["args"]["z_prev"] == {"field": {"var": "p0"}, "name": "z_mm"}
    assert after["args"]["expect_taken"] == {"lit": 1}


def test_load_cycle_has_probe_raise_before_second_probe():
    """判定探测前必须先补一次 feed_raise, 否则读到的是 feed_lower 后的让位位置."""
    actions = _body_actions("feedlift_load_cycle")
    assert actions.count("feedlift.feed_raise") == 2
    second_probe = len(actions) - 1 - actions[::-1].index("feedlift.probe_stack")
    assert actions[second_probe - 1] == "feedlift.feed_raise"


def test_unload_cycle_probes_once_before_place():
    """下料 cycle: 只在放板前探测一次 (不同光电边沿不可相减, 故不做差分)."""
    probes = _probe_calls("feedlift_unload_cycle")
    assert len(probes) == 1
    only = probes[0]
    assert only["args"]["magazine"] == {"lit": "waste"}
    assert only["args"]["reconcile"] == {"lit": True}
    assert "z_prev" not in only["args"] and "expect_taken" not in only["args"]

    actions = _body_actions("feedlift_unload_cycle")
    assert actions[actions.index("feedlift.probe_stack") - 1] == "feedlift.unload_ready"


def test_cycle_scripts_declare_probe_vars():
    """assign 目标必须在 vars 里声明, 否则 VM schema 校验不过."""
    for name, expected in (("feedlift_load_cycle", {"p0", "p1"}),
                           ("feedlift_unload_cycle", {"p0"})):
        doc = yaml.safe_load((_OPS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
        declared = {v["name"] for v in doc.get("vars", [])}
        assert expected <= declared
        for var in expected:
            assert next(v for v in doc["vars"] if v["name"] == var)["type"] == "DICT"


# ──────────────────────────────────────────────────────────────────────────
# 多点拟合
# ──────────────────────────────────────────────────────────────────────────

def test_fit_recovers_constants_from_collinear_samples():
    """三点严格共线: 节距与空仓位精确复原, 残差 0."""
    fit = fit_calib([(0, 500.0), (10, 477.5), (30, 432.5)])   # z = 500 − 2.25N
    assert fit["ok"] is True and fit["n"] == 3
    assert fit["z_empty_mm"] == 500.0
    assert fit["pitch_mm"] == 2.25
    assert fit["residual_rms_mm"] == 0.0
    assert fit["residuals"] == [0.0, 0.0, 0.0]


def test_fit_two_points_gives_no_residual_information():
    """钉住本特性最容易误读的一处: 两点必然共线, 残差恒为 0 并不代表准。

    此时必须返回 residual_rms_mm=None 并给出说明, 绝不返回一个看着很好的 0。
    """
    fit = fit_calib([(0, 500.0), (30, 432.5)])
    assert fit["ok"] is True and fit["n"] == 2
    assert fit["pitch_mm"] == 2.25            # 拟合本身有效, 退化成旧的两步公式
    assert fit["residual_rms_mm"] is None
    assert fit["residual_rms_plates"] is None
    assert "没有信息" in fit["reason"]


def test_fit_residual_reflects_measurement_noise():
    """加噪样本: 残差 RMS 落在噪声量级 —— 这正是光电触发重复性的实测值."""
    clean = [(0, 500.0), (10, 477.5), (20, 455.0), (30, 432.5)]
    noise = [+0.05, -0.05, +0.05, -0.05]
    fit = fit_calib([(n, z + d) for (n, z), d in zip(clean, noise)])
    assert fit["ok"] is True
    assert abs(fit["pitch_mm"] - 2.25) < 0.01
    assert 0.02 < fit["residual_rms_mm"] < 0.12         # 与 ±0.05mm 噪声同量级
    assert fit["residual_rms_plates"] == round(fit["residual_rms_mm"] / fit["pitch_mm"], 4)


def test_fit_rejects_degenerate_inputs():
    """定不出直线的两种情形: 样本不足 / 张数全同 (分母为 0, 不能除零)."""
    one = fit_calib([(0, 500.0)])
    assert one["ok"] is False and "至少要 2 组" in one["reason"]
    same = fit_calib([(5, 500.0), (5, 499.9), (5, 500.1)])
    assert same["ok"] is False and "张数相同" in same["reason"]
    assert fit_calib([])["ok"] is False


def test_search_action_matches_unload_cycle_probe_edge():
    """边沿一致性钉子: 标定采样用的动作必须与 cycle 内 probe 前的那个动作是同一个。

    unload_ready 搜光电2=TRUE, unload_bury 搜同一光电的 FALSE 沿; 若标定用了 bury 而
    运行探测在 ready 之后, 两者就差一个光电回差, 换算出的张数会系统性偏移。
    """
    assert SEARCH_ACTION["feed"] == "feedlift.feed_raise"
    assert SEARCH_ACTION["waste"] == "feedlift.unload_ready"
    for script, magazine in (("feedlift_load_cycle", "feed"),
                             ("feedlift_unload_cycle", "waste")):
        actions = _body_actions(script)
        first_probe = actions.index("feedlift.probe_stack")
        assert actions[first_probe - 1] == SEARCH_ACTION[magazine]


def test_clear_action_precedes_first_probe_search_in_both_cycles():
    """清零钉子: 每个 cycle 的首次探测前必须是「清零 → 逼近」两步。

    2026-07-26 现场 bug: 逼近动作 (feed_raise / unload_ready) 在光电已 TRUE 时是幂等直通,
    原地确认 300ms 即 DONE 而轴一步不动, 单发它读到的是上次停轴的陈旧位置 —— 装了 5 张板
    仍测出与空仓一样的 498.619。清零动作先把光电退成 FALSE, 逼近才会真搜索。
    """
    assert CLEAR_ACTION["feed"] == "feedlift.feed_clear"
    assert CLEAR_ACTION["waste"] == "feedlift.unload_bury"
    assert set(CLEAR_ACTION) == set(SEARCH_ACTION)          # 两表必须成对
    for script, magazine in (("feedlift_load_cycle", "feed"),
                             ("feedlift_unload_cycle", "waste")):
        actions = _body_actions(script)
        first_probe = actions.index("feedlift.probe_stack")
        assert actions[first_probe - 2] == CLEAR_ACTION[magazine], (
            f"{script}: 首次探测前缺清零动作, 测到的会是陈旧位置")


def test_load_cycle_second_probe_relies_on_feed_lower_as_clear():
    """取板后那次探测前不补清零: feed_lower(−5mm) 已把光电退出去, 再补一次纯属浪费节拍。"""
    actions = _body_actions("feedlift_load_cycle")
    last_probe = len(actions) - 1 - actions[::-1].index("feedlift.probe_stack")
    assert actions[last_probe - 1] == "feedlift.feed_raise"
    assert actions[last_probe - 2] != "feedlift.feed_clear"
    assert "feedlift.feed_lower" in actions[:last_probe]     # 清零由它承担


def test_feed_clear_action_registered():
    """新增的 1Z 清零动作: plc_l2 / 动作码 13, 且带搜索窗口预下发."""
    adef = ActionRegistry.load(_ACTIONS_DIR).get("feedlift.feed_clear")
    assert adef.kind == "plc_l2"
    assert adef.action_code == 13
    assert set(adef.preload_targets) == {"feedlift_1z_search_low", "feedlift_1z_search_high"}


# ──────────────────────────────────────────────────────────────────────────
# 前置自检
#
# 现场症状: 两个板仓的标定都在第一个动作上失败, 界面只显示 "error=301"/"error=302"。
# 这两个码不是运动失败, 是**前置条件 10 秒等待超时, 轴根本没启动**; 而三项前置里
# 只有接近开关是上位机看得见的, bHomed 与 Alarm 都没暴露成 OPC 节点。
#
# ⚠ 错误码释义本身已改由编排说明书 (mock/behavior/specs/*.yaml) 供给, 断言迁到
# tests/test_plc_error_hints_offline.py —— 本文件曾有的那份手抄门表与释义表已删,
# 抄一份必漂。下面只留标定链自己的自检。
# ──────────────────────────────────────────────────────────────────────────

def test_preflight_gate_reads_ix8_bits_by_raw_polarity():
    """自检按 IX8 裸位判定, 镜像的是 PLC 自己的 ST 判据, 不做常开常闭折算。

    两个传感器职责不同 (2026-07-27 现场目视确认, 弄反了整条诊断都会歪):
        光电开关 (侧面, bit3/4) —— 顶板是否升到取料位; **测量**用
        接近开关 (仓底, bit5/6) —— 仓内有没有板;       **物料互锁**用
    """
    from eit_ptlc.controller.feedlift_count import preflight_gate

    # 现场实测过的一个值: IX8=228 → 仓底接近开关1/2 都有板 (bit5/6), 侧面光电1/2 都未到位
    feed = preflight_gate("feed", 228, True)
    assert feed["proximity"] is True and feed["photoelectric"] is False
    assert feed["ok"] is True and feed["ix8_bits"] == "11100100"
    # 通过不等于动作会成功: 看不见的两项必须如实点名, 且要带上 Alarm 的物理含义
    assert any("bHomed" in u for u in feed["unobservable"])
    assert any("Alarm.0" in u and "上料机构无物料" in u for u in feed["unobservable"])
    assert any("下料机构已满料" in u for u in preflight_gate("waste", 228, True)["unobservable"])

    waste = preflight_gate("waste", 228, True)
    assert waste["axis"] == 2 and waste["proximity"] is True

    # 仓底没板 = 空仓 = 已经能确定会超时, 提前止步而不是白等 PLC 那 10 秒。
    # 文案必须讲成"空仓"而不是甩一个位号, 并给出"改用非零张数"的做法。
    blocked = preflight_gate("feed", 0, True)
    assert blocked["ok"] is False
    assert "仓底检测不到板" in blocked["text"] and "空仓" in blocked["text"]
    assert "IX8.5" in blocked["text"]                 # 位号仍保留, 供查线用
    assert "10/20/30" in blocked["text"] and "截距" in blocked["text"]
    assert preflight_gate("waste", 0b00100000, True)["ok"] is False   # bit5 是 1Z 的, 与 2Z 无关

    assert preflight_gate("feed", 228, False)["ok"] is False          # PLC_Ready=FALSE 也拦下
    assert preflight_gate("feed", 228, None)["ok"] is True            # 读不到就不参与判定


# ──────────────────────────────────────────────────────────────────────────
# 标定端点
#
# 两个驱动运动的端点现在都走 VM 编排 (feedlift_calib_sample / feedlift_measure_count),
# 不再直调执行器 —— 直调不留运行记录, 现场看不出动作到底执行没执行。故这里挂的是真
# VmController + 真脚本仓库 (读的就是 config/operation/07_feedlift 下那两份 YAML),
# 只把执行器替换成 stub: PLC L2 动作假装 DONE, host 动作则委派回真逻辑, 这样编排接线、
# 记样拟合与落盘仍是被真正跑过的那份代码。
# ──────────────────────────────────────────────────────────────────────────

class _Res:
    """最小 ActionResult 替身: VM 只用 ok/status/result/message/step/error_code."""

    def __init__(self, status="DONE", result=None, message=""):
        self.status = type("S", (), {"value": status})()
        self.result = result or {}
        self.message = message
        self.step = 0
        self.error_code = 0

    @property
    def ok(self):
        return self.status.value == "DONE"


def _measure(trigger_mm, *, approach=5.0):
    """造一次测量要消耗的两个轴位置读数: (清零位, 触发位)。

    approach=0 即模拟"逼近动作返回 DONE 但轴没动"——2026-07-26 现场那个 bug 的形态。
    """
    return [trigger_mm - approach, trigger_mm]


_MAGAZINES = {"feed": ("上料仓 (1Z)", 30), "waste": ("下料仓 (2Z)", 30)}


def _client(tmp_path, *, positions, action_status="DONE"):
    """FastAPI + register_feedlift_routes + 真 VM/脚本仓库。

    positions: 依次返回的轴位置列表; **每次测量消耗两个** (清零后一次、逼近后一次),
    用 _measure() 构造。None → 无 PLC (读位动作报错)。
    板仓表来自物料拓扑 (MaterialStore.magazines), 此处用最小 store stub 顶替, 免得
    离线测试为两个常数去装配整套 material_topology.yaml。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from eit_ptlc.api.feedlift_routes import register_feedlift_routes
    from eit_ptlc.controller.feedlift_count import (
        MAGAZINE_AXIS, preflight_gate, record_sample)
    from eit_ptlc.operation.resources import ResourceGate
    from eit_ptlc.operation.vm.controller import VmController
    from eit_ptlc.operation.vm.repo import ScriptRepo
    from eit_ptlc.runtime.run_store import RunStore

    queue = list(positions or [])
    calib_path = _calib_file(tmp_path)

    class _StoreStub:
        magazines = dict(_MAGAZINES)

        def magazine_count(self, magazine):
            return 12

    class _ExecStub:
        """PLC L2 动作假装 DONE; host 动作委派回真逻辑 (记样/自检/读位都要真跑)."""

        calls = []

        async def execute(self, name, params=None, *, current_mode=None):
            args = dict(params or {})
            _ExecStub.calls.append((name, args))
            if action_status != "DONE":
                return _Res(action_status, message="模拟动作未完成")
            if name == "feedlift.preflight":
                # IX8 bit5/bit6 置位 = 两个接近开关都到位, 前置自检放行
                return _Res(result=preflight_gate(args["magazine"], 0b01100000, True))
            if name == "feedlift.read_pos":
                if positions is None:
                    raise RuntimeError("PLC 未就绪")
                axis = MAGAZINE_AXIS[args["magazine"]]
                return _Res(result={"magazine": args["magazine"], "axis": axis,
                                    "z_mm": queue.pop(0) if queue else 0.0})
            if name == "feedlift.calib_record":
                mag = args["magazine"]
                return _Res(result=record_sample(
                    calib_path, mag, _MAGAZINES[mag][1], args["plates"],
                    args["z_clear"], args["z_trigger"]))
            if name == "feedlift.probe_stack":
                if positions is None:
                    raise RuntimeError("PLC 未就绪")
                z_mm = queue.pop(0) if queue else 0.0
                if args.get("z_clear") is not None and z_mm - args["z_clear"] <= 0.02:
                    raise RuntimeError("读数是陈旧值, 已拒绝采用")
                return _Res(result={"count": 12, "residual": 0.03, "ok": True, "z_mm": z_mm})
            return _Res()                                  # 四个 PLC L2 光电搜索动作

    _ExecStub.calls = []
    app = FastAPI()
    app.state.feedlift_calib_path = calib_path
    app.state.material_store = _StoreStub()
    app.state.control_mode = "DEBUG"
    app.state.executor = _ExecStub()
    # 路由只用它判"PLC 在不在"(缺席即 503, 不起编排); 真正的读位走 feedlift.read_pos 动作
    app.state.plc = object() if positions is not None else None
    app.state.run_store = RunStore(":memory:")
    repo = ScriptRepo(_OPS_DIR.parent, history_root=tmp_path / "history")
    app.state.script_repo = repo
    app.state.vm = VmController(
        executor=app.state.executor,
        res_gate=ResourceGate(),                    # specs 为空 = 一律按 exclusive 处理
        resolve_script=lambda n: repo.get("default", n),
        event_sink=app.state.run_store.on_event,
        mode_provider=lambda: app.state.control_mode)
    register_feedlift_routes(app)
    return TestClient(app), app, _ExecStub


def test_calib_get_reports_uncalibrated(tmp_path):
    client, _, _ = _client(tmp_path, positions=_measure(500.0))
    body = client.get("/api/feedlift/calib").json()
    assert body["feed"]["calibrated"] is False
    assert body["feed"]["capacity"] == 30      # 来自物料拓扑, 不在标定文件里
    assert body["waste"]["warn_threshold"] == 25
    assert body["feed"]["search_action"] == "feedlift.feed_raise"
    assert body["feed"]["samples"] == []


def test_sample_clears_then_approaches(tmp_path):
    """采样必须「先清零再逼近」, 顺序不可颠倒 —— 只发逼近会读到陈旧位置。

    整条编排的动作序也在此钉死: 前置自检在最前 (不满足就别白等 PLC 那 10 秒),
    两次读位分别夹在清零后与逼近后 (二者之差即逼近位移, 记样时要靠它判读数新旧)。
    """
    client, _, ex = _client(tmp_path, positions=_measure(477.5))
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 10})
    assert r.status_code == 200
    assert [c[0] for c in ex.calls] == [
        "feedlift.preflight", "feedlift.feed_clear", "feedlift.read_pos",
        "feedlift.feed_raise", "feedlift.read_pos", "feedlift.calib_record"]
    assert r.json()["sampled"] == {"plates": 10, "z_mm": 477.5}
    assert r.json()["samples"] == [{"plates": 10, "z_mm": 477.5}]
    assert r.json()["run_id"]                       # 走了编排 ⇒ 有运行记录可查


def test_sample_422_when_axis_did_not_approach(tmp_path):
    """本次现场 bug 的直接钉子: 逼近动作返回 DONE 但轴没动 ⇒ 读数陈旧, 必须拒收。

    清零位与触发位相同 (approach=0) 即模拟幂等直通; 端点应报 422 且不留样本。
    """
    client, app, _ = _client(tmp_path, positions=_measure(498.619, approach=0.0))
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 5})
    assert r.status_code == 422
    assert "陈旧值" in r.json()["detail"]
    assert load_calib(app.state.feedlift_calib_path, "feed", 30).samples == ()

    # 逼近位移只要超过下界就放行 (正常值就是光电回差, 本身很小)
    ok_client, _, _ = _client(tmp_path, positions=_measure(498.619, approach=MIN_APPROACH_MM * 5))
    assert ok_client.post("/api/feedlift/calib/sample",
                          json={"magazine": "feed", "plates": 5}).status_code == 200


def test_sample_422_when_action_fails(tmp_path):
    """动作没 DONE 就不该记样本 —— 位置不可信."""
    client, app, _ = _client(tmp_path, positions=_measure(477.5), action_status="ERROR")
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 10})
    assert r.status_code == 422
    assert load_calib(app.state.feedlift_calib_path, "feed", 30).samples == ()


def test_multi_sample_fits_and_persists(tmp_path):
    """三组非零采样后自动拟合并落盘, 采样记录一并留存 (标定值的出处可追)。

    空仓基准位 500.0 是**外推出来的截距** —— 三组样本全在 10/20/30 张, 从没采过空仓。
    这正是标定不必 (也不能) 采空仓那一组的依据。
    """
    client, app, _ = _client(
        tmp_path, positions=_measure(477.5) + _measure(455.0) + _measure(432.5))
    for plates in (10, 20, 30):
        r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": plates})
        assert r.status_code == 200

    calib = load_calib(app.state.feedlift_calib_path, "feed", 30)
    assert calib.calibrated is True
    assert calib.pitch_mm == 2.25 and calib.z_empty_mm == 500.0
    assert calib.samples == ((10, 477.5), (20, 455.0), (30, 432.5))
    assert r.json()["fit"]["residual_rms_mm"] == 0.0


def test_sample_keeps_samples_but_rejects_bad_pitch(tmp_path):
    """拟合节距超区间: 样本是现场事实要留下, 坏常数才是要挡住的 —— 只拒写 pitch。

    注意与 test_sample_422_when_axis_did_not_approach 的区别: 这里每次都真逼近过
    (轴确实动了), 只是两次触发位恰好相同 ⇒ 节距 0, 属于标定不合理而非读数不可信。
    """
    client, app, _ = _client(tmp_path, positions=_measure(500.0) + _measure(500.0))
    client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 10})
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 30})
    assert r.status_code == 200
    assert "合理区间" in r.json()["reject_reason"]

    calib = load_calib(app.state.feedlift_calib_path, "feed", 30)
    assert calib.calibrated is False              # 坏常数没落盘
    assert len(calib.samples) == 2                # 但样本都在


def test_clear_samples_resets_calibration(tmp_path):
    client, app, ex = _client(
        tmp_path, positions=_measure(477.5) + _measure(455.0) + _measure(432.5))
    for plates in (10, 20, 30):
        client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": plates})
    assert load_calib(app.state.feedlift_calib_path, "feed", 30).calibrated is True

    before = len(ex.calls)
    r = client.request("DELETE", "/api/feedlift/calib/samples", params={"magazine": "feed"})
    assert r.status_code == 200
    calib = load_calib(app.state.feedlift_calib_path, "feed", 30)
    assert calib.samples == () and calib.calibrated is False and calib.z_empty_mm == 0.0
    assert len(ex.calls) == before                # 清空不驱动任何运动


def test_measure_clears_approaches_then_probe_stack(tmp_path):
    """实测同样走清零+逼近取位, 换算与对账则复用 probe_stack 动作本身。

    只读一次位: 清零位交给 probe_stack 当 z_clear 自校验, 触发位由它自己读 —— 换算
    与判定都在那个动作里, 与两个 feedlift cycle 是同一条代码路径。
    """
    client, _, ex = _client(tmp_path, positions=_measure(432.5))
    r = client.post("/api/feedlift/measure", json={"magazine": "waste"})
    assert r.status_code == 200
    assert r.json()["count"] == 12
    assert r.json()["run_id"]
    assert [c[0] for c in ex.calls] == [
        "feedlift.preflight", "feedlift.unload_bury", "feedlift.read_pos",
        "feedlift.unload_ready", "feedlift.probe_stack"]
    probe_args = ex.calls[-1][1]
    assert probe_args["magazine"] == "waste" and probe_args["reconcile"] is True
    assert probe_args["z_clear"] == 427.5           # 清零位透给动作做陈旧读数自校验


def test_endpoints_reject_unknown_magazine_and_bad_plates(tmp_path):
    client, _, _ = _client(tmp_path, positions=_measure(500.0))
    assert client.post("/api/feedlift/calib/sample",
                       json={"magazine": "hopper", "plates": 10}).status_code == 400
    assert client.post("/api/feedlift/calib/sample",
                       json={"magazine": "feed", "plates": 31}).status_code == 400
    assert client.post("/api/feedlift/calib/sample",
                       json={"magazine": "feed", "plates": -1}).status_code == 400


def test_empty_magazine_sample_rejected_before_any_motion(tmp_path):
    """空仓那一组必须在起编排前就拒掉。

    仓底的玻璃升降接近开关是**有无板检测** (2026-07-27 现场目视确认), 空仓时清零动作
    (feed_clear / unload_bury) 的物料互锁不成立, PLC 必然 10 秒超时报 301/302 ——
    那是设计如此的互锁, 不是故障。起了编排只会往运行历史塞一条注定超时的运行。

    而这一组本来就不必采: 空仓基准位是拟合直线的截距, 由非零张数外推得出
    (见 test_multi_sample_fits_and_persists)。
    """
    client, app, ex = _client(tmp_path, positions=_measure(500.0))
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 0})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "空仓" in detail and "截距" in detail      # 说清为什么不能采、也不必采
    assert ex.calls == []                             # 一个动作都没发
    assert app.state.run_store.list_runs() == []      # 一条运行记录都没留


def test_sample_503_when_plc_absent(tmp_path):
    """没有 PLC 就别起编排: 起了只是往运行历史塞一条注定失败的运行, 还把"设备没接上"
    伪装成"流程跑挂了"。"""
    client, app, _ = _client(tmp_path, positions=None)    # app.state.plc = None
    assert client.post("/api/feedlift/calib/sample",
                       json={"magazine": "feed", "plates": 10}).status_code == 503
    assert app.state.run_store.list_runs() == []          # 一条运行记录都不该留下


def test_sample_run_is_recorded_in_history(tmp_path):
    """本轮改造的目的本身: 采样必须留得下运行记录, 现场才看得出动作执行没执行。

    改造前标定直调执行器、绕开 VM, 既不发 operation_* 事件也不进 RunStore ——
    运行历史里一条都没有。
    """
    client, app, _ = _client(tmp_path, positions=_measure(477.5))
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 10})
    assert r.status_code == 200

    runs = app.state.run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == r.json()["run_id"]
    assert runs[0]["operation"] == "feedlift_calib_sample"
    assert runs[0]["status"] == "DONE"

    # 逐步事件也在: 每个动作各有 enter/done, 回放与单步都靠它
    events = app.state.run_store.get_run(runs[0]["run_id"])["events"]
    done = [e for e in events if e.get("type") == "vm_node_done"]
    assert [e.get("action") for e in done if e.get("action")] == [
        "feedlift.preflight", "feedlift.feed_clear", "feedlift.read_pos",
        "feedlift.feed_raise", "feedlift.read_pos", "feedlift.calib_record"]


def test_failed_action_message_carries_error_hint(tmp_path):
    """动作失败时 message 必须带上错误码释义, 且释义要跟着进运行历史。

    PLC 只回一个整数, 原样透出到界面/历史就是 "error=301" 这么一个字; 而 301/302 是
    **前置没满足、轴根本没启动**, 与 304/305/307 那种真搜到边界完全两回事。
    """
    client, app, _ = _client(tmp_path, positions=_measure(477.5), action_status="ERROR")
    r = client.post("/api/feedlift/calib/sample", json={"magazine": "feed", "plates": 10})
    assert r.status_code == 422
    assert "run_id=" in r.json()["detail"]                 # 失败也给出历史入口
    assert load_calib(app.state.feedlift_calib_path, "feed", 30).samples == ()
