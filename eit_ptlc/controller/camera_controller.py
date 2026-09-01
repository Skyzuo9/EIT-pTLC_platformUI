"""相机控制器
============
功能:
    按 CameraCfg 选择 Mock 或大恒实机相机服务, 对上层提供统一拍照入口 (含光源由驱动负责).
    迁移自 UI-Upper/core/camera_service.py 的业务装配部分; 采集驱动在 driver/camera_driver.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

from eit_ptlc.config.models import CameraCfg
from eit_ptlc.driver.camera_driver import CameraService, DahengCameraService, MockCameraService

log = logging.getLogger(__name__)


def build_camera_service(cfg: CameraCfg) -> CameraService:
    """按配置构建相机服务 (mock=True 用预置图, 否则大恒 gxipy)."""
    if cfg.mock:
        log.info("[Camera] 使用 Mock 相机 (预置图 %s)", cfg.test_image)
        return MockCameraService(cfg.test_image, cfg.test_before_image)
    log.info("[Camera] 使用大恒实机相机 (ip=%s)", cfg.daheng.get("ip"))
    return DahengCameraService(cfg.daheng)


class CameraController:
    """相机业务控制器: 封装拍照到样品目录, 含 profile 预填 + 逐项覆写解析."""

    def __init__(self, service: CameraService, profiles: dict | None = None) -> None:
        self._service = service
        self._profiles = dict(profiles or {})    # {profile名: {部分 daheng 参数}}

    @classmethod
    def from_config(cls, cfg: CameraCfg) -> "CameraController":
        return cls(build_camera_service(cfg), profiles=cfg.profiles)

    def resolve_params(self, profile: str | None, overrides: dict | None) -> dict:
        """合成本次拍照参数: profile 基线 ← 逐项覆写 (overrides 优先)。

        profile 为 None/空 → 仅用 overrides; profile 未知 → KeyError (调用方拒绝)。
        返回的是"覆盖增量"(叠加在服务构造时的 daheng 基线之上)。
        """
        base: dict = {}
        if profile:
            if profile not in self._profiles:
                raise KeyError(f"未知相机 profile: {profile} (可用 {sorted(self._profiles)})")
            base = dict(self._profiles[profile])
        if overrides:
            base.update({k: v for k, v in overrides.items() if v is not None})
        return base

    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg",
                      profile: str | None = None, overrides: dict | None = None) -> Path:
        """触发拍照, 返回保存路径; 按 profile + overrides 解析相机参数。"""
        params = self.resolve_params(profile, overrides)
        return await self._service.capture(sample_id, save_dir, filename=filename, params=params)

    async def capture_with_timing(
        self,
        sample_id: str,
        save_dir: Path,
        *,
        filename: str = "after.jpg",
        profile: str | None = None,
        overrides: dict | None = None,
    ) -> Tuple[Path, dict]:
        """触发拍照并返回 UV 计时，参数解析与生产拍照入口完全一致."""
        params = self.resolve_params(profile, overrides)
        return await self._service.capture_with_timing(
            sample_id, save_dir, filename=filename, params=params,
        )
