"""可抢占会话属主租约(session.owner)的离线契约测试.

这些用例只驱动 codesys_ipc.py 里 session.owner 的纯文件状态机, 绝不启动 InoProShop、
不连 PLC。验证四个前提: 跨进程独占 / 空闲自动接管 / 忙时阻塞至超时 / 崩溃与逃生阀兜底,
以及显式 own_session 免于空闲抢占。session.owner 的 6 字段 schema 与 server.mjs 的
newOwnerPayload 逐字对齐(跨语言镜像), 故本文件对该 schema 的断言等同于对 Node 侧的约束。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from eit_ptlc.driver.codesys_ipc import CodesysIpcClient

_PLC_IP = "192.0.2.55"


def _client(tmp_path: Path, label: str, *, ipc_dir: Path | None = None,
            idle_release: float = 60.0, wait: float = 300.0,
            max_hold: float = 900.0) -> CodesysIpcClient:
    project = tmp_path / "active.project"
    if not project.exists():
        project.write_bytes(b"project")
    return CodesysIpcClient(
        exe=str(tmp_path / "InoProShop.exe"), profile="test", project=project,
        ipc_dir=ipc_dir or (tmp_path / "ipc"), compile_category="test", plc_ip=_PLC_IP,
        poll_sec=0.001, ready_timeout=0.01, idle_timeout=0,
        session_label=label, session_idle_release=idle_release,
        session_wait_timeout=wait, session_max_hold=max_hold,
    )


def _dead_pid() -> int:
    """一个必死的 pid: 起一个瞬退子进程并等其退出, 返回其(已消亡)pid."""
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def _write_owner(client: CodesysIpcClient, **fields) -> None:
    payload = {
        "owner_id": "foreign", "label": "foreign", "pid": os.getpid(),
        "acquired_at": time.time(), "last_activity": time.time(),
        "owner_token": "foreigntoken",
    }
    payload.update(fields)
    client._write_json_atomic(client._session_owner_path, payload)  # noqa: SLF001


def test_claim_free_then_refresh_keeps_owner_changes_token(tmp_path: Path) -> None:
    a = _client(tmp_path, "A")
    a._claim_or_wait("write", 2.0)  # noqa: SLF001
    o1 = a._read_json(a._session_owner_path)  # noqa: SLF001
    assert o1 and o1["owner_id"] == a._owner_id
    # schema: 与 server.mjs newOwnerPayload 同 6 字段
    assert set(o1) == {"owner_id", "label", "pid", "acquired_at", "last_activity", "owner_token"}
    a._claim_or_wait("compile", 2.0)  # noqa: SLF001
    o2 = a._read_json(a._session_owner_path)  # noqa: SLF001
    assert o2["owner_id"] == a._owner_id           # 属主不变
    assert o2["owner_token"] != o1["owner_token"]  # 每次盖章换新 token(消解空闲抢占 TOCTOU)
    assert o2["acquired_at"] == o1["acquired_at"]  # acquired_at 保持(供 MAX_HOLD)


def test_foreign_live_owner_blocks_until_timeout(tmp_path: Path) -> None:
    ipc = tmp_path / "shared"
    a = _client(tmp_path, "A", ipc_dir=ipc)
    b = _client(tmp_path, "B", ipc_dir=ipc)
    a._claim_or_wait("write", 2.0)  # noqa: SLF001  A 持有(pid=本测试进程, 存活且新鲜)
    t0 = time.time()
    with pytest.raises(RuntimeError, match="独占|超时"):
        b._claim_or_wait("write", 0.3)  # noqa: SLF001
    assert time.time() - t0 >= 0.3    # 确实阻塞了(非立即失败)


def test_idle_owner_is_preempted(tmp_path: Path) -> None:
    ipc = tmp_path / "shared"
    a = _client(tmp_path, "A", ipc_dir=ipc, idle_release=0.3)
    b = _client(tmp_path, "B", ipc_dir=ipc, idle_release=0.3)
    a._claim_or_wait("write", 2.0)  # noqa: SLF001
    time.sleep(0.5)                                   # > idle_release, A 变空闲
    b._claim_or_wait("write", 2.0)  # noqa: SLF001
    assert b._read_json(b._session_owner_path)["owner_id"] == b._owner_id  # noqa: SLF001


def test_dead_pid_owner_is_preempted(tmp_path: Path) -> None:
    a = _client(tmp_path, "A")
    _write_owner(a, owner_id="ghost", pid=_dead_pid(), owner_token="deadtok")
    a._claim_or_wait("write", 2.0)  # noqa: SLF001  死属主 = 崩溃兜底, 立即抢占
    assert a._read_json(a._session_owner_path)["owner_id"] == a._owner_id  # noqa: SLF001


def test_max_hold_escape_valve(tmp_path: Path) -> None:
    a = _client(tmp_path, "A", max_hold=0.5)
    # 活 pid + last_activity 新鲜, 但 acquired_at 极旧 -> 超 MAX_HOLD 逃生阀 -> 可抢占
    _write_owner(a, owner_id="stuck", pid=os.getpid(),
                 acquired_at=time.time() - 100.0, last_activity=time.time(),
                 owner_token="stucktok")
    a._claim_or_wait("write", 2.0)  # noqa: SLF001
    assert a._read_json(a._session_owner_path)["owner_id"] == a._owner_id  # noqa: SLF001


def test_release_clears_file(tmp_path: Path) -> None:
    a = _client(tmp_path, "A")
    a._claim_or_wait("write", 2.0)  # noqa: SLF001
    assert Path(a._session_owner_path).exists()  # noqa: SLF001
    a._release_owner()  # noqa: SLF001
    assert not Path(a._session_owner_path).exists()  # noqa: SLF001


def test_snapshot_reports_owner_fields(tmp_path: Path) -> None:
    a = _client(tmp_path, "A")
    snap0 = a.session_snapshot()
    assert snap0["owned"] is False and not snap0["owner"]
    a._claim_or_wait("write", 2.0)  # noqa: SLF001
    snap1 = a.session_snapshot()
    assert snap1["owned"] is True
    assert snap1["owner"]["owner_id"] == a._owner_id
    assert snap1["owner_alive"] is True
    assert isinstance(snap1["owner_idle_sec"], float) and snap1["owner_idle_sec"] >= 0


def test_exclusive_call_blocks_on_foreign_owner(tmp_path: Path) -> None:
    """call() 级集成: 写类 op 被存活外部属主挡住, 在触达 worker 前就阻塞至超时抛忙."""
    a = _client(tmp_path, "A", wait=0.3)
    _write_owner(a, owner_id="foreign-live", pid=os.getpid(), owner_token="ft")
    with pytest.raises(RuntimeError, match="独占|超时"):
        asyncio.run(a.call("write", {"path": "Application/Foo", "declaration": "x",
                                     "implementation": None, "save": False}, timeout=5.0))
    # 未落到 worker: worker_active.py 从未生成
    assert not Path(a._worker_script).exists()  # noqa: SLF001


def test_own_session_immune_to_idle_then_releases(tmp_path: Path) -> None:
    """显式 own_session 后台刷新器保活: 空闲阈内不被抢; 退出即释放让他方接管."""
    ipc = tmp_path / "shared"
    a = _client(tmp_path, "A", ipc_dir=ipc, idle_release=0.3)
    b = _client(tmp_path, "B", ipc_dir=ipc, idle_release=0.3)

    async def scenario() -> None:
        async with a.own_session(label="A:tx"):
            await asyncio.sleep(0.9)          # > idle_release, 但刷新器每 0.15s 保活
            with pytest.raises(RuntimeError, match="独占|超时"):
                await asyncio.to_thread(b._claim_or_wait, "write", 0.3)  # noqa: SLF001
        # 退出后 A 已释放 -> B 立即抢到
        await asyncio.to_thread(b._claim_or_wait, "write", 2.0)  # noqa: SLF001
        assert b._read_json(b._session_owner_path)["owner_id"] == b._owner_id  # noqa: SLF001

    asyncio.run(scenario())
