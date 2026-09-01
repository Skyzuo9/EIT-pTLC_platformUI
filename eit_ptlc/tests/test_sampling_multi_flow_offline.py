"""多样品上样 operation — VM 端到端离线 (真 sampling_multi_execute.yaml + 伪执行器)。

关键钉子:
    1. N 行 → 恰好 N 条带, 且**每条带收到的正是该行的几何** (本次改动的核心承诺)
    2. 行内参数覆盖流程级缺省; 行内没给该字段才回落缺省
    3. rinse_rounds=0 是合法值不是"没给" —— 不能被 falsy 合并吃掉 (故合并用 contains 而非 or)
    4. 行缺必填几何 → 报错且**一个设备动作都没发出** (几何缺省会被 coerce 成 0.0,
       而 0.0 是合法坐标, 静默走下去会把点样头真开到零位)
    5. 空清单 → 报错而非静默空跑报 DONE
    6. 体积模型外提后数值不变 (单样品 sampling_execute 与多样品各跑一遍对齐同一组常数)
    7. 逐行各算一次体积模型: 行内改了体积/余量, 该行的吸取量与活塞终点跟着变
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_debug_offline import wait_status

_OP_DIR = Path("eit_ptlc/config/operation/01_sampling")


def _doc(name: str) -> dict:
    return yaml.safe_load((_OP_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


class RecordingExecutor:
    """记录每次 call 的动作名与实参 (全部 DONE); 逐行几何/参数是否真的落到动作上就看这里。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append((name, dict(params or {})))
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result={})

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)

    def of(self, name: str) -> list[dict]:
        return [p for n, p in self.calls if n == name]


def _drive(op_name: str, inputs: dict, terminal: str = "DONE", overrides: dict | None = None):
    """跑一条流程到终态; 返回 (执行器, 事件列表)。子脚本按名从 01_sampling 目录解析。"""

    async def run():
        ex = RecordingExecutor()
        events: list[dict] = []
        c = VmController(executor=ex, res_gate=ResourceGate(),
                         resolve_script=_doc, event_sink=events.append)
        s = await c.start(_doc(op_name), inputs, mode_run="run", overrides=overrides or {})
        rid = s["run_id"]
        assert await wait_status(c, rid, terminal), c.state(rid)
        return ex, events

    return asyncio.run(run())


def _fail_message(events: list[dict]) -> str:
    failed = [e for e in events if e["type"] == "operation_failed"]
    assert failed, "期望流程失败, 但没有 operation_failed 事件"
    return failed[-1]["message"]


# 缺省参数组 (V=2, E=1.5, G=0.2, R=3) 下体积模型的解析解, 与
# sampling_volume_model.yaml 文件头「缺省 G=0.2 -> N=1.225mL」一致。
_ASPIRATE_TOTAL = 3.5      # V + E
_BAND_END = 1.225          # D + G/2 = 1.125 + 0.1
_ASPIRATE_ROUND = 4.5      # R + E

_ROWS3 = [
    {"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0},
    {"well": "A2", "x_start": 160.0, "x_end": 240.0, "y_height": -20.0},
    {"well": "B1", "x_start": 70.0, "x_end": 240.0, "y_height": -40.0},
]


# --------------------------------------------------------------------------
# 1. 逐行几何真的落到各自的条带上
# --------------------------------------------------------------------------

def test_each_row_spots_its_own_band_geometry():
    """3 行 → 3 条带, 每条带的 x_start/x_end/y_height 与孔位都取自对应行。"""
    ex, _ = _drive("sampling_multi_execute", {"samples": _ROWS3, "rinse_rounds": 0})

    bands = ex.of("sampling.spot_band_layer")
    assert len(bands) == 3, ex.names()
    assert [(b["x_start"], b["x_end"], b["y_height"]) for b in bands] == [
        (70.0, 150.0, -20.0), (160.0, 240.0, -20.0), (70.0, 240.0, -40.0)]
    # 每带都显式指名组合点位 (几何是覆盖, 不回写点表)
    assert all(b["ref_spot"] == "spot_pose" for b in bands)

    asp = ex.of("sampling.aspirate")
    assert [a["well"] for a in asp] == ["A1", "A2", "B1"]
    # 吸样与点样严格交替: 不能先吸三次再点三次 (针里只有一段样品)
    assert ex.names() == ["sampling.aspirate", "sampling.spot_band_layer"] * 3


# --------------------------------------------------------------------------
# 2/3. 行内覆盖 vs 流程级缺省
# --------------------------------------------------------------------------

def test_row_override_wins_and_missing_key_falls_back_to_flow_default():
    """行内给了就用行内的, 没给就继承流程级缺省 —— 逐行独立。"""
    rows = [
        {"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0},           # 全继承
        {"well": "A2", "x_start": 160.0, "x_end": 240.0, "y_height": -20.0,
         "sample_volume_ml": 5.0, "dry_cycles": 4, "spot_speed_mm_s": 12.5},          # 部分覆盖
    ]
    ex, _ = _drive("sampling_multi_execute",
                   {"samples": rows, "rinse_rounds": 0,
                    "sample_volume_ml": 2.0, "dry_cycles": 1, "spot_speed_mm_s": 40.0})

    asp = ex.of("sampling.aspirate")
    bands = ex.of("sampling.spot_band_layer")
    # 第 1 行走缺省 V=2 -> 吸取 3.5; 第 2 行行内 V=5 -> 吸取 6.5 (体积模型逐行重算)
    assert asp[0]["sample_volume_ml"] == _ASPIRATE_TOTAL
    assert asp[1]["sample_volume_ml"] == 6.5
    assert [b["dry_cycles"] for b in bands] == [1, 4]
    assert [b["spot_speed_mm_s"] for b in bands] == [40.0, 12.5]


def test_rinse_rounds_zero_is_a_value_not_an_absence():
    """rinse_rounds=0 (只点一轮不回收) 是合法值; 合并逻辑不能把它当"没给"而回落缺省。"""
    rows = [
        {"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0, "rinse_rounds": 0},
        {"well": "A2", "x_start": 160.0, "x_end": 240.0, "y_height": -20.0},   # 继承缺省 2
    ]
    ex, _ = _drive("sampling_multi_execute", {"samples": rows, "rinse_rounds": 2})

    # 行1: 吸+点各 1 次, 无润洗; 行2: 2 轮润洗 -> 润洗 2 次, 吸 1+2 次, 点 1+2 次
    assert ex.count("sampling.rinse_mix") == 2
    assert ex.count("sampling.aspirate") == 1 + 3
    assert ex.count("sampling.spot_band_layer") == 1 + 3
    # 润洗轮的吸取量走 R+E, 且仍点回本行同一条带
    rinse_bands = ex.of("sampling.spot_band_layer")[2:]
    assert all(b["y_height"] == -20.0 and b["x_start"] == 160.0 for b in rinse_bands)
    assert ex.of("sampling.rinse_mix")[0]["well"] == "A2"


# --------------------------------------------------------------------------
# 4/5. 负向: 必须在任何设备动作之前拦下
# --------------------------------------------------------------------------

def test_row_missing_geometry_raises_before_any_device_action():
    """缺 y_height 会被 coerce 成 0.0 (合法坐标!) 把点样头开到零位, 必须先拦。"""
    rows = [{"well": "A1", "x_start": 70.0, "x_end": 150.0}]      # 少 y_height
    ex, events = _drive("sampling_multi_execute", {"samples": rows}, terminal="ERROR")

    assert "SAMPLING_MULTI_ROW_INCOMPLETE" in _fail_message(events)
    assert ex.calls == [], f"守卫之前不该有任何动作下发: {ex.names()}"


def test_second_row_incomplete_stops_before_that_rows_actions():
    """坏行在中间: 前面的行照跑, 到坏行即停, 不得跳过它继续点后面的带。"""
    rows = [
        {"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0},
        {"well": "A2", "x_start": 160.0, "x_end": 240.0},                     # 少 y_height
        {"well": "B1", "x_start": 70.0, "x_end": 240.0, "y_height": -40.0},
    ]
    ex, events = _drive("sampling_multi_execute",
                        {"samples": rows, "rinse_rounds": 0}, terminal="ERROR")

    assert "SAMPLING_MULTI_ROW_INCOMPLETE" in _fail_message(events)
    assert ex.names() == ["sampling.aspirate", "sampling.spot_band_layer"]


def test_empty_sample_list_raises_instead_of_silent_done():
    """空清单跑完报 DONE 会被误读成"点完了", 故显式拒绝。"""
    ex, events = _drive("sampling_multi_execute", {"samples": []}, terminal="ERROR")

    assert "SAMPLING_MULTI_EMPTY" in _fail_message(events)
    assert ex.calls == []


def test_row_volume_chain_guard_still_fires_per_row():
    """体积模型的硬闸外提后仍逐行生效 (排空余量 <= 针流路死体积 1.125)。"""
    rows = [{"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0,
             "over_aspirate_ml": 1.0}]
    ex, events = _drive("sampling_multi_execute", {"samples": rows}, terminal="ERROR")

    assert "SAMPLING_VOLUME_CHAIN" in _fail_message(events)
    assert ex.calls == []


# --------------------------------------------------------------------------
# 6. 体积模型外提无回归: 单样品与多样品算出同一组常数
# --------------------------------------------------------------------------

def test_volume_model_extraction_keeps_single_sample_numbers():
    """sampling_execute 改调 sampling_volume_model 后, 下发给动作的体积逐字未变。"""
    ex, _ = _drive("sampling_execute", {"plate_spec": "4×6", "plate_no": "1", "well": "A1"})

    asp = ex.of("sampling.aspirate")
    bands = ex.of("sampling.spot_band_layer")
    assert asp[0]["sample_volume_ml"] == _ASPIRATE_TOTAL       # 首轮 V+E
    assert asp[1]["sample_volume_ml"] == _ASPIRATE_ROUND       # 润洗轮 R+E (缺省 rinse_rounds=1)
    assert all(b["spot_end_position_ml"] == _BAND_END for b in bands)
    # 几何未覆盖时保持"未给" -> 动作层走点表示教基准 (不能变成 0.0)
    assert all(b.get("x_start") is None and b.get("y_height") is None for b in bands)


def test_multi_execute_matches_single_sample_volumes_on_defaults():
    """同一组缺省参数下, 多样品每行算出的体积与单样品一致。"""
    ex, _ = _drive("sampling_multi_execute", {"samples": _ROWS3})

    for a in ex.of("sampling.aspirate"):
        assert a["sample_volume_ml"] in (_ASPIRATE_TOTAL, _ASPIRATE_ROUND)
    assert all(b["spot_end_position_ml"] == _BAND_END
               for b in ex.of("sampling.spot_band_layer"))


# --------------------------------------------------------------------------
# 7. 周期壳: 一次上下料, 中间点 N 带
# --------------------------------------------------------------------------

def test_multi_cycle_is_four_stage_with_one_load_unload():
    """多样品周期仍是四段骨架; 上下料各一次, samples 透传到执行段。"""
    doc = _doc("sampling_multi_cycle")
    scripts = [n.get("script") for n in doc["body"] if n.get("op") == "run_script"]
    assert scripts == ["sampling_prepare", "sampling_load",
                       "sampling_multi_execute", "sampling_unload"]

    execute_node = [n for n in doc["body"] if n.get("script") == "sampling_multi_execute"][0]
    assert execute_node["inputs"] == {"samples": {"var": "samples"}}

    # samples 必须是非旋钮入参: 若成了旋钮, 运行前覆盖会压过逐行值 (见流程文件头)
    for name in ("sampling_multi_cycle", "sampling_multi_execute"):
        vd = [v for v in _doc(name)["vars"] if v["name"] == "samples"][0]
        assert vd["io"] == "in" and "ui" not in vd, name


# --------------------------------------------------------------------------
# 8. 面板赖以工作的两条机制 (改坏了面板会静默失灵, 故在此钉住)
# --------------------------------------------------------------------------

def test_flow_defaults_are_overridable_by_name_from_the_cycle_entry():
    """面板把「流程缺省」当 overrides 发: 入口是 cycle 时也必须命中 execute 里的同名旋钮。

    缺省旋钮声明在 execute, 而 cycle 的 inputs 只认自己声明的变量 —— 若靠 inputs 传,
    「含上下料」模式下这些缺省会被静默丢弃, 面板上改的值一点不生效。overrides 按名注入
    到每一帧 (含深层子脚本), 正是为此。
    """
    from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides

    knobs = collect_knobs(_doc("sampling_multi_cycle"), _doc)
    names = {k["name"] for k in knobs}
    assert {"sample_volume_ml", "rinse_rounds", "over_aspirate_ml", "air_gap_ml"} <= names
    # 面板发的覆盖必须过得了运行前校验 (否则 API 直接 400 "未知旋钮")
    assert validate_overrides(knobs, {"sample_volume_ml": 3.0, "rinse_rounds": 0}) == []


def test_override_sets_the_default_but_row_value_still_wins():
    """覆盖设的是"缺省"层, 不是"逐行"层 —— 行内给了值仍以行内为准。

    注入发生在建帧时, 行内合并发生在 body 执行时 (在其后), 故顺序天然正确。
    这条一旦反过来, 面板上一个手滑就会把整张表压成同一个体积, 且不报错。
    """
    rows = [
        {"well": "A1", "x_start": 70.0, "x_end": 150.0, "y_height": -20.0},           # 吃缺省
        {"well": "A2", "x_start": 160.0, "x_end": 240.0, "y_height": -20.0,
         "sample_volume_ml": 1.0},                                                     # 行内覆盖
    ]
    ex, _ = _drive("sampling_multi_execute", {"samples": rows},
                   overrides={"sample_volume_ml": 4.0, "rinse_rounds": 0})

    asp = ex.of("sampling.aspirate")
    assert len(asp) == 2, ex.names()                       # rinse_rounds 覆盖成 0 -> 无润洗轮
    assert asp[0]["sample_volume_ml"] == 4.0 + 1.5         # 缺省被覆盖成 V=4
    assert asp[1]["sample_volume_ml"] == 1.0 + 1.5         # 行内 V=1 仍胜过覆盖
