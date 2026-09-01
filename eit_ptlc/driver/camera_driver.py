"""相机采集驱动
==============
功能:
    相机拍照抽象层, 隔离 Mock 与实机 (大恒 gxipy SDK) 差异; 为拍照业务提供统一接口.
    迁移自 UI-Upper/core/camera_service.py.

接口:
    CameraService.capture(sample_id, save_dir, filename) -> Path
        触发拍照, 返回保存的图像路径 (async; SDK 阻塞调用在 executor 中运行).
    CameraService.capture_with_timing(sample_id, save_dir, filename) -> (Path, dict)
        触发拍照, 返回图像路径 + UV 安全计时信息.

并发安全:
    DahengCameraService 使用 asyncio.Lock 防止并发相机访问.
    取消安全: 若 asyncio task 在 run_in_executor 运行时被取消, 必须等待后台 SDK
    线程完成清理/关灯后才释放锁，避免下一次拍照与未结束的 SDK 调用并发进入硬件.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


class CameraService(ABC):
    """相机拍照抽象基类."""

    @abstractmethod
    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg",
                      params: Optional[dict] = None) -> Path:
        """触发拍照, 返回保存的图像路径.

        参数:
            sample_id: 样品 ID (用于日志); save_dir: 保存目录; filename: 文件名;
            params: 本次拍照的相机参数覆盖 (profile + 逐项覆写后的完整/部分 daheng 参数);
                    Mock 实现忽略, 实机合并到基线参数。None 表示用构造时的基线。
        返回:
            保存后的图像文件路径
        """

    async def capture_with_timing(self, sample_id: str, save_dir: Path, *,
                                   filename: str = "after.jpg",
                                   params: Optional[dict] = None) -> Tuple[Path, dict]:
        """触发拍照, 返回图像路径 + UV 安全计时信息.

        默认实现: 委托给 capture(), 返回空 timing_info.
        实机实现 (DahengCameraService) 覆写此方法以返回真实计时数据.
        """
        path = await self.capture(sample_id, save_dir, filename=filename, params=params)
        return path, {}


class MockCameraService(CameraService):
    """Mock 实现: 从预置测试图复制到 save_dir/<filename>, 供无实机开发/调试.

    可选 test_before_image: 提供且存在时, capture(after.jpg) 同时复制 before.jpg.
    """

    def __init__(self, test_image: Path, test_before_image: Optional[Path] = None):
        self._test_image = Path(test_image)
        self._test_before_image = Path(test_before_image) if test_before_image else None

    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg",
                      params: Optional[dict] = None) -> Path:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        dst = save_dir / filename
        # Mock 忽略 params (无真实相机参数); before.jpg 优先用 test_before_image, 其余用 test_image
        if filename == "before.jpg" and self._test_before_image is not None and self._test_before_image.is_file():
            src = self._test_before_image
        else:
            src = self._test_image
        shutil.copy2(src, dst)
        log.info("[MockCamera] 复制预置图 %s -> %s", src, dst)
        # 双帧支持: capture after.jpg 时自动附带 before.jpg
        if filename == "after.jpg" and self._test_before_image is not None and self._test_before_image.is_file():
            before_dst = save_dir / "before.jpg"
            shutil.copy2(self._test_before_image, before_dst)
            log.info("[MockCamera] 复制 before 预置图 %s -> %s", self._test_before_image, before_dst)
        return dst


class DahengCameraService(CameraService):
    """实机实现: 通过大恒 gxipy SDK 调用 GigE 彩色相机拍照.

    SDK 阻塞调用经 run_in_executor 放入线程池, 避免阻塞 asyncio 事件循环.

    并发安全: asyncio.Lock 保证同一时刻只有一个相机操作在执行.
    取消安全: task 取消时等待 executor 中的同步拍照函数完成清理后再释放锁.
    """

    def __init__(self, params: dict | None = None):
        # params 与 app.yaml camera.daheng 段对应; 缺失字段回落到 daheng_capture.DEFAULT_PARAMS
        self._params = params or {}
        self._lock = asyncio.Lock()

    async def capture(self, sample_id: str, save_dir: Path, *, filename: str = "after.jpg",
                      params: Optional[dict] = None) -> Path:
        """触发拍照 (向后兼容: 仅返回路径)."""
        path, _timing = await self.capture_with_timing(
            sample_id, save_dir, filename=filename, params=params,
        )
        return path

    async def capture_with_timing(self, sample_id: str, save_dir: Path, *,
                                   filename: str = "after.jpg",
                                   params: Optional[dict] = None) -> Tuple[Path, dict]:
        """触发拍照, 返回图像路径 + UV 安全计时信息.

        在 asyncio.Lock 保护下调用底层 daheng_capture, 防止并发相机访问.
        若外层 task 被取消, 不能立即释放锁；run_in_executor 中的 SDK 线程无法被
        Python 取消, 必须等它完成 finally 关灯/断开后再放行下一次拍照.
        """
        from eit_ptlc.driver.daheng_capture import capture as daheng_capture

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        dst = save_dir / filename
        # 本次覆盖参数合并到基线 (覆盖优先); 缺失字段在 daheng_capture 内回落 DEFAULT_PARAMS
        merged = {**self._params, **(params or {})}

        await self._lock.acquire()
        future: asyncio.Future | None = None
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(None, daheng_capture, dst, merged)
            path, timing = await asyncio.shield(future)
            return path, timing
        except asyncio.CancelledError:
            if future is not None:
                log.warning(
                    "[DahengCamera] 拍照任务被取消，等待后台 SDK 线程完成清理后再释放相机锁",
                )
                try:
                    await asyncio.shield(future)
                except Exception:
                    log.exception("[DahengCamera] 取消后的后台清理以异常结束")
            raise
        finally:
            self._lock.release()
