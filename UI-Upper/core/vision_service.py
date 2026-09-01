"""VisionService - 视觉分析服务封装（双帧模式）
=================================
封装 View/pTLC_Viewing/tlc_analyze.py 的 process_pair() 函数。

返回规范：
  analyze()      → VisionResult(x, y, confidence, ok)      简要结果，ScrapeStage 使用
  analyze_full()  → AnalysisResult(bands, summary, ...)      完整结果，Vision Tab 使用

双帧模式（唯一模式）：
  analyze() / analyze_full() 的 before_path 参数为 Optional[Path]。
  before_path 为 None 时返回 ok=False——调用方应通过 SampleStore 确保
  BeforePhotoStage 已捕获 before.jpg，否则视为视觉失败。
  不存在单帧回退路径，双帧是唯一运行模式。

设计约束：
  - process_pair() 是 CPU/IO 密集型操作，通过 executor 异步化，不阻塞事件循环
  - mock_mode=True 时跳过真实分析，返回固定模拟结果（用于无图像环境联调）
"""

import asyncio
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# tlc_analyze 所在目录（相对本文件：../../View/pTLC_Viewing）
_VIEW_DIR = Path(__file__).parent.parent.parent / "View" / "pTLC_Viewing"


@dataclass
class VisionResult:
    """视觉分析简要结果（ScrapeStage 使用）。"""
    x: float           # 质心 x 坐标（cm）
    y: float           # 质心 y 坐标（cm）
    confidence: float  # 置信度（0-1，基于归一化迁移高度）
    ok: bool           # 分析是否成功


@dataclass
class BandInfo:
    """单条 band 的结构化信息。"""
    band_id: str
    is_origin: bool
    centroid_cm: tuple[float, float]           # (x_cm, y_cm)
    bbox_cm: tuple[float, float, float, float] # (x_min, y_min, x_max, y_max)
    vertical_width_cm: float
    horizontal_span_cm: float
    distance_to_origin_cm: float
    normalized_develop_height: float           # Rf 值
    area_cm2: float                            # vertical_width * horizontal_span
    path_json_path: Optional[Path] = None       # band_XX_path.json
    contour_image_path: Optional[Path] = None   # band_XX_contour_path.png
    metrics_image_path: Optional[Path] = None  # band_XX_metrics.png（origin 无）


@dataclass
class AnalysisResult:
    """视觉分析完整结果（Vision Tab 使用）。"""
    ok: bool
    case_name: str
    case_dir: Path                             # 分析输出目录
    summary: dict                              # summary.json 完整内容
    bands: list[BandInfo] = field(default_factory=list)
    annotated_image_path: Optional[Path] = None  # 标注图
    before_image_path: Optional[Path] = None
    after_image_path: Optional[Path] = None


class VisionService:
    """视觉分析服务。

    使用方式：
        svc = VisionService(output_dir=Path("output"), mock_mode=True)
        result = await svc.analyze("sample_001", before_path, after_path)

    参数：
        output_dir     : process_pair 保存图像/JSON 的根目录
        mock_mode      : True → 返回固定模拟结果，跳过真实图像分析
        plate_size_cm  : TLC板尺寸（cm），默认20
        path_step_cm   : 刮取路径步长（cm），默认0.25
        min_row_score  : 行评分阈值，默认5.0
        render_scale   : 输出图像缩放比（服务化场景无需高清，默认1.0）
    """

    def __init__(
        self,
        output_dir: Path,
        mock_mode: bool = False,
        plate_size_cm: float = 20.0,
        path_step_cm: float = 0.25,
        min_row_score: float = 5.0,
        render_scale: float = 1.0,
        mock_fail_rate: float = 0.0,
        image_plate_orientation: str = "rot0",
        auto_rectify_tilt: bool = False,
        rectify_min_angle_deg: float = 0.5,
    ):
        self._output_dir = Path(output_dir)
        self._mock_mode = mock_mode
        self._plate_size_cm = plate_size_cm
        self._path_step_cm = path_step_cm
        self._min_row_score = min_row_score
        self._render_scale = render_scale
        self._mock_fail_rate = mock_fail_rate
        self._image_plate_orientation = image_plate_orientation
        self._auto_rectify_tilt = auto_rectify_tilt
        self._rectify_min_angle_deg = rectify_min_angle_deg

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def with_output_dir(self, output_dir: Path) -> "VisionService":
        """创建使用不同 output_dir 的副本（保留其余参数不变）。

        用于 ScrapeStage 切换到 SampleStore 的 analysis 目录，
        使分析结果与 Vision Tab 的搜索路径一致。
        """
        return VisionService(
            output_dir=output_dir,
            mock_mode=self._mock_mode,
            plate_size_cm=self._plate_size_cm,
            path_step_cm=self._path_step_cm,
            min_row_score=self._min_row_score,
            render_scale=self._render_scale,
            mock_fail_rate=self._mock_fail_rate,
            image_plate_orientation=self._image_plate_orientation,
            auto_rectify_tilt=self._auto_rectify_tilt,
            rectify_min_angle_deg=self._rectify_min_angle_deg,
        )

    async def analyze(
        self,
        sample_id: str,
        before_path: Optional[Path],
        after_path: Path,
    ) -> VisionResult:
        """分析一对前后图像，返回 VisionResult（简要结果，ScrapeStage 使用）。

        双帧模式要求 before_path 和 after_path 同时有效。
        before_path 为 None 时返回 VisionResult(ok=False)——调用方应确保
        BeforePhotoStage 已捕获 before.jpg 并通过 SampleStore 传递。
        不存在单帧回退路径。
        """
        if self._mock_mode:
            # Critical #4: mock_mode 也必须校验 before_path（双帧是唯一模式）
            # before_path 为 None 或无效时返回 ok=False，与真实模式行为一致
            if before_path is None or not Path(before_path).is_file():
                log.warning("[Vision] Mock模式：样品 %s before_path 缺失或无效，返回 ok=False", sample_id)
                return VisionResult(x=0.0, y=0.0, confidence=0.0, ok=False)
            await asyncio.sleep(0.1)  # 模拟分析耗时
            if random.random() < self._mock_fail_rate:
                log.info("[Vision] Mock模式：样品 %s 模拟失败", sample_id)
                return VisionResult(x=0.0, y=0.0, confidence=0.0, ok=False)
            x = 10.0 + random.uniform(-0.5, 0.5)
            y = 8.0 + random.uniform(-0.5, 0.5)
            log.info("[Vision] Mock模式：样品 %s 返回模拟结果 (%.2f, %.2f)", sample_id, x, y)
            return VisionResult(x=x, y=y, confidence=0.95, ok=True)

        # 双帧校验：before_path 为 None 或无效时返回失败（双帧是唯一模式）
        if before_path is None or not Path(before_path).is_file():
            log.warning("[Vision] 样品 %s: before_path 缺失或无效，双帧视觉分析失败", sample_id)
            return VisionResult(x=0.0, y=0.0, confidence=0.0, ok=False)

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self._run_analysis,
                sample_id,
                before_path,
                after_path,
            )
            return result
        except Exception as e:
            log.error("[Vision] 样品 %s 分析异常: %s", sample_id, e, exc_info=True)
            return VisionResult(x=0.0, y=0.0, confidence=0.0, ok=False)

    async def analyze_full(
        self,
        sample_id: str,
        before_path: Optional[Path],
        after_path: Path,
    ) -> AnalysisResult:
        """分析一对前后图像，返回 AnalysisResult（完整结果，Vision Tab 使用）。

        双帧模式要求 before_path 和 after_path 同时有效。
        before_path 为 None 时返回 AnalysisResult(ok=False)——调用方应确保
        BeforePhotoStage 已捕获 before.jpg 并通过 SampleStore 传递。
        不存在单帧回退路径。
        """
        if self._mock_mode:
            # Critical #4: mock_mode 也必须校验 before_path（双帧是唯一模式）
            # before_path 为 None 或无效时返回 ok=False，与真实模式行为一致
            if before_path is None or not Path(before_path).is_file():
                log.warning("[Vision] Mock模式：样品 %s before_path 缺失或无效，返回 ok=False", sample_id)
                return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={})
            await asyncio.sleep(0.1)
            if random.random() < self._mock_fail_rate:
                log.info("[Vision] Mock模式：样品 %s 模拟失败", sample_id)
                return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={})
            # Mock: 生成 3 条非 origin band（数据供UI交互测试，不生成 matplotlib 标注图）
            mock_bands = [
                BandInfo(
                    band_id=f"band_{i:02d}", is_origin=False,
                    centroid_cm=(10.0 + i * 0.1, 5.0 + i * 2.0),
                    bbox_cm=(1.0, 4.0 + i * 2.0, 19.0, 6.0 + i * 2.0),
                    vertical_width_cm=1.5 + i * 0.3,
                    horizontal_span_cm=17.5,
                    distance_to_origin_cm=3.0 + i * 2.0,
                    normalized_develop_height=0.2 + i * 0.15,
                    area_cm2=(1.5 + i * 0.3) * 17.5,
                    path_json_path=None,
                    contour_image_path=None,
                )
                for i in range(1, 4)
            ]
            log.info("[Vision] Mock模式：样品 %s 返回 %d 条模拟 band", sample_id, len(mock_bands))
            return AnalysisResult(
                ok=True, case_name=sample_id,
                case_dir=self._output_dir / sample_id,
                summary={}, bands=mock_bands,
                annotated_image_path=None,
            )

        # 双帧校验：before_path 为 None 或无效时返回失败（双帧是唯一模式）
        if before_path is None or not Path(before_path).is_file():
            log.warning("[Vision] 样品 %s: before_path 缺失或无效，双帧视觉分析失败", sample_id)
            return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={})

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self._run_analysis_full,
                sample_id,
                before_path,
                after_path,
            )
            return result
        except Exception as e:
            log.error("[Vision] 样品 %s analyze_full 异常: %s", sample_id, e, exc_info=True)
            return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={})

    # ------------------------------------------------------------------
    # 内部实现（同步，在 executor 中运行）
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tlc_analyze() -> Any:
        """动态注入 tlc_analyze 所在目录并导入 process_pair。"""
        view_dir_str = str(_VIEW_DIR)
        if view_dir_str not in sys.path:
            sys.path.insert(0, view_dir_str)
        try:
            from tlc_analyze import process_pair  # type: ignore  # noqa: PLC0415
            return process_pair
        except ImportError as e:
            raise RuntimeError(f"无法导入 tlc_analyze，请检查路径 {_VIEW_DIR}: {e}") from e

    def _call_process_pair(
        self,
        sample_id: str,
        before_path: Path,
        after_path: Path,
    ) -> dict:
        """调用 tlc_analyze.process_pair()，返回 summary dict。"""
        process_pair = self._ensure_tlc_analyze()

        before_path = Path(before_path)
        after_path = Path(after_path)
        if not before_path.is_file():
            raise FileNotFoundError(
                f"before 图像不存在或不是文件: {before_path} "
                f"(resolved: {before_path.resolve()})"
            )
        if not after_path.is_file():
            raise FileNotFoundError(
                f"after 图像不存在或不是文件: {after_path} "
                f"(resolved: {after_path.resolve()})"
            )

        return process_pair(
            case_name=sample_id,
            before_path=before_path,
            after_path=after_path,
            output_dir=self._output_dir,
            plate_size_cm=self._plate_size_cm,
            path_step_cm=self._path_step_cm,
            min_row_score=self._min_row_score,
            render_scale=self._render_scale,
            export_pdf=False,
            image_plate_orientation=self._image_plate_orientation,
            auto_rectify_tilt=self._auto_rectify_tilt,
            rectify_min_angle_deg=self._rectify_min_angle_deg,
        )

    def _run_analysis(
        self,
        sample_id: str,
        before_path: Path,
        after_path: Path,
    ) -> VisionResult:
        """同步执行 tlc_analyze.process_pair()，提取第一条条带质心。"""
        summary = self._call_process_pair(sample_id, before_path, after_path)

        # 提取第一条非原点条带的质心坐标
        bands = summary.get("bands", [])
        non_origin = [b for b in bands if not b.get("is_origin", False)]

        if not non_origin:
            log.warning("[Vision] 样品 %s: 未检测到条带，分析失败", sample_id)
            return VisionResult(x=0.0, y=0.0, confidence=0.0, ok=False)

        first = non_origin[0]
        band_metrics = first.get("metrics", {})
        centroid_cm = band_metrics.get("centroid_cm", {})
        x_cm = float(centroid_cm.get("x_cm", 0.0))
        y_cm = float(centroid_cm.get("y_cm", 0.0))

        # 归一化迁移高度作为置信度（范围约 0~1，超出时截断）
        raw_confidence = band_metrics.get("normalized_develop_height") or 0.0
        confidence = float(min(1.0, max(0.0, raw_confidence)))

        log.info(
            "[Vision] 样品 %s: 质心 (%.3f, %.3f) cm，置信度 %.3f",
            sample_id, x_cm, y_cm, confidence,
        )
        return VisionResult(x=x_cm, y=y_cm, confidence=confidence, ok=True)

    def _run_analysis_full(
        self,
        sample_id: str,
        before_path: Path,
        after_path: Path,
    ) -> AnalysisResult:
        """同步执行 tlc_analyze.process_pair()，返回完整 AnalysisResult。"""
        summary = self._call_process_pair(sample_id, before_path, after_path)

        case_dir = self._output_dir / sample_id
        band_infos = self._extract_band_infos(summary, case_dir)

        # 生成全band标注图（基于 after.jpg 原图 + band 矩形框）
        annotated_image = self._generate_annotated_image(sample_id, case_dir, band_infos, after_path)

        result = AnalysisResult(
            ok=True,
            case_name=sample_id,
            case_dir=case_dir,
            summary=summary,
            bands=band_infos,
            annotated_image_path=annotated_image if annotated_image and annotated_image.exists() else None,
            before_image_path=before_path,
            after_image_path=after_path,
        )
        log.info(
            "[Vision] 样品 %s: 分析完成，%d 条 band（含 origin）",
            sample_id, len(band_infos),
        )
        return result

    def _generate_annotated_image(
        self,
        sample_id: str,
        case_dir: Path,
        bands: list[BandInfo],
        after_path: Path,
    ) -> Optional[Path]:
        """基于 after.jpg 原图生成全 band 标注图。

        优先使用 OpenCV 渲染（参考 tlc_analyze.py 的 draw_band_overlay 范式），
        绘制带光晕的 contour 轮廓线 + 刮取路径轨迹 + 质心标记 + 编号标签。
        若 contour 数据不可用则回退到 PIL 矩形框绘制。
        保存为 case_dir/<sample_id>_annotated.png。
        """
        if not after_path.exists():
            log.warning("[Vision] after.jpg 不存在，跳过标注图生成: %s", after_path)
            return None

        if not after_path.is_file():
            log.warning("[Vision] after_path 不是文件，跳过标注图生成: %s (is_file=%s)",
                        after_path, after_path.is_file())
            return None

        # 尝试读取 summary.json 获取 contour/path 像素数据
        summary_path = case_dir / "summary.json"
        summary_data = None
        if summary_path.exists():
            try:
                import json
                summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
                log.info("[Vision] 已加载 summary.json: %s (%d bands)",
                         summary_path, len(summary_data.get("bands", [])))
            except Exception as e:
                log.warning("[Vision] 读取 summary.json 失败: %s (%s)", e, summary_path)
        else:
            log.warning("[Vision] summary.json 不存在: %s，将回退到 PIL 渲染", summary_path)

        # 优先路径：使用 OpenCV 渲染带 contour + path 的标注图
        if summary_data is not None:
            try:
                result_path = self._generate_annotated_image_cv(
                    sample_id, case_dir, bands, after_path, summary_data,
                )
                if result_path is not None:
                    return result_path
                log.warning("[Vision] CV 渲染返回 None，回退到 PIL")
            except Exception as e:
                log.warning("[Vision] CV 渲染异常，回退到 PIL: %s", e, exc_info=True)

        # 回退路径：PIL 简单矩形框
        log.info("[Vision] 使用 PIL 回退渲染标注图")
        return self._generate_annotated_image_pil(
            sample_id, case_dir, bands, after_path,
        )

    def _generate_annotated_image_cv(
        self,
        sample_id: str,
        case_dir: Path,
        bands: list[BandInfo],
        after_path: Path,
        summary_data: dict,
    ) -> Optional[Path]:
        """OpenCV 渲染标注图：contour 轮廓 + 刮取路径 + 质心 + 标签。

        参考 tlc_analyze.py 的 draw_band_overlay 范式，
        利用 process_pair 输出的 contour_px / scrape_path 数据。
        """
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            log.warning("[Vision] cv2/numpy 不可用，回退到 PIL 渲染")
            return None

        img_bgr = cv2.imread(str(after_path), cv2.IMREAD_COLOR)
        if img_bgr is None:
            log.warning("[Vision] 无法读取 after 图像: %s", after_path)
            return None

        # 色彩常量（与 tlc_analyze.py 对齐）
        CONTOUR_MAGENTA = (54, 132, 255)   # BGR
        PATH_CYAN = (236, 216, 0)          # BGR
        CENTROID_WHITE = (245, 245, 245)   # BGR
        OVERLAY_SHADOW = (7, 7, 10)        # BGR
        PLATE_FRAME = (232, 232, 228)      # BGR

        plate_bbox_px = summary_data.get("plate_bbox_px")
        if not plate_bbox_px:
            log.warning("[Vision] summary 中无 plate_bbox_px，回退到 PIL")
            return None

        # 解析 plate 区域
        if isinstance(plate_bbox_px, dict):
            plate_x = plate_bbox_px["x"]
            plate_y = plate_bbox_px["y"]
            plate_w = plate_bbox_px["w"]
            plate_h = plate_bbox_px["h"]
        elif isinstance(plate_bbox_px, (list, tuple)) and len(plate_bbox_px) == 4:
            plate_x, plate_y = plate_bbox_px[0], plate_bbox_px[1]
            plate_w = plate_bbox_px[2] - plate_bbox_px[0]
            plate_h = plate_bbox_px[3] - plate_bbox_px[1]
        else:
            log.warning("[Vision] plate_bbox_px 格式无法解析: %s", type(plate_bbox_px))
            return None

        log.info(
            "[Vision] CV 渲染启动: plate_bbox=(%d,%d,%d,%d), img_size=%s",
            plate_x, plate_y, plate_w, plate_h, img_bgr.shape[:2],
        )

        # 画板框
        cv2.rectangle(
            img_bgr, (plate_x, plate_y),
            (plate_x + plate_w, plate_y + plate_h),
            PLATE_FRAME, 2, lineType=cv2.LINE_AA,
        )

        # 线宽参数
        core = 2
        halo = 4

        # cm → px 转换函数（供 bbox 回退和标签定位使用）
        plate_size_cm = self._plate_size_cm

        def cm_to_px(cx_cm: float, cy_cm: float) -> tuple[int, int]:
            px = int(round(plate_x + (cx_cm / plate_size_cm) * plate_w))
            py = int(round(plate_y + plate_h - (cy_cm / plate_size_cm) * plate_h))
            return px, py

        # 读取各 band 的 contour / path 数据并叠加绘制
        bands_data = summary_data.get("bands", [])
        n_contours_drawn = 0
        n_paths_drawn = 0
        log.info("[Vision] CV 渲染: bands=%d, bands_data=%d, plate_bbox=%s",
                 len(bands), len(bands_data), plate_bbox_px)
        for band_info, band_summary in zip(bands, bands_data):
            path_json_str = band_summary.get("path_json", "")
            contour_px = None
            path_points_px = None

            if path_json_str:
                # Bug fix: path_json 可能是相对路径，优先尝试原始路径，
                # 失败则相对于 case_dir 解析（process_pair 输出路径以 case_dir 为根）
                path_json_path = Path(path_json_str)
                resolved_from = "raw"
                if not path_json_path.is_file():
                    # 回退 1: 在 case_dir 内查找（path_json 可能是 case_dir 下的相对路径）
                    # process_pair 中 contour_dir = case_dir / "task1_task2_contours_paths"
                    # path_json_str 可能是 vision_output/S002/task1_task2_contours_paths/... 或
                    # data/samples/S002/analysis/S002/task1_task2_contours_paths/...
                    # 尝试将 path_json 最后两段拼接在 case_dir 下
                    path_json_path = case_dir / Path(path_json_str).name
                    resolved_from = f"case_dir/{Path(path_json_str).name}"
                if not path_json_path.is_file():
                    # 回退 2: 尝试 case_dir 下的 task1_task2_contours_paths 子目录
                    contour_subdir = case_dir / "task1_task2_contours_paths"
                    path_json_path = contour_subdir / f"{band_info.band_id}_path.json"
                    resolved_from = f"contour_dir/{band_info.band_id}_path.json"
                if not path_json_path.is_file():
                    # 回退 3: case_dir.parent 拼接原始路径（适配旧的 vision_output 结构）
                    path_json_path = case_dir.parent / path_json_str
                    resolved_from = f"case_dir.parent/{path_json_str}"

                if path_json_path.is_file():
                    try:
                        import json as _json
                        path_data = _json.loads(path_json_path.read_text(encoding="utf-8"))
                        # contour_px: [{"x_px": ..., "y_px": ...}, ...]
                        cp = path_data.get("contour_px", [])
                        if cp and isinstance(cp, list) and len(cp) >= 3:
                            contour_px = np.array(
                                [[p["x_px"], p["y_px"]] for p in cp],
                                dtype=np.float32,
                            )
                        # scrape_path.points_px: [{"x_px": ..., "y_px": ...}, ...]
                        sp = path_data.get("scrape_path", {}).get("points_px", [])
                        if sp:
                            path_points_px = np.array(
                                [[p["x_px"], p["y_px"]] for p in sp],
                                dtype=np.int32,
                            )
                        log.debug(
                            "[Vision] band %s: path_json 解析成功 (from=%s, contour=%dpts, path=%dpts)",
                            band_info.band_id, resolved_from,
                            len(contour_px) if contour_px is not None else 0,
                            len(path_points_px) if path_points_px is not None else 0,
                        )
                    except Exception as e:
                        log.warning("[Vision] 读取 path_json 失败: %s (%s)", e, path_json_path)
                else:
                    log.debug(
                        "[Vision] path_json 未找到: raw=%s, tried=%s (resolved_from=%s)",
                        band_summary.get("path_json", ""), path_json_path, resolved_from,
                    )

            # --- 绘制 contour 轮廓（带光晕） ---
            if contour_px is not None and len(contour_px) >= 3:
                pts = np.rint(contour_px).astype(np.int32)
                # halo 层（深色阴影，提升可见度）
                cv2.polylines(
                    img_bgr, [pts], isClosed=True,
                    color=OVERLAY_SHADOW, thickness=halo, lineType=cv2.LINE_AA,
                )
                # core 层（magenta 轮廓线）
                cv2.polylines(
                    img_bgr, [pts], isClosed=True,
                    color=CONTOUR_MAGENTA, thickness=core, lineType=cv2.LINE_AA,
                )
                n_contours_drawn += 1
            else:
                # 回退：用 bbox_cm 转像素坐标画矩形（Bug fix: 之前直接用 cm 值当 px）
                x_min, y_min, x_max, y_max = band_info.bbox_cm
                tl = cm_to_px(x_min, y_max)  # y_max 在图像上方
                br = cm_to_px(x_max, y_min)  # y_min 在图像下方
                cv2.rectangle(img_bgr, tl, br, CONTOUR_MAGENTA, core, lineType=cv2.LINE_AA)
                log.debug(
                    "[Vision] band %s 无 contour 数据，回退 bbox 矩形: (%d,%d)-(%d,%d)",
                    band_info.band_id, tl[0], tl[1], br[0], br[1],
                )

            # --- 绘制刮取路径轨迹（cyan） ---
            if path_points_px is not None and len(path_points_px) >= 2:
                # halo
                cv2.polylines(
                    img_bgr, [path_points_px], isClosed=False,
                    color=OVERLAY_SHADOW, thickness=halo, lineType=cv2.LINE_AA,
                )
                # core
                cv2.polylines(
                    img_bgr, [path_points_px], isClosed=False,
                    color=PATH_CYAN, thickness=core, lineType=cv2.LINE_AA,
                )
                n_paths_drawn += 1
                # 起止点标记
                radius = 3
                cv2.circle(
                    img_bgr, tuple(path_points_px[0]), radius + core,
                    OVERLAY_SHADOW, -1, lineType=cv2.LINE_AA,
                )
                cv2.circle(
                    img_bgr, tuple(path_points_px[0]), radius,
                    (255, 255, 255), -1, lineType=cv2.LINE_AA,
                )
                cv2.circle(
                    img_bgr, tuple(path_points_px[-1]), radius + core,
                    OVERLAY_SHADOW, -1, lineType=cv2.LINE_AA,
                )
                cv2.circle(
                    img_bgr, tuple(path_points_px[-1]), radius,
                    CENTROID_WHITE, -1, lineType=cv2.LINE_AA,
                )

            # --- 绘制质心十字标记 ---
            cx_cm, cy_cm = band_info.centroid_cm
            cx_px, cy_px = cm_to_px(cx_cm, cy_cm)
            marker_size = 8
            cv2.drawMarker(
                img_bgr, (cx_px, cy_px), OVERLAY_SHADOW,
                cv2.MARKER_CROSS, marker_size + halo, halo, line_type=cv2.LINE_AA,
            )
            cv2.drawMarker(
                img_bgr, (cx_px, cy_px), CENTROID_WHITE,
                cv2.MARKER_CROSS, marker_size, core, line_type=cv2.LINE_AA,
            )

            # --- 绘制标签（使用 tlc_analyze.draw_text 范式的简化版） ---
            self._draw_label_cv(
                img_bgr, band_info,
                plate_x, plate_y, plate_w, plate_h,
                self._plate_size_cm,
            )

        output_path = case_dir / f"{sample_id}_annotated.png"
        case_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), img_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 2])
        log.info(
            "[Vision] CV 标注图已生成: %s (contours=%d, paths=%d, total_bands=%d)",
            output_path, n_contours_drawn, n_paths_drawn, len(bands),
        )
        return output_path

    @staticmethod
    def _draw_label_cv(
        canvas,
        band: BandInfo,
        plate_x: int, plate_y: int,
        plate_w: int, plate_h: int,
        plate_size_cm: float,
    ) -> None:
        """在 canvas 上绘制 band 标签（cv2，带背景框）."""
        try:
            import cv2  # type: ignore
        except ImportError:
            return

        # 构建标签文本
        rf_str = f" Rf={band.normalized_develop_height:.3f}" if not band.is_origin else ""
        label = band.band_id + (" (O)" if band.is_origin else "") + rf_str

        # 计算 bbox 左上角像素位置（cm → px）
        x_min, y_min, x_max, y_max = band.bbox_cm
        label_px_x = int(plate_x + (x_min / plate_size_cm) * plate_w)
        label_px_y = int(plate_y + plate_h - (y_max / plate_size_cm) * plate_h) - 5

        # 绘制标签背景 + 文字
        font_scale = 0.5
        thickness = 1
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)
        # 背景
        cv2.rectangle(
            canvas,
            (label_px_x - 2, label_px_y - th - 4),
            (label_px_x + tw + 2, label_px_y + 4),
            (0, 0, 0), -1,
        )
        # 文字
        cv2.putText(
            canvas, label,
            (label_px_x, label_px_y),
            font, font_scale, (244, 244, 238), thickness, cv2.LINE_AA,
        )

    def _generate_annotated_image_pil(
        self,
        sample_id: str,
        case_dir: Path,
        bands: list[BandInfo],
        after_path: Path,
    ) -> Optional[Path]:
        """回退路径：PIL 简单矩形框标注图。"""
        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore
        except ImportError:
            log.warning("[Vision] PIL 不可用，跳过标注图生成")
            return None

        try:
            img = Image.open(after_path).convert("RGB")
        except Exception as e:
            log.warning("[Vision] 无法打开 after.jpg: %s", e)
            return None

        img_w, img_h = img.size
        draw = ImageDraw.Draw(img)
        plate_size_cm = self._plate_size_cm

        # 尝试从 summary.json 读取 plate_bbox_px 做精确映射
        plate_bbox_px = None
        summary_path = case_dir / "summary.json"
        if summary_path.exists():
            try:
                import json
                summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
                plate_bbox_px = summary_data.get("plate_bbox_px")
            except Exception:
                pass

        if plate_bbox_px:
            if isinstance(plate_bbox_px, dict):
                plate_x = plate_bbox_px["x"]
                plate_y = plate_bbox_px["y"]
                plate_w = plate_bbox_px["w"]
                plate_h = plate_bbox_px["h"]
            elif isinstance(plate_bbox_px, (list, tuple)) and len(plate_bbox_px) == 4:
                plate_x, plate_y = plate_bbox_px[0], plate_bbox_px[1]
                plate_w = plate_bbox_px[2] - plate_bbox_px[0]
                plate_h = plate_bbox_px[3] - plate_bbox_px[1]
            else:
                plate_x, plate_y = 0, 0
                plate_w, plate_h = img_w, img_h
        else:
            plate_x, plate_y = 0, 0
            plate_w, plate_h = img_w, img_h

        def cm_to_px(cx_cm: float, cy_cm: float) -> tuple[int, int]:
            px = int(plate_x + (cx_cm / plate_size_cm) * plate_w)
            py = int(plate_y + plate_h - (cy_cm / plate_size_cm) * plate_h)
            return px, py

        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        for band in bands:
            x_min, y_min, x_max, y_max = band.bbox_cm
            tl_px = cm_to_px(x_min, y_max)
            br_px = cm_to_px(x_max, y_min)

            draw.rectangle(
                [tl_px[0], tl_px[1], br_px[0], br_px[1]],
                outline="red", width=2,
            )

            rf_str = f" Rf={band.normalized_develop_height:.3f}" if not band.is_origin else ""
            area_str = f" A={band.area_cm2:.1f}cm²"
            label = band.band_id + (" (O)" if band.is_origin else "") + rf_str + area_str
            text_x = tl_px[0] + 3
            text_y = tl_px[1] + 2
            draw.text((text_x, text_y), label, fill="red", font=font)

        output_path = case_dir / f"{sample_id}_annotated.png"
        case_dir.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        log.info("[Vision] PIL 标注图已生成: %s", output_path)
        return output_path

    @staticmethod
    def _extract_band_infos(summary: dict, case_dir: Path) -> list[BandInfo]:
        """从 summary.json 提取 BandInfo 列表。"""
        bands_data = summary.get("bands", [])
        infos: list[BandInfo] = []
        for b in bands_data:
            metrics = b.get("metrics", {})
            centroid = metrics.get("centroid_cm", {})
            bbox = metrics.get("bbox_cm")  # may not exist in summary

            # 垂直宽度与水平跨度
            v_width = float(metrics.get("vertical_band_width_cm", 0.0))
            h_span = float(metrics.get("horizontal_span_cm", 0.0))
            area = v_width * h_span

            # bbox_cm：从 centroid_cm + vertical_width_cm + horizontal_span_cm 计算
            cx = float(centroid.get("x_cm", 0.0))
            cy = float(centroid.get("y_cm", 0.0))
            hw = h_span / 2
            vh = v_width / 2
            if isinstance(bbox, dict) and bbox:
                # summary 中若已有 bbox_cm 则优先使用
                bbox_cm_val = (
                    float(bbox.get("x_min", 0)),
                    float(bbox.get("y_min", 0)),
                    float(bbox.get("x_max", 0)),
                    float(bbox.get("y_max", 0)),
                )
            else:
                bbox_cm_val = (cx - hw, cy - vh, cx + hw, cy + vh)

            # 路径文件和图像路径
            path_json = Path(b.get("path_json", "")) if b.get("path_json") else None
            contour_img = Path(b.get("contour_path_image", "")) if b.get("contour_path_image") else None
            metrics_img = Path(b.get("metrics_image", "")) if b.get("metrics_image") else None

            infos.append(BandInfo(
                band_id=b.get("band_id", "unknown"),
                is_origin=bool(b.get("is_origin", False)),
                centroid_cm=(
                    float(centroid.get("x_cm", 0.0)),
                    float(centroid.get("y_cm", 0.0)),
                ),
                bbox_cm=bbox_cm_val,
                vertical_width_cm=v_width,
                horizontal_span_cm=h_span,
                distance_to_origin_cm=float(metrics.get("distance_to_origin_cm", 0.0)),
                normalized_develop_height=float(metrics.get("normalized_develop_height", 0.0)),
                area_cm2=area,
                path_json_path=path_json,
                contour_image_path=contour_img,
                metrics_image_path=metrics_img,
            ))
        return infos


# ----------------------------------------------------------------------
# 工厂函数：从 config.yaml vision 段构造 VisionService
# ----------------------------------------------------------------------

def build_vision_from_cfg(vcfg, *, output_dir: Optional[Path] = None) -> "VisionService":
    """从 VisionCfg 构造 VisionService。

    贯通 config.yaml vision 段中的姿态归一化参数（image_plate_orientation /
    auto_rectify_tilt / rectify_min_angle_deg）到所有 VisionService 构造点，
    消除 UI / CLI / stress / pltc-terminal 几个模式下的行为分裂。

    Args:
        vcfg: core.config.VisionCfg 实例，不允许 None。调用方应保证
              配置链路畅通，None 表示配置未被正确注入。
        output_dir: 可选，覆盖 vcfg.output_dir（例如 Vision Tab 需要
                    使用样品级 analysis 目录）。
    """
    if vcfg is None:
        raise ValueError(
            "build_vision_from_cfg: vcfg 为 None，配置注入链路断裂。"
            "请检查 main.py / run_ui 是否将 cfg.vision 透传到 state.vision_cfg。"
        )
    return VisionService(
        output_dir=output_dir if output_dir is not None else vcfg.output_dir,
        mock_mode=vcfg.mock,
        image_plate_orientation=vcfg.image_plate_orientation,
        auto_rectify_tilt=vcfg.auto_rectify_tilt,
        rectify_min_angle_deg=vcfg.rectify_min_angle_deg,
    )
