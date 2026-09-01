from __future__ import annotations

import asyncio
import logging
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import httpx

from eit_ptlc.config.models import PallasVisionCfg


_TERMINATORS = {
    "none": b"",
    "cr": b"\r",
    "lf": b"\n",
    "crlf": b"\r\n",
    "nul": b"\0",
}
_NUMERIC_TOKEN = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
_MAX_ABS_XY_MM = 10.0
_MAX_ABS_RZ_DEG = 5.0
LightSetter = Callable[[bool], Awaitable[None]]
log = logging.getLogger(__name__)


class PallasVisionError(RuntimeError):
    """PALLASVision TCP 触发或结果解析失败。"""


class PallasVisionResultError(PallasVisionError):
    """PALLASVision 已返回结果，但结果缺失、不可解析或超出允许范围。"""


class PallasVisionClient:
    """PALLASVision TCP 纠偏客户端。

    callback 模式: 上位机监听本地端口, 触发 PALLAS TCP Server 后等待 TCP Client 回传。
    reply 模式: 触发连接本身直接读回包。两种模式返回同一偏移 dict。
    """

    def __init__(self, cfg: PallasVisionCfg, *, light_setter: LightSetter | None = None) -> None:
        self.cfg = cfg
        self._light_setter = light_setter
        self._lock = asyncio.Lock()

    async def capture_plate_offset(self, *, apply_rz: bool = False) -> dict[str, Any]:
        if not self.cfg.enabled:
            return neutral_offset("disabled")
        if self.cfg.mock:
            return neutral_offset("mock")
        async with self._lock:
            result = await self._capture_result_with_light()
        if not apply_rz:
            result["drz_deg"] = 0.0
        result["source"] = result.get("source") or "pallas_vision"
        return result

    async def capture_plate_pose(self) -> dict[str, Any]:
        """示教用: 开补光拍一次, 返回板原始像素位姿 {u, v, theta, valid} (走 Bridge /measure_pose)。

        功能:
            与 capture_plate_offset 同样的补光时序 (DO7 开→settle→拍→关) 与串行锁, 但不做纠偏
            换算, 直接返回 detect 出的原始位姿, 供板位对位控制台重新示教零点 reference。
            仅本地视觉 Bridge 模式可用 (示教对象就是本地视觉的零点)。
        返回:
            dict{u, v, theta, valid}; 识别不到板 valid=False
        异常:
            PallasVisionError: 未启用 / mock / 非 Bridge 模式 / Bridge 通信或相机故障
        """
        if not self.cfg.enabled:
            raise PallasVisionError("PALLASVision 未启用, 无法示教零点")
        if self.cfg.mock:
            raise PallasVisionError("PALLASVision mock 模式, 无法真机示教零点")
        if not self.cfg.bridge_enabled:
            raise PallasVisionError("示教零点仅支持 Bridge 模式 (bridge_enabled=true)")
        async with self._lock:
            return await self._run_with_light(self._measure_pose_via_bridge)

    async def _capture_result_with_light(self) -> dict[str, Any]:
        return await self._run_with_light(self._capture_result)

    async def _run_with_light(self, action: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        """开补光→settle→执行 action→finally 关灯 的通用时序 (纠偏 capture / 示教 measure_pose 共用)。

        light_control_enabled=False 时直接执行 action 不控灯。关灯失败视为需人工确认的严重
        事件: log.critical 并抛 PallasVisionError (不吞), 保证补光不会被遗留点亮。
        """
        if not self.cfg.light_control_enabled:
            return await action()
        if self._light_setter is None:
            raise PallasVisionError("PALLASVision 光源控制已启用但未接入机器人 DO setter")

        await self._set_light(True)
        await self._settle_after_light()
        try:
            return await action()
        finally:
            try:
                await self._set_light(False)
            except Exception as exc:
                log.critical(
                    "PALLASVision 纠偏后关闭 DO%s 光源失败，需人工确认光源状态",
                    self.cfg.light_do_channel,
                    exc_info=True,
                )
                raise PallasVisionError(
                    f"PALLASVision 纠偏后关闭 DO{self.cfg.light_do_channel} 光源失败: {exc}"
                ) from exc

    async def _capture_result(self) -> dict[str, Any]:
        if self.cfg.bridge_enabled:
            return await self._capture_bridge_result()
        payload = await self._capture_payload()
        result = parse_plate_offset_payload(
            payload,
            encoding=self.cfg.encoding,
            err_fail_code=self.cfg.err_fail_code,
            max_abs_xy_mm=self.cfg.max_abs_xy_mm,
            max_abs_rz_deg=self.cfg.max_abs_rz_deg,
        )
        result["source"] = "pallas_vision"
        return result

    async def _capture_payload_with_light(self) -> bytes:
        if not self.cfg.light_control_enabled:
            return await self._capture_payload()
        if self._light_setter is None:
            raise PallasVisionError("PALLASVision 光源控制已启用但未接入机器人 DO setter")

        await self._set_light(True)
        await self._settle_after_light()
        try:
            return await self._capture_payload()
        finally:
            try:
                await self._set_light(False)
            except Exception as exc:
                log.critical(
                    "PALLASVision 纠偏后关闭 DO%s 光源失败，需人工确认光源状态",
                    self.cfg.light_do_channel,
                    exc_info=True,
                )
                raise PallasVisionError(
                    f"PALLASVision 纠偏后关闭 DO{self.cfg.light_do_channel} 光源失败: {exc}"
                ) from exc

    async def _capture_payload(self) -> bytes:
        if self.cfg.result_mode == "callback":
            return await self._capture_callback()
        if self.cfg.result_mode == "reply":
            return await self._capture_reply()
        raise PallasVisionError(f"未知 PALLAS result_mode: {self.cfg.result_mode}")

    async def _set_light(self, enabled: bool) -> None:
        assert self._light_setter is not None
        await self._light_setter(bool(enabled))

    async def _settle_after_light(self) -> None:
        """开补光后、触发拍照前的稳定等待。

        PALLAS 触发路径本身无内建 settle (开灯即触发)，这里补一段等待让机械臂到位后的
        残振衰减、补光到稳态再拍，提升 dx/dy/Δθ 读数稳定性。时长取 cfg.light_settle_ms。
        """
        settle_ms = int(self.cfg.light_settle_ms)
        if settle_ms > 0:
            await asyncio.sleep(settle_ms / 1000.0)

    async def _capture_callback(self) -> bytes:
        loop = asyncio.get_running_loop()
        received: asyncio.Future[bytes] = loop.create_future()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data = await asyncio.wait_for(reader.read(self.cfg.read_bytes), self.cfg.result_timeout)
                if not received.done():
                    received.set_result(data)
            except Exception as exc:
                if not received.done():
                    received.set_exception(exc)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, self.cfg.listen_host, self.cfg.listen_port)
        try:
            await self._send_trigger(read_reply=False)
            return await asyncio.wait_for(received, self.cfg.result_timeout)
        finally:
            server.close()
            await server.wait_closed()

    async def _capture_reply(self) -> bytes:
        return await self._send_trigger(read_reply=True)

    async def _capture_bridge_result(self) -> dict[str, Any]:
        timeout = httpx.Timeout(
            max(self.cfg.bridge_timeout, self.cfg.connect_timeout + self.cfg.result_timeout + 1.0),
            connect=self.cfg.connect_timeout,
        )
        url = f"http://{self.cfg.bridge_host}:{self.cfg.bridge_port}/capture"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, json={})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _bridge_error_detail(exc.response)
            error_cls = PallasVisionResultError if exc.response.status_code == 422 else PallasVisionError
            raise error_cls(f"PALLASBridge capture 失败: HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise PallasVisionError(f"连接 PALLASBridge {url} 失败: {exc}") from exc
        except ValueError as exc:
            raise PallasVisionError("PALLASBridge 返回非 JSON 响应") from exc

        if "raw" in data:
            result = parse_plate_offset_payload(
                data["raw"],
                encoding=self.cfg.encoding,
                err_fail_code=self.cfg.err_fail_code,
                max_abs_xy_mm=self.cfg.max_abs_xy_mm,
                max_abs_rz_deg=self.cfg.max_abs_rz_deg,
            )
            result["source"] = data.get("source") or "pallas_bridge"
            return result

        try:
            result = {
                "dx_mm": round(float(data["dx_mm"]), 3),
                "dy_mm": round(float(data["dy_mm"]), 3),
                "drz_deg": round(float(data.get("drz_deg", 0.0)), 3),
                "err": int(float(data.get("err", 0))),
                "valid": bool(data["valid"]),
                "raw": str(data.get("raw", "")),
                "source": data.get("source") or "pallas_bridge",
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PallasVisionError(f"PALLASBridge 返回字段不完整: {data!r}") from exc
        _validate_offset_range(
            result,
            max_abs_xy_mm=self.cfg.max_abs_xy_mm,
            max_abs_rz_deg=self.cfg.max_abs_rz_deg,
        )
        return result

    async def _measure_pose_via_bridge(self) -> dict[str, Any]:
        """POST Bridge /measure_pose 取板原始位姿 (示教用)。超时同 capture (含相机拍照耗时)。"""
        timeout = httpx.Timeout(
            max(self.cfg.bridge_timeout, self.cfg.connect_timeout + self.cfg.result_timeout + 1.0),
            connect=self.cfg.connect_timeout,
        )
        url = f"http://{self.cfg.bridge_host}:{self.cfg.bridge_port}/measure_pose"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, json={})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _bridge_error_detail(exc.response)
            raise PallasVisionError(
                f"PALLASBridge measure_pose 失败: HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise PallasVisionError(f"连接 PALLASBridge {url} 失败: {exc}") from exc
        except ValueError as exc:
            raise PallasVisionError("PALLASBridge measure_pose 返回非 JSON 响应") from exc
        try:
            return {
                "u": float(data["u"]),
                "v": float(data["v"]),
                "theta": float(data["theta"]),
                "valid": bool(data["valid"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PallasVisionError(f"PALLASBridge measure_pose 返回字段不完整: {data!r}") from exc

    async def bridge_status(self) -> dict[str, Any]:
        if not self.cfg.bridge_enabled:
            return {"bridge_enabled": False, "config": self.snapshot()}
        return await self._bridge_request("GET", "/status")

    async def bridge_reconnect(self) -> dict[str, Any]:
        if not self.cfg.bridge_enabled:
            return {"bridge_enabled": False, "config": self.snapshot()}
        return await self._bridge_request("POST", "/reconnect")

    async def bridge_reload(self) -> dict[str, Any]:
        """令 Bridge 清本地视觉配置缓存, 使新写的零点 (reference) 下次取图即生效 (热更)。"""
        if not self.cfg.bridge_enabled:
            return {"bridge_enabled": False}
        return await self._bridge_request("POST", "/reload")

    async def _bridge_request(self, method: str, path: str) -> dict[str, Any]:
        url = f"http://{self.cfg.bridge_host}:{self.cfg.bridge_port}{path}"
        timeout = httpx.Timeout(self.cfg.bridge_timeout, connect=self.cfg.connect_timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(method, url)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _bridge_error_detail(exc.response)
            raise PallasVisionError(f"PALLASBridge 请求失败: HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise PallasVisionError(f"连接 PALLASBridge {url} 失败: {exc}") from exc
        except ValueError as exc:
            raise PallasVisionError("PALLASBridge 返回非 JSON 响应") from exc
        return data

    async def _send_trigger(self, *, read_reply: bool) -> bytes:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.cfg.host, self.cfg.port),
                self.cfg.connect_timeout,
            )
        except Exception as exc:
            raise PallasVisionError(f"连接 PALLASVision {self.cfg.host}:{self.cfg.port} 失败: {exc}") from exc
        try:
            writer.write(_payload(self.cfg))
            await writer.drain()
            if not read_reply:
                return b""
            return await asyncio.wait_for(reader.read(self.cfg.read_bytes), self.cfg.result_timeout)
        finally:
            writer.close()
            await writer.wait_closed()

    def snapshot(self) -> dict[str, Any]:
        return asdict(self.cfg)


def parse_plate_offset_payload(payload: bytes | str, *, encoding: str = "utf-8", err_fail_code: int = 111,
                               max_abs_xy_mm: float = _MAX_ABS_XY_MM,
                               max_abs_rz_deg: float = _MAX_ABS_RZ_DEG) -> dict[str, Any]:
    text = payload.decode(encoding, errors="replace") if isinstance(payload, bytes) else str(payload)
    text = text.replace("\x00", "").strip()
    if not text:
        raise PallasVisionResultError("PALLASVision 未返回纠偏数据")

    parsed = _parse_json(text)
    if parsed is None:
        parsed = _parse_key_values(text)
    if parsed is None:
        parsed = _parse_numeric_list(text)
    if parsed is None:
        # 识别失败哨兵: PALLAS 识别不到板时回传裸错误码 (如 "111"), 无分隔符、既非坐标也
        # 非键值, 三种解析器都落空。成功结果恒为逗号分隔的 3 个浮点, 故裸整数不会与合法偏移
        # 相撞。这是"识别失败"语义而非协议/硬件故障, 应回 valid=False 交流程内 human 分支
        # 人工重拍/中止, 而不是抛异常让整条运行判 FAILED。其它无法解析内容仍照旧抛错。
        if _is_fail_code_sentinel(text, err_fail_code):
            return {"dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0,
                    "err": int(err_fail_code), "valid": False, "raw": text}
        raise PallasVisionResultError(f"无法解析 PALLASVision 纠偏数据: {text!r}")

    dx = _float_pick(parsed, "dx_mm", "dx", "x", "hxtx", "varx")
    dy = _float_pick(parsed, "dy_mm", "dy", "y", "hxty", "vary")
    drz = _float_pick(parsed, "drz_deg", "dtheta", "theta", "angle", "rz", "drz", default=0.0)
    err = int(_float_pick(parsed, "err", "errnum", "error", "error_code", default=0.0))
    explicit_valid = _bool_pick(parsed, "valid", "ok", "success")
    valid = (err != int(err_fail_code)) if explicit_valid is None else bool(explicit_valid) and err != int(err_fail_code)
    result = {
        "dx_mm": round(float(dx), 3),
        "dy_mm": round(float(dy), 3),
        "drz_deg": round(float(drz), 3),
        "err": err,
        "valid": bool(valid),
        "raw": text,
    }
    _validate_offset_range(result, max_abs_xy_mm=max_abs_xy_mm, max_abs_rz_deg=max_abs_rz_deg)
    return result


def _is_fail_code_sentinel(text: str, err_fail_code: int) -> bool:
    """判断整段 payload 是否恰为失败码的数值 (如 "111"/"111.0"/" 111 ")。

    PALLAS 错误码为整数, 但现场可能以小数/带空白形式回传 (如 "111.0")。成功结果恒为 ≥2 个
    分隔数 (逗号/JSON/键值), 单个数值不可能是合法成功, 故按"数值相等"判哨兵即可:
    float("111.0")==111 判识别失败哨兵 → 交人工重拍/中止分支; 而 111.9≠111、"a,b"→ValueError
    仍照旧抛 PallasVisionResultError (不放松错误判定)。
    """
    try:
        return float(text.strip()) == float(err_fail_code)
    except (TypeError, ValueError):
        return False


def _payload(cfg: PallasVisionCfg) -> bytes:
    return cfg.trigger.encode(cfg.encoding) + _TERMINATORS[cfg.terminator]


def neutral_offset(source: str) -> dict[str, Any]:
    """零偏结果体 (纠偏关闭/mock/仿真沙盒共用的同一份形状).

    参数:
        source: 这一份零偏从哪来 —— "disabled" / "mock" / "sim_synthetic"
    返回:
        Dict, 与真实纠偏结果同键 (dx_mm/dy_mm/drz_deg/err/valid/source)

    公开而不是私有, 是因为仿真沙盒的合成纠偏要用它: 那边**必须**与本文件同形,
    否则真机与沙盒对同一条流程给出键集不同的结果, 两个世界会以不同方式失败。
    """
    return {"dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0, "err": 0, "valid": True, "source": source}


def _bridge_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return str(data)


def _parse_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return {_norm_key(k): v for k, v in data.items()}
    if isinstance(data, list):
        return _numbers_to_dict(data)
    return None


def _parse_key_values(text: str) -> dict[str, Any] | None:
    pairs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(-?\d+(?:\.\d+)?|true|false|ok|ng)", text, flags=re.I)
    if not pairs:
        return None
    return {_norm_key(k): v for k, v in pairs}


def _parse_numeric_list(text: str) -> dict[str, Any] | None:
    # PALLAS 现场格式约定为逗号分隔: dx,dy,drz[,err]。这里也接受空白/分号分隔，
    # 但拒绝 "0.2418730.9912150.012353" 这类无分隔粘连格式，避免误解析为超大偏移。
    if re.fullmatch(rf"\s*{_NUMERIC_TOKEN}(?:[\s,;]+{_NUMERIC_TOKEN})+\s*", text) is None:
        return None
    nums = [float(x) for x in re.findall(_NUMERIC_TOKEN, text)]
    if len(nums) < 2:
        return None
    return _numbers_to_dict(nums)


def _numbers_to_dict(values: list[Any]) -> dict[str, Any]:
    out = {"dx_mm": values[0], "dy_mm": values[1]}
    if len(values) >= 3:
        out["drz_deg"] = values[2]
    if len(values) >= 4:
        out["err"] = values[3]
    return out


def _norm_key(key: Any) -> str:
    return str(key).strip().lower().replace(" ", "").replace("-", "_")


def _float_pick(values: dict[str, Any], *keys: str, default: float | None = None) -> float:
    for key in keys:
        if key in values:
            try:
                return float(values[key])
            except (TypeError, ValueError) as exc:
                raise PallasVisionResultError(
                    f"PALLASVision 字段 {key!r} 不是数字: {values[key]!r}"
                ) from exc
    if default is not None:
        return default
    raise PallasVisionResultError(f"PALLASVision 结果缺少字段: {keys}")


def _bool_pick(values: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in values:
            value = values[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "ok", "success"}
            return bool(value)
    return None

def _validate_offset_range(result: dict[str, Any], *, max_abs_xy_mm: float, max_abs_rz_deg: float) -> None:
    dx = float(result["dx_mm"])
    dy = float(result["dy_mm"])
    drz = float(result["drz_deg"])
    if not all(math.isfinite(value) for value in (dx, dy, drz)):
        raise PallasVisionResultError(f"PALLASVision 纠偏结果包含非有限值: {result['raw']!r}")
    if not result["valid"]:
        return
    if abs(dx) > max_abs_xy_mm or abs(dy) > max_abs_xy_mm:
        raise PallasVisionResultError(
            f"PALLASVision 平移偏移超限: dx={dx:.3f}mm dy={dy:.3f}mm "
            f"(允许 |dx|,|dy| <= {max_abs_xy_mm:.3f}mm), raw={result['raw']!r}"
        )
    if abs(drz) > max_abs_rz_deg:
        raise PallasVisionResultError(
            f"PALLASVision 角度偏移超限: drz={drz:.3f}deg "
            f"(允许 |drz| <= {max_abs_rz_deg:.3f}deg), raw={result['raw']!r}"
        )
