"""plc_write 块写回读确认离线测试
===============================
功能:
    用内存假节点验证 OpcUaDriver.write_block_confirmed 的核心逻辑:
      - 数组 + 标量混合块写后逐字段回读一致 → 通过
      - 浮点回读带 atol 容差 (微小误差视为一致)
      - 回读不符触发有界重写, 仍不符抛 PLCWriteConfirmError
      - 数组按 array_len 补齐, 比对针对归一后的写入值 (而非原始入参)

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_plc_write_confirm_offline
"""

from __future__ import annotations

import asyncio
import sys

from asyncua import ua

from eit_ptlc.config.models import NodeSpec, PlcNodeMap
from eit_ptlc.driver.opcua_driver import OpcUaDriver, PLCState, PLCWriteConfirmError


class _FakeNode:
    """内存假 OPC 节点: 记录最近写入值, read_value 原样返回。

    perturb: 可选回调, 在写入存值后对存值做扰动 (模拟回读不符); 传入 (写入次数) 返回是否扰动。
    """

    def __init__(self, value):
        self.value = value
        self.writes = 0
        self.perturb = None

    async def read_value(self):
        return self.value

    async def write_value(self, datavalue):
        self.writes += 1
        v = datavalue.Value.Value  # ua.DataValue -> Variant -> python 值 (标量或 list)
        self.value = list(v) if isinstance(v, list) else v
        if self.perturb and self.perturb(self.writes):
            # 扰动: 标量 +10, 数组首元素 +10 (制造不符)
            if isinstance(self.value, list):
                self.value = list(self.value)
                self.value[0] = self.value[0] + 10.0
            else:
                self.value = self.value + 10.0


def _make_driver() -> OpcUaDriver:
    node_map = PlcNodeMap(
        gvl_path=("GVL",),
        heartbeat_node="g_pass_z",
        estop_node="g_pass_z",
        nodes={
            "g_sx": NodeSpec(name="g_sx", var_type="Float", array_len=400),
            "g_scrape_feed": NodeSpec(name="g_scrape_feed", var_type="Int16"),
            "g_pass_z": NodeSpec(name="g_pass_z", var_type="Float"),
        },
    )
    drv = OpcUaDriver("opc.tcp://fake", node_map)
    # 假节点替换 + 标记已连接 (跳过真实 OPC)
    drv._nodes = {
        "g_sx": _FakeNode([0.0] * 400),
        "g_scrape_feed": _FakeNode(0),
        "g_pass_z": _FakeNode(0.0),
    }
    drv._connected_evt.set()
    drv._state = PLCState.CONNECTED
    return drv


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"{'PASS' if cond else 'FAIL'} {name}" + ("" if cond else f": {detail}"))
        if not cond:
            failures.append(name)

    # 1) 块写: 数组 (满 400) + 标量, 回读一致
    drv = _make_driver()
    sx = [round(i * 0.1, 3) for i in range(400)]
    report = await drv.write_block_confirmed({"g_sx": sx, "g_scrape_feed": 800})
    check("block_ok", report["g_sx"]["ok"] and report["g_scrape_feed"]["ok"], str(report))
    check("block_readback", await drv._nodes["g_sx"].read_value() == sx, "数组回读应等于写入")

    # 2) 浮点 atol: 节点存值与期望差 5e-4 < atol(1e-3) → 视为一致
    drv = _make_driver()
    drv._nodes["g_pass_z"].perturb = None
    # 手动让写入后存值带微小误差
    orig_write = drv._nodes["g_pass_z"].write_value

    async def _eps_write(dv):
        await orig_write(dv)
        drv._nodes["g_pass_z"].value += 5e-4

    drv._nodes["g_pass_z"].write_value = _eps_write
    rep = await drv.write_block_confirmed({"g_pass_z": 7.5}, atol=1e-3)
    check("float_atol_pass", rep["g_pass_z"]["ok"], str(rep))

    # 3) 数组归一: 入参仅 3 点, array_len=400 → 补 0.0; 回读 400 长度仍确认通过
    drv = _make_driver()
    rep = await drv.write_block_confirmed({"g_sx": [1.0, 2.0, 3.0]})
    rb = await drv._nodes["g_sx"].read_value()
    check("array_pad_confirm", rep["g_sx"]["ok"] and len(rb) == 400 and rb[3] == 0.0,
          f"len={len(rb)} rb[3]={rb[3]}")

    # 4) 首次写入被扰动 → 第 2 次重写成功 (attempts=2)
    drv = _make_driver()
    drv._nodes["g_pass_z"].perturb = lambda w: w == 1  # 仅第 1 次扰动
    rep = await drv.write_block_confirmed({"g_pass_z": 3.0}, attempts=2)
    check("retry_then_ok", rep["g_pass_z"]["ok"] and rep["g_pass_z"]["attempts"] == 2, str(rep))

    # 5) 持续扰动 → 耗尽 attempts 抛 PLCWriteConfirmError
    drv = _make_driver()
    drv._nodes["g_pass_z"].perturb = lambda w: True
    raised = False
    try:
        await drv.write_block_confirmed({"g_pass_z": 3.0}, attempts=2)
    except PLCWriteConfirmError as exc:
        raised = exc.node == "g_pass_z"
    check("confirm_error_raised", raised, "应抛 PLCWriteConfirmError(node=g_pass_z)")

    print(f"\n共 6 用例, 失败 {len(failures)}")
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
