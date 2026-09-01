"""伺服点位标定与下发服务 — 把 PlateCatalog 与 OPC 驱动接起来。

职责 (单写者, B 方案):
  - 采点: 操作员把轴点动到某孔后, 本服务读 PLC 镜像的实际位置 `*_ActPos`
    (PC 只读), 记为该孔的标定点。3 点齐 → commit 解仿射并持久化 calibration.yaml。
  - 下发: 执行时按业务参数 (实例 + 孔行列) 实时算物理目标, 写 PLC 目标节点 `*_Target`
    (PC 唯一写者), 由 PLC 既有 step 序列消费 → 运动。

  jog 本身不归本服务: 归 HMI 手动屏, 或上位机的单点控制 (`/api/manual/*`, 见
  controller/manual_service.py)。本服务不夺取伺服控制权; 仅读 ActPos / 写 Target。

  曾经还有一条「去使能手推」通道 (写 `Sampling_Servo_FreeMove` 让 4X/3Y 掉使能供人手推),
  已于 2026-07 删除 —— PLC 侧那是个自毁循环: 两轴掉使能 ⇒ `bAllAxesEnabled` 假
  ⇒ `PLC_Ready` 假 ⇒ `PLC_Servo_伺服` 的排空块把 `Sampling_Servo_FreeMove` 抹掉
  ⇒ 轴立刻回电, 根本停不在去使能态; 且 5Z 的 xEnable 只有 `急停`, 从设计上就永不释放。
  标定改走单点控制的电动点动 (三轴全覆盖, 可 0.01mm 相对定位微调)。

  轴对当前默认上样 4X(X)/3Y(Y) —— 两块上样板共用。点样 6X/7Y 等将来按需扩展
  (届时改为按实例携带轴对)。
"""

from __future__ import annotations

import logging

from eit_ptlc.controller.plate_affine import CalibrationPoint, Well, WellTarget
from eit_ptlc.controller.plate_catalog import PlateCalibration, PlateCatalog, save_calibrations

log = logging.getLogger(__name__)


class CalibrationService:
    """采点(读 *_ActPos) + 提交(solve+持久化) + 下发(写 *_Target)。"""

    def __init__(
        self,
        catalog: PlateCatalog,
        driver,
        calibration_path,
        *,
        x_axis: str = "Sampling_4X",
        y_axis: str = "Sampling_3Y",
        x_limits: tuple[float, float] | None = None,
        y_limits: tuple[float, float] | None = None,
    ):
        self._catalog = catalog
        self._driver = driver
        self._path = calibration_path
        self._x = x_axis
        self._y = y_axis
        # 各轴软限位 (min, max) mm: 写 *_Target 前钳制, 防边角孔标定越程撞硬限位。
        # 由 bootstrap 从 points.yaml 注入; None = 未配置 (退化为不校验, 仅告警, 保留旧行为)。
        self._x_limits = x_limits
        self._y_limits = y_limits

    @property
    def catalog(self) -> PlateCatalog:
        """暴露只读目录 (供路由做查询 DTO; 写操作仍走本服务方法)。"""
        return self._catalog

    # —— 查询 ——
    def list_instances(self) -> list[PlateCalibration]:
        return self._catalog.instances()

    async def read_actpos(self) -> dict:
        """读当前轴对的实际位置镜像 (*_ActPos), 供实时显示与采点。"""
        if self._driver is None:
            raise RuntimeError("PLC 驱动未就绪")
        x = float(await self._driver.read_variable(f"{self._x}_ActPos"))
        y = float(await self._driver.read_variable(f"{self._y}_ActPos"))
        return {"x_axis": self._x, "x_mm": round(x, 3), "y_axis": self._y, "y_mm": round(y, 3)}

    def targets(self, instance_id: str) -> list[WellTarget]:
        return self._catalog.targets(instance_id)

    def target(self, instance_id: str, well: Well) -> tuple[float, float]:
        return self._catalog.well_target(instance_id, well)

    # —— 采点 / 提交 ——
    async def capture_well(self, well: Well) -> CalibrationPoint:
        """读当前轴实际位置 (*_ActPos) 作为 well 的标定点。需操作员先 jog 到该孔。"""
        pos = await self.read_actpos()
        point = CalibrationPoint(well, pos["x_mm"], pos["y_mm"])
        log.info("[calibration] 采点 %s @ (%.3f, %.3f)", well, point.x_mm, point.y_mm)
        return point

    def commit(self, instance_id: str, points: list[CalibrationPoint]) -> PlateCalibration:
        """提交标定 (≥3 点): 先纯函数式 solve 校验, 通过后才改缓存 + 持久化。

        次序关键: 退化/共线/不足点先在 validate_calibration 抛错 (不触碰共享状态),
        故原本可用的内存标定不会被坏输入覆盖 (该实例后续下发仍正常)。
        """
        self._catalog.validate_calibration(instance_id, points)  # 先校验, 失败即抛, 不动状态
        updated = self._catalog.set_calibration(instance_id, points)
        self._catalog.transform(instance_id)  # 校验已通过, 此处仅暖缓存
        save_calibrations(self._path, {c.id: c for c in self._catalog.instances()})
        log.info("[calibration] 提交并持久化 %s (%d 点)", instance_id, len(points))
        return updated

    # —— 下发 ——
    def _check_axis_limit(self, axis: str, v: float, limits: tuple[float, float] | None) -> None:
        """写 Target 前的软限位校验: 越程即拒发并抛错 (不静默 clamp, 避免把标错掩盖成贴边)。"""
        if limits is None:
            log.warning("[calibration] 轴 %s 未配置软限位, 跳过越程校验 (建议在 points.yaml 配置)", axis)
            return
        lo, hi = limits
        if not (lo <= v <= hi):
            raise ValueError(
                f"上样轴 {axis} 目标 {v:.3f} 超出软限位 [{lo}, {hi}]; 拒绝下发 (疑似标定越程, 请复核标定点)"
            )

    async def push_well(self, instance_id: str, well: Well) -> tuple[float, float]:
        """实时算该孔物理目标并写入 PLC 目标节点 (*_Target), 返回 (x_mm, y_mm)。"""
        if self._driver is None:
            raise RuntimeError("PLC 驱动未就绪")
        x, y = self._catalog.well_target(instance_id, well)
        # 两轴均先校验再下发: 任一越程则零写入 (避免写了 X 才在 Y 失败导致半下发)
        self._check_axis_limit(self._x, x, self._x_limits)
        self._check_axis_limit(self._y, y, self._y_limits)
        await self._driver.write_variable(f"{self._x}_Target", x)
        await self._driver.write_variable(f"{self._y}_Target", y)
        log.info("[calibration] 下发 %s %s → 4X=%.3f 3Y=%.3f", instance_id, well, x, y)
        return x, y
