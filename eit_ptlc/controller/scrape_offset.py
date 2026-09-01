"""刮痕位置测量 — 从刮后对账帧自动算出「指令 vs 实刮」的位置误差。

原理:
    刮前 after_normalized.jpg 与刮后 scraped_normalized.jpg 已由 replay_normalization 保证
    同帧同尺寸(契约 C-3, 禁重新检测), 故两图可直接差分: 硅胶被刮掉处灰度显著变化 → 实刮掩膜。
    指令扫掠区由 preview_payload.scrape_px 按 cutter_width_px 渲成同型掩膜(与叠加图同一画法)。
    两个掩膜过**同一个**质心算子, 差值即位置误差; 再经 plate_coords 映回板 cm。

    修正方向由 cnc_path._flip_from_corner 决定(唯一 flip 真源), 不在此另立查表。

⚠️ 本测量给出的是相机链(A)+机床链(B)+刀具链(C)的**合量**, 无法分离三者。
   对"让生产刮准"这是正确的修正量 —— 生产闭环本身就是照片→cm→机床, 折进 plate_origin 后闭环自洽。
   但若相机被碰移位, 其误差会被静默吸收进 plate_origin, 机床侧其实是歪的。
   需要分离时仍须卡尺法交叉验证(见 docs/superpowers/specs/2026-07-15-photoscrape-scrape-closedloop-design.md §8)。

前置(缺任一即拒绝测量, 不猜):
    case_dir/after_normalized.jpg   刮前归一化帧
    case_dir/scraped_normalized.jpg 刮后归一化帧(由 scraped_overlay 回放产出; 缺 = 帧契约未成立)
    case_dir/preview_payload.json   本次下发的指令路径(契约 C-5, 与 summary 同代)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller import plate_coords
from eit_ptlc.controller.cnc_path import _flip_from_corner

log = logging.getLogger(__name__)

# 灰度差阈值下限(0-255): 防两图几乎相同(未真刮)时 Otsu 把噪声放大成"检出"
_MIN_DIFF_LEVEL = 25
# 实刮掩膜面积 / 指令扫掠面积 的可信区间; 越界说明检测残缺或糊开, 数不可采纳
_MIN_AREA_RATIO = 0.15
_MAX_AREA_RATIO = 3.0
# 质心Δ 与 bbox中心Δ 的一致性阈值(cm): 两者分歧大 = 刮槽检出不对称/残缺
_CENTROID_AGREE_CM = 0.15
# 实刮掩膜的搜索窗 = 指令扫掠区外扩此距离(cm); 窗外的变化计入 stray, 不进质心
_DEFAULT_SEARCH_MARGIN_CM = 2.0
# 连通块被采纳的最小面积 = 指令扫掠面积的此比例。一块**真**刮痕必与指令区同量级,
# 达不到的只可能是污点/残粉/被吸走的暗斑, 剔除后既不进质心也不计入块数。
#
# ⚠️ 这条是 2026-07-26 真机 CALIB-20260726141119 第2轮误判的修复: 当时一个 196px
#    (0.027cm² = 2.1×1.6mm, 灰度刮前 46.6暗 → 刮后 163.2亮, 即**消失的暗污点**而非刮痕)
#    绊掉了"连通块数==1"硬闸, 整轮作废、放弃写盘 —— 而它对质心的影响只有 (0.055, 0.014)mm,
#    比 dx 自身的估计歧义(0.90mm)还小 16 倍。原判据只数**块数**、对面积完全不敏感, 是错的代理量:
#    杂痕能带偏质心的程度 ∝ 面积×距离。按面积过滤后判据才真正对应它想防的东西。
#    实测分离度: 该杂点 196px 比阈值(35402×0.05=1770px)低 9 倍, 主刮痕 30292px 高 17 倍。
_MIN_COMPONENT_RATIO = 0.05
# 图案"拉伸"警示阈值(cm): 实刮与指令的 bbox 宽/高差超过此值, 在 message 里给出指纹。
# 拉伸 ≠ 平移: 平移是标定要测的量; 拉伸(两端偏移不等)是"px↔cm 比例失真或刮取过程中
# 位置跳变"的病征, 此时 Δ 含失真分量不可采纳。且对称图形整体拉伸时质心Δ与bbox中心Δ
# 一致地各偏一半, centroid_agreement 判据拦不住 —— 必须单独看宽高差。
#
# ⚠️ 这是 2026-07-27 真机 CALIB-20260727165445 的复盘: 板框左边被照明削 ~11mm, x 比例
#    低估 6%, 卡尺实测 80.0mm 的图案被"测成" ~86mm; 当时靠人工比对竖笔/横带两端才定位。
#    本字段把该指纹自动化。只警示、不进判据 —— 每多一条判据就多一条整轮作废的路,
#    而板框失真应由 scrape_calib 的方形校验在建工作区时拦住, 这里是测量端的最后一道显影。
_STRETCH_WARN_CM = 0.15


def _load_payload(case_dir: Path) -> dict[str, Any]:
    payload_path = case_dir / "preview_payload.json"
    if not payload_path.is_file():
        raise FileNotFoundError(
            "缺少 preview_payload.json (本次候选未经 cnc_path, 或几何无板参照); 无法比对指令路径")
    return json.loads(payload_path.read_text(encoding="utf-8"))


def _mask_stats(mask) -> dict[str, Any] | None:
    """掩膜 → {area_px, centroid_px, bbox_px}; 空掩膜返回 None。质心与 bbox 中心同时给出供交叉校验。"""
    import cv2  # noqa: PLC0415

    area = int(cv2.countNonZero(mask))
    if area <= 0:
        return None
    moments = cv2.moments(mask, binaryImage=True)
    if moments["m00"] <= 0:
        return None
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    x, y, w, h = cv2.boundingRect(mask)
    return {
        "area_px": area,
        "centroid_px": [round(cx, 2), round(cy, 2)],
        "bbox_px": [int(x), int(y), int(w), int(h)],
        "bbox_center_px": [round(x + w / 2.0, 2), round(y + h / 2.0, 2)],
    }


def _split_components(mask, min_area_px: int):
    """按面积把掩膜拆成「采纳」与「碎块」两张, 返回 (采纳掩膜, 碎块掩膜, 采纳块数, 碎块数)。

    参数:
        mask:        搜索窗内的实刮候选掩膜(0/255)
        min_area_px: 连通块被采纳的最小面积(px); 低于此值的块归为碎块
    返回:
        Tuple, (kept_mask, minor_mask, kept_count, minor_count)

    采纳掩膜同时用于质心与面积 —— 碎块既不带偏 Δ, 也不计入 component_count 判据。
    真刮痕断成两半时两半都在阈值之上, 仍会双双存活 → 判据照样挂, 原意图完整保留。
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    kept = np.zeros(mask.shape, dtype=np.uint8)
    minor = np.zeros(mask.shape, dtype=np.uint8)
    kept_count = 0
    minor_count = 0
    for idx in range(1, count):   # 0 是背景
        area = int(stats[idx, cv2.CC_STAT_AREA])
        target = kept if area >= min_area_px else minor
        target[labels == idx] = 255
        if area >= min_area_px:
            kept_count += 1
        else:
            minor_count += 1
    return kept, minor, kept_count, minor_count


def _commanded_mask(shape, payload: dict[str, Any]):
    """按 preview_payload 的 scrape_px + cutter_width_px 渲指令扫掠掩膜(与对账叠加同一画法)。"""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    pts = payload.get("scrape_px") or []
    if len(pts) < 2:
        raise ValueError("preview_payload.scrape_px 点数不足, 无法构造指令扫掠区")
    mask = np.zeros(shape[:2], dtype=np.uint8)
    arr = np.rint(np.asarray(pts, dtype=np.float32)).astype(np.int32)
    width = max(1, int(round(float(payload.get("cutter_width_px") or 1.0))))
    cv2.polylines(mask, [arr], False, 255, width, cv2.LINE_8)
    return mask


def _diff_mask(before, after, plate_rect, kernel_px: int):
    """刮前/刮后灰度绝对差 → 二值刮槽掩膜(限板框内, 开运算去麻点 + 闭运算补断口)。

    用绝对差而非有向差: 刮掉硅胶后露出的基材可能更暗也可能更亮(铝基反光), 不预设方向。

    差分先按刮前帧的照度场做平场归一, 再走全局 Otsu:
    ⚠️ 2026-07-27 真机复盘第二课: 板面亮度随补光衰减左右可差 ~35%(左暗条涂层 g≈65,
       右侧 ≈86), 刮槽的差分信号随之左弱右强(≈60 vs ≈81), 全局单阈值把暗侧刮槽边缘
       系统性漏检 —— 实测检出完整度右半 96% / 左半 89% / 竖笔区仅 71%, 掩膜质量随位置
       漂移使质心被拉离 bbox 中心, centroid_agreement 判据虚挂(dx 分歧 2.2mm)。
       平场后左右信号归一(74 vs 75), 阈值对全板等效。照度场取刮前帧的大尺度模糊
       (标定时刮前是空白板, 场内无图案; 生产刮前有谱带, 尺度取刀宽 3 倍以上抹平)。
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_before, gray_after)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)

    plate_mask = np.zeros(diff.shape, dtype=np.uint8)
    px, py, pw, ph = plate_rect
    cv2.rectangle(plate_mask, (px, py), (px + pw, py + ph), 255, -1)

    # 照度平场: gain = 板内照度中位 / 局部照度; 分母下限 20% 防暗角把噪声放大成假检出
    illum = cv2.GaussianBlur(gray_before, (0, 0), max(15.0, kernel_px * 9.0))
    ref = float(np.median(illum[plate_mask > 0])) or 1.0
    gain = ref / np.maximum(illum.astype(np.float32), ref * 0.2)
    diff = np.clip(diff.astype(np.float32) * gain, 0.0, 255.0).astype(np.uint8)

    diff_in_plate = cv2.bitwise_and(diff, plate_mask)

    otsu_level, _ = cv2.threshold(
        diff_in_plate[plate_mask > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    level = max(float(otsu_level), float(_MIN_DIFF_LEVEL))
    _, mask = cv2.threshold(diff_in_plate, level, 255, cv2.THRESH_BINARY)

    k = max(3, kernel_px | 1)   # 奇数核
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask, float(level), diff_in_plate


def _delta_cm(from_px, to_px, plate_bbox_px, plate_size_cm) -> tuple[float, float]:
    """两个像素点 → 板 cm 位移(经 plate_coords 单一真源, Y 轴翻转已在其中)。"""
    (fx, fy), (tx, ty) = plate_coords.px_to_cm_affine(
        [tuple(from_px), tuple(to_px)], plate_bbox_px, plate_size_cm)
    return tx - fx, ty - fy


def suggest_plate_origin(
    dx_cm: float, dy_cm: float, cfg: GCodeCfg,
) -> tuple[float, float]:
    """由「实刮 − 指令」的板 cm 位移推 plate_origin 新值。

    _to_machine 为 m = o ± c*10 (符号由 flip 定)。指令 c 落到了实测 a = c + Δ, 即
    o ± c*10 = o_true ± a*10 → o_true = o ∓ Δ*10。故 flip=False 时减, flip=True 时加。
    """
    flip_x, flip_y = _flip_from_corner(cfg.origin_corner)
    sign_x = 1.0 if flip_x else -1.0
    sign_y = 1.0 if flip_y else -1.0
    return (
        round(cfg.plate_origin_x + sign_x * dx_cm * 10.0, 3),
        round(cfg.plate_origin_y + sign_y * dy_cm * 10.0, 3),
    )


def _render_overlay(scraped, cmd_mask, act_mask, minor_mask, cmd_stats,
                    act_stats: dict[str, Any] | None, out_path: Path) -> bool:
    """在刮后帧上画: 指令扫掠区(青) + 实刮掩膜(白) + 被剔除的碎块(红) + 质心位移箭头(黄)。

    碎块必须画出来 —— 否则"剔掉了什么、为什么这轮过/不过"在界面上不可查, 只能靠猜。

    act_stats=None(未检出)时只画指令区与碎块, 无白轮廓也无箭头 —— 恰恰这一档最需要看图
    ("为什么没测出来"), 少画几层不是省事, 是把现场留给操作员。
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    image = scraped.copy()
    tint = image.copy()
    tint[cmd_mask > 0] = (236, 216, 0)          # 青 = 指令
    cv2.addWeighted(tint, 0.30, image, 0.70, 0.0, image)
    for contours, color in (
        (cv2.findContours(act_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0],
         (255, 255, 255)),                       # 白 = 采纳的实刮轮廓
        (cv2.findContours(minor_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0],
         (60, 60, 255)),                         # 红 = 面积不足被剔除的碎块
    ):
        cv2.drawContours(image, contours, -1, (7, 7, 10), 4, cv2.LINE_AA)
        cv2.drawContours(image, contours, -1, color, 2, cv2.LINE_AA)

    # 碎块只有毫米级(实测 2.1×1.6mm), 在缩略图上轮廓线细到看不见 —— 再套一个最小半径的红圈,
    # 保证不放大也能一眼定位到"被剔掉的是哪一块"
    for contour in cv2.findContours(minor_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        (mx, my), radius = cv2.minEnclosingCircle(contour)
        center = (int(round(mx)), int(round(my)))
        ring = max(24, int(round(radius * 2.0)))
        cv2.circle(image, center, ring, (7, 7, 10), 6, cv2.LINE_AA)
        cv2.circle(image, center, ring, (60, 60, 255), 3, cv2.LINE_AA)

    src = tuple(int(round(v)) for v in cmd_stats["centroid_px"])
    cv2.circle(image, src, 7, (236, 216, 0), -1, cv2.LINE_AA)
    if act_stats is not None:
        dst = tuple(int(round(v)) for v in act_stats["centroid_px"])
        cv2.circle(image, dst, 7, (255, 255, 255), -1, cv2.LINE_AA)
        if src != dst:
            cv2.arrowedLine(image, src, dst, (7, 7, 10), 6, cv2.LINE_AA, tipLength=0.25)
            cv2.arrowedLine(image, src, dst, (0, 255, 255), 3, cv2.LINE_AA, tipLength=0.25)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(out_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 2]))


def measure_scrape_offset(
    summary_path: Path | str,
    cfg: GCodeCfg,
    *,
    search_margin_cm: float = _DEFAULT_SEARCH_MARGIN_CM,
) -> dict[str, Any]:
    """测「指令 vs 实刮」位置误差, 返回 Δ + 建议 plate_origin + 可信度判据。

    参数:
        summary_path: 本次刮取所用 summary.json(其同目录即 case_dir)
        cfg: 运行期实时 gcode 配置(与 cnc_path 同源), 供推算建议 plate_origin
        search_margin_cm: 实刮掩膜搜索窗 = 指令扫掠区外扩此距离; 窗外变化计入 stray 不进质心

    返回:
        dict, 关键键: ok / trustworthy / dx_cm / dy_cm / suggested_plate_origin_x/y /
        checks(逐条可信度判据) / dx_agree_cm / dy_agree_cm(逐轴估计器分歧) /
        minor_count / minor_area_px(被剔除的碎屑) / annotated_name / message
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    case_dir = Path(summary_path).parent
    before_path = case_dir / "after_normalized.jpg"      # 刮前(视觉/手绘的归一化底图)
    scraped_path = case_dir / "scraped_normalized.jpg"   # 刮后(replay_normalization 回放产出)
    for path, why in ((before_path, "刮前归一化帧"), (scraped_path, "刮后归一化帧")):
        if not path.is_file():
            raise FileNotFoundError(f"缺少 {path.name}({why}); 帧契约未成立, 拒绝测量")

    payload = _load_payload(case_dir)
    plate_bbox_px = payload.get("plate_bbox_px")
    plate_size_cm = float(payload.get("plate_size_cm") or 20.0)
    if plate_bbox_px is None:
        raise ValueError("preview_payload 缺少 plate_bbox_px, 无法把像素位移换算成板 cm")

    before = cv2.imread(str(before_path), cv2.IMREAD_COLOR)
    scraped = cv2.imread(str(scraped_path), cv2.IMREAD_COLOR)
    if before is None or scraped is None:
        raise ValueError("刮前/刮后归一化帧读取失败(文件损坏或非图像)")
    if before.shape != scraped.shape:
        raise ValueError(
            f"刮前/刮后帧尺寸不一致({before.shape[:2]} vs {scraped.shape[:2]}); 回放链已破, 拒绝测量")

    bx, by, bw, bh = plate_coords.plate_bbox_xywh(plate_bbox_px)
    px_per_cm = bw / plate_size_cm
    plate_rect = (int(round(bx)), int(round(by)), int(round(bw)), int(round(bh)))

    cmd_mask = _commanded_mask(before.shape, payload)
    cutter_px = max(1.0, float(payload.get("cutter_width_px") or 1.0))
    act_raw, level, _diff = _diff_mask(before, scraped, plate_rect, int(round(cutter_px / 3.0)))

    # 搜索窗: 指令扫掠区外扩 search_margin_cm; 窗外的变化不进质心(但计入 stray 供告警)
    margin_px = max(1, int(round(search_margin_cm * px_per_cm)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin_px * 2 + 1, margin_px * 2 + 1))
    search_mask = cv2.dilate(cmd_mask, kernel)
    window_mask = cv2.bitwise_and(act_raw, search_mask)
    outside_mask = cv2.bitwise_and(act_raw, cv2.bitwise_not(search_mask))

    cmd_stats = _mask_stats(cmd_mask)
    if cmd_stats is None:
        raise ValueError("指令扫掠区为空(scrape_px 退化), 无法比对")

    # 窗内按面积拆分: 够大的才是刮痕(进质心与块数判据), 碎块剔除但如实记账
    min_component_px = max(1, int(round(cmd_stats["area_px"] * _MIN_COMPONENT_RATIO)))
    act_mask, minor_mask, kept_count, minor_count = _split_components(
        window_mask, min_component_px)
    act_stats = _mask_stats(act_mask)

    minor_area_px = int(cv2.countNonZero(minor_mask))
    result: dict[str, Any] = {
        "ok": False,
        "trustworthy": False,
        "case_dir": str(case_dir),
        "diff_level": round(level, 1),
        "px_per_cm": round(px_per_cm, 3),
        "commanded": cmd_stats,
        "actual": act_stats,
        # stray = **所有未采纳的变化面积** = 窗外杂痕 + 窗内被剔除的碎块。
        # 单块碎屑不足以带偏 Δ, 但"满板碎屑"必须有人管 —— 由 stray_ratio 一条兜住,
        # 不为此新增第五条判据(每多一条判据就多一条整轮作废的路)。
        "stray_area_px": int(cv2.countNonZero(outside_mask)) + minor_area_px,
        "outside_area_px": int(cv2.countNonZero(outside_mask)),
        "minor_area_px": minor_area_px,
        "minor_count": minor_count,
        "min_component_px": min_component_px,
        "checks": {},
        "message": "",
    }

    # 出图在分叉之前 —— 未检出那档同样要有图。原先它排在成功分支末尾, 于是"存疑"有图、
    # "未检出"没图, 恰好把最需要看现场的一档给漏了 (2026-07-27 CALIB-...101716 实例)。
    out_name = "scrape_offset.png"
    try:
        rendered = _render_overlay(scraped, cmd_mask, act_mask, minor_mask,
                                   cmd_stats, act_stats, case_dir / out_name)
        result["annotated_name"] = out_name if rendered else ""
    except Exception as exc:  # noqa: BLE001 出图失败不影响数值结论
        log.warning("[offset] 测量叠加图渲染失败(不影响数值): %s", exc)
        result["annotated_name"] = ""

    if act_stats is None:
        result["message"] = (
            f"指令区附近未检出刮痕(灰度差阈值 {level:.0f})。"
            "可能板面在指令区已有旧痕(非空白牺牲板, 前后帧同样黑 → 差分无信号)、"
            "本次未真刮、刮痕过浅, 或实际位置偏出搜索窗 "
            f"{search_margin_cm}cm — 可调大搜索窗重测。"
            + (f" (窗内另有 {minor_count} 块碎屑共 {minor_area_px}px, 均不足指令面积的 "
               f"{_MIN_COMPONENT_RATIO:.0%}, 已剔除)" if minor_count else "")
        )
        return result

    # 质心Δ 为主, bbox 中心Δ 为交叉校验(两者分歧大 = 检出残缺/不对称)
    dx_cm, dy_cm = _delta_cm(
        cmd_stats["centroid_px"], act_stats["centroid_px"], plate_bbox_px, plate_size_cm)
    bdx_cm, bdy_cm = _delta_cm(
        cmd_stats["bbox_center_px"], act_stats["bbox_center_px"], plate_bbox_px, plate_size_cm)

    # 逐边偏移分解 → 拉伸指纹: 平移时四边同偏, 拉伸时两端不等(见 _STRETCH_WARN_CM 注释)。
    # 图像上沿 = 板高 y 沿(翻转在 _delta_cm 内), 故 (bbox y0) 对出来的是 dy_top。
    cbx, cby, cbw, cbh = cmd_stats["bbox_px"]
    abx, aby, abw, abh = act_stats["bbox_px"]
    dx_left_cm, dy_top_cm = _delta_cm((cbx, cby), (abx, aby), plate_bbox_px, plate_size_cm)
    dx_right_cm, dy_bottom_cm = _delta_cm(
        (cbx + cbw, cby + cbh), (abx + abw, aby + abh), plate_bbox_px, plate_size_cm)
    stretch_x_cm = dx_right_cm - dx_left_cm      # 正 = 实刮比指令宽
    stretch_y_cm = dy_top_cm - dy_bottom_cm      # 正 = 实刮比指令高

    area_ratio = act_stats["area_px"] / max(1, cmd_stats["area_px"])
    # 逐轴分歧单独留存: 合量判据不变, 但两轴的可信度天差地别(扁带时代 dx 分歧 0.90cm 而 dy 仅 0.01),
    # 只报合量会把"哪个轴不能信"这条关键信息糊掉, 面板需要逐轴数来提示操作员
    dx_agree_cm = abs(dx_cm - bdx_cm)
    dy_agree_cm = abs(dy_cm - bdy_cm)
    agree_cm = float(np.hypot(dx_agree_cm, dy_agree_cm))
    stray_ratio = result["stray_area_px"] / max(1, act_stats["area_px"])

    checks = {
        "area_ratio": {
            "value": round(area_ratio, 3), "pass": _MIN_AREA_RATIO <= area_ratio <= _MAX_AREA_RATIO,
            "hint": f"实刮/指令 面积比应在 [{_MIN_AREA_RATIO}, {_MAX_AREA_RATIO}]; 越界=检出残缺或糊开",
        },
        "centroid_agreement_cm": {
            "value": round(agree_cm, 3), "pass": agree_cm <= _CENTROID_AGREE_CM,
            "hint": f"质心Δ 与 bbox中心Δ 的分歧应 ≤ {_CENTROID_AGREE_CM}cm; 超出=刮痕检出不对称",
        },
        "component_count": {
            "value": kept_count, "pass": kept_count == 1,
            "hint": (f"搜索窗内达标(≥指令面积{_MIN_COMPONENT_RATIO:.0%})的连通刮痕应恰好 1 块; "
                     "多块=真有杂痕混入或刮痕断开。更小的碎屑已剔除并计入未采纳面积"),
        },
        "stray_ratio": {
            "value": round(stray_ratio, 3), "pass": stray_ratio <= 0.25,
            "hint": "未采纳的变化面积(窗外杂痕+窗内碎屑)占比应 ≤0.25; 偏大=板面另有痕迹, Δ 可能被带偏",
        },
    }
    result["checks"] = checks
    result["trustworthy"] = all(c["pass"] for c in checks.values())

    ox, oy = suggest_plate_origin(dx_cm, dy_cm, cfg)
    result.update({
        "ok": True,
        "dx_cm": round(dx_cm, 4), "dy_cm": round(dy_cm, 4),
        "dx_mm": round(dx_cm * 10.0, 3), "dy_mm": round(dy_cm * 10.0, 3),
        "bbox_dx_cm": round(bdx_cm, 4), "bbox_dy_cm": round(bdy_cm, 4),
        "dx_agree_cm": round(dx_agree_cm, 4), "dy_agree_cm": round(dy_agree_cm, 4),
        "dx_left_cm": round(dx_left_cm, 4), "dx_right_cm": round(dx_right_cm, 4),
        "dy_top_cm": round(dy_top_cm, 4), "dy_bottom_cm": round(dy_bottom_cm, 4),
        "stretch_x_cm": round(stretch_x_cm, 4), "stretch_y_cm": round(stretch_y_cm, 4),
        "origin_x_mm": cfg.plate_origin_x, "origin_y_mm": cfg.plate_origin_y,
        "suggested_plate_origin_x": ox, "suggested_plate_origin_y": oy,
    })

    failed = [k for k, c in checks.items() if not c["pass"]]
    result["message"] = (
        f"实刮相对指令 Δ=({dx_cm:.3f}, {dy_cm:.3f}) cm"
        f", 逐轴估计器分歧 dx±{dx_agree_cm:.3f} / dy±{dy_agree_cm:.3f} cm。"
        + (f"已剔除 {minor_count} 块面积不足的碎屑({minor_area_px}px)。" if minor_count else "")
        + ("全部可信度判据通过。" if not failed else f"可信度存疑 — 未通过: {', '.join(failed)}。")
    )
    if abs(stretch_x_cm) > _STRETCH_WARN_CM or abs(stretch_y_cm) > _STRETCH_WARN_CM:
        result["message"] += (
            f"⚠ 实刮图案相对指令存在拉伸: 宽差 {stretch_x_cm * 10.0:+.1f}mm"
            f"(左端偏 {dx_left_cm * 10.0:+.1f} / 右端偏 {dx_right_cm * 10.0:+.1f}mm), "
            f"高差 {stretch_y_cm * 10.0:+.1f}mm。拉伸不是平移 —— 优先怀疑板框(plate_bbox)"
            "被照明削边致 px↔cm 比例失真(核对板框纵横比), 其次刮取过程中板/机床位置跳变; "
            "本轮 Δ 含失真分量, 不宜采纳。"
        )
    return result
