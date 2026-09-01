"""launcher PLC 链路预检的离线单测。

全部 mock 掉真 socket 与真 PowerShell:不碰网络、不起进程。
真机两态 (拔线 / 插线) 的验证靠手测,见实施计划验收第 3/4 条。
"""

from __future__ import annotations

import json
import socket
import subprocess

import eit_ptlc.main as m


# ---------------------------------------------------------------------------
# _tcp_reachable
# ---------------------------------------------------------------------------

class _FakeSock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_tcp_reachable_true_on_connect(monkeypatch):
    monkeypatch.setattr(m.socket, "create_connection", lambda *a, **k: _FakeSock())
    assert m._tcp_reachable("192.168.0.50", 4840) is True


def test_tcp_reachable_false_on_oserror(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(m.socket, "create_connection", _boom)
    assert m._tcp_reachable("192.168.0.50", 4840) is False


def test_tcp_reachable_passes_timeout(monkeypatch):
    seen = {}

    def _capture(addr, timeout=None):
        seen["addr"], seen["timeout"] = addr, timeout
        return _FakeSock()

    monkeypatch.setattr(m.socket, "create_connection", _capture)
    m._tcp_reachable("10.0.0.1", 1234, timeout=0.5)
    assert seen["addr"] == ("10.0.0.1", 1234)
    assert seen["timeout"] == 0.5


# ---------------------------------------------------------------------------
# _plc_route_hint —— 判据是 Find-NetRoute 的 NextHop
# ---------------------------------------------------------------------------

def _ps_stdout(payload) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr="")


# 本机实测的地址/网卡表 (以太网 2 = idx 7 是 PLC 口, 掩码确实是 /16)
_ADDRS = [
    {"IPAddress": "10.37.2.7", "PrefixLength": 24, "InterfaceIndex": 12},
    {"IPAddress": "192.168.1.35", "PrefixLength": 24, "InterfaceIndex": 20},
    {"IPAddress": "192.168.0.63", "PrefixLength": 16, "InterfaceIndex": 7},
]


def _iface_payload(*, plc_nic_up: bool) -> dict:
    return {
        "Addrs": _ADDRS,
        "Adapters": [
            {"Index": 12, "Up": True},
            {"Index": 20, "Up": True},
            {"Index": 7, "Up": plc_nic_up},
        ],
    }


def test_route_hint_blames_link_when_plc_nic_down(monkeypatch):
    """本次故障的那一态: PLC 网段的网卡不是 Up。必须指向网线/网卡。"""
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _ps_stdout(_iface_payload(plc_nic_up=False)))
    hint = m._plc_route_hint("192.168.0.50")
    assert "192.168.0.63" in hint
    assert "网线" in hint
    assert "PLC 电源" not in hint, "掉链路时不该把人引去查 PLC 电源"


def test_route_hint_blames_plc_when_nic_up(monkeypatch):
    """网卡正常却连不上, 那就不是线的锅, 该查 PLC 侧。

    这条同时是回归闸: 早先实现拿 Find-NetRoute 的 NextHop 判链路, 而它看 ARP ——
    网卡 Up 但 PLC 没开机时也会返回"走默认网关", 与掉链路同一签名, 分不开两者。
    """
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _ps_stdout(_iface_payload(plc_nic_up=True)))
    hint = m._plc_route_hint("192.168.0.50")
    assert "PLC 电源" in hint
    assert "192.168.0.63" in hint
    assert "网线" not in hint


def test_route_hint_reports_when_no_nic_on_plc_subnet(monkeypatch):
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: _ps_stdout({
            "Addrs": [{"IPAddress": "10.37.2.7", "PrefixLength": 24, "InterfaceIndex": 12}],
            "Adapters": [{"Index": 12, "Up": True}],
        }))
    assert "没有任何网卡在 PLC 所在网段" in m._plc_route_hint("192.168.0.50")


def test_route_hint_picks_longest_prefix_on_subnet(monkeypatch):
    """同网段有多张网卡时取掩码最长的那张 (最贴切), 而不是撞见的第一张。"""
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: _ps_stdout({
            "Addrs": [
                {"IPAddress": "192.168.0.63", "PrefixLength": 16, "InterfaceIndex": 7},
                {"IPAddress": "192.168.0.9", "PrefixLength": 24, "InterfaceIndex": 8},
            ],
            "Adapters": [{"Index": 7, "Up": False}, {"Index": 8, "Up": True}],
        }))
    hint = m._plc_route_hint("192.168.0.50")
    assert "192.168.0.9" in hint and "PLC 电源" in hint


def test_route_hint_handles_single_object_payload(monkeypatch):
    """PowerShell 5.1 无 -AsArray, 单元素集合 ConvertTo-Json 出 dict 而非 list。"""
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: _ps_stdout({
            "Addrs": {"IPAddress": "192.168.0.63", "PrefixLength": 16, "InterfaceIndex": 7},
            "Adapters": {"Index": 7, "Up": False},
        }))
    assert "网线" in m._plc_route_hint("192.168.0.50")


def test_route_hint_degrades_when_iface_table_empty(monkeypatch):
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _ps_stdout({"Addrs": [], "Adapters": []}))
    assert "PLC 不可达" in m._plc_route_hint("192.168.0.50")


def test_route_hint_degrades_on_unresolvable_hostname(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no such host")

    monkeypatch.setattr(m.socket, "gethostbyname", _boom)
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _ps_stdout(_iface_payload(plc_nic_up=True)))
    assert "PLC 不可达" in m._plc_route_hint("plc-does-not-resolve")


def test_local_ifaces_empty_on_malformed_json(monkeypatch):
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"))
    assert m._local_ipv4_ifaces() == []


def test_local_ifaces_skips_unparsable_rows(monkeypatch):
    monkeypatch.setattr(
        m.subprocess, "run",
        lambda *a, **k: _ps_stdout({
            "Addrs": [
                {"IPAddress": "192.168.0.63", "PrefixLength": 16, "InterfaceIndex": 7},
                {"IPAddress": "bad", "PrefixLength": None, "InterfaceIndex": None},
            ],
            "Adapters": [{"Index": 7, "Up": True}, {"Index": None, "Up": True}],
        }))
    ifaces = m._local_ipv4_ifaces()
    assert ifaces == [{"ip": "192.168.0.63", "prefix": 16, "index": 7, "up": True}]


def test_route_hint_handles_loopback_target(monkeypatch):
    """plc.url 可指向本机 Mock; 回环没有对应网卡, 不能误报成掉链路。"""
    def _boom(*a, **k):
        raise AssertionError("回环目标不该去查网卡表")

    monkeypatch.setattr(m.subprocess, "run", _boom)
    hint = m._plc_route_hint("127.0.0.1")
    assert "Mock" in hint
    assert "网线" not in hint


def test_route_hint_degrades_when_powershell_times_out(monkeypatch):
    """归因手段本身不能变成新的故障点。"""
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=5.0)

    monkeypatch.setattr(m.subprocess, "run", _boom)
    hint = m._plc_route_hint("192.168.0.50")
    assert hint and "PLC 不可达" in hint


def test_route_hint_degrades_when_powershell_missing(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("powershell not found")

    monkeypatch.setattr(m.subprocess, "run", _boom)
    assert "PLC 不可达" in m._plc_route_hint("192.168.0.50")


# ---------------------------------------------------------------------------
# _plc_link_probe
# ---------------------------------------------------------------------------

def test_link_probe_returns_none_when_reachable(monkeypatch):
    monkeypatch.setattr(m, "_tcp_reachable", lambda *a, **k: True)
    assert m._plc_link_probe("opc.tcp://192.168.0.50:4840") is None


def test_link_probe_defaults_port_when_url_omits_it(monkeypatch):
    seen = {}

    def _probe(host, port, *a, **k):
        seen["host"], seen["port"] = host, port
        return True

    monkeypatch.setattr(m, "_tcp_reachable", _probe)
    m._plc_link_probe("opc.tcp://192.168.0.50")
    assert seen == {"host": "192.168.0.50", "port": m._DEFAULT_OPCUA_PORT}


def test_link_probe_reports_reason_when_unreachable(monkeypatch):
    monkeypatch.setattr(m, "_tcp_reachable", lambda *a, **k: False)
    monkeypatch.setattr(m, "_plc_route_hint", lambda host: "归因串")
    reason = m._plc_link_probe("opc.tcp://192.168.0.50:4840")
    assert reason is not None
    assert "192.168.0.50:4840" in reason and "归因串" in reason


def test_link_probe_rejects_unparsable_url(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("地址都解析不出来, 不该再去探网络")

    monkeypatch.setattr(m, "_tcp_reachable", _boom)
    reason = m._plc_link_probe("不是个地址")
    assert reason is not None and "plc.url" in reason


# ---------------------------------------------------------------------------
# _config_plc_url
# ---------------------------------------------------------------------------

def test_config_plc_url_reads_app_yaml():
    """真读仓库里的 app.yaml —— 它是该地址的唯一真源。"""
    assert m._config_plc_url().startswith("opc.tcp://")


def test_config_plc_url_falls_back_when_yaml_broken(monkeypatch):
    real_read = m.Path.read_text

    def _boom(self, *a, **k):
        if self.name == "app.yaml":
            raise OSError("boom")
        return real_read(self, *a, **k)

    monkeypatch.setattr(m.Path, "read_text", _boom)
    assert m._config_plc_url() == m._PLC_URL_FALLBACK


# ---------------------------------------------------------------------------
# _start_all 的闸门行为
# ---------------------------------------------------------------------------

def _stub_start_all(monkeypatch, *, link_ok: bool):
    """把 _start_all 里除预检外的一切都掐掉,只观察它走不走到起后端。"""
    started: list[str] = []
    monkeypatch.setattr(m, "_free_port", lambda port: None)
    monkeypatch.setattr(m, "_start_mqtt_broker", lambda: object())
    monkeypatch.setattr(m, "_start_pallas_bridge", lambda: object())
    monkeypatch.setattr(m, "_wait_ready", lambda *a, **k: True)
    monkeypatch.setattr(m, "_stop_all", lambda procs: None)
    monkeypatch.setattr(m, "_config_plc_url", lambda: "opc.tcp://192.168.0.50:4840")
    monkeypatch.setattr(m, "_plc_link_probe", lambda url: None if link_ok else "链路不通")
    monkeypatch.setattr(m, "_tcp_reachable", lambda *a, **k: False)

    def _backend(*, real=False):
        started.append("后端")
        return object()

    monkeypatch.setattr(m, "_start_backend", _backend)
    return started


def test_start_all_blocks_backend_when_link_down(monkeypatch):
    started = _stub_start_all(monkeypatch, link_ok=False)
    m._start_all({}, open_browser=False, real=True)
    assert started == [], "PLC 不通时不该起后端"


def test_start_all_starts_backend_when_link_ok(monkeypatch):
    started = _stub_start_all(monkeypatch, link_ok=True)
    monkeypatch.setattr(m, "_lan_ips", lambda: [])
    m._start_all({}, open_browser=False, real=True)
    assert started == ["后端"]


def test_start_all_skips_probe_when_flag_set(monkeypatch):
    started = _stub_start_all(monkeypatch, link_ok=False)
    monkeypatch.setattr(m, "_lan_ips", lambda: [])

    def _boom(url):
        raise AssertionError("--skip-link-check 时不该探测")

    monkeypatch.setattr(m, "_plc_link_probe", _boom)
    m._start_all({}, open_browser=False, real=True, skip_link_check=True)
    assert started == ["后端"]


def test_start_all_never_probes_in_sim_mode(monkeypatch):
    started = _stub_start_all(monkeypatch, link_ok=False)
    monkeypatch.setattr(m, "_lan_ips", lambda: [])

    def _boom(url):
        raise AssertionError("sim 模式不碰真 PLC, 不该探测")

    monkeypatch.setattr(m, "_plc_link_probe", _boom)
    m._start_all({}, open_browser=False, real=False)
    assert started == ["后端"]
