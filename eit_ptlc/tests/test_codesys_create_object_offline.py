"""钉死 create/caps 两个 op 在三个进程里的定义一致(离线; 不起 InoProShop)。

存在理由:
    worker_body.py / server.mjs / driver/codesys_ipc.py 各自维护一份 op 集合(写锁 EXCLUSIVE、
    部署守卫 BLOCKED), 是跨语言镜像 —— 漏改任一处不会报错, 只会静默丢掉一层保护:
    create 不进 EXCLUSIVE 就不取写锁(两个客户端并发建对象), 不进 BLOCKED 就能在部署事务
    窗口内改工程。三处都是纯文本/常量, 故本测试用读文件的方式对账, 无需真机。
    与 test_codesys_generate_code_offline.py 的同名守卫同形。
"""

from pathlib import Path

from eit_ptlc.driver.codesys_ipc import _DEPLOY_GUARD_BLOCKED_OPS, _EXCLUSIVE_OPS

_ROOT = Path(__file__).resolve().parent.parent
_WORKER_BODY = _ROOT / "tools" / "codesys-mcp" / "worker_body.py"
_MCP_SERVER = _ROOT / "tools" / "codesys-mcp" / "server.mjs"


def test_create_is_exclusive_and_guard_blocked_in_python_client() -> None:
    assert "create" in _EXCLUSIVE_OPS
    assert "create" in _DEPLOY_GUARD_BLOCKED_OPS


def test_worker_registers_create_and_caps_ops() -> None:
    body = _WORKER_BODY.read_text(encoding="utf-8")
    assert '"create": op_create,' in body
    assert '"caps": op_caps,' in body
    # create 改工程 -> 必须被部署守卫挡住; caps 只读 -> 必须不在守卫集合里, 否则部署期连
    # 探针都用不了(诊断能力被自己的安全门锁死)
    blocked = next(
        line for line in body.splitlines() if line.startswith("DEPLOY_GUARD_BLOCKED_OPS")
    )
    blocked_block = body.split("DEPLOY_GUARD_BLOCKED_OPS", 1)[1].split("))", 1)[0]
    assert '"create"' in blocked_block, blocked
    assert '"caps"' not in blocked_block


def test_mcp_server_exposes_create_and_caps_tools() -> None:
    server = _MCP_SERVER.read_text(encoding="utf-8")

    exclusive_line = next(l for l in server.splitlines() if "const EXCLUSIVE_OPS" in l)
    assert '"create"' in exclusive_line
    assert '"caps"' not in exclusive_line          # 只读 op 不取写锁

    guard_block = server.split("const DEPLOY_GUARD_BLOCKED_OPS", 1)[1].split("]", 1)[0]
    assert '"create"' in guard_block
    assert '"caps"' not in guard_block

    assert 'server.tool("codesys_create_object"' in server
    assert 'server.tool("codesys_caps"' in server
    assert 'call("create", {' in server
    assert 'call("caps", { path: a.path }' in server
