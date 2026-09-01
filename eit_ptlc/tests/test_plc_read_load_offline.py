#!/usr/bin/env python3
"""PLC 读取负载与断连churn 回归测试 (对 Mock 服务器)
====================================================
背景:
    现场上位机反复打两类日志 ——
        [PLC] 调用侧先于心跳发现连接断开: ConnectionError: client is disconnected
        asyncua ... UaError: No request found for request id: NNNN, pending are {...}
    根因链: (1) 未下装符号 (节点表标 optional 的镜像, 如 Sampling_5Z_ActPos) 被遥测每秒读一次,
    每次都重走一遍容器浏览去确认它不存在 —— 每秒几百次串行往返的自伤负载; (2) 工位快照逐字段
    读, 8 字段 × 8 工位并发; 两者一起把 PLC 服务端压过 asyncua 的链路探测超时, 整条会话被判死;
    (3) 驱动重连时先 disconnect 旧 client, 而 asyncua 在 socket 仍开着时就清空了待应答表,
    并发协程手里那些绑定旧 session 的 Node 又继续发请求 —— 撞出上面那条 request id 报错。

本测试锁死修复后的三条性质 (都是"往返次数"层面的断言, 不是行为层面, 因为退化回旧实现时
行为完全正确、只有负载爆炸):
    1. 未下装符号只解析一次, 之后零往返 (负缓存);
    2. 工位快照一次批读拿全 8 个字段 (一次 Read service, 不是 8 次);
    3. 重连后节点缓存整体重建, 不留绑定旧 session 的 Node。

运行:
    & "C:/ProgramData/miniforge3/envs/eit_lab/python.exe" -m pytest \
        eit_ptlc/tests/test_plc_read_load_offline.py -q
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_plc_nodes          # noqa: E402
from eit_ptlc.controller.plc_controller import PlcController  # noqa: E402
from eit_ptlc.driver import opcua_driver as od_mod         # noqa: E402
from eit_ptlc.driver.opcua_driver import OpcUaDriver       # noqa: E402
from eit_ptlc.mock.plc_server import build_mock_server     # noqa: E402

_URL = "opc.tcp://127.0.0.1:48479/eit_ptlc/loadtest/"
_NODES = _PKG / "config" / "plc_nodes.yaml"

# 节点表与 mock 都不会有的名字: 用来触发"未下装符号"这条路径
_ABSENT = "Definitely_Not_A_PLC_Variable_XYZ"
_L2_FIELDS = ("State", "ActiveCode", "AcceptedSeq", "CompletedSeq",
              "Step", "ErrorCode", "SafeState", "Retryable")


class _Counter:
    """把模块级协程函数包一层计数, 用完可还原 (测的是往返次数, 只能从这里数)."""

    def __init__(self, module: object, attr: str) -> None:
        self._module = module
        self._attr = attr
        self._orig = getattr(module, attr)
        self.calls = 0

        async def _wrapped(*a, **kw):
            self.calls += 1
            return await self._orig(*a, **kw)

        setattr(module, attr, _wrapped)

    def restore(self) -> None:
        setattr(self._module, self._attr, self._orig)


class PlcReadLoadTest(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.node_map = load_plc_nodes(_NODES)
        self.server = await build_mock_server(_URL, self.node_map)
        await self.server.__aenter__()
        self.driver = OpcUaDriver(_URL, self.node_map, reconnect_wait_timeout=15.0)
        await self.driver.connect()

    async def asyncTearDown(self) -> None:
        try:
            await self.driver.disconnect()
        finally:
            await self.server.__aexit__(None, None, None)

    # ── 1. 负缓存: 未下装符号只解析一次 ──────────────────────────────────
    async def test_absent_symbol_resolved_once_then_zero_roundtrips(self):
        """未下装符号第一次读会浏览容器, 之后必须零往返直接抛。

        退化回旧实现时本用例会看到 resolve 次数 == 读取次数 —— 那正是遥测 1Hz 打在
        PLC 上的 browse 风暴。
        """
        counter = _Counter(od_mod, "resolve_gvl_node")
        try:
            for i in range(5):
                with self.assertRaises(KeyError, msg=f"第 {i + 1} 次读应抛 KeyError"):
                    await self.driver.read_variable(_ABSENT)
            self.assertEqual(counter.calls, 1,
                             f"未下装符号只该解析一次, 实际解析了 {counter.calls} 次 (负缓存失效)")
        finally:
            counter.restore()
        self.assertIsNotNone(self.driver.missing_reason(_ABSENT),
                             "解析失败后应记入负缓存并可查到原因")

    async def test_optional_node_absent_at_connect_costs_no_roundtrip(self):
        """节点表声明、PLC 端没有的变量, 连接后**首读**就该零往返。

        这正是现场 Sampling_5Z_ActPos 的处境 (plc_nodes.yaml 标 optional, PLC 未下装)。
        _cache_nodes 在连接时已经算出了缺失清单, 负缓存必须在那时预置好 —— 若要等第一次读
        失败才建, 遥测第一轮仍会付一整趟容器浏览的代价。

        Mock 是照 node_map 建节点的, 所以这里反过来: 服务器用"少一个变量"的表建,
        驱动用完整表连 —— 精确复现"节点表比 PLC 多一个符号"。
        """
        import dataclasses

        victim = "Sampling_5Z_ActPos"
        self.assertIn(victim, self.node_map.nodes, "样本节点应在节点表里")
        server_map = dataclasses.replace(
            self.node_map,
            nodes={k: v for k, v in self.node_map.nodes.items() if k != victim})

        # 用同一端口重开一台"缺这个符号"的 mock
        await self.driver.disconnect()
        await self.server.__aexit__(None, None, None)
        self.server = await build_mock_server(_URL, server_map)
        await self.server.__aenter__()
        self.driver = OpcUaDriver(_URL, self.node_map, reconnect_wait_timeout=15.0)
        await self.driver.connect()

        self.assertNotIn(victim, self.driver._nodes, "该符号本就不该被缓存到")
        self.assertIsNotNone(self.driver.missing_reason(victim),
                             "连接期就该把它记入负缓存")
        counter = _Counter(od_mod, "resolve_gvl_node")
        try:
            for _ in range(3):
                with self.assertRaises(KeyError):
                    await self.driver.read_variable(victim)
            self.assertEqual(counter.calls, 0,
                             f"{victim} 在连接期已知缺失, 首读起就不该再浏览容器")
        finally:
            counter.restore()

    async def test_read_many_fills_none_for_absent_without_failing_others(self):
        """批读里混入未下装符号: 该位置为 None, 其余值照常返回。"""
        values = await self.driver.read_many(["collect_Step", _ABSENT, "collect_Step"])
        self.assertEqual(len(values), 3)
        self.assertIsNone(values[1], "未下装符号应填 None")
        self.assertIsNotNone(values[0], "同批其余点不该被带塌")
        self.assertEqual(values[0], values[2])

    # ── 2. 批读: 工位快照一次请求 ────────────────────────────────────────
    async def test_station_snapshot_is_one_read_service_call(self):
        """snapshot 必须一次 Read service 拿全 8 个字段 (旧实现是 8 次往返)。"""
        plc = PlcController(self.driver, poll_interval=0.05)
        client = self.driver._client
        orig_read_values = client.read_values
        calls = 0

        async def _counting_read_values(nodes):
            nonlocal calls
            calls += 1
            return await orig_read_values(nodes)

        client.read_values = _counting_read_values
        try:
            snap = await plc.snapshot("Collect")
        finally:
            client.read_values = orig_read_values

        self.assertEqual(calls, 1, f"工位快照应只发 1 次批读, 实际 {calls} 次")
        self.assertEqual(set(snap), set(_L2_FIELDS))

    async def test_snapshot_with_mirrors_stays_one_call(self):
        """L2 字段 + 附加镜像合并后仍是一次请求; 未下装的镜像填 None 且不额外发请求。"""
        plc = PlcController(self.driver, poll_interval=0.05)
        client = self.driver._client
        orig_read_values = client.read_values
        calls = 0

        async def _counting_read_values(nodes):
            nonlocal calls
            calls += 1
            return await orig_read_values(nodes)

        client.read_values = _counting_read_values
        resolve_counter = _Counter(od_mod, "resolve_gvl_node")
        try:
            snap = await plc.snapshot_with_mirrors("Collect", (_ABSENT,))
        finally:
            client.read_values = orig_read_values
            resolve_counter.restore()

        self.assertEqual(calls, 1, f"合并后仍应只发 1 次批读, 实际 {calls} 次")
        self.assertIn(_ABSENT, snap)
        self.assertIsNone(snap[_ABSENT], "未下装镜像应为 None")
        self.assertLessEqual(resolve_counter.calls, 1,
                             "未下装镜像最多解析一次, 之后走负缓存")

    # ── 3. 重连: 节点缓存整体重建 ────────────────────────────────────────
    async def test_reconnect_rebuilds_node_cache(self):
        """重连后缓存里不能留旧 session 的 Node。

        asyncua 的 Node 硬引用创建它的 session, 旧实现的 _cache_nodes 只覆盖命中项、
        从不清表, 所以重连后任何没被重新 browse 到的名字会永久绑在死会话上。
        """
        name = "collect_Step"
        await self.driver.read_variable(name)
        before_session = self.driver._nodes[name].session

        # 哨兵: 一个重连后不会被重新 browse 到的缓存项。旧实现只覆盖命中项、从不清表,
        # 所以它会带着死 session 一直留着 —— 这才是本用例真正的判别点
        # (collect_Step 这种重连后仍能 browse 到的名字, 新旧实现都会被覆盖成新节点, 判别不了)。
        self.driver._dynamic_nodes["__stale_probe__"] = self.driver._nodes[name]

        # 停掉 server 制造真断连, 起替身后驱动应自行重连
        await self.server.__aexit__(None, None, None)
        hb_interval = od_mod.HEARTBEAT_INTERVAL
        od_mod.HEARTBEAT_INTERVAL = 0.05
        try:
            pending = asyncio.create_task(self.driver.read_variable(name))
            await asyncio.sleep(0.5)
            self.server = await build_mock_server(_URL, self.node_map)
            await self.server.__aenter__()
            value = await asyncio.wait_for(pending, timeout=30.0)
        finally:
            od_mod.HEARTBEAT_INTERVAL = hb_interval

        self.assertIsNotNone(value, "重连后读应恢复")
        self.assertGreaterEqual(self.driver.reconnect_count, 1)
        self.assertNotIn("__stale_probe__", self.driver._dynamic_nodes,
                         "重连后旧缓存项仍在 —— 缓存是覆盖式更新而非整体重建, "
                         "没被重新 browse 到的名字会永久绑死在旧 session 上")
        self.assertIsNot(self.driver._nodes[name].session, before_session,
                         "重连后缓存节点仍绑在旧 session 上 —— 缓存没被整体重建")


if __name__ == "__main__":
    unittest.main()
