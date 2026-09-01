#!/usr/bin/env python3
"""PALLASVision TCP string-trigger probe.

This script verifies whether the upper computer can trigger the PALLASVision
string trigger directly through TCP Server. It does not talk to PLC or robot
motion channels. The default project is ``机器人程序/vision1.prjb``.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PROJECT = Path(__file__).resolve().parents[2] / "机器人程序" / "vision1.prjb"


@dataclass(frozen=True)
class ProjectHint:
    host: str
    port: int
    server_name: str
    server_enabled: bool | None
    trigger: str
    trigger_program: str


def _read_zip_text(zip_file: zipfile.ZipFile, name: str) -> str:
    with zip_file.open(name) as fh:
        return fh.read().decode("utf-8-sig")


def load_project_hint(project: Path, *, server_name: str = "TCP服务器") -> ProjectHint:
    """Read TCP Server and string-trigger defaults from a PALLASVision .prjb."""
    with zipfile.ZipFile(project) as zf:
        tcp_servers = json.loads(_read_zip_text(zf, "TCPServer.json"))
        comm = json.loads(_read_zip_text(zf, "CommunicatorManager.json"))
        triggers = json.loads(_read_zip_text(zf, "GlobalTriggerManager.json"))

    by_name = {cfg.get("DeviceName", ""): (server_id, cfg) for server_id, cfg in tcp_servers.items()}
    if server_name in by_name:
        server_id, server_cfg = by_name[server_name]
    elif by_name:
        server_id, server_cfg = next(iter(by_name.values()))
        server_name = str(server_cfg.get("DeviceName") or server_name)
    else:
        raise ValueError(f"{project} 中没有 TCPServer.json 服务器配置")

    enabled: bool | None = None
    for dev in (comm.get("ComDevice") or {}).values():
        if str(dev.get("ID")) == str(server_id):
            enabled = bool(dev.get("ENABLE"))
            break

    string_triggers = triggers.get("StringTrigger") or []
    trigger_cfg = string_triggers[0] if string_triggers else {}
    trigger = str(trigger_cfg.get("strTriggerData") or "1")
    trigger_program = str(trigger_cfg.get("strConfigName") or "")

    return ProjectHint(
        host=str(server_cfg.get("IP") or "127.0.0.1"),
        port=int(server_cfg.get("Port") or 8887),
        server_name=server_name,
        server_enabled=enabled,
        trigger=trigger,
        trigger_program=trigger_program,
    )


def _terminator_bytes(name: str) -> bytes:
    return {
        "none": b"",
        "cr": b"\r",
        "lf": b"\n",
        "crlf": b"\r\n",
        "nul": b"\0",
    }[name]


def build_payload(args: argparse.Namespace, hint: ProjectHint | None) -> bytes:
    if args.hex_payload:
        text = args.hex_payload.replace(" ", "").replace(",", "")
        if len(text) % 2:
            raise ValueError("--hex-payload 长度必须为偶数")
        return bytes.fromhex(text)

    trigger = args.trigger
    if trigger is None:
        trigger = hint.trigger if hint is not None else "1"
    return trigger.encode(args.encoding) + _terminator_bytes(args.terminator)


def send_once(
    host: str,
    port: int,
    payload: bytes,
    *,
    connect_timeout: float,
    recv_timeout: float,
    read_bytes: int,
    shutdown_write: bool,
) -> bytes:
    with socket.create_connection((host, port), timeout=connect_timeout) as sock:
        sock.settimeout(recv_timeout)
        sock.sendall(payload)
        if shutdown_write:
            sock.shutdown(socket.SHUT_WR)
        if recv_timeout <= 0 or read_bytes <= 0:
            return b""
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(read_bytes)
            except TimeoutError:
                break
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if len(chunk) < read_bytes:
                break
        return b"".join(chunks)


def listen_once(
    host: str,
    port: int,
    *,
    timeout: float,
    read_bytes: int,
    accept_count: int,
    encoding: str,
    reply: bytes,
) -> int:
    """Listen for PALLASVision TCP client result pushes and print payloads."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        server.settimeout(timeout)
        print(f"[LISTEN] {host}:{port} 等待 PALLASVision TCP客户端连接...")
        accepted = 0
        while accepted < accept_count:
            try:
                conn, addr = server.accept()
            except TimeoutError:
                print("[LISTEN] 等待超时，未收到连接。")
                break
            except socket.timeout:
                print("[LISTEN] 等待超时，未收到连接。")
                break
            accepted += 1
            with conn:
                conn.settimeout(timeout)
                chunks: list[bytes] = []
                while True:
                    try:
                        chunk = conn.recv(read_bytes)
                    except TimeoutError:
                        break
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if len(chunk) < read_bytes:
                        break
                payload = b"".join(chunks)
                text = payload.decode(encoding, errors="replace")
                print(f"[ACCEPT] {addr[0]}:{addr[1]}")
                print(f"[DATA] {payload!r}  hex={payload.hex(' ')}  text={text!r}")
                if reply:
                    conn.sendall(reply)
                    print(f"[REPLY] {reply!r}  hex={reply.hex(' ')}")
    return accepted
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "通过 TCP Server 向 PALLASVision 发送字符串触发信号。"
            "默认从 机器人程序/vision1.prjb 读取 TCP 服务器与字符串触发配置。"
        )
    )
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="PALLASVision .prjb 工程路径")
    parser.add_argument("--server-name", default="TCP服务器", help="读取工程内哪个 TCP Server 配置")
    parser.add_argument("--show-project", action="store_true", help="打印从 .prjb 读取到的 TCP/触发配置")
    parser.add_argument("--host", help="PALLASVision TCP Server IP；缺省用工程内 TCP服务器")
    parser.add_argument("--port", type=int, help="PALLASVision TCP Server 端口；缺省用工程内 TCP服务器")
    parser.add_argument("--trigger", help="触发字符串；缺省用工程内 StringTrigger，当前通常为 1")
    parser.add_argument("--encoding", default="utf-8", help="触发字符串编码，默认 utf-8")
    parser.add_argument("--terminator", choices=["none", "cr", "lf", "crlf", "nul"], default="none",
                        help="字符串后的结束符；PALLAS 工程当前未启用结束符，默认 none")
    parser.add_argument("--hex-payload", help="直接发送十六进制字节，例如 31 或 310d0a")
    parser.add_argument("--connect-timeout", type=float, default=3.0, help="连接超时秒数")
    parser.add_argument("--recv-timeout", type=float, default=2.0,
                        help="读回包超时秒数；设 0 表示发送后不等待")
    parser.add_argument("--read-bytes", type=int, default=4096, help="单次读取的最大字节数")
    parser.add_argument("--repeat", type=int, default=1, help="重复发送次数")
    parser.add_argument("--delay", type=float, default=0.5, help="重复发送间隔秒数")
    parser.add_argument("--shutdown-write", action="store_true",
                        help="发送后关闭写半边；若 PALLAS 需要连接保持则不要启用")
    parser.add_argument("--dry-run", action="store_true", help="只打印将发送的内容，不建立 TCP 连接")
    parser.add_argument("--listen", action="store_true",
                        help="作为上位机本地 TCP Server 接收 PALLASVision 发送数据")
    parser.add_argument("--listen-host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=18887,
                        help="监听端口，建议与 PALLAS 触发端口 8887 分开")
    parser.add_argument("--listen-timeout", type=float, default=60.0, help="等待连接/数据超时秒数")
    parser.add_argument("--accept-count", type=int, default=1, help="接收多少次连接后退出")
    parser.add_argument("--reply", default="", help="收到数据后可选回包文本")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    hint: ProjectHint | None = None
    if args.project:
        try:
            hint = load_project_hint(args.project, server_name=args.server_name)
        except Exception as exc:
            if not args.host or not args.port or not args.trigger:
                parser.error(f"读取工程默认值失败: {exc}; 请显式传 --host --port --trigger")
            print(f"[WARN] 读取工程默认值失败: {exc}", file=sys.stderr)

    if args.show_project and hint is not None:
        enabled = "未知" if hint.server_enabled is None else ("已启用" if hint.server_enabled else "未启用")
        print(f"[PROJECT] {args.project}")
        print(f"[TCP] {hint.server_name}: {hint.host}:{hint.port} ({enabled})")
        print(f"[TRIGGER] 字符串 {hint.trigger!r} -> 程序 {hint.trigger_program or '未知'}")
        if hint.server_enabled is False:
            print("[WARN] 工程保存状态显示 TCP Server 未启用；请在 PALLASVision 通信设备管理中勾选使能。")

    if args.listen:
        reply = args.reply.encode(args.encoding) if args.reply else b""
        accepted = listen_once(
            args.listen_host,
            args.listen_port,
            timeout=args.listen_timeout,
            read_bytes=args.read_bytes,
            accept_count=max(1, args.accept_count),
            encoding=args.encoding,
            reply=reply,
        )
        return 0 if accepted else 2

    host = args.host or (hint.host if hint is not None else "127.0.0.1")
    port = args.port or (hint.port if hint is not None else 8887)
    try:
        payload = build_payload(args, hint)
    except Exception as exc:
        parser.error(str(exc))

    print(f"[TARGET] {host}:{port}")
    print(f"[SEND] {payload!r}  hex={payload.hex(' ')}")

    if args.dry_run:
        print("[DRY-RUN] 未建立连接。")
        return 0

    ok = True
    for idx in range(max(1, args.repeat)):
        if args.repeat > 1:
            print(f"[TRY] {idx + 1}/{args.repeat}")
        try:
            reply = send_once(
                host,
                port,
                payload,
                connect_timeout=args.connect_timeout,
                recv_timeout=args.recv_timeout,
                read_bytes=args.read_bytes,
                shutdown_write=args.shutdown_write,
            )
        except OSError as exc:
            ok = False
            print(f"[ERROR] TCP 发送失败: {exc}", file=sys.stderr)
        else:
            if reply:
                text = reply.decode(args.encoding, errors="replace")
                print(f"[RECV] {reply!r}  hex={reply.hex(' ')}  text={text!r}")
            else:
                print("[RECV] 无回包或等待超时；若 PALLASVision 程序被触发，这不一定是失败。")
        if idx + 1 < args.repeat:
            time.sleep(max(0.0, args.delay))

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
