"""pTLC 上位机前端启动入口 (开发编排, 多进程 + 分控台窗 + 交互菜单)
===============================================================
功能:
    一条命令拉起 MQTT broker(:1883)、PALLASBridge(:18888) 与后端 (uvicorn :18080);
    后端监听地址取自 config/app.yaml api.host (当前 0.0.0.0 → 同网段设备可经
    http://<本机IP>:18080/ 访问, 就绪日志会打印该地址).
    前端默认由后端同源托管 web/dist 构建产物, 不再单独占一个窗口 —— 加 --dev-frontend
    才另起 vite 开发服务器 (:15173, 带 HMR, 供改前端源码时用).
    每次启动前自动杀掉占用相关端口的残留进程, 随后进入交互菜单 (启动/重启/停止/退出).
    各子进程在独立的原生控制台窗口 (PowerShell/cmd) 中运行并输出自身日志,
    交互菜单留在当前终端保持干净, 不被日志刷屏.
    MQTT/Bridge/后端三个 Python 子进程经 tools/run_logged 包一层, 输出在窗口滚动的同时
    落盘 eit_ptlc/var/logs/<mqtt|bridge|backend>.log (上一次的轮转为 *.prev.log);
    子进程就绪前退出或中途崩溃时, launcher 把该日志末尾若干行带回本终端.
    默认 sim 模式 (进程内 Mock PLC + 内存机器人仿真), --real 切换为真机 PLC + Dobot 直连.

为何:
    后端 (FastAPI /api:18080) 与 PALLASBridge / MQTT broker 是独立进程,
    Bridge 保持纠偏回传端口在线. 本入口取代'手工开多个终端'的流程, 单命令启动整套 UI.
    前端 api.js 用 baseURL '/' 与 location.host, 天然同源, 故后端直接托管 dist 即可,
    省掉一个常驻窗口与一层 vite 代理; 只有需要 HMR 时才值得多开那个窗口.
    日志直接落到各自的原生控制台窗 (可滚动回看 / 搜索 / 复制), 无需自建 GUI 日志窗;
    但窗口随进程一起消失, 崩溃现场留不下 —— 2026-07-28 后端因 PLC 网口链路断而起服失败,
    现场只剩"退出码=3", 驱动打出的排查结论全丢了. 故子进程再包一层 tee (tools/run_logged):
    窗口观感不变, 日志额外落盘, 崩溃时由 launcher 主动把尾巴打到本终端.
    端口取不常用值规避与其它本机服务冲突; 启动即按端口清理残留, 避免'端口被上一份
    实例占用'导致后端 OPC UA 绑定失败 (OSError 10048). sim 后端自带进程内 Mock PLC
    与内存机器人仿真, 无需单独起 mock 进程.
    后端监听地址遵循 config 单一事实源: app.yaml api.host 此前从未被消费 (uvicorn
    缺省绑 127.0.0.1, 仅本机可访问), 现由 launcher 读取传 --host 使之生效; 不另设
    CLI 参数, 与端口不暴露为参数同理. ⚠ API 无鉴权, 0.0.0.0 = 同网段任何人可操控
    真机; 需收紧时改 api.host 为 127.0.0.1, 或防火墙对 18080 限定来源网段.

使用:
    cd eit_ptlc/web && npm run build     # 首次 / 前端有改动时重建产物
    python eit_ptlc/main.py
    可选参数:
        --no-browser    就绪后不自动打开浏览器
        --real          连接真机 PLC + 真机机器人 (默认 sim 模式)
        --dev-frontend  另起 vite 开发服务器 (:15173, HMR); 默认后端同源托管 dist
        --skip-link-check  跳过 --real 起后端前的 PLC 链路预检
    菜单: [1] 启动   [2] 重启   [3] 停止   [4] 退出

    --real 会在起后端前先探一次 PLC (app.yaml plc.url) 的裸 TCP: 通了才起, 不通就
    打印一行归因并退回菜单. 理由是后端 real 模式 lifespan 里 driver.connect() 无容错,
    PLC 连不上 = uvicorn 退出码 3 + 满屏 asyncio traceback, 而驱动自己那句人话结论
    会被日志回打的末 40 行截掉.

验证:
    选 [1]/[2] 后后端控制台窗出现 'Uvicorn running on http://0.0.0.0:18080' /
    'Application startup complete', 浏览器自动打开 http://localhost:18080/ 运维页,
    launcher 另打印 '局域网访问: http://<本机IP>:18080/', 同网段设备开该地址见同一页面
    (打不开先查防火墙对 18080 的入站放行);
    加 --dev-frontend 时另有前端控制台窗出现 vite 'Local: http://localhost:15173/',
    浏览器改开 15173. 选 [3] 各进程数秒内退出 (其控制台窗关闭); 选 [4] 或 Ctrl+C
    清理后退出, 无残留 uvicorn / node.
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("launcher")


def _config_api_host() -> str:
    """功能: 读 config/app.yaml 的 api.host 作为后端 uvicorn 监听地址.

    返回:
        str, api.host 值; 文件/键缺失或解析失败时回退 "0.0.0.0" (与 config/models.py ApiCfg 默认一致)
    说明:
        api.host 曾是从未被消费的死配置 (launcher 起 uvicorn 只传 --port, uvicorn 缺省绑
        127.0.0.1, 导致仅本机可访问), 由本函数使之生效. yaml 延迟导入: launcher 其余部分
        纯标准库, PyYAML 已列入 _PY_CHILD_DEPS 预检, 这里缺失时不炸 launcher 而回退默认值.
    """
    try:
        import yaml
        cfg = yaml.safe_load(
            (Path(__file__).resolve().parent / "config" / "app.yaml").read_text(encoding="utf-8")
        )
        host = str((cfg.get("api") or {}).get("host") or "").strip()
    except Exception:
        return "0.0.0.0"
    return host or "0.0.0.0"


def _config_plc_url() -> str:
    """功能: 读 config/app.yaml 的 plc.url, 供 real 模式起后端前的链路预检定位 PLC.

    返回:
        str, plc.url 值; 文件/键缺失或解析失败时回退 _PLC_URL_FALLBACK
    说明:
        与 _config_api_host 同一形状 (yaml 延迟导入 + 异常回退): 预检本身绝不能
        成为新的启动故障点, 读不到配置就退回默认地址照常探测.
    """
    try:
        import yaml
        cfg = yaml.safe_load(
            (Path(__file__).resolve().parent / "config" / "app.yaml").read_text(encoding="utf-8")
        )
        url = str((cfg.get("plc") or {}).get("url") or "").strip()
    except Exception:
        return _PLC_URL_FALLBACK
    return url or _PLC_URL_FALLBACK


def _lan_ips() -> list[str]:
    """功能: 枚举本机局域网 IPv4, 供就绪日志打印同网段设备可访问的 URL.

    返回:
        list[str], 候选地址, RFC1918 私网段排前; 探测不到返回空表
    说明:
        多网卡机器 (实验室有线 + 办公 WiFi 等) 逐个列出, 访问者自选与其同网段的那个.
        不用'UDP connect 查默认路由'技巧: 本机开 TUN 代理时它拿到的是虚拟网卡
        fake-IP (实测 Mihomo 198.18.0.1), 他机不可达. 故以 gethostbyname_ex 枚举
        为准, 按段过滤: 排除回环 127/8、链路本地 169.254/16 (未拿到 DHCP 的假地址)、
        基准测试段 198.18/15 (TUN fake-IP 常用)、CGNAT 100.64/10.
    """
    try:
        addrs = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    preferred: list[str] = []
    other: list[str] = []
    for addr in addrs:
        octets = addr.split(".")
        if len(octets) != 4:
            continue
        o1, o2 = int(octets[0]), int(octets[1])
        if o1 == 127 or (o1 == 169 and o2 == 254) or (o1 == 198 and o2 in (18, 19)) \
                or (o1 == 100 and 64 <= o2 <= 127):
            continue
        rfc1918 = o1 == 10 or (o1 == 172 and 16 <= o2 <= 31) or (o1 == 192 and o2 == 168)
        (preferred if rfc1918 else other).append(addr)
    return preferred + other


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# 后端口与 web/vite.config.js 的代理目标 (http://localhost:18080) 强绑定, 不暴露为参数以免代理错位
BACKEND_PORT = 18080
# 后端监听地址真源 = config/app.yaml api.host (默认 0.0.0.0 → 局域网可访问, 改 127.0.0.1 仅本机);
# 同为不暴露 CLI 参数, 想改就改配置
BACKEND_HOST = _config_api_host()
# 前端口与 web/vite.config.js 的 server.port (strictPort) 强绑定
FRONTEND_PORT = 15173
# PALLASBridge HTTP 端口; 回传监听端口与 app.yaml pallas_vision.listen_port 保持一致
PALLAS_BRIDGE_PORT = 18888
PALLAS_CALLBACK_PORT = 18887
# OPC UA Mock 端口 = runtime/bootstrap.py 的 _SIM_URL 端口; launcher 不绑定它, 仅在启动前清理其残留占用
OPCUA_PORT = 48490
# 内置 MQTT broker 端口 = app.yaml water_level.broker_port; 香橙派与后端液位客户端均连它 (监听 0.0.0.0)
MQTT_BROKER_PORT = 1883
_BACKEND_APP = "eit_ptlc.runtime.bootstrap:app"
# 后端 + PALLASBridge 两个 sys.executable 子进程的顶层 import 硬依赖并集 (import 名: pip 名) +
# launcher 以 -m uvicorn 起后端所需的 uvicorn; 缺任一则对应子进程 import 即 ModuleNotFoundError
# 退出码=1, 且它们跑在独立控制台窗崩溃一闪而过, 故启动前统一预检 (import 名与 pip 名不一致时分列)
_PY_CHILD_DEPS = {
    "asyncua": "asyncua",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "yaml": "PyYAML",
    "numpy": "numpy",
    "httpx": "httpx",
    "msgpack": "msgpack",
    "zstandard": "zstandard",
    "ruamel": "ruamel.yaml",
    "python_multipart": "python-multipart",
}
# 后端子进程的 cwd = 仓库根, 使 eit_ptlc 包可被 `python -m uvicorn` 导入
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = Path(__file__).resolve().parent / "web"
# 就绪等待上限 (秒): 覆盖首次启动 vite 依赖预构建的耗时
_READY_TIMEOUT = 40.0
# 子进程日志双写目录 (eit_ptlc/var/ 已在 .gitignore); 文件名见 _LOG_STEMS
_LOG_DIR = Path(__file__).resolve().parent / "var" / "logs"
# 进程登记名 -> 日志文件名 (无条目者不包 tee: 前端走 shell 的 npm, 不吃 Python 那套 env)
_LOG_STEMS = {"MQTT": "mqtt", "PALLASBridge": "bridge", "后端": "backend"}
# 子进程异常退出时回打到本终端的日志行数
_LOG_TAIL_LINES = 40
# real 模式起后端前的 PLC 链路预检 (sim 不探)
# 地址真源 = app.yaml plc.url; 读不到时的回退值需与该文件现值一致
_PLC_URL_FALLBACK = "opc.tcp://192.168.0.50:4840"
# URL 省略端口时的 OPC UA 缺省端口, 与 driver/opcua_driver.py _DEFAULT_OPCUA_PORT 一致
_DEFAULT_OPCUA_PORT = 4840
# 裸 TCP 建连探测超时 (秒): 通的时候实测 15ms, 给 2s 是留给链路抖动, 不是留给"慢"
_PLC_PROBE_TIMEOUT = 2.0
# 归因用的 PowerShell 调用超时 (秒); 超时按"归因不可用"退化, 不阻断结论
_ROUTE_HINT_TIMEOUT = 5.0
# 机器人地址: 与 PLC 同网段同网口, 探它只为区分故障面 (两个都不通=网口问题), 不作为闸门
_ROBOT_PROBE_HOSTPORT = ("192.168.0.15", 29999)


# ---------------------------------------------------------------------------
# 子进程管理
# ---------------------------------------------------------------------------

def _port_open(port: int) -> bool:
    """功能: 探测本机端口是否已接受连接.

    参数:
        port: 待探测的 TCP 端口
    返回:
        bool, 能在 0.5s 内建立连接为 True, 否则 False
    说明:
        用 localhost 而非 127.0.0.1: vite 默认仅监听 IPv6 (::1), uvicorn 监听 IPv4
        (127.0.0.1); create_connection 会遍历 getaddrinfo 返回的全部地址逐个尝试,
        与浏览器解析 localhost 的行为一致, 故同一探测对前后端均可命中.
    """
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def _pids_on_port(port: int) -> list[int]:
    """功能: 查出在指定 TCP 端口上处于 LISTENING 状态的所有进程 PID.

    参数:
        port: 目标 TCP 端口
    返回:
        list[int], 监听该端口的 PID 列表 (去重; 已排除 PID 0 与本启动器自身)
    """
    # 不加 `-p TCP`: 该过滤只列 IPv4, 而 vite 默认仅监听 IPv6 ([::1]:15173),
    # 会漏杀 vite 残留进程导致端口永久被占; 不带协议过滤的 netstat 对 IPv4/IPv6
    # 监听行的协议列均为 "TCP", 下方 parts[0]=="TCP" 已能正确区分并跳过 UDP.
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True, errors="ignore", check=False,
    )
    self_pid = os.getpid()
    suffix = f":{port}"
    pids: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP" or parts[3] != "LISTENING":
            continue
        local = parts[1]
        if not local.endswith(suffix):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid in (0, self_pid) or pid in pids:
            continue
        pids.append(pid)
    return pids


def _proc_name(pid: int) -> str:
    """功能: 取指定 PID 的进程映像名, 用于杀进程前的中文提示.

    参数:
        pid: 进程号
    返回:
        str, 进程映像名 (如 python.exe); 查不到返回 '未知'
    """
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True, text=True, errors="ignore", check=False,
    )
    line = result.stdout.strip()
    if line.startswith('"'):
        return line.split('","', 1)[0].strip('"')
    return "未知"


def _free_port(port: int) -> None:
    """功能: 释放指定端口 — 杀掉所有在该端口 LISTENING 的进程 (连同其进程树).

    参数:
        port: 待释放的 TCP 端口
    """
    for pid in _pids_on_port(port):
        name = _proc_name(pid)
        log.info("[端口 %d] 释放: 终止占用进程 PID=%d (%s)", port, pid, name)
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )


class _ChildExited(RuntimeError):
    """子进程在就绪前退出; 额外带进程登记名, 供上层定位该回打哪份日志."""

    def __init__(self, name: str, code) -> None:
        super().__init__(f"{name} 进程在就绪前退出 (退出码={code})")
        self.name = name


def _wait_ready(items: list[tuple[str, subprocess.Popen, int]], timeout: float) -> bool:
    """功能: 等待所有子进程对应端口就绪, 同时监测进程是否提前退出.

    参数:
        items: [(名称, 子进程, 端口), ...]
        timeout: 总等待上限 (秒)
    返回:
        bool, 全部端口就绪返回 True, 超时返回 False
    异常:
        _ChildExited (RuntimeError 子类), 任一子进程在就绪前退出 (附带退出码与进程名),
        交由上层回打其日志尾巴并进入清理
    """
    deadline = time.monotonic() + timeout
    pending = list(items)
    while pending and time.monotonic() < deadline:
        for item in list(pending):
            name, proc, port = item
            if proc.poll() is not None:
                raise _ChildExited(name, proc.returncode)
            if _port_open(port):
                log.info("[%s] 就绪 (:%d)", name, port)
                pending.remove(item)
        if pending:
            time.sleep(0.3)
    return not pending


def _terminate_tree(name: str, proc: subprocess.Popen) -> None:
    """功能: 强制终止子进程及其整棵进程树 (Windows taskkill /T).

    参数:
        name: 进程名称 (用于日志)
        proc: 子进程对象
    """
    if proc.poll() is not None:
        return
    log.info("[%s] 正在终止进程树 (pid=%d)", name, proc.pid)
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _graceful_stop_backend(
    proc: subprocess.Popen, *, break_timeout: float = 5.0, wait_timeout: float = 8.0,
) -> bool:
    """功能: 优雅关停独立控制台里的后端 uvicorn, 让其跑完 lifespan 收尾。

    机制: uvicorn 在 Windows 默认捕获 SIGBREAK → should_exit → lifespan shutdown
    (含 PLC 断开 / 机器人 close / 在飞拍照 finally 关 UV+复位相机 / run_store 关闭)。
    后端在 CREATE_NEW_CONSOLE 独立控制台, 故用一次性 helper 子进程 FreeConsole →
    AttachConsole(后端) → GenerateConsoleCtrlEvent(CTRL_BREAK, 组0) 广播, 避免扰动
    launcher 自身控制台/交互菜单。

    参数:
        proc: 后端子进程
        break_timeout: 投递 helper 的最长等待 (秒)
        wait_timeout: 投递后等后端优雅退出的最长等待 (秒)
    返回:
        bool, 后端已(优雅)退出为 True; 超时/失败为 False (调用方 taskkill 兜底)
    """
    if proc.poll() is not None:
        return True
    log.info("[后端] 优雅关停: 投递 CTRL_BREAK 并等待 lifespan 收尾 ...")
    try:
        subprocess.run(
            [sys.executable, "-c",
             "import ctypes,sys;k=ctypes.windll.kernel32;"
             "k.FreeConsole();k.AttachConsole(int(sys.argv[1]));"
             "k.GenerateConsoleCtrlEvent(1,0)",   # 1=CTRL_BREAK_EVENT, 0=该控制台全部
             str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=break_timeout, check=False,
        )
        proc.wait(timeout=wait_timeout)
        return True
    except (subprocess.TimeoutExpired, OSError):
        log.warning("[后端] 优雅关停超时/失败, 回退强杀")
        return False


def _check_dist_fresh() -> None:
    """功能: 静态托管模式下校验前端构建产物存在且不比源码旧.

    缺产物 fail-fast (要 npm run build); 产物比源码旧只 WARN —— 它能跑, 只是内容陈旧,
    挡住"我改了前端怎么没生效"这类误判。
    """
    index = _WEB_DIR / "dist" / "index.html"
    if not index.is_file():
        log.error("未找到前端构建产物: %s", index)
        log.error('请先构建: cd "%s" && npm run build   (或加 --dev-frontend 用 vite 开发服务器)', _WEB_DIR)
        sys.exit(1)
    src = _WEB_DIR / "src"
    if not src.is_dir():
        return
    newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0.0)
    if newest > index.stat().st_mtime:
        log.warning("前端产物比 src/ 旧, 页面可能不是最新代码 — 需要的话跑: cd \"%s\" && npm run build",
                    _WEB_DIR)


def _tcp_reachable(host: str, port: int, timeout: float = _PLC_PROBE_TIMEOUT) -> bool:
    """功能: 裸 TCP 建连探测, 判目标此刻是否可达.

    参数:
        host/port: 目标; timeout: 建连超时 (秒)
    返回:
        bool, 能在 timeout 内建立连接为 True
    说明:
        与 _port_open 的区别: 那个只探本机 localhost 端口 (判子进程就绪), 这个探
        远端设备. 本机开着 Mihomo TUN 时"连不上"不足以断言主机不存在 (关闭的端口
        也表现为超时), 但"连得上"是可信的 —— 现场反证做过: 同网段不存在的主机
        (192.168.0.199) 与 PLC 上不存在的端口 (:9999) 均超时, 说明 TUN 没有代
        接管 192.168.0.0/24, 连通结论不是假的.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _local_ipv4_ifaces() -> list[dict]:
    """功能: 列出本机 IPv4 地址及其所在网卡的链路状态, 供链路归因用.

    返回:
        list[dict], 每项 {"ip": str, "prefix": int, "index": int, "up": bool};
        取不到返回空表 (归因随之退化, 绝不抛)
    说明:
        地址与网卡两张表**按 InterfaceIndex (整数) 关联**, 不碰网卡名 —— 中文名
        经 subprocess 取回必乱码: text=True + errors="ignore" 得到 "浠ュお缃 2"
        (以太网 2), 而 encoding="oem" 在本机直接抛 UnicodeDecodeError. 同理
        Status 也不取原文而在 PowerShell 侧折成布尔 (`-eq 'Up'`), 免受本地化影响.
    """
    script = (
        "$a = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        "Select-Object IPAddress,PrefixLength,InterfaceIndex; "
        "$b = Get-NetAdapter -ErrorAction SilentlyContinue | "
        "ForEach-Object { [pscustomobject]@{ Index = $_.ifIndex; Up = ($_.Status -eq 'Up') } }; "
        "[pscustomobject]@{ Addrs = @($a); Adapters = @($b) } | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="ignore",
            timeout=_ROUTE_HINT_TIMEOUT, check=False,
        )
        parsed = json.loads((result.stdout or "").strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if not isinstance(parsed, dict):
        return []

    def _as_list(value) -> list:
        # ConvertTo-Json 对单元素集合出 dict 而非 list (5.1 无 -AsArray), 两种形状都吃
        if isinstance(value, list):
            return value
        return [value] if isinstance(value, dict) else []

    up_by_index = {}
    for adapter in _as_list(parsed.get("Adapters")):
        try:
            up_by_index[int(adapter.get("Index"))] = bool(adapter.get("Up"))
        except (TypeError, ValueError):
            continue
    ifaces = []
    for addr in _as_list(parsed.get("Addrs")):
        try:
            index = int(addr.get("InterfaceIndex"))
            ifaces.append({
                "ip": str(addr.get("IPAddress") or "").strip(),
                "prefix": int(addr.get("PrefixLength")),
                "index": index,
                "up": up_by_index.get(index, False),
            })
        except (TypeError, ValueError):
            continue
    return ifaces


def _plc_route_hint(host: str) -> str:
    """功能: PLC 探测失败后, 把失败归因成可执行的一句话.

    参数:
        host: PLC 主机 (IP 或名字)
    返回:
        str, 人类可读的排查方向; 归因手段本身不可用时退化成通用一句
    说明:
        判据 = "PLC 网段那块网卡此刻是不是 Up" —— 直接证据, 三分支互斥:
        本机压根没有该网段的地址 / 有但网卡掉链路 / 网卡正常但 PLC 不应答.

        ⚠ 不要改用 Find-NetRoute 的 NextHop 判链路 (实机验收否掉过):
        它的选路是**看 ARP 的**, 不只看路由表. 实测网口 Up 时,
        192.168.0.50 (PLC 在线, 有 ARP 应答) 判 on-link, 而同网段的
        192.168.0.199 (无人应答) 同样返回 NextHop=10.37.2.254 + 0.0.0.0/0 ——
        与"网口掉链路"完全同一个签名, 分不开"线断了"和"PLC 没开机"这两件事,
        而这恰恰是本函数要回答的问题.

        另: 别用 "UDP connect 后取 getsockname() 源 IP" 判链路 —— 实测它对
        192.168.0.50 返回 192.168.0.63 (该网口自己的地址), 与同期 Find-NetRoute
        的结论矛盾 (_lan_ips 已因 TUN fake-IP 否过这招一次, 这是第二个否决理由).
    """
    generic = "PLC 不可达 — 查 PLC 网口链路 (网线/USB 网卡)、PLC 电源、OPC UA 服务是否启动"
    try:
        plc_ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            plc_ip = ipaddress.ip_address(socket.gethostbyname(host))
        except (OSError, ValueError):
            return generic
    if plc_ip.is_loopback:
        # app.yaml 里 plc.url 可指向本机 Mock (opc.tcp://localhost:4840); 回环没有
        # 对应网卡, 走下面的网卡判定会误报"掉链路"
        return f"PLC 地址指向本机 ({plc_ip}) 但没人监听 — 本机 Mock 没起, 或该用真机地址"
    ifaces = _local_ipv4_ifaces()
    if not ifaces:
        return generic
    # PLC 网段上的本机地址 (可能不止一个, 取掩码最长的那个 = 最贴切的那张网卡)
    on_subnet = []
    for iface in ifaces:
        try:
            net = ipaddress.ip_network(f"{iface['ip']}/{iface['prefix']}", strict=False)
        except ValueError:
            continue
        if plc_ip in net:
            on_subnet.append(iface)
    if not on_subnet:
        return (f"本机没有任何网卡在 PLC 所在网段 ({plc_ip}) — "
                f"PLC 专用网口多半掉链路或未配地址, 查网线/USB 网卡/静态 IP 设置")
    best = max(on_subnet, key=lambda i: i["prefix"])
    if not best["up"]:
        return (f"PLC 网段的网卡 (本机地址 {best['ip']}) 未处于 Up — 掉链路了, "
                f"查网线两头/USB 网卡是否松动/交换机与 PLC 是否上电; "
                f"链路断时去 PLC 的包会退化走默认网关被静默丢弃, 所以表现为超时而非拒绝")
    return (f"PLC 网段的网卡正常 (本机地址 {best['ip']}, Up) 但 PLC 不应答 — "
            f"查 PLC 电源 / OPC UA 服务是否启动 / 连接数是否耗尽")


def _plc_link_probe(url: str) -> str | None:
    """功能: real 模式起后端前探一次 PLC 链路.

    参数:
        url: OPC UA 端点 (如 opc.tcp://192.168.0.50:4840)
    返回:
        None = 通; 否则返回一行不通的原因 (已含排查方向)
    说明:
        存在的理由: 后端 real 模式的 lifespan 里 driver.connect() 无容错, PLC 连不上
        就是 uvicorn "Application startup failed" + 退出码 3, 而 launcher 回打的日志
        末 40 行会被 asyncio traceback 占满, 驱动自己那句人话结论反而被挤掉. 与其让人
        读栈, 不如起之前先花 15ms 探一下.

        好路径实测 15ms, 无感; 归因 (_plc_route_hint, 实测约 2.7s —— Get-NetAdapter
        本身就慢) 只在探测失败时才付, 总计约 5s 拿到一句结论, 仍远优于现状的
        13s + 40 行 traceback.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return f"PLC 地址无法解析: {url!r} (查 config/app.yaml 的 plc.url)"
    port = parsed.port or _DEFAULT_OPCUA_PORT
    if _tcp_reachable(host, port):
        return None
    return f"{host}:{port} 连不上 — {_plc_route_hint(host)}"


def _preflight(*, dev_frontend: bool) -> None:
    """功能: 启动前的 fail-fast 预检, 不满足直接退出, 不做任何降级.

    参数:
        dev_frontend: True=起 vite 开发服务器 (需 npm/node_modules); False=后端同源托管 dist
    """
    if not (_WEB_DIR / "package.json").is_file():
        log.error("未找到前端工程: %s", _WEB_DIR / "package.json")
        sys.exit(1)
    if dev_frontend:
        # vite 开发服务器才需要运行期 npm 与依赖; 静态托管只吃 dist 产物
        if not (_WEB_DIR / "node_modules").is_dir():
            log.error("前端依赖未安装, 请先在 eit_ptlc/web 执行 npm install")
            sys.exit(1)
        if shutil.which("npm") is None:
            log.error("未在 PATH 中找到 npm, 请先安装 Node.js / npm")
            sys.exit(1)
    else:
        _check_dist_fresh()
    # 后端/PALLASBridge 依赖预检: 两者都用 sys.executable (= 本启动器解释器) 起, 故直接对当前解释器校验;
    # 缺失则 fail-fast 在主终端列出缺哪些 + 安装建议, 避免子进程在独立控制台窗 import 崩溃后一闪而过看不到
    missing = [pip_name for mod, pip_name in _PY_CHILD_DEPS.items()
               if importlib.util.find_spec(mod) is None]
    if missing:
        log.error("后端/Bridge 依赖缺失, 当前解释器无法运行子进程: %s", sys.executable)
        log.error("缺失: %s", ", ".join(missing))
        log.error('uv 环境请执行: uv sync --project "%s"', _REPO_ROOT)
        log.error('非 uv 环境请执行: %s -m pip install -e "%s"', sys.executable, _REPO_ROOT)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 子进程日志 (控制台窗 + 文件双写; 崩溃时把尾巴带回本终端)
# ---------------------------------------------------------------------------

def _log_path(name: str) -> Path | None:
    """功能: 取某子进程的日志文件路径.

    参数:
        name: 进程登记名 (MQTT / PALLASBridge / 后端 / 前端)
    返回:
        Path; 该进程未接入 tee (如前端) 返回 None
    """
    stem = _LOG_STEMS.get(name)
    return None if stem is None else _LOG_DIR / f"{stem}.log"


def _logged(name: str, cmd: list[str]) -> list[str]:
    """功能: 把子进程命令包一层 tee 运行器, 使其输出在控制台窗滚动的同时落盘.

    参数:
        name: 进程登记名 (决定日志文件名)
        cmd: 原命令
    返回:
        list[str], 包装后的命令; 该进程未接入 tee 时原样返回
    说明:
        tee 层的信号/编码/退出码约束见 tools/run_logged.py 模块头 —— 它忽略 CTRL_BREAK
        以便把后端 lifespan 收尾日志写完, 并原样透传子命令退出码 (故 launcher 报的
        "退出码=3" 仍是 uvicorn 的真码).
    """
    path = _log_path(name)
    if path is None:
        return cmd
    return [sys.executable, "-m", "eit_ptlc.tools.run_logged",
            "--log", str(path), "--", *cmd]


def _print_child_log_tail(name: str, lines: int = _LOG_TAIL_LINES) -> None:
    """功能: 把某子进程日志的末尾若干行打到 launcher 终端 (崩溃现场回收).

    参数:
        name: 进程登记名
        lines: 回打行数
    说明:
        只在异常路径调用 —— 正常运行时日志留在各自窗口, 本终端保持干净.
    """
    path = _log_path(name)
    if path is None:
        return
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("[%s] 日志读取失败 (%s): %s", name, path, exc)
        return
    tail = content.splitlines()[-lines:]
    if not tail:
        log.warning("[%s] 日志为空 (%s): 子进程未来得及输出即退出", name, path)
        return
    print(f"\n---- [{name}] 日志末 {len(tail)} 行 ({path}) ----")
    for line in tail:
        print(line)
    print(f"---- [{name}] 日志结束 (完整日志见上述路径; 上一次运行为 *.prev.log) ----\n")


# ---------------------------------------------------------------------------
# 子进程启动 (各在独立的原生控制台窗口运行)
# ---------------------------------------------------------------------------

def _start_backend(*, real: bool = False) -> subprocess.Popen:
    """功能: 在新控制台窗口中启动后端 uvicorn 子进程.

    参数:
        real: True=连接真机 PLC + Dobot (EIT_MODE=real), False=sim 模式.
    返回:
        subprocess.Popen
    """
    cmd = [sys.executable, "-m", "uvicorn", _BACKEND_APP,
           "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)]
    env = os.environ.copy()
    env["EIT_MODE"] = "real" if real else "sim"
    return subprocess.Popen(
        _logged("后端", cmd),
        cwd=str(_REPO_ROOT),
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _start_mqtt_broker() -> subprocess.Popen:
    """功能: 在新控制台窗口中启动内置 MQTT broker (液位数据/状态/命令中转, 纯标准库零依赖)."""
    cmd = [sys.executable, "-m", "eit_ptlc.tools.mqtt_broker",
           "--host", "0.0.0.0", "--port", str(MQTT_BROKER_PORT)]
    return subprocess.Popen(
        _logged("MQTT", cmd),
        cwd=str(_REPO_ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _start_pallas_bridge() -> subprocess.Popen:
    """功能: 在新控制台窗口中启动 PALLASVision 伴随 Bridge."""
    cmd = [
        sys.executable,
        "-m",
        "eit_ptlc.tools.pallas_bridge",
        "--config",
        str(Path("eit_ptlc") / "config" / "app.yaml"),
    ]
    return subprocess.Popen(
        _logged("PALLASBridge", cmd),
        cwd=str(_REPO_ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _start_frontend() -> subprocess.Popen:
    """功能: 在新控制台窗口中启动 Vite 前端开发服务器子进程.

    返回:
        subprocess.Popen
    """
    # shell=True 原因: npm/vite 是 Windows .cmd, 必须经 cmd.exe 解析
    return subprocess.Popen(
        "npm run dev",
        cwd=str(_WEB_DIR),
        shell=True,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


# ---------------------------------------------------------------------------
# 启动 / 停止编排
# ---------------------------------------------------------------------------

def _start_all(
    procs: dict[str, subprocess.Popen],
    open_browser: bool,
    *,
    real: bool = False,
    dev_frontend: bool = False,
    skip_link_check: bool = False,
) -> None:
    """功能: 释放端口残留 -> 启动 Bridge/前后端 -> 等待就绪 -> 可选开浏览器.

    参数:
        procs: 名称 → 子进程 的登记表
        open_browser: 就绪后是否自动打开浏览器
        real: True=连接真机 PLC + Dobot, False=sim 模式
        dev_frontend: True=另起 vite 开发服务器窗口 (HMR); False=后端同源托管 web/dist
        skip_link_check: True=跳过 real 模式的 PLC 链路预检 (明知不通也要起)
    """
    # 启动前清理端口 (前端口仅在真起 vite 时才需要清)
    ports = [MQTT_BROKER_PORT, PALLAS_BRIDGE_PORT, PALLAS_CALLBACK_PORT, BACKEND_PORT, OPCUA_PORT]
    if dev_frontend:
        ports.append(FRONTEND_PORT)
    for port in ports:
        _free_port(port)

    mode_label = "real" if real else "sim"
    # 启动内置 MQTT broker (最先起: 后端液位客户端 + 香橙派抓帧脚本均连它)
    log.info("启动 MQTT broker :%d ...", MQTT_BROKER_PORT)
    procs["MQTT"] = _start_mqtt_broker()
    try:
        ready = _wait_ready([("MQTT", procs["MQTT"], MQTT_BROKER_PORT)], _READY_TIMEOUT)
    except RuntimeError as exc:
        log.error("MQTT broker 启动失败: %s", exc)
        _print_child_log_tail("MQTT")
        _stop_all(procs)
        return
    if not ready:
        log.error("MQTT broker 未在 %.0fs 内就绪", _READY_TIMEOUT)
        _print_child_log_tail("MQTT")
        _stop_all(procs)
        return

    # 启动 PALLASBridge: 不要求 PALLAS 在线, 但本机 HTTP/回传监听必须就绪
    log.info("启动 PALLASBridge :%d ...", PALLAS_BRIDGE_PORT)
    procs["PALLASBridge"] = _start_pallas_bridge()
    try:
        ready = _wait_ready([("PALLASBridge", procs["PALLASBridge"], PALLAS_BRIDGE_PORT)], _READY_TIMEOUT)
    except RuntimeError as exc:
        log.error("PALLASBridge 启动失败: %s", exc)
        _print_child_log_tail("PALLASBridge")
        _stop_all(procs)
        return
    if not ready:
        log.error("PALLASBridge 未在 %.0fs 内就绪", _READY_TIMEOUT)
        _print_child_log_tail("PALLASBridge")
        _stop_all(procs)
        return

    # PLC 链路预检 (仅 real): 后端 lifespan 里 driver.connect() 无容错, 连不上就是
    # 退出码 3 + 满屏 asyncio traceback. 放在这里而不是 _preflight —— 后者在 main()
    # 里只跑一次, 而菜单 [1]/[2] 会重复调本函数, 链路是会抖的, 每次启动都该重探.
    if real and not skip_link_check:
        reason = _plc_link_probe(_config_plc_url())
        if reason is not None:
            log.error("PLC 链路预检未通过: %s", reason)
            # 机器人与 PLC 同网段同网口, 探它只为区分故障面, 不作为闸门
            robot_host, robot_port = _ROBOT_PROBE_HOSTPORT
            if _tcp_reachable(robot_host, robot_port):
                log.error("参考: 机器人 %s:%d 可达 —— 网口通, 问题更可能在 PLC 侧",
                          robot_host, robot_port)
            else:
                log.error("参考: 机器人 %s:%d 同样不可达 —— 整个网口/线路的问题, 不是 PLC 单点",
                          robot_host, robot_port)
            log.error("要绕过预检照旧启动加 --skip-link-check; 只想起 UI 就去掉 --real 走 sim 模式")
            log.error("修好后在下方菜单选 [1] 重试即可, 不必重开本启动器")
            _stop_all(procs)
            return

    # 启动后端
    log.info("启动后端 (uvicorn %s) :%d ...", mode_label, BACKEND_PORT)
    procs["后端"] = _start_backend(real=real)

    # 启动前端: 默认由后端同源托管 web/dist, 只有 --dev-frontend 才另起 vite 窗口
    targets = [("后端", procs["后端"], BACKEND_PORT)]
    if dev_frontend:
        log.info("启动前端 (vite dev) :%d ...", FRONTEND_PORT)
        procs["前端"] = _start_frontend()
        targets.append(("前端", procs["前端"], FRONTEND_PORT))
    ui_port = FRONTEND_PORT if dev_frontend else BACKEND_PORT

    # 等待就绪
    try:
        ready = _wait_ready(targets, _READY_TIMEOUT)
    except _ChildExited as exc:
        log.error("启动失败: %s", exc)
        _print_child_log_tail(exc.name)
        _stop_all(procs)
        return

    if ready:
        if dev_frontend:
            log.info("✓ Bridge/前后端均已就绪 — Bridge :%d | 后端 :%d | 前端 :%d",
                     PALLAS_BRIDGE_PORT, BACKEND_PORT, FRONTEND_PORT)
        else:
            log.info("✓ Bridge/后端均已就绪 — Bridge :%d | 后端(含前端静态站) :%d",
                     PALLAS_BRIDGE_PORT, BACKEND_PORT)
        if BACKEND_HOST != "127.0.0.1":
            # 绑 0.0.0.0 = 全部网卡都在听, 多网卡逐个列出; 绑具体 IP 则只有它可达
            ips = _lan_ips() if BACKEND_HOST == "0.0.0.0" else [BACKEND_HOST]
            if ips:
                urls = " 或 ".join(f"http://{ip}:{BACKEND_PORT}/" for ip in ips)
                log.info("局域网访问: %s (访问者选与本机同网段的; 打不开先查 Windows "
                         "防火墙对 python.exe / TCP %d 的入站放行)", urls, BACKEND_PORT)
        if open_browser:
            # 本机优先回环: 绑 0.0.0.0 也监听 127.0.0.1; 仅当绑定具体网卡 IP (回环不可达)
            # 且 UI 由后端托管时才开该 IP (--dev-frontend 的 vite 恒在 127.0.0.1)
            if BACKEND_HOST in ("0.0.0.0", "127.0.0.1") or dev_frontend:
                url = f"http://localhost:{ui_port}/"
            else:
                url = f"http://{BACKEND_HOST}:{ui_port}/"
            log.info("打开浏览器: %s", url)
            webbrowser.open(url)
    else:
        log.warning(
            "未在 %.0fs 内全部就绪 (可手动访问 http://localhost:%d/)",
            _READY_TIMEOUT, ui_port,
        )
        # "起了但不就绪"比崩溃更难猜, 同样把没起来的那个的日志尾巴带出来
        for name, _proc, port in targets:
            if not _port_open(port):
                _print_child_log_tail(name)


def _stop_all(procs: dict[str, subprocess.Popen]) -> None:
    """功能: 终止已登记的全部子进程树并清空登记表 (幂等).

    后端优先优雅关停 (跑 lifespan 收尾 + 在飞拍照 finally 释放相机/关 UV), 超时/失败
    再强杀兜底; PALLASBridge / 前端无关键收尾, 直接强杀。

    参数:
        procs: 名称 → 子进程 的登记表
    """
    if not procs:
        return
    for name, proc in list(procs.items()):
        if name == "后端":
            if _graceful_stop_backend(proc):
                log.info("[后端] 已优雅退出 (lifespan 收尾完成)")
                continue
            log.warning("[后端] 优雅退出未完成, 强制终止")
        _terminate_tree(name, proc)
    procs.clear()
    log.info("已停止 Bridge/前后端")


def _print_menu(procs: dict[str, subprocess.Popen]) -> None:
    """功能: 打印当前运行状态与操作菜单."""
    status = ("运行中: " + ", ".join(procs)) if procs else "已停止"
    print(
        "\n============================\n"
        " pTLC 上位机 launcher\n"
        f" 状态: {status}\n"
        "----------------------------\n"
        "  [1] 启动\n"
        "  [2] 重启\n"
        "  [3] 停止\n"
        "  [4] 退出\n"
        "============================"
    )


def parse_args() -> argparse.Namespace:
    """功能: 解析命令行参数."""
    parser = argparse.ArgumentParser(
        description="pTLC 上位机前端启动入口 (开发编排, 多进程 + 分控台窗 + 交互菜单)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="就绪后不自动打开浏览器 (默认打开)",
    )
    parser.add_argument(
        "--real", action="store_true",
        help="连接真机 PLC (OPC UA) + 真机机器人 (Dobot TCP); 默认 sim 模式",
    )
    parser.add_argument(
        "--dev-frontend", action="store_true",
        help="另起 vite 开发服务器窗口 (:15173, 带 HMR, 改前端源码即时生效); "
             "默认由后端同源托管 web/dist 构建产物, 不开这个窗口",
    )
    parser.add_argument(
        "--skip-link-check", action="store_true",
        help="跳过 --real 起后端前的 PLC 链路预检 (明知不通也要起, 让后端自己去撞超时)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    """功能: 预检 → 自动启动一次 → 进入交互菜单 (启动/重启/停止/退出) → 退出时统一清理."""
    args = parse_args()
    _preflight(dev_frontend=args.dev_frontend)

    procs: dict[str, subprocess.Popen] = {}

    def _start() -> None:
        """按当前命令行参数启动整套 (菜单的 [1]/[2] 与首次启动共用, 免参数漏传)."""
        _start_all(procs, open_browser=not args.no_browser,
                   real=args.real, dev_frontend=args.dev_frontend,
                   skip_link_check=args.skip_link_check)

    try:
        # 首次自动启动
        _start()

        while True:
            # 崩溃检测: 已死的子进程提示并移除登记
            for name, proc in list(procs.items()):
                code = proc.poll()
                if code is not None:
                    log.warning("[%s] 进程已退出 (退出码=%s)", name, code)
                    _print_child_log_tail(name)   # 跑着跑着崩的场景与启动崩同样瞎
                    procs.pop(name, None)

            running = bool(procs)

            _print_menu(procs)
            try:
                choice = input("选择> ").strip()
            except EOFError:
                choice = "4"

            if choice == "1":
                if running:
                    log.info("Bridge/前后端已在运行, 如需重来请选 [2] 重启")
                else:
                    _start()
            elif choice == "2":
                _stop_all(procs)
                _start()
            elif choice == "3":
                _stop_all(procs)
            elif choice == "4":
                break
            else:
                log.info("无效选择: %s (请输入 1-4)", choice or "<空>")
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C, 正在退出 ...")
    finally:
        _stop_all(procs)
        log.info("已退出")


if __name__ == "__main__":
    main()
