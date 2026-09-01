"""DatabaseService - SQLite 二级索引层（异步）
==================================================
提供样品数据的结构化存储与查询能力，作为文件系统的补充索引。

设计定位：
  - 文件系统（data/samples/<id>/）保持真相源，图像/G-code 等二进制文件仍在文件系统
  - SQLite 提供结构化查询（样品元数据、分析指标、条带信息、G-code 索引等）
  - 写入失败仅 log.warning，绝不影响主流程（fire-and-forget 语义）

并发安全：
  - 单 asyncio 事件循环 + 单 aiosqlite 连接 + WAL mode
  - 无需连接池或锁（aiosqlite 内部已序列化）

迁移兼容：
  - Schema 基于 database/HostSystem/app/persistance/persist_data.py 的成熟设计
  - 额外预建 event_log 表，供未来日志持久化迁移（SqliteSink）使用
  - 路径统一使用相对项目根的 posix 格式存储
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# 项目根目录（UI-Upper 的父目录 = EIT_Project）
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ======================================================================
# Schema 定义
# ======================================================================

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    data_dir TEXT NOT NULL,
    before_image_path TEXT,
    after_image_path TEXT,
    selected_gcode_path TEXT,
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_selected_bands (
    sample_id TEXT NOT NULL,
    band_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    PRIMARY KEY (sample_id, band_id),
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL UNIQUE,
    summary_path TEXT NOT NULL,
    annotated_image_path TEXT,
    plate_bbox_x INTEGER,
    plate_bbox_y INTEGER,
    plate_bbox_w INTEGER,
    plate_bbox_h INTEGER,
    plate_size_cm REAL,
    render_scale REAL,
    visual_style_scale REAL,
    export_pdf INTEGER,
    background_normalization_json TEXT,
    output_crop_json TEXT,
    origin_band_json TEXT,
    solvent_front_json TEXT,
    raw_summary_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    band_id TEXT NOT NULL,
    is_origin INTEGER NOT NULL,
    contour_image_path TEXT,
    path_json_path TEXT,
    path_point_count INTEGER,
    metrics_image_path TEXT,
    metrics_json_path TEXT,
    centroid_x_px REAL,
    centroid_y_px REAL,
    centroid_x_cm REAL,
    centroid_y_cm REAL,
    bbox_x INTEGER,
    bbox_y INTEGER,
    bbox_w INTEGER,
    bbox_h INTEGER,
    vertical_band_width_cm REAL,
    horizontal_span_cm REAL,
    distance_to_origin_cm REAL,
    normalized_develop_height REAL,
    normalized_develop_width REAL,
    metrics_json TEXT,
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE,
    UNIQUE (sample_id, band_id)
);

CREATE TABLE IF NOT EXISTS band_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    band_id TEXT NOT NULL,
    path_json_path TEXT NOT NULL,
    contour_point_count INTEGER,
    scrape_point_count INTEGER,
    bbox_cm_json TEXT,
    coordinate_system_json TEXT,
    raw_path_json TEXT NOT NULL,
    FOREIGN KEY (sample_id, band_id) REFERENCES bands(sample_id, band_id) ON DELETE CASCADE,
    UNIQUE (sample_id, band_id)
);

CREATE TABLE IF NOT EXISTS scrape_path_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    band_id TEXT NOT NULL,
    point_index INTEGER NOT NULL,
    x_px REAL,
    y_px REAL,
    x_cm REAL,
    y_cm REAL,
    FOREIGN KEY (sample_id, band_id) REFERENCES bands(sample_id, band_id) ON DELETE CASCADE,
    UNIQUE (sample_id, band_id, point_index)
);

CREATE TABLE IF NOT EXISTS gcode_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    path TEXT NOT NULL,
    path_image TEXT,
    band_selection_json TEXT NOT NULL DEFAULT '[]',
    is_selected INTEGER NOT NULL DEFAULT 0,
    line_count INTEGER NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    content TEXT NOT NULL,
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE,
    UNIQUE (sample_id, path)
);

-- v2 (2026-06-07)： ScrapeArrays 主索引。取代 gcode_files 的主路径：
-- Vision Tab 与 ScrapeStage 生成 ScrapeArrays 后直接写入本表;
-- gcode_files 表仅供存量样品与 ingest_samples_to_db.py 调用。
CREATE TABLE IF NOT EXISTS scrape_arrays (
    sample_id TEXT NOT NULL,
    band_id TEXT NOT NULL,
    strategy TEXT,
    num_passes INTEGER,
    total_depth_mm REAL,
    scrape_point_count INTEGER,
    collect_point_count INTEGER,
    scrape_feed INTEGER,
    plunge_feed INTEGER,
    safe_z REAL,
    approach_z REAL,
    plate_surface_z REAL,
    png_path TEXT,
    arrays_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sample_id, band_id),
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS image_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    band_id TEXT,
    image_role TEXT NOT NULL,
    path TEXT NOT NULL,
    source_table TEXT,
    description TEXT,
    FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE,
    UNIQUE (sample_id, band_id, image_role, path)
);

-- 日志表预留（供未来 SqliteSink 使用，本期不写入）
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_bands_sample_id ON bands(sample_id);
CREATE INDEX IF NOT EXISTS idx_gcode_sample_id ON gcode_files(sample_id);
CREATE INDEX IF NOT EXISTS idx_scrape_arrays_sample_id ON scrape_arrays(sample_id);
CREATE INDEX IF NOT EXISTS idx_image_assets_sample_id ON image_assets(sample_id);
CREATE INDEX IF NOT EXISTS idx_image_assets_role ON image_assets(image_role);
CREATE INDEX IF NOT EXISTS idx_event_log_sample_id ON event_log(sample_id);
CREATE INDEX IF NOT EXISTS idx_event_log_ts ON event_log(ts);
"""


# ======================================================================
# 路径工具函数
# ======================================================================


def _rel_path(path: str | Path | None, root: Path | None = None) -> str | None:
    """将路径转为相对项目根的 posix 格式字符串，保证可移植性。"""
    if path is None:
        return None
    root = root or _PROJECT_ROOT
    normalized = Path(str(path).replace("\\", "/"))
    if normalized.is_absolute():
        try:
            return normalized.relative_to(root).as_posix()
        except ValueError:
            return normalized.as_posix()
    return normalized.as_posix()


def _resolve_path(path: str | Path, root: Path | None = None) -> Path:
    """将相对路径转回绝对路径。"""
    root = root or _PROJECT_ROOT
    value = Path(str(path).replace("\\", "/"))
    return value if value.is_absolute() else root / value


def _as_json(value: Any) -> str:
    """将 Python 对象转为紧凑 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _now_iso() -> str:
    """当前 UTC 时间 ISO8601 字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ======================================================================
# DatabaseService
# ======================================================================


class DatabaseService:
    """异步 SQLite 数据库服务（二级索引层）。

    生命周期：
        db = DatabaseService(db_path)
        await db.start()       # 连接 + 建表
        ...                    # upsert / query
        await db.stop()        # 关闭连接
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._conn = None  # aiosqlite.Connection

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def connected(self) -> bool:
        return self._conn is not None

    async def start(self) -> None:
        """连接数据库并执行 schema 建表。幂等。"""
        if self._conn is not None:
            return
        try:
            import aiosqlite
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self._db_path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.executescript(SCHEMA)
            # Phase 5B: 幂等 schema 演进 — 添加 deleted_at 列（软删除）
            try:
                await self._conn.execute(
                    "ALTER TABLE samples ADD COLUMN deleted_at TEXT"
                )
                await self._conn.commit()
                log.info("[Database] schema 演进: 已添加 samples.deleted_at 列")
            except Exception:
                # 列已存在 → 忽略（SQLite 无 IF NOT EXISTS 语法用于 ALTER）
                pass
            await self._conn.commit()
            log.info("[Database] 已连接: %s", self._db_path)
        except Exception as e:
            log.error("[Database] 启动失败: %s", e)
            self._conn = None
            raise

    async def stop(self) -> None:
        """关闭数据库连接。幂等。"""
        if self._conn is None:
            return
        try:
            await self._conn.close()
        except Exception as e:
            log.warning("[Database] 关闭异常: %s", e)
        finally:
            self._conn = None
            log.info("[Database] 已关闭")

    # ==================================================================
    # 写入接口
    # ==================================================================

    async def upsert_sample(
        self, sample_id: str, metadata: dict, sample_dir: Path
    ) -> None:
        """写入/更新样品主记录。"""
        if self._conn is None:
            return
        try:
            before_path = _rel_path(metadata.get("before_image") or sample_dir / "before.jpg")
            after_path = _rel_path(metadata.get("after_image") or sample_dir / "after.jpg")
            selected_gcode = _rel_path(metadata.get("gcode_path"))

            # DELETE + INSERT 保证幂等（级联删除子表）
            await self._conn.execute(
                "DELETE FROM samples WHERE sample_id = ?", (sample_id,)
            )
            await self._conn.execute(
                """INSERT INTO samples (
                    sample_id, data_dir, before_image_path, after_image_path,
                    selected_gcode_path, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sample_id,
                    _rel_path(sample_dir),
                    before_path,
                    after_path,
                    selected_gcode,
                    metadata.get("created_at"),
                    metadata.get("updated_at"),
                    _as_json(metadata),
                ),
            )
            # 插入 selected_bands
            selected_bands = metadata.get("selected_bands", [])
            for idx, band_id in enumerate(selected_bands):
                await self._conn.execute(
                    """INSERT OR IGNORE INTO sample_selected_bands
                       (sample_id, band_id, sort_order) VALUES (?, ?, ?)""",
                    (sample_id, band_id, idx),
                )
            # 登记图片资产
            await self._insert_image_asset(
                sample_id, None, "sample_before", before_path,
                "samples", "TLC plate image before development.",
            )
            await self._insert_image_asset(
                sample_id, None, "sample_after", after_path,
                "samples", "TLC plate image after development.",
            )
            await self._conn.commit()
            log.debug("[Database] upsert_sample: %s", sample_id)
        except Exception as e:
            log.warning("[Database] upsert_sample 失败 (%s): %s", sample_id, e)

    async def upsert_analysis(
        self, sample_id: str, summary: dict, summary_path: Path
    ) -> None:
        """写入/更新分析结果。"""
        if self._conn is None:
            return
        try:
            plate_bbox = summary.get("plate_bbox_px", {})
            annotated_path = summary_path.parent / f"{sample_id}_annotated.png"

            # 先删除旧分析记录
            await self._conn.execute(
                "DELETE FROM analyses WHERE sample_id = ?", (sample_id,)
            )
            await self._conn.execute(
                """INSERT INTO analyses (
                    sample_id, summary_path, annotated_image_path,
                    plate_bbox_x, plate_bbox_y, plate_bbox_w, plate_bbox_h,
                    plate_size_cm, render_scale, visual_style_scale, export_pdf,
                    background_normalization_json, output_crop_json,
                    origin_band_json, solvent_front_json,
                    raw_summary_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sample_id,
                    _rel_path(summary_path),
                    _rel_path(annotated_path) if annotated_path.exists() else None,
                    plate_bbox.get("x"),
                    plate_bbox.get("y"),
                    plate_bbox.get("w"),
                    plate_bbox.get("h"),
                    summary.get("plate_size_cm"),
                    summary.get("render_scale"),
                    summary.get("visual_style_scale"),
                    int(bool(summary.get("export_pdf"))),
                    _as_json(summary.get("background_normalization")),
                    _as_json(summary.get("output_crop")),
                    _as_json(summary.get("origin_band")),
                    _as_json(summary.get("solvent_front")),
                    _as_json(summary),
                    _now_iso(),
                ),
            )
            if annotated_path.exists():
                await self._insert_image_asset(
                    sample_id, None, "analysis_annotated",
                    _rel_path(annotated_path), "analyses",
                    "Annotated TLC analysis result image.",
                )
            await self._conn.commit()
            log.debug("[Database] upsert_analysis: %s", sample_id)
        except Exception as e:
            log.warning("[Database] upsert_analysis 失败 (%s): %s", sample_id, e)

    async def upsert_bands(self, sample_id: str, bands: list[dict]) -> None:
        """写入/更新条带信息（含 band_paths 和 scrape_path_points）。"""
        if self._conn is None:
            return
        try:
            # 清除旧 bands 数据（级联删除 band_paths, scrape_path_points）
            await self._conn.execute(
                "DELETE FROM bands WHERE sample_id = ?", (sample_id,)
            )
            for band in bands:
                metrics = band.get("metrics") or {}
                centroid_px = metrics.get("centroid_px", {})
                centroid_cm = metrics.get("centroid_cm", {})
                bbox = metrics.get("bbox_px_roi", {})

                await self._conn.execute(
                    """INSERT INTO bands (
                        sample_id, band_id, is_origin, contour_image_path,
                        path_json_path, path_point_count, metrics_image_path,
                        metrics_json_path, centroid_x_px, centroid_y_px,
                        centroid_x_cm, centroid_y_cm, bbox_x, bbox_y, bbox_w, bbox_h,
                        vertical_band_width_cm, horizontal_span_cm,
                        distance_to_origin_cm, normalized_develop_height,
                        normalized_develop_width, metrics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sample_id,
                        band["band_id"],
                        int(bool(band.get("is_origin"))),
                        _rel_path(band.get("contour_path_image")),
                        _rel_path(band.get("path_json")),
                        band.get("path_point_count"),
                        _rel_path(band.get("metrics_image")),
                        _rel_path(band.get("metrics_json")),
                        centroid_px.get("x_px"),
                        centroid_px.get("y_px"),
                        centroid_cm.get("x_cm"),
                        centroid_cm.get("y_cm"),
                        bbox.get("x"),
                        bbox.get("y"),
                        bbox.get("w"),
                        bbox.get("h"),
                        metrics.get("vertical_band_width_cm"),
                        metrics.get("horizontal_span_cm"),
                        metrics.get("distance_to_origin_cm"),
                        metrics.get("normalized_develop_height"),
                        metrics.get("normalized_develop_width"),
                        _as_json(metrics) if metrics else None,
                    ),
                )
                # 登记条带图片资产
                await self._insert_image_asset(
                    sample_id, band["band_id"], "band_contour_path",
                    band.get("contour_path_image"), "bands",
                    "Band contour and scrape path visualization.",
                )
                await self._insert_image_asset(
                    sample_id, band["band_id"], "band_metrics",
                    band.get("metrics_image"), "bands",
                    "Band metrics visualization.",
                )
                # 插入 band_paths 和 scrape_path_points
                if band.get("path_json"):
                    await self._insert_band_path(
                        sample_id, band["band_id"], band["path_json"]
                    )

            await self._conn.commit()
            log.debug("[Database] upsert_bands: %s (%d bands)", sample_id, len(bands))
        except Exception as e:
            log.warning("[Database] upsert_bands 失败 (%s): %s", sample_id, e)

    async def upsert_gcode(
        self, sample_id: str, gcode_dir: Path, metadata: dict
    ) -> None:
        """导入正式 G-code 文件（gcode/ 目录下的 *.gcode）。"""
        if self._conn is None:
            return
        try:
            if not gcode_dir.exists():
                return
            # 清除旧 gcode 记录
            await self._conn.execute(
                "DELETE FROM gcode_files WHERE sample_id = ?", (sample_id,)
            )
            selected_gcode = _rel_path(metadata.get("gcode_path"))

            for path in sorted(gcode_dir.glob("*.gcode")):
                content = path.read_text(encoding="utf-8-sig", errors="replace")
                band_selection = self._parse_band_selection(sample_id, path)
                image_path = self._find_gcode_path_image(path)
                path_rel = _rel_path(path)

                await self._conn.execute(
                    """INSERT INTO gcode_files (
                        sample_id, path, path_image, band_selection_json,
                        is_selected, line_count, file_size_bytes, content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sample_id,
                        path_rel,
                        _rel_path(image_path) if image_path else None,
                        _as_json(band_selection),
                        int(path_rel == selected_gcode),
                        len(content.splitlines()),
                        path.stat().st_size,
                        content,
                    ),
                )
                await self._insert_image_asset(
                    sample_id, None, "gcode_path_preview",
                    image_path, "gcode_files",
                    f"Path preview image for {path.name}.",
                )

            await self._conn.commit()
            log.debug("[Database] upsert_gcode: %s", sample_id)
        except Exception as e:
            log.warning("[Database] upsert_gcode 失败 (%s): %s", sample_id, e)

    async def upsert_scrape_arrays(
        self,
        sample_id: str,
        band_id: str,
        arrays_obj: Any,
        png_path: Path | str | None = None,
        strategy: Optional[str] = None,
    ) -> None:
        """写入 / 更新 ScrapeArrays 记录（v2 主路径）。

        取代 upsert_gcode：ScrapeArrays 是 PLC 实际消费的点位数组，本函数将其双轨
        落库（1）索引字段供 List/Filter；（2）完整 as_plc_dict() JSON 供零损回放。
        DELETE+INSERT 模式保证幂等，按 (sample_id, band_id) 主键覆盖。

        失败仅 log.warning，不抛异常（fire-and-forget）。
        """
        if self._conn is None:
            return
        try:
            arr_dict = (
                arrays_obj.as_plc_dict() if hasattr(arrays_obj, "as_plc_dict")
                else dict(arrays_obj)
            )
            await self._conn.execute(
                "DELETE FROM scrape_arrays WHERE sample_id = ? AND band_id = ?",
                (sample_id, band_id),
            )
            await self._conn.execute(
                """INSERT INTO scrape_arrays (
                    sample_id, band_id, strategy, num_passes, total_depth_mm,
                    scrape_point_count, collect_point_count, scrape_feed, plunge_feed,
                    safe_z, approach_z, plate_surface_z, png_path,
                    arrays_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sample_id,
                    band_id,
                    strategy,
                    int(arr_dict.get("g_pass_count", 0) or 0),
                    float(arr_dict.get("g_total_depth", 0.0) or 0.0),
                    len(arr_dict.get("g_sx", []) or []),
                    len(arr_dict.get("g_cx", []) or []),
                    int(arr_dict.get("g_scrape_feed", 0) or 0),
                    int(arr_dict.get("g_plunge_feed", 0) or 0),
                    float(arr_dict.get("g_safe_z", 0.0) or 0.0),
                    float(arr_dict.get("g_approach_z", 0.0) or 0.0),
                    float(arr_dict.get("g_plate_surface_z", 0.0) or 0.0),
                    _rel_path(png_path),
                    _as_json(arr_dict),
                    _now_iso(),
                ),
            )
            # 同步登记 PNG 预览资产
            if png_path is not None:
                await self._insert_image_asset(
                    sample_id, band_id, "scrape_arrays_preview",
                    _rel_path(png_path), "scrape_arrays",
                    f"ScrapeArrays path preview for band {band_id}.",
                )
            await self._conn.commit()
            log.debug("[Database] upsert_scrape_arrays: %s/%s", sample_id, band_id)
        except Exception as e:
            log.warning(
                "[Database] upsert_scrape_arrays 失败 (%s/%s): %s",
                sample_id, band_id, e,
            )

    async def update_selected_bands(
        self, sample_id: str, bands: list[str]
    ) -> None:
        """更新样品选中的条带列表。"""
        if self._conn is None:
            return
        try:
            await self._conn.execute(
                "DELETE FROM sample_selected_bands WHERE sample_id = ?",
                (sample_id,),
            )
            for idx, band_id in enumerate(bands):
                await self._conn.execute(
                    """INSERT INTO sample_selected_bands
                       (sample_id, band_id, sort_order) VALUES (?, ?, ?)""",
                    (sample_id, band_id, idx),
                )
            # 同步更新 samples 表的 metadata_json 中 selected_bands
            row = await self._conn.execute(
                "SELECT metadata_json FROM samples WHERE sample_id = ?",
                (sample_id,),
            )
            existing = await row.fetchone()
            if existing:
                meta = json.loads(existing[0])
                meta["selected_bands"] = bands
                meta["updated_at"] = datetime.now().isoformat()
                await self._conn.execute(
                    "UPDATE samples SET metadata_json = ?, updated_at = ? WHERE sample_id = ?",
                    (_as_json(meta), meta["updated_at"], sample_id),
                )
            await self._conn.commit()
            log.debug("[Database] update_selected_bands: %s → %s", sample_id, bands)
        except Exception as e:
            log.warning("[Database] update_selected_bands 失败 (%s): %s", sample_id, e)

    # ==================================================================
    # 查询接口
    # ==================================================================

    async def get_sample(self, sample_id: str) -> Optional[dict]:
        """查询单个样品记录。"""
        if self._conn is None:
            return None
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            log.warning("[Database] get_sample 失败 (%s): %s", sample_id, e)
            return None

    async def list_samples(
        self, filter: Optional[dict] = None, *, include_deleted: bool = False
    ) -> list[dict]:
        """列出样品记录。

        可选 filter 字段：
          - recipe_name: str  精确匹配 metadata_json.recipe_name
          - date_from / date_to: str  ISO8601 区间，匹配 created_at
          - id_substring: str  sample_id 子串匹配（LIKE %x%）

        include_deleted=False（默认）时过滤软删除记录。
        无 filter 或空 dict 时等价于全表扫描，按 created_at DESC 排序，
        缺失 created_at 的旧记录排在最后。
        """
        if self._conn is None:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            f = filter or {}
            # Phase 5B: 默认过滤软删除记录
            if not include_deleted:
                clauses.append("(deleted_at IS NULL OR deleted_at = '')")
            recipe_name = f.get("recipe_name")
            if recipe_name:
                clauses.append(
                    "json_extract(metadata_json, '$.recipe_name') = ?"
                )
                params.append(recipe_name)
            date_from = f.get("date_from")
            if date_from:
                clauses.append("COALESCE(created_at, '') >= ?")
                params.append(date_from)
            date_to = f.get("date_to")
            if date_to:
                clauses.append("COALESCE(created_at, '') <= ?")
                params.append(date_to)
            id_substring = f.get("id_substring")
            if id_substring:
                clauses.append("sample_id LIKE ?")
                params.append(f"%{id_substring}%")
            sql = "SELECT * FROM samples"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            # 缺 created_at 的旧记录排末尾（NULL 在 SQLite 中默认排前）
            sql += (
                " ORDER BY CASE WHEN created_at IS NULL OR created_at = '' "
                "THEN 1 ELSE 0 END, created_at DESC, sample_id"
            )
            cursor = await self._conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[Database] list_samples 失败: %s", e)
            return []

    async def list_recipes_used(self) -> list[str]:
        """返回 DB 中出现过的所有 recipe_name（DISTINCT，按字典序）。

        从 samples.metadata_json 中提取 $.recipe_name；空字符串/NULL 自动剔除。
        """
        if self._conn is None:
            return []
        try:
            # SQL 别名 r 不可在 WHERE 中使用（SQLite 执行顺序：FROM→WHERE→SELECT），
            # 故 WHERE 中重复 json_extract 表达式；ORDER BY 阶段别名已可见。
            # 同时排除已软删样品（deleted_at IS NOT NULL），与 list_samples 默认口径对齐。
            cursor = await self._conn.execute(
                "SELECT DISTINCT json_extract(metadata_json, '$.recipe_name') AS r "
                "FROM samples "
                "WHERE deleted_at IS NULL "
                "  AND json_extract(metadata_json, '$.recipe_name') IS NOT NULL "
                "  AND json_extract(metadata_json, '$.recipe_name') != '' "
                "ORDER BY r"
            )
            rows = await cursor.fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception as e:
            log.warning("[Database] list_recipes_used 失败: %s", e)
            return []

    async def get_statistics(self) -> dict:
        """获取仪表盘统计数据（4 项）。

        返回字段（DB 未连接时全部归零，不抛异常）：
          - total_samples: int   全部样品数（含 metadata 缺失的旧记录）
          - today_samples: int   今日新增样品数（按 created_at 当地时区 date() 匹配）
          - total_bands:   int   全部条带数（bands 表行数）
          - top_recipe:    Optional[tuple[str, int]]  使用频次第一的配方 (name, count)；
                                                     无任何带 recipe_name 的样品时为 None
        """
        empty = {
            "total_samples": 0,
            "today_samples": 0,
            "total_bands": 0,
            "top_recipe": None,
        }
        if self._conn is None:
            return empty
        try:
            # 全部统计均排除已软删样品（deleted_at IS NOT NULL），
            # 与 list_samples 默认口径一致，避免 Dashboard 与 History Tab 显示口径漂移。
            cur = await self._conn.execute(
                "SELECT COUNT(*) FROM samples WHERE deleted_at IS NULL"
            )
            row = await cur.fetchone()
            total_samples = int(row[0]) if row else 0

            cur = await self._conn.execute(
                "SELECT COUNT(*) FROM samples "
                "WHERE deleted_at IS NULL "
                "  AND date(created_at) = date('now', 'localtime')"
            )
            row = await cur.fetchone()
            today_samples = int(row[0]) if row else 0

            # bands 表无 deleted_at 字段，通过 IN 子查询排除已软删样品的 bands。
            cur = await self._conn.execute(
                "SELECT COUNT(*) FROM bands "
                "WHERE sample_id IN (SELECT sample_id FROM samples WHERE deleted_at IS NULL)"
            )
            row = await cur.fetchone()
            total_bands = int(row[0]) if row else 0

            # SQL 别名 r 不可在 WHERE 中使用，WHERE 内重复 json_extract 表达式。
            cur = await self._conn.execute(
                "SELECT json_extract(metadata_json, '$.recipe_name') AS r, "
                "       COUNT(*) AS c "
                "FROM samples "
                "WHERE deleted_at IS NULL "
                "  AND json_extract(metadata_json, '$.recipe_name') IS NOT NULL "
                "  AND json_extract(metadata_json, '$.recipe_name') != '' "
                "GROUP BY r ORDER BY c DESC, r LIMIT 1"
            )
            row = await cur.fetchone()
            top_recipe = (row[0], int(row[1])) if row else None

            return {
                "total_samples": total_samples,
                "today_samples": today_samples,
                "total_bands": total_bands,
                "top_recipe": top_recipe,
            }
        except Exception as e:
            log.warning("[Database] get_statistics 失败: %s", e)
            return empty

    async def get_bands(self, sample_id: str) -> list[dict]:
        """查询样品的所有条带信息。"""
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM bands WHERE sample_id = ? ORDER BY band_id",
                (sample_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[Database] get_bands 失败 (%s): %s", sample_id, e)
            return []

    async def get_scrape_path_points(
        self, sample_id: str, band_id: str
    ) -> list[dict]:
        """查询指定条带的刮取路径点。"""
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                """SELECT point_index, x_px, y_px, x_cm, y_cm
                   FROM scrape_path_points
                   WHERE sample_id = ? AND band_id = ?
                   ORDER BY point_index""",
                (sample_id, band_id),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[Database] get_scrape_path_points 失败 (%s/%s): %s",
                        sample_id, band_id, e)
            return []

    async def get_gcode_files(self, sample_id: str) -> list[dict]:
        """查询样品的所有 G-code 文件（存量样品兼容渠道）。"""
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM gcode_files WHERE sample_id = ? ORDER BY path",
                (sample_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[Database] get_gcode_files 失败 (%s): %s", sample_id, e)
            return []

    async def get_scrape_arrays(self, sample_id: str) -> list[dict]:
        """查询样品的所有 ScrapeArrays 记录（v2 主路径）。

        返回列表依 band_id 排序。每条含 arrays_json （完整 PLC 参数）与
        总结字段（strategy/num_passes/png_path 等）。调用者遇到列表为
        空可回退查询 get_gcode_files 处理存量样品。
        """
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM scrape_arrays WHERE sample_id = ? ORDER BY band_id",
                (sample_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning(
                "[Database] get_scrape_arrays 失败 (%s): %s", sample_id, e,
            )
            return []

    async def get_selected_gcode(self, sample_id: str) -> Optional[dict]:
        """查询当前选中的正式 G-code。"""
        if self._conn is None:
            return None
        try:
            cursor = await self._conn.execute(
                """SELECT * FROM gcode_files
                   WHERE sample_id = ? AND is_selected = 1""",
                (sample_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            log.warning("[Database] get_selected_gcode 失败 (%s): %s", sample_id, e)
            return None

    async def get_image_assets(self, sample_id: str) -> list[dict]:
        """查询样品的所有图片资源索引。"""
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                """SELECT * FROM image_assets
                   WHERE sample_id = ?
                   ORDER BY image_role, band_id, path""",
                (sample_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[Database] get_image_assets 失败 (%s): %s", sample_id, e)
            return []

    async def get_selected_bands(self, sample_id: str) -> list[str]:
        """查询样品选中的条带 ID 列表（按 sort_order 排序）。"""
        if self._conn is None:
            return []
        try:
            cursor = await self._conn.execute(
                """SELECT band_id FROM sample_selected_bands
                   WHERE sample_id = ? ORDER BY sort_order""",
                (sample_id,),
            )
            rows = await cursor.fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            log.warning("[Database] get_selected_bands 失败 (%s): %s", sample_id, e)
            return []

    # ==================================================================
    # 内部辅助方法
    # ==================================================================

    async def _insert_image_asset(
        self,
        sample_id: str,
        band_id: str | None,
        image_role: str,
        path: str | Path | None,
        source_table: str,
        description: str,
    ) -> None:
        """登记图片资源到 image_assets 表。"""
        path_rel = _rel_path(path)
        if not path_rel:
            return
        await self._conn.execute(
            """INSERT OR IGNORE INTO image_assets (
                sample_id, band_id, image_role, path, source_table, description
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (sample_id, band_id, image_role, path_rel, source_table, description),
        )

    async def _insert_band_path(
        self, sample_id: str, band_id: str, path_json: str
    ) -> None:
        """读取 band path JSON 并写入 band_paths + scrape_path_points。"""
        path = _resolve_path(path_json)
        if not path.is_file():
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        scrape_path = payload.get("scrape_path") or {}
        points_px = scrape_path.get("points_px") or []
        points_cm = scrape_path.get("points_cm") or []
        scrape_count = max(len(points_px), len(points_cm))

        await self._conn.execute(
            """INSERT OR REPLACE INTO band_paths (
                sample_id, band_id, path_json_path, contour_point_count,
                scrape_point_count, bbox_cm_json, coordinate_system_json,
                raw_path_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sample_id,
                band_id,
                _rel_path(path_json),
                len(payload.get("contour_px") or []),
                scrape_count,
                _as_json(scrape_path.get("bbox_cm")),
                _as_json(payload.get("coordinate_system")),
                _as_json(payload),
            ),
        )

        # 批量插入刮取路径点
        for index in range(scrape_count):
            px = points_px[index] if index < len(points_px) else {}
            cm = points_cm[index] if index < len(points_cm) else {}
            await self._conn.execute(
                """INSERT OR REPLACE INTO scrape_path_points (
                    sample_id, band_id, point_index, x_px, y_px, x_cm, y_cm
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    sample_id,
                    band_id,
                    index,
                    px.get("x_px"),
                    px.get("y_px"),
                    cm.get("x_cm"),
                    cm.get("y_cm"),
                ),
            )

    @staticmethod
    def _parse_band_selection(sample_id: str, path: Path) -> list[str]:
        """从 G-code 文件名解析对应条带（如 S1_band_01_band_04.gcode → ["band_01","band_04"]）。"""
        prefix = f"{sample_id}_"
        stem = path.stem
        if not stem.startswith(prefix):
            return []
        tokens = stem[len(prefix):].split("_")
        bands = []
        index = 0
        while index < len(tokens) - 1:
            if tokens[index] == "band":
                bands.append(f"band_{tokens[index + 1]}")
                index += 2
            else:
                index += 1
        return bands

    @staticmethod
    def _find_gcode_path_image(gcode_path: Path) -> Path | None:
        """查找 G-code 对应的路径示意图。"""
        image_path = gcode_path.with_name(f"{gcode_path.stem}_path.png")
        return image_path if image_path.exists() else None

    # ------------------------------------------------------------------
    # Phase 5B/5C: 软删除 / 还原 / 硬删除
    # ------------------------------------------------------------------

    async def soft_delete_sample(self, sample_id: str) -> None:
        """软删除样品：设置 deleted_at 时间戳。"""
        if self._conn is None:
            return
        try:
            await self._conn.execute(
                "UPDATE samples SET deleted_at = CURRENT_TIMESTAMP WHERE sample_id = ?",
                (sample_id,),
            )
            await self._conn.commit()
            log.info("[Database] soft_delete_sample: %s", sample_id)
        except Exception as e:
            log.warning("[Database] soft_delete_sample 失败 (%s): %s", sample_id, e)

    async def restore_sample(self, sample_id: str) -> None:
        """还原软删除样品：清除 deleted_at。"""
        if self._conn is None:
            return
        try:
            await self._conn.execute(
                "UPDATE samples SET deleted_at = NULL WHERE sample_id = ?",
                (sample_id,),
            )
            await self._conn.commit()
            log.info("[Database] restore_sample: %s", sample_id)
        except Exception as e:
            log.warning("[Database] restore_sample 失败 (%s): %s", sample_id, e)

    async def hard_delete_sample(self, sample_id: str) -> None:
        """硬删除样品：从 DB 中永久删除主表 + 子表（FK 级联）。

        注意：文件系统删除由调用者上层负责（保证顺序：先 DB 后 fs）。
        """
        if self._conn is None:
            return
        try:
            await self._conn.execute(
                "DELETE FROM samples WHERE sample_id = ?",
                (sample_id,),
            )
            await self._conn.commit()
            log.info("[Database] hard_delete_sample: %s", sample_id)
        except Exception as e:
            log.warning("[Database] hard_delete_sample 失败 (%s): %s", sample_id, e)
            raise

    async def get_sample_disk_info(self, sample_id: str) -> dict:
        """获取样品在 DB 中的子表记录数（供硬删前预览用）。"""
        info = {"db_records": 0}
        if self._conn is None:
            return info
        try:
            tables = [
                "sample_selected_bands", "analyses", "bands",
                "band_paths", "scrape_path_points", "gcode_files",
                "scrape_arrays", "image_assets",
            ]
            total = 0
            for tbl in tables:
                cur = await self._conn.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE sample_id = ?",
                    (sample_id,),
                )
                row = await cur.fetchone()
                total += (row[0] if row else 0)
            info["db_records"] = total
        except Exception as e:
            log.debug("[Database] get_sample_disk_info 异常: %s", e)
        return info
