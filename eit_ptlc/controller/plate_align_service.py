"""
功能:
    板位对位控制台后端服务: 一键示教点样视觉零点。驱动机器人从点样巢取一块 (操作员已坐正的)
    空白板, 举到拍照位 P86, 用 .163 对位相机测板原始位姿 (u, v, theta), 与当前零点参考比对
    给出差值供预览; 操作员确认后把新位姿写回 config/local_plate_vision.yaml 的 reference,
    并令 Bridge 热更缓存生效。

    运动/工位动作全部经 action executor 逐步下发 (复用 robot.* 与点样 L2 动作的门控, 不裸调 controller);
    取图经 vision client (复用 DO7 补光时序 + Bridge /measure_pose)。示教是标定写操作, 仅 DEBUG
    模式可用 (门控在路由层)。

    示教零点原理: 参考位姿必须对应"能被名义 P19 正确放入的板姿"。故先把 7Y 推到放板位, 让板停在
    放板位 P19, 机器人**从下方在 P19 抓起**(复用生产 robot_suction_pick 的下方进近)一块"已正确坐入"
    的板举到 P86 拍照, 其像素位姿即正确零点(与生产"7Y推出→P19放板"同条件)。生产中夹偏的板据此零点算纠偏。
协议:
    teach(current_mode) -> {measured, current_reference, delta_px, delta_theta_deg, expect_center, sane, message}
    apply(u, v, theta)  -> {reference, reloaded}
    status()            -> {reference, bridge}
"""
from __future__ import annotations

import logging
from typing import Any

from eit_ptlc.action.models import ActionStatus
from eit_ptlc.controller import local_plate_vision

log = logging.getLogger(__name__)

# 示教中心像素与名义板位 (detect.expect_center) 的允许带: 超出判为误检, 拒绝采纳为零点
_SANE_BAND_PX = 250.0

# 取板→举到 P86 拍照位 的运动步。抓板复用生产 robot_suction_pick(spotting): 先 sampling.place_axis 把
# 7Y 推到放板位(确保板停在 P19), 吸盘朝上**从下方**经 pick.approach_*(Z−30)进近到 P19 吸起, 再
# pick.retreat_*(Z+20)提板 —— 与生产取板同点同向; 之后举到 P86 拍姿(生产此处回 P1, 示教岔到 P86)。
# 每步 (action, args), 经 executor 串行下发。
_PICKUP_STEPS: list[tuple[str, dict[str, Any]]] = [
    ("robot.require_anchor", {"point_id": "P1", "joint_tol_deg": 2.0, "pos_tol_mm": 5.0, "rot_tol_deg": 5.0}),
    ("sampling.place_axis", {}),  # 7Y 推出到放板位, 确保板停在 P19 (动作码31)
    ("robot.move_to_point", {"point_id_or_robot_name": "P4", "motion": "move_j", "acc": 60, "vel": 50, "cp": 20}),
    ("robot.tool_action", {"action": "rotary-up", "timeout_ms": 3000}),
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.pick.approach_far", "motion": "move_l", "acc": 12, "vel": 15, "cp": 0}),   # 从下方进近 (Z−30)
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.pick.approach_near", "motion": "move_l", "acc": 6, "vel": 10, "cp": 0}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P19", "motion": "move_l", "acc": 6, "vel": 5, "cp": 0}),
    ("robot.tool_action", {"action": "suction-on", "timeout_ms": 3000}),
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.pick.retreat_near", "motion": "move_l", "acc": 6, "vel": 10, "cp": 0}),   # Z+20 提板
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.pick.retreat_far", "motion": "move_l", "acc": 18, "vel": 20, "cp": 0}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P4", "motion": "move_j", "acc": 60, "vel": 50, "cp": 20}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P86", "motion": "move_j", "acc": 30, "vel": 30, "cp": 0}),
    ("robot.dwell", {"duration_ms": 300}),
]

# 原位放回 (P19) + 回 P1: 复用生产 robot_suction_put(spotting) 的放板段 —— 从上方经 put.approach_*(Z+20)
# 下到 P19 松手放板, 再 put.retreat_*(Z−30)空爪下潜退出(松手后是空爪, 下潜不碰板, 同生产放板)。
# 抓/放同点 P19; rotary-down 回 P1 复位。
_RETURN_STEPS: list[tuple[str, dict[str, Any]]] = [
    ("robot.move_to_point", {"point_id_or_robot_name": "P4", "motion": "move_j", "acc": 60, "vel": 50, "cp": 20}),
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.put.approach_far", "motion": "move_l", "acc": 12, "vel": 15, "cp": 0}),
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.put.approach_near", "motion": "move_l", "acc": 6, "vel": 10, "cp": 0}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P19", "motion": "move_l", "acc": 6, "vel": 5, "cp": 0}),
    ("robot.tool_action", {"action": "suction-off", "timeout_ms": 3000}),
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.put.retreat_near", "motion": "move_l", "acc": 6, "vel": 10, "cp": 0}),   # 空爪下潜退出 (Z−30)
    ("robot.move_to_point", {"point_id_or_robot_name": "spotting.put.retreat_far", "motion": "move_l", "acc": 18, "vel": 20, "cp": 0}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P4", "motion": "move_j", "acc": 60, "vel": 50, "cp": 20}),
    ("robot.tool_action", {"action": "rotary-down", "timeout_ms": 3000}),
    ("robot.move_to_point", {"point_id_or_robot_name": "P1", "motion": "move_j", "acc": 50, "vel": 37, "cp": 2}),
    ("robot.require_anchor", {"point_id": "P1", "joint_tol_deg": 2.0, "pos_tol_mm": 5.0, "rot_tol_deg": 5.0}),
]


class PlateAlignError(RuntimeError):
    """板位对位示教失败 (运动步失败 / 配置缺失 / 采值不合理)。"""


class PlateAlignService:
    """点样视觉零点一键示教服务 (executor 走运动, vision client 走取图与写零点热更)。"""

    def __init__(self, *, executor: Any, vision_client: Any) -> None:
        """
        参数:
            executor: ActionExecutor, 逐步下发 robot.* 动作 (带 rail/安全门控)
            vision_client: PallasVisionClient, 提供 capture_plate_pose / bridge_reload / bridge_status
        """
        self._executor = executor
        self._vision = vision_client

    async def teach(self, *, current_mode: str) -> dict[str, Any]:
        """一键示教: 取板→举到 P86 拍姿→放回, 返回测得零点与当前零点的比对 (不写盘)。

        参数:
            current_mode: 当前控制模式, 透传给 executor 做动作模式门控 (示教须 DEBUG)
        返回:
            dict{measured{u,v,theta,valid}, current_reference{u0,v0,theta0}, delta_px,
                 delta_theta_deg, expect_center, sane, message}
        异常:
            PlateAlignError: 运动步失败 / 本地视觉配置缺失
        """
        cfg = local_plate_vision.load_cfg()
        if cfg is None:
            raise PlateAlignError("config/local_plate_vision.yaml 缺失, 无法示教零点")

        # 1. 取板举到 P86 (取板段失败即抛, 不进入拍照/放回)
        await self._run_steps(_PICKUP_STEPS, current_mode)
        # 2. 拍姿; 无论成功与否都要把板放回复位 (finally)
        try:
            pose = await self._vision.capture_plate_pose()
        finally:
            await self._run_steps(_RETURN_STEPS, current_mode)

        current_reference = {"u0": cfg.u0, "v0": cfg.v0, "theta0": cfg.theta0}
        expect_center = [float(cfg.expect_center[0]), float(cfg.expect_center[1])]
        if not pose.get("valid"):
            return {"measured": pose, "current_reference": current_reference,
                    "delta_px": None, "delta_theta_deg": None, "expect_center": expect_center,
                    "sane": False, "message": "未识别到板 (请确认板已坐正 / 补光正常), 未采到零点"}

        u = float(pose["u"])
        v = float(pose["v"])
        theta = float(pose["theta"])
        du = u - cfg.u0
        dv = v - cfg.v0
        delta_px = round((du * du + dv * dv) ** 0.5, 1)
        sane = self._is_sane(u, v, cfg)
        message = "OK" if sane else (
            f"测得中心 ({u:.0f},{v:.0f}) 偏离名义板位 ({expect_center[0]:.0f},{expect_center[1]:.0f}) 过大, "
            "疑似误检, 不建议采纳"
        )
        return {"measured": pose, "current_reference": current_reference,
                "delta_px": delta_px, "delta_theta_deg": round(theta - cfg.theta0, 2),
                "expect_center": expect_center, "sane": sane, "message": message}

    async def apply(self, u: float, v: float, theta: float) -> dict[str, Any]:
        """把示教测得的板姿写回 reference 并令 Bridge 热更 (确认应用)。

        参数:
            u/v: 板中心像素; theta: 板倾角 (deg) — 取自一次合理的 teach 结果
        返回:
            dict{reference{u0,v0,theta0}, reloaded}
        异常:
            PlateAlignError: 采值不合理 (非有限 / 偏离名义板位过大), 拒绝写入以免污染零点
        """
        cfg = local_plate_vision.load_cfg()
        if cfg is None:
            raise PlateAlignError("config/local_plate_vision.yaml 缺失, 无法写零点")
        u = float(u)
        v = float(v)
        theta = float(theta)
        if not self._is_sane(u, v, cfg):
            raise PlateAlignError(
                f"采值 ({u:.0f},{v:.0f}) 偏离名义板位 {tuple(int(x) for x in cfg.expect_center)} 过大, 拒绝写入零点")
        reference = local_plate_vision.write_reference(u, v, theta)
        reload_result = await self._vision.bridge_reload()
        log.info("[PlateAlign] 已应用新零点 %s, bridge 热更 =%s", reference, reload_result)
        return {"reference": reference, "reloaded": bool(reload_result.get("reloaded", False))}

    async def status(self) -> dict[str, Any]:
        """当前零点参考 + Bridge 状态 (供控制台显示; 不动机器人)。"""
        cfg = local_plate_vision.load_cfg()
        reference = None
        if cfg is not None:
            reference = {"u0": cfg.u0, "v0": cfg.v0, "theta0": cfg.theta0,
                         "expect_center": [float(cfg.expect_center[0]), float(cfg.expect_center[1])]}
        bridge = await self._vision.bridge_status()
        return {"reference": reference, "bridge": bridge}

    @staticmethod
    def _is_sane(u: float, v: float, cfg: Any) -> bool:
        """测得中心是否落在名义板位 (expect_center) 的允许带内 (拦误检, 防污染零点)。"""
        import math

        if not (math.isfinite(u) and math.isfinite(v)):
            return False
        expect_x, expect_y = cfg.expect_center
        return abs(u - expect_x) <= _SANE_BAND_PX and abs(v - expect_y) <= _SANE_BAND_PX

    async def _run_steps(self, steps: list[tuple[str, dict[str, Any]]], current_mode: str) -> None:
        """逐步经 executor 下发运动动作; 任一步非 DONE 即抛 PlateAlignError 中止。"""
        for action, args in steps:
            result = await self._executor.execute(action, dict(args), current_mode=current_mode)
            if result.status is not ActionStatus.DONE:
                raise PlateAlignError(
                    f"示教运动步失败: {action}({args.get('point_id_or_robot_name') or args.get('action') or ''}) "
                    f"-> {result.status.value}: {result.message}")
