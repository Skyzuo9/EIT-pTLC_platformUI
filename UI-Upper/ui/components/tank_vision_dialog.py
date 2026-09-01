"""
TankVisionDialog — 液位检测单通道监控 Dialog

功能:
  - 左侧: MJPEG 实时画面 + Canvas 叠加层 (支持画线标定 + ROI 拖拽)
  - 右侧: 8 个检测参数控件, 即时下发 (滑块/下拉)
  - 底部: [应用全部] [保存到配置文件] [重置] [raw切换]
  - 打开时: stream_start + get_detect_param 并行发出
  - 关闭时: stream_stop + 清理

人工标定流程:
  1. [✏️ 手动标定] → MJPEG 切 raw 模式, Canvas 出现
  2. 用户沿硅胶板边沿画线 → 自动计算旋转角度 + 初始 ROI
  3. MQTT set_calibration → MJPEG 切 annotated 模式
  4. Canvas 显示 ROI 拖拽手柄, 用户微调
  5. [💾 确认] → save_calibration 持久化

依赖:
  - WaterLevelClient (core/water_level_client.py)
  - NiceGUI ui.html / ui.slider / ui.select / ui.button
"""

import asyncio
import logging
import math
import time
from typing import Optional

from nicegui import ui

from ui.state import get_state

log = logging.getLogger(__name__)

# 检测参数定义: {name: (label, type, range_or_options, default)}
PARAM_DEFS = {
    # 液位边缘检测 (高频)
    "water_edge_threshold":     ("边缘阈值",        "slider",  {"min": 0.0, "max": 100.0, "step": 0.5}, 10.0),
    "water_blur_ksize":         ("模糊核大小",      "select",  [1, 3, 5, 7, 9], 5),
    "water_sobely_ksize":       ("Sobel-Y 核",      "select",  [-1, 1, 3, 5, 7], -1),
    # 前沿对比验证 (新增)
    "front_contrast_threshold": ("对比度阈值",      "slider",  {"min": 0.02, "max": 0.80, "step": 0.01}, 0.12),
    "front_zone_width":         ("对比区宽度",      "slider",  {"min": 10, "max": 60, "step": 1}, 20),
    "front_zone_gap":           ("区隙间距",        "slider",  {"min": 1, "max": 10, "step": 1}, 3),
    # 信号显著性检验 (防止无信号时噪声误检)
    "water_snr_threshold":      ("SNR 阈值",        "slider",  {"min": 1.2, "max": 15.0, "step": 0.1}, 3.5),
    "water_diff_threshold":     ("差分均值下限",    "slider",  {"min": 0.0, "max": 50.0, "step": 0.5}, 5.0),
    # 流动方向
    "flow_direction":           ("流动方向",        "select",  ["bottom_to_top", "left_to_right", "right_to_left"], "left_to_right"),
    # 高级设置 (可折叠, 低频)
    "roi_crop_x":               ("ROI 裁剪 X",      "slider",  {"min": 0.0, "max": 0.45, "step": 0.01}, 0.10),
    "roi_crop_y":               ("ROI 裁剪 Y",      "slider",  {"min": 0.0, "max": 0.45, "step": 0.01}, 0.10),
    "roi_sobel_ksize":          ("ROI Sobel 核",    "select",  [-1, 1, 3, 5, 7], 5),
    "height_offset_cm":         ("高度偏移 (cm)",   "slider",  {"min": -50.0, "max": 50.0, "step": 0.1}, 0.0),
    "height_gain":              ("高度增益",        "slider",  {"min": 0.5, "max": 2.0, "step": 0.01}, 1.0),
    "front_arrival_frames":     ("前沿到达帧数",    "slider",  {"min": 10, "max": 300, "step": 5}, 30),
    "front_departure_frames":   ("前沿离开帧数",    "slider",  {"min": 10, "max": 600, "step": 5}, 60),
}

# 需要 debounce 的参数 (改变需重初始化算子, 开销较大)
_DEBOUNCE_PARAMS = {"roi_sobel_ksize", "water_sobely_ksize"}
_DEBOUNCE_MS = 0.2  # 200ms

# ROI 宽度默认值 (像素)
_DEFAULT_ROI_WIDTH_PX = 80

# ---- JavaScript: Canvas 标定交互 ----
# 注意：必须用 ui.run_javascript() 执行此 JS 体（真正 eval），
# 不能用 ui.add_head_html(<script>...) —— socket 已连接时 NiceGUI 走
# insertAdjacentHTML 注入，浏览器规范规定此方式插入的 <script> 不会执行，
# 导致 window._initCalibCanvas 等函数从未定义、Canvas 标定交互失效。
_CALIB_JS = """
(function() {
    window._calibCh = {};

    window._initCalibCanvas = function(chId) {
        var img = document.getElementById('mjpeg-ch' + chId);
        var canvas = document.getElementById('canvas-ch' + chId);
        var hint = document.getElementById('hint-ch' + chId);
        if (!img || !canvas) return;

        // 如果已存在状态但 DOM 元素已被重建（dialog 关闭再打开），
        // 删除旧状态强制重新初始化，否则事件监听器挂在已销毁的 DOM 上
        if (window._calibCh[chId] && window._calibCh[chId]._img !== img) {
            delete window._calibCh[chId];
        }
        if (window._calibCh[chId]) return;

        var st = {
            mode: 'none', line: null, roi: null,
            drawing: false, dragMode: null,
            dragStart: null, roiStart: null,
            imgW: 640, imgH: 480,
            _img: img,  // 记录关联的 DOM 元素，用于检测 dialog 重建
        };
        window._calibCh[chId] = st;
        canvas._st = st;

        // Prevent right-click gestures and context menu on the entire container
        var container = document.getElementById('calib-container-ch' + chId);
        if (container) {
            container.addEventListener('mousedown', function(e) {
                if (e.button === 2) { e.preventDefault(); e.stopPropagation(); }
            });
            container.addEventListener('contextmenu', function(e) {
                e.preventDefault(); return false;
            });
        }

        function getNaturalSize() {
            if (img.naturalWidth > 0) {
                st.imgW = img.naturalWidth;
                st.imgH = img.naturalHeight;
            } else {
                setTimeout(getNaturalSize, 500);
            }
        }

        function syncSize() {
            var r = img.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                canvas.width = r.width;
                canvas.height = r.height;
                canvas.style.width = r.width + 'px';
                canvas.style.height = r.height + 'px';
            }
        }

        function toImg(e) {
            // ★ 修正 object-fit:contain 导致的 letterboxing 坐标映射偏差。
            // getBoundingClientRect() 返回的是 img 元素的 CSS box，
            // 当 box 宽高比 ≠ 图像宽高比时，图像实际只在 box 的一部分区域渲染，
            // 简单按 box 尺寸线性映射会将留白区域也当成图像，导致角度测偏。
            var r = img.getBoundingClientRect();
            if (st.imgW <= 0 || st.imgH <= 0) {
                return { x: 0, y: 0 };
            }
            var imgAspect = st.imgW / st.imgH;
            var boxAspect = r.width / r.height;
            var renderW, renderH, offsetX = 0, offsetY = 0;

            if (imgAspect > boxAspect) {
                // 图像比 box 更宽 → 上下留白 (letterbox)
                renderW = r.width;
                renderH = r.width / imgAspect;
                offsetY = (r.height - renderH) / 2;
            } else {
                // 图像比 box 更高 → 左右留白 (pillarbox)
                renderH = r.height;
                renderW = r.height * imgAspect;
                offsetX = (r.width - renderW) / 2;
            }

            return {
                x: (e.clientX - r.left - offsetX) * st.imgW / renderW,
                y: (e.clientY - r.top  - offsetY) * st.imgH / renderH,
            };
        }

        function redraw() {
            var ctx = canvas.getContext('2d');
            var w = canvas.width, h = canvas.height;
            ctx.clearRect(0, 0, w, h);
            if (st.imgW <= 0) return;
            var sx = w / st.imgW, sy = h / st.imgH;

            if (st.line && (st.mode === 'line' || st.mode === 'roi')) {
                var lx1 = st.line.x1 * sx, ly1 = st.line.y1 * sy;
                var lx2 = st.line.x2 * sx, ly2 = st.line.y2 * sy;
                // glow
                ctx.strokeStyle = 'rgba(255,0,0,0.25)';
                ctx.lineWidth = 7; ctx.beginPath();
                ctx.moveTo(lx1, ly1); ctx.lineTo(lx2, ly2); ctx.stroke();
                // line
                ctx.strokeStyle = '#ff0000'; ctx.lineWidth = 3;
                ctx.beginPath();
                ctx.moveTo(lx1, ly1); ctx.lineTo(lx2, ly2); ctx.stroke();
                // endpoints
                [[lx1,ly1],[lx2,ly2]].forEach(function(p) {
                    ctx.fillStyle = '#ff0000';
                    ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, 2*Math.PI); ctx.fill();
                    ctx.fillStyle = '#ffffff';
                    ctx.beginPath(); ctx.arc(p[0], p[1], 3, 0, 2*Math.PI); ctx.fill();
                });
            }

            if (st.roi && (st.mode === 'roi' || st.mode === 'line')) {
                var rx = st.roi.x * sx, ry = st.roi.y * sy;
                var rw = st.roi.w * sx, rh = st.roi.h * sy;
                // fill
                ctx.fillStyle = 'rgba(0, 255, 255, 0.12)';
                ctx.fillRect(rx, ry, rw, rh);
                // border
                ctx.strokeStyle = '#00ffff'; ctx.lineWidth = 2;
                ctx.setLineDash([6, 3]);
                ctx.strokeRect(rx, ry, rw, rh);
                ctx.setLineDash([]);
                // corners
                ctx.fillStyle = '#00ffff';
                [[rx,ry],[rx+rw,ry],[rx,ry+rh],[rx+rw,ry+rh]].forEach(function(p) {
                    ctx.fillRect(p[0]-6, p[1]-6, 12, 12);
                });
            }
        }

        // --- Mouse handlers ---
        canvas.addEventListener('mousedown', function(e) {
            e.preventDefault();
            if (e.button !== 0) return;  // only handle left-click
            syncSize(); getNaturalSize();
            if (st.imgW <= 0) return;
            var pt = toImg(e);

            if (st.mode === 'line') {
                st.drawing = true;
                st.line = {x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y};
                redraw();
            } else if (st.mode === 'roi' && st.roi) {
                var sx = canvas.width / st.imgW, sy = canvas.height / st.imgH;
                var rx = st.roi.x * sx, ry = st.roi.y * sy;
                var rw = st.roi.w * sx, rh = st.roi.h * sy;
                var r = img.getBoundingClientRect();
                var mx = e.clientX - r.left, my = e.clientY - r.top;

                st.dragMode = null;
                var corners = [
                    [rx, ry, 'nw'], [rx+rw, ry, 'ne'],
                    [rx, ry+rh, 'sw'], [rx+rw, ry+rh, 'se'],
                ];
                for (var i = 0; i < 4; i++) {
                    if (Math.abs(mx - corners[i][0]) < 12 &&
                        Math.abs(my - corners[i][1]) < 12) {
                        st.dragMode = corners[i][2]; break;
                    }
                }
                if (!st.dragMode && mx >= rx && mx <= rx+rw &&
                    my >= ry && my <= ry+rh) {
                    st.dragMode = 'move';
                }
                if (st.dragMode) {
                    st.dragStart = {x: pt.x, y: pt.y};
                    st.roiStart = {x: st.roi.x, y: st.roi.y,
                                   w: st.roi.w, h: st.roi.h};
                }
            }
        });

        canvas.addEventListener('mousemove', function(e) {
            e.preventDefault();
            syncSize();
            if (st.imgW <= 0) return;
            var pt = toImg(e);

            if (st.mode === 'line' && st.drawing) {
                st.line.x2 = pt.x; st.line.y2 = pt.y;
                redraw();
            } else if (st.mode === 'roi' && st.dragMode && st.roiStart) {
                var dx = pt.x - st.dragStart.x;
                var dy = pt.y - st.dragStart.y;
                var r = st.roiStart;
                var nx = r.x, ny = r.y, nw = r.w, nh = r.h;

                if (st.dragMode === 'nw') {
                    nx = r.x + dx; ny = r.y + dy;
                    nw = r.w - dx; nh = r.h - dy;
                } else if (st.dragMode === 'ne') {
                    ny = r.y + dy; nw = r.w + dx; nh = r.h - dy;
                } else if (st.dragMode === 'sw') {
                    nx = r.x + dx; nw = r.w - dx; nh = r.h + dy;
                } else if (st.dragMode === 'se') {
                    nw = r.w + dx; nh = r.h + dy;
                } else if (st.dragMode === 'move') {
                    nx = r.x + dx; ny = r.y + dy;
                }

                nw = Math.max(20, Math.min(nw, st.imgW - nx));
                nh = Math.max(20, Math.min(nh, st.imgH - ny));
                nx = Math.max(0, Math.min(nx, st.imgW - nw));
                ny = Math.max(0, Math.min(ny, st.imgH - nh));

                st.roi = {x: Math.round(nx), y: Math.round(ny),
                          w: Math.round(nw), h: Math.round(nh)};
                redraw();
            } else if (st.mode === 'roi' && st.roi && !st.dragMode) {
                var sx = canvas.width / st.imgW, sy = canvas.height / st.imgH;
                var rx = st.roi.x * sx, ry = st.roi.y * sy;
                var rw = st.roi.w * sx, rh = st.roi.h * sy;
                var r = img.getBoundingClientRect();
                var mx = e.clientX - r.left, my = e.clientY - r.top;
                var cursor = 'default';
                var corners = [
                    [rx,ry,'nwse-resize'],[rx+rw,ry,'nesw-resize'],
                    [rx,ry+rh,'nesw-resize'],[rx+rw,ry+rh,'nwse-resize'],
                ];
                for (var i = 0; i < 4; i++) {
                    if (Math.abs(mx-corners[i][0]) < 12 &&
                        Math.abs(my-corners[i][1]) < 12) {
                        cursor = corners[i][2]; break;
                    }
                }
                if (cursor === 'default' && mx >= rx && mx <= rx+rw &&
                    my >= ry && my <= ry+rh) {
                    cursor = 'grab';
                }
                canvas.style.cursor = cursor;
            }
        });

        canvas.addEventListener('mouseup', function(e) {
            e.preventDefault();
            if (st.mode === 'line' && st.drawing) {
                st.drawing = false;
                var l = st.line;
                if (Math.abs(l.x2-l.x1) > 3 || Math.abs(l.y2-l.y1) > 3) {
                    emitEvent('wl_calib_pending', {
                        channel: chId, type: 'line',
                        x1: Math.round(l.x1), y1: Math.round(l.y1),
                        x2: Math.round(l.x2), y2: Math.round(l.y2),
                        imgW: st.imgW, imgH: st.imgH,
                    });
                }
            } else if (st.mode === 'roi' && st.dragMode && st.roi) {
                emitEvent('wl_calib_pending', {
                    channel: chId, type: 'roi',
                    x: st.roi.x, y: st.roi.y,
                    w: st.roi.w, h: st.roi.h,
                });
                st.dragMode = null;
                st.dragStart = null;
                st.roiStart = null;
            }
        });

        // Resize observer
        if (window.ResizeObserver) {
            new ResizeObserver(function() { syncSize(); redraw(); }).observe(img);
        } else {
            setInterval(function() { syncSize(); redraw(); }, 1000);
        }

        // Exported API — 通过 cid 动态查找 DOM 元素，避免闭包捕获错误
        window._calibSetMode = function(cid, mode) {
            var s = window._calibCh[cid]; if (!s) return;
            var cv = document.getElementById('canvas-ch' + cid);
            var ht = document.getElementById('hint-ch' + cid);
            var im = document.getElementById('mjpeg-ch' + cid);
            if (!cv) return;
            s.mode = mode;
            if (mode === 'line') { s.line = null; s.roi = null; }
            s.drawing = false; s.dragMode = null;
            cv.style.pointerEvents = (mode === 'none') ? 'none' : 'auto';
            cv.style.cursor = mode === 'line' ? 'crosshair' : 'default';
            if (ht) {
                ht.style.display = (mode === 'line' || mode === 'roi') ? 'block' : 'none';
                ht.textContent = mode === 'line' ? '⬆ 沿硅胶板边沿画线 (click-drag)' :
                                 mode === 'roi' ? '↔ 拖拽调整 ROI 区域' : '';
            }
            // 同步尺寸并重绘
            if (im) { var r = im.getBoundingClientRect();
                if (r.width > 0) { cv.width = r.width; cv.height = r.height; } }
            (function(canvas, st) {  // inline redraw using local vars
                var ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                if (st.imgW <= 0) return;
                var sx = canvas.width / st.imgW, sy = canvas.height / st.imgH;
                if (st.line && (st.mode === 'line' || st.mode === 'roi')) {
                    var lx1=st.line.x1*sx, ly1=st.line.y1*sy, lx2=st.line.x2*sx, ly2=st.line.y2*sy;
                    ctx.strokeStyle='rgba(255,0,0,0.3)';ctx.lineWidth=7;
                    ctx.beginPath();ctx.moveTo(lx1,ly1);ctx.lineTo(lx2,ly2);ctx.stroke();
                    ctx.strokeStyle='#f00';ctx.lineWidth=3;
                    ctx.beginPath();ctx.moveTo(lx1,ly1);ctx.lineTo(lx2,ly2);ctx.stroke();
                    ctx.fillStyle='#f00';
                    [[lx1,ly1],[lx2,ly2]].forEach(function(p){ctx.beginPath();
                        ctx.arc(p[0],p[1],6,0,2*Math.PI);ctx.fill();
                        ctx.fillStyle='#fff';ctx.beginPath();
                        ctx.arc(p[0],p[1],3,0,2*Math.PI);ctx.fill();ctx.fillStyle='#f00';});
                }
                if (st.roi && (st.mode === 'roi' || st.mode === 'line')) {
                    var rx=st.roi.x*sx, ry=st.roi.y*sy, rw=st.roi.w*sx, rh=st.roi.h*sy;
                    ctx.fillStyle='rgba(0,255,255,0.12)';ctx.fillRect(rx,ry,rw,rh);
                    ctx.strokeStyle='#0ff';ctx.lineWidth=2;ctx.setLineDash([6,3]);
                    ctx.strokeRect(rx,ry,rw,rh);ctx.setLineDash([]);
                    ctx.fillStyle='#0ff';
                    [[rx,ry],[rx+rw,ry],[rx,ry+rh],[rx+rw,ry+rh]].forEach(function(p){
                        ctx.fillRect(p[0]-6,p[1]-6,12,12);});
                }
            })(cv, s);
        };

        window._calibSetRoi = function(cid, x, y, w, h) {
            var s = window._calibCh[cid]; if (!s) return;
            var cv = document.getElementById('canvas-ch' + cid);
            var im = document.getElementById('mjpeg-ch' + cid);
            s.roi = {x: x, y: y, w: w, h: h};
            if (cv && im) { var r = im.getBoundingClientRect();
                if (r.width > 0) { cv.width = r.width; cv.height = r.height; } }
            // trigger redraw via setMode
            if (cv) window._calibSetMode(cid, s.mode);
        };

        window._calibSetLine = function(cid, x1, y1, x2, y2) {
            var s = window._calibCh[cid]; if (!s) return;
            s.line = {x1: x1, y1: y1, x2: x2, y2: y2};
            if (s.mode) window._calibSetMode(cid, s.mode);
        };

        // Init
        setTimeout(function() { getNaturalSize(); syncSize(); }, 600);
    };
})();
"""


def _compute_calibration_from_line(x1, y1, x2, y2, img_w, img_h,
                                    roi_width_px, channel_id,
                                    flow_direction):
    """从用户画的参考线计算旋转角度和 ROI 矩形。

    使用纯 math 库（无 numpy/cv2 依赖），公式与香橙派
    _rebuild_rotation_matrix() 完全一致。

    Args:
        x1, y1, x2, y2: 参考线端点（原始帧像素坐标）
        img_w, img_h: 原始帧尺寸
        roi_width_px: ROI 延伸宽度 (像素)
        channel_id: 通道号 (1-based, 决定分组)
        flow_direction: 'left_to_right' | 'right_to_left'

    Returns:
        (rotation_angle_deg, roi_dict)
        roi_dict = {"x", "y", "w", "h", "reference_y", "reference_x"}
    """
    # 1. 旋转角度 — ★ 关键: 用户画的是竖直边，QR 标定用的是水平边
    #    对于同一块顺时针倾斜的板:
    #      QR 顶边 (水平): TR 在 TL 右下 → atan2(dy,dx) > 0 (正角度)
    #      竖直边 (垂直): 底部在顶部左侧 → atan2(dx,dy) < 0 (负角度)
    #    两者符号相反! 因此需要取反，使手动标定与 QR 标定的角度约定一致。
    dx = x2 - x1
    dy = y2 - y1
    angle_rad = math.atan2(dx, dy)  # 线条偏离竖直的角度 (raw)
    rotation_angle_deg = -math.degrees(angle_rad)  # ★ 取反，匹配 QR convention

    # ★ 归一化到 [-90, 90]: 无论用户从上往下还是从下往上画线，角度一致
    if rotation_angle_deg > 90:
        rotation_angle_deg -= 180
    elif rotation_angle_deg < -90:
        rotation_angle_deg += 180

    # 2. 构建旋转矩阵 — ★ 必须与 OpenCV getRotationMatrix2D + cv2.transform 一致
    #    cv2.transform 对 (cx,cy,θ) 产生的前向映射 (src→dst):
    #      x' = src_x·cosθ + src_y·sinθ + tx
    #      y' = -src_x·sinθ + src_y·cosθ + ty
    #    其中 tx = new_w/2 - cx·cosθ - cy·sinθ
    #         ty = new_h/2 + cx·sinθ - cy·cosθ
    #    这与 warpAffine 的输出图像坐标一致。
    effective_rad = math.radians(rotation_angle_deg)  # 使用取反后的角度
    center_x = img_w / 2.0
    center_y = img_h / 2.0
    cos_a = math.cos(effective_rad)
    sin_a = math.sin(effective_rad)
    abs_cos = abs(cos_a)
    abs_sin = abs(sin_a)
    new_w = int(img_h * abs_sin + img_w * abs_cos)
    new_h = int(img_h * abs_cos + img_w * abs_sin)

    # tx, ty 使旧中心 (center_x, center_y) 映射到新中心 (new_w/2, new_h/2)
    tx = new_w / 2.0 - center_x * cos_a - center_y * sin_a
    ty = new_h / 2.0 + center_x * sin_a - center_y * cos_a

    # 3. 变换参考线端点到旋转后坐标系 (cv2.transform/warpAffine convention)
    x1r = x1 * cos_a + y1 * sin_a + tx
    y1r = -x1 * sin_a + y1 * cos_a + ty
    x2r = x2 * cos_a + y2 * sin_a + tx
    y2r = -x2 * sin_a + y2 * cos_a + ty

    # 4. 从旋转后的参考线生成 ROI 矩形
    ref_x = (x1r + x2r) / 2.0
    ref_y_top = min(y1r, y2r)
    ref_y_bot = max(y1r, y2r)

    if flow_direction == "right_to_left":
        # 组1 (CH1-4): 液流从右→左, ROI 从参考线向左延伸
        roi_x = ref_x - roi_width_px
        roi_w = roi_width_px
        reference_x = ref_x
    else:
        # 组2 (CH5-8): 液流从左→右, ROI 从参考线向右延伸
        roi_x = ref_x
        roi_w = roi_width_px
        reference_x = ref_x

    roi_y = ref_y_top
    roi_h = ref_y_bot - ref_y_top

    # Clamp
    roi_x = max(0, int(roi_x))
    roi_y = max(0, int(roi_y))
    roi_w = min(int(roi_w), new_w - roi_x)
    roi_h = min(int(roi_h), new_h - roi_y)
    roi_w = max(20, roi_w)
    roi_h = max(20, roi_h)

    roi = {
        "x": roi_x,
        "y": roi_y,
        "w": roi_w,
        "h": roi_h,
        # reference_y: 液面高度参考线 (垂直流使用, 水平流场景下无实际作用)
        "reference_y": roi_y,
        "reference_x": round(reference_x),
    }

    return rotation_angle_deg, roi


# ── 模块级标定事件监听器 (只注册一次，按 channel 分发) ──
# 不能放在 _build_tank_vision_dialog() 内部，否则每次打开 dialog
# 都会重复注册全局 ui.on()，监听器累积触发 NiceGUI 重渲染，
# 最终导致 RuntimeError: No response returned.
_calib_listeners: dict[int, callable] = {}


def _global_calib_handler(e):
    """全局标定事件分发器：按 channel 路由到对应 dialog 的回调"""
    data = e.args or {}
    ch = data.get("channel")
    cb = _calib_listeners.get(ch)
    if cb is not None:
        asyncio.ensure_future(cb(e))


# 模块加载时注册一次，永不复复注册
ui.on("wl_calib_pending", _global_calib_handler)


def _build_tank_vision_dialog(
    channel_id: int,
    wl_client,
):
    """构建 TankVisionDialog 并返回 dialog 对象。

    在 NiceGUI 上下文中调用。每次打开时新建 dialog，
    关闭后自动销毁（避免 MJPEG 流残留）。
    """
    stream_url = f"/wl_proxy/ch/{channel_id}"

    # 捕获 NiceGUI Client 引用，避免在后台 asyncio Task 中调用
    # ui.run_javascript() 时因 slot stack 为空而抛出 RuntimeError。
    # 参见 _global_calib_handler 中使用 asyncio.ensure_future() 的注释。
    _client = ui.context.client

    # SVG 占位图
    _PLACEHOLDER = (
        "data:image/svg+xml,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720'>"
        "<rect fill='%23e0e0e0' width='1280' height='720'/>"
        "<text x='640' y='360' text-anchor='middle' dy='.3em' "
        "font-family='sans-serif' font-size='28' fill='%23999999'>"
        "等待连接...</text></svg>"
    )

    # ---- 状态 ----
    _params: dict = {}
    _initial_params: dict = {}
    _view_mode: str = "annotated"  # "annotated" | "raw" | "debug"
    _pre_calib_mode: str = "annotated"  # 进入标定前的视图模式 (用于恢复)
    _advanced_expanded: bool = False  # 高级设置折叠状态
    _active: bool = False
    _debounce_timers: dict[str, asyncio.Task | None] = {k: None for k in _DEBOUNCE_PARAMS}
    _pending_debounce: dict[str, any] = {}
    _closed: bool = False

    # ---- 标定/ROI 状态 ----
    _calibrated: bool = False
    _has_roi: bool = False
    _roi_mode: str = "auto"
    _roi_bbox: tuple | None = None
    _rotation_angle_deg: float = 0.0
    _flow_direction: str = "left_to_right"

    # 人工标定状态机: 'idle' | 'drawing' | 'adjusting'
    _calib_state: str = "idle"
    _calib_prev_rotation: float = 0.0
    _calib_prev_roi: dict | None = None
    _roi_width_px: int = _DEFAULT_ROI_WIDTH_PX

    # ---- 控件引用 ----
    _controls: dict[str, any] = {}
    _status_label: Optional[ui.label] = None
    _html_container: Optional[ui.html] = None
    _calib_status_label: Optional[ui.label] = None
    _calib_btn: Optional[ui.button] = None
    _calib_confirm_btn: Optional[ui.button] = None
    _calib_cancel_btn: Optional[ui.button] = None
    _roi_inputs: dict[str, any] = {}
    _roi_apply_btn: Optional[ui.button] = None
    _roi_clear_btn: Optional[ui.button] = None
    _roi_width_slider: Optional[ui.slider] = None
    _calib_tip_label: Optional[ui.label] = None
    _debug_btn: Optional[ui.button] = None
    _raw_btn: Optional[ui.button] = None

    # ---- 安全通知 ----
    def _safe_notify(message: str, type: str = "info") -> None:  # noqa: A002
        try:
            state = get_state()
            state._notification_queue.append((message, type))
        except Exception:
            pass

    # ---- 辅助函数 ----
    async def _send_param_change(param_name: str, value):
        if not wl_client or not _active:
            return
        await wl_client.send_command("set_detect_param", {
            "channel": channel_id,
            "params": {param_name: value},
        })
        _params[param_name] = value

    def _on_param_change(param_name: str, value):
        if not _active:
            return
        if param_name in _DEBOUNCE_PARAMS:
            _pending_debounce[param_name] = value
            if _debounce_timers[param_name]:
                _debounce_timers[param_name].cancel()
            _debounce_timers[param_name] = asyncio.create_task(
                _debounced_send(param_name))
        else:
            asyncio.create_task(_send_param_change(param_name, value))

    async def _debounced_send(param_name: str):
        await asyncio.sleep(_DEBOUNCE_MS)
        value = _pending_debounce.pop(param_name, None)
        if value is not None:
            await _send_param_change(param_name, value)

    def _update_all_controls():
        for name, ctrl in _controls.items():
            val = _params.get(name, PARAM_DEFS[name][3])
            if PARAM_DEFS[name][1] == "slider":
                ctrl.value = float(val)
            elif PARAM_DEFS[name][1] == "select":
                ctrl.value = val

    async def _load_params():
        if not wl_client:
            return
        future = asyncio.get_running_loop().create_future()

        def on_param(payload):
            if future.done():
                return
            channels = payload.get("channels", [])
            for ch in channels:
                if ch.get("channel") == channel_id:
                    params_ch = {k: v for k, v in ch.items() if k != "channel"}
                    future.set_result(params_ch)
                    return
            if not future.done():
                future.set_result({})

        wl_client.on_param(on_param)
        await wl_client.send_command("get_detect_param", {"channel": channel_id})

        try:
            params = await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("[TankVision] CH%d 参数加载超时", channel_id)
            return

        if params:
            _params.clear()
            _params.update(params)
            _initial_params.clear()
            _initial_params.update(params)
            _update_all_controls()
            if _status_label:
                _status_label.set_text(f"通道 {channel_id} — 参数已加载")
                _status_label.classes("text-positive")

    async def _load_calibration():
        """查询香橙派当前标定状态"""
        nonlocal _calibrated, _has_roi, _roi_mode, _roi_bbox
        nonlocal _rotation_angle_deg, _flow_direction
        if not wl_client:
            return

        future = asyncio.get_running_loop().create_future()

        def on_ack(payload):
            if future.done():
                return
            if payload.get("cmd") == "get_calibration":
                future.set_result(payload)

        wl_client.on_ack(on_ack)
        await wl_client.send_command("get_calibration", {"channel": channel_id})

        try:
            info = await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("[TankVision] CH%d 标定查询超时", channel_id)
            return

        _calibrated = info.get("calibrated", False)
        _rotation_angle_deg = info.get("rotation_angle_deg", 0.0)
        _roi_mode = info.get("roi_mode", "auto")
        _flow_direction = info.get("flow_direction", "left_to_right")
        roi_data = info.get("roi")
        if roi_data:
            _roi_bbox = (roi_data["x"], roi_data["y"],
                         roi_data["w"], roi_data["h"])
            _has_roi = True
        else:
            _roi_bbox = None
            _has_roi = False
        _update_calib_ui()

    async def _activate():
        nonlocal _active
        if not wl_client:
            if _status_label:
                _status_label.set_text("未连接香橙派 (MQTT 客户端不可用)")
                _status_label.classes("text-negative")
            log.warning("[TankVision-DBG] CH%d _activate 失败: wl_client=None", channel_id)
            return

        log.info("[TankVision-DBG] CH%d _activate 开始: set_active_channels+stream_start+load_params+load_calib",
                 channel_id)

        # 1. 确保摄像头已激活（静默启动后通道可能处于 IDLE 状态）
        #    使用 action: "add" 增量激活，不影响其他已活跃的通道
        active_ok = await wl_client.send_command("set_active_channels", {
            "action": "add",
            "channels": [channel_id],
            "stream_channels": [channel_id],
        })
        if not active_ok:
            log.warning("[TankVision-DBG] CH%d set_active_channels 发送失败", channel_id)

        # 2. stream_start + 加载参数/标定 并行
        results = await asyncio.gather(
            wl_client.send_command("stream_start", {"channel": channel_id}),
            _load_params(),
            _load_calibration(),
            return_exceptions=True,
        )

        stream_ok = results[0]
        if isinstance(stream_ok, Exception) or not stream_ok:
            err_msg = str(stream_ok) if isinstance(stream_ok, Exception) else "MQTT 发送失败"
            log.error("[TankVision] stream_start CH%d 失败: %s", channel_id, err_msg)
            if _status_label:
                _status_label.set_text(f"stream_start 失败: {err_msg}")
                _status_label.classes("text-negative")
            return

        # 等待 Orange Pi 启动 MJPEG 流（相机初始化约需 1-2s）
        await asyncio.sleep(1.5)
        _active = True
        log.info("[TankVision-DBG] CH%d _activate 完成: _active=True 初始view=%s",
                 channel_id, _view_mode)
        _refresh_mjpeg_src()
        if _status_label:
            _status_label.set_text(f"通道 {channel_id} — 视频流已连接")
            _status_label.classes("text-positive")

    async def _deactivate():
        nonlocal _active, _calib_state
        log.info("[TankVision-DBG] CH%d _deactivate: 关闭dialog, 当前view=%s",
                 channel_id, _view_mode)
        _active = False
        for t in _debounce_timers.values():
            if t:
                t.cancel()
        if wl_client:
            await wl_client.send_command("stream_stop", {"channel": channel_id})
            # 不回收摄像头：debug 预览无法判断该通道是否被实验占用，
            # 贸然 deactivate 会中断实验中的液位监测。摄像头保持 CAPTURE
            # 状态继续上报，由 ResourceManager 周期性同步统一管理生命周期。

    # ---- MJPEG 画面控制 ----
    def _refresh_mjpeg_src():
        """刷新 MJPEG 画面 src（含自动重试：流未就绪时每秒重试，最多 30 次）

        ★ 关键：MJPEG 是无限 HTTP 流，浏览器不会因为单纯设置 img.src
        而主动 abort 旧连接。必须先设 img.src='' 强制终止旧 MJPEG 流，
        再设新 URL，确保浏览器释放旧 TCP 连接后重新请求。

        Debug 模式: 主 img 固定 annotated + 显示 debug 容器并加载 ?debug=1 流。
        非 Debug 模式: 隐藏 debug 容器 + abort debug MJPEG。
        """
        base_url = stream_url
        is_debug = (_view_mode == "debug")
        # 主画面 URL: debug 模式下固定 annotated, 否则按 _view_mode
        if _view_mode == "debug":
            main_url = base_url  # annotated, 固定
            debug_url = base_url + "?debug=1"
        elif _view_mode == "raw":
            main_url = base_url + "?raw=1"
            debug_url = None
        else:
            main_url = base_url
            debug_url = None
        log.info("[TankVision-DBG] CH%d _refresh_mjpeg_src: view_mode=%s main=%s debug=%s",
                 channel_id, _view_mode, main_url,
                 debug_url if debug_url else "hidden")
        _client.run_javascript(f"""
            (function() {{
                var img = document.getElementById('mjpeg-ch{channel_id}');
                var debugCtr = document.getElementById('debug-container-ch{channel_id}');
                var debugImg = document.getElementById('mjpeg-debug-ch{channel_id}');
                var showDebug = {str(is_debug).lower()};

                // Debug 容器显隐 + 主画面高度适应
                if (debugCtr) debugCtr.style.display = showDebug ? 'block' : 'none';
                if (img) img.style.maxHeight = showDebug ? '30vh' : '75vh';
                // 隐藏时 abort debug MJPEG 连接
                if (!showDebug && debugImg) debugImg.src = '';

                // ── 主画面刷新 (annotated / raw) ──
                if (img) {{
                    var mainUrl = '{main_url}';
                    var retries = 0, maxRetries = 30, _intentionalAbort = false;
                    function tryLoad() {{
                        if (retries >= maxRetries) return;
                        var sep = mainUrl.includes('?') ? '&' : '?';
                        var newUrl = mainUrl + sep + '_r=' + retries + '&_t=' + Date.now();
                        retries++;
                        _intentionalAbort = true;
                        img.src = '';
                        setTimeout(function() {{
                            img.src = newUrl;
                            _intentionalAbort = false;
                        }}, 50);
                    }}
                    img.onerror = function() {{
                        if (_intentionalAbort) return;
                        setTimeout(tryLoad, 1000);
                    }};
                    tryLoad();
                    setTimeout(function() {{
                        if (window._initCalibCanvas) window._initCalibCanvas({channel_id});
                    }}, 800);
                }}

                // ── Debug 画面刷新 (仅 debug 模式) ──
                if (showDebug && debugImg) {{
                    var dUrl = '{debug_url}';
                    var dRetries = 0, dMax = 30, _dAbort = false;
                    function tryLoadDebug() {{
                        if (dRetries >= dMax) return;
                        var sep = dUrl.includes('?') ? '&' : '?';
                        var newUrl = dUrl + sep + '_dr=' + dRetries + '&_t=' + Date.now();
                        dRetries++;
                        _dAbort = true;
                        debugImg.src = '';
                        setTimeout(function() {{
                            debugImg.src = newUrl;
                            _dAbort = false;
                        }}, 50);
                    }}
                    debugImg.onerror = function() {{
                        if (_dAbort) return;
                        setTimeout(tryLoadDebug, 1000);
                    }};
                    tryLoadDebug();
                }}
            }})();
        """)

    def _toggle_raw():
        nonlocal _view_mode
        if not _active:
            return
        # ★ Debug 模式下禁用 raw 切换 (双画面固定 annotated + debug)
        if _view_mode == "debug":
            return
        _view_mode = "raw" if _view_mode != "raw" else "annotated"
        if _raw_btn:
            if _view_mode == "raw":
                _raw_btn.props("flat size=sm color=orange")
                _raw_btn.set_text("🔍 原始 (开)")
            else:
                _raw_btn.props(remove="color")
                _raw_btn.set_text("原始/标注切换")
        if _debug_btn and _view_mode == "debug":
            # raw 和 debug 互斥 — 切到 raw 时关闭 debug 高亮
            _debug_btn.props(remove="color")
            _debug_btn.set_text("🔬 调试视图")
        _refresh_mjpeg_src()

    def _toggle_debug():
        nonlocal _view_mode
        if not _active:
            log.warning("[TankVision-DBG] CH%d _toggle_debug 被忽略: _active=False", channel_id)
            return
        old_mode = _view_mode
        _view_mode = "debug" if _view_mode != "debug" else "annotated"
        log.info("[TankVision-DBG] CH%d 视图切换: %s → %s", channel_id, old_mode, _view_mode)
        if _debug_btn:
            if _view_mode == "debug":
                _debug_btn.props("flat size=sm color=info")
                _debug_btn.set_text("🔬 调试 (开)")
            else:
                _debug_btn.props(remove="color")
                _debug_btn.set_text("🔬 调试视图")
        # ★ Debug 模式: 禁用 raw 切换按钮 (双画面时标注视图固定 annotated)
        if _raw_btn:
            if _view_mode == "debug":
                _raw_btn.props("flat size=sm color=grey")
                _raw_btn.set_text("原始/标注 (不可用)")
                _raw_btn.disable()
            else:
                _raw_btn.props(remove="color")
                _raw_btn.set_text("原始/标注切换")
                _raw_btn.enable()
        _refresh_mjpeg_src()

    # ---- 标定状态机 ----
    def _update_calib_ui():
        """根据 _calibrated / _calib_state 刷新标定区域 UI"""
        if _calib_status_label:
            if _calibrated:
                _calib_status_label.set_text("✓ 已标定")
                _calib_status_label.classes("text-positive",
                    remove="text-warning text-negative text-grey")
            else:
                _calib_status_label.set_text("✗ 未标定")
                _calib_status_label.classes("text-warning",
                    remove="text-positive text-negative text-grey")

        # 标定按钮状态
        if _calib_btn:
            if _calib_state == "drawing":
                _calib_btn.set_text("⏳ 等待画线...")
                _calib_btn.props("color=warning")
                _calib_btn.disable()
            elif _calib_state == "adjusting":
                _calib_btn.set_text("🔄 重新标定")
                _calib_btn.props("color=info")
                _calib_btn.enable()
            else:
                _calib_btn.set_text("✏️ 手动标定")
                _calib_btn.props("color=primary")
                _calib_btn.enable()

        # 确认/取消按钮可见性
        is_calibrating = _calib_state in ("drawing", "adjusting")
        if _calib_confirm_btn:
            _calib_confirm_btn.set_visibility(is_calibrating)
        if _calib_cancel_btn:
            _calib_cancel_btn.set_visibility(is_calibrating)
        if _roi_width_slider:
            _roi_width_slider.set_visibility(is_calibrating)

        if _calib_tip_label:
            if _calib_state == "drawing":
                _calib_tip_label.set_text("⬆ 请在左侧画面沿硅胶板边沿画线")
                _calib_tip_label.classes("text-warning")
            elif _calib_state == "adjusting":
                _calib_tip_label.set_text("↔ 拖拽青色 ROI 框微调，满意后点击 ✓ 确认")
                _calib_tip_label.classes("text-info")
            else:
                _calib_tip_label.set_text("")
                _calib_tip_label.classes("")

    async def _on_calib_pending(e):
        """JS → Python 推送回调 (Canvas 画线/拖拽结果, 经 emitEvent 主动送达)。

        监听器在 dialog 构建时一次性注册 (见下方 ui.on)，派发由
        _calib_state 闸门控制，避免渲染后动态新增监听器触发重渲染。
        """
        if _closed:
            return
        data = e.args or {}
        if data.get("channel") != channel_id:
            return  # 同页面多 dialog 时按通道过滤
        if data.get("type") == "line" and _calib_state == "drawing":
            await _on_line_drawn(data["x1"], data["y1"],
                                 data["x2"], data["y2"],
                                 data.get("imgW", 640),
                                 data.get("imgH", 480))
        elif data.get("type") == "roi" and _calib_state == "adjusting":
            await _on_roi_dragged(data["x"], data["y"],
                                  data["w"], data["h"])

    async def _enter_calib_drawing():
        """进入标定-画线模式"""
        nonlocal _calib_state, _view_mode, _pre_calib_mode
        nonlocal _calib_prev_rotation, _calib_prev_roi

        # 保存当前标定状态 (用于取消时恢复)
        _calib_prev_rotation = _rotation_angle_deg
        _calib_prev_roi = {
            "x": _roi_bbox[0], "y": _roi_bbox[1],
            "w": _roi_bbox[2], "h": _roi_bbox[3],
        } if _roi_bbox else None

        _calib_state = "drawing"
        _pre_calib_mode = _view_mode  # 记住标定前的模式
        _view_mode = "raw"  # 标定时显示原始帧
        _update_calib_ui()
        _refresh_mjpeg_src()

        # 通知 Canvas 进入画线模式
        await asyncio.sleep(1.0)  # 等 MJPEG 加载
        # fire-and-forget: 不等待浏览器响应，避免 MJPEG 流期间 WebSocket 超时
        _client.run_javascript(
            f"window._calibSetMode({channel_id}, 'line')")

    async def _on_line_drawn(x1, y1, x2, y2, img_w, img_h):
        """Canvas 画线完成回调: 计算标定参数 → MQTT 下发 → 进入调整模式"""
        nonlocal _calib_state, _view_mode, _rotation_angle_deg

        rot_deg, roi = _compute_calibration_from_line(
            x1, y1, x2, y2, img_w, img_h,
            _roi_width_px, channel_id, _flow_direction,
        )

        _rotation_angle_deg = rot_deg

        # 下发到香橙派
        if wl_client:
            await wl_client.send_command("set_calibration", {
                "channel": channel_id,
                "rotation_angle_deg": rot_deg,
                "roi": roi,
                "save": False,
            })

        # 更新输入框
        for field in ("x", "y", "w", "h"):
            if field in _roi_inputs and field in roi:
                _roi_inputs[field].value = str(roi[field])

        # 进入 ROI 调整模式
        _calib_state = "adjusting"
        _view_mode = "annotated"  # 切回标注模式看效果
        _update_calib_ui()
        _refresh_mjpeg_src()

        await asyncio.sleep(0.8)
        # 通知 Canvas 进入 ROI 拖拽模式 + 设置 ROI 坐标 (fire-and-forget)
        _client.run_javascript(
            f"window._calibSetMode({channel_id}, 'roi');"
            f"window._calibSetRoi({channel_id}, {roi['x']}, {roi['y']}, "
            f"{roi['w']}, {roi['h']});"
        )

        _safe_notify(f"通道 {channel_id} 旋转角度={rot_deg:.1f}°, "
                     f"ROI=({roi['x']},{roi['y']},{roi['w']}×{roi['h']})",
                     type="positive")

    async def _on_roi_dragged(x, y, w, h):
        """Canvas ROI 拖拽完成回调: MQTT 即时下发新 ROI"""
        nonlocal _roi_bbox
        _roi_bbox = (x, y, w, h)
        # 更新输入框
        for field, val in [("x", x), ("y", y), ("w", w), ("h", h)]:
            if field in _roi_inputs:
                _roi_inputs[field].value = str(val)

        # 即时下发 (不保存)
        if wl_client:
            await wl_client.send_command("set_calibration", {
                "channel": channel_id,
                "rotation_angle_deg": _rotation_angle_deg,
                "roi": {"x": x, "y": y, "w": w, "h": h},
                "save": False,
            })

    async def _confirm_calibration():
        """确认标定: 持久化 + 退出标定模式"""
        nonlocal _calib_state, _view_mode, _pre_calib_mode
        if wl_client:
            await wl_client.send_command("save_calibration",
                                         {"channel": channel_id})
        _calib_state = "idle"
        _view_mode = _pre_calib_mode  # 恢复标定前的视图模式
        _update_calib_ui()
        _refresh_mjpeg_src()
        _client.run_javascript(
            f"window._calibSetMode({channel_id}, 'none')")
        _safe_notify(f"通道 {channel_id} 标定已保存", type="positive")

    async def _cancel_calibration():
        """取消标定: 恢复之前的标定参数"""
        nonlocal _calib_state, _view_mode, _pre_calib_mode, _rotation_angle_deg, _roi_bbox
        _calib_state = "idle"
        _view_mode = _pre_calib_mode  # 恢复标定前的视图模式
        _update_calib_ui()

        # 恢复
        if _calib_prev_roi:
            _rotation_angle_deg = _calib_prev_rotation
            _roi_bbox = (_calib_prev_roi["x"], _calib_prev_roi["y"],
                         _calib_prev_roi["w"], _calib_prev_roi["h"])
            if wl_client:
                await wl_client.send_command("set_calibration", {
                    "channel": channel_id,
                    "rotation_angle_deg": _calib_prev_rotation,
                    "roi": _calib_prev_roi,
                    "save": False,
                })

        _refresh_mjpeg_src()
        _client.run_javascript(
            f"window._calibSetMode({channel_id}, 'none')")
        _safe_notify(f"通道 {channel_id} 标定已取消", type="info")

    # ---- MJPEG 画面 HTML (含 Canvas 叠加层) ----
    def _build_image_html():
        """构建 MJPEG + Canvas 叠加层 HTML（初始占位，src 由 _refresh_mjpeg_src 通过 JS 设置）

        debug 模式下额外显示第二个 img（debug 容器），上下排列:
          上 — annotated 标注视图 (固定)
          下 — debug 2×2 网格视图
        """
        # 注意: Canvas 初始化通过 _refresh_mjpeg_src() 中的 ui.run_javascript()
        # 完成, 不能在 HTML 中内嵌 <script> 标签 (NiceGUI ui.html() 安全检查会拒绝)
        return f"""
        <div id="calib-container-ch{channel_id}"
             style="position: relative; display: inline-block; width: 100%;
                    user-select: none; -webkit-user-select: none;
                    -webkit-user-drag: none;"
             oncontextmenu="return false">
          <img id="mjpeg-ch{channel_id}" src="{_PLACEHOLDER}"
               draggable="false"
               style="display: block; width: 100%; max-height: 75vh;
                      object-fit: contain; border: 2px solid #ccc;
                      border-radius: 4px; user-select: none;
                      -webkit-user-drag: none;
                      pointer-events: none;">
          <canvas id="canvas-ch{channel_id}"
                  style="position: absolute; top: 0; left: 0;
                         width: 100%; height: 100%;
                         pointer-events: none;">
          </canvas>
          <div id="hint-ch{channel_id}"
               style="position: absolute; bottom: 8px; left: 8px;
                      color: #ff0; background: rgba(0,0,0,0.65);
                      padding: 3px 10px; border-radius: 4px;
                      font-size: 14px; display: none;
                      pointer-events: none;">
          </div>
        </div>
        <!-- Debug 视图容器: 仅 debug 模式可见, 无需 Canvas 叠加层 -->
        <div id="debug-container-ch{channel_id}"
             style="display: none; position: relative; width: 100%; margin-top: 8px;">
          <img id="mjpeg-debug-ch{channel_id}" src="{_PLACEHOLDER}"
               draggable="false"
               style="display: block; width: 100%; max-height: 42vh;
                      object-fit: contain; border: 2px solid #4488ff;
                      border-radius: 4px; user-select: none;
                      -webkit-user-drag: none;">
          <div style="position: absolute; top: 4px; left: 4px; color: #0ff;
                      background: rgba(0,0,0,0.7); padding: 2px 8px;
                      border-radius: 3px; font-size: 12px;
                      pointer-events: none;">
            DEBUG
          </div>
        </div>
        """

    # ---- ROI 旧接口兼容 ----
    async def _apply_roi():
        """手动输入框 → MQTT set_roi (数字微调用)"""
        if not wl_client:
            return
        try:
            x = int(_roi_inputs["x"].value or 0)
            y = int(_roi_inputs["y"].value or 0)
            w = int(_roi_inputs["w"].value or 100)
            h = int(_roi_inputs["h"].value or 100)
            ref_y_str = (_roi_inputs.get("reference_y") and
                         _roi_inputs["reference_y"].value)
        except (ValueError, TypeError):
            _safe_notify("ROI 参数必须为整数", type="negative")
            return
        if w < 20 or h < 20:
            _safe_notify("ROI 最小尺寸 20×20", type="negative")
            return
        payload = {"channel": channel_id, "x": x, "y": y,
                   "w": w, "h": h, "save": True}
        if ref_y_str:
            try:
                payload["reference_y"] = int(ref_y_str)
            except (ValueError, TypeError):
                pass

        # 同步 Canvas (fire-and-forget)
        _client.run_javascript(
            f"window._calibSetRoi({channel_id}, {x}, {y}, {w}, {h})")

        ok = await wl_client.send_command("set_roi", payload)
        if ok:
            nonlocal _roi_mode, _roi_bbox
            _roi_mode = "manual"
            _roi_bbox = (x, y, w, h)
            _safe_notify(f"通道 {channel_id} ROI 已应用并保存", type="positive")
        else:
            _safe_notify(f"通道 {channel_id} ROI 下发失败", type="negative")

    async def _clear_roi():
        if not wl_client:
            return
        ok = await wl_client.send_command("clear_roi", {"channel": channel_id})
        if ok:
            nonlocal _roi_mode, _roi_bbox
            _roi_mode = "auto"
            _roi_bbox = None
            _safe_notify(f"通道 {channel_id} ROI 已清除", type="positive")
        else:
            _safe_notify(f"通道 {channel_id} 清除 ROI 失败", type="negative")

    async def _save():
        if wl_client:
            ok = await wl_client.send_command("save_detect_param",
                                              {"channel": channel_id})
            if ok:
                _safe_notify(f"通道 {channel_id} 参数已保存", type="positive")
            else:
                _safe_notify(f"通道 {channel_id} 保存失败", type="negative")

    def _reset():
        for name, val in _initial_params.items():
            if name in _controls:
                _params[name] = val
                ctrl = _controls[name]
                if PARAM_DEFS[name][1] == "slider":
                    ctrl.value = float(val)
                elif PARAM_DEFS[name][1] == "select":
                    ctrl.value = val
                _on_param_change(name, val)
        if _status_label:
            _status_label.set_text(f"通道 {channel_id} — 已恢复初始值")
            _status_label.classes("text-positive")

    def _apply_all():
        if not _active or not wl_client:
            return
        asyncio.create_task(
            wl_client.send_command("set_detect_param", {
                "channel": channel_id,
                "params": dict(_params),
            })
        )
        ui.notify(f"通道 {channel_id} 参数已批量下发", type="info")

    async def _save_calibration():
        if not wl_client:
            return
        ok = await wl_client.send_command("save_calibration",
                                          {"channel": channel_id})
        if ok:
            _safe_notify(f"通道 {channel_id} 校准/ROI 已持久化", type="positive")
        else:
            _safe_notify(f"通道 {channel_id} 保存校准失败", type="negative")

    async def _reload_config():
        if not wl_client:
            return
        ok = await wl_client.send_command("reload_config",
                                          {"channel": channel_id})
        if ok:
            _safe_notify(f"通道 {channel_id} 配置已重载", type="positive")
        else:
            _safe_notify(f"通道 {channel_id} 重载配置失败", type="negative")

    def _on_roi_width_change(value):
        nonlocal _roi_width_px
        _roi_width_px = int(value)

    # ---- 创建 Dialog ----
    with ui.dialog() as dialog, ui.card().classes("q-pa-md").style(
            "width: 90vw; max-width: 1300px"):
        with ui.column().classes("w-full"):
            # 标题
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"通道 {channel_id} 监控").classes(
                    "text-h6 text-weight-bold")
                _status_label = ui.label("正在连接...").classes("text-grey")

            ui.separator()

            with ui.row().classes("w-full gap-4 q-mt-sm items-start").style(
                    "flex-wrap: nowrap"):
                # 左侧: MJPEG + Canvas
                with ui.column().style(
                        "flex: 0 0 65%; max-width: 65%; min-width: 0"):
                    _html_container = ui.html(_build_image_html()).classes(
                        "w-full").style("min-height: 400px")
                    with ui.row().classes("gap-2 q-mt-xs"):
                        _raw_btn = ui.button("原始/标注切换",
                                  on_click=_toggle_raw).props("flat size=sm")
                        _debug_btn = ui.button("🔬 调试视图",
                                  on_click=_toggle_debug).props("flat size=sm")
                        ui.button("🔄 刷新",
                                  on_click=_refresh_mjpeg_src).props(
                                    "flat size=sm")

                # 右侧: 参数面板
                with ui.column().style(
                        "flex: 0 0 35%; max-width: 35%; min-width: 280px"
                        ).classes("gap-2"):
                    ui.label("检测参数").classes(
                        "text-subtitle1 text-weight-bold q-mb-sm")

                    _param_groups = [
                        ("液位边缘检测", [
                            "water_edge_threshold", "water_blur_ksize",
                            "water_sobely_ksize",
                        ]),
                        ("信号显著性检验", [
                            "water_snr_threshold", "water_diff_threshold",
                        ]),
                        ("前沿对比验证", [
                            "front_contrast_threshold", "front_zone_width",
                            "front_zone_gap",
                        ]),
                        ("流动方向", [
                            "flow_direction",
                        ]),
                    ]
                    # ★ 辅助函数: 创建参数行
                    def _build_param_row(name):
                        label, ptype, opts, default = PARAM_DEFS[name]
                        with ui.row().classes(
                                "w-full items-center gap-2"):
                            ui.label(label).classes("text-caption").style(
                                "min-width: 100px")
                            if ptype == "slider":
                                ctrl = ui.slider(
                                    min=opts["min"], max=opts["max"],
                                    step=opts["step"], value=default,
                                ).props("label-always").classes(
                                    "flex-grow")
                                val_label = ui.label(str(default)).classes(
                                    "text-caption").style(
                                    "min-width: 50px; text-align: right")
                                ctrl.on("update:model-value",
                                        lambda e, n=name, l=val_label:
                                        (_on_param_change(n, e.args),
                                         l.set_text(f"{e.args:.2f}")))
                            elif ptype == "select":
                                ctrl = ui.select(
                                    options=[str(o) for o in opts],
                                    value=str(default),
                                ).classes("flex-grow").style(
                                    "min-width: 80px")
                                ctrl.on("update:model-value",
                                        lambda e, n=name:
                                        _on_param_change(n, type(opts[0])(
                                        e.args if not isinstance(
                                            e.args, dict)
                                        else e.args.get("value", "")
                                    )))
                            _controls[name] = ctrl

                    for _group_label, _group_keys in _param_groups:
                        ui.label(_group_label).classes(
                            "text-caption text-weight-medium text-grey-7 "
                            "q-mt-sm q-mb-xs")
                        for name in _group_keys:
                            _build_param_row(name)

                    # ★ 高级设置 (可折叠, 默认折叠)
                    with ui.column().classes("w-full q-mt-sm"):
                        _adv_header = ui.button(
                            "▶ 高级设置",
                            on_click=lambda: _toggle_advanced(),
                        ).props("flat dense size=sm color=grey").classes(
                            "text-caption text-weight-medium")
                        _adv_container = ui.column().classes("w-full gap-1")
                        _adv_container.set_visibility(False)

                        with _adv_container:
                            ui.label("ROI 与预处理").classes(
                                "text-caption text-weight-medium text-grey-7 "
                                "q-mt-xs q-mb-xs")
                            _build_param_row("roi_crop_x")
                            _build_param_row("roi_crop_y")
                            _build_param_row("roi_sobel_ksize")

                            ui.label("标定").classes(
                                "text-caption text-weight-medium text-grey-7 "
                                "q-mt-sm q-mb-xs")
                            _build_param_row("height_offset_cm")
                            _build_param_row("height_gain")

                            ui.label("状态机").classes(
                                "text-caption text-weight-medium text-grey-7 "
                                "q-mt-sm q-mb-xs")
                            _build_param_row("front_arrival_frames")
                            _build_param_row("front_departure_frames")

                    def _toggle_advanced():
                        nonlocal _advanced_expanded
                        _advanced_expanded = not _advanced_expanded
                        if _advanced_expanded:
                            _adv_header.set_text("▼ 高级设置")
                            _adv_container.set_visibility(True)
                        else:
                            _adv_header.set_text("▶ 高级设置")
                            _adv_container.set_visibility(False)

                    # ── 标定区块 (新版: 人工画线标定) ──
                    ui.separator().classes("q-mt-sm")
                    ui.label("标定").classes(
                        "text-subtitle1 text-weight-bold q-mb-sm")
                    with ui.row().classes("w-full items-center gap-2"):
                        _calib_status_label = ui.label("—").classes(
                            "text-caption text-grey")
                        _calib_btn = ui.button(
                            "✏️ 手动标定",
                            on_click=lambda: _enter_calib_drawing(),
                        ).props("dense color=primary unelevated").tooltip(
                            "在画面上沿硅胶板边沿画线进行标定")

                    # 标定提示
                    _calib_tip_label = ui.label("").classes(
                        "text-caption q-mt-xs")

                    # ROI 宽度滑块 (标定时显示)
                    _roi_width_slider = ui.slider(
                        min=20, max=200, step=5, value=_DEFAULT_ROI_WIDTH_PX,
                    ).props("label label-always").classes(
                        "q-mt-sm").tooltip("ROI 延伸宽度 (像素)")
                    _roi_width_slider.on("update:model-value",
                                         lambda e: _on_roi_width_change(
                                             e.args))
                    _roi_width_slider.set_visibility(False)

                    # 确认/取消 (标定时显示)
                    with ui.row().classes("w-full gap-2 q-mt-sm"):
                        _calib_confirm_btn = ui.button(
                            "✓ 确认标定",
                            on_click=lambda: _confirm_calibration(),
                        ).props("dense flat size=sm color=positive")
                        _calib_cancel_btn = ui.button(
                            "✗ 取消",
                            on_click=lambda: _cancel_calibration(),
                        ).props("dense flat size=sm")
                        _calib_confirm_btn.set_visibility(False)
                        _calib_cancel_btn.set_visibility(False)

                    # ── ROI 手动设置 (微调输入框) ──
                    ui.label("ROI 手动设置").classes(
                        "text-caption text-weight-medium text-grey-7 "
                        "q-mt-sm q-mb-xs")
                    with ui.row().classes("w-full items-center gap-1"):
                        for _roi_field, _roi_label, _roi_w in [
                            ("x", "X", "70px"), ("y", "Y", "70px"),
                            ("w", "W", "70px"), ("h", "H", "70px"),
                        ]:
                            inp = ui.input(
                                label=_roi_label,
                                value="",
                            ).props(f"dense outlined").style(
                                f"width: {_roi_w}")
                            _roi_inputs[_roi_field] = inp
                    with ui.row().classes("w-full items-center gap-1 "
                                          "q-mt-xs"):
                        ref_y_inp = ui.input(
                            label="ref_y", value="",
                        ).props("dense outlined").style(
                            "width: 80px").tooltip(
                            "参考线Y坐标, 不填默认=ROI顶部")
                        _roi_inputs["reference_y"] = ref_y_inp
                    with ui.row().classes("w-full gap-2 q-mt-xs"):
                        _roi_apply_btn = ui.button(
                            "✓ 应用 ROI",
                            on_click=lambda: _apply_roi(),
                        ).props("dense flat size=sm color=positive")
                        _roi_clear_btn = ui.button(
                            "✗ 清除 ROI",
                            on_click=lambda: _clear_roi(),
                        ).props("dense flat size=sm")

                    # ── 管理操作 ──
                    ui.label("管理").classes(
                        "text-caption text-weight-medium text-grey-7 "
                        "q-mt-sm q-mb-xs")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "🔄 重载配置",
                            on_click=lambda: _reload_config(),
                        ).props("dense flat size=sm").tooltip(
                            "从配置文件恢复ROI和参数")

            ui.separator()

            # 底部按钮栏
            with ui.row().classes("w-full gap-4 q-mt-sm justify-end"):
                ui.button("重置", on_click=_reset).props("flat")
                ui.button("应用全部", on_click=_apply_all).props(
                    "flat color=info")
                ui.button("保存到配置文件",
                          on_click=lambda: _save(),
                          ).props("color=positive")
                ui.button("关闭",
                          on_click=lambda: _do_close(),
                          ).props("color=grey")

    # ---- Dialog 生命周期钩子 ----
    async def _do_open():
        nonlocal _closed
        _closed = False
        # 注册本 dialog 的回调到模块级分发器 (不重复注册全局 ui.on)
        _calib_listeners[channel_id] = _on_calib_pending
        dialog.open()
        # 真正 eval 标定 JS（定义 window._initCalibCanvas 等），必须在
        # _activate() 之前执行，因为 _refresh_mjpeg_src() 会引用这些函数。
        _client.run_javascript(_CALIB_JS)
        await _activate()

    async def _do_close():
        nonlocal _closed
        if _closed:
            return
        _closed = True
        await _deactivate()
        # 从模块级分发器注销本 dialog 的回调
        _calib_listeners.pop(channel_id, None)
        dialog.close()

    dialog.open_channel = _do_open
    dialog.close_channel = _do_close

    return dialog


def _build_grid_preview_dialog():
    """构建全通道 2×4 网格预览 Dialog。

    通过同源代理 /wl_proxy/grid 获取香橙派 MJPEG 网格流。
    无需 stream_start/stream_stop —— 网格端点始终可用。

    核心优势：一个 HTTP 连接承载 8 路画面，不受浏览器
    每 host 6 连接的并发限制。
    """
    stream_url = "/wl_proxy/grid"

    _PLACEHOLDER = (
        "data:image/svg+xml,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='1920' height='1080'>"
        "<rect fill='%23e0e0e0' width='1920' height='1080'/>"
        "<text x='960' y='540' text-anchor='middle' dy='.3em' "
        "font-family='sans-serif' font-size='32' fill='%23999999'>"
        "正在连接网格预览...</text></svg>"
    )

    _closed = False
    _image_widget = None

    with ui.dialog() as dialog, ui.card().classes("q-pa-md").style(
            "width: 90vw; max-width: 1300px"):
        with ui.column().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("📺 全通道网格预览 (2×4)").classes(
                    "text-h6 text-weight-bold")
                ui.label("单连接，不受浏览器并发限制").classes(
                    "text-caption text-grey")

            ui.separator()

            _image_widget = ui.image(_PLACEHOLDER).classes(
                "w-full border-2 border-grey-4 rounded").style(
                "max-height: 80vh; object-fit: contain")

            with ui.row().classes("w-full gap-3 q-mt-sm justify-end"):
                ui.button(
                    "🔄 刷新",
                    on_click=lambda: _image_widget.set_source(
                        f"{stream_url}?_t={int(time.time() * 1000)}"),
                ).props("flat size=sm")
                ui.button("关闭", on_click=lambda: _do_close()).props(
                    "color=grey")

    def _do_close():
        nonlocal _closed
        if _closed:
            return
        _closed = True
        dialog.close()

    def _do_open():
        nonlocal _closed
        _closed = False
        dialog.open()
        _image_widget.set_source(stream_url)

    dialog.open_preview = _do_open
    dialog.close_preview = _do_close

    return dialog
