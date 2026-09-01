"""运行前旋钮覆盖 (knob override) 离线测试
==========================================
功能:
    验证"运行前把一张覆盖 map 在建帧时按名注入"的核心机制 (不接硬件):
      - 深层子脚本的旋钮被覆盖命中 (零逐层 inputs 透传);
      - 非旋钮 in var (无 ui) / 常量 / scratch 不被覆盖误伤 (保 batch 逐行差异);
      - 覆盖值经类型 coerce (字符串 "3" -> INT 3);
      - LIST 旋钮 + for 循环驱动多实例 (lanes 表), 逐行 vol 经 field 提取不被全局覆盖冲刷;
      - collect_knobs 静态收集 (去重 + 深度) 与 validate_overrides 运行前校验。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_knob_override_offline
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides
from eit_ptlc.operation.vm.state import VmStatus
from eit_ptlc.operation.vm.thread import VmThread


class FakeExecutor:
    """假执行器: 记录调用; 恒返回 DONE."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        self.calls.append((name, params))
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE, accepted=True,
                            message="ok", result={"echo": params})


def script(name, variables, body, *, label=None):
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": name, "label": label or name,
            "vars": variables, "body": body}


def var(name, vtype, io, default, *, ui=None, scope="local"):
    vd = {"name": name, "scope": scope, "type": vtype, "io": io, "default": default}
    if ui is not None:
        vd["ui"] = ui
    return vd


def arg_seq(ex, action, key):
    return [c[1].get(key) for c in ex.calls if c[0] == action]


# --- 固定脚本树: root -> mid -> leaf (leaf 处 3 层深) -------------------------
# leaf 有旋钮 cleaning_count (in+ui) 与非旋钮 well (in, 无 ui, 由 mid 经 inputs 喂 "B2")。
LEAF = script("knob_leaf",
              [var("cleaning_count", "INT", "in", 1, ui={"label": "清洗次数", "min": 1, "max": 20}),
               var("well", "STRING", "in", "A1")],
              [{"op": "call", "action": "CLEAN",
                "args": {"n": {"var": "cleaning_count"}, "w": {"var": "well"}}}])
MID = script("knob_mid", [],
             [{"op": "run_script", "script": "knob_leaf", "inputs": {"well": {"lit": "B2"}}}])
ROOT = script("knob_root", [], [{"op": "run_script", "script": "knob_mid"}])

# --- LIST 批次: lanes 表 (in+ui) 驱动 for; 逐行 vol 经 field 提取, 非旋钮不被全局覆盖 ----
LANE_EXEC = script("lane_exec", [var("vol", "FLOAT", "in", 0.0)],
                   [{"op": "call", "action": "SPOT", "args": {"v": {"var": "vol"}}}])
LANE_BATCH = script("lane_batch",
                    [var("lanes", "LIST", "in", [], ui={"label": "lane 表"}),
                     var("lane", "DICT", "var", {})],
                    [{"op": "for", "var": "lane", "in": {"var": "lanes"},
                      "body": [{"op": "run_script", "script": "lane_exec",
                                "inputs": {"vol": {"field": {"var": "lane"}, "name": "vol"}}}]}])

_DOCS = {d["name"]: d for d in (ROOT, MID, LEAF, LANE_EXEC, LANE_BATCH)}


def _resolve(name):
    return _DOCS[name]


async def _run() -> int:
    failures: list[str] = []
    tally = {"n": 0}

    def check(name, cond, detail=""):
        tally["n"] += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) 基线: 无覆盖 -> 深层旋钮取默认 1, well 取 mid 经 inputs 喂的 "B2"
    ex = FakeExecutor()
    t = VmThread(ROOT, executor=ex, res_gate=ResourceGate(), resolve_script=_resolve)
    st = await t.run()
    check("baseline_default", st is VmStatus.DONE and arg_seq(ex, "CLEAN", "n") == [1]
          and arg_seq(ex, "CLEAN", "w") == ["B2"], f"{st} {ex.calls}")

    # 2) 覆盖命中 3 层深子脚本旋钮 (零逐层 inputs 透传); 值经 coerce ("3" -> 3)
    ex = FakeExecutor()
    t = VmThread(ROOT, executor=ex, res_gate=ResourceGate(), resolve_script=_resolve,
                 overrides={"cleaning_count": "3"})
    await t.run()
    check("override_deep_frame", arg_seq(ex, "CLEAN", "n") == [3], arg_seq(ex, "CLEAN", "n"))

    # 3) 非旋钮 in var (well 无 ui) 不被同名覆盖误伤 -> 仍是 inputs 喂的 "B2"
    ex = FakeExecutor()
    t = VmThread(ROOT, executor=ex, res_gate=ResourceGate(), resolve_script=_resolve,
                 overrides={"well": "ZZ", "cleaning_count": 5})
    await t.run()
    check("non_knob_untouched", arg_seq(ex, "CLEAN", "w") == ["B2"]
          and arg_seq(ex, "CLEAN", "n") == [5], ex.calls)

    # 4) 常量不被覆盖 (io=const 非旋钮): 声明同名 const, 覆盖应被忽略且不报"写常量"错
    konst = script("konst", [var("K", "INT", "const", 7)],
                   [{"op": "call", "action": "A", "args": {"k": {"var": "K"}}}])
    ex = FakeExecutor()
    t = VmThread(konst, executor=ex, res_gate=ResourceGate(), overrides={"K": 99})
    st = await t.run()
    check("const_untouched", st is VmStatus.DONE and arg_seq(ex, "A", "k") == [7], f"{st} {ex.calls}")

    # 5) LIST 旋钮驱动 for 循环轮数; 逐行 vol 经 field 提取, 各不相同 (非旋钮不被全局冲刷)
    ex = FakeExecutor()
    t = VmThread(LANE_BATCH, executor=ex, res_gate=ResourceGate(), resolve_script=_resolve,
                 overrides={"lanes": [{"vol": 1.0}, {"vol": 2.0}, {"vol": 3.0}]})
    await t.run()
    check("list_knob_drives_loop", arg_seq(ex, "SPOT", "v") == [1.0, 2.0, 3.0], arg_seq(ex, "SPOT", "v"))

    # 6) collect_knobs: 从 ROOT 静态收集到深层旋钮 cleaning_count, 且 well (无 ui) 不入集
    knobs = collect_knobs(ROOT, _resolve)
    names = sorted(k["name"] for k in knobs)
    cc = next((k for k in knobs if k["name"] == "cleaning_count"), None)
    check("collect_finds_deep_knob", names == ["cleaning_count"]
          and cc is not None and cc["type"] == "INT" and cc["ui"].get("max") == 20
          and cc["script"] == "knob_leaf", f"{names} {cc}")

    # 7) collect_knobs 去重: 同名旋钮两处声明 -> 一项, 记录两条 paths
    dupA = script("dupA", [var("g", "INT", "in", 1, ui={"label": "g"})],
                  [{"op": "run_script", "script": "dupB"}])
    dupB = script("dupB", [var("g", "INT", "in", 2, ui={"label": "g"})], [])
    knobs2 = collect_knobs(dupA, lambda n: {"dupB": dupB}[n])
    g = knobs2[0] if knobs2 else None
    check("collect_dedup_by_name", len(knobs2) == 1 and g["name"] == "g"
          and len(g["paths"]) == 2, knobs2)

    # 8) validate_overrides: 越界/未知键/枚举拒, 合法过
    ok = validate_overrides(knobs, {"cleaning_count": 10})
    over = validate_overrides(knobs, {"cleaning_count": 99})
    unk = validate_overrides(knobs, {"nope": 1})
    check("validate_in_range_ok", ok == [], ok)
    check("validate_over_max_rejected", any("超过上限" in e for e in over), over)
    check("validate_unknown_rejected", any("未知旋钮" in e for e in unk), unk)

    enum_knob = [{"name": "mode", "type": "STRING", "ui": {"enum": ["a", "b"]}}]
    check("validate_enum_rejected", validate_overrides(enum_knob, {"mode": "z"}) != []
          and validate_overrides(enum_knob, {"mode": "a"}) == [], "enum")

    # 9) 无 default 的旋钮 (点样几何型): 未覆盖 → 调用收到 None (base-by-read, 非零值默认); 覆盖 → 具体浮点。
    #    这是第二步的关键修复: thread._make_frame 对"无 default 旋钮"落 None 而非 coerce_value 的 0.0,
    #    否则每轮都会把 x_start=0.0 当有效覆盖冲掉点表示教基准。
    GEO = script("geo_exec",
                 [var("gx", "FLOAT", "in", None,
                      ui={"label": "点样X起点", "min": -500.0, "max": 500.0, "live_from": "spot_pose.x_start"})],
                 [{"op": "call", "action": "sampling.spot_band_layer", "args": {"x_start": {"var": "gx"}}}],
                 label="上样-执行")
    ex = FakeExecutor()
    t = VmThread(GEO, executor=ex, res_gate=ResourceGate())
    await t.run()
    check("nodefault_knob_none_when_unset",
          arg_seq(ex, "sampling.spot_band_layer", "x_start") == [None],
          arg_seq(ex, "sampling.spot_band_layer", "x_start"))
    ex = FakeExecutor()
    t = VmThread(GEO, executor=ex, res_gate=ResourceGate(), overrides={"gx": "123.5"})
    await t.run()
    check("nodefault_knob_override_applies",
          arg_seq(ex, "sampling.spot_band_layer", "x_start") == [123.5],
          arg_seq(ex, "sampling.spot_band_layer", "x_start"))

    # 10) collect_knobs 附 action 关联 (下钻树) + live_from 解析 (面板预填当前示教基准)
    class _FakePts:
        def composite_entry(self, key):
            if key != "spot_pose":
                return None
            return SimpleNamespace(members=[SimpleNamespace(key="x_start", value=70.0),
                                            SimpleNamespace(key="x_end", value=240.0),
                                            SimpleNamespace(key="y_height", value=-20.0)])

    kg = collect_knobs(GEO, lambda n: {}[n],
                       resolve_action_label=lambda a: "上样-单条带点样吹干" if a == "sampling.spot_band_layer" else a,
                       points=_FakePts())[0]
    check("knob_action_assoc",
          kg["actions"] == [{"name": "sampling.spot_band_layer", "label": "上样-单条带点样吹干"}], kg.get("actions"))
    check("knob_live_from_resolved", kg["live"] == 70.0, kg.get("live"))
    kg_nopts = collect_knobs(GEO, lambda n: {}[n])[0]
    check("knob_live_none_without_points",
          kg_nopts["live"] is None
          and kg_nopts["actions"] == [{"name": "sampling.spot_band_layer", "label": "sampling.spot_band_layer"}],
          kg_nopts)

    print(f"\n共 {tally['n']} 组用例, 失败 {len(failures)}")
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
