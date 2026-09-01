"""原子动作详细说明配置与定点保存 API 离线测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.controller.actions_service import ActionsService


_ACTIONS_DIR = Path(__file__).resolve().parents[1] / "config" / "actions"
_SECTIONS = ("执行步骤：", "前置与安全：", "完成与异常：")


def test_all_current_actions_have_structured_descriptions() -> None:
    registry = ActionRegistry.load(_ACTIONS_DIR)
    actions = registry.list()
    assert len(actions) == 93
    block_desc_count = sum(
        path.read_text(encoding="utf-8").count("  desc: |-")
        for path in _ACTIONS_DIR.rglob("*.yaml")
    )
    assert block_desc_count == len(actions)
    for action in actions:
        assert action.desc.strip(), action.name
        for section in _SECTIONS:
            assert section in action.desc, f"{action.name} 缺少 {section}"
        if action.kind == "plc_l2":
            assert "PLC核对：" in action.desc, f"{action.name} 缺少 PLC 真源核对依据"
            assert "20260702.project" in action.desc, f"{action.name} 未指向现役 PLC 工程"
        else:
            assert "实现核对：" in action.desc, f"{action.name} 缺少上位机实现核对依据"


def test_param_labels_are_not_truncated_by_flow_mapping_commas() -> None:
    """params 是 YAML 流式映射 {..}, 值文本里的裸逗号是键分隔符, 会把 label 拦腰截断。

    截断后 UI 显示残缺 (如「吸液速度 V (DT」), 余段还变成静默被忽略的野键。含逗号的
    label 必须加引号; 括号配对是这类截断最直接的检测信号。
    """
    for action in ActionRegistry.load(_ACTIONS_DIR).list():
        for param in getattr(action, "params", []) or []:
            label = param.label or ""
            assert label.count("(") == label.count(")"), (
                f"{action.name}.{param.name} 的 label 括号不配对: {label!r} "
                f"—— 多半是含逗号未加引号被流式映射截断"
            )


def test_slow_actions_raise_absolute_timeout_together_with_stall() -> None:
    """放大了 stall_timeout 的慢动作必须同时放大 action_timeout。

    两者语义不同: stall 是"无进度多久算卡"(每次 PLC 推进就复位), action_timeout 是
    绝对上限(不复位)。只提 stall 会留下"PLC 一直在推进、却在绝对上限处被判
    TIMEOUT 结果不明确"的坑 —— sampling.spot_band_layer 就踩过: stall 从 60 提到 600,
    action_timeout 仍走全局 600, 而单条带蛇形分程点样实测已达 420~440s。
    """
    global_ceiling = 600.0   # app.yaml plc.action_timeout
    for action in ActionRegistry.load(_ACTIONS_DIR).list():
        stall = getattr(action, "stall_timeout", None)
        if stall is None or stall < global_ceiling:
            continue
        absolute = getattr(action, "action_timeout", None)
        assert absolute is not None, (
            f"{action.name} 把 stall_timeout 提到 {stall}s 却未覆盖 action_timeout, "
            f"绝对上限仍是全局 {global_ceiling}s"
        )
        assert absolute > stall, (
            f"{action.name} 的绝对上限 {absolute}s 不大于停滞预算 {stall}s"
        )


def test_registry_rejects_missing_description(tmp_path: Path) -> None:
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "robot.yaml").write_text(
        "robot.query:\n"
        "  kind: robot\n"
        "  label: 查询\n"
        "  method: query\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="必须声明非空 desc"):
        ActionRegistry.load(actions_dir)


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    path = actions_dir / "robot.yaml"
    path.write_text(
        "# 文件头注释\n"
        "robot.query:\n"
        "  kind: robot\n"
        "  label: 查询\n"
        "  desc: |-\n"
        "    执行步骤：读取状态。\n"
        "    前置与安全：只读。\n"
        "    完成与异常：返回状态。\n"
        "  method: query\n"
        "\n"
        "# 相邻动作必须逐字保留\n"
        "robot.home:\n"
        "  kind: robot\n"
        "  label: 回原点\n"
        "  desc: |-\n"
        "    执行步骤：回原点。\n"
        "    前置与安全：确认安全。\n"
        "    完成与异常：到位或报错。\n"
        "  method: home\n",
        encoding="utf-8",
    )
    registry = ActionRegistry.load(actions_dir)
    app = create_app(registry)

    def on_reload(new_registry: ActionRegistry) -> None:
        app.state.registry = new_registry

    app.state.actions = ActionsService(actions_dir, on_reload=on_reload)
    return TestClient(app), path


def test_description_api_surgically_updates_and_hot_reloads(tmp_path: Path) -> None:
    client, path = _client(tmp_path)
    before = path.read_text(encoding="utf-8")
    sibling = before[before.index("# 相邻动作必须逐字保留"):]
    desc = (
        "执行步骤：读取控制器状态；保留冒号：与 # 字符。\n"
        "前置与安全：只读，不发送运动命令。\n"
        "完成与异常：返回连接、使能及报警状态。"
    )

    response = client.put(
        "/api/actions/robot.query/description", json={"desc": desc})
    assert response.status_code == 200, response.text
    assert response.json()["desc"] == desc
    assert client.get("/api/actions/robot.query").json()["desc"] == desc

    after = path.read_text(encoding="utf-8")
    assert after.startswith("# 文件头注释\nrobot.query:\n")
    assert after[after.index("# 相邻动作必须逐字保留"):] == sibling
    assert "  desc: |-\n    执行步骤：" in after


def test_description_api_rejects_blank_unknown_and_wrong_type(tmp_path: Path) -> None:
    client, path = _client(tmp_path)
    before = path.read_text(encoding="utf-8")

    assert client.put(
        "/api/actions/robot.query/description", json={"desc": "   "},
    ).status_code == 400
    assert client.put(
        "/api/actions/nope/description", json={"desc": "有效说明"},
    ).status_code == 404
    assert client.put(
        "/api/actions/robot.query/description", json={"desc": 123},
    ).status_code == 422
    assert path.read_text(encoding="utf-8") == before
