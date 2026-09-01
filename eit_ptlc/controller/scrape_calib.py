"""刮痕自动标定 — 标定图案几何 + 逐轮工作区构造。

标定思路: 在空白牺牲板上刮一个**已知板 cm 位置**的图案, 拍照测出实刮位置, 差值即
相机链+机床链+刀具链的合量误差, 折进 gcode.plate_origin。测量本体见 scrape_offset.py。

图案为 **L 形**(长横带 + 左端竖笔), 这个形状是被两个相反的约束夹出来的, 见 _PATTERN 系常量。
逐轮换位, 且全部偏离板中心 —— 居中图案对 origin_corner 镜像错误是不变的, 检不出来
(L 形还额外是**手性**的, 镜像后不自等, 比矩形更能暴露翻转错误)。

⚠️ 逐轮换基准帧是本模块存在的理由:
    第二轮刮完后板上有两条痕。若仍拿最初空白板帧做差分, 两条都会被检出(connectedComponents
    判据必挂); 若第二轮刮在同一位置, 与旧痕高度重叠, 差分只剩细月牙。
    故 **第 N 轮的差分基准 = 第 N−1 轮的 scraped_normalized.jpg**(旧痕在前后两帧都在, 差分抵消)
    **且** 第 N 轮位置与前轮错开(见 _PATTERN_Y0_CM)。工作区命名与基准帧选择的唯一真源在此,
    调用方(端点/面板)不得自行拼路径。

⚠️ "空白牺牲板"是前提而非建议: 建工作区时会逐轮核对图案区在基准帧上确实还是完好涂层
    (见 _assert_pattern_region_blank), 不然刮完也只能报"未检出"。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from eit_ptlc.controller import plate_coords
from eit_ptlc.controller.sketch_path import write_manual_summary

log = logging.getLogger(__name__)

CALIB_BAND_ID = "calib_01"

# ── 标定图案几何 ────────────────────────────────────────────────────────────
# 形状是 L: 一条长横带(定 y) + 左端一个朝 +y 的竖笔(定 x)。两段各自不可省, 理由如下。
#
# ① 为什么必须"宽而扁" —— 2026-07-26 真机教训:
#    收集路径长度 ∝ y 方向高度, 与 x 宽度几乎无关(拖尾沿 x, 每个 y 层拖一次)。
#    4×4cm 方块的全程 15038mm @feed800 ≈ 18.8 分钟, 远超单 pass 停滞预算而被判"结果不明确";
#    同样 0.6×4.0cm 仍要 13412mm(缩宽度几乎无效), 而 8×0.6cm 只要 3758mm。
#
# ② 为什么光有横带不行 —— 同日第二轮标定复盘实测:
#    一条 8×0.6 的扁带**在 x 方向几何欠定**。用重叠配准量: 沿带长挪 2.8mm 只掉 2.5% 重叠,
#    垂直带挪同样距离掉 49% —— 相关峰是条平脊, x 的信息根本不在图里。
#    实证: 三种估计器对同一轮的 dy 一致在 0.14mm 内, dx 却散在 0.90mm(大于 dx 自身 0.75mm)。
#    **这是形状问题, 换估计器(模板配准/相位相关)救不了。**
#    竖笔提供垂直边, 把 x 的重叠损失率从 5.1% 提到 11.5%(条件数 2.25×), y 仅由 46.2% 退到 38.9%,
#    代价只有每轮 +35 秒(3758 → 4229mm, 4.70 → 5.29min)。
#
# ③ 竖笔为何朝 +y 且在左端: 远离 y=0 点样边(那里有 machine_y_min_mm 截平钳制, 会被误读成偏移)。
#
# 改任何一个尺寸后**必须**跑 test_scrape_calib_offline 的三条几何钉子(路径长度上限 /
# 扫掠实心且列距达标 / x 向可观测性下限)复核。
_BAND_X0_CM, _BAND_X1_CM = 4.0, 12.0     # 横带 x 跨度 8cm —— 定 y
_BAND_H_CM = 0.6                         # 横带高
_STEM_W_CM, _STEM_H_CM = 0.6, 1.5        # 左端竖笔 —— 定 x
# 逐轮下沿。间距 5.5cm − 图案高 2.1cm = **相邻净间距 3.4cm** > 默认 2cm 搜索窗,
# 使旧痕落不进新轮的窗内 (这是第二道保险; 第一道是"第 N 轮用第 N−1 轮刮后帧当差分基准")。
# 顶 15.0+2.1 = 17.1cm < 20cm 板宽, 下沿 4.0cm 远离点样边。
_PATTERN_Y0_CM: tuple[float, ...] = (4.0, 9.5, 15.0)
MAX_ROUND = len(_PATTERN_Y0_CM)

# ── 开刮前的空白预检 ────────────────────────────────────────────────────────
# 差分测量的前提是"图案区在基准帧上是完好涂层"。刮在已经刮秃的地方, 前后帧同样黑,
# 差分无信号 → measure_scrape_offset 只能报"未检出", 而那时刀已经跑完、粉已经出了。
#
# ⚠️ 这是 2026-07-27 真机 CALIB-20260727101716 第1轮的复盘: 操作员拿了一块用过的板
#    (板上已有约 10 条旧刮痕), 第1轮图案 y4.0-6.1cm 正压在一条全宽旧痕上。指令面积
#    ≈41000px, 而差分只挑出 6 块碎屑共 3924px(新溅的粉点), 全部够不着 5% 门槛。
#    白刮一轮才知道。故把判断提到建工作区时 —— 那时还没有任何刀具动作。
_BLANK_DARK_RATIO = 0.10   # 图案区暗像素占比上限; 空白板实测≈0, 故障板那轮≈0.8, 两边余量都足
_BLANK_DARK_REL = 0.55     # "暗" = 灰度 < 完好涂层亮度 × 此系数
# 完好涂层亮度取板内灰度的高分位而非中位数: 板上已有旧痕会把中位数拉低,
# 用中位数当基准等于"越脏的板越宽松", 方向正好反了。
_COATED_PERCENTILE = 75

# ── 板框方形校验 ────────────────────────────────────────────────────────────
# 板是 20×20 正方形, 检出框长宽差超过此比例 = 板框检测被照明削了边(绿板掩膜的绝对亮度
# 阈值把暗侧整列剔除), px↔cm 比例随之失真 —— 刮痕会被"测成"拉长+平移的假象, 标定必挂。
#
# ⚠️ 这是 2026-07-27 真机 CALIB-20260727165445 的复盘: 左侧补光衰减, 板框检出 1634×1712
#    (纵横比 0.954, 左边被削 98px≈11mm), x 比例低估 6% → 卡尺实测 80.0mm 的图案被"测成"
#    ~86mm, centroid_agreement 判据挂掉, 白刮一轮后靠人工比对竖笔/横带两端才定位到板框。
#    同日 06:37 一轮板框 69×1133(检测彻底崩溃)、06:44 一轮 0.963, 全都该在建工作区时拦下。
# 容差取 0.02: 正常光照实测纵横比 0.994~1.006, 故障日 0.954/0.963, 两边余量都足。
_BBOX_ASPECT_TOL = 0.02


def pattern_contour_cm(round_no: int) -> list[tuple[float, float]]:
    """第 round_no 轮标定 L 形图案的 6 个角(板 cm), 逆时针自左下角起。

    参数:
        round_no: 轮次, 从 1 起; 超出 MAX_ROUND 抛 ValueError (一块板放不下更多图案)
    返回:
        List[Tuple[float, float]], 闭合 L 形的六个角点(板 cm)
    """
    if not 1 <= round_no <= MAX_ROUND:
        raise ValueError(f"标定轮次须在 1..{MAX_ROUND} 之间(一块板容量上限), 得到 {round_no}")
    y0 = _PATTERN_Y0_CM[round_no - 1]
    y_band = y0 + _BAND_H_CM                 # 横带上沿 = 竖笔根部
    y_top = y_band + _STEM_H_CM              # 竖笔顶
    x_stem = _BAND_X0_CM + _STEM_W_CM        # 竖笔右边
    return [
        (_BAND_X0_CM, y0), (_BAND_X1_CM, y0),        # 横带下沿 左→右
        (_BAND_X1_CM, y_band), (x_stem, y_band),     # 横带上沿 右→竖笔根
        (x_stem, y_top), (_BAND_X0_CM, y_top),       # 竖笔 右→顶→左
    ]


def _assert_pattern_region_blank(
    base: Path, contour_cm: list[tuple[float, float]],
    plate_bbox_px: Any, plate_size_cm: float, round_no: int,
) -> None:
    """基准帧上本轮图案区若已有旧痕, 当场拒绝 —— 别等刮完才发现测不出来。

    参数:
        base:          本轮差分基准帧(轮1=空白板帧, 轮N=轮N−1 刮后帧)
        contour_cm:    本轮 L 形图案的角点(板 cm)
        plate_bbox_px: 板框(建 cm→px 映射)
        plate_size_cm: 板边长 cm
        round_no:      轮次, 仅用于消息
    异常:
        ValueError: 图案区暗像素占比超 _BLANK_DARK_RATIO(端点转 422)

    护栏不是工艺步: 缺 cv2 或基准帧不可解码时**放行**并留一条 warning。宁可漏判一次
    (下游 measure_scrape_offset 仍会报未检出), 也不能因为看不了图就把整条标定链堵死。
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError as exc:
        log.warning("[calib] 缺 cv2/numpy, 跳过图案区空白预检: %s", exc)
        return

    image = cv2.imread(str(base), cv2.IMREAD_GRAYSCALE)
    if image is None:
        log.warning("[calib] 基准帧不可解码, 跳过图案区空白预检: %s", base)
        return

    bx, by, bw, bh = plate_coords.plate_bbox_xywh(plate_bbox_px)
    plate = image[int(by):int(by + bh), int(bx):int(bx + bw)]
    if plate.size == 0:
        log.warning("[calib] 板框落在帧外, 跳过图案区空白预检: bbox=%s", plate_bbox_px)
        return
    coated = float(np.percentile(plate, _COATED_PERCENTILE))

    # 图案区掩膜用 L 形 contour 本身而非其 bbox —— 缺口那块并不会被刮到, 不该计入
    pts = plate_coords.cm_to_px_affine(contour_cm, plate_bbox_px, plate_size_cm)
    mask = np.zeros(image.shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.rint(np.asarray(pts, dtype=np.float32)).astype(np.int32)], 255)
    region = image[mask > 0]
    if region.size == 0:
        log.warning("[calib] 图案区掩膜为空, 跳过空白预检(轮%d)", round_no)
        return

    dark_ratio = float((region < coated * _BLANK_DARK_REL).mean())
    if dark_ratio > _BLANK_DARK_RATIO:
        xs = [x for x, _ in contour_cm]
        ys = [y for _, y in contour_cm]
        raise ValueError(
            f"第 {round_no} 轮图案区(x {min(xs):g}~{max(xs):g}, y {min(ys):g}~{max(ys):g} cm)"
            f"在差分基准帧上已有 {dark_ratio:.0%} 暗像素(上限 {_BLANK_DARK_RATIO:.0%}) —— "
            "板面非空白/旧痕重叠, 刮上去前后帧同样黑, 差分测不出新刮痕。"
            "请换一块空白牺牲板重跑。"
        )
    log.info("[calib] 轮%d 图案区空白预检通过(暗像素 %.1f%%)", round_no, dark_ratio * 100)


def workspace_dir(output_dir: Path | str, sample_id: str, round_no: int) -> Path:
    """第 round_no 轮的工作区目录(唯一命名真源)。"""
    return Path(output_dir) / f"{sample_id}_calib_r{round_no}"


def base_frame_path(output_dir: Path | str, sample_id: str, round_no: int) -> Path:
    """第 round_no 轮的差分基准帧。

    轮1 = 视觉 case 的空白板归一化帧; 轮N = 第 N−1 轮的刮后归一化帧
    (让旧痕在前后两帧都存在从而在差分中抵消)。
    """
    output_dir = Path(output_dir)
    if round_no <= 1:
        return output_dir / sample_id / "after_normalized.jpg"
    return workspace_dir(output_dir, sample_id, round_no - 1) / "scraped_normalized.jpg"


def _read_vision_frame(vision_summary: Path) -> tuple[Any, float, dict]:
    """从视觉 case 的 summary 取建帧三件: plate_bbox_px / plate_size_cm / normalize_applied。

    缺任一即拒绝 —— 少了它们产出的工作区根本测不了, 不如当场失败而非静默留个哑弹。
    板框还须近正方(_BBOX_ASPECT_TOL): 比例失真的板框测出的 Δ 全是假象, 刮了也白刮。
    """
    if not vision_summary.is_file():
        raise FileNotFoundError(f"找不到视觉 case 的 summary.json: {vision_summary}")
    data = json.loads(vision_summary.read_text(encoding="utf-8"))
    plate_bbox_px = data.get("plate_bbox_px")
    if plate_bbox_px is None:
        raise ValueError("视觉 summary 缺 plate_bbox_px(未框到板); 标定需要板参照, 请重拍")
    _bx, _by, bbox_w, bbox_h = plate_coords.plate_bbox_xywh(plate_bbox_px)
    if min(bbox_w, bbox_h) <= 0 or abs(bbox_w / bbox_h - 1.0) > _BBOX_ASPECT_TOL:
        raise ValueError(
            f"视觉板框 {bbox_w:g}×{bbox_h:g}px(纵横比 {bbox_w / max(bbox_h, 1e-9):.3f})"
            f"偏离正方形超过 {_BBOX_ASPECT_TOL:.0%} —— 板是正方形, 板框大概率被照明削边"
            "(暗侧被绿板掩膜的绝对亮度阈值剔除), px↔cm 比例已失真, 测出的偏移全是假象。"
            "请检查补光/曝光后重拍建帧, 再开始标定。")
    normalize_applied = data.get("normalize_applied")
    if not normalize_applied:
        raise ValueError(
            "视觉 summary 缺 normalize_applied(早于帧回放契约的老 case); "
            "刮后无法确定性回放, 拒绝构造标定工作区")
    return plate_bbox_px, float(data.get("plate_size_cm") or 20.0), normalize_applied


def build_round_workspace(
    output_dir: Path | str, sample_id: str, round_no: int,
) -> dict[str, Any]:
    """构造第 round_no 轮的标定工作区, 返回可直接交给 cnc_path 的 summary_path。

    参数:
        output_dir: 视觉输出根目录(config.vision.output_dir)
        sample_id:  本次标定的样品 ID, 视觉 case 目录同名
        round_no:   轮次, 从 1 起
    返回:
        Dict[str, Any], 含 summary_path / band_id / workspace / round /
        contour_cm / base_frame(本轮差分基准帧来源)
    异常:
        FileNotFoundError: 视觉 summary 或差分基准帧缺失(端点转 404)
        ValueError: 轮次越界 / 视觉 case 不满足建帧条件 / 图案区已有旧痕(端点转 422)

    产出目录内含 after_normalized.jpg(差分基准) + summary.json + <band>_path.json,
    刮完由 scraped_overlay 补上 scraped_normalized.jpg, 三件套齐则 measure_scrape_offset 可测。
    """
    output_dir = Path(output_dir)
    plate_bbox_px, plate_size_cm, normalize_applied = _read_vision_frame(
        output_dir / sample_id / "summary.json")

    base = base_frame_path(output_dir, sample_id, round_no)
    if not base.is_file():
        raise FileNotFoundError(
            f"第 {round_no} 轮的差分基准帧不存在: {base}"
            + ("" if round_no <= 1 else " (上一轮的刮后回放帧未产出, 对账链在上一轮已断)"))

    contour_cm = pattern_contour_cm(round_no)
    # 预检排在建工作区之前: 拒绝时不留半拉工作区, 也不留任何刀具动作
    _assert_pattern_region_blank(base, contour_cm, plate_bbox_px, plate_size_cm, round_no)

    workspace = workspace_dir(output_dir, sample_id, round_no)
    summary_path = write_manual_summary(
        contour_cm, workspace, band_id=CALIB_BAND_ID,
        plate_bbox_px=plate_bbox_px, normalize_applied=normalize_applied,
    )
    # 基准帧落成本工作区的 after_normalized.jpg —— measure_scrape_offset 按此名取刮前帧
    shutil.copy2(base, workspace / "after_normalized.jpg")

    log.info("[calib] 轮%d 工作区就绪: %s (基准帧 %s)", round_no, workspace, base.name)
    return {
        "round": round_no,
        "summary_path": str(summary_path),
        "band_id": CALIB_BAND_ID,
        "workspace": str(workspace),
        "plate_size_cm": plate_size_cm,
        "contour_cm": [[round(x, 3), round(y, 3)] for x, y in contour_cm],
        "base_frame": str(base),
        # 本轮刮前基准帧的相对路径 (供端点拼 /api/vision/image URL 让面板显示 —— 操作员反馈
        # "没看到刮前拍照", 其实拍了, 只是相机动作快且界面不呈现)
        "base_frame_rel": f"{workspace.name}/after_normalized.jpg",
        "max_round": MAX_ROUND,
    }
