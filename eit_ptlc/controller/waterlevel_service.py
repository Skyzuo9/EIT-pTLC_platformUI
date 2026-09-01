"""液位拉帧检测服务 (上位机周期任务)
========================================
功能:
    检测从香橙派搬到上位机后的运行时主服务。周期性 (默认 2s, 任务不时间敏感) 对每个
    "活跃通道" 从香橙派单帧端点 GET /frame/ch{N} 拉一张原始帧, 跑 detect_level 算出
    "溶剂前沿到达 ROI 的百分比", 维护只读快照供 API/UI 消费。

职责边界:
    - 几何/占比算法 → waterlevel_detector (纯函数)
    - 标定真源 → waterlevel_store (8 通道 ChannelConfig)
    - 设备在线/命令下发 → orangepi_waterlevel (MQTT) 仍各司其职
    本服务只做"拉帧→检测→快照" + 参考图捕获 + 活跃通道节流。

节流 (复用现有按需启停):
    active 集合由上位机 (ResourceManager) 按展缸占用注入; 只有活跃通道才拉帧检测。
    香橙派侧相机的激活由既有 set_active_channels(MQTT) 管, 两者共用同一活跃集合。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import cv2
import httpx
import numpy as np

from eit_ptlc.controller.waterlevel_detector import (
    DryGainGuard,
    LevelResult,
    ReferenceBundle,
    compute_reference,
    detect_level,
    extract_roi_gray,
    dry_zone_front_percent,
    measure_dry_gain,
    render_debug_frame,
)
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    default_configs,
    load_channel_configs,
    save_channel_configs,
)

log = logging.getLogger(__name__)

# 暗帧守卫: ROI 均亮 < 此比例×参考均亮 → 判暗帧 (相机重开曝光爬坡等), 弃帧不检测。
# 全板浸润的真实变暗 ~10-30% (wet_rel_threshold 5%/px 即判湿), 远到不了 65% — 0.35 安全。
DARK_FRAME_RATIO = 0.35

# 参考窗口暗帧地板 (绝对灰度): 冷相机曝光爬坡的近黑帧不入 median, 防毒参考基线。
# 相对守卫 (DARK_FRAME_RATIO) 需要已有参考作基线, 建窗期没有 → 用绝对地板兜。
REF_DARK_FLOOR = 15.0

# update_calibration 的"未传参"哨兵: 区分 缺省(保持现值) 与 显式 None(清除干参考区)
_UNSET = object()

# 每通道走势历史长度: 900 × interval(2s) ≈ 30 分钟, 覆盖一次完整展开。
# 内存 ~900×8×40B ≈ 300KB, 可忽略。
HISTORY_MAXLEN = 900

# 调试叠加图 JPEG 质量 (要看清红色掩膜边界, 比原始帧代理的 70 略高)
DEBUG_JPEG_QUALITY = 80


class WaterLevelDetectService:
    """上位机拉帧检测服务。

    用法:
        svc = WaterLevelDetectService(orangepi_ip, stream_port, config_path)
        await svc.start()
        svc.set_active_channels({1, 3})   # 由 RM 注入
        snap = svc.snapshot()
        await svc.stop()
    """

    def __init__(self, orangepi_ip: str, stream_port: int,
                 config_path: Optional[Union[str, Path]] = None,
                 interval: float = 2.0, grab_timeout: float = 3.0,
                 wl_client=None, max_active_channels: int = 0,
                 ref_frames: int = 15):
        self._ip = orangepi_ip
        self._port = stream_port
        self._config_path = Path(config_path) if config_path else None
        self._interval = interval
        self._grab_timeout = grab_timeout
        # 并发采集相机数上限 (0=不限): 香橙派 8 路 UVC 同开会顶爆 USB2 带宽/供电致整段丢流 (见现场 wl.log)。
        # >0 时 _push_remote_active 只激活 pinned(录制/查看中)+低号补齐至上限, 其余停用。
        self._max_active_channels = int(max_active_channels)
        # 需求钉住的通道, 分两档优先级 (上限裁剪时 录制 > 查看 > 其余):
        #   _pin_record 录制中 = 硬 pin, 恒不被裁 → 录制途中误点别的 ch 也挤不掉正在录的相机 (录制神圣)
        #   _pin_view   单路查看中 = 软 pin, 上限不够时先于录制让位
        self._pin_record: set[int] = set()
        self._pin_view: set[int] = set()

        # 全 8 通道默认 + 文件覆盖 (缺失通道保默认未标定)
        merged = default_configs()
        if self._config_path:
            merged.update(load_channel_configs(self._config_path))
        self._configs: dict[int, ChannelConfig] = merged

        # 参考窗口帧数: request_reference 后连续 N 帧逐像素 median 成基线 (抗单帧噪声/瞬扰)
        self._ref_frames = max(1, int(ref_frames))

        self._refs: dict[int, ReferenceBundle] = {}   # 通道 → 干板参考 (板+干区灰度)
        self._results: dict[int, LevelResult] = {}    # 通道 → 最近检测结果
        self._observed_at: dict[int, str] = {}        # 通道 → 最近完成检测的 UTC 时间
        self._reachable: dict[int, bool] = {}         # 通道 → 最近拉帧是否成功
        self._fail_streak: dict[int, int] = {}        # 通道 → 连续拉帧失败次数 (边沿日志用)
        self._fail_since: dict[int, float] = {}       # 通道 → 本次中断起点 (monotonic)
        self._active: set[int] = set()
        self._ref_pending: set[int] = set()           # 参考窗口进行中的通道
        self._ref_accum: dict[int, list[ReferenceBundle]] = {}   # 窗口逐帧累积
        self._guards: dict[int, DryGainGuard] = {}    # 通道 → 干区增益冻结守卫 (log 模式)
        self._front_max: dict[int, float] = {}        # 通道 → 参考以来最大前沿 (%, 守卫 hint)

        # 调试叠加图的素材: 必须存"产出当前 _results[ch] 的那一帧"与"当时那次守卫增益",
        # 渲染时原样回喂 render_debug_frame → 画面与数字严格同口径 (自测 gain 会分叉)。
        self._last_frame: dict[int, np.ndarray] = {}
        self._last_gain: dict[int, Optional[float]] = {}
        # 通道 → 走势历史 (无效点也记, 曲线上表现为断口 —— 那正是要看的信息)
        self._history: dict[int, deque] = {}

        self._wl_client = wl_client                   # 注入则由本服务下发激活香橙派相机
        self._resync_every = max(1, round(30.0 / interval))  # 每 ~30s 重发激活防丢包
        self._task: Optional[asyncio.Task] = None
        self._stop = False

    # ---- 生命周期 ----
    async def start(self) -> None:
        self._stop = False
        if not self._active:
            self._active = self._calibrated_channels()   # 默认: 已标定通道开箱即检
        await self._push_remote_active()                 # 激活香橙派对应相机 (有 wl_client 时)
        self._task = asyncio.create_task(self._loop(), name="wl-detect-loop")
        log.info("[WL] 拉帧检测服务已启动 (源 http://%s:%s, 周期 %.1fs, 活跃 %s)",
                 self._ip, self._port, self._interval, sorted(self._active))

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("[WL] 拉帧检测服务已停止")

    # ---- 外部控制 ----
    def set_active_channels(self, channels) -> None:
        """注入活跃通道集合 (RM 按展缸占用计算); 仅这些通道拉帧检测。不触发 MQTT。"""
        self._active = {int(c) for c in channels}

    async def set_active_channels_async(self, channels) -> None:
        """设置活跃通道并下发香橙派激活对应相机 (检测权威 = 上位机 detect service)。"""
        self._active = {int(c) for c in channels}
        await self._push_remote_active()

    def _calibrated_channels(self) -> set[int]:
        return {ch for ch, cfg in self._configs.items() if cfg.calib.calibrated}

    def _capped_active(self) -> list[int]:
        """按 max_active_channels 裁剪活跃采集集合 (0=不限)。

        优先级: 录制中(_pin_record) > 查看中(_pin_view) > 其余按通道号。取前 cap 个; 超限的不下发
        → 香橙派 set 语义会停用它们, 把同开的 UVC 相机数压在 USB 预算内。录制通道恒排第一 ⇒ 录制
        途中误点别的 ch 页面也挤不掉正在录的那路相机 (最坏情况: cap 内塞不下时先丢查看 pin/普通路)。
        """
        active_set = set(self._active)
        active = sorted(active_set)
        cap = self._max_active_channels
        if cap <= 0 or len(active) <= cap:
            return active
        rec = sorted(c for c in active_set if c in self._pin_record)
        view = sorted(c for c in active_set if c in self._pin_view and c not in self._pin_record)
        rest = sorted(c for c in active if c not in self._pin_record and c not in self._pin_view)
        kept = sorted((rec + view + rest)[:cap])
        dropped = [c for c in active if c not in kept]
        if dropped:
            log.warning("[WL] 活跃相机 %d 路超 max_active_channels=%d → 只激活 %s (停用 %s; 录制pin=%s 查看pin=%s)",
                        len(active), cap, kept, dropped, rec, view)
        return kept

    async def _push_remote_active(self) -> None:
        """向香橙派下发 set_active_channels 激活活跃通道相机 (幂等; 无 wl_client 则跳过)。

        stream_channels 恒为空: 检测走单帧 /frame 端点 (不需持久 /stream); 实时视频流由单路
        调试视图的 stream_start/stop 独立人工管 (网格总览也走 /frame 轮询, 与流无关)。旧版把
        stream_channels=active 会白白把每个活跃通道拉进 STREAM 态 (无节流推流循环隐患)。
        channels 经 _capped_active 按 max_active_channels 裁剪, 防 8 路 UVC 同开顶爆 USB。
        """
        if self._wl_client is None:
            return
        try:
            await self._wl_client.send_command("set_active_channels", {
                "channels": self._capped_active(),
                "stream_channels": []})
        except Exception as exc:
            log.warning("[WL] 下发 set_active_channels 失败: %s", exc)

    async def ensure_active(self, channel: int, *, record: bool = False) -> None:
        """钉住并激活某通道并立即下发 (不必等 ~30s 周期重发)。

        record=True (开始录制): 硬 pin (_pin_record), 上限下优先级最高, 恒不被裁 → 录制途中误点
                                别的 ch 页面挤不掉正在录的相机;
        record=False (打开单路查看): 软 pin (_pin_view), 上限不够时先于录制 pin 让位。
        一路可同时被录+看 (两档都进)。
        """
        ch = int(channel)
        (self._pin_record if record else self._pin_view).add(ch)
        self._active.add(ch)
        await self._push_remote_active()

    async def release_pin(self, channel: int, *, record: bool = False) -> None:
        """解除对应档 pin (停录 record=True / 离开查看 record=False); 立即下发使上限重新生效。

        只解本档 (一路可同时被录+看, 停录后若仍在看则查看 pin 仍在); 不从 _active 移除 ——
        是否续采交回常规活跃集判定 (仍已标定则留, 只是上限不够时可能被裁)。
        """
        ch = int(channel)
        pin = self._pin_record if record else self._pin_view
        if ch in pin:
            pin.discard(ch)
            await self._push_remote_active()

    def request_reference(self, channel: int) -> None:
        """请求捕获干板参考: 自下一轮拉帧起连续 ref_frames 帧逐像素 median 成基线。

        窗口约 N×interval (默认 15×2s ≈ 30s), 应在**关盖后、前沿进入 ROI 前**触发
        (median 对 <50% 帧的瞬时污染鲁棒); 窗口期该通道不产出检测结果。
        """
        ch = int(channel)
        self._ref_accum.pop(ch, None)   # 重触发 → 重开窗口
        self._ref_pending.add(ch)

    def has_reference(self, channel: int) -> bool:
        """该通道是否已有干板参考 (capture_reference 轮询完成判据)。

        窗口进行中 (pending) 不算"已有" — 否则第二个 run 起旧板参考仍在 _refs,
        capture_reference 首拍即 True 短路, 新板根本没等新窗口 (违反"每 run 无条件重拍")。
        旧参考保留在 _refs 供检测连续性, 直至新基线落位覆盖 (手动按钮 UX 不变)。
        """
        ch = int(channel)
        return ch in self._refs and ch not in self._ref_pending

    def cancel_reference(self, channel: int) -> None:
        """撤销挂起的参考窗口 (采集超时时调): 防帧源迟到后在湿板上补采毒参考。"""
        ch = int(channel)
        self._ref_pending.discard(ch)
        self._ref_accum.pop(ch, None)

    def _invalidate_detect_state(self, ch: int) -> None:
        """标定变更/参考失效时清空该通道运行态 (参考图/窗口累积/守卫/前沿记忆)。"""
        self._refs.pop(ch, None)
        self._ref_accum.pop(ch, None)
        self._guards.pop(ch, None)
        self._front_max.pop(ch, None)
        # 调试帧素材一并丢: 旧帧配新标定渲出来的画面与 _results 里的旧数字对不上,
        # 宁可让「识别」页空一拍 (下一轮 ~2s 就补上), 也不给一张自相矛盾的图。
        self._last_frame.pop(ch, None)
        self._last_gain.pop(ch, None)

    def _note_history(self, ch: int, result: LevelResult, ts: str) -> None:
        """向该通道走势历史追加一点 (有效/无效都记)。

        无效点在前端曲线上表现为断口 —— 中断/暗帧/等待前沿本身就是要看的信息, 不能抹平。
        """
        hist = self._history.setdefault(ch, deque(maxlen=HISTORY_MAXLEN))
        hist.append({
            "t": ts,
            "front_percent": result.front_percent if result.valid else None,
            "valid": bool(result.valid),
            "reason": result.reason,
        })

    def get_config(self, channel: int) -> Optional[ChannelConfig]:
        return self._configs.get(int(channel))

    # ---- 标定/参数写入 (上位机真源; 取代香橙派 set_roi/set_calibration MQTT 下发) ----
    def _persist(self) -> None:
        if self._config_path is None:
            return
        try:
            save_channel_configs(self._config_path, self._configs)
        except Exception as exc:
            log.warning("[WL] 标定持久化失败: %s", exc)

    def save_all(self) -> None:
        """显式持久化全部通道配置到 calib_path (供 save_detect_param 确认)。"""
        self._persist()

    def reload(self) -> dict[int, ChannelConfig]:
        """从标定文件重读全部通道配置 (单写者兜底 + 外部离线写盘后同步)。

        运行中服务是文件唯一写者; 若离线工具在服务停机时改过盘, 或需从外部同步, 调此重读。
        参考图随标定失效, 一并清空。无 config_path (内存态) 则空操作。
        """
        if self._config_path is None:
            return self._configs
        merged = default_configs()
        merged.update(load_channel_configs(self._config_path))
        self._configs = merged
        self._refs.clear()
        self._ref_accum.clear()
        self._guards.clear()
        self._front_max.clear()
        log.info("[WL] 已从 %s 重载标定配置 (%d 通道)", self._config_path, len(self._configs))
        return self._configs

    def update_roi(self, channel: int, x, y, w, h, save: bool = True) -> bool:
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return False
        cfg.calib.roi_bbox = (int(x), int(y), int(w), int(h))
        cfg.calib.roi_frac = None             # 新手输像素 ROI(相对当前推流分辨率)→ 清旧比例, 避免陈旧优先
        self._invalidate_detect_state(int(channel))   # ROI 变 → 参考/守卫失效, 待重抓
        if save:
            self._persist()
        return True

    def clear_roi(self, channel: int, save: bool = True) -> None:
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return
        cfg.calib.roi_bbox = None
        self._invalidate_detect_state(int(channel))
        if save:
            self._persist()

    def update_calibration(self, channel: int, rotation_angle_deg=None,
                           roi_bbox=None, roi_frac=None, flow_direction=None,
                           dry_ref_frac=_UNSET, save: bool = True) -> bool:
        """写入单通道标定 (旋转角/ROI/流向/干参考区), 内存生效并可选持久化。

        dry_ref_frac: 缺省哨兵=保持现值; 4 元序列=设置干参考区 (旋转后画布比例);
        None=显式清除。任何标定变更都使参考图/增益守卫失效 (需重采参考)。
        """
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return False
        if rotation_angle_deg is not None:
            cfg.calib.rotation_angle_deg = float(rotation_angle_deg)
        # roi_frac 优先 (分辨率无关真源); 设 frac 即清 bbox 避免陈旧优先
        if roi_frac is not None and len(roi_frac) == 4:
            cfg.calib.roi_frac = tuple(float(v) for v in roi_frac)
            cfg.calib.roi_bbox = None
        elif roi_bbox is not None and len(roi_bbox) == 4:
            cfg.calib.roi_bbox = tuple(int(v) for v in roi_bbox)
            cfg.calib.roi_frac = None         # 新像素 ROI → 清旧比例 (同 update_roi)
        if flow_direction in ("left_to_right", "right_to_left", "bottom_to_top"):
            cfg.calib.flow_direction = flow_direction
        if dry_ref_frac is not _UNSET:
            if dry_ref_frac is None:
                cfg.calib.dry_ref_frac = None          # 显式清除干参考区
            elif isinstance(dry_ref_frac, (list, tuple)) and len(dry_ref_frac) == 4:
                cfg.calib.dry_ref_frac = tuple(float(v) for v in dry_ref_frac)
        self._invalidate_detect_state(int(channel))   # 标定变 → 参考/守卫失效
        if save:
            self._persist()
        return True

    def update_params(self, channel: int, params: dict, save: bool = True) -> bool:
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return False
        fd = params.get("flow_direction")           # flow_direction 归 calib
        if fd in ("left_to_right", "right_to_left", "bottom_to_top"):
            cfg.calib.flow_direction = fd
        p = cfg.params
        sep = params.get("separation_mode")         # 口径枚举: 仅收合法值
        if sep in ("abs", "log"):
            p.separation_mode = sep
        for k in ("roi_crop_x", "roi_crop_y", "blur_ksize",
                  "wet_pixel_threshold", "wet_rel_threshold", "front_ratio_level",
                  "front_gap_frac", "trigger_percent_t2", "t1_offset"):
            if k in params:
                setattr(p, k, type(getattr(p, k))(params[k]))
        if save:
            self._persist()
        return True

    def get_params(self, channel: int) -> dict:
        """返回通道当前检测参数 (含 flow_direction), 供前端读初值。"""
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return {}
        p = cfg.params
        return {
            "flow_direction": cfg.calib.flow_direction,
            "roi_crop_x": p.roi_crop_x, "roi_crop_y": p.roi_crop_y,
            "blur_ksize": p.blur_ksize,
            "separation_mode": p.separation_mode,
            "wet_pixel_threshold": p.wet_pixel_threshold,
            "wet_rel_threshold": p.wet_rel_threshold,
            "front_ratio_level": p.front_ratio_level,
            "front_gap_frac": p.front_gap_frac,
            "trigger_percent_t2": p.trigger_percent_t2,
            "t1_offset": p.t1_offset,
        }

    def get_calibration(self, channel: int) -> dict:
        """返回通道当前标定 (rotation/roi_frac/roi_bbox/flow/干参考区), 供前端标定面板
        预加载 seed, 避免保存时用默认值静默覆盖已存标定。缺通道 → {}。"""
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return {}
        c = cfg.calib
        return {
            "rotation_angle_deg": c.rotation_angle_deg,
            "roi_frac": list(c.roi_frac) if c.roi_frac is not None else None,
            "roi_bbox": list(c.roi_bbox) if c.roi_bbox is not None else None,
            "flow_direction": c.flow_direction,
            "dry_ref_frac": list(c.dry_ref_frac) if c.dry_ref_frac is not None else None,
            "calibrated": bool(c.calibrated),
        }

    # ---- 只读快照 ----
    def snapshot(self) -> dict:
        """返回各通道最新检测快照 (front_percent 为读数真源, valid=False 时为 None)。"""
        channels: dict[int, dict] = {}
        for ch, r in sorted(self._results.items()):
            cfg = self._configs.get(ch)
            guard = self._guards.get(ch)
            channels[ch] = {
                "channel": ch,
                "front_percent": r.front_percent,
                "valid": r.valid,
                "reason": r.reason,
                "wet_ratio": round(r.wet_ratio, 4),
                "diff_mean": round(r.diff_mean, 4),
                "drift": round(r.drift, 2),
                "gain": round(r.gain, 4),
                "amplitude": round(r.amplitude, 4),
                "gain_frozen": bool(guard.frozen) if guard is not None else False,
                # 三种冻结原因语义完全不同 (前沿逼近干区 / 干区被打湿 / —— 见 DryGainGuard),
                # 页面只显示"已冻结"时无从归因, 故一并上报
                "gain_frozen_reason": (guard.reason or None) if guard is not None else None,
                "has_ref": ch in self._refs,
                "reachable": self._reachable.get(ch, False),
                "calibrated": bool(cfg and cfg.calib.calibrated),
                "flow_direction": cfg.calib.flow_direction if cfg else None,
                "observed_at": self._observed_at.get(ch),
            }
        return {
            "channels": channels,
            "active": sorted(self._active),
            "reachable_any": any(self._reachable.get(c, False) for c in self._active),
        }

    def debug_frame_jpeg(self, channel: int,
                         inplace_overlay: bool = True) -> Optional[bytes]:
        """渲染该通道的检测叠加图并编码为 JPEG; 无缓存帧 (未激活/尚未检测) 返回 None。

        用 _process 存下的原帧与当次守卫增益复算掩膜, 故画面与 snapshot 里的数字同出一帧。
        参考窗口期传 result=None: 此时没有本帧检测结果, 不能拿上一轮的旧数字画 HUD/前沿线。
        按需渲染 —— 没人打开「识别」页就零开销。

        inplace_overlay=False: 板面不着色也不画前沿线, 只留标定框 (供与开启态对照看判得准不准)。
        """
        ch = int(channel)
        frame = self._last_frame.get(ch)
        cfg = self._configs.get(ch)
        if frame is None or cfg is None:
            return None
        result = None if ch in self._ref_pending else self._results.get(ch)
        try:
            canvas = render_debug_frame(frame, cfg.calib, self._refs.get(ch),
                                        cfg.params, result, self._last_gain.get(ch),
                                        inplace_overlay=inplace_overlay)
        except Exception:
            log.exception("[WL] CH%s 调试叠加图渲染失败", ch)
            return None
        ok, buf = cv2.imencode(".jpg", canvas,
                               [int(cv2.IMWRITE_JPEG_QUALITY), DEBUG_JPEG_QUALITY])
        if not ok:
            return None
        return buf.tobytes()

    def history(self, channel: int, limit: int = HISTORY_MAXLEN) -> list[dict]:
        """返回该通道最近 limit 个走势点 (最旧在前); 无历史返回空列表。"""
        hist = self._history.get(int(channel))
        if not hist:
            return []
        n = max(1, min(int(limit), HISTORY_MAXLEN))
        return list(hist)[-n:]

    # ---- 周期循环 ----
    async def _loop(self) -> None:
        ticks = 0
        while not self._stop:
            try:
                await self._tick()
                ticks += 1
                if ticks % self._resync_every == 0:
                    await self._push_remote_active()   # 周期重发激活防丢包 (~30s)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[WL] 拉帧检测 tick 异常")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        """一轮: 串行拉取并检测各活跃通道 (通常 1~4 路, 2s 周期, 串行足够)。"""
        active = sorted(self._active)
        if not active:
            return
        async with httpx.AsyncClient(timeout=self._grab_timeout, trust_env=False) as client:
            for ch in active:
                frame = await self._grab(client, ch)
                self._note_reachable(ch, frame is not None)
                if frame is None:
                    continue
                await self._process(ch, frame)

    def _note_reachable(self, ch: int, ok: bool) -> None:
        """拉帧成败的边沿日志: 中断开始/恢复各一条 (含时长与失败次数), 不逐帧刷屏。

        UI 画面对中断"保持最后一帧"不再黑闪 (framePoll 前端), 中断事实全靠这里进日志;
        snapshot.reachable 仍逐帧真值, wait_level 的 unreachable 降级判据不受影响。
        """
        self._reachable[ch] = ok
        if ok:
            streak = self._fail_streak.pop(ch, 0)
            since = self._fail_since.pop(ch, None)
            if streak:
                dur = time.monotonic() - since if since is not None else 0.0
                log.warning("[WL] CH%s 拉帧恢复 (中断 %.1fs, 连续失败 %d 次)", ch, dur, streak)
            return
        streak = self._fail_streak.get(ch, 0) + 1
        self._fail_streak[ch] = streak
        if streak == 1:
            self._fail_since[ch] = time.monotonic()
            log.warning("[WL] CH%s 拉帧中断 (源 http://%s:%s/frame/ch%s); 恢复时汇报中断时长",
                        ch, self._ip, self._port, ch)

    async def _grab(self, client: httpx.AsyncClient, ch: int):
        """GET /frame/ch{N} → 解码为 BGR; 失败/非 200/损坏返回 None。"""
        url = f"http://{self._ip}:{self._port}/frame/ch{ch}"
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            log.debug("[WL] CH%s 拉帧失败: %s", ch, exc)
            return None
        if resp.status_code != 200:
            return None
        arr = np.frombuffer(resp.content, np.uint8)
        if arr.size == 0:
            return None
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    async def _process(self, ch: int, frame) -> None:
        """参考窗口捕获 (若 pending) 或检测; CPU 操作走 executor 不阻塞事件循环。

        log 模式检测前先量干区增益并经 DryGainGuard 过滤 (front 逼近 / 干区自卫 /
        步限三判据冻结), 过滤后的 gain 作 override 注入 detect_level —— 干区被前沿
        打湿后的中毒测量到不了分离层, percent 不会被坏补偿拉崩。
        """
        cfg = self._configs.get(ch)
        if cfg is None:
            return
        loop = asyncio.get_running_loop()
        if ch in self._ref_pending:
            # 参考窗口期不产检测结果。仍存帧 (让「识别」页看得见正在采的干板画面, 便于确认
            # 关盖/无前沿) 并记一个无效点, 使曲线上这段 ~30s 空白自带解释而非莫名断线。
            self._last_frame[ch] = frame
            self._last_gain[ch] = None
            self._note_history(ch, LevelResult(valid=False, reason="ref_window"),
                               datetime.now(timezone.utc).isoformat())
            bundle = await loop.run_in_executor(
                None, compute_reference, frame, cfg.calib, cfg.params)
            if bundle is not None:
                if float(bundle.plate_gray.mean()) < REF_DARK_FLOOR:
                    log.warning("[WL] CH%s 参考窗口暗帧 (板均亮 %.1f < %.1f), 弃帧不入基线",
                                ch, float(bundle.plate_gray.mean()), REF_DARK_FLOOR)
                    return
                acc = self._ref_accum.setdefault(ch, [])
                if acc and acc[0].plate_gray.shape != bundle.plate_gray.shape:
                    acc.clear()          # 窗口期标定被改 → 尺寸不齐, 重开窗口
                acc.append(bundle)
                if len(acc) >= self._ref_frames:
                    plate = np.median([b.plate_gray for b in acc],
                                      axis=0).astype(np.float32)
                    drys = [b.dry_gray for b in acc]
                    dry = None
                    if (all(d is not None for d in drys)
                            and len({d.shape for d in drys}) == 1):
                        dry = np.median(drys, axis=0).astype(np.float32)
                    self._refs[ch] = ReferenceBundle(plate_gray=plate, dry_gray=dry)
                    self._ref_pending.discard(ch)
                    self._ref_accum.pop(ch, None)
                    self._guards[ch] = DryGainGuard()   # 新基线 → 守卫/前沿记忆归零
                    self._front_max.pop(ch, None)
                    log.info("[WL] CH%s 参考已捕获 (%d 帧 median, 板 %s, 干区 %s)",
                             ch, self._ref_frames, plate.shape,
                             None if dry is None else dry.shape)
            return

        ref = self._refs.get(ch)
        if ref is not None:
            gray = await loop.run_in_executor(
                None, extract_roi_gray, frame, cfg.calib, cfg.params)
            if (gray is not None
                    and float(gray.mean()) < DARK_FRAME_RATIO * float(ref.plate_gray.mean())):
                prev = self._results.get(ch)
                if prev is None or prev.reason != "frame_dark":   # 边沿日志, 持续暗不刷屏
                    log.warning("[WL] CH%s 暗帧 (ROI 均亮 %.1f < %.2f×参考 %.1f), 弃帧不检测",
                                ch, float(gray.mean()), DARK_FRAME_RATIO,
                                float(ref.plate_gray.mean()))
                dark_result = LevelResult(valid=False, reason="frame_dark",
                                          roi_size=(gray.shape[1], gray.shape[0]))
                self._results[ch] = dark_result
                ts = datetime.now(timezone.utc).isoformat()
                self._observed_at[ch] = ts
                # 暗帧也留素材: 「识别」页要能看见"画面到底暗成什么样"才好排查
                self._last_frame[ch] = frame
                self._last_gain[ch] = None
                self._note_history(ch, dark_result, ts)
                return
        gain_override = None
        gain_trusted = True
        if ref is not None and cfg.params.separation_mode == "log":
            guard = self._guards.setdefault(ch, DryGainGuard())
            measure = await loop.run_in_executor(
                None, measure_dry_gain, frame, cfg.calib, ref, cfg.params)
            gain_override, gain_trusted = guard.filter(
                measure, self._front_max.get(ch),
                dry_zone_front_percent(cfg.calib, cfg.params))
        result = await loop.run_in_executor(
            None, detect_level, frame, cfg.calib, ref, cfg.params, gain_override)
        if not gain_trusted:
            # 干区亮度一拍跳变 = 光照真变了。守卫已跟上新 gain 作后续基线, 但参考图仍是旧光照
            # 下拍的, 本帧补偿只纠得动乘性分量 —— 读数不可采信。与暗帧弃帧同结构: 记无效点
            # 而非上报一个算得出来但错的数 (见 DryGainGuard 的 ③ 说明)。
            prev = self._results.get(ch)
            if prev is None or prev.reason != "gain_step":        # 边沿日志, 持续闪烁不刷屏
                log.warning("[WL] CH%s 干区照度一拍跳变超限, 本帧不可信 (gain 已跟进 %.4f)",
                            ch, gain_override if gain_override is not None else 1.0)
            # front_percent 一并清空: 全局约定"无效帧不带读数" (暗帧路径与 detect_level 的
            # 非 ok 分支同此), snapshot / trigger 都依赖它
            result = replace(result, valid=False, reason="gain_step", front_percent=None)
        self._results[ch] = result
        if result.valid and result.front_percent is not None:
            self._front_max[ch] = max(self._front_max.get(ch, 0.0),
                                      float(result.front_percent))
        ts = datetime.now(timezone.utc).isoformat()
        self._observed_at[ch] = ts
        # 存渲染素材: frame 与 gain_override 必须是"产出上面这个 result 的那一次"的原值,
        # 调试叠加图据此复算掩膜 → 所见即所算 (见 render_debug_frame 口径约定)
        self._last_frame[ch] = frame
        self._last_gain[ch] = gain_override
        self._note_history(ch, result, ts)
