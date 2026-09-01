"""launcher 优雅关停后端的离线单测。

只验证 _graceful_stop_backend 的回退/短路逻辑与 _stop_all 的路由:
mock 掉真正投递 CTRL_BREAK 的 subprocess.run 与假 proc,不起真进程。
跨控制台 CTRL_BREAK 的真实投递靠真机手测 (见实施计划 Task 4)。
"""

from __future__ import annotations

import subprocess

import eit_ptlc.main as m


class _FakeProc:
    def __init__(self, *, poll_val, wait_raises=False, pid=54321):
        self._poll = poll_val
        self._wait_raises = wait_raises
        self.pid = pid

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        if self._wait_raises:
            raise subprocess.TimeoutExpired(cmd="uvicorn", timeout=timeout)
        return 0


def test_graceful_stop_returns_true_when_backend_exits(monkeypatch):
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    proc = _FakeProc(poll_val=None)
    assert m._graceful_stop_backend(proc) is True
    assert calls, "应向后端投递 CTRL_BREAK (subprocess.run 未被调用)"
    assert calls[0][0][0][-1] == str(proc.pid), "命令列表末位是后端 pid"


def test_graceful_stop_returns_false_on_wait_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    proc = _FakeProc(poll_val=None, wait_raises=True)
    assert m._graceful_stop_backend(proc) is False
    assert calls, "应向后端投递 CTRL_BREAK (subprocess.run 未被调用)"
    assert calls[0][0][0][-1] == str(proc.pid), "命令列表末位是后端 pid"


def test_graceful_stop_short_circuits_when_already_dead(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("已退出的后端不应再投递 CTRL_BREAK")

    monkeypatch.setattr(m.subprocess, "run", _boom)
    assert m._graceful_stop_backend(_FakeProc(poll_val=0)) is True


def test_stop_all_backend_graceful_others_forced(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "_graceful_stop_backend", lambda proc: seen.append("graceful-backend") or True)
    monkeypatch.setattr(m, "_terminate_tree", lambda name, proc: seen.append(f"terminate-{name}"))

    procs = {"PALLASBridge": object(), "后端": object(), "前端": object()}
    m._stop_all(procs)

    assert "graceful-backend" in seen
    assert "terminate-PALLASBridge" in seen
    assert "terminate-前端" in seen
    assert "terminate-后端" not in seen   # 后端优雅退出成功, 不再强杀
    assert procs == {}


def test_stop_all_backend_falls_back_to_force_when_graceful_fails(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "_graceful_stop_backend", lambda proc: seen.append("graceful-fail") or False)
    monkeypatch.setattr(m, "_terminate_tree", lambda name, proc: seen.append(f"terminate-{name}"))

    procs = {"后端": object()}
    m._stop_all(procs)

    assert seen == ["graceful-fail", "terminate-后端"]   # 优雅失败 → 强杀兜底
