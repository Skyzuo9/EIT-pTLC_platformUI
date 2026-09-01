"""PLC 编排说明书离线一致性测试 (漂移看门狗 · 离线层)
=====================================================
功能:
    校验 mock/behavior/specs/*.yaml 这份"从 CODESYS 逐字提取的工序记录"与仓库内
    另外两份真源不漂移:
      ① spec.station 集合 == runtime/bootstrap._ALL_L2_STATIONS (八个 L2 工位一个不缺);
      ② spec.accepts ⊇ config/actions/**/plc_*.yaml 声明的该工位全部动作码
         (spec 可以多 —— 派发器接受但上位机没暴露的码是真实存在的, 如 PhotoScrape 36/51);
      ③ 每个动作五要素齐全 (锚点/段号表/互锁门/错误码/时序常量的容器), sha256 是 64 位十六进制;
      ④ 常量取值合理 (正数时长/毫米), 动作 kind 在闭集内;
      ⑤ 加载器的双射校验生效 (accepts 与 actions 键互为子集)。

    **本测试抓的是仓库内三方漂移, 抓不了 PLC 端的改动** —— 那要跑在线层
    `python -m eit_ptlc.tools.plc_spec_drift` (经文件 IPC 拉现役 ST 重算哈希比对)。
    诚实地写在这里, 免得有人以为绿灯就等于"与真机一致"。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_plc_spec_offline.py -q
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from eit_ptlc.mock.behavior.spec_loader import KINDS, load_all_specs, load_station_spec
from eit_ptlc.runtime.bootstrap import _ALL_L2_STATIONS

_CONFIG_ACTIONS = Path(__file__).resolve().parent.parent / "config" / "actions"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _norm_station(name: str) -> str:
    """工位名归一: 大小写与下划线都不算差异.

    三处写法并存且都是既有事实: spec 用 L2 前缀原名 StagingA, plc_*.yaml 写
    staging_a, 单点面板键写 staginga (models.MANUAL_STATIONS 的注释点过这件事)。
    """
    return str(name or "").lower().replace("_", "")


def _host_action_codes() -> dict:
    """读 config/actions/**/plc_*.yaml, 返回 {归一工位名: {动作码: 动作名}}."""
    out: dict = {}
    for path in sorted(_CONFIG_ACTIONS.rglob("plc_*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for action_name, body in doc.items():
            if not isinstance(body, dict):
                continue
            station = _norm_station(body.get("station"))
            code = body.get("action_code")
            if not station or code is None:
                continue
            out.setdefault(station, {})[int(code)] = action_name
    return out


class TestSpecCoverage(unittest.TestCase):
    """spec 与两份真源的覆盖关系."""

    @classmethod
    def setUpClass(cls):
        cls.specs = load_all_specs()
        cls.host = _host_action_codes()

    def test_every_l2_station_has_a_spec(self):
        """八个 L2 工位一个不缺 —— 少一个就意味着那个工位的行为无据可依."""
        self.assertEqual(sorted(self.specs), sorted(_ALL_L2_STATIONS))

    def test_spec_accepts_cover_all_host_action_codes(self):
        """上位机声明的每个动作码都必须在 spec 的 accepts 里.

        反向不要求相等: 派发器可能接受上位机没暴露的码 (PhotoScrape 36/51 即如此),
        那是真机事实, 记下来比抹掉好。
        """
        for station, spec in self.specs.items():
            host_codes = set(self.host.get(_norm_station(station), {}))
            missing = sorted(host_codes - set(spec.accepts))
            self.assertEqual(
                missing, [],
                f"{station}: 上位机声明了 {missing} 但 spec.accepts 没有 —— "
                f"要么 spec 提取漏了, 要么派发器根本不收该码 (那是上位机的 bug)")

    def test_host_declares_no_unknown_station(self):
        """plc_*.yaml 里的 station 值必须都能对上某个 spec 工位 (拼错即静默失联)."""
        known = {_norm_station(station) for station in self.specs}
        unknown = sorted(set(self.host) - known)
        self.assertEqual(unknown, [], f"plc_*.yaml 出现未知工位: {unknown}")


class TestSpecShape(unittest.TestCase):
    """每份 spec 的结构完整性."""

    @classmethod
    def setUpClass(cls):
        cls.specs = load_all_specs()

    def test_dispatcher_anchor_and_reject_code(self):
        for station, spec in self.specs.items():
            with self.subTest(station=station):
                self.assertTrue(spec.dispatcher_pou.startswith("Application/"),
                                f"{station}: 派发器 POU 路径应以 Application/ 开头")
                self.assertRegex(spec.dispatcher_sha256, _SHA_RE)
                self.assertGreater(spec.unknown_code_error, 0,
                                   f"{station}: 未知码必须有拒绝码 (沙盒据此回 REJECTED)")
                self.assertEqual(spec.codesys_project, "20260702.project")

    def test_actions_have_five_elements(self):
        """五要素: 锚点 / 段号表 / 互锁门 / 错误码 / kind+摘要."""
        for station, spec in self.specs.items():
            for code, action in spec.actions.items():
                with self.subTest(station=station, code=code):
                    self.assertRegex(action.sha256, _SHA_RE)
                    self.assertTrue(action.pou.startswith("Application/"))
                    self.assertIn(action.kind, KINDS)
                    self.assertTrue(action.summary.strip(), "摘要不许空")
                    self.assertTrue(action.notes.strip(),
                                    "notes 是行为层的照抄依据, 不许空")
                    for item in action.steps:
                        self.assertIsInstance(item["step"], int)
                        self.assertTrue(item["phase"], "段号必须带阶段名")
                    for error_code in action.errors:
                        self.assertGreater(error_code, 0)

    def test_duration_constants_are_positive(self):
        """**时长**常量必须为正 —— 0 或负的时长一定是抄错了.

        只判时长 (名字以 _s / _ms 结尾)。位置类常量刻意不判: 零位 (photo_8y_home=0)、
        负位移 (feed_lower_rel_mm=-5.0)、空集窗占位 (ALIGN_X_WIN_MAX=-1.0)、
        帧变换原点 (ALIGN_FRAME_OY=0) 全都是现役事实, 拿"必须为正"去卡它们
        等于逼着后来者篡改提取结果。
        """
        for station, spec in self.specs.items():
            for name, value in spec.constants.items():
                if not isinstance(value, (int, float)):
                    continue
                if not name.endswith(("_s", "_ms")):
                    continue
                with self.subTest(station=station, constant=name):
                    self.assertGreater(value, 0, f"{station}.{name} 是时长, 应为正数")

    def test_step_values_unique_within_action(self):
        """同一动作的段号表不该重复列同一个值 (重复即抄两遍)."""
        for station, spec in self.specs.items():
            for code, action in spec.actions.items():
                values = [item["step"] for item in action.steps]
                with self.subTest(station=station, code=code):
                    self.assertEqual(len(values), len(set(values)),
                                     f"{station}/{code}: 段号表有重复值 {values}")

    def test_anchor_sha_unique_per_pou(self):
        """同一 POU 在一份 spec 里的哈希必须一致 (内联动作共用派发器锚点是常态)."""
        for station, spec in self.specs.items():
            by_pou: dict = {}
            for action in spec.actions.values():
                previous = by_pou.setdefault(action.pou, action.sha256)
                with self.subTest(station=station, pou=action.pou):
                    self.assertEqual(previous, action.sha256,
                                     f"{station}: {action.pou} 出现两个不同哈希")


class TestFeedLiftSpecFacts(unittest.TestCase):
    """FeedLift 的关键事实钉死 (第一目标流程 sampling_load 全靠它)."""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_station_spec("FeedLift")

    def test_dispatcher_accepts_ten_and_thirteen(self):
        """现役派发器收 10/13 —— 仓库内旧 xml 快照只收 5 个码, 以现役为准 (2026-08-10 裁决)."""
        self.assertEqual(list(self.spec.accepts), [10, 11, 12, 13, 21, 22, 91])

    def test_stable_confirm_is_300ms_but_debug_is_200ms(self):
        """稳定确认统一 300ms; A91 调试确认刻意 200ms, 不许统一."""
        self.assertEqual(self.spec.constants["stable_confirm_ms"], 300)
        self.assertEqual(self.spec.constants["debug_stable_ms"], 200)

    def test_feed_clear_gate_has_no_feed_sensor(self):
        """A13 的门刻意不查上料进料传感器 (空仓标定第一组正需要它能跑)."""
        clear_gate = self.spec.action(13).gate
        raise_gate = self.spec.action(11).gate
        self.assertIn("feed_sensor", raise_gate)
        self.assertNotIn("feed_sensor", clear_gate)
        self.assertIn(307, self.spec.action(13).errors)
        self.assertIn(304, self.spec.action(11).errors)

    def test_search_actions_declare_recapture_limits(self):
        """四个搜索动作共用重捕获上限常量 (2.0mm x 2 次)."""
        self.assertEqual(self.spec.constants["recapture_max_mm"], 2.0)
        self.assertEqual(self.spec.constants["recapture_max_count"], 2)
        for code in (11, 13, 21, 22):
            self.assertEqual(self.spec.action(code).kind, "jog_search")


if __name__ == "__main__":
    unittest.main(verbosity=2)
