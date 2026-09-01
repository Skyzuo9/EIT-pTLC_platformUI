"""CODESYS worker 生命周期/会话控制离线测试
=============================================
功能:
    不启动 InoProShop, 在 CPython 里停桩 CODESYS 全局(projects/system/unicode)后 exec
    真实 worker_body.py(子进程运行, 便于超时判活), 验证 worker 主循环语义:
      - 基线: 空请求目录 + idle>0 → 空闲超时自关, 终态 stopped
      - BOM 请求: 带 UTF-8 BOM 的合法请求应被剥 BOM 解析并正常处理(2026-07 真实事故回归:
        一个 PowerShell 手工投递的 BOM 请求曾被当"半写入"永久滞留, 击穿空闲自关)
      - 坏文件隔离: 不可解析且超龄的请求改名 .bad, 不再永久滞留冻结空闲计时
      - idle=0: 常驻永不自关(人机共用一个窗口场景)
      - 接管: manual_control=true 时 worker 拒执行非 status 请求(ok=false), 空闲计时冻结
        不自关; 释放后恢复空闲自关
      - 空闲自关击穿(F7): 隔离恒失效(未来 mtime)时 processed==0 分支仍限时自关;
        idle=0 常驻与接管冻结语义不受影响
      - BOM split-brain(F9): 带 BOM 的 session_control.json 在 worker 与客户端接管门同判
      - 接管 TTL(F8): updated_at 超 24h 的标志两侧均视为过期; 缺 updated_at 旧格式永不过期
      - 隔离误伤(F6): 老化合法请求单次瞬态读失败不隔离(连败>=3轮才隔离); 真毒文件隔离时
        补写 request quarantined 错误响应
      - 双 dispatch: 请求文件删除失败被吞时, 同一请求绝不重复执行
    另测 CodesysIpcClient(进程内):
      - spawn 冷却: 新鲜 error 状态(工程被占用)→ ensure_worker 快速失败不拉 EXE;
        过期 error → 正常走 spawn 路径
      - stop_worker 契约: 不在线 False; 活体(含 opening)写哨兵等进程退出; 接管态拒停
        (RuntimeError, 哨兵不写); 启动窗口(无 status + spawn.lock 活)拒停; 超时抛
        TimeoutError 且回收哨兵(取消停止)

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_codesys_worker_offline
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_WORKER_BODY = _THIS_FILE.parent.parent / "tools" / "codesys-mcp" / "worker_body.py"

# 现场毒文件的复刻: UTF-8 BOM + PowerShell ConvertTo-Json 风格(args 为数组)
_BOM_LIST_REQUEST = "﻿{\n    \"args\":  [\n\n             ],\n    \"op\":  \"list\"\n}"


# ----------------------------------------------------------------------
# 子进程入口: 停桩 CODESYS 全局, exec 真实 worker_body.py (不改动其源码)
# ----------------------------------------------------------------------

def _run_worker_child(ipc_dir: str, idle: float, quarantine: float,
                      flaky_reads: int = 0, sticky_removes: int = 0) -> None:
    from types import SimpleNamespace

    class _FakeProject:
        def save(self):
            # 落盘计数: 双 dispatch 用例断言同一请求只执行一次
            p = os.path.join(ipc_dir, "save_count.txt")
            try:
                with open(p, "r") as f:
                    n = int(f.read().strip() or "0")
            except (OSError, ValueError):
                n = 0
            with open(p, "w") as f:
                f.write(str(n + 1))

    if flaky_reads > 0:
        # F6 打桩: 对 *.req.json 的前 N 次 codecs.open 抛 IOError(模拟 Windows 杀软/索引器
        # 瞬态共享冲突)。补丁真 codecs 模块单例 — 见模块 docstring 打桩铁律。
        import codecs as _codecs
        real_open = _codecs.open
        remaining = {"n": flaky_reads}

        def _flaky_open(path, *a, **kw):
            if str(path).endswith(".req.json") and remaining["n"] > 0:
                remaining["n"] -= 1
                raise IOError("simulated transient sharing violation")
            return real_open(path, *a, **kw)

        _codecs.open = _flaky_open

    if sticky_removes > 0:
        # 双 dispatch 打桩: 对 *.req.json 的前 N 次 os.remove 抛 OSError(模拟删除撞共享冲突被吞)
        real_remove = os.remove
        rem = {"n": sticky_removes}

        def _sticky_remove(path, *a, **kw):
            if str(path).endswith(".req.json") and rem["n"] > 0:
                rem["n"] -= 1
                raise OSError("simulated sharing violation on remove")
            return real_remove(path, *a, **kw)

        os.remove = _sticky_remove

    header = (
        'IPC_DIR = r"%s"\n' % ipc_dir
        + 'PROJECT_PATH = r"%s"\n' % os.path.join(ipc_dir, "fake.project")
        + "POLL_SEC = 0.01\n"
        + 'COMPILE_CATEGORY = "test"\n'
        + 'PLC_IP = ""\n'
        + "IDLE_TIMEOUT_SEC = %s\n" % idle
        + "QUARANTINE_AGE_SEC = %s\n\n" % quarantine
    )
    body = _WORKER_BODY.read_text(encoding="utf-8")
    stub_globals = {
        "__name__": "__main__",
        "unicode": str,
        "projects": SimpleNamespace(open=lambda path, pwd, primary: _FakeProject()),
        "system": SimpleNamespace(process_messageloop=lambda: None,
                                  exit=lambda: sys.exit(0)),
    }
    exec(compile(header + body, "worker_body_sim", "exec"), stub_globals)


def _spawn_worker(ipc_dir: Path, idle: float, quarantine: float = 10.0,
                  flaky_reads: int = 0, sticky_removes: int = 0) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(_THIS_FILE), "--as-worker", str(ipc_dir), str(idle),
         str(quarantine), str(flaky_reads), str(sticky_removes)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _read_status(ipc_dir: Path) -> dict:
    try:
        return json.loads((ipc_dir / "worker.status").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _wait_responses(ipc_dir: Path, rids: list[str], timeout: float = 5.0) -> dict:
    """等待各 rid 的响应文件出现, 返回 {rid: resp_dict}; 超时缺席的 rid 不在结果里."""
    out: dict = {}
    deadline = time.time() + timeout
    while time.time() < deadline and len(out) < len(rids):
        for rid in rids:
            if rid in out:
                continue
            p = ipc_dir / "responses" / (rid + ".resp.json")
            try:
                out[rid] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        time.sleep(0.05)
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    import asyncio
    import tempfile

    from eit_ptlc.driver.codesys_ipc import CodesysIpcClient

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    tmp_root = Path(tempfile.mkdtemp(prefix="codesys_worker_"))

    # ---- 1) 基线: 空请求目录, idle=1 → 空闲超时自关, 终态 stopped ----
    d1 = tmp_root / "s1"
    (d1 / "requests").mkdir(parents=True)
    p1 = _spawn_worker(d1, idle=1)
    try:
        rc = p1.wait(timeout=10)
        check("idle_baseline_exits", rc == 0 and _read_status(d1).get("state") == "stopped",
              f"rc={rc}, status={_read_status(d1)}")
    except subprocess.TimeoutExpired:
        p1.kill()
        check("idle_baseline_exits", False, "worker 未在 10s 内空闲自关")

    # ---- 2) BOM 合法请求被剥 BOM 解析并处理(现场毒文件回归) ----
    d2 = tmp_root / "s2"
    (d2 / "requests").mkdir(parents=True)
    (d2 / "requests" / "bomreq.req.json").write_text(_BOM_LIST_REQUEST, encoding="utf-8")
    p2 = _spawn_worker(d2, idle=1)
    resp2 = _wait_responses(d2, ["bomreq"])
    try:
        rc = p2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p2.kill()
        rc = None
    check("bom_request_processed",
          resp2.get("bomreq", {}).get("ok") is True,
          f"resp={resp2}")
    check("bom_request_consumed_and_idle_exit",
          rc == 0 and not list((d2 / "requests").glob("*.req.json")),
          f"rc={rc}, leftover={list((d2 / 'requests').glob('*'))}")

    # ---- 3) 坏文件隔离: 不可解析请求超龄改名 .bad, 空闲自关恢复(击穿事故的根治验证) ----
    d3 = tmp_root / "s3"
    (d3 / "requests").mkdir(parents=True)
    (d3 / "requests" / "poison.req.json").write_text("﻿{ not valid json", encoding="utf-8")
    p3 = _spawn_worker(d3, idle=1, quarantine=0.3)
    try:
        rc = p3.wait(timeout=10)
        quarantined = (d3 / "requests" / "poison.req.json.bad").exists()
        leftover = (d3 / "requests" / "poison.req.json").exists()
        check("poison_quarantined_and_idle_exit",
              rc == 0 and quarantined and not leftover and _read_status(d3).get("state") == "stopped",
              f"rc={rc}, quarantined={quarantined}, leftover={leftover}, status={_read_status(d3)}")
        resp3 = _wait_responses(d3, ["poison"], timeout=1.0)
        check("poison_quarantine_error_response",
              resp3.get("poison", {}).get("ok") is False
              and "quarantined" in resp3.get("poison", {}).get("error", ""),
              f"resp={resp3}")
    except subprocess.TimeoutExpired:
        p3.kill()
        check("poison_quarantined_and_idle_exit", False,
              "worker 未在 10s 内退出(坏文件仍在冻结空闲计时?)")

    # ---- 4) idle=0: 常驻永不自关 ----
    d4 = tmp_root / "s4"
    (d4 / "requests").mkdir(parents=True)
    p4 = _spawn_worker(d4, idle=0)
    time.sleep(2.5)
    alive4 = p4.poll() is None
    status4 = _read_status(d4)
    p4.kill()
    check("idle_zero_persists", alive4 and status4.get("state") == "ready",
          f"alive={alive4}, status={status4}")

    # ---- 5) 接管: 拒执行非 status 请求 + 空闲计时冻结; 释放后恢复自关 ----
    d5 = tmp_root / "s5"
    (d5 / "requests").mkdir(parents=True)
    (d5 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "tester"}), encoding="utf-8")
    (d5 / "requests" / "rstat.req.json").write_text(
        json.dumps({"op": "status", "args": {}}), encoding="utf-8")
    (d5 / "requests" / "rwrite.req.json").write_text(
        json.dumps({"op": "write", "args": {"path": "Application/Foo"}}), encoding="utf-8")
    t5_start = time.time()
    p5 = _spawn_worker(d5, idle=0.8)
    resp5 = _wait_responses(d5, ["rstat", "rwrite"])
    check("manual_status_allowed", resp5.get("rstat", {}).get("ok") is True, f"resp={resp5}")
    check("manual_write_blocked",
          resp5.get("rwrite", {}).get("ok") is False
          and "manual control" in resp5.get("rwrite", {}).get("error", ""),
          f"resp={resp5}")
    # 接管期间空闲计时冻结: 超过 idle(0.8s) 3 倍仍存活
    remain = 2.5 - (time.time() - t5_start)
    if remain > 0:
        time.sleep(remain)
    frozen_alive = p5.poll() is None
    check("manual_freezes_idle", frozen_alive, "worker 在接管期间空闲自关了")
    # 释放接管 → 恢复空闲自关
    (d5 / "session_control.json").write_text(
        json.dumps({"manual_control": False, "owner": "shared"}), encoding="utf-8")
    try:
        rc = p5.wait(timeout=8)
        check("release_resumes_idle_exit", rc == 0 and _read_status(d5).get("state") == "stopped",
              f"rc={rc}, status={_read_status(d5)}")
    except subprocess.TimeoutExpired:
        p5.kill()
        check("release_resumes_idle_exit", False, "释放接管后 worker 未恢复空闲自关")

    # ---- 6) IPC 客户端 spawn 冷却: 新鲜 error → 快速失败不拉 EXE; 过期 error → 放行 ----
    d6 = tmp_root / "s6"
    d6.mkdir(parents=True)
    client6 = CodesysIpcClient(
        exe=str(d6 / "missing_InoProShop.exe"), profile="test",
        project=d6 / "missing.project", ipc_dir=d6,
        compile_category="test", ready_timeout=2.0)
    (d6 / "worker.status").write_text(
        json.dumps({"state": "error", "error": "工程正被其它 InoProShop 占用", "ts": time.time()}),
        encoding="utf-8")
    t0 = time.time()
    cooled = ""
    try:
        asyncio.run(client6.ensure_worker())
    except RuntimeError as exc:
        cooled = str(exc)
    elapsed = time.time() - t0
    check("spawn_cooldown_fast_fail",
          "冷却" in cooled and elapsed < 1.0
          and not (d6 / "worker_active.py").exists() and not (d6 / "spawn.lock").exists(),
          f"err={cooled!r}, elapsed={elapsed:.2f}s")
    # 过期 error(ts 冷却期外) → 放行到 spawn 路径(EXE 缺失 → OSError, 且 worker 脚本已生成)
    (d6 / "worker.status").write_text(
        json.dumps({"state": "error", "error": "老错误", "ts": time.time() - 120}),
        encoding="utf-8")
    passed_gate = False
    try:
        asyncio.run(client6.ensure_worker())
    except OSError:
        passed_gate = True   # Popen 缺 EXE → FileNotFoundError, 证明冷却门已放行
    except RuntimeError as exc:
        passed_gate = "冷却" not in str(exc)
    check("spawn_cooldown_stale_passes",
          passed_gate and (d6 / "worker_active.py").exists() and not (d6 / "spawn.lock").exists(),
          f"passed_gate={passed_gate}")

    # ---- 7) stop_worker: 不在线 → False 且不写哨兵; 在线 → 写哨兵并等进程退出 ----
    d7 = tmp_root / "s7"
    d7.mkdir(parents=True)
    client7 = CodesysIpcClient(
        exe=str(d7 / "missing.exe"), profile="test", project=d7 / "missing.project",
        ipc_dir=d7, compile_category="test")
    res_offline = asyncio.run(client7.stop_worker(timeout=2.0))
    check("stop_worker_offline_false",
          res_offline is False and not (d7 / "worker.stop").exists(),
          f"res={res_offline}")
    # 迷你真 worker: 子进程轮询 stop 哨兵, 见到即退出(pid 消亡 = 文件锁释放的等价信号)
    stop_path = d7 / "worker.stop"
    mini = subprocess.Popen(
        [sys.executable, "-c",
         "import os,sys,time\n"
         "while not os.path.exists(sys.argv[1]):\n"
         "    time.sleep(0.05)\n",
         str(stop_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (d7 / "worker.status").write_text(
        json.dumps({"state": "ready", "pid": mini.pid, "ts": time.time()}), encoding="utf-8")
    try:
        res_online = asyncio.run(client7.stop_worker(timeout=10.0))
        check("stop_worker_online_true", res_online is True and mini.poll() is not None,
              f"res={res_online}, mini_rc={mini.poll()}")
    finally:
        if mini.poll() is None:
            mini.kill()

    # ---- 8) F1 接管门: 接管态 stop_worker → RuntimeError, 哨兵不写, worker 存活 ----
    d8 = tmp_root / "s8"
    d8.mkdir(parents=True)
    client8 = CodesysIpcClient(
        exe=str(d8 / "missing.exe"), profile="test", project=d8 / "missing.project",
        ipc_dir=d8, compile_category="test")
    (d8 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "tester"}), encoding="utf-8")
    stop8 = d8 / "worker.stop"
    mini8 = subprocess.Popen(
        [sys.executable, "-c",
         "import os,sys,time\n"
         "while not os.path.exists(sys.argv[1]):\n"
         "    time.sleep(0.05)\n",
         str(stop8)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (d8 / "worker.status").write_text(
        json.dumps({"state": "ready", "pid": mini8.pid, "ts": time.time()}), encoding="utf-8")
    try:
        blocked8 = ""
        try:
            asyncio.run(client8.stop_worker(timeout=2.0))
        except RuntimeError as exc:
            blocked8 = str(exc)
        check("manual_stop_blocked", "manual control" in blocked8, f"err={blocked8!r}")
        check("manual_stop_no_sentinel", not stop8.exists(), "接管态不应写 stop 哨兵")
        check("manual_stop_worker_survives", mini8.poll() is None, "接管态 stop 不应杀 worker")
    finally:
        if mini8.poll() is None:
            mini8.kill()

    # ---- 9) F2 活体语义: opening 态可停(写哨兵等退出); 启动窗口(无 status + spawn.lock 活)拒停 ----
    d9 = tmp_root / "s9"
    d9.mkdir(parents=True)
    client9 = CodesysIpcClient(
        exe=str(d9 / "missing.exe"), profile="test", project=d9 / "missing.project",
        ipc_dir=d9, compile_category="test", ready_timeout=2.0)
    stop9 = d9 / "worker.stop"
    mini9 = subprocess.Popen(
        [sys.executable, "-c",
         "import os,sys,time\n"
         "while not os.path.exists(sys.argv[1]):\n"
         "    time.sleep(0.05)\n",
         str(stop9)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (d9 / "worker.status").write_text(
        json.dumps({"state": "opening", "pid": mini9.pid, "ts": time.time()}), encoding="utf-8")
    try:
        res9 = asyncio.run(client9.stop_worker(timeout=8.0))
        check("stop_opening_waits", res9 is True and mini9.poll() is not None,
              f"res={res9}, mini_rc={mini9.poll()}")
    finally:
        if mini9.poll() is None:
            mini9.kill()
    # 启动窗口: spawn 胜者已删 status 且 spawn.lock 持有者(本测试进程)存活 → 拒停让调用方稍后重试
    (d9 / "worker.status").unlink(missing_ok=True)
    (d9 / "spawn.lock").write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")
    window_err = ""
    try:
        asyncio.run(client9.stop_worker(timeout=1.0))
    except RuntimeError as exc:
        window_err = str(exc)
    check("stop_spawn_window_rejects", "正在启动" in window_err, f"err={window_err!r}")
    (d9 / "spawn.lock").unlink(missing_ok=True)

    # ---- 10) F3 超时=取消停止: 哨兵被回收, 不延迟毒杀仍在长操作中的 worker ----
    d10 = tmp_root / "s10"
    d10.mkdir(parents=True)
    client10 = CodesysIpcClient(
        exe=str(d10 / "missing.exe"), profile="test", project=d10 / "missing.project",
        ipc_dir=d10, compile_category="test")
    mini10 = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (d10 / "worker.status").write_text(
        json.dumps({"state": "ready", "pid": mini10.pid, "ts": time.time()}), encoding="utf-8")
    try:
        timed_out = False
        try:
            asyncio.run(client10.stop_worker(timeout=1.0))
        except TimeoutError:
            timed_out = True
        check("stop_timeout_raises", timed_out, "永不看哨兵的 worker 应触发 TimeoutError")
        check("stop_timeout_sentinel_recycled", not (d10 / "worker.stop").exists(),
              "超时路径应回收 stop 哨兵(取消停止)")
        check("stop_timeout_worker_alive", mini10.poll() is None, "")
    finally:
        if mini10.poll() is None:
            mini10.kill()

    # ---- 11) F7: 隔离恒失效(未来 mtime, 年龄恒为负)时, 空闲自关仍须限时生效 ----
    d11 = tmp_root / "s11"
    (d11 / "requests").mkdir(parents=True)
    bad11 = d11 / "requests" / "future.req.json"
    bad11.write_text("{ not valid json", encoding="utf-8")
    t11 = time.time()
    os.utime(bad11, (t11, t11 + 3600))   # 未来 mtime: quarantine_if_stale 年龄为负 → 恒放过
    p11 = _spawn_worker(d11, idle=1)
    try:
        rc = p11.wait(timeout=10)
        check("future_mtime_idle_exit",
              rc == 0 and _read_status(d11).get("state") == "stopped",
              f"rc={rc}, status={_read_status(d11)}")
    except subprocess.TimeoutExpired:
        p11.kill()
        check("future_mtime_idle_exit", False,
              "隔离失效时坏文件仍冻结空闲自关 (F7 未修)")

    # ---- 12) F7 守卫: 同 fixture + idle=0 → 常驻不退 (IDLE_TIMEOUT_SEC>0 守卫保留) ----
    d12 = tmp_root / "s12"
    (d12 / "requests").mkdir(parents=True)
    bad12 = d12 / "requests" / "future.req.json"
    bad12.write_text("{ not valid json", encoding="utf-8")
    t12 = time.time()
    os.utime(bad12, (t12, t12 + 3600))
    p12 = _spawn_worker(d12, idle=0)
    time.sleep(2.5)
    alive12 = p12.poll() is None
    p12.kill()
    check("future_mtime_idle_zero_persists", alive12, "idle=0 常驻被 F7 改动破坏")

    # ---- 13) F7 接管冻结: 同 fixture + manual_control=true → 冻结不退; 释放后限时退出 ----
    d13 = tmp_root / "s13"
    (d13 / "requests").mkdir(parents=True)
    bad13 = d13 / "requests" / "future.req.json"
    bad13.write_text("{ not valid json", encoding="utf-8")
    t13 = time.time()
    os.utime(bad13, (t13, t13 + 3600))
    (d13 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "tester"}), encoding="utf-8")
    p13 = _spawn_worker(d13, idle=0.8)
    time.sleep(2.5)   # 超过 idle 3 倍
    frozen13 = p13.poll() is None
    check("future_mtime_manual_freezes_idle", frozen13,
          "接管期间 processed==0 分支的空闲判定未冻结")
    (d13 / "session_control.json").write_text(
        json.dumps({"manual_control": False, "owner": "shared"}), encoding="utf-8")
    try:
        rc = p13.wait(timeout=8)
        check("future_mtime_release_resumes_exit", rc == 0, f"rc={rc}")
    except subprocess.TimeoutExpired:
        p13.kill()
        check("future_mtime_release_resumes_exit", False, "释放接管后仍未空闲自关")

    # ---- 14) F9: 带 BOM 的 session_control.json — worker 拒 write 且客户端接管门同判 (split-brain 钉死) ----
    d14 = tmp_root / "s14"
    (d14 / "requests").mkdir(parents=True)
    (d14 / "session_control.json").write_text(
        "\ufeff" + json.dumps({"manual_control": True, "owner": "tester"}), encoding="utf-8")
    (d14 / "requests" / "rwrite.req.json").write_text(
        json.dumps({"op": "write", "args": {"path": "Application/Foo"}}), encoding="utf-8")
    p14 = _spawn_worker(d14, idle=0.8)
    resp14 = _wait_responses(d14, ["rwrite"])
    p14.kill()   # 接管冻结态, 不会自关, 直接杀
    check("bom_control_worker_blocks",
          resp14.get("rwrite", {}).get("ok") is False
          and "manual control" in resp14.get("rwrite", {}).get("error", ""),
          f"resp={resp14}")
    client14 = CodesysIpcClient(
        exe=str(d14 / "missing.exe"), profile="test", project=d14 / "missing.project",
        ipc_dir=d14, compile_category="test")
    raised14 = False
    try:
        client14._assert_not_manual_control("write")
    except RuntimeError:
        raised14 = True
    check("bom_control_client_gate_blocks", raised14,
          "客户端接管门没读出 BOM 标志 (split-brain: worker 拒而客户端放行)")

    # ---- 15) F8: 过期接管标志(updated_at 25h 前) → 非 status 请求放行 + 空闲自关恢复 ----
    d15 = tmp_root / "s15"
    (d15 / "requests").mkdir(parents=True)
    (d15 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "ghost",
                    "updated_at": time.time() - 25 * 3600}), encoding="utf-8")
    (d15 / "requests" / "rlist.req.json").write_text(
        json.dumps({"op": "list", "args": {}}), encoding="utf-8")
    p15 = _spawn_worker(d15, idle=1)
    resp15 = _wait_responses(d15, ["rlist"])
    check("expired_manual_allows_ops", resp15.get("rlist", {}).get("ok") is True,
          f"resp={resp15}")
    try:
        rc = p15.wait(timeout=10)
        check("expired_manual_resumes_idle_exit", rc == 0, f"rc={rc}")
    except subprocess.TimeoutExpired:
        p15.kill()
        check("expired_manual_resumes_idle_exit", False, "过期接管标志仍冻结空闲自关")

    # ---- 16) F8 客户端侧: 过期标志不抛; 新鲜标志仍抛 ----
    d16 = tmp_root / "s16"
    d16.mkdir(parents=True)
    client16 = CodesysIpcClient(
        exe=str(d16 / "missing.exe"), profile="test", project=d16 / "missing.project",
        ipc_dir=d16, compile_category="test")
    (d16 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "ghost",
                    "updated_at": time.time() - 25 * 3600}), encoding="utf-8")
    expired_ok = True
    try:
        client16._assert_not_manual_control("write")
    except RuntimeError:
        expired_ok = False
    check("client_expired_manual_passes", expired_ok, "过期标志仍被客户端门拦截")
    (d16 / "session_control.json").write_text(
        json.dumps({"manual_control": True, "owner": "op",
                    "updated_at": time.time()}), encoding="utf-8")
    fresh_blocked = False
    try:
        client16._assert_not_manual_control("write")
    except RuntimeError:
        fresh_blocked = True
    check("client_fresh_manual_blocks", fresh_blocked, "新鲜标志未被拦截")

    # ---- 17) F6: 老化合法请求 + 首读瞬态失败 → 不得隔离, 最终 ok 响应(误伤回归) ----
    d17 = tmp_root / "s17"
    (d17 / "requests").mkdir(parents=True)
    req17 = d17 / "requests" / "aged.req.json"
    req17.write_text(json.dumps({"op": "list", "args": {}}), encoding="utf-8")
    t17 = time.time()
    os.utime(req17, (t17 - 60, t17 - 60))   # 回拨 60s: 年龄远超默认 QUARANTINE_AGE_SEC(10s)
    p17 = _spawn_worker(d17, idle=1, flaky_reads=1)   # 首读必败(瞬态), 次轮成功
    resp17 = _wait_responses(d17, ["aged"])
    check("aged_transient_read_not_quarantined",
          resp17.get("aged", {}).get("ok") is True
          and not list((d17 / "requests").glob("*.bad")),
          f"resp={resp17}, bad={list((d17 / 'requests').glob('*.bad'))}")
    try:
        p17.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p17.kill()

    # ---- 18) 双 dispatch: 请求删除失败被吞 → 同一请求绝不重复执行 ----
    d18 = tmp_root / "s18"
    (d18 / "requests").mkdir(parents=True)
    (d18 / "requests" / "once.req.json").write_text(
        json.dumps({"op": "save", "args": {}}), encoding="utf-8")
    p18 = _spawn_worker(d18, idle=1, sticky_removes=3)   # 前 3 次 os.remove(req) 失败
    resp18 = _wait_responses(d18, ["once"])
    try:
        rc18 = p18.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p18.kill()
        rc18 = None
    save_count = ((d18 / "save_count.txt").read_text().strip()
                  if (d18 / "save_count.txt").exists() else "0")
    check("no_double_dispatch_on_remove_failure",
          resp18.get("once", {}).get("ok") is True and save_count == "1" and rc18 == 0,
          f"resp={resp18}, save_count={save_count}, rc={rc18}")

    print(f"\nCODESYS worker 生命周期/会话控制离线测试: 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--as-worker":
        _run_worker_child(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
                          int(sys.argv[5]) if len(sys.argv) > 5 else 0,
                          int(sys.argv[6]) if len(sys.argv) > 6 else 0)
        sys.exit(0)
    sys.exit(main())
