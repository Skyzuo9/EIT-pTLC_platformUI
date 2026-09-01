"""PLC 编排说明书漂移检查 (在线层)
==================================
功能:
    经文件 IPC 向常驻 InoProShop worker 拉取现役工程的 POU 源码, 重算 ST 哈希,
    与 mock/behavior/specs/*.yaml 里记录的锚点逐条比对。有任一 DRIFT 即退出码非零。

    这是漂移看门狗的**在线层**: 离线层 (tests/test_plc_spec_offline.py) 只能抓仓库内
    三方漂移, 抓不到"有人在 CODESYS 里改了 ST 而没更新 spec"—— 那正是本工具的职责。
    虚拟 PLC 的行为一旦与真机 PLC 分叉, 沙盒就开始骗人, 所以每次改 PLC 后应跑一次。

    只发 read 类操作 (worker 侧是共享锁), 不 acquire 会话独占, 不写工程。
    ⚠ 但它会**懒启动 InoProShop** 并占用该工程的单开名额 —— 与下装/人工开工程互斥,
    跑之前确认没人正在用 CODESYS。

用法:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.plc_spec_drift
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.plc_spec_drift --station FeedLift
退出码:
    0 = 全部锚点一致; 1 = 存在漂移或读取失败
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

from eit_ptlc.mock.behavior.spec_loader import load_all_specs, st_sha256

log = logging.getLogger(__name__)

# 与 .mcp.json / app.yaml codesys.ipc_dir 同值 (三处必须一致, 改一处要改三处)
_IPC_DIR = Path(__file__).resolve().parent.parent / "var" / "codesys-ipc-20260702"


def ipc_call(op: str, args: dict, *, ipc_dir: Path, timeout: float = 60.0) -> dict:
    """发一次文件 IPC 请求并等响应.

    参数:
        op: worker 操作名 (本工具只用 read); args: 操作参数
        ipc_dir: IPC 目录; timeout: 等待响应的最长秒数
    返回:
        Dict, worker 的响应体 {"ok": bool, "result"|"error": ...}
    Raises:
        TimeoutError: 超时未见响应文件 (worker 未启动或已崩)
    """
    request_id = uuid.uuid4().hex[:12]
    request_path = ipc_dir / "requests" / f"{request_id}.req.json"
    response_path = ipc_dir / "responses" / f"{request_id}.resp.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps({"op": op, "args": args}, ensure_ascii=False),
                            encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if response_path.exists():
            try:
                body = json.loads(response_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # 响应文件可能正在写: 退让一拍重读
                time.sleep(0.1)
                continue
            response_path.unlink(missing_ok=True)
            return body
        time.sleep(0.1)
    raise TimeoutError(f"IPC 超时: op={op} args={args}")


def check_station(spec, *, ipc_dir: Path) -> list:
    """比对一个工位的全部锚点; 返回逐条结果行."""
    rows = []
    for pou, expected in sorted(spec.anchors().items()):
        try:
            body = ipc_call("read", {"path": pou}, ipc_dir=ipc_dir)
        except TimeoutError as exc:
            rows.append({"pou": pou, "state": "ERROR", "detail": str(exc)})
            continue
        if not body.get("ok"):
            rows.append({"pou": pou, "state": "ERROR", "detail": str(body.get("error"))})
            continue
        result = body["result"]
        actual = st_sha256(result.get("declaration") or "", result.get("implementation") or "")
        if actual == expected:
            rows.append({"pou": pou, "state": "OK", "detail": ""})
        else:
            rows.append({"pou": pou, "state": "DRIFT",
                         "detail": f"spec={expected[:12]}… 现役={actual[:12]}…"})
    return rows


def main(argv: list | None = None) -> int:
    """命令行入口; 返回进程退出码."""
    parser = argparse.ArgumentParser(description="PLC 编排说明书漂移检查 (在线层)")
    parser.add_argument("--station", default="", help="只查某工位 (缺省查全部)")
    parser.add_argument("--ipc-dir", default=str(_IPC_DIR), help="文件 IPC 目录")
    parser.add_argument("--timeout", type=float, default=60.0, help="单次 IPC 超时秒数")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ipc_dir = Path(args.ipc_dir)
    if not ipc_dir.exists():
        log.error("IPC 目录不存在: %s (worker 从未启动过?)", ipc_dir)
        return 1

    specs = load_all_specs()
    if args.station:
        if args.station not in specs:
            log.error("未知工位 %s; 可选: %s", args.station, ", ".join(sorted(specs)))
            return 1
        specs = {args.station: specs[args.station]}

    drift = 0
    error = 0
    for station, spec in sorted(specs.items()):
        log.info("== %s (%s) ==", station, spec.codesys_project)
        for row in check_station(spec, ipc_dir=ipc_dir):
            log.info("  %-6s %-64s %s", row["state"], row["pou"], row["detail"])
            if row["state"] == "DRIFT":
                drift += 1
            elif row["state"] == "ERROR":
                error += 1

    if drift or error:
        log.error("\n漂移 %d 处, 读取失败 %d 处 —— spec 与现役工程已分叉, "
                  "沙盒行为不再可信; 请重新提取 ST 并更新 spec", drift, error)
        return 1
    log.info("\n全部锚点与现役工程一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
