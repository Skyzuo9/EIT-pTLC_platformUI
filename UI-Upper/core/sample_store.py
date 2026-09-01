"""SampleStore - 样品数据存取抽象层（DB 兼容设计）。

当前实现：文件系统（data/samples/<sample_id>/）。
未来可替换为 DB client，调用方无需改动。

样品目录结构：
    data/samples/
      <sample_id>/
        before.jpg / after.jpg
        analysis/
          summary.json
          <sample_id>.png
          task1_task2_contours_paths/
          task3_metrics/
        gcode/
          <sample_id>.gcode
          <sample_id>_path.png
        metadata.json
      debug/                    ← Debug Tab 测试目录（list_samples 排除）
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# 支持的图像扩展名
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


class SampleStore:
    """样品数据存取抽象层。

    当前实现：文件系统（data/samples/<sample_id>/）。
    未来可替换为 DB client，调用方无需改动。

    可选的 DB 二级索引层（self._db）由 ui/app.py 在启动后注入，
    在 save_metadata() 中同步触发 DB upsert，fire-and-forget 语义。
    """

    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        # DB 二级索引层（可选），由 ui/app.py 启动后注入
        self._db: Optional[Any] = None

    @property
    def root_dir(self) -> Path:
        """样品根目录。"""
        return self._root

    def get_sample_dir(self, sample_id: str) -> Path:
        """返回样品根目录。

        安全防御：对 sample_id 做 resolve() 归一化后校验结果路径仍在
        self._root 下，避免包含 ../ 或绝对路径的非法 sample_id 被后续
        shutil.rmtree() 等破坏性 IO 越界删除。越界时抛 ValueError。
        """
        candidate = (self._root / sample_id).resolve()
        root = self._root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as e:
            raise ValueError(
                f"非法 sample_id（路径越界）: {sample_id!r}"
            ) from e
        return self._root / sample_id

    def get_before_path(self, sample_id: str) -> Optional[Path]:
        """查找 before 图像（支持多种扩展名自动匹配）。

        Warning #7: 使用 is_file() 替代 exists()——Path.exists() 对目录也返回 True，
        而 is_file() 仅对文件返回 True，避免将目录误判为图像路径。
        """
        sample_dir = self.get_sample_dir(sample_id)
        for ext in _IMAGE_EXTENSIONS:
            candidate = sample_dir / f"before{ext}"
            if candidate.is_file():
                return candidate
        # 也检查大写扩展名
        for ext in _IMAGE_EXTENSIONS:
            candidate = sample_dir / f"before{ext.upper()}"
            if candidate.is_file():
                return candidate
        return None

    def set_before_path(self, sample_id: str, path: Path) -> None:
        """记录 before 图像路径到 metadata（供 BeforePhotoStage 写入、ScrapeStage 读取）。

        当前实现：将图像复制到样品目录下的 before.jpg（若源路径不在样品目录中）。
        未来 DB 实现时可直接写入记录。
        """
        src = Path(path)
        if not src.is_file():
            log.warning("[SampleStore] set_before_path: 源文件不存在 %s", src)
            return
        sample_dir = self.get_sample_dir(sample_id)
        sample_dir.mkdir(parents=True, exist_ok=True)
        dst = sample_dir / f"before{src.suffix}"
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
            log.info("[SampleStore] before 图像已保存: %s → %s", src, dst)
        else:
            log.debug("[SampleStore] before 图像已在目标位置: %s", dst)

    def get_after_path(self, sample_id: str) -> Optional[Path]:
        """查找 after 图像（支持多种扩展名自动匹配）。

        Warning #7: 使用 is_file() 替代 exists()——Path.exists() 对目录也返回 True，
        而 is_file() 仅对文件返回 True，避免将目录误判为图像路径。
        """
        sample_dir = self.get_sample_dir(sample_id)
        for ext in _IMAGE_EXTENSIONS:
            candidate = sample_dir / f"after{ext}"
            if candidate.is_file():
                return candidate
        for ext in _IMAGE_EXTENSIONS:
            candidate = sample_dir / f"after{ext.upper()}"
            if candidate.is_file():
                return candidate
        return None

    def get_analysis_dir(self, sample_id: str) -> Path:
        """返回 analysis 子目录。"""
        return self._root / sample_id / "analysis"

    def get_gcode_dir(self, sample_id: str) -> Path:
        """返回 gcode 子目录。"""
        return self._root / sample_id / "gcode"

    def has_analysis(self, sample_id: str) -> bool:
        """检查样品是否已有分析结果。

        搜索模式：
          1. analysis_dir/summary.json  （旧格式兼容）
          2. analysis_dir/{sample_id}/summary.json  （process_pair case_dir 嵌套）
        """
        analysis_dir = self.get_analysis_dir(sample_id)
        # 模式 1: analysis_dir/summary.json
        if (analysis_dir / "summary.json").exists():
            return True
        # 模式 2: analysis_dir/{sample_id}/summary.json（process_pair 输出在子目录）
        if (analysis_dir / sample_id / "summary.json").exists():
            return True
        return False

    def get_summary_path(self, sample_id: str) -> Optional[Path]:
        """返回 summary.json 路径，不存在返回 None。

        搜索模式：
          1. analysis_dir/summary.json  （旧格式兼容）
          2. analysis_dir/{sample_id}/summary.json  （process_pair case_dir 嵌套）
        """
        analysis_dir = self.get_analysis_dir(sample_id)
        # 模式 1: analysis_dir/summary.json
        candidate = analysis_dir / "summary.json"
        if candidate.exists():
            return candidate
        # 模式 2: analysis_dir/{sample_id}/summary.json（process_pair 子目录）
        candidate = analysis_dir / sample_id / "summary.json"
        if candidate.exists():
            return candidate
        return None

    def get_annotated_image_path(self, sample_id: str) -> Optional[Path]:
        """返回标注图路径，不存在返回 None。

        搜索模式：
          1. analysis_dir/{sample_id}_annotated.png  （VisionService 生成的主路径）
          2. analysis_dir/{sample_id}/{sample_id}_annotated.png  （process_pair case_dir 嵌套）
          3. analysis_dir/{sample_id}.png/jpg  （旧格式兼容）
        """
        analysis_dir = self.get_analysis_dir(sample_id)
        # 模式 1: analysis_dir/{sample_id}_annotated.png
        candidate = analysis_dir / f"{sample_id}_annotated.png"
        if candidate.exists():
            return candidate
        # 模式 2: analysis_dir/{sample_id}/{sample_id}_annotated.png（process_pair 嵌套）
        candidate = analysis_dir / sample_id / f"{sample_id}_annotated.png"
        if candidate.exists():
            return candidate
        # 模式 3: 旧格式兼容
        for ext in (".png", ".jpg"):
            candidate = analysis_dir / f"{sample_id}{ext}"
            if candidate.exists():
                return candidate
        return None

    def list_samples(self) -> list[str]:
        """列出所有样品 ID（按目录名，仅含有效样品目录）。

        排除以 "." 开头的目录、"debug" 目录，以及 LogPersistence 兜底目录 "_system"。
        """
        if not self._root.exists():
            return []
        samples = []
        for d in sorted(self._root.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in ("debug", "_system"):
                samples.append(d.name)
        return samples

    def save_metadata(self, sample_id: str, meta: dict) -> Path:
        """写入 metadata.json（读-改-写合并）。同时触发 DB upsert（如已注入 DB 二级索引）。
    
        合并语义：RecipeTask 与 Vision Tab 两路径都会调用 save_metadata 写入不同子集字段
        （前者写 recipe_name/completed_at/enabled_stages，后者写 selected_bands/gcode_path）。
        若采用“后写者赢”语义会互相抹掉 → History Tab 只能看到最后一次写入的字段。
        改为合并后，metadata.json 会增量累加，例如先 RecipeTask 下发 recipe_name，
        后 Vision Tab 补充 selected_bands，两者字段都保留；updated_at 永远刷新为当前时间。
        """
        meta_path = self.get_sample_dir(sample_id) / "metadata.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
    
        # 读-改-写：如已存在则先加载旧字段，新传入的同名字段覆盖旧值，其余保留。
        old: dict = {}
        if meta_path.is_file():
            try:
                old = json.loads(meta_path.read_text(encoding="utf-8")) or {}
                if not isinstance(old, dict):
                    old = {}
            except (json.JSONDecodeError, OSError) as e:
                log.warning(
                    "[SampleStore] save_metadata 读取旧 metadata 失败（将覆写） %s: %s",
                    meta_path,
                    e,
                )
                old = {}
        merged: dict = {**old, **meta}
    
        # updated_at 永远刷新；created_at 以旧值优先，否则回退到当前时间。
        merged["updated_at"] = datetime.now().isoformat()
        if not merged.get("created_at"):
            merged["created_at"] = merged["updated_at"]
    
        meta_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    
        # DB 同步（fire-and-forget，不阻塞主流程）
        if self._db is not None:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        self._db.upsert_sample(sample_id, merged, self.get_sample_dir(sample_id))
                    )
            except Exception as e:
                log.debug("[SampleStore] DB upsert_sample 调度失败（已忽略）: %s", e)
    
        return meta_path

    def load_metadata(self, sample_id: str) -> Optional[dict]:
        """读取 metadata.json，不存在返回 None。"""
        meta_path = self.get_sample_dir(sample_id) / "metadata.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("[SampleStore] 读取 metadata 失败 %s: %s", meta_path, e)
            return None

    def create_sample_dir(self, sample_id: str) -> Path:
        """创建样品目录结构（含 analysis/ 和 gcode/ 子目录）。"""
        sample_dir = self.get_sample_dir(sample_id)
        (sample_dir / "analysis").mkdir(parents=True, exist_ok=True)
        (sample_dir / "gcode").mkdir(parents=True, exist_ok=True)
        return sample_dir

    def save_capture(self, sample_id: str, image_path: Path, label: str = "after") -> Path:
        """将拍照图像保存到样品目录。

        Args:
            sample_id: 样品 ID
            image_path: 源图像路径（由 CameraService.capture() 返回）
            label: "after"（scrape 阶段）或 "before"（spotting 阶段，预留）

        Returns:
            保存后的目标路径
        """
        sample_dir = self.get_sample_dir(sample_id)
        sample_dir.mkdir(parents=True, exist_ok=True)
        dst = sample_dir / f"{label}{image_path.suffix}"
        shutil.copy2(image_path, dst)
        log.info("[SampleStore] 保存 %s 图像: %s → %s", label, image_path, dst)
        return dst

    def get_debug_dir(self) -> Path:
        """返回 debug 目录路径（与样品目录同级）。"""
        return self._root / "debug"

    # ------------------------------------------------------------------
    # DB 同步辅助方法（fire-and-forget，由外部触发点调用）
    # ------------------------------------------------------------------

    def trigger_db_analysis(
        self, sample_id: str, summary: dict, summary_path: Path, bands: list[dict]
    ) -> None:
        """视觉分析完成后同步 analyses + bands 到 DB（如已注入）。"""
        if self._db is None:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                async def _do():
                    await self._db.upsert_analysis(sample_id, summary, summary_path)
                    await self._db.upsert_bands(sample_id, bands)
                asyncio.create_task(_do())
        except Exception as e:
            log.debug("[SampleStore] DB trigger_db_analysis 失败（已忽略）: %s", e)

    def trigger_db_gcode(self, sample_id: str) -> None:
        """G-code 生成后同步 gcode_files 到 DB（存量样品兼容渠道）。

        v2 主路径请使用 trigger_db_scrape_arrays。本函数仅供
        scripts/ingest_samples_to_db.py 后补历史样品调用。
        """
        if self._db is None:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                meta = self.load_metadata(sample_id) or {}
                gcode_dir = self.get_gcode_dir(sample_id)
                asyncio.create_task(
                    self._db.upsert_gcode(sample_id, gcode_dir, meta)
                )
        except Exception as e:
            log.debug("[SampleStore] DB trigger_db_gcode 失败（已忽略）: %s", e)

    def trigger_db_scrape_arrays(
        self,
        sample_id: str,
        band_id: str,
        arrays_obj,
        png_path: Path | str | None = None,
        strategy: str | None = None,
    ) -> None:
        """ScrapeArrays 生成后同步 scrape_arrays 表到 DB（v2 主路径、fire-and-forget）。

        调用点：Vision Tab _on_generate_gcode / _regenerate_gcode_preview，
        以及 ScrapeStage._generate_gcode / _generate_gcode_for_band，
        生成 ScrapeArrays + 渲染 PNG 后调一次。
        """
        if self._db is None:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._db.upsert_scrape_arrays(
                        sample_id, band_id, arrays_obj, png_path, strategy,
                    )
                )
        except Exception as e:
            log.debug(
                "[SampleStore] DB trigger_db_scrape_arrays 失败（已忽略）: %s", e,
            )

    def trigger_db_selected_bands(self, sample_id: str, bands: list[str]) -> None:
        """Band 选择变更后同步到 DB（如已注入）。"""
        if self._db is None:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._db.update_selected_bands(sample_id, bands)
                )
        except Exception as e:
            log.debug("[SampleStore] DB trigger_db_selected_bands 失败（已忽略）: %s", e)
