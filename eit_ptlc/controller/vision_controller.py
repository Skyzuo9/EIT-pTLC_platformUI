"""VisionService - 视觉分析服务封装（双帧模式）
=================================
封装 View/pTLC_Viewing/tlc_analyze.py 的 process_pair() 函数。

返回规范：
  analyze()      → VisionResult(x, y, rf, ok)      简要结果，ScrapeStage 使用
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
import json
import logging
import random
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from eit_ptlc.controller import plate_coords

log = logging.getLogger(__name__)

# tlc_analyze 所在目录（相对本文件：../../View/pTLC_Viewing）
_VIEW_DIR = Path(__file__).parent.parent.parent / "View" / "pTLC_Viewing"

_UNSET: Any = object()  # analyze_action rotation 的"未提供"哨兵 (None 是合法值=每帧自动估, 不能用 None 当缺省)


@dataclass
class VisionResult:
    """视觉分析简要结果（ScrapeStage 使用）。"""
    x: float           # 质心 x 坐标（cm）
    y: float           # 质心 y 坐标（cm）
    rf: float  # Rf 值（归一化迁移高度）
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
    """视觉分析完整结果（Vision Tab 使用）。

    reason 把过去 collapse 成单一 ok=False 的三种失败区分开, 供 operation VM 分支:
      - "ok"             : 分析成功 (至少 1 条非原点条带)
      - "no_bands"       : 分析跑通但未检出任何非原点条带 (非致命, 人工可选跳过刮板)
      - "before_invalid" : before 图缺失/无效 (双帧必需, 人工可补拍)
      - "analyze_error"  : tlc_analyze 内部异常 / summary.ok=False (人工可重拍)
    """
    ok: bool
    case_name: str
    case_dir: Path                             # 分析输出目录
    summary: dict                              # summary.json 完整内容
    reason: str = "ok"                         # ok|no_bands|before_invalid|analyze_error
    message: str = ""                          # 失败时的人类可读说明
    bands: list[BandInfo] = field(default_factory=list)
    annotated_image_path: Optional[Path] = None  # 标注图
    before_image_path: Optional[Path] = None
    after_image_path: Optional[Path] = None


def _band_display(band) -> dict[str, Any]:
    """把 BandInfo 摊平为门/中控/调试台面板可读的显示 dict (analyze_action.bands 字段用)。"""
    return {
        "band_id": band.band_id,
        "is_origin": band.is_origin,
        "centroid_cm": list(band.centroid_cm) if band.centroid_cm is not None else None,
        "normalized_develop_height": band.normalized_develop_height,
        "vertical_width_cm": band.vertical_width_cm,
        "horizontal_span_cm": band.horizontal_span_cm,
        "area_cm2": band.area_cm2,
        "distance_to_origin_cm": band.distance_to_origin_cm,
    }


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
        image_plate_rotation_deg: Optional[float] = None,
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
        self._image_plate_rotation_deg = image_plate_rotation_deg

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def with_output_dir(self, output_dir: Path) -> "VisionService":
        """创建使用不同 output_dir 的副本（保留其余参数不变）。

        用于 ScrapeStage 切换到 SampleStore 的 analysis 目录，
        使分析结果与 Vision Tab 的搜索路径一致。
        """
        return self.with_overrides(output_dir=output_dir)

    def with_overrides(
        self,
        output_dir: Optional[Path] = None,
        overrides: Optional[dict[str, Any]] = None,
    ) -> "VisionService":
        """创建带临时识别参数覆盖的 VisionService 副本。

        调试台可用这个公开接口复用同一条 process_pair() 算法路径，
        不需要读取 _mock_mode / _plate_size_cm 等私有字段。
        """
        allowed = {
            "plate_size_cm",
            "path_step_cm",
            "min_row_score",
            "render_scale",
            "image_plate_orientation",
            "auto_rectify_tilt",
            "rectify_min_angle_deg",
            "image_plate_rotation_deg",
        }
        overrides = dict(overrides or {})
        unknown = sorted(set(overrides) - allowed)
        if unknown:
            raise ValueError(f"VisionService.with_overrides 不支持的参数: {unknown}")

        return VisionService(
            output_dir=output_dir if output_dir is not None else self._output_dir,
            mock_mode=self._mock_mode,
            plate_size_cm=float(overrides.get("plate_size_cm", self._plate_size_cm)),
            path_step_cm=float(overrides.get("path_step_cm", self._path_step_cm)),
            min_row_score=float(overrides.get("min_row_score", self._min_row_score)),
            render_scale=float(overrides.get("render_scale", self._render_scale)),
            mock_fail_rate=self._mock_fail_rate,
            image_plate_orientation=str(overrides.get("image_plate_orientation", self._image_plate_orientation)),
            auto_rectify_tilt=bool(overrides.get("auto_rectify_tilt", self._auto_rectify_tilt)),
            rectify_min_angle_deg=float(overrides.get("rectify_min_angle_deg", self._rectify_min_angle_deg)),
            image_plate_rotation_deg=overrides.get("image_plate_rotation_deg", self._image_plate_rotation_deg),
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
                return VisionResult(x=0.0, y=0.0, rf=0.0, ok=False)
            await asyncio.sleep(0.1)  # 模拟分析耗时
            if random.random() < self._mock_fail_rate:
                log.info("[Vision] Mock模式：样品 %s 模拟失败", sample_id)
                return VisionResult(x=0.0, y=0.0, rf=0.0, ok=False)
            x = 10.0 + random.uniform(-0.5, 0.5)
            y = 8.0 + random.uniform(-0.5, 0.5)
            log.info("[Vision] Mock模式：样品 %s 返回模拟结果 (%.2f, %.2f)", sample_id, x, y)
            return VisionResult(x=x, y=y, rf=0.95, ok=True)

        # 双帧校验：before_path 为 None 或无效时返回失败（双帧是唯一模式）
        if before_path is None or not Path(before_path).is_file():
            log.warning("[Vision] 样品 %s: before_path 缺失或无效，双帧视觉分析失败", sample_id)
            return VisionResult(x=0.0, y=0.0, rf=0.0, ok=False)

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
            return VisionResult(x=0.0, y=0.0, rf=0.0, ok=False)

    async def analyze_full(
        self,
        sample_id: str,
        before_path: Optional[Path],
        after_path: Path,
        *,
        overrides: Optional[dict[str, Any]] = None,
        output_dir: Optional[Path] = None,
    ) -> AnalysisResult:
        """分析一对前后图像，返回 AnalysisResult（完整结果，Vision Tab 使用）。

        双帧模式要求 before_path 和 after_path 同时有效。
        before_path 为 None 时返回 AnalysisResult(ok=False)——调用方应确保
        BeforePhotoStage 已捕获 before.jpg 并通过 SampleStore 传递。
        不存在单帧回退路径。
        """
        if overrides or output_dir is not None:
            return await self.with_overrides(
                output_dir=output_dir,
                overrides=overrides,
            ).analyze_full(sample_id, before_path, after_path)

        if self._mock_mode:
            # Critical #4: mock_mode 也必须校验 before_path（双帧是唯一模式）
            # before_path 为 None 或无效时返回 ok=False，与真实模式行为一致
            if before_path is None or not Path(before_path).is_file():
                log.warning("[Vision] Mock模式：样品 %s before_path 缺失或无效，返回 ok=False", sample_id)
                return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={},
                                      reason="before_invalid", message="before 图缺失或无效（双帧必需）")
            await asyncio.sleep(0.1)
            if random.random() < self._mock_fail_rate:
                log.info("[Vision] Mock模式：样品 %s 模拟失败", sample_id)
                return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={},
                                      reason="analyze_error", message="mock 模拟分析失败")
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

        # 双帧校验：before 缺失/无效时无法做条带分析，但仍对 after **单图**做同一套姿态归一化,
        # 落 after_normalized.jpg + plate_bbox_px, 让手绘门画在归一化(=机床对齐)帧, 实刮不再反向
        # (见 memory[photoscrape-vision-frame-consistency])。after 也不可读时回落空 case 旧行为。
        if before_path is None or not Path(before_path).is_file():
            log.warning("[Vision] 样品 %s: before 缺失/无效，转 after 单图归一化 backdrop（手绘兜底）", sample_id)
            loop = asyncio.get_running_loop()
            try:
                bd = await loop.run_in_executor(
                    None, self._run_prepare_backdrop, sample_id, after_path,
                )
            except Exception as exc:  # noqa: BLE001 归一化失败(如 after 不可读)不阻断: 回落 raw backdrop
                log.warning("[Vision] 样品 %s: after 单图归一化失败，回落空 case: %s", sample_id, exc)
                return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={},
                                      reason="before_invalid", message="before 图缺失或无效（双帧必需）")
            return AnalysisResult(
                ok=False, case_name=sample_id, case_dir=bd["case_dir"],
                summary={"plate_bbox_px": bd["plate_bbox_px"], "plate_size_cm": bd["plate_size_cm"]},
                reason="before_invalid",
                message="before 图缺失或无效（双帧必需）；已对 after 单图归一化供手绘兜底",
                after_image_path=Path(after_path),
            )

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
            return AnalysisResult(ok=False, case_name=sample_id, case_dir=Path(), summary={},
                                  reason="analyze_error", message=f"视觉分析内部异常: {e}")

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

    @staticmethod
    def _ensure_prepare_backdrop() -> Any:
        """动态注入 tlc_analyze 目录并导入 prepare_manual_backdrop（与 process_pair 同源）。"""
        view_dir_str = str(_VIEW_DIR)
        if view_dir_str not in sys.path:
            sys.path.insert(0, view_dir_str)
        try:
            from tlc_analyze import prepare_manual_backdrop  # type: ignore  # noqa: PLC0415
            return prepare_manual_backdrop
        except ImportError as e:
            raise RuntimeError(f"无法导入 tlc_analyze，请检查路径 {_VIEW_DIR}: {e}") from e

    def _run_prepare_backdrop(self, sample_id: str, after_path: Path) -> dict:
        """无 before 手绘兜底：对 after 单图跑姿态归一化 backdrop（同步，executor 中运行）。

        复用与 process_pair 完全一致的归一化参数（orientation/deskew/找板），保证手绘门
        画布与 CNC 标定同帧。after 不可读 → RuntimeError，调用方回落空 case 旧行为。
        """
        prepare_manual_backdrop = self._ensure_prepare_backdrop()
        after_path = Path(after_path)
        if not after_path.is_file():
            raise RuntimeError(f"after 图像不存在或不是文件: {after_path}")
        return prepare_manual_backdrop(
            case_name=sample_id,
            after_path=after_path,
            output_dir=self._output_dir,
            plate_size_cm=self._plate_size_cm,
            image_plate_orientation=self._image_plate_orientation,
            auto_rectify_tilt=self._auto_rectify_tilt,
            rectify_min_angle_deg=self._rectify_min_angle_deg,
            image_plate_rotation_deg=self._image_plate_rotation_deg,
        )

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
            image_plate_rotation_deg=self._image_plate_rotation_deg,
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
            return VisionResult(x=0.0, y=0.0, rf=0.0, ok=False)

        first = non_origin[0]
        band_metrics = first.get("metrics", {})
        centroid_cm = band_metrics.get("centroid_cm", {})
        x_cm = float(centroid_cm.get("x_cm", 0.0))
        y_cm = float(centroid_cm.get("y_cm", 0.0))

        # 归一化迁移高度作为 Rf 值（范围约 0~1，超出时截断）
        raw_rf = band_metrics.get("normalized_develop_height") or 0.0
        rf = float(min(1.0, max(0.0, raw_rf)))

        log.info(
            "[Vision] 样品 %s: 质心 (%.3f, %.3f) cm，Rf %.3f",
            sample_id, x_cm, y_cm, rf,
        )
        return VisionResult(x=x_cm, y=y_cm, rf=rf, ok=True)

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
        non_origin_bands = [b for b in band_infos if not b.is_origin]
        summary_ok = bool(summary.get("ok", True))
        ok = summary_ok and bool(non_origin_bands)

        # 区分失败原因（供 VM 分支）：summary.ok=False → analyze_error；
        # 跑通但零非原点条带 → no_bands（非致命，人工可跳过刮板）。
        if ok:
            reason, message = "ok", ""
        elif not summary_ok:
            reason, message = "analyze_error", "tlc_analyze 报告 summary.ok=False"
        else:
            reason, message = "no_bands", "未检出任何非原点条带（before≈after? 参数未调? ）"

        # 生成全band标注图（基于 after.jpg 原图 + band 矩形框）
        annotated_image = self._generate_annotated_image(sample_id, case_dir, band_infos, after_path)

        result = AnalysisResult(
            ok=ok,
            case_name=sample_id,
            case_dir=case_dir,
            summary=summary,
            reason=reason,
            message=message,
            bands=band_infos,
            annotated_image_path=annotated_image if annotated_image and annotated_image.exists() else None,
            before_image_path=before_path,
            after_image_path=after_path,
        )
        log.info(
            "[Vision] 样品 %s: 分析完成，%d 条 band（含 origin），有效条带=%d，ok=%s (reason=%s)",
            sample_id, len(band_infos), len(non_origin_bands), ok, reason,
        )
        return result

    # ------------------------------------------------------------------
    # vision 动作适配 (executor _exec_vision 注入调用)
    # ------------------------------------------------------------------

    async def analyze_action(
        self,
        sample_id: str,
        before_path: str,
        after_path: str,
        *,
        image_plate_orientation: Optional[str] = None,
        auto_rectify_tilt: Optional[bool] = None,
        rectify_min_angle_deg: Optional[float] = None,
        min_row_score: Optional[float] = None,
        image_plate_rotation_deg: Optional[float] = _UNSET,  # None=显式自动估(生产 live-read null 必须穿透); _UNSET=未提供→烘定基线
    ) -> dict:
        """vision 动作: 分析前后图, 返回**结构化** result dict 供 operation VM 分支。

        识别参数覆盖 (可选, 关键字): image_plate_orientation/auto_rectify_tilt/
        rectify_min_angle_deg/min_row_score —— 非 None 者覆盖基线, 供门内"重新识别(调参)"
        下发前迭代 与 中控 param-sweep; VM 不传时全走基线 (bootstrap 注入 config.vision 实时值)。
        image_plate_rotation_deg 例外: None 是合法值(每帧自动估), 用 _UNSET 哨兵区分"未提供"
        (回落烘定基线) 与"显式传 None"(必须穿透覆盖, 不可被当缺省丢弃)。

        契约变更 (容错化)：不再对可恢复失败抛 ValueError（那样会被 executor 归一为
        REJECTED → VM raise → run FAILED，故障点无人工处置余地）。改为**始终**返回
        result dict，字段:
          ok           : bool，是否成功（至少 1 条非原点条带）
          reason       : "ok"|"no_bands"|"before_invalid"|"analyze_error"
          message      : 人类可读说明（失败时非空）
          summary_path : summary.json 路径（供 cnc_path；失败无 case 时为 ""）
          case_dir     : 分析输出目录
          band_ids     : 检出的 band id 列表
          annotated_url: 标注图同源 URL（供 HITL 弹窗 <img>；无图为 ""）

        VM 据 result.ok / result.reason 分支：no_bands / before_invalid 走人工菜单
        （重拍 / 补拍before / 跳过刮板 / 中止取板），不再是致命错误。

        测试用法: before/after 取自 test 目录的预置图; mock_mode 时跳过真实分析。
        """
        before = Path(before_path) if before_path else None
        # 每-run 识别参数覆盖 (门内重识别 / 中控 param-sweep / bootstrap 注入的 config.vision
        # 实时基线): 仅收非 None 项; 全 None → overrides=None → 用本 VisionService 烘定基线。
        overrides = {
            key: value
            for key, value in (
                ("image_plate_orientation", image_plate_orientation),
                ("auto_rectify_tilt", auto_rectify_tilt),
                ("rectify_min_angle_deg", rectify_min_angle_deg),
                ("min_row_score", min_row_score),
            )
            if value is not None
        }
        # rotation 单独用 _UNSET 哨兵: None 是合法值(每帧自动估), 必须显式进 overrides
        # 穿透 with_overrides(present-None 不回落烘定值); 未提供才走烘定基线。
        if image_plate_rotation_deg is not _UNSET:
            overrides["image_plate_rotation_deg"] = image_plate_rotation_deg
        res = await self.analyze_full(
            sample_id, before, Path(after_path), overrides=overrides or None
        )
        # 标注图同源 URL (供 HITL 弹窗 <img> 加载; 经 vite 代理 /api→后端)。
        # 无标注图 (mock / before 无效 / 生成失败) → 空串, 弹窗据此不渲染图。
        annotated_url = ""
        if res.annotated_image_path:
            try:
                rel = Path(res.annotated_image_path).relative_to(self._output_dir).as_posix()
                annotated_url = f"/api/vision/image/{rel}"
            except ValueError:
                annotated_url = ""
        # 视觉失败(before_invalid/analyze_error)时无标注图 → 手绘门画布无底图, 用户完全无从下笔。
        # 兜底: 给一张可服务的 after 图当底图 (能到手绘门, 说明 after 已拍成)。只补 annotated_url;
        # 不伪造 case_dir/summary_path (失败语义不变; 前端据空 context 走 4 角标板 → 透视映射)。
        if not annotated_url:
            annotated_url = self._backdrop_url(sample_id, res.case_dir, after_path)
        # case_dir 为空 (before_invalid / analyze_error 提前返回) 时 summary_path 置空,
        # 失败分支不会消费它; 成功 / no_bands 时 case 目录有效, summary.json 可被 cnc_path 读。
        has_case = str(res.case_dir) not in ("", ".")
        summary_path = str(res.case_dir / "summary.json") if has_case else ""
        # 落 inputs.json 供门内"重新识别(调参)"回溯本 run 的 before/after (前端只需带 summary_path)。
        if has_case:
            try:
                (Path(res.case_dir) / "inputs.json").write_text(
                    json.dumps(
                        {"sample_id": sample_id, "before_path": before_path,
                         "after_path": after_path},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                log.warning("[Vision] 写 inputs.json 失败 (不影响分析结果)", exc_info=True)
        return {
            "ok": bool(res.ok),
            "reason": res.reason,
            "message": res.message,
            "summary_path": summary_path,
            "case_dir": str(res.case_dir),
            "band_ids": [b.band_id for b in res.bands],
            "annotated_url": annotated_url,
            "bands": [_band_display(b) for b in res.bands],
        }

    def _backdrop_url(self, sample_id: str, case_dir: Path, after_path: str) -> str:
        """手绘门底图兜底 URL: 视觉失败无标注图时, 给一张可 /api/vision/image 服务的 after 图。

        优先 case 内已有的可服务帧 (after_normalized→after, 与 plate_bbox 同帧, 保 WYSIWYG);
        否则 (before_invalid 无 case) 把本 run 原始 after 拷进 output_dir/<sample_id>/after.jpg。
        sample_id 去路径分隔符防越 output_dir; 任何 IO 失败回空串, 绝不因底图拖垮 analyze。
        """
        try:
            if str(case_dir) not in ("", "."):
                for name in ("after_normalized.jpg", "after.jpg"):
                    cand = Path(case_dir) / name
                    if cand.is_file():
                        rel = cand.relative_to(self._output_dir).as_posix()
                        return f"/api/vision/image/{rel}"
            src = Path(after_path) if after_path else None
            if src is None or not src.is_file():
                return ""
            safe_id = Path(str(sample_id)).name or "manual"
            dst = self._output_dir / safe_id / "after.jpg"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.resolve() != src.resolve():
                shutil.copyfile(src, dst)
            rel = dst.relative_to(self._output_dir).as_posix()
            return f"/api/vision/image/{rel}"
        except (OSError, ValueError):
            log.warning("[Vision] 手绘门底图兜底失败 (不影响分析结果)", exc_info=True)
            return ""

    def _generate_annotated_image(
        self,
        sample_id: str,
        case_dir: Path,
        bands: list[BandInfo],
        after_path: Path,
    ) -> Optional[Path]:
        """基于 after.jpg 原图生成全 band 标注图。

        优先使用 OpenCV 渲染（参考 tlc_analyze.py 的 draw_band_overlay 范式），
        绘制带光晕的 contour 轮廓线 + 质心标记 + 编号标签。
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
        # 归一化图上盘后，标注底图切到 case_dir/after_normalized.jpg（与 plate_bbox_px 同帧；
        # 缺失/旧数据回落原始 after）。见 tlc_analyze.process_pair。
        _norm_after = case_dir / "after_normalized.jpg"
        if _norm_after.is_file():
            after_path = _norm_after

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
        """OpenCV 渲染识别标注图：contour 轮廓 + 质心 + 标签。

        参考 tlc_analyze.py 的 draw_band_overlay 范式，
        只利用 process_pair 输出的 contour_px 几何。执行路径由 cnc_path
        在选定 band 后单独生成，不能在识别图中用 zipper 轨迹冒充。
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
            px, py = plate_coords.cm_to_px_affine(
                [(cx_cm, cy_cm)],
                {"x": plate_x, "y": plate_y, "w": plate_w, "h": plate_h},
                plate_size_cm,
            )[0]
            return int(round(px)), int(round(py))

        # 读取各 band 的 contour / path 数据并叠加绘制
        bands_data = summary_data.get("bands", [])
        n_contours_drawn = 0
        log.info("[Vision] CV 渲染: bands=%d, bands_data=%d, plate_bbox=%s",
                 len(bands), len(bands_data), plate_bbox_px)
        for band_info, band_summary in zip(bands, bands_data):
            path_json_str = band_summary.get("path_json", "")
            contour_px = None

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
                        log.debug(
                            "[Vision] band %s: path_json 解析成功 (from=%s, contour=%dpts)",
                            band_info.band_id, resolved_from,
                            len(contour_px) if contour_px is not None else 0,
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
            "[Vision] CV 标注图已生成: %s (contours=%d, total_bands=%d)",
            output_path, n_contours_drawn, len(bands),
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
        lx, ly = plate_coords.cm_to_px_affine(
            [(x_min, y_max)],
            {"x": plate_x, "y": plate_y, "w": plate_w, "h": plate_h},
            plate_size_cm,
        )[0]
        label_px_x = int(lx)
        label_px_y = int(ly) - 5

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
            px, py = plate_coords.cm_to_px_affine(
                [(cx_cm, cy_cm)],
                {"x": plate_x, "y": plate_y, "w": plate_w, "h": plate_h},
                plate_size_cm,
            )[0]
            return int(round(px)), int(round(py))

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
        def _safe_float(value: Any, default: float = 0.0) -> float:
            if value is None:
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        bands_data = summary.get("bands", [])
        infos: list[BandInfo] = []
        for b in bands_data:
            metrics = b.get("metrics", {})
            if not metrics and b.get("is_origin"):
                origin_info = summary.get("origin_band", {})
                metrics = {
                    "centroid_cm": origin_info.get("center_cm", {}),
                    "bbox_cm": None,
                    "vertical_band_width_cm": 0.0,
                    "horizontal_span_cm": 0.0,
                    "distance_to_origin_cm": 0.0,
                    "normalized_develop_height": 0.0,
                }
            centroid = metrics.get("centroid_cm", {})
            bbox = metrics.get("bbox_cm")  # may not exist in summary

            # 垂直宽度与水平跨度
            v_width = _safe_float(metrics.get("vertical_band_width_cm", 0.0))
            h_span = _safe_float(metrics.get("horizontal_span_cm", 0.0))
            area = v_width * h_span

            # bbox_cm：从 centroid_cm + vertical_width_cm + horizontal_span_cm 计算
            cx = _safe_float(centroid.get("x_cm", 0.0))
            cy = _safe_float(centroid.get("y_cm", 0.0))
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
                    _safe_float(centroid.get("x_cm", 0.0)),
                    _safe_float(centroid.get("y_cm", 0.0)),
                ),
                bbox_cm=bbox_cm_val,
                vertical_width_cm=v_width,
                horizontal_span_cm=h_span,
                distance_to_origin_cm=_safe_float(metrics.get("distance_to_origin_cm", 0.0)),
                normalized_develop_height=_safe_float(metrics.get("normalized_develop_height", 0.0)),
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
        image_plate_rotation_deg=vcfg.image_plate_rotation_deg,
    )
