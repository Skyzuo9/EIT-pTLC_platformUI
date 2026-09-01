"""asyncua 变量订阅器 - 维护 PLC 变量快照与变更时间戳

通过 asyncua subscription 监控 PLC 关键变量，维护一份内存快照供
Debug Tab 和 Flow Tab 只读访问。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from core.plc_client import resolve_gvl_node, _find_child_by_name

log = logging.getLogger(__name__)

# 需要订阅的关键变量列表（协议 v1.1：删除 Recipe_Param_*，接入所有工位六件套）
MONITORED_VARS = [
    # 调试辅助
    "Test_BOOL",
    # 协议 v1.1：collect 工位六件套 + 业务参数
    "collect_Enable", "collect_Step", "collect_Done",
    "collect_Error", "collect_Reset", "collect_Busy",
    "collect_forward_instructions", "collect_count",
    # 协议 v1.3：develop（展开）工位六件套
    "Expand_Enable", "Expand_Step", "Expand_Done",
    "Expand_Error", "Expand_Reset", "Expand_Busy",
    # 协议 v1.4：spotting（上样点样）工位六件套
    "Sampling_Enable", "Sampling_Step", "Sampling_Done",
    "Sampling_Error", "Sampling_Reset", "Sampling_Busy",
    # 协议 v1.5：scrape 工位六件套 + 业务参数
    "scrape_Enable", "scrape_Step", "scrape_Done",
    "scrape_Error", "scrape_Reset", "scrape_Busy",
    "scrape_Confirm", "scrape_WaitConfirm", "scrape_gcode_instructions", "scrape_PhotoMode",
    # 全局
    "PLC_EStop",
    # 实机 PLC Host_Computer 额外变量（b 前缀）
    "bOutput", "bEnable", "bErrorReset", "bStepEnable",
]


class VariableMonitor:
    """通过 asyncua subscription 监控 PLC 变量。

    使用方式：
        vm = VariableMonitor()
        await vm.start(client_session)   # client_session = asyncua Client 实例
        # snapshot 自动更新
        await vm.stop()
    """

    def __init__(self) -> None:
        self.snapshot: Dict[str, Any] = {}
        self.timestamps: Dict[str, datetime] = {}
        self._subscription = None
        self._handles: list = []
        self._listeners: list[Callable[[str, Any], None]] = []
        # node → BrowseName.Name 映射（供 datachange_notification 回调反查变量名）
        # 实机（Inovance）节点 Identifier 为数字型，无法用子串匹配；
        # 改为订阅时记录 node→name 映射，回调中直接查表。
        self._node_name_map: Dict[int, str] = {}

    def add_listener(self, cb: Callable[[str, Any], None]) -> None:
        """注册变量变更监听器。"""
        self._listeners.append(cb)

    async def start(self, client_session) -> None:
        """使用已连接的 asyncua client session 创建订阅。

        Args:
            client_session: 已连接的 asyncua.Client 实例
        """
        try:
            self._subscription = await client_session.create_subscription(200, self)
            # 通过 BrowseName 跨命名空间定位 Host_Computer 对象（与 plc_client._cache_nodes 路径一致）
            gvl = await resolve_gvl_node(client_session)
            for var_name in MONITORED_VARS:
                try:
                    node = await _find_child_by_name(gvl, var_name)
                    handle = await self._subscription.subscribe_data_change(node)
                    self._handles.append(handle)
                    # 记录 node → 变量名 映射（供 datachange_notification 回调查表）
                    self._node_name_map[id(node)] = var_name
                    # 初始读取
                    val = await node.read_value()
                    self.snapshot[var_name] = val
                    self.timestamps[var_name] = datetime.now()
                except Exception as e:
                    log.warning("[VariableMonitor] 订阅 %s 失败: %s", var_name, e)
            log.info(
                "[VariableMonitor] 启动完成，已订阅 %d/%d 个变量",
                len(self.snapshot), len(MONITORED_VARS),
            )
        except Exception as e:
            log.warning("[VariableMonitor] 启动订阅失败: %s", e)

    def datachange_notification(self, node, val, data) -> None:
        """asyncua 订阅回调。

        通过 _node_name_map 查表获取变量名（兼容实机数字型 Identifier 和 mock 字符串型）。
        订阅时已注册所有 node→name 映射，此处直接查表即可。
        """
        var_name = self._node_name_map.get(id(node))
        if var_name is None:
            return
        self.snapshot[var_name] = val
        self.timestamps[var_name] = datetime.now()
        for cb in self._listeners:
            try:
                cb(var_name, val)
            except Exception:
                pass

    async def extend_subscription(self, client_session, new_vars: list[str]) -> list[str]:
        """动态扩展订阅变量列表。

        供 UI "扫描 PLC 变量" 功能调用：扫描到新变量后追加订阅。
        已在 snapshot 或 MONITORED_VARS 中的变量自动跳过。

        Args:
            client_session: 已连接的 asyncua.Client 实例
            new_vars: 需要新增订阅的变量名列表

        Returns:
            成功订阅的变量名列表
        """
        if not self._subscription:
            return []
        gvl = await resolve_gvl_node(client_session)
        added: list[str] = []
        for var_name in new_vars:
            if var_name in self.snapshot or var_name in MONITORED_VARS:
                continue  # 已订阅
            try:
                node = await _find_child_by_name(gvl, var_name)
                handle = await self._subscription.subscribe_data_change(node)
                self._handles.append(handle)
                # 记录 node → 变量名 映射（供 datachange_notification 回调查表）
                self._node_name_map[id(node)] = var_name
                val = await node.read_value()
                self.snapshot[var_name] = val
                self.timestamps[var_name] = datetime.now()
                MONITORED_VARS.append(var_name)
                added.append(var_name)
            except Exception as e:
                log.warning("[VariableMonitor] 动态订阅 %s 失败: %s", var_name, e)
        if added:
            log.info("[VariableMonitor] 动态扩展 %d 个变量", len(added))
        return added

    async def auto_discover(self, client_session) -> int:
        """自动扫描 Host_Computer 下全部变量并扩展订阅。

        在 start() 之后调用，浏览 PLC Host_Computer 对象下所有子节点，
        将不在 snapshot 中的变量自动加入订阅和 MONITORED_VARS。
        确保实机连接后变量表能显示 PLC 端全部变量，无需手动扫描。

        Args:
            client_session: 已连接的 asyncua.Client 实例

        Returns:
            新增订阅的变量数量
        """
        if not self._subscription:
            return 0
        try:
            gvl = await resolve_gvl_node(client_session)
            children = await gvl.get_children()
            new_vars: list[str] = []
            for child in children:
                try:
                    bn = await child.read_browse_name()
                    name = bn.Name
                    if name not in self.snapshot and name not in MONITORED_VARS:
                        new_vars.append(name)
                except Exception:
                    continue
            if new_vars:
                added = await self.extend_subscription(client_session, new_vars)
                log.info(
                    "[VariableMonitor] auto_discover: Host_Computer 共 %d 变量, 新增订阅 %d 个",
                    len(children), len(added),
                )
                return len(added)
            return 0
        except Exception as e:
            log.warning("[VariableMonitor] auto_discover 失败: %s", e)
            return 0

    async def stop(self) -> None:
        """停止订阅。"""
        if self._subscription:
            try:
                await self._subscription.delete()
            except Exception:
                pass
            self._subscription = None
            self._handles.clear()
        self._node_name_map.clear()
        self.snapshot.clear()
        self.timestamps.clear()

    async def guarded_write(self, plc_client, var_name: str, value) -> bool:
        """受限写入：检查工位状态后允许写入。

        Phase C：移除 PLC_Busy 全局互锁，改为直接写入（工位级互锁由 Stage 管理）。

        Args:
            plc_client: PLCClient 实例（需已连接）
            var_name: 变量名
            value: 写入值

        Returns:
            True=写入成功，False=写入失败
        """
        try:
            await plc_client.write_variable(var_name, value)
            self.snapshot[var_name] = value
            self.timestamps[var_name] = datetime.now()
            return True
        except Exception as e:
            log.error("[VariableMonitor] 写入 %s 失败: %s", var_name, e)
            return False
