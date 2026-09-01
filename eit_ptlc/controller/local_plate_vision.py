"""
功能:
    本地视觉板位纠偏 (PALLASVision 临时替代路径)。从大恒相机 .163 取图, 用 OpenCV
    定位点样站举板 (P86) 的板中心与角度, 经真机标定的线性映射换算成机器人系
    dx_mm/dy_mm/drz_deg, 返回与 PALLAS Bridge 完全相同的契约 dict。识别失败回
    err=111/valid=False 哨兵 (交由流程内人工重拍, 不抛硬故障)。

    检测参数与 Stage2 真机标定所用完全一致, 保证参考位姿 (u0/v0/theta0) 与运行期一致。
    标定常数、坐标符号、启用开关全部在 config/local_plate_vision.yaml, 改配置即生效。

协议 (与 controller/pallas_vision_client.py 的 Bridge 返回体一致):
    返回 dict{dx_mm, dy_mm, drz_deg, err, valid, raw, source}
    补光 (DO7) 由后端在调用 Bridge /capture 前后开关, 本模块不控灯, 只负责取图与测量。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

log = logging.getLogger(__name__)

# 标定/检测配置文件: eit_ptlc/config/local_plate_vision.yaml
_CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "local_plate_vision.yaml"


@dataclass(frozen=True)
class LocalVisionCfg:
    """本地视觉纠偏配置 (相机 / 检测 / 零点参考位姿 / 标定线性系数)。

    启用总开关不在此配置, 而在 app.yaml 的 pallas_vision.local_vision_enabled。
    """

    ip: str
    exposure_us: float
    gain: float
    roi: tuple[int, int, int, int]        # 收紧 ROI (x0,y0,x1,y1): 排除机械臂与环形补光眩光
    threshold: int                        # 板暗 (灰度~45-70), 阈值取背景与板之间 (~38)
    close_ksize: int
    open_ksize: int
    min_area: int
    expect_center: tuple[float, float]    # 板名义像素位置, 多轮廓时据此选出板 (排除机械臂)
    u0: float                             # 零点参考: 理想夹持板在图像中的中心/角度
    v0: float
    theta0: float
    ax: float                             # 标定线性系数: dx_mm = sign_xy*(ax*du + bx*dv)
    bx: float
    ay: float                             #              dy_mm = sign_xy*(ay*du + by*dv)
    by: float
    arz: float                            #              drz_deg = sign_rz*(arz*dtheta)
    sign_xy: float                        # 闭环收敛符号 (待 Stage4 真机验证/翻转)
    sign_rz: float
    err_fail_code: int


def load_cfg(path: Path | None = None) -> LocalVisionCfg | None:
    """读取 config/local_plate_vision.yaml。

    参数:
        path: 可选配置路径, 缺省用模块内 _CFG_PATH
    返回:
        LocalVisionCfg; 文件不存在返回 None (调用方据此回落 PALLAS TCP 路径)
    """
    cfg_path = path or _CFG_PATH
    if not cfg_path.exists():
        return None
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cam = data.get("camera", {})
    det = data.get("detect", {})
    ref = data.get("reference", {})
    cal = data.get("calib", {})
    return LocalVisionCfg(
        ip=str(cam.get("ip", "192.168.0.163")),
        exposure_us=float(cam.get("exposure_us", 10000)),
        gain=float(cam.get("gain", 2.0)),
        roi=tuple(int(x) for x in det.get("roi", [1120, 430, 2160, 1400])),
        threshold=int(det.get("threshold", 38)),
        close_ksize=int(det.get("close_ksize", 81)),
        open_ksize=int(det.get("open_ksize", 21)),
        min_area=int(det.get("min_area", 300000)),
        expect_center=tuple(float(x) for x in det.get("expect_center", [1571, 967])),
        u0=float(ref.get("u0", 1571.7)),
        v0=float(ref.get("v0", 967.2)),
        theta0=float(ref.get("theta0", -89.4)),
        ax=float(cal.get("ax", 0.0)),
        bx=float(cal.get("bx", -0.495)),
        ay=float(cal.get("ay", 0.463)),
        by=float(cal.get("by", 0.0)),
        arz=float(cal.get("arz", 0.952)),
        sign_xy=float(cal.get("sign_xy", -1.0)),
        sign_rz=float(cal.get("sign_rz", -1.0)),
        err_fail_code=int(data.get("err_fail_code", 111)),
    )


def detect_plate_pose(gray: np.ndarray, cfg: LocalVisionCfg) -> tuple[float, float, float] | None:
    """在收紧 ROI 内定位板, 返回 (u, v, angle_deg); 找不到返回 None。

    功能:
        与 Stage2 标定检测完全一致 (同 ROI / 阈值 / 形态学 / 选最接近期望中心的轮廓 /
        minAreaRect), 保证参考位姿与运行期一致。板近方形, minAreaRect 角有 90° 对称歧义,
        故按 90° 解歧义归一到参考角 theta0 附近 (纠偏范围小, |dtheta|<=5°)。
    参数:
        gray: 单通道灰度图 (整幅相机图)
        cfg: 本地视觉配置
    返回:
        (u, v, angle_deg) 板中心像素坐标与倾角; 无板返回 None
    """
    rx0, ry0, rx1, ry1 = cfg.roi
    roi = gray[ry0:ry1, rx0:rx1]
    _, binary = cv2.threshold(roi, cfg.threshold, 255, cv2.THRESH_BINARY)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.close_ksize, cfg.close_ksize))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.open_ksize, cfg.open_ksize))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_kernel)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    expect_x, expect_y = cfg.expect_center
    best = None
    for contour in contours:
        if cv2.contourArea(contour) < cfg.min_area:
            continue
        (cx, cy), _size, angle = cv2.minAreaRect(contour)
        cx += rx0
        cy += ry0
        dist = ((cx - expect_x) ** 2 + (cy - expect_y) ** 2) ** 0.5
        if best is None or dist < best[0]:
            best = (dist, cx, cy, angle)
    if best is None:
        return None

    _dist, cx, cy, angle = best
    # 90° 解歧义: 把 minAreaRect 角归一到参考角附近, 消除正方形的四重朝向翻转
    while angle - cfg.theta0 > 45.0:
        angle -= 90.0
    while angle - cfg.theta0 < -45.0:
        angle += 90.0
    return (cx, cy, angle)


def offset_from_gray(gray: np.ndarray, cfg: LocalVisionCfg) -> dict[str, Any]:
    """检测 + 标定换算 -> 契约 dict。

    功能:
        定位板, 按真机标定线性映射把像素偏移换算成机器人系 dx_mm/dy_mm/drz_deg。
        识别不到板时回 err=err_fail_code/valid=False 哨兵 (与 PALLAS 识别失败语义一致,
        交由 robot_suction_put 流程内 human 分支重拍/中止, 不抛硬故障)。
    参数:
        gray: 整幅灰度图; cfg: 本地视觉配置
    返回:
        dict{dx_mm, dy_mm, drz_deg, err, valid, raw, source}
    """
    pose = detect_plate_pose(gray, cfg)
    if pose is None:
        log.warning("[LocalVision] 未识别到板, 回失败哨兵 err=%d valid=False", cfg.err_fail_code)
        # 注意: 不能用键名 "raw" —— 后端 _capture_bridge_result 见到 "raw" 会走 PALLAS
        # 字符串解析路径 (期望 dx/x/hxtx...), 会误解析本地视觉的字典。诊断信息放 "detail"。
        return {"dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0,
                "err": int(cfg.err_fail_code), "valid": False,
                "detail": "no_plate", "source": "local_vision"}

    u, v, theta = pose
    du = u - cfg.u0
    dv = v - cfg.v0
    dtheta = theta - cfg.theta0
    # 像素偏移 -> 机器人系 mm/deg (Stage2 真机标定线性映射)。
    # sign_xy/sign_rz 为让闭环收敛的符号: 第一版按物理推理暂定, 必须经 Stage4 真机闭环
    # 验证; 若某分量越纠越偏 (发散), 在 config 里翻转对应 sign 即可, 无需改代码。
    dx_mm = cfg.sign_xy * (cfg.ax * du + cfg.bx * dv)
    dy_mm = cfg.sign_xy * (cfg.ay * du + cfg.by * dv)
    drz_deg = cfg.sign_rz * (cfg.arz * dtheta)
    # 键名用 "detail" 而非 "raw": 后端见 "raw" 会走 PALLAS 字符串解析路径, 误解析本字典
    return {"dx_mm": round(float(dx_mm), 3), "dy_mm": round(float(dy_mm), 3),
            "drz_deg": round(float(drz_deg), 3), "err": 0, "valid": True,
            "detail": f"u={u:.1f};v={v:.1f};th={theta:.2f}", "source": "local_vision"}


def _capture_gray(cfg: LocalVisionCfg) -> np.ndarray:
    """触发 .163 相机拍一帧并读回灰度图 (measure_offset / measure_pose 共用取图路径)。

    功能:
        复用 driver/daheng_capture.capture 从 .163 取一帧 (不控相机 GPIO 补光, 补光由
        后端 DO7 在外层开关), 存临时文件后读回并转灰度。
    参数:
        cfg: 本地视觉配置
    返回:
        单通道灰度图 (np.ndarray)
    异常:
        相机取图/读图失败抛 RuntimeError (由 Bridge 转 HTTP 503, 属真实故障而非识别失败)
    """
    import tempfile

    # 延迟导入: 依赖大恒 SDK 与相机, 仅实拍时需要 (便于离线单测本模块其余逻辑)
    from eit_ptlc.driver import daheng_capture as daheng

    exposure_ms = max(1, int(cfg.exposure_us / 1000))
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "local_vision.jpg"
        params = {
            "ip": cfg.ip,
            "auto_light_control": False,          # 补光走后端 DO7, 相机不控灯
            "exposure_time": float(cfg.exposure_us),
            "gain": float(cfg.gain),
            "uv_on_time_ms": exposure_ms + 60,    # 仅为满足 capture() 的 UV 参数校验 (非 UV 用途)
            "uv_hard_cutoff_ms": exposure_ms + 180,
        }
        saved_path, _timing = daheng.capture(out_path, params)
        image = cv2.imread(str(saved_path))
    if image is None:
        raise RuntimeError(f"本地视觉: 读取相机图像失败 (ip={cfg.ip})")
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def measure_offset(cfg: LocalVisionCfg) -> dict[str, Any]:
    """触发 .163 相机拍照 + 检测 + 换算 -> 契约 dict (供 Bridge 同步调用, 阻塞式)。

    功能:
        从 .163 取一帧 (取图见 _capture_gray, 补光由后端 DO7 外层开关), 交 offset_from_gray
        检测并按标定线性映射换算成机器人系偏移。
    参数:
        cfg: 本地视觉配置
    返回:
        dict{dx_mm, dy_mm, drz_deg, err, valid, raw, source}
    异常:
        相机取图/读图失败抛 RuntimeError (由 Bridge 转 HTTP 503, 属真实故障而非识别失败)
    """
    gray = _capture_gray(cfg)
    return offset_from_gray(gray, cfg)


def measure_pose(cfg: LocalVisionCfg) -> dict[str, Any]:
    """触发 .163 相机拍照 + 检测板姿 -> {u, v, theta, valid} (供零点示教读原始位姿)。

    功能:
        从 .163 取一帧 (取图见 _capture_gray, 补光由后端 DO7 外层开关), 调 detect_plate_pose
        得板中心与角度。与 measure_offset 的区别: 不做标定换算, 直接返回原始像素位姿,
        供重新示教 reference.u0/v0/theta0。
    参数:
        cfg: 本地视觉配置
    返回:
        dict{u, v, theta, valid}; 识别不到板 valid=False (u/v/theta 回 0.0)
    异常:
        相机取图/读图失败抛 RuntimeError (由 Bridge 转 HTTP 503, 属真实故障而非识别失败)
    """
    gray = _capture_gray(cfg)
    pose = detect_plate_pose(gray, cfg)
    if pose is None:
        log.warning("[LocalVision] 示教测姿未识别到板, 回 valid=False")
        return {"u": 0.0, "v": 0.0, "theta": 0.0, "valid": False}
    u, v, theta = pose
    return {"u": round(float(u), 1), "v": round(float(v), 1),
            "theta": round(float(theta), 2), "valid": True}


def write_reference(u: float, v: float, theta: float, path: Path | None = None) -> dict[str, float]:
    """把示教测得的板姿写回 config/local_plate_vision.yaml 的 reference.u0/v0/theta0。

    功能:
        用 ruamel round-trip 仅改 reference 下 u0/v0/theta0 三个值, 保留文件注释与其余
        字段 (camera/detect/calib 一律不动)。这是零点参考唯一的程序化落盘入口 (示教用)。
    参数:
        u/v: 板中心像素坐标; theta: 板倾角 (deg); path: 可选配置路径, 缺省用 _CFG_PATH
    返回:
        dict{u0, v0, theta0} 实际写入的值
    异常:
        文件不存在或缺 reference 段抛 RuntimeError (示教前置不满足, 不静默建段)
    """
    from ruamel.yaml import YAML

    cfg_path = path or _CFG_PATH
    if not cfg_path.exists():
        raise RuntimeError(f"本地视觉配置不存在, 无法写零点: {cfg_path}")
    ryaml = YAML()
    ryaml.preserve_quotes = True
    data = ryaml.load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("reference") is None:
        raise RuntimeError("local_plate_vision.yaml 缺少 reference 段, 无法写零点")
    u0 = round(float(u), 1)
    v0 = round(float(v), 1)
    theta0 = round(float(theta), 2)
    data["reference"]["u0"] = u0
    data["reference"]["v0"] = v0
    data["reference"]["theta0"] = theta0
    with cfg_path.open("w", encoding="utf-8", newline="\n") as handle:
        ryaml.dump(data, handle)
    log.info("[LocalVision] 已写回零点参考 u0=%.1f v0=%.1f theta0=%.2f -> %s", u0, v0, theta0, cfg_path)
    return {"u0": u0, "v0": v0, "theta0": theta0}


def _main() -> None:
    """CLI 自测。

    用法:
        # 离线: 对给定图像跑检测+换算 (不需相机)
        python -m eit_ptlc.controller.local_plate_vision <image.jpg>
        # 实拍: 触发 .163 一次并输出偏移
        python -m eit_ptlc.controller.local_plate_vision --capture
    """
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_cfg()
    if cfg is None:
        print("未找到 config/local_plate_vision.yaml")
        return
    args = sys.argv[1:]
    if args and args[0] == "--capture":
        print(json.dumps(measure_offset(cfg), ensure_ascii=False))
    elif args:
        gray = cv2.cvtColor(cv2.imread(args[0]), cv2.COLOR_BGR2GRAY)
        print(json.dumps(offset_from_gray(gray, cfg), ensure_ascii=False))
    else:
        print(_main.__doc__)


if __name__ == "__main__":
    _main()
