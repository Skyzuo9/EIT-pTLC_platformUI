"""抓取锚点修正公式的两语言漂移锁。

公式有两份实现 —— 编译器 `clip_compiler.ClipBuilder._grab_corrected`(把修正烤进片段的
随爪变换与落位 dock)与前端 `MachineStateDriver.attach`(播放期磁吸)。两边必须逐字同式:
漂了不报错, 只表现为放件瞬间件从磁吸位硬弹回烤死的 dock 位 + "dock 与实际取料位姿
不同源"误告警(2026-08-06 实测 58.8mm)。

锁法: 与 web/tests/three-d/payloadDock.test.js 的 freeAxes 用例共用**同一组实测数字**
(中转B 取瓶: 全量偏移 (−18.19, −1.92, +55.91)mm, 放开长度轴后应修 (0, −1.92, +55.91))。
改任何一边的公式, 先改两份夹具再改实现。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three_d" / "pipeline"))


def _grab_corrected(record: dict, transform: "np.ndarray") -> "np.ndarray":
    from clip_compiler import ClipBuilder

    # _grab_corrected 是纯函数(只读 record/transform), 绕过 __init__ 的重资产装载
    return ClipBuilder._grab_corrected(object.__new__(ClipBuilder), record, transform)


def test_grab_corrected_matches_frontend_numbers():
    record = {
        "kind": "item",
        "grabLocal": [0.0, 0.089, 0.0],
        "mountLocal": {"position": [0.0, 0.0, -0.12], "freeAxes": [[1.0, 0.0, 0.0]]},
    }
    transform = np.eye(4)
    # 变换后特征点 = (0.01819, 0.00192, -0.17591) mount 系; 全量 shift = 锚点 − 特征
    # = (−18.19, −1.92, +55.91)mm; 放开长度轴 x 后应只修 (0, −1.92, +55.91)。
    transform[:3, 3] = [0.01819, 0.00192 - 0.089, -0.17591]

    corrected = _grab_corrected(record, transform)
    feature = corrected @ np.append(np.asarray(record["grabLocal"]), 1.0)
    assert abs(feature[0] - 0.01819) < 1e-12, "长度轴分量必须放手(咬哪段由示教定)"
    assert abs(feature[1] - 0.0) < 1e-12, "闭合轴分量应修到锚点"
    assert abs(feature[2] - (-0.12)) < 1e-12, "销轴分量应修到锚点"
    # 姿态与非平移部分不许动
    assert np.allclose(corrected[:3, :3], transform[:3, :3])


def test_grab_corrected_full_correction_without_free_axes():
    # freeAxes=[]/缺省 = 三轴全锚定(瓶居中, 2026-08-07 定案: 销笼对回转体是双水平轴
    # 定心特征)。与 payloadDock.test.js 的"freeAxes 为空表"用例同一组语义。
    record = {
        "kind": "item",
        "grabLocal": [0.0, 0.089, 0.0],
        "mountLocal": {"position": [0.0, 0.0, -0.12], "freeAxes": []},
    }
    transform = np.eye(4)
    transform[:3, 3] = [0.01819, 0.00192 - 0.089, -0.17591]
    corrected = _grab_corrected(record, transform)
    feature = corrected @ np.append(np.asarray(record["grabLocal"]), 1.0)
    assert np.allclose(feature[:3], [0.0, 0.0, -0.12], atol=1e-12), "三轴全部修到锚点"


def test_grab_corrected_passthrough_for_tray_and_missing_fields():
    transform = np.eye(4)
    transform[:3, 3] = [0.1, 0.2, 0.3]
    for record in (
        {"kind": "tray", "grabLocal": [0, 0, 0],
         "mountLocal": {"position": [0, 0, -0.12]}},          # 托盘: 不修
        {"kind": "item", "mountLocal": {"position": [0, 0, -0.12]}},  # 缺 grabLocal
        {"kind": "item", "grabLocal": [0, 0.089, 0]},          # 缺 mountLocal
    ):
        assert np.allclose(_grab_corrected(record, transform), transform)
