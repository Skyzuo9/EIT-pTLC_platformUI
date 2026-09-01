"""刮后对账叠加 — "说好的 vs 刮到的" (spec §5.2)。

scraped.jpg(原始相机帧) → replay_normalization 回放到归一化帧(禁重新检测, 契约 C-3)
→ 读 cnc_path 落盘的 preview_payload.json(契约 C-5, never regenerates) → render_cnc_overlay。
青色指令路径 vs 照片里白色刮槽的错位 = 相机链+机床链+刀具链总 bias 的直接图像测量。

全链 fail-safe: 对账是哨兵不是工艺步, 任何失败 ok=false 不抛 (YAML try 双保险)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from eit_ptlc.controller.cnc_preview import render_cnc_overlay

log = logging.getLogger(__name__)


def _ensure_tlc_analyze() -> Any:
    """动态注入 View/pTLC_Viewing 并导入 tlc_analyze (与 vision_quality 同模式)。"""
    view_dir = Path(__file__).resolve().parents[2] / "View" / "pTLC_Viewing"
    if str(view_dir) not in sys.path:
        sys.path.insert(0, str(view_dir))
    try:
        import tlc_analyze  # type: ignore  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"Unable to import tlc_analyze from {view_dir}: {exc}") from exc
    return tlc_analyze


def _url_for(path: Path, image_root: Path | None) -> str:
    if image_root is None:
        return ""
    try:
        rel = path.resolve().relative_to(Path(image_root).resolve()).as_posix()
        return f"/api/vision/image/{rel}"
    except (OSError, ValueError):
        return ""


def render_scraped_overlay(
    summary_path: Path | str, scraped_path: Path | str, *, image_root: Path | None = None,
) -> dict:
    """刮后照片 → scraped_normalized.jpg + scraped_annotated.png, 落 case 目录。永不 raise。"""
    out = {"ok": False, "scraped_url": "", "annotated_url": "", "message": ""}
    try:
        case_dir = Path(summary_path).parent
        payload_path = case_dir / "preview_payload.json"
        if not payload_path.is_file():
            out["message"] = "缺少 preview_payload.json(候选未经 cnc_path 或几何无板参照), 跳过对账叠加"
            return out
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        ta = _ensure_tlc_analyze()
        normalized = ta.replay_normalization(
            scraped_path, summary_path, case_dir / "scraped_normalized.jpg")
        out["scraped_url"] = _url_for(Path(normalized), image_root)
        annotated = case_dir / "scraped_annotated.png"
        if not render_cnc_overlay(normalized, payload, annotated):
            out["message"] = "对账叠加渲染失败(cv2 缺失或底图不可读)"
            return out
        out["ok"] = True
        out["annotated_url"] = _url_for(annotated, image_root)
        return out
    except Exception as exc:  # noqa: BLE001 哨兵步全链 fail-safe, 失败留 message 供日志/复盘
        log.warning("[reconcile] 刮后对账叠加失败(不阻断主流程): %s", exc, exc_info=True)
        out["message"] = f"对账叠加失败: {exc}"
        return out


class ScrapeReconcileController:
    """executor vision kind 的 async 入口 (与 CncPathController 同型)。"""

    def __init__(self, image_root_provider: Callable[[], Path] | None = None) -> None:
        self._image_root = image_root_provider

    async def scraped_overlay(self, summary_path: str = "", scraped_path: str = "") -> dict:
        loop = asyncio.get_running_loop()
        root = Path(self._image_root()) if self._image_root is not None else None
        return await loop.run_in_executor(
            None, lambda: render_scraped_overlay(summary_path, scraped_path, image_root=root))
