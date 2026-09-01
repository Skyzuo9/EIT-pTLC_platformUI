"""液位检测离线回放整定台 (上位机侧, 调参专用)
================================================
用途:
    把一段录制 (waterlevel_recorder 产出的 <stem>.avi + .jsonl + .meta.json) 当输入,
    用**现役检测算法** (waterlevel_detector.detect_level) 逐帧跑一遍, 并给一排实时滑块
    整定全部参数 —— 拖滑块即时看 ROI 叠加 / 湿区掩膜 / percent 数值, 按键把当前参数
    跑完整段画出 percent(t) 时序曲线, 用来"确定需求"(阈值该定多少 / 要不要时序滤波 /
    前沿是否需要状态机)。Ctrl+右键拖可框"干参考区"(板外永不湿处), 检测与整定台共用
    separate_wet 口径做漂移补偿, HUD/曲线均显示 drift。

第一性原理 / 奥卡姆:
    - 零新算法: 帧源复用 recorder.replay(), 判据复用 detector.detect_level() (纯函数),
      标定初值复用录制旁挂 meta.json 的 calibration_snapshot, 存盘复用 store 的原生格式。
      本文件只是把这些现成积木串成一个 OpenCV trackbar 交互外壳。
    - 参考图 (干板) 不固定成一张灰度, 而是记 ref_frame_idx —— 每次渲染用**当前** calib/params
      从该帧重算 ref_gray, 这样改旋转/ROI/模糊后参考图与检测图的像素尺寸永远对齐, 不会 shape 不符。

运行:
    conda activate platformupper
    python -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/adhoc/ch5_20260707_125330.avi
    # 省略路径 → 取 data/water_level_recordings 下最新一段 .avi
    # 传目录     → 取该目录下最新一段 .avi

热键 (焦点在 preview 窗口):
    空格 播放/暂停        r  把当前帧设为参考(干板)帧
    ← →  上/下一帧         c  用当前参数跑完整段, matplotlib 画 percent(t)/front(t) 曲线
                              (c_speed 滑块 = 倍速: 每 N 帧抽 1 帧检测, 跳过帧不解码)
    ,  .  快退/快进 10 帧   w  存当前参数为 <stem>.tuned.json (store 原生格式, 可并入标定真源)
    e    终端敲精确值 (逐项输入)
    W    并入生产真源 config/water_level_calib.json (load-merge-save + 确认)
    h    打印热键          q / Esc  退出
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional
from urllib.error import URLError
from urllib.request import urlopen

import cv2
import numpy as np

from eit_ptlc.controller.waterlevel_config_tiers import apply_commit
from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    DryGainGuard,
    ReferenceBundle,
    WaterLevelDetectParams,
    angle_to_make_line_vertical,
    box_to_roi_frac,
    compute_reference,
    detect_level,
    dry_zone_front_percent,
    extract_dry_gray,
    extract_roi_gray,
    measure_dry_gain,
    rotation_matrix,
    separate_wet,
)
from eit_ptlc.controller.waterlevel_recorder import replay
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    DRY_REF_DEFAULT_BY_FLOW,
    load_channel_configs,
    save_channel_configs,
)
from eit_ptlc.tools import wl_marks

log = logging.getLogger(__name__)

CTRL_WIN = "controls (拖滑块)"
VIEW_WIN = "preview (热键: 空格播放 e敲值 r参考 c曲线 w存草稿 W并入真源 q退出; 左键拖=画竖直边定角 右键拖=框ROI Ctrl+右键拖=框干参考区(漂移补偿))"
CURVE_WIN = "curve (X 关闭; 每次 c 刷新)"
FLOWS = ["left_to_right", "right_to_left", "bottom_to_top"]

from dataclasses import dataclass, replace
from typing import Callable


# ====================================================================
# 参数标度单一真源: 自然值 <-> 滑块 int (建轨/读轨/敲值 REPL 三处共用)
# ====================================================================
@dataclass(frozen=True)
class ParamSpec:
    """一个可敲参数的标度规格。to_pos/from_pos 为纯函数, 无 cv2 依赖, 可离线测。"""
    key: str
    trackbar: str
    track_hi: int
    lo: float
    hi: float
    to_pos: Callable[[float], int]
    from_pos: Callable[[int], float]
    is_int: bool
    hint: str


PARAM_SPECS: list[ParamSpec] = [
    ParamSpec("flow", "flow 0L>R1R>L2B>T", 2, 0, 2,
              lambda v: max(0, min(2, int(round(v)))), lambda p: int(p), True, "0=L>R 1=R>L 2=B>T"),
    ParamSpec("roi_fx", "roi_fx(/1000)", 999, 0.0, 0.999,
              lambda v: max(0, min(999, int(round(v * 1000)))), lambda p: p / 1000.0, False, "比例 0~0.999"),
    ParamSpec("roi_fy", "roi_fy(/1000)", 999, 0.0, 0.999,
              lambda v: max(0, min(999, int(round(v * 1000)))), lambda p: p / 1000.0, False, "比例 0~0.999"),
    ParamSpec("roi_fw", "roi_fw(/1000)", 1000, 0.001, 1.0,
              lambda v: max(1, min(1000, int(round(v * 1000)))), lambda p: max(1, p) / 1000.0, False, "比例 0.001~1.0"),
    ParamSpec("roi_fh", "roi_fh(/1000)", 1000, 0.001, 1.0,
              lambda v: max(1, min(1000, int(round(v * 1000)))), lambda p: max(1, p) / 1000.0, False, "比例 0.001~1.0"),
    ParamSpec("crop_x", "crop_x(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
    ParamSpec("crop_y", "crop_y(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
    ParamSpec("blur_ksize", "blur(2v+1)", 15, 1, 31,
              lambda v: max(0, min(15, int(round((v - 1) / 2)))), lambda p: 2 * int(p) + 1, True, "奇数核 1~31"),
    ParamSpec("wet_thr", "wet_thr(x10)", 1000, 0.0, 100.0,
              lambda v: max(0, min(1000, int(round(v * 10)))), lambda p: p / 10.0, False, "0~100 [abs]"),
    ParamSpec("sep_mode", "sep 0abs 1log", 1, 0, 1,
              lambda v: max(0, min(1, int(round(v)))), lambda p: int(p), True, "0=abs(旧) 1=log(默认)"),
    ParamSpec("wet_rel", "wet_rel(promille)", 200, 0.0, 0.20,
              lambda v: max(0, min(200, int(round(v * 1000)))), lambda p: p / 1000.0, False,
              "相对变暗 k 0~0.20 [log]"),
    ParamSpec("front_lvl", "front_lvl(%)", 100, 0.0, 1.0,
              lambda v: max(0, min(100, int(round(v * 100)))), lambda p: p / 100.0, False, "0~1"),
    ParamSpec("front_gap", "front_gap(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
]
SPECS: dict[str, ParamSpec] = {s.key: s for s in PARAM_SPECS}
ROTATION_KEY = "rotation_deg"


def edit_menu() -> list[tuple[str, str]]:
    """敲值菜单顺序: index 0 = rotation(非滑块, 写 ui.angle_deg), 其后 PARAM_SPECS 各项。"""
    return [(ROTATION_KEY, "角度 -45~45")] + [(s.key, s.hint) for s in PARAM_SPECS]


def parse_edit_command(line: str):
    """解析一行敲值命令 → (key, value)。

    '<编号|短名> <值>' → (key, float);空行/'q' → (None, None);非法 → ('__error__', 提示串)。
    纯函数, 不碰 cv2, 供离线测。
    """
    line = line.strip()
    if line == "" or line.lower() == "q":
        return (None, None)
    parts = line.split()
    if len(parts) != 2:
        return ("__error__", "格式: <编号|短名> <值>")
    tok, valstr = parts
    menu = edit_menu()
    keys = [k for k, _ in menu]
    key = None
    if tok.isdigit():
        i = int(tok)
        if 0 <= i < len(menu):
            key = keys[i]
    elif tok in keys:
        key = tok
    if key is None:
        return ("__error__", f"未知参数: {tok}")
    try:
        value = float(valstr)
    except ValueError:
        return ("__error__", f"非数字: {valstr}")
    return (key, value)


# 交互状态 (鼠标回调 <-> 主循环共享): 旋转总角 + 画线两点 + ROI 拖框
class _UIState:
    def __init__(self, angle_deg: float = 0.0):
        self.angle_deg = float(angle_deg)   # 旋转总角 (画线定角累加, 取代旋转滑块)
        self.line_p0 = None                 # 画线起点 (旋转后画布像素)
        self.line_cur = None                # 画线当前点 (拖动中)
        self.roi_drag0 = None               # ROI 拖框起点
        self.roi_drag_cur = None            # ROI 拖框当前点
        self.dry_frac = None                # 干参考区比例框 (Ctrl+右键拖设置; 漂移补偿)
        self.dry_drag0 = None               # 干区拖框起点
        self.dry_drag_cur = None            # 干区拖框当前点
        self.left_origin = (0, 0)           # 左图在合成画布中的原点 (恒 0,0)
        self.rot_size = (1, 1)              # 最近一次渲染的旋转后画布尺寸 (rw, rh)


# ====================================================================
# 输入定位 + meta 初值
# ====================================================================
def _default_recordings_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "water_level_recordings"


def _resolve_avi(arg: Optional[str]) -> Path:
    """把命令行入参解析成一段具体 .avi。省略/给目录 → 取(该目录下)最新一段。"""
    if arg:
        p = Path(arg)
        if p.is_file():
            return p
        if p.is_dir():
            root = p
        else:
            raise SystemExit(f"路径不存在: {p}")
    else:
        root = _default_recordings_dir()
    avis = sorted(root.rglob("*.avi"), key=lambda f: f.stat().st_mtime)
    if not avis:
        raise SystemExit(f"目录下没有 .avi: {root}")
    return avis[-1]


def _meta_path(avi: Path) -> Path:
    return Path(str(avi.with_suffix("")) + ".meta.json")


def _load_initial(avi: Path) -> tuple[ChannelCalibration, WaterLevelDetectParams, dict]:
    """读 meta.json 的 calibration_snapshot 当初值; 缺失/无标定 → 用检测器默认 + 居中兜底 ROI。"""
    calib = ChannelCalibration()
    params = WaterLevelDetectParams()
    meta: dict = {}
    mp = _meta_path(avi)
    if mp.is_file():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("meta.json 解析失败 (%s), 用默认初值", exc)
    snap = meta.get("calibration_snapshot") or {}
    if snap:
        rf = snap.get("roi_frac")
        rb = snap.get("roi_bbox")
        calib = ChannelCalibration(
            rotation_angle_deg=float(snap.get("rotation_angle_deg", 0.0)),
            roi_bbox=tuple(rb) if isinstance(rb, (list, tuple)) and len(rb) == 4 else None,
            flow_direction=snap.get("flow_direction", "left_to_right"),
            roi_frac=tuple(float(v) for v in rf)
            if isinstance(rf, (list, tuple)) and len(rf) == 4 else None,
            dry_ref_frac=tuple(float(v) for v in snap["dry_ref_frac"])
            if isinstance(snap.get("dry_ref_frac"), (list, tuple)) and len(snap["dry_ref_frac"]) == 4 else None,
        )
        sp = snap.get("params") or {}
        sp_mode = sp.get("separation_mode", params.separation_mode)
        params = WaterLevelDetectParams(
            roi_crop_x=float(sp.get("roi_crop_x", params.roi_crop_x)),
            roi_crop_y=float(sp.get("roi_crop_y", params.roi_crop_y)),
            blur_ksize=int(sp.get("blur_ksize", params.blur_ksize)),
            separation_mode=sp_mode if sp_mode in ("abs", "log") else "log",
            wet_pixel_threshold=float(sp.get("wet_pixel_threshold", params.wet_pixel_threshold)),
            wet_rel_threshold=float(sp.get("wet_rel_threshold", params.wet_rel_threshold)),
            front_ratio_level=float(sp.get("front_ratio_level", params.front_ratio_level)),
            front_gap_frac=float(sp.get("front_gap_frac", params.front_gap_frac)),
        )
    # meta 快照无标定 → 回退读标定真源 config/water_level_calib.json[通道] (解 CH5-8 看着像没标定)
    if not calib.calibrated:
        ch = meta.get("channel")
        calib_json = Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"
        if ch is not None and calib_json.is_file():
            cfgs = load_channel_configs(calib_json)
            cc = cfgs.get(int(ch))
            if cc is not None and cc.calib.calibrated:
                calib = cc.calib
                params = cc.params
                log.info("[整定台] meta 无标定, 回退用真源 CH%s 标定", ch)
    # 无任何 ROI → 居中兜底 (让 extract_roi_gray 不至于 no_roi, 用户再拖滑块框好)
    if calib.roi_frac is None and calib.roi_bbox is None:
        calib.roi_frac = (0.30, 0.05, 0.20, 0.80)
    return calib, params, meta


def _initial_roi_frac(calib: ChannelCalibration, cap_w: int, cap_h: int) -> tuple:
    """把初值 calib 折成 4 元 roi_frac (滑块起点); roi_bbox-only 时按采集档换算成比例。"""
    if calib.roi_frac is not None:
        return calib.roi_frac
    if calib.roi_bbox is not None and cap_w > 0 and cap_h > 0:
        # roi_bbox 在"旋转后坐标系", 用旋转后画布尺寸换比例 (与检测口径一致)
        _M, (rw, rh) = rotation_matrix(calib.rotation_angle_deg, cap_w, cap_h)
        x, y, w, h = calib.roi_bbox
        return (x / rw, y / rh, w / rw, h / rh)
    return (0.30, 0.05, 0.20, 0.80)


# ====================================================================
# 滑块 <-> 值 映射 (trackbar 只吃 int)
# ====================================================================
def _add_trackbars(calib: ChannelCalibration, params: WaterLevelDetectParams,
                   n_frames: int, roi_frac: tuple) -> None:
    cv2.namedWindow(CTRL_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(CTRL_WIN, 460, 640)
    noop = lambda _v: None
    fx, fy, fw, fh = roi_frac

    # 导航轨 (非参数, 不入存盘)
    cv2.createTrackbar("frame", CTRL_WIN, 0, max(1, n_frames - 1), noop)
    cv2.createTrackbar("ref_frame", CTRL_WIN, 0, max(1, n_frames - 1), noop)
    cv2.createTrackbar("c_speed(xN)", CTRL_WIN, 1, 16, noop)   # 'c' 整段回放倍速 (抽帧)

    # 各参数初值 (自然值) → 经 spec.to_pos 定初始滑块位
    flow_idx = FLOWS.index(calib.flow_direction) if calib.flow_direction in FLOWS else 0
    init = {
        "flow": flow_idx,
        "roi_fx": fx, "roi_fy": fy, "roi_fw": fw, "roi_fh": fh,
        "crop_x": params.roi_crop_x, "crop_y": params.roi_crop_y,
        "blur_ksize": params.blur_ksize,
        "wet_thr": params.wet_pixel_threshold,
        "sep_mode": 0 if params.separation_mode == "abs" else 1,
        "wet_rel": params.wet_rel_threshold,
        "front_lvl": params.front_ratio_level,
        "front_gap": params.front_gap_frac,
    }
    for s in PARAM_SPECS:
        cv2.createTrackbar(s.trackbar, CTRL_WIN, s.to_pos(init[s.key]), s.track_hi, noop)


def _read_state(ui):
    """从滑块 + UIState 读回 (calib, params, frame_idx, ref_idx)。旋转角来自画线定角 (ui.angle_deg)。"""
    def val(key):
        s = SPECS[key]
        return s.from_pos(cv2.getTrackbarPos(s.trackbar, CTRL_WIN))
    calib = ChannelCalibration(
        rotation_angle_deg=ui.angle_deg,
        flow_direction=FLOWS[int(val("flow"))],
        roi_frac=(val("roi_fx"), val("roi_fy"), val("roi_fw"), val("roi_fh")),
        dry_ref_frac=ui.dry_frac,
    )
    params = WaterLevelDetectParams(
        roi_crop_x=val("crop_x"),
        roi_crop_y=val("crop_y"),
        blur_ksize=int(val("blur_ksize")),
        separation_mode=("abs", "log")[int(val("sep_mode"))],
        wet_pixel_threshold=val("wet_thr"),
        wet_rel_threshold=val("wet_rel"),
        front_ratio_level=val("front_lvl"),
        front_gap_frac=val("front_gap"),
    )
    g = lambda name: cv2.getTrackbarPos(name, CTRL_WIN)
    return calib, params, g("frame"), g("ref_frame")


def _current_value(ui, key):
    """读某可敲项当前自然值 (rotation 读 ui.angle_deg, 余读 trackbar)。"""
    if key == ROTATION_KEY:
        return round(ui.angle_deg, 2)
    s = SPECS[key]
    return round(s.from_pos(cv2.getTrackbarPos(s.trackbar, CTRL_WIN)), 4)


def _apply_value(ui, key, value):
    """应用敲入的自然值 (clamp → rotation 写 ui.angle_deg / 余回填 trackbar), 返回回读值。"""
    if key == ROTATION_KEY:
        ui.angle_deg = max(-45.0, min(45.0, float(value)))
        return round(ui.angle_deg, 2)
    s = SPECS[key]
    v = max(s.lo, min(s.hi, float(value)))
    cv2.setTrackbarPos(s.trackbar, CTRL_WIN, s.to_pos(v))
    return _current_value(ui, key)


def run_edit_repl(ui) -> None:
    """终端模态敲值: 列可编辑项 → 逐行 '<编号|短名> <值>' → 即时生效并回填滑块。

    空行/'q' 退出。input() 阻塞期间预览窗不刷新 (模态编辑的已知取舍)。
    """
    menu = edit_menu()
    print("\n[整定台] 敲值编辑 (逐行输入; 空行/q 退出):")
    for i, (key, hint) in enumerate(menu):
        print(f"  {i:2d}  {key:12s} = {_current_value(ui, key):<8}  ({hint})")
    while True:
        try:
            line = input("编辑> ")
        except EOFError:
            break
        key, value = parse_edit_command(line)
        if key is None:
            break
        if key == "__error__":
            print(f"  ! {value}")
            continue
        print(f"  {key} → {_apply_value(ui, key, value)}")


# ====================================================================
# 帧缓存 (随机寻帧; MJPG 每帧皆关键帧, set POS_FRAMES 可靠)
# ====================================================================
class _FrameSource:
    def __init__(self, avi: Path):
        self.cap = cv2.VideoCapture(str(avi))
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._cache: dict[int, np.ndarray] = {}
        self._order: list[int] = []
        self._cap_max = 64

    def get(self, idx: int) -> Optional[np.ndarray]:
        idx = max(0, min(idx, self.n - 1))
        if idx in self._cache:
            return self._cache[idx]
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        self._cache[idx] = frame
        self._order.append(idx)
        if len(self._order) > self._cap_max:
            self._cache.pop(self._order.pop(0), None)
        return frame

    def release(self):
        self.cap.release()


# ====================================================================
# 可视化: ROI 框 + 湿区掩膜 + 数值
# ====================================================================
def _wet_mask(frame, gray: np.ndarray, ref: Optional[ReferenceBundle],
              calib: ChannelCalibration,
              params: WaterLevelDetectParams) -> tuple[np.ndarray, str, float, float]:
    """复算湿区掩膜供叠加 (仅显示用, 经 separate_wet 与 detect_level 严格同口径)。

    返回 (mask, 口径标签 abs/log/otsu, drift, gain)。单帧预览用帧内自测 gain
    (随机寻帧无时序, 不套 DryGainGuard; 守卫时序仅 'c' 整段回放生效)。
    """
    if ref is not None and ref.plate_gray.shape == gray.shape:
        dry_now = extract_dry_gray(frame, calib, params)
        mask, drift, _corr, gain = separate_wet(gray, ref, dry_now, params)
        return mask, params.separation_mode, drift, gain
    _t, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return otsu > 0, "otsu", 0.0, 1.0


def _render(frame, ref_frame, calib, params, ui=None, marks_line=None):
    """构造展示画面: 左=旋转帧带ROI框, 右=ROI湿区掩膜叠加; 附检测结果文字。"""
    h, w = frame.shape[:2]
    M, (rw, rh) = rotation_matrix(calib.rotation_angle_deg, w, h)
    rotated = cv2.warpAffine(frame, M, (rw, rh))
    roi_px = calib.roi_pixels(rw, rh)
    if ui is not None:
        ui.rot_size = (rw, rh)

    # 左图: 画完整 ROI(黄) + crop 后有效框(绿)
    left = rotated.copy()
    if roi_px is not None:
        rx, ry, rww, rhh = roi_px
        cv2.rectangle(left, (rx, ry), (rx + rww, ry + rhh), (0, 255, 255), 1)
        mx, my = int(rww * params.roi_crop_x), int(rhh * params.roi_crop_y)
        cv2.rectangle(left, (rx + mx, ry + my),
                      (rx + rww - mx, ry + rhh - my), (0, 255, 0), 2)

    # 竖直参考线 (画面中线) + 交互中的画线/拖框指引
    cv2.line(left, (rw // 2, 0), (rw // 2, rh), (180, 180, 180), 1)
    if ui is not None:
        if ui.line_p0 is not None and ui.line_cur is not None:
            cv2.line(left, ui.line_p0, ui.line_cur, (255, 0, 255), 2)
        if ui.roi_drag0 is not None and ui.roi_drag_cur is not None:
            cv2.rectangle(left, ui.roi_drag0, ui.roi_drag_cur, (0, 128, 255), 1)

    # 干参考区框 (橙): 已定框实线 + 拖动中虚指引
    if calib.dry_ref_frac is not None:
        dfx, dfy, dfw, dfh = calib.dry_ref_frac
        cv2.rectangle(left, (round(dfx * rw), round(dfy * rh)),
                      (round((dfx + dfw) * rw), round((dfy + dfh) * rh)), (255, 128, 0), 1)
    if ui is not None and ui.dry_drag0 is not None and ui.dry_drag_cur is not None:
        cv2.rectangle(left, ui.dry_drag0, ui.dry_drag_cur, (255, 128, 0), 1)

    # 检测结果 (现役算法)
    ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None
    result = detect_level(frame, calib, ref=ref, params=params)

    # 右图: ROI 湿区掩膜叠加 (放大到与左图等高)
    gray = extract_roi_gray(frame, calib, params)
    if gray is not None:
        mask, mode, _drift_vis, _gain_vis = _wet_mask(frame, gray, ref, calib, params)
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        vis[mask] = (0, 0, 255)
        scale = rh / max(1, vis.shape[0])
        right = cv2.resize(vis, (max(1, int(vis.shape[1] * scale)), rh),
                           interpolation=cv2.INTER_NEAREST)
    else:
        right = np.zeros((rh, 120, 3), np.uint8)
        mode = "no_roi"

    canvas = np.hstack([left, right])
    is_abs = params.separation_mode == "abs"
    wet_show = (f"wet_thr={params.wet_pixel_threshold:.1f}" if is_abs
                else f"k={params.wet_rel_threshold:.3f}")
    lines = [
        f"valid={result.valid} reason={result.reason or '-'} sep={mode}",
        f"front={result.front_percent}  wet={result.wet_ratio:.3f}",
        f"diff_mean={result.diff_mean:.4g}  A={result.amplitude:.4g}  "
        f"drift={result.drift:+5.2f}  gain={result.gain:.4f}  roi={result.roi_size}",
        f"rot={calib.rotation_angle_deg:+.1f} flow={calib.flow_direction} {wet_show} front_lvl={params.front_ratio_level:.2f}",
    ]
    if marks_line:
        lines.append(marks_line)
    y = 18
    for i, txt in enumerate(lines):
        color = (0, 255, 0) if (i == 0 and result.valid) else (60, 220, 255)
        if i == 0 and not result.valid:
            color = (0, 165, 255)
        cv2.putText(canvas, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        y += 20
    return canvas, result


def _make_mouse_cb(ui):
    """preview 窗口鼠标回调: 左键拖=画竖直参考边(松开→定角); 右键拖=框 ROI(松开→回填滑块)。
    坐标为合成画布像素; 左图原点在 (0,0), 故直接就是旋转后画布坐标 (右图在右侧, 忽略)。"""
    def cb(event, x, y, flags, _param):
        rw, rh = ui.rot_size
        inside_left = 0 <= x < rw and 0 <= y < rh
        if event == cv2.EVENT_LBUTTONDOWN and inside_left:
            ui.line_p0 = (x, y); ui.line_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.line_p0 is not None:
            ui.line_cur = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and ui.line_p0 is not None:
            x0, y0 = ui.line_p0
            dx, dy = (x - x0), (y - y0)
            if abs(dx) + abs(dy) >= 5:                       # 忽略误点
                ui.angle_deg += angle_to_make_line_vertical(dx, dy)
                ui.angle_deg = max(-45.0, min(45.0, ui.angle_deg))
                print(f"[整定台] 画线定角 → 总角 {ui.angle_deg:+.2f}°")
            ui.line_p0 = ui.line_cur = None
        elif event == cv2.EVENT_RBUTTONDOWN and inside_left and (flags & cv2.EVENT_FLAG_CTRLKEY):
            ui.dry_drag0 = (x, y); ui.dry_drag_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.dry_drag0 is not None:
            ui.dry_drag_cur = (x, y)
        elif event == cv2.EVENT_RBUTTONUP and ui.dry_drag0 is not None:
            x0, y0 = ui.dry_drag0
            rx, ry = min(x0, x), min(y0, y)
            rww, rhh = abs(x - x0), abs(y - y0)
            if rww >= 3 and rhh >= 3:
                ui.dry_frac = box_to_roi_frac(rx, ry, rww, rhh, rw, rh)
                print(f"[整定台] 框干参考区 → frac ({ui.dry_frac[0]:.3f},{ui.dry_frac[1]:.3f},"
                      f"{ui.dry_frac[2]:.3f},{ui.dry_frac[3]:.3f})")
            ui.dry_drag0 = ui.dry_drag_cur = None
        elif event == cv2.EVENT_RBUTTONDOWN and inside_left:
            ui.roi_drag0 = (x, y); ui.roi_drag_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.roi_drag0 is not None:
            ui.roi_drag_cur = (x, y)
        elif event == cv2.EVENT_RBUTTONUP and ui.roi_drag0 is not None:
            x0, y0 = ui.roi_drag0
            rx, ry = min(x0, x), min(y0, y)
            rww, rhh = abs(x - x0), abs(y - y0)
            if rww >= 3 and rhh >= 3:
                fx, fy, fw, fh = box_to_roi_frac(rx, ry, rww, rhh, rw, rh)
                cv2.setTrackbarPos("roi_fx(/1000)", CTRL_WIN, max(0, min(999, round(fx * 1000))))
                cv2.setTrackbarPos("roi_fy(/1000)", CTRL_WIN, max(0, min(999, round(fy * 1000))))
                cv2.setTrackbarPos("roi_fw(/1000)", CTRL_WIN, max(1, min(1000, round(fw * 1000))))
                cv2.setTrackbarPos("roi_fh(/1000)", CTRL_WIN, max(1, min(1000, round(fh * 1000))))
                print(f"[整定台] 拖框 ROI → frac ({fx:.3f},{fy:.3f},{fw:.3f},{fh:.3f})")
            ui.roi_drag0 = ui.roi_drag_cur = None
    return cb


# ====================================================================
# 整段 percent(t) 时序曲线 (按 'c' 触发) —— 计算/渲染拆半, 根治卡死:
#   层1 旧循环不泵 cv2 事件 → Windows "未响应";
#   层2 plt.show() 把 matplotlib GUI mainloop 嵌进 OpenCV 键循环互卡。
#   现: _run_series 每 ~30 采样帧泵一次事件 (可 Esc 中断);
#       渲染只用 FigureCanvasAgg (无 GUI) → BGR → cv2.imshow + PNG 落盘。
# ====================================================================
def _run_series(avi: Path, calib, params, ref_frame, stride: int = 1,
                n_total: Optional[int] = None, interactive: bool = True) -> Optional[dict]:
    """整段回放跑检测出时序 (计算半)。返回 None = 用户 Esc 中断。

    stride>1 = 倍速抽帧 (跳过帧不解码); 守卫按采样帧推进 (等效低 fps 服务),
    大倍速下光照快变可能提前触发 gain_step 冻结 —— 看细节用 1x。
    泵事件期间按键会被本函数吃掉 (除 Esc), 属整段跑模态的已知取舍。
    interactive=True 每 ~30 帧泵一次 cv2 事件并允许 Esc 中断 (需 highgui 窗口);
    interactive=False 为纯 headless 计算, 不触碰 cv2.waitKey (供离线契约测试/无窗环境)。
    """
    stride = max(1, int(stride))
    ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None
    is_log = params.separation_mode == "log"
    guard = DryGainGuard()
    zone_pct = dry_zone_front_percent(calib, params)
    front_max: Optional[float] = None
    frozen_at: Optional[float] = None
    ts, pct, front, diff, drifts, gains, valid = [], [], [], [], [], [], []
    t0 = None
    approx = ((int(n_total) + stride - 1) // stride) if n_total else None
    for i, (frame, t) in enumerate(replay(avi, stride=stride)):
        if i % 30 == 0:
            if interactive and (cv2.waitKey(1) & 0xFF) == 27:
                print(f"\n[整定台] 整段跑已中断 (Esc) @ 采样帧 {i}")
                return None
            if approx:
                print(f"\r[整定台] 整段回放 {i}/{approx} ...", end="", flush=True)
        gain_ov = None
        gain_trusted = True
        if ref is not None and is_log:
            gain_ov, gain_trusted = guard.filter(
                measure_dry_gain(frame, calib, ref, params), front_max, zone_pct)
        r = detect_level(frame, calib, ref=ref, params=params, gain_override=gain_ov)
        if not gain_trusted:
            # 与 waterlevel_service._process 逐字同口径, 否则回放曲线与真机对不上
            r = replace(r, valid=False, reason="gain_step", front_percent=None)
        if r.valid and r.front_percent is not None:
            front_max = max(front_max or 0.0, r.front_percent)
        if t is not None and t0 is None:
            t0 = t
        tx = (t - t0) if (t is not None and t0 is not None) else float(i * stride)
        if frozen_at is None and guard.frozen:
            frozen_at = tx
        ts.append(tx)
        pct.append(r.wet_ratio * 100.0)
        front.append(r.front_percent if (r.valid and r.front_percent is not None) else np.nan)
        diff.append(r.diff_mean)
        drifts.append(r.drift)
        gains.append(r.gain)
        valid.append(r.valid)
    if approx:
        print()
    n_valid = sum(valid)
    wet_desc = (f"k={params.wet_rel_threshold}" if is_log
                else f"wet_thr={params.wet_pixel_threshold}")
    print(f"[整定台] 整段跑完: {len(ts)} 帧"
          + (f" (x{stride} 抽帧)" if stride > 1 else "")
          + f", valid {n_valid} 帧 "
          f"({100*n_valid/max(1,len(ts)):.0f}%), sep={params.separation_mode} "
          f"{wet_desc} front_lvl={params.front_ratio_level}"
          + (f"  [gain 冻结 @t={frozen_at:.1f} ({guard.reason})]" if frozen_at is not None else ""))
    return {"ts": ts, "pct": pct, "front": front, "diff": diff, "drifts": drifts,
            "gains": gains, "valid": valid, "frozen_at": frozen_at,
            "guard_reason": (guard.reason if frozen_at is not None else None),
            "t0": t0}


def _build_curve_fig(avi: Path, calib, params, series: dict, stride: int,
                     mark_lines=()):
    """时序 → matplotlib Figure (渲染半)。只用 FigureCanvasAgg, 严禁 pyplot。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    ts, pct, front = series["ts"], series["pct"], series["front"]
    is_log = params.separation_mode == "log"
    frozen_at = series["frozen_at"]
    fig = Figure(figsize=(11, 6))
    FigureCanvasAgg(fig)
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    ax1.plot(ts, front, ".-", ms=3, label="front% (前沿线, 读数真源)")
    ax1.plot(ts, pct, ".-", ms=2, alpha=0.45, label="掩膜浸润比 (诊断: 看湿区有没有洞)")
    ax1.set_ylabel("%"); ax1.set_ylim(-5, 105); ax1.grid(alpha=0.3)
    ax1.set_title(f"{avi.name}  rot={calib.rotation_angle_deg:+.1f} flow={calib.flow_direction} "
                  f"sep={params.separation_mode}"
                  + (f"  x{stride}" if stride > 1 else ""))
    for x, label in mark_lines:
        ax1.axvline(x, ls="--", color="tab:green", alpha=0.7)
        ax1.annotate(label, (x, 102), fontsize=8, color="tab:green",
                     ha="center", va="bottom", annotation_clip=False)
    ax1.legend(loc="best")
    ax2.plot(ts, series["diff"], ".-", ms=3, color="tab:red", label="diff_mean")
    if is_log:
        ax2.plot(ts, (np.asarray(series["gains"]) - 1.0) * 100.0, ".-", ms=2,
                 alpha=0.6, color="tab:blue", label="gain-1 (%, 干区增益)")
    else:
        ax2.plot(ts, series["drifts"], ".-", ms=2, alpha=0.6,
                 color="tab:blue", label="drift (干区漂移)")
    if frozen_at is not None:
        for ax in (ax1, ax2):
            ax.axvline(frozen_at, ls=":", color="tab:purple", alpha=0.8)
        ax2.plot([], [], ls=":", color="tab:purple",
                 label=f"gain 冻结 ({series['guard_reason']})")
    ax2.set_xlabel("t (s, 相对起始; 无时间戳时为帧序)"); ax2.set_ylabel("diff_mean")
    ax2.grid(alpha=0.3); ax2.legend(loc="best")
    fig.tight_layout()
    return fig


def _fig_to_bgr(fig) -> np.ndarray:
    """matplotlib Figure (Agg canvas) → BGR ndarray (供 cv2.imshow / imwrite)。"""
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    return cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)


def _show_and_save_curve(avi: Path, fig) -> None:
    """曲线 → PNG 落盘 (imencode 显式判成败 + 原子写) + 普通 cv2 窗口显示
    (主循环 waitKeyEx 持续泵它, 不阻塞)。"""
    img = _fig_to_bgr(fig)
    png = wl_marks.curve_png_path(avi)
    try:
        ok, buf = cv2.imencode(".png", img)   # imwrite 静默吞失败; imencode 显式回 ok
        if not ok:
            print("[整定台] 曲线 PNG 编码失败 (imencode 返回 False)", file=sys.stderr)
        else:
            tmp = png.with_suffix(png.suffix + ".tmp")   # 原子写: 先 .tmp 再 replace
            tmp.write_bytes(buf.tobytes())
            os.replace(tmp, png)
            print(f"[整定台] 曲线已落盘 → {png.name}")
    except (cv2.error, OSError) as exc:
        print(f"[整定台] 曲线 PNG 落盘失败: {exc}", file=sys.stderr)
    cv2.imshow(CURVE_WIN, img)


# ====================================================================
# 标记板打标 (数字键=距板顶 cm 整数值; 真值文件 <stem>.marks.json)
# ====================================================================
def _parse_marks_arg(s: str) -> tuple[float, ...]:
    """--marks 解析: 逗号分隔, 限 1–9 整数 cm (键位=cm 值本身), 去重非空。"""
    try:
        vals = [float(tok) for tok in s.split(",") if tok.strip()]
    except ValueError:
        raise SystemExit(f"--marks 非法: {s!r} (应为逗号分隔数字, 如 5,4,3,2,1)")
    for v in vals:
        if v != int(v) or not 1 <= v <= 9:
            raise SystemExit(f"--marks 项 {v:g} 非法: 数字键=cm 整数值, 限 1–9 整数")
    if not vals or len(set(vals)) != len(vals):
        raise SystemExit(f"--marks 为空或重复: {s!r}")
    return tuple(vals)


def _mark_lines(series: dict, marks: dict) -> list[tuple[float, str]]:
    """标注事件 → 曲线竖线 [(相对秒, '5cm'), ...]; 无墙钟基准或 ts 缺 → 跳过。"""
    t0 = series.get("t0")
    if t0 is None:
        return []
    return [(float(ev["ts"]) - float(t0), f"{float(ev['cm']):g}cm")
            for ev in marks["events"] if ev.get("ts") is not None]


def _marks_report(src, avi: Path, calib, params, ref_frame, marks: dict,
                  ref_frame_idx=None) -> dict:
    """出标记板报告: 每个标注帧用当前参数现算 front (单帧口径, 同预览; 非守卫
    时序口径 —— 标定用途足够), 组装 → 打印 → 原子落盘。ref_frame_idx 落进报告使可复现。"""
    import dataclasses
    ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None
    if marks["events"] and ref is None:
        print("[整定台] 未设参考帧 (r), 无法现算标注帧 front — 报告只含真值事件")
    fronts: dict[float, Optional[float]] = {}
    for ev in marks["events"]:
        cm = float(ev["cm"])
        fidx = int(ev["frame_idx"])
        # 帧号越界防钳位: _FrameSource.get 会把越界 idx 钳到末帧 (同 stem 重录短片
        # 场景会算出错误 front), 越界即记 None (与 frame is None 同分支)。
        frame = src.get(fidx) if 0 <= fidx < src.n else None
        if ref is None or frame is None:
            fronts[cm] = None
            continue
        r = detect_level(frame, calib, ref=ref, params=params)
        fronts[cm] = r.front_percent if (r.valid and r.front_percent is not None) else None
    report = wl_marks.build_report(
        marks, fronts,
        calib_snapshot=dataclasses.asdict(calib),
        params_snapshot=dataclasses.asdict(params),
        ref_frame_idx=ref_frame_idx)
    print(wl_marks.format_report(report))
    wl_marks.save_report(wl_marks.report_path(avi), report)
    print(f"[整定台] 报告已落盘 → {wl_marks.report_path(avi).name}")
    return report


# ====================================================================
# 存参 (按 'w'): store 原生格式, 可并入 config/water_level_calib.json
# ====================================================================
def _save_params(avi: Path, meta: dict, calib, params) -> Path:
    ch = meta.get("channel", 0) or 0
    out = Path(str(avi.with_suffix("")) + ".tuned.json")
    save_channel_configs(out, {int(ch): ChannelConfig(calib=calib, params=params)})
    print(f"[整定台] 已存 CH{ch} 调好的参数 → {out}  (store 原生格式, 可并入标定真源)")
    return out


def backend_alive(backend_url: str, timeout: float = 0.8) -> bool:
    """探测上位机后端是否在线 (GET {backend_url}/api/health)。

    单写者约束: 后端在跑时它是标定文件唯一写者, CLI 离线整定不得写盘 (否则覆盖运行态)。
    连不上/超时/非 2xx 一律视为离线 (本机 localhost 探测, 失败即真离线)。
    """
    try:
        with urlopen(f"{backend_url.rstrip('/')}/api/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (URLError, OSError, ValueError):
        return False


def commit_to_source(calib_json_path, ch, calib, params, confirm, *,
                     backend_url: str = "http://127.0.0.1:18080",
                     alive: Optional[Callable[[], bool]] = None) -> bool:
    """把当前通道调好的 calib/params 并入生产真源 config/water_level_calib.json。

    单写者: 后端在跑 → **拒绝写盘** (后端是唯一写者, 应停后端后再离线整定, 或用网页);
    后端离线 → 经 `apply_commit` 按层写盘 (判据+尺寸广播全通道, 位置仅本路), 后端下次启动读盘。
    守卫: 无 ROI (not calibrated) 拒写; confirm() 假则中止。返回是否已写。
    `alive` 可注入探测函数 (缺省探 backend_url); 便于离线测试。
    """
    if not calib.calibrated:
        print("[整定台] 当前无 ROI (未标定), 拒绝并入真源")
        return False
    probe = alive if alive is not None else (lambda: backend_alive(backend_url))
    if probe():
        print(f"[整定台] 后端在运行 ({backend_url}), 它是标定文件唯一写者 —— 拒绝 CLI 写盘。\n"
              "         请停后端后再离线整定 (或改用网页标定); 避免覆盖运行态。")
        return False
    ch = int(ch)
    existing = load_channel_configs(calib_json_path)
    old = existing.get(ch)
    print(f"[整定台] 拟并入 CH{ch} → {calib_json_path} (判据+尺寸广播全通道, 位置仅本路)")
    if old is not None:
        print(f"   旧: rot={old.calib.rotation_angle_deg:+.2f} roi_frac={old.calib.roi_frac}")
    else:
        print("   旧: (该通道原不存在)")
    print(f"   新: rot={calib.rotation_angle_deg:+.2f} roi_frac={calib.roi_frac}")
    if not confirm():
        print("[整定台] 已取消, 真源未改")
        return False
    tuned = ChannelConfig(calib=calib, params=params)
    existing.setdefault(ch, tuned)                 # apply_commit 要求本路在册 (缺则先占位)
    merged = apply_commit(existing, ch, tuned, broadcast_global=True, with_pose=True)
    save_channel_configs(calib_json_path, merged)
    print(f"[整定台] CH{ch} 已并入真源; 判据+尺寸广播 {len(merged)} 通道 (后端下次启动或 reload 生效)")
    return True


HELP = """\
[整定台热键]  空格 播放/暂停   ←/a 上一帧   →/d 下一帧   , . 快退/快进10帧
              e 终端敲精确值   r 设当前帧为参考(干板)帧   c 跑整段画 percent(t) 曲线  (进度条实时打印, Esc 中断; 曲线窗 X 关, PNG 自动落盘)
                (c_speed(xN) 滑块 = 'c' 倍速: 每 N 帧抽 1 帧检测, 跳过帧不解码; 看细节用 1)
              w 存草稿 <stem>.tuned.json   W 并入真源(后端须离线; 判据+尺寸广播全通道)
              数字键1-9 打标: 当前帧=该 cm 标线越线帧 (键=距板顶 cm 值; 重按换帧, 同帧再按取消)
              鼠标: 左键拖=画竖直边定角   右键拖=框ROI   Ctrl+右键拖=框干参考区(漂移补偿)
              h 本帮助   q/Esc 退出"""


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="液位检测离线回放整定台")
    ap.add_argument("avi", nargs="?", help="录制 .avi 路径 (省略/给目录=取最新一段)")
    ap.add_argument("--backend", default="http://127.0.0.1:18080",
                    help="上位机后端地址 (W 并入前探测其是否在线; 在线则拒绝写盘)")
    ap.add_argument("--marks", default="5,4,3,2,1",
                    help="标线高度表 (距板顶 cm, 逗号分隔 1–9 整数; 数字键=cm 值本身)")
    args = ap.parse_args(argv)

    avi = _resolve_avi(args.avi)
    calib0, params0, meta = _load_initial(avi)
    src = _FrameSource(avi)
    if src.n <= 0 or src.get(0) is None:
        print(f"[整定台] 无法解码: {avi}", file=sys.stderr)
        src.release()
        return 2
    cap_h, cap_w = src.get(0).shape[:2]
    roi_frac0 = _initial_roi_frac(calib0, cap_w, cap_h)

    print(f"[整定台] 载入 {avi}  ({src.n} 帧, {cap_w}x{cap_h}, CH{meta.get('channel', '?')})")

    marks_cm_cli = _parse_marks_arg(args.marks)
    mpath = wl_marks.marks_path(avi)
    try:
        marks = wl_marks.load_marks(mpath)
    except ValueError as exc:
        print(f"[整定台] {exc} — 忽略损坏 marks, 从空白开始 (首次打标才覆盖原文件)")
        marks = None
    if marks is None:
        marks = wl_marks.new_marks(meta.get("channel"), avi.name, marks_cm_cli)
    elif tuple(float(c) for c in marks["marks_cm"]) != marks_cm_cli \
            and args.marks != "5,4,3,2,1":
        print(f"[整定台] marks 文件已有标线表 {marks['marks_cm']} (文件权威), 忽略 --marks")
    stamps = wl_marks.load_timestamps(wl_marks.jsonl_path(avi))
    if not stamps:
        print("[整定台] ! 无 .jsonl 时间戳: 打标可用, 但区间速度/曲线叠线缺席")
    if marks["events"]:
        print(f"[整定台] {wl_marks.format_hud_line(marks)}")

    print(HELP)

    cv2.namedWindow(VIEW_WIN, cv2.WINDOW_NORMAL)
    _add_trackbars(calib0, params0, src.n, roi_frac0)

    ui = _UIState(angle_deg=calib0.rotation_angle_deg)
    ui.dry_frac = calib0.dry_ref_frac or DRY_REF_DEFAULT_BY_FLOW.get(calib0.flow_direction)
    cv2.setMouseCallback(VIEW_WIN, _make_mouse_cb(ui))

    playing = False
    last_sig = None          # 上次渲染的状态签名; 未变则不重算 (消卡顿)
    # Windows waitKeyEx 方向键全码 (Linux/GTK 为 81..84, 一并认)
    LEFT = {2424832, 81}
    RIGHT = {2555904, 83}
    while True:
        calib, params, fidx, ridx = _read_state(ui)
        sig = (repr(calib), repr(params), fidx, ridx,
               ui.line_p0, ui.line_cur, ui.roi_drag0, ui.roi_drag_cur,
               ui.dry_frac, ui.dry_drag0, ui.dry_drag_cur,
               wl_marks.format_hud_line(marks))
        if playing or sig != last_sig:
            frame = src.get(fidx)
            ref_frame = src.get(ridx)
            if frame is not None:
                canvas, _res = _render(frame, ref_frame, calib, params, ui,
                                       marks_line=wl_marks.format_hud_line(marks))
                cv2.imshow(VIEW_WIN, canvas)
            last_sig = sig

        keyfull = cv2.waitKeyEx(30 if playing else 20)
        key = keyfull & 0xFF if keyfull != -1 else 255
        if key in (ord("q"), 27):
            break
        elif key == ord(" "):
            playing = not playing
        elif key == ord("r"):
            cv2.setTrackbarPos("ref_frame", CTRL_WIN, fidx)
            print(f"[整定台] 参考帧 → {fidx}")
        elif key == ord("c"):
            stride = max(1, cv2.getTrackbarPos("c_speed(xN)", CTRL_WIN))
            series = _run_series(avi, calib, params, src.get(ridx),
                                 stride=stride, n_total=src.n)
            if series is not None:
                _marks_report(src, avi, calib, params, src.get(ridx), marks,
                              ref_frame_idx=ridx)
                try:
                    fig = _build_curve_fig(avi, calib, params, series, stride,
                                           mark_lines=_mark_lines(series, marks))
                    _show_and_save_curve(avi, fig)
                except ImportError:
                    print("[整定台] 未装 matplotlib, 曲线跳过 (报告/marks 已落盘); "
                          "pip install matplotlib")
        elif key == ord("w"):
            _save_params(avi, meta, calib, params)
        elif ord("1") <= key <= ord("9"):
            cm = float(key - ord("0"))
            if cm not in (float(c) for c in marks["marks_cm"]):
                print(f"[整定台] {cm:g}cm 不在标线表 {marks['marks_cm']} (--marks 可改)")
            else:
                action = wl_marks.toggle_event(marks, cm, fidx, stamps.get(fidx))
                wl_marks.save_marks(mpath, marks)
                zh = {"set": "打标", "moved": "改标", "cleared": "取消"}[action]
                print(f"[整定台] {cm:g}cm 线 {zh} @f{fidx}  → {mpath.name}")
        elif key == ord("h"):
            print(HELP)
        elif key == ord("e"):
            playing = False
            run_edit_repl(ui)
        elif key == ord("W"):
            ch = meta.get("channel")
            if ch is None:
                print("[整定台] meta 无 channel, 无法定位真源槽位, 中止")
            else:
                try:
                    calib_json = Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"
                    commit_to_source(
                        calib_json, int(ch), calib, params,
                        confirm=lambda: input(f"确认并入 CH{ch} 到真源? [y/N] ").strip().lower() == "y",
                        backend_url=args.backend,
                    )
                except (EOFError, OSError, ValueError) as exc:
                    print(f"[整定台] 并入中止: {exc}")
        elif keyfull in LEFT or key == ord("a"):        # ← / a: 上一帧
            cv2.setTrackbarPos("frame", CTRL_WIN, max(0, fidx - 1))
        elif keyfull in RIGHT or key == ord("d"):       # → / d: 下一帧
            cv2.setTrackbarPos("frame", CTRL_WIN, min(src.n - 1, fidx + 1))
        elif key == ord(","):
            cv2.setTrackbarPos("frame", CTRL_WIN, max(0, fidx - 10))
        elif key == ord("."):
            cv2.setTrackbarPos("frame", CTRL_WIN, min(src.n - 1, fidx + 10))

        if playing:
            nxt = fidx + 1
            if nxt >= src.n:
                nxt = 0
            cv2.setTrackbarPos("frame", CTRL_WIN, nxt)

        if cv2.getWindowProperty(VIEW_WIN, cv2.WND_PROP_VISIBLE) < 1:
            break

    src.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
