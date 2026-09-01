"""CameraService - 相机拍照抽象层

职责：为 ScrapeStage（Step 20 拍照）提供统一的拍照接口，
隔离 Mock 与实机（大恒 PALLAS SDK）差异。

接口：
    CameraService.capture(sample_id, save_dir) -> Path
        触发拍照，返回保存的图像路径。

设计决策：
- capture() 为 async 方法——Daheng 实现中 SDK 调用可能在 executor 中运行
- save_dir 由调用方传入（SampleStore.get_sample_dir(sample_id)），不硬编码路径
- 固定保存为 after.jpg（Step 20 仅拍展开后图像）
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class CameraService(ABC):
    """相机拍照抽象基类。"""

    @abstractmethod
    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg") -> Path:
        """触发拍照，返回保存的图像路径。

        Args:
            sample_id: 样品 ID（用于日志）
            save_dir: 图像保存目录（由调用方提供）
            filename: 保存文件名（默认 after.jpg）

        Returns:
            保存后的图像文件路径
        """


class MockCameraService(CameraService):
    """测试阶段实现：从预置测试图复制到 save_dir/<filename>

    用于无实机相机的开发/调试场景。

    可选 test_before_image：若提供且文件存在，在 capture(filename="after.jpg") 时
    同时复制为 before.jpg，用于双帧视觉分析的开发调试。
    当 BeforePhotoStage 显式调用 capture(filename="before.jpg") 时，
    不会触发自动 before 复制（避免重复覆盖）。
    """

    def __init__(self, test_image: Path, test_before_image: Optional[Path] = None):
        self._test_image = Path(test_image)
        self._test_before_image = Path(test_before_image) if test_before_image else None

    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg") -> Path:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        dst = save_dir / filename

        # 源图像选择：before.jpg 优先使用 _test_before_image，其余使用 _test_image
        if filename == "before.jpg" and self._test_before_image is not None and self._test_before_image.is_file():
            src = self._test_before_image
        else:
            src = self._test_image
        shutil.copy2(src, dst)
        log.info("[MockCamera] 复制预置图 %s → %s", src, dst)

        # 双帧支持：仅在 capture after.jpg 时，自动附带 before.jpg
        # BeforePhotoStage 显式调用 capture(filename="before.jpg") 时不触发
        if filename == "after.jpg" and self._test_before_image is not None and self._test_before_image.is_file():
            before_dst = save_dir / "before.jpg"
            shutil.copy2(self._test_before_image, before_dst)
            log.info("[MockCamera] 复制 before 预置图 %s → %s", self._test_before_image, before_dst)

        return dst


class DahengCameraService(CameraService):
    """实机实现：通过大恒 PALLAS SDK 调用 GigE 彩色相机拍照。

    拍照逻辑委托给 scripts/daheng_capture.py，SDK 阻塞调用通过
    run_in_executor 放入线程池，避免阻塞 asyncio 事件循环。
    """

    def __init__(self, params: dict | None = None):
        """Args:
            params: 相机参数字典，与 config.example.yaml camera.daheng 段对应。
                    缺失字段回落到 scripts/daheng_capture.DEFAULT_PARAMS。
        """
        self._params = params or {}

    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg") -> Path:
        from scripts.daheng_capture import capture as daheng_capture

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        dst = save_dir / filename

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, daheng_capture, dst, self._params)
