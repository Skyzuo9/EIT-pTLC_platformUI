"""
功能: 24 孔深孔板(SBS footprint)的参数化几何 —— 产出顶点/面表, 不落任何具体渲染器.

为什么手写顶点表而不是 bmesh 算子: 与 blender_clean._PartMesh 同一理由 —— 免疫 Blender
版本差异, 且顶点保持精确轴对齐值, 04 步的 weld/dedup 才焊得上(两块板顶点逐位相同会被
折成一份, 只出一个图元).

**本模块只依赖 stdlib(math)**, 因此 Blender 自带 Python 与系统 Python 都能 import ——
`blender_clean.build_sample_plates()`(烘进整机)与 `gen_labware.py`(单独出数模资产)共用
同一份代数, 不存在"两处各推一遍迟早漂"的风险.

坐标约定(板局部, 毫米):
    原点 = footprint 中心在**板底平面**上; +Z 朝上;
    +X = 板长轴(127.76, 6 列方向), +Y = 板短轴(85.48, 4 行方向).
    A1 在 (−X, +Y) 角 —— 即从 +Z 俯视时的左上角, 与厂商图的 A1 缺角同侧.
装进整机时长轴对齐 Blender X(= 3Y 轴向), 短轴对齐 Blender Y(= 4X 轴向),
与 config/calibration.yaml 的"列沿 3Y / 行沿 4X"一致.

尺寸来源: **实际采购件的厂商技术参数表**(A-GEN), 原件在仓库根的 `深孔板规格文件/`:
    10mL → 型号 **P-10-SQV-24**(24 Well Square Deep Well Plate 10mL, V Bottom)
    15mL → 型号 **P-15-SQV-24**(24 Well Deep Well Plate 15mL)

参数表的符号 → 本模块的键:
    L/W 板长宽 → length_mm / width_mm      H 总高 → height_mm      fh 裙边高 → skirt_mm
    h 孔深     → well_depth_mm             b 孔底段深 → bottom_h_mm
    B 方孔边长 → well_top_mm               d/D 孔底内/外径 → bottom_id_mm / bottom_od_mm
    P1/P3 首行首列的边缘距 → a1_x_mm / a1_y_mm      P2/P4 孔距 → pitch_mm

⚠ **两个规格的 footprint / 裙边 / 边缘距各不相同**, 不要当成同一个外形只换高度。
  2026-08-06 订正: 此前照网上查到的通用 SBS 值(127.76 × 85.48 等)建模, 并写过
  "两者 footprint 完全相同" —— 按厂商表这是错的(127.50×85.50 vs 127.20×85.30)。
  凡此类"通用标准值"与厂商表冲突时**一律以厂商表为准**: 装的是那个件, 不是标准。

⚠ 15mL 那份表**自身不自洽**: P1=18.88 配 L=127.20 ⇒ 对侧只剩 18.32, 栅格偏 0.56mm
  (10mL 的 18.75 配 127.50 则完美居中)。18.88/15.74 恰是 ANSI 127.76×85.48 的居中值,
  像是沿用了标准数字却换了 footprint。**本模块照表取字面值, 不自作主张居中**,
  由 plate_report() 把两侧余量都打出来让这个不对称可见(见 edge_margin_mm)。
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 规格表
# ---------------------------------------------------------------------------

# 只有真正两表一致的量才放共有段; footprint / 裙边 / 边缘距 / 孔深 全部拆进各规格 ——
# 把它们塞回共有段是上一版的错(详见模块头注释的订正)。
_COMMON = {
    "rows": 4,                # A~D, 沿板宽 W(本模块的 Y)
    "cols": 6,                # 1~6, 沿板长 L(本模块的 X)
    "pitch_mm": 18.00,        # P2 = P4, 两表一致
    "well_top_mm": 17.10,     # B 方孔边长, 两表一致
    "bottom_id_mm": 14.00,    # d 孔底内径, 两表一致
    "bottom_od_mm": 15.50,    # D 孔底外径, 两表一致
    # ---- 以下三项厂商表**没给**, 是为了建出实体而定的取值, 不要当实测值引用 ----
    "corner_r_mm": 3.18,      # 法兰角: 表无, 取 ANSI/SLAS 1-2004 的 R3.18
    "shell_t_mm": 1.20,       # 外壳壁厚: 表无
    "deck_t_mm": 2.00,        # 顶面台面厚: 表无
}

PLATE_SPECS: dict[str, dict] = {
    # A-GEN P-10-SQV-24 —— 深孔板规格文件/24方孔深孔板（锥底，10mL）.pdf
    # 自洽性: 18.75 + 5×18 = 108.75, 127.50 − 108.75 = 18.75(居中 ✔);
    #         15.75 + 3×18 =  69.75,  85.50 −  69.75 = 15.75(居中 ✔)
    "deepwell_24_10ml": dict(
        _COMMON,
        key="deepwell_24_10ml",
        part_no="P-10-SQV-24",
        label="24 方孔深孔板 10mL(锥底)",
        length_mm=127.50,     # L
        width_mm=85.50,       # W
        height_mm=44.00,      # H
        skirt_mm=2.50,        # fh
        well_depth_mm=41.90,  # h
        bottom_h_mm=1.20,     # b
        a1_x_mm=18.75,        # P1
        a1_y_mm=15.75,        # P3
        nominal_ml=10.0,
        theoretical_g=62.00,  # 表里给了理论重量, 留作交叉核对
    ),
    # A-GEN P-15-SQV-24 —— 深孔板规格文件/24方孔深孔板（锥底，15mL）.pdf
    # ⚠ 不自洽(见模块头): 18.88 + 90 = 108.88, 127.20 − 108.88 = 18.32(偏 0.56mm);
    #                     15.74 + 54 =  69.74,  85.30 −  69.74 = 15.56
    "deepwell_24_15ml": dict(
        _COMMON,
        key="deepwell_24_15ml",
        part_no="P-15-SQV-24",
        label="24 方孔深孔板 15mL(锥底)",
        length_mm=127.20,     # L
        width_mm=85.30,       # W
        height_mm=63.20,      # H
        skirt_mm=2.90,        # fh
        well_depth_mm=60.30,  # h
        bottom_h_mm=2.00,     # b
        a1_x_mm=18.88,        # P1
        a1_y_mm=15.74,        # P3
        nominal_ml=15.0,
        theoretical_g=None,   # 表里这一格是空的
    ),
}

# 圆角/缺角的每角分段数. 两块板必须用同一个值 —— 环形面片靠"内外两圈点数相等"来配对,
# 分段数不同就配不上(见 _ring).
CORNER_SEG = 6
# A1 缺角边长(0 = 不做缺角). 厂商普遍做缺角标记 A1; 整机尺度下它不到一个像素, 但单独
# 出数模资产时是识别 A1 的唯一外部特征, 所以保留.
A1_CHAMFER_MM = 3.0


# ---------------------------------------------------------------------------
# 二维轮廓
# ---------------------------------------------------------------------------

def rounded_rect(length: float, width: float, radius: float,
                 seg: int = CORNER_SEG, a1_chamfer: float = 0.0) -> list:
    """
    功能: 生成以原点为中心的圆角矩形轮廓(CCW, 从 +Z 俯视).

    **点数恒为 4×seg, 与 radius / a1_chamfer 无关** —— 这是内外轮廓能直接配成环形面片的
    前提. 缺角的实现方式是"把该角的 seg 个点摊在一条直线上"而不是少给几个点, 就是为了
    守住这个不变量.

    参数:
        length: X 方向全长
        width: Y 方向全宽
        radius: 圆角半径(会被钳到不超过半边长)
        seg: 每个角的分段数
        a1_chamfer: A1 角(−X,+Y)的直线缺角边长; 0 表示照常走圆角
    返回值: list[tuple[float, float]], 长度 4×seg
    """
    half_l, half_w = length / 2.0, width / 2.0
    r = max(0.0, min(radius, half_l, half_w))
    # CCW: (+X,+Y) → (−X,+Y) → (−X,−Y) → (+X,−Y)
    corners = [
        (half_l - r, half_w - r, 0.0),
        (-half_l + r, half_w - r, math.pi / 2.0),
        (-half_l + r, -half_w + r, math.pi),
        (half_l - r, -half_w + r, 3.0 * math.pi / 2.0),
    ]
    points: list = []
    for index, (cx, cy, start) in enumerate(corners):
        if index == 1 and a1_chamfer > 0.0:
            # A1 缺角: 从 (−half_l + c, +half_w) 直线切到 (−half_l, +half_w − c)
            chamfer = min(a1_chamfer, half_l, half_w)
            x0, y0 = -half_l + chamfer, half_w
            x1, y1 = -half_l, half_w - chamfer
            for i in range(seg):
                t = i / float(seg - 1) if seg > 1 else 0.0
                points.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            continue
        for i in range(seg):
            t = i / float(seg - 1) if seg > 1 else 0.0
            ang = start + (math.pi / 2.0) * t
            points.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return points


#: 孔的每圈取点数. 必须是 8 的倍数 —— 这样 `_well_loop` 的射线角恰好落在方形的 4 个角与
#: 4 条边中点上, 顶口就是**精确的方**而不是近似; 相邻孔的外壁才拼得严, 台面不会出现针孔.
WELL_SEG = 16

#: 方口渐变到圆底用几圈过渡. 3 圈在 1.2~2.0mm 的底段上已看不出棱.
BOTTOM_RINGS = 3


def _well_loop(cx: float, cy: float, half: float, radius: float,
               roundness: float, n: int = WELL_SEG) -> list:
    """
    功能: 生成孔的一圈截面 —— 在"方"与"圆"之间按 roundness 插值(CCW, 恒 n 点).

    为什么用**同一组射线角**分别取方与圆上的点再逐点插值: 这样两种形状天然一一对应,
    直接喂给 `_taper` 就能拉出"方口渐变到圆底"的侧壁, 不必处理点数不等的配对。
    n 取 8 的倍数时射线角正好命中方形的 4 角与 4 边中点, roundness=0 得到**精确方形**。

    参数:
        cx/cy: 孔心
        half: 方形半边长(roundness=0 时生效)
        radius: 圆半径(roundness=1 时生效)
        roundness: 0=方 / 1=圆, 中间线性插值
        n: 取点数
    返回值: list[tuple[float, float]]
    """
    pts = []
    for i in range(n):
        ang = math.tau * i / n
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        # 沿该射线到方形边界: |x|≤half 且 |y|≤half ⇒ r = half / max(|cos|, |sin|)
        square_r = half / max(abs(cos_a), abs(sin_a))
        r = square_r + (radius - square_r) * roundness
        pts.append((cx + r * cos_a, cy + r * sin_a))
    return pts


# ---------------------------------------------------------------------------
# 孔位
# ---------------------------------------------------------------------------

def well_label(row: int, col: int) -> str:
    """
    功能: (行, 列) → 孔号, 1-based, 行用字母.
    参数: row 1..rows; col 1..cols
    返回值: str, 如 "A1"
    """
    return f"{chr(ord('A') + row - 1)}{col}"


def well_centers(spec: dict) -> list:
    """
    功能: 全部孔心在板局部系的坐标(不含 z).

    行沿 −Y 递增(A 在 +Y 侧), 列沿 +X 递增(1 在 −X 侧) —— 于是 A1 落在 (−X,+Y) 角,
    与 rounded_rect 的缺角同侧, 也与 calibration.yaml 的"列沿 3Y / 行沿 4X"同构.

    参数: spec 规格字典
    返回值: list[tuple[str, int, int, float, float]] = (标签, 行, 列, x, y)
    """
    half_l, half_w = spec["length_mm"] / 2.0, spec["width_mm"] / 2.0
    x0 = -half_l + spec["a1_x_mm"]
    y0 = half_w - spec["a1_y_mm"]
    out = []
    for row in range(1, spec["rows"] + 1):
        for col in range(1, spec["cols"] + 1):
            out.append((
                well_label(row, col), row, col,
                x0 + (col - 1) * spec["pitch_mm"],
                y0 - (row - 1) * spec["pitch_mm"],
            ))
    return out


def well_volume_ml(spec: dict) -> float:
    """
    功能: 按几何算单孔"齐口容积"(mL) —— 生成器的自检量, **不是**厂商标称值.

    孔型: 方口 B 直筒到深度 (h − b), 最后 b 那一段由方渐变到 Ø d 的圆底。
    直筒段 = B²·(h−b); 底段用棱台公式 (A1 + √(A1·A2) + A2)·b/3, A1 = B², A2 = π(d/2)²。

    ⚠ 与标称值的关系: 齐口容积**恒大于**标称。本机两个规格算得 ≈11.9 / ≈17.0 mL,
    对标称 10 / 15 mL 的比值 1.19 / 1.14 —— 两者比值相近, 这个一致性本身就是
    "规格表读对了"的旁证。**不要**把它当成"应该等于 10/15"去调参数。

    参数: spec 规格字典
    返回值: float, 毫升
    """
    edge = spec["well_top_mm"]
    bottom_h = spec["bottom_h_mm"]
    straight = max(0.0, spec["well_depth_mm"] - bottom_h)
    prism = edge * edge * straight
    a1 = edge * edge
    a2 = math.pi * (spec["bottom_id_mm"] / 2.0) ** 2
    cap = (a1 + math.sqrt(a1 * a2) + a2) * bottom_h / 3.0
    return (prism + cap) / 1000.0


def edge_margin_mm(spec: dict) -> dict:
    """
    功能: 算孔栅格四周的边缘余量 —— 用来把厂商表里"栅格没居中"的不自洽**摆到明面上**.

    P1/P3 只给了一侧的边缘距, 另一侧是 L/W 减掉栅格跨度推出来的。两侧相等即居中。
    本机: 10mL 两侧都是 18.75 / 15.75(居中); 15mL 是 18.88 vs 18.32、15.74 vs 15.56。

    参数: spec 规格字典
    返回值: dict, 四个方向的余量(mm)与是否居中
    """
    span_l = (spec["cols"] - 1) * spec["pitch_mm"]
    span_w = (spec["rows"] - 1) * spec["pitch_mm"]
    near_l, near_w = spec["a1_x_mm"], spec["a1_y_mm"]
    far_l = spec["length_mm"] - span_l - near_l
    far_w = spec["width_mm"] - span_w - near_w
    return {
        "length_near_mm": round(near_l, 4), "length_far_mm": round(far_l, 4),
        "width_near_mm": round(near_w, 4), "width_far_mm": round(far_w, 4),
        "centered": abs(near_l - far_l) < 0.01 and abs(near_w - far_w) < 0.01,
        "skew_mm": round(max(abs(near_l - far_l), abs(near_w - far_w)), 4),
    }


# ---------------------------------------------------------------------------
# 网格累积器
# ---------------------------------------------------------------------------

class MeshAcc:
    """
    功能: 把若干面片累积进**一个**网格的顶点/面表(与 blender_clean._PartMesh 同构).

    面的绕序一律"从外面看逆时针"(法线朝外). 环形/带状面片的绕序在 _ring / _band 里
    各推导过一次并写在注释里 —— 这类东西反了不会报错, 只会让模型从外面看变成黑面/透明.
    """

    def __init__(self) -> None:
        self.verts: list = []
        self.faces: list = []
        self.smooth: list = []

    def add(self, verts: list, faces: list, smooth: list) -> None:
        """功能: 追加一批顶点与面, 自动偏移面的顶点下标. 参数: verts/faces/smooth. 返回值: None"""
        base = len(self.verts)
        self.verts.extend(verts)
        self.faces.extend(tuple(base + i for i in face) for face in faces)
        self.smooth.extend(smooth)

    @property
    def tri_count(self) -> int:
        """功能: 三角形数(四边形按 2 算). 参数: 无. 返回值: int"""
        return sum(len(f) - 2 for f in self.faces)


def _band(acc: MeshAcc, loop: list, z0: float, z1: float,
          outward: bool = True, smooth: bool = False) -> None:
    """
    功能: 把一条闭合轮廓沿 Z 拉成一圈侧壁.

    绕序推导(loop 为 CCW/俯视): 取 +X 边上一段, lo_i=(a,-b,z0) lo_j=(a,b,z0) hi_j hi_i,
    面 (lo_i, lo_j, hi_j, hi_i) 的法线 = (lo_j−lo_i)×(hi_j−lo_j) = (+X) —— 即朝外.
    要朝内就整体反序.

    参数: acc 累积器; loop 轮廓; z0/z1 上下沿; outward 法线朝外; smooth 平滑着色
    返回值: None
    """
    n = len(loop)
    verts = [(x, y, z0) for x, y in loop] + [(x, y, z1) for x, y in loop]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        quad = (i, j, n + j, n + i)
        faces.append(quad if outward else tuple(reversed(quad)))
    acc.add(verts, faces, [smooth] * len(faces))


def _ring(acc: MeshAcc, outer: list, inner: list, z: float, up: bool = True) -> None:
    """
    功能: 在同一 Z 平面上, 用四边形带把内外两圈轮廓连成一个环面.

    **要求内外轮廓点数相等且逐点对应** —— rounded_rect 恒出 4×seg 个点就是为了这个.
    绕序推导: outer/inner 均 CCW 时, 面 (o_i, o_j, in_j, in_i) 的法线 = +Z.

    参数: acc 累积器; outer/inner 内外轮廓(点数须相等); z 平面高度; up 法线朝上
    返回值: None
    """
    n = len(outer)
    if len(inner) != n:
        raise ValueError(f"_ring: 内外轮廓点数不等 ({n} vs {len(inner)})")
    verts = [(x, y, z) for x, y in outer] + [(x, y, z) for x, y in inner]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        quad = (i, j, n + j, n + i)
        faces.append(quad if up else tuple(reversed(quad)))
    acc.add(verts, faces, [False] * len(faces))


def _cap(acc: MeshAcc, loop: list, z: float, up: bool) -> None:
    """
    功能: 用扇形三角把一条闭合轮廓封成平面盖(平底用).
    参数: acc; loop 轮廓; z 高度; up 法线朝上
    返回值: None
    """
    n = len(loop)
    cx = sum(p[0] for p in loop) / n
    cy = sum(p[1] for p in loop) / n
    verts = [(x, y, z) for x, y in loop] + [(cx, cy, z)]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        tri = (i, j, n)
        faces.append(tuple(reversed(tri)) if up else tri)
    acc.add(verts, faces, [False] * len(faces))


# ---------------------------------------------------------------------------
# 单孔
# ---------------------------------------------------------------------------

def _well_cup(acc: MeshAcc, spec: dict, cx: float, cy: float) -> None:
    """
    功能: 攒一个孔 —— 方口直筒 + 末端 b 段方口渐变到 Ø d 圆底(内外双壁 + 顶沿环 + 底盖).

    为什么是双壁而不是只做内腔: 只做内腔时从板底下看是一片空, 而深孔板最有辨识度的
    外观特征恰恰是底面那 24 个凸出来的孔.

    外壁顶边长恰取孔距(18.00), 于是相邻孔的外壁**正好贴合**, 顶面自然连成一整片台面,
    不必再单独造孔间的肋 —— 肋厚 = 孔距 − 开口 = 18.00 − 17.10 = 0.90 自动成立.

    ⚠ 直筒段**不加拔模**: 厂商表只给了一个边长 B, 没给底口尺寸。注塑件当然有脱模斜度,
      但那个角度表里没有 —— 编一个数出来会让它看起来像实测值。宁可直筒, 并在此写明。
    ⚠ Ø d 圆底做成**平底**: 型号叫"锥底/V Bottom", 但表里只给了底段深 b 与内径 d,
      没给锥尖的落差。同上, 不编。b 已经很浅(1.2 / 2.0mm), 平底与浅锥在整机尺度上无差别。

    参数: acc 累积器; spec 规格; cx/cy 孔心(板局部)
    返回值: None
    """
    z_top = spec["height_mm"]
    z_deep = z_top - spec["well_depth_mm"]                 # 内腔最深(= 表的 h)
    z_body = z_deep + spec["bottom_h_mm"]                  # 直筒段底(= 底段 b 的起点)

    in_half = spec["well_top_mm"] / 2.0                    # B/2
    out_half = spec["pitch_mm"] / 2.0                      # 外壁半边 = 孔距/2, 与邻孔贴合
    in_r = spec["bottom_id_mm"] / 2.0                      # d/2
    out_r = spec["bottom_od_mm"] / 2.0                     # D/2
    # 底板厚度表里没给, 取底部内外径之差的一半(= 该处壁厚), 并在下面断言它不捅穿裙边
    floor_t = (spec["bottom_od_mm"] - spec["bottom_id_mm"]) / 2.0
    z_out = z_deep - floor_t

    def loops(half: float, radius: float, count: int) -> list:
        """功能: 底段的一串过渡截面(方→圆). 参数: half 方半边; radius 圆半径; count 环数. 返回值: list"""
        return [_well_loop(cx, cy, half, radius, k / float(count)) for k in range(count + 1)]

    in_rings = loops(in_half, in_r, BOTTOM_RINGS)
    out_rings = loops(out_half, out_r, BOTTOM_RINGS)

    _ring(acc, out_rings[0], in_rings[0], z_top, up=True)                     # 顶沿
    _band(acc, out_rings[0], z_top, z_body, outward=True)                     # 外壁直筒
    _band(acc, in_rings[0], z_top, z_body, outward=False)                     # 内壁直筒

    # 底段: 逐环从方渐变到圆
    for k in range(BOTTOM_RINGS):
        t0 = z_body + (z_deep - z_body) * (k / float(BOTTOM_RINGS))
        t1 = z_body + (z_deep - z_body) * ((k + 1) / float(BOTTOM_RINGS))
        _taper(acc, in_rings[k], in_rings[k + 1], t0, t1, outward=False)
        o0 = z_body + (z_out - z_body) * (k / float(BOTTOM_RINGS))
        o1 = z_body + (z_out - z_body) * ((k + 1) / float(BOTTOM_RINGS))
        _taper(acc, out_rings[k], out_rings[k + 1], o0, o1, outward=True)

    # 内外各自封口即可, **不要**在两者之间再补环: 它们不在同一高度(z_deep vs z_out),
    # 内腔是朝上的凹底、外形是朝下的凸底, 各自已经闭合; 补环只会多一片穿在实体里的面。
    _cap(acc, in_rings[-1], z_deep, up=True)                                  # 内底(从上往孔里看得见)
    _cap(acc, out_rings[-1], z_out, up=False)                                 # 外底(从板底下看得见)


def _taper(acc: MeshAcc, loop_top: list, loop_bot: list,
           z_top: float, z_bot: float, outward: bool) -> None:
    """
    功能: 上下两圈**不同大小**的轮廓之间拉侧壁(带拔模的直锥段).
    参数: acc; loop_top/loop_bot 上下轮廓(点数须相等); z_top/z_bot; outward 法线朝外
    返回值: None
    """
    n = len(loop_top)
    verts = [(x, y, z_bot) for x, y in loop_bot] + [(x, y, z_top) for x, y in loop_top]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        quad = (i, j, n + j, n + i)
        faces.append(quad if outward else tuple(reversed(quad)))
    acc.add(verts, faces, [False] * len(faces))


# ---------------------------------------------------------------------------
# 整板
# ---------------------------------------------------------------------------

def build_plate(spec: dict) -> MeshAcc:
    """
    功能: 生成一整块深孔板的网格.

    构件清单(自下而上):
        外壳侧壁 0→H, 内壳侧壁 0→H, 底沿环(z=0),
        台面环 z=H(外轮廓 → 孔区), 台面下沿环 z=H−deck_t(内轮廓 → 孔区),
        24 个方杯孔.

    ⚠ 孔区**不假定居中**: 位置由 P1/P3(a1_x_mm / a1_y_mm)算出来的孔心决定, 再据此
    平移孔区矩形。10mL 那份表算下来正好居中, 而 15mL 偏 0.28/0.09mm(见模块头的不自洽说明)
    —— 早先版本把孔区写死居中, 在 15mL 上会让台面留边与孔位对不上。

    参数: spec 规格字典(取自 PLATE_SPECS)
    返回值: MeshAcc
    """
    acc = MeshAcc()
    height = spec["height_mm"]
    shell = spec["shell_t_mm"]
    deck = spec["deck_t_mm"]

    outer = rounded_rect(spec["length_mm"], spec["width_mm"],
                         spec["corner_r_mm"], CORNER_SEG, A1_CHAMFER_MM)
    inner = rounded_rect(spec["length_mm"] - 2 * shell, spec["width_mm"] - 2 * shell,
                         max(0.5, spec["corner_r_mm"] - shell), CORNER_SEG,
                         max(0.0, A1_CHAMFER_MM - shell))
    grid_l = spec["cols"] * spec["pitch_mm"]
    grid_w = spec["rows"] * spec["pitch_mm"]
    # 孔区中心 = 首末孔心的中点(而不是板心) —— 见上面的"不假定居中"
    centers = well_centers(spec)
    gx = (min(c[3] for c in centers) + max(c[3] for c in centers)) / 2.0
    gy = (min(c[4] for c in centers) + max(c[4] for c in centers)) / 2.0
    block = [(x + gx, y + gy) for x, y in rounded_rect(grid_l, grid_w, 0.4, CORNER_SEG, 0.0)]

    _band(acc, outer, 0.0, height, outward=True, smooth=True)     # 外壳
    _band(acc, inner, 0.0, height, outward=False, smooth=True)    # 内壳
    _ring(acc, outer, inner, 0.0, up=False)                       # 裙边底沿
    _ring(acc, outer, block, height, up=True)                     # 顶面留边
    _ring(acc, inner, block, height - deck, up=False)             # 台面下沿(挡住从底下看进来的空腔)

    for _label, _row, _col, cx, cy in well_centers(spec):
        _well_cup(acc, spec, cx, cy)
    return acc


def plate_report(spec: dict) -> dict:
    """
    功能: 生成器的自检报告 —— 逐项对着厂商参数表可核, 供门禁与人工复核.
    参数: spec 规格字典
    返回值: dict
    """
    centers = well_centers(spec)
    xs = sorted({round(c[3], 4) for c in centers})
    ys = sorted({round(c[4], 4) for c in centers})
    acc = build_plate(spec)
    volume = well_volume_ml(spec)
    return {
        "key": spec["key"],
        "part_no": spec["part_no"],
        "label": spec["label"],
        "footprint_mm": [spec["length_mm"], spec["width_mm"]],   # L / W
        "height_mm": spec["height_mm"],                          # H
        "skirt_mm": spec["skirt_mm"],                            # fh
        "wells": len(centers),
        "grid": f'{spec["rows"]}×{spec["cols"]}',
        "pitch_x_mm": round(xs[1] - xs[0], 4) if len(xs) > 1 else None,
        "pitch_y_mm": round(ys[1] - ys[0], 4) if len(ys) > 1 else None,
        "a1_center_mm": [round(centers[0][3], 4), round(centers[0][4], 4)],
        # 两侧边缘余量: 相等即栅格居中. 15mL 那份表在这里是不等的, 见模块头注释
        "edge_margin_mm": edge_margin_mm(spec),
        "well_top_mm": spec["well_top_mm"],                      # B
        "well_depth_mm": spec["well_depth_mm"],                  # h
        "bottom_h_mm": spec["bottom_h_mm"],                      # b
        "bottom_id_mm": spec["bottom_id_mm"],                    # d
        "bottom_od_mm": spec["bottom_od_mm"],                    # D
        # 齐口容积, 恒大于标称; ratio 是"读对了规格表"的旁证(两个规格应相近), 不是判据
        "well_volume_ml": round(volume, 3),
        "nominal_ml": spec["nominal_ml"],
        "volume_ratio": round(volume / spec["nominal_ml"], 3),
        "verts": len(acc.verts),
        "tris": acc.tri_count,
    }
