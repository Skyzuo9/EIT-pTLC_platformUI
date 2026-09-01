"""工站初始化离线测试
======================
功能:
    覆盖单工站初始化 (POST /api/plc/stations/{station}/init) 与全工站一键初始化
    (POST /api/plc/stations/init_all) 的契约与端到端行为.

    四条容易回归、且回归后现场表现很隐蔽的不变量:
    1. feedlift.init 的动作码必须是 10 且与 PLC 侧 A10_init_初始化 对齐 —— 写错码
       PLC 只会回 101 未知码 REJECTED, 看着像"初始化没生效"而不像配置错.
    2. 初始化不做 DEBUG 门控 (与工位复位相反) —— 初始化是每天开机的正常操作.
       这两个端点门控口径不同, 很容易在后续重构里被"统一"掉.
    3. 遇错继续汇总: 某站失败时其余站仍要跑完, 且失败站要被点名 —— 若退化成
       fail-fast, 现场就得反复重跑才能发现第二个故障站.
    4. 泵总线切分: sampling/develop/collect 三站的 init 必须落在**同一条**并行分支里.
       这条最隐蔽 —— 拆散了脚本照样通过校验、sim 照样全绿, 只有真机会串 485.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m unittest eit_ptlc.tests.test_station_init_offline -v
"""

from __future__ import annotations

import functools
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import eit_ptlc.runtime.bootstrap as bootstrap
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.operation.vm.schema import validate_script

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
_ACTIONS_DIR = _CONFIG_DIR / "actions"
_INIT_ALL_SCRIPT = _CONFIG_DIR / "operation" / "00_system" / "system_init_all.yaml"

# 有 init 动作的工位 (station -> 该工位 init 会跑几条动作)。展缸的 init 是按缸的,
# 整站初始化须逐缸跑一遍, 故 8 条; 其余工位 1 条。
_INIT_STATIONS = {"photoscrape": 1, "sampling": 1, "develop": 8, "collect": 1, "feedlift": 1}
# 无 init 动作的工位: 目标态动作, 本就不需要初始化 (端点应 404 而非假装成功)
_NO_INIT_STATIONS = ("pump", "rail", "staging_a")
# 共用同一条注射泵 485 总线的工位 (PLC 侧 转发转存/%MW1300 是全站唯一一套收发缓冲):
#   Sampling A10 -> /4Z…  Develop A10 -> /1Z…或/2Z…  Collect A10 -> /3Z…
# 三者的 init 必须顺序执行, 故必须同处一条并行分支。
_PUMP_BUS_INITS = ("sampling.init", "develop.init", "collect.init")


def _collect_calls(block):
    """递归收集一个块内所有 call 节点的 action 名.

    branches 是 list-of-blocks (与 body/then/else 等 list-of-nodes 不同), 单独展开;
    漏了它, 改成并行后的脚本会被误判成"漏了某个工位"。
    """
    found = set()
    for node in block or []:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "call":
            found.add(node.get("action"))
        for key in ("body", "then", "else", "finally"):
            found |= _collect_calls(node.get(key))
        for handler in node.get("catch", []) or []:
            found |= _collect_calls(handler.get("body"))
        for branch in node.get("elifs", []) or []:
            found |= _collect_calls(branch.get("body"))
        for br in node.get("branches", []) or []:   # parallel: 每个 br 本身就是一个块
            found |= _collect_calls(br)
    return found


def _find_parallels(block):
    """递归找出块内所有 parallel 节点 (含嵌套)."""
    found = []
    for node in block or []:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "parallel":
            found.append(node)
        for key in ("body", "then", "else", "finally"):
            found += _find_parallels(node.get(key))
        for handler in node.get("catch", []) or []:
            found += _find_parallels(handler.get("body"))
        for branch in node.get("elifs", []) or []:
            found += _find_parallels(branch.get("body"))
        for br in node.get("branches", []) or []:
            found += _find_parallels(br)
    return found


class TestInitContract(unittest.TestCase):
    """动作目录与编排脚本的静态契约 (不起服, 不连 PLC)."""

    @classmethod
    def setUpClass(cls):
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.action_names = {d.name for d in cls.registry.list()}

    def test_feedlift_init_matches_plc_action_code(self):
        """feedlift.init 存在且 (station, action_code) 与 PLC A10_init_初始化 对齐."""
        adef = self.registry.get("feedlift.init")
        self.assertEqual(adef.kind, "plc_l2")
        self.assertEqual(adef.station, "feedlift")
        self.assertEqual(adef.action_code, 10)
        # modes 为空 = RUN/DEBUG 均可; 初始化是常规开机操作, 不该被限成 DEBUG-only
        self.assertEqual(tuple(adef.modes), ())

    def test_every_init_station_has_action(self):
        """_INIT_STATIONS 里每个工位都真有 init 动作, 且无 init 的工位确实没有."""
        for station in _INIT_STATIONS:
            self.assertIn(f"{station}.init", self.action_names, f"{station} 缺 init 动作")
        for station in _NO_INIT_STATIONS:
            self.assertNotIn(f"{station}.init", self.action_names,
                             f"{station} 多了 init 动作, 请同步更新路由的 404 说明与本测试")

    def test_init_all_script_validates(self):
        """全工站初始化脚本通过 VM 校验, 且覆盖全部五个有 init 的工位."""
        doc = yaml.safe_load(_INIT_ALL_SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(validate_script(doc, valid_actions=self.action_names), [])
        called = _collect_calls(doc.get("body"))
        for station in _INIT_STATIONS:
            self.assertIn(f"{station}.init", called, f"全工站初始化漏了 {station}")
        # 只读安全预检: 各站 init 都没有 safety_anchor 硬门, 而 photoscrape.init 要动三根轴,
        # 故脚本自己必须校验臂在 P1。用 require_anchor (只读) 而非 home_ensure (会 move_j)。
        self.assertIn("robot.require_anchor", called, "全工站初始化缺机械臂安全位预检")
        self.assertNotIn("robot.home_ensure", called, "全工站初始化不应擅自动臂")
        # 资源钩子不得进初始化: 单独调会掐掉在跑流程仍在用的真空
        self.assertNotIn("pump.vacuum_on", called)
        self.assertNotIn("pump.vacuum_off", called)

    def test_pump_bus_stations_stay_in_one_branch(self):
        """共用 485 总线的三站 init 必须落在同一条并行分支里 (顺序即互斥).

        为什么锁这条: PLC 的 转发转存 / %MW1300 / 接收字符 是全站唯一一套串口收发缓冲,
        1~4 号注射泵挂同一条 485。Sampling A10 发 /4Z…、Develop A10 发 /1Z…或/2Z…、
        Collect A10 发 /3Z…, 三者都靠全局 泵站位符 互斥。把它们拆到不同分支并发跑:
          - 一秒都省不到 —— 后到者只会卡在自己的 step0 自旋等锁;
          - 却要承担 %MX2005.5 ("泵空闲"位, 不区分是哪台泵) 在多站交替持有总线时的
            边沿归属风险。
        零收益 + 非零风险。而且拆散后脚本照样通过 validate_script、sim 照样全绿,
        只有真机才会串线 —— 所以必须在这里拦住。
        """
        doc = yaml.safe_load(_INIT_ALL_SCRIPT.read_text(encoding="utf-8"))
        parallels = _find_parallels(doc.get("body"))
        self.assertTrue(parallels, "全工站初始化应并行执行 (未找到 op: parallel)")

        for par in parallels:
            branches = par.get("branches") or []
            holders = [i for i, br in enumerate(branches)
                       if _collect_calls(br) & set(_PUMP_BUS_INITS)]
            self.assertLessEqual(
                len(holders), 1,
                f"泵总线三站被拆到了 {len(holders)} 条并行分支 (分支号 {holders}); "
                f"{'/'.join(_PUMP_BUS_INITS)} 共用同一条 485, 必须同处一支顺序执行")
            if holders:
                # 落在同一支里, 就得三站齐全 —— 少一站说明有人被挪到了并行的别处
                self.assertEqual(
                    _collect_calls(branches[holders[0]]) & set(_PUMP_BUS_INITS),
                    set(_PUMP_BUS_INITS),
                    f"泵总线支缺站: 期望 {set(_PUMP_BUS_INITS)} 全在分支 {holders[0]} 内")

    def test_develop_tanks_stay_sequential(self):
        """展缸逐缸 init 必须留在 for 循环里, 不得摊平成并行.

        8 个缸共用同一个 Develop_L2 状态机 (同为动作码 10, 靠 Expand_Target_Tank 选缸),
        上位机侧 plc_controller 还按工位前缀加了锁 —— 并了只是在这两处排队, 零收益。
        """
        doc = yaml.safe_load(_INIT_ALL_SCRIPT.read_text(encoding="utf-8"))

        def under_for(block):
            """block 内的 develop.init 是否全部处于某个 op: for 之下."""
            for node in block or []:
                if not isinstance(node, dict):
                    continue
                if node.get("op") == "for" and "develop.init" in _collect_calls(node.get("body")):
                    return True
                for key in ("body", "then", "else", "finally"):
                    if under_for(node.get(key)):
                        return True
                for handler in node.get("catch", []) or []:
                    if under_for(handler.get("body")):
                        return True
                for br in node.get("branches", []) or []:
                    if under_for(br):
                        return True
            return False

        self.assertTrue(under_for(doc.get("body")),
                        "develop.init 不在 for 循环下 —— 展缸 8 缸不可并行, 见 Develop_L2 单状态机")


class TestInitEndpoints(unittest.TestCase):
    """sim 装配下的端到端行为 (真起内存 OPC UA + 八工位 L2 状态机)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-init-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url="opc.tcp://127.0.0.1:48486/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()

    def test_each_station_inits_alone(self):
        """每个有 init 的工位都能单独初始化; 展缸逐缸跑出 8 条 result."""
        with TestClient(self._app) as client:
            for station, expected in _INIT_STATIONS.items():
                resp = client.post(f"/api/plc/stations/{station}/init")
                self.assertEqual(resp.status_code, 200, f"{station}: {resp.text}")
                body = resp.json()
                self.assertTrue(body["ok"], f"{station} 初始化未成功: {body}")
                self.assertEqual(len(body["results"]), expected, f"{station} 动作条数不符")
                for item in body["results"]:
                    self.assertEqual(item["status"], "DONE")

    def test_station_without_init_returns_404(self):
        """泵站/地轨/中转A 没有 init 动作: 404 且说明原因, 不能静默成功."""
        with TestClient(self._app) as client:
            for station in _NO_INIT_STATIONS:
                resp = client.post(f"/api/plc/stations/{station}/init")
                self.assertEqual(resp.status_code, 404, f"{station}: {resp.text}")
                self.assertIn("没有初始化动作", resp.json()["detail"])

    def test_init_allowed_in_run_while_reset_stays_debug_only(self):
        """RUN 下初始化可用、复位被拒 —— 两个端点门控口径不同, 这条锁住它."""
        with TestClient(self._app) as client:
            self.assertEqual(
                client.post("/api/mode", json={"control_mode": "RUN"}).status_code, 200)
            try:
                self.assertEqual(
                    client.post("/api/plc/stations/feedlift/init").status_code, 200)
                self.assertEqual(
                    client.post("/api/plc/stations/feedlift/reset").status_code, 403)
            finally:
                client.post("/api/mode", json={"control_mode": "DEBUG"})

    def test_init_all_runs_every_station(self):
        """全工站初始化跑到 DONE 并留下 run_id (走 VM 才有运行历史可回放)."""
        with TestClient(self._app) as client:
            resp = client.post("/api/plc/stations/init_all")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["status"], "DONE")
            self.assertTrue(body["run_id"])


class TestInitAllAggregatesFailures(unittest.TestCase):
    """注入某工位故障, 验证"遇错继续跑完再汇总"而不是 fail-fast.

    单列一个类是因为要换掉 mock 的工位状态机装配: 给 Develop 的动作码 10 注入 ERROR,
    这必须在 create_sim_app 之前 patch, 与上面共用 app 的用例不能混在一个装配里。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-init-fail-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        cls._orig_fsm = bootstrap.run_l2_fsm
        bootstrap._DATA_DIR = Path(cls._tmp.name)

        @functools.wraps(cls._orig_fsm)
        def _fsm(server, prefix, stop_event, **kw):
            # 展缸初始化必失败, 其余工位照常 —— 用来验证失败不会带掉后面的工位
            if prefix == "Develop":
                kw.setdefault("error_codes", (10,))
            return cls._orig_fsm(server, prefix, stop_event, **kw)

        bootstrap.run_l2_fsm = _fsm
        cls._app = bootstrap.create_sim_app(
            opcua_url="opc.tcp://127.0.0.1:48487/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap.run_l2_fsm = cls._orig_fsm
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()

    def test_failed_station_is_named_and_others_still_run(self):
        with TestClient(self._app) as client:
            # 先确认注入生效: 展缸单独初始化确实失败
            solo = client.post("/api/plc/stations/develop/init").json()
            self.assertFalse(solo["ok"], "故障注入没生效, 后面的断言会失去意义")

            resp = client.post("/api/plc/stations/init_all")
            self.assertEqual(resp.status_code, 422, resp.text)
            detail = resp.json()["detail"]
            self.assertIn("展开缸", detail, f"失败站没被点名: {detail}")
            self.assertIn("run_id", detail)

            # 关键: 展缸之后的两站 (收集/上下料升降) 仍要跑完 —— fail-fast 会漏掉它们。
            # 逐缸 try 也要生效: 八个缸都该被点名, 而不是第一个缸就带掉整段。
            self.assertEqual(detail.count("展开缸"), 8, f"逐缸 try 未生效: {detail}")
            for station in ("collect", "feedlift"):
                self.assertTrue(
                    client.post(f"/api/plc/stations/{station}/init").json()["ok"],
                    f"{station} 在展缸失败后应仍可初始化")


if __name__ == "__main__":
    unittest.main()
