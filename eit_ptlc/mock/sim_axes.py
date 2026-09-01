"""仿真沙盒的轴绑定表 (flat 镜像节点 ↔ 单点伺服结构 ↔ 瞬移到位对)
====================================================================
功能:
    集中声明 11 根直线轴在两套点表间的对应关系, 供仿真沙盒 (runtime/sim_stack.py):
      1. flat→struct 同步任务 —— 真 PLC 每扫描做 `flat := struct.fActPos` 镜像;
         沙盒的行为源反过来: L2 瞬移/on_done 写 flat, 同步任务抄进 manual 伺服结构
         的 fActPos, 20Hz realtime_feedback_loop 读 struct 后 axis_pose 才有数;
      2. 瞬移到位对 (TELEPORT_MIRRORS) —— 阶段②的 L2 行为近似: 动作 DONE 时
         `*_ActPos := *_Target` (Target 装的是上位机真实下推的示教/仿射值, 所以
         瞬移落在**真实位置**上); 无 flat Target 的轴 (上下料 1Z/2Z 的行程烧在
         PLC 里) 阶段②不动, 由阶段③编排说明书接管;
      3. /api/sim/state 的轴读写寻址。

真源出处 (三方逐字对照, 改任何一处先查另两处):
    axis id / struct 名  ← config/manual_points.yaml stations.*.axes[]
    flat ActPos/Target 名 ← config/plc_nodes.yaml
    axis id ↔ 三维机构    ← three_d/models/device-manifest.json realtime.axes
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimAxisLink:
    """一根轴的沙盒绑定: manual 伺服结构名 + flat 实际位镜像节点."""
    axis_id: str
    label: str
    struct: str          # manual_points.yaml 的伺服结构容器名 (…DATE)
    act_pos: str         # plc_nodes.yaml 的 flat 实际位节点


#: 11 根直线轴 (与 manual_points.yaml / plc_nodes.yaml 逐字对照)
AXIS_LINKS: tuple[SimAxisLink, ...] = (
    SimAxisLink("axis_1z", "玻璃上料轴1Z", "玻璃上料轴1ZDATE", "FeedLift_1Z_ActPos"),
    SimAxisLink("axis_2z", "玻璃上料轴2Z", "玻璃上料轴2ZDATE", "FeedLift_2Z_ActPos"),
    SimAxisLink("axis_3y", "打样瓶上料轴3Y", "打样瓶上料轴3YDATE", "Sampling_3Y_ActPos"),
    SimAxisLink("axis_4x", "上样轴4X", "上样轴4X轴DATE", "Sampling_4X_ActPos"),
    SimAxisLink("axis_5z", "上样轴5Z", "上样轴5Z轴DATE", "Sampling_5Z_ActPos"),
    SimAxisLink("axis_6x", "点样轴6X", "点样轴6XDATE", "Spot_6X_ActPos"),
    SimAxisLink("axis_7y", "点样轴7Y", "点样轴7YDATE", "Spot_7Y_ActPos"),
    SimAxisLink("axis_8y", "拍照轴8Y", "拍照轴8YDATE", "Photo_8Y_ActPos"),
    SimAxisLink("axis_9x", "刮板轴9X", "刮板轴9XDATE", "PhotoScrape_9X_ActPos"),
    SimAxisLink("axis_10z", "刮板轴10Z", "刮板轴10ZDATE", "PhotoScrape_10Z_ActPos"),
    SimAxisLink("axis_11y", "地轨轴11Y", "地轨轴11YDATE", "Rail_ActPos"),
)

AXIS_BY_ID = {link.axis_id: link for link in AXIS_LINKS}

#: flat 别名: PLC 侧同源双写的节点 (写 ActPos 时顺带保持一致)
ACT_POS_ALIASES: dict[str, tuple[str, ...]] = {
    "Photo_8Y_ActPos": ("PhotoScrape_8Y_ActPos",),
}

#: 瞬移到位对 (工位前缀 -> ((Target 源, ActPos 目的), ...)):
#: 只列上位机会真实下推 Target 的轴 —— 值是真示教/仿射结果, 瞬移即"落到真实位置"。
#: FeedLift/Develop/Collect/StagingA 的轴行程烧在 PLC 里, 无 flat Target, 留给阶段③。
TELEPORT_MIRRORS: dict[str, tuple[tuple[str, str], ...]] = {
    "Sampling": (
        ("Sampling_4X_Target", "Sampling_4X_ActPos"),
        ("Sampling_3Y_Target", "Sampling_3Y_ActPos"),
        ("Sampling_5Z_Target", "Sampling_5Z_ActPos"),
    ),
    "PhotoScrape": (
        ("Spot_7Y_Target", "Spot_7Y_ActPos"),
        ("Photo_8Y_Target", "Photo_8Y_ActPos"),
        ("Photo_8Y_Target", "PhotoScrape_8Y_ActPos"),
        ("PhotoScrape_Align_TargetX", "PhotoScrape_9X_ActPos"),
        ("PhotoScrape_Align_TargetZ", "PhotoScrape_10Z_ActPos"),
    ),
}


def rail_on_done_factory(read, write):
    """Rail 工位的 on_done: Rail_ActPos := Rail_Pos_Target[Rail_Target_Position-1]。

    静态镜像对写不了数组索引, 故用 run_l2_fsm 的 on_done 回调表达。
    参数:
        read/write: async (name[, value]) 节点读写 (mock_read/mock_write 的偏函数)
    """
    async def on_done(code: int) -> None:
        slot = int(await read("Rail_Target_Position"))
        targets = await read("Rail_Pos_Target")
        if isinstance(targets, (list, tuple)) and 1 <= slot <= len(targets):
            await write("Rail_ActPos", float(targets[slot - 1]))
            await write("Rail_Homed", True)
    return on_done
