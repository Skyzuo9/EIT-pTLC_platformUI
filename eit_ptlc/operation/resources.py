"""设备资源门
============
功能:
    按 config/resources.yaml 的资源表统一管理跨流程共享的设备资源, 使多条并发运行不会
    互相踩掉对方仍在使用的设备; PLC 仍保留最终拒绝权.

资源模式:
    exclusive - 一次只允许一个持有者 (工位/机器人/展缸动作), 后到者等待; 与升级前语义一致.
    shared    - 允许多个持有者并存, 引用计数 0->1 执行 activate 动作, 1->0 执行 deactivate
                动作. 大真空泵即此类: 短流程收尾不会关掉长流程仍在用的真空.

死锁约束:
    整组资源按名排序串行获取, 释放逆序; call/parallel 节点级只允许声明 shared 资源;
    with_resources 区间允许 exclusive, 但受 vm/schema.py 的 W1/W2 防死锁律约束 ——
    独占区间只允许出现在"根 resources 无独占"的脚本 (如展开等待段短取排液), 即任何
    协程在等待独占锁时手上必不持有其他独占锁, hold-and-wait 不成立, 嵌套持锁互等不存在.

未在资源表中登记的名字按 exclusive 处理, 使无资源表装配 (纯离线测试) 保持原行为.

持有者登记 (并行调度可观测性):
    acquire(..., holder=run_id) 时登记独占资源的持有者与起始时刻、共享资源的持有者计数;
    snapshot() 一并暴露, 供 /api/resources 与调度看板回答"这个资源现在被谁占着、占了多久".
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import yaml

log = logging.getLogger(__name__)

MODE_EXCLUSIVE = "exclusive"
MODE_SHARED = "shared"
VALID_MODES = {MODE_EXCLUSIVE, MODE_SHARED}


class ResourceError(RuntimeError):
    """资源表配置错误或资源钩子执行失败."""


@dataclass(frozen=True)
class ResourceSpec:
    """一个设备资源的静态规格.

    字段:
        resource_id: 资源名 (如 device:vacuum_pump / station:sampling)
        label:       工程师可读名称
        mode:        exclusive | shared
        activate:    shared 资源计数 0->1 时执行的动作名; exclusive 恒为 None
        deactivate:  shared 资源计数 1->0 时执行的动作名; exclusive 恒为 None
    """
    resource_id: str
    label: str
    mode: str
    activate: Optional[str] = None
    deactivate: Optional[str] = None


def load_resource_specs(path: str | Path) -> dict[str, ResourceSpec]:
    """读取资源表 YAML 并校验为 {资源名: ResourceSpec}.

    参数:
        path: config/resources.yaml 路径
    返回:
        Dict[str, ResourceSpec]
    """
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw = doc.get("resources") or {}
    if not isinstance(raw, dict):
        raise ResourceError(f"资源表 {path} 的 resources 必须为 mapping")
    specs: dict[str, ResourceSpec] = {}
    for rid, item in raw.items():
        if not isinstance(item, dict):
            raise ResourceError(f"资源 {rid} 定义必须为 mapping")
        mode = item.get("mode")
        if mode not in VALID_MODES:
            raise ResourceError(f"资源 {rid} 的 mode 非法: {mode!r} (合法 {sorted(VALID_MODES)})")
        activate, deactivate = item.get("activate"), item.get("deactivate")
        # shared 必须两个钩子齐全: 只有开没有关会把泵永久留在开态
        if mode == MODE_SHARED and not (activate and deactivate):
            raise ResourceError(f"共享资源 {rid} 必须同时配置 activate 与 deactivate 动作")
        if mode == MODE_EXCLUSIVE and (activate or deactivate):
            raise ResourceError(f"独占资源 {rid} 不应配置 activate/deactivate 动作")
        specs[rid] = ResourceSpec(resource_id=rid, label=item.get("label") or rid, mode=mode,
                                  activate=activate, deactivate=deactivate)
    return specs


class ResourceGate:
    """命名资源门: 独占资源按互斥锁串行, 共享资源按引用计数合成唯一物理开关调用."""

    def __init__(self, specs: Optional[dict[str, ResourceSpec]] = None, *,
                 activator: Optional[Callable[[str], Awaitable[None]]] = None) -> None:
        """构造资源门.

        参数:
            specs:     资源表 {资源名: ResourceSpec}; None/空表示全部按 exclusive 处理
            activator: 异步钩子执行器 (动作名 -> None), 由 bootstrap 注入以调用 ActionExecutor;
                       共享资源必需, 执行失败须抛异常
        """
        self._specs: dict[str, ResourceSpec] = dict(specs or {})
        self._activator = activator
        self._locks: dict[str, asyncio.Lock] = {}        # exclusive: 互斥锁
        self._state_locks: dict[str, asyncio.Lock] = {}  # shared: 计数与钩子的串行化锁
        self._counts: dict[str, int] = {}                # shared: 当前持有者数
        # 持有者登记 (纯诊断投影, 不参与互斥判定): exclusive 名 -> {holder, since};
        # shared 名 -> {holder: 计数}。holder 为 acquire 调用方自报的 run_id, 未报记 "?"。
        self._held: dict[str, dict] = {}
        self._shared_holders: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # 资源表查询 (供 schema 校验与 API 门禁)
    # ------------------------------------------------------------------

    def spec(self, name: str) -> Optional[ResourceSpec]:
        """返回资源规格; 未登记返回 None."""
        return self._specs.get(name)

    def is_known(self, name: str) -> bool:
        """资源名是否已在资源表中登记."""
        return name in self._specs

    def mode_of(self, name: str) -> str:
        """返回资源模式; 未登记按 exclusive 处理."""
        spec = self._specs.get(name)
        return spec.mode if spec is not None else MODE_EXCLUSIVE

    def hook_actions(self) -> set[str]:
        """返回全部被登记为 activate/deactivate 的动作名 (禁止编排层与动作目录直调)."""
        names: set[str] = set()
        for spec in self._specs.values():
            if spec.activate:
                names.add(spec.activate)
            if spec.deactivate:
                names.add(spec.deactivate)
        return names

    # ------------------------------------------------------------------
    # 获取与释放
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self, resources: list[str], *, holder: Optional[str] = None):
        """原子获取一组资源 (排序串行, 避免死锁); 上下文退出时逆序释放.

        参数:
            resources: 资源名列表 (去重)
            holder: 持有者标识 (通常为 run_id), 仅用于占用登记与诊断, 不参与互斥判定
        """
        ordered = sorted(set(resources))
        acquired: list[str] = []
        try:
            for name in ordered:
                await self._acquire_one(name)
                acquired.append(name)
                self._record_hold(name, holder)
        except BaseException:
            # 取到一半失败: 已取部分必须回退, 否则该资源被永久占住
            await self._release_all(acquired, keep_original_error=True, holder=holder)
            raise
        if ordered:
            log.debug("[Gate] 已获取资源: %s (holder=%s)", ordered, holder)
        try:
            yield
        except BaseException:
            # body 已有异常在飞 (含取消): 释放失败只记 ERROR, 保留原异常供上层收口
            await self._release_all(acquired, keep_original_error=True, holder=holder)
            raise
        else:
            # body 正常结束: 释放失败必须抛出, 否则真空泵可能留在开态而无人知晓
            await self._release_all(acquired, keep_original_error=False, holder=holder)
        finally:
            if ordered:
                log.debug("[Gate] 已释放资源: %s", ordered)

    def _record_hold(self, name: str, holder: Optional[str]) -> None:
        """登记一次成功获取的持有者信息 (exclusive 覆盖式, shared 计数式)."""
        who = holder or "?"
        if self.mode_of(name) == MODE_EXCLUSIVE:
            self._held[name] = {"holder": who, "since": _time.time()}
        else:
            d = self._shared_holders.setdefault(name, {})
            d[who] = d.get(who, 0) + 1

    def _drop_hold(self, name: str, holder: Optional[str]) -> None:
        """撤销一次持有登记 (在物理释放前执行; 钩子失败不影响登记一致性)."""
        who = holder or "?"
        if self.mode_of(name) == MODE_EXCLUSIVE:
            self._held.pop(name, None)
        else:
            d = self._shared_holders.get(name)
            if d is not None:
                cnt = d.get(who, 0) - 1
                if cnt > 0:
                    d[who] = cnt
                else:
                    d.pop(who, None)
                if not d:
                    self._shared_holders.pop(name, None)

    async def _acquire_one(self, name: str) -> None:
        """获取单个资源: exclusive 取锁, shared 计数加一并在首个持有者时驱动物理开."""
        spec = self._specs.get(name)
        if spec is None or spec.mode == MODE_EXCLUSIVE:
            await self._lock(name).acquire()
            return
        async with self._state_lock(name):
            self._counts[name] = self._counts.get(name, 0) + 1
            if self._counts[name] == 1:
                try:
                    await self._run_hook(spec.activate, name, "开启")
                except BaseException:
                    self._counts[name] = 0      # 开启失败: 计数回滚, 本次不算持有者
                    raise
            log.debug("[Gate] 共享资源 %s 持有者数 -> %d", name, self._counts[name])

    async def _release_one(self, name: str) -> None:
        """释放单个资源: exclusive 解锁, shared 计数减一并在最后一个持有者退出时驱动物理关."""
        spec = self._specs.get(name)
        if spec is None or spec.mode == MODE_EXCLUSIVE:
            self._lock(name).release()
            return
        async with self._state_lock(name):
            self._counts[name] = self._counts.get(name, 0) - 1
            if self._counts[name] < 0:
                raise ResourceError(f"共享资源 {name} 引用计数为负, 获取与释放未配对")
            log.debug("[Gate] 共享资源 %s 持有者数 -> %d", name, self._counts[name])
            if self._counts[name] == 0:
                await self._run_hook(spec.deactivate, name, "关闭")

    async def _release_all(self, acquired: list[str], *, keep_original_error: bool,
                           holder: Optional[str] = None) -> None:
        """逆序释放已取得的全部资源.

        参数:
            acquired:            已成功获取的资源名 (按获取顺序)
            keep_original_error: True 表示已有异常在飞, 释放失败只记 ERROR 不改变传播中的异常;
                                 False 表示正常退出, 首个释放失败必须抛出
            holder:              acquire 时自报的持有者标识 (撤销登记用)
        """
        first_error: Optional[BaseException] = None
        for name in reversed(acquired):
            self._drop_hold(name, holder)
            try:
                await self._release_one(name)
            except BaseException as exc:
                log.error("[Gate] 释放资源 %s 失败, 该设备可能仍处于工作状态: %s", name, exc)
                if first_error is None:
                    first_error = exc
        if first_error is not None and not keep_original_error:
            raise first_error

    async def _run_hook(self, action: Optional[str], name: str, what: str) -> None:
        """执行共享资源的物理开关动作 (activate/deactivate)."""
        if not action:
            raise ResourceError(f"共享资源 {name} 未配置{what}动作")
        if self._activator is None:
            raise ResourceError(f"资源门未注入动作执行器, 无法{what}共享资源 {name}")
        log.info("[Gate] 共享资源 %s %s: 执行动作 %s", name, what, action)
        await self._activator(action)

    # ------------------------------------------------------------------
    # 只读视图
    # ------------------------------------------------------------------

    def _lock(self, name: str) -> asyncio.Lock:
        return self._locks.setdefault(name, asyncio.Lock())

    def _state_lock(self, name: str) -> asyncio.Lock:
        return self._state_locks.setdefault(name, asyncio.Lock())

    def locked(self, name: str) -> bool:
        """独占资源当前是否被占用 (供只读视图/诊断)."""
        lock = self._locks.get(name)
        return bool(lock and lock.locked())

    def holders(self, name: str) -> int:
        """共享资源当前持有者数 (供只读视图/诊断)."""
        return self._counts.get(name, 0)

    def snapshot(self) -> dict[str, dict]:
        """返回全部已知资源的占用快照.

        形态: {资源名: {label, mode, locked|holders[, holder, since][, holder_list]}}
        独占且占用中时附 holder (run_id) 与 since (epoch 秒); 共享有持有者时附 holder_list。
        """
        names = set(self._specs) | set(self._locks) | set(self._counts)
        out: dict[str, dict] = {}
        for name in sorted(names):
            spec = self._specs.get(name)
            mode = self.mode_of(name)
            item = {"label": spec.label if spec is not None else name, "mode": mode}
            if mode == MODE_SHARED:
                item["holders"] = self.holders(name)
                held = self._shared_holders.get(name)
                if held:
                    item["holder_list"] = sorted(held)
            else:
                item["locked"] = self.locked(name)
                info = self._held.get(name)
                if item["locked"] and info is not None:
                    item["holder"] = info.get("holder")
                    item["since"] = info.get("since")
            out[name] = item
        return out
