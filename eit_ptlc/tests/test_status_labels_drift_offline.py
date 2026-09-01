"""设备状态枚举的漂移看门狗 (Python 侧)
=======================================
功能:
    断言 web/tests/three-d/plcStatusLabels.contract.json 这份金样, 与 Python 里的
    数值真源逐条一致。前端 stationStatus.js 是这些数值的副本, 由 node 侧的
    stationStatus.test.js 对着**同一份金样**断言 —— 两道绊线夹住一份金样,
    谁先动谁先红, 而 Python 不必去解析 JS。

    覆盖:
      RobotMode                (driver/dobot_tcp_driver.py)
      PLCActionState           (controller/plc_controller.py)
      PLCActionSafeState       (同上)
      last_action=N 的赋值点   (driver/dobot_tcp_driver.py, 正则扫源码)

    改了 Python 枚举 -> 本测试红 -> 更新金样 -> node 侧接着红 -> 补前端中文。
    顺序是有意的: 先承认数值变了, 再决定中文怎么写。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from eit_ptlc.controller.plc_controller import PLCActionSafeState, PLCActionState
from eit_ptlc.driver.dobot_tcp_driver import RobotMode

_ROOT = Path(__file__).resolve().parent.parent
_CONTRACT = _ROOT / "web" / "tests" / "three-d" / "plcStatusLabels.contract.json"
_DRIVER = _ROOT / "driver" / "dobot_tcp_driver.py"

_HINT = "更新 web/tests/three-d/plcStatusLabels.contract.json 与 stationStatus.js"


def _contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _from_int_enum(enum_cls) -> dict:
    return {str(int(member)): member.name for member in enum_cls}


def test_robot_mode_matches_driver():
    """RobotMode 是普通类而非 IntEnum, 取其大写整型类属性."""
    expected = {
        str(value): name
        for name, value in vars(RobotMode).items()
        if not name.startswith("_") and isinstance(value, int)
    }
    assert _contract()["robotMode"] == expected, f"RobotMode 变了 —— {_HINT}"


def test_l2_state_matches_controller():
    assert _contract()["l2State"] == _from_int_enum(PLCActionState), f"PLCActionState 变了 —— {_HINT}"


def test_l2_safe_state_matches_controller():
    assert _contract()["l2SafeState"] == _from_int_enum(PLCActionSafeState), (
        f"PLCActionSafeState 变了 —— {_HINT}")


def test_last_action_codes_match_driver_source():
    """last_action 没有枚举类, 数值散在赋值点上; 正则扫出来当真源.

    形如 `last_action=24` 与 `last_action = 29` 两种写法都要覆盖。
    """
    source = _DRIVER.read_text(encoding="utf-8")
    found = sorted({int(m) for m in re.findall(r"last_action\s*=\s*(\d+)", source)})
    # 三元写法 `last_action=25 if ... else 27` 只会被扫到第一个数, 补扫 else 分支
    found = sorted(set(found) | {
        int(m) for m in re.findall(r"last_action\s*=\s*\d+\s+if\s+.+?\s+else\s+(\d+)", source)
    })
    assert _contract()["robotLastAction"] == found, f"last_action 赋值点变了 —— {_HINT}"


def test_contract_declares_its_python_truth():
    """金样里必须写清每张表的真源路径 —— 下一个人才知道去哪改."""
    truth = _contract()["_python_truth"]
    for key in ("robotMode", "l2State", "l2SafeState", "robotLastAction"):
        assert truth.get(key), f"金样缺 {key} 的真源声明"
