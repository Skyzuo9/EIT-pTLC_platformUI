"""列式分块编解码器: 量化 → 死区 → 时间轴差分 → zstd。

一块 (chunk) 是一小段时间 (默认 10 s) 的全部状态, **自带关键帧且独立可解码** ——
拖动时间轴只需解一块即可定位, 不必从头重放。这与视频编解码的 I 帧同理, 是"秒级
seek"的前提, 也是本格式与"把 JSON 一行行追加进文件"的根本差别 (实测 70–100 倍)。

压缩率的来源不是 zstd 本身, 而是**编码前把数据变得可压**:
    量化   把 float 变成物理意义明确的整数, 抹掉无意义的尾数
    死区   抹掉编码器噪声引起的整数翻动 (静止的轴不该产生任何码流)
    差分   静止 = 全 0, 匀速 = 常数, 两者都极易压

时间基约束 (硬约束, 不是实现细节):
    帧时间戳一律存**绝对纪元秒**, 与线上 JSON 逐字一致。前端 stampMs 把 < 1e12 的
    值判定为"秒"并乘 1000, 存成 0 基相对时间会被误判并乘出天文数字, 而采样器会永远
    钳在第一帧。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import msgpack
import numpy as np
import zstandard as zstd

from eit_ptlc.runtime.recording.channels import ChannelSpec, spec_for_value

CHUNK_MAGIC = b"PTCDVR01"
CHUNK_VERSION = 1
_ZSTD_LEVEL = 10

# 三态编码: confirmed 的 None 是"两个到位信号都不成立"这一**真实状态**,
# 不是缺数据。压成 False 会让回放把运动途中错画成已到位。
_TRI_TO_CODE = {False: 0, True: 1, None: 2}
_CODE_TO_TRI = (False, True, None)


def _pack_bits(flags: list[bool]) -> bytes:
    return np.packbits(np.asarray(flags, dtype=bool)).tobytes()


def _unpack_bits(blob: bytes, count: int) -> np.ndarray:
    return np.unpackbits(np.frombuffer(blob, dtype=np.uint8))[:count].astype(bool)


def _delta_encode(codes: np.ndarray) -> bytes:
    if codes.size == 0:
        return b""
    codes = codes.astype(np.int64, copy=False)
    out = np.empty(codes.size, dtype=np.int64)
    out[0] = codes[0]
    np.subtract(codes[1:], codes[:-1], out=out[1:])
    return np.ascontiguousarray(out.astype(np.int32)).tobytes()


def _delta_decode(blob: bytes) -> np.ndarray:
    if not blob:
        return np.zeros(0, dtype=np.int64)
    return np.cumsum(np.frombuffer(blob, dtype=np.int32).astype(np.int64))


def _apply_deadband(codes: np.ndarray, deadband: int) -> np.ndarray:
    """滞回量化: 变化小于 deadband 步则保持上一个已发出的值。

    本质是顺序扫描, 无法向量化; 但一块只有几百帧 × 几十通道, 且绝大多数通道整块
    取值恒定 —— 先做一次 O(n) 的等值判定即可短路掉绝大部分工作。
    """
    if deadband <= 0 or codes.size < 2:
        return codes
    if bool((codes == codes[0]).all()):
        return codes
    out = codes.copy()
    last = int(out[0])
    for i in range(1, out.size):
        value = int(codes[i])
        if abs(value - last) < deadband:
            out[i] = last
        else:
            out[i] = value
            last = value
    return out


@dataclass
class _Column:
    """一个通道在本块内的取值序列 (按帧对齐, 缺帧记 None)。"""

    spec: ChannelSpec
    values: list = field(default_factory=list)

    def pad_to(self, n: int) -> None:
        if len(self.values) < n:
            self.values.extend([_MISSING] * (n - len(self.values)))


class _Missing:
    """缺帧哨兵。不能用 None —— None 是 tri 通道的合法取值。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        return "<missing>"


_MISSING = _Missing()


@dataclass
class Chunk:
    """解码后的块。streams[name] = {"ts": [...], "channels": {id: [...]}}。"""

    t0: float
    t1: float
    keyframe: dict
    streams: dict[str, dict]
    events: list[dict]

    def frame_count(self, stream: str) -> int:
        data = self.streams.get(stream)
        return len(data["ts"]) if data else 0


class ChunkBuilder:
    """按流累积帧, 收尾时编码成一块。

    用法:
        b = ChunkBuilder(t0, keyframe={...})
        b.add_frame("axis_pose", ts, {"axis_1z.position": 12.3, ...})
        b.add_event({"type": "vm_node_enter", ...})
        blob = b.encode()
    """

    def __init__(self, t0: float, keyframe: dict | None = None) -> None:
        self.t0 = float(t0)
        self.t1 = float(t0)
        self.keyframe = dict(keyframe or {})
        self._ts: dict[str, list[float]] = {}
        self._cols: dict[str, dict[str, _Column]] = {}
        self.events: list[dict] = []

    # -- 累积 ---------------------------------------------------------

    def add_frame(self, stream: str, ts: float, values: dict) -> None:
        ts = float(ts)
        self.t1 = max(self.t1, ts)
        stamps = self._ts.setdefault(stream, [])
        columns = self._cols.setdefault(stream, {})
        stamps.append(ts)
        n = len(stamps)
        for key, value in values.items():
            column = columns.get(key)
            if column is None:
                column = _Column(spec=spec_for_value(stream, _field_of(key), value))
                # 本通道在本块中途才首次出现: 之前的帧补缺帧标记, 保持按帧对齐
                column.values = [_MISSING] * (n - 1)
                columns[key] = column
            column.pad_to(n - 1)
            column.values.append(value)
        for key, column in columns.items():
            column.pad_to(n)

    def add_event(self, event: dict) -> None:
        """低频/不可丢事件原样入块 (telemetry / material_state / 运行事件 / scrape 等)。"""
        self.events.append(event)
        ts = event.get("ts")
        if isinstance(ts, (int, float)):
            self.t1 = max(self.t1, float(ts))

    def is_empty(self) -> bool:
        return not self.events and not any(self._ts.values())

    def columns(self) -> dict[str, dict[str, list]]:
        """按 {流: {通道: [值]}} 交出累积到的原值。

        与 decode_chunk 出来的 chunk.streams[流]["channels"] 是同一形状, 于是活动度
        判定在录制侧与补算侧能共用同一个实现 —— 两处各写一遍必然会飘。
        """
        return {stream: {key: column.values for key, column in columns.items()}
                for stream, columns in self._cols.items()}

    # -- 编码 ---------------------------------------------------------

    def encode(self) -> bytes:
        streams: dict[str, dict] = {}
        for stream, stamps in self._ts.items():
            if not stamps:
                continue
            base = stamps[0]
            # 毫秒整数化后差分。int32 可表示 ±24 天的间隔, 远超任何块跨度。
            ms = np.round((np.asarray(stamps, dtype=np.float64) - base) * 1000.0)
            channels: dict[str, dict] = {}
            for key, column in self._cols[stream].items():
                encoded = _encode_column(column)
                if encoded is not None:
                    channels[key] = encoded
            streams[stream] = {
                "tb": base,
                "n": len(stamps),
                "ts": _delta_encode(ms.astype(np.int64)),
                "ch": channels,
            }

        doc = {
            "v": CHUNK_VERSION,
            "t0": self.t0,
            "t1": self.t1,
            "kf": self.keyframe,
            "ev": self.events,
            "st": streams,
        }
        raw = msgpack.packb(doc, use_bin_type=True, datetime=False)
        return CHUNK_MAGIC + zstd.ZstdCompressor(level=_ZSTD_LEVEL).compress(raw)


def _field_of(channel_id: str) -> str:
    """通道 id 形如 "axis_1z.position" / "rob_grip_vial.confirmed" -> 取字段名。"""
    return channel_id.rsplit(".", 1)[-1] if "." in channel_id else channel_id


def _encode_column(column: _Column) -> dict | None:
    values = column.values
    if not values:
        return None
    spec = column.spec
    present = [v is not _MISSING for v in values]
    if not any(present):
        return None

    codes = np.zeros(len(values), dtype=np.int64)
    enum_table: list | None = None
    if spec.kind == "enum":
        enum_table = []
        index: dict[Any, int] = {}
        for i, value in enumerate(values):
            if value is _MISSING:
                continue
            key = value
            slot = index.get(key)
            if slot is None:
                slot = len(enum_table)
                index[key] = slot
                enum_table.append(value)
            codes[i] = slot
    elif spec.kind == "tri":
        for i, value in enumerate(values):
            if value is _MISSING:
                continue
            codes[i] = _TRI_TO_CODE.get(value, 2)
    elif spec.kind == "bool":
        for i, value in enumerate(values):
            if value is _MISSING:
                continue
            codes[i] = 1 if value else 0
    else:
        quantum = spec.quantum
        for i, value in enumerate(values):
            if value is _MISSING:
                continue
            try:
                codes[i] = int(round(float(value) / quantum))
            except (TypeError, ValueError):
                codes[i] = 0

    # 缺帧沿用上一个已知码, 让差分保持 0 —— 缺帧本身由 present 位图如实记录,
    # 这里的填充只影响码流大小, 不影响解码出的语义。
    if not all(present):
        last = 0
        for i, ok in enumerate(present):
            if ok:
                last = int(codes[i])
            else:
                codes[i] = last

    if spec.kind == "num":
        codes = _apply_deadband(codes, spec.deadband)

    out: dict = {"k": spec.kind, "d": _delta_encode(codes)}
    if spec.kind == "num":
        out["q"] = spec.quantum
    if enum_table is not None:
        out["e"] = enum_table
    if not all(present):
        out["p"] = _pack_bits(present)
    return out


def encode_chunk(builder: ChunkBuilder) -> bytes:
    return builder.encode()


def decode_chunk(blob: bytes) -> Chunk:
    if not blob.startswith(CHUNK_MAGIC):
        raise ValueError("不是 PTLC 录制块 (magic 不匹配)")
    raw = zstd.ZstdDecompressor().decompress(blob[len(CHUNK_MAGIC):])
    doc = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    version = doc.get("v")
    if version != CHUNK_VERSION:
        raise ValueError(f"块版本不支持: {version} (本程序支持 {CHUNK_VERSION})")

    streams: dict[str, dict] = {}
    for stream, data in (doc.get("st") or {}).items():
        n = int(data["n"])
        base = float(data["tb"])
        ms = _delta_decode(data["ts"])
        stamps = (base + ms.astype(np.float64) / 1000.0).tolist()
        channels: dict[str, list] = {}
        for key, enc in (data.get("ch") or {}).items():
            channels[key] = _decode_column(enc, n)
        streams[stream] = {"ts": stamps, "channels": channels}

    return Chunk(
        t0=float(doc["t0"]),
        t1=float(doc["t1"]),
        keyframe=doc.get("kf") or {},
        streams=streams,
        events=list(doc.get("ev") or []),
    )


def _decode_column(enc: dict, n: int) -> list:
    codes = _delta_decode(enc["d"])
    kind = enc["k"]
    present_blob = enc.get("p")
    present = _unpack_bits(present_blob, n) if present_blob else None

    out: list = []
    for i in range(n):
        if present is not None and not present[i]:
            out.append(_MISSING)
            continue
        code = int(codes[i]) if i < codes.size else 0
        if kind == "enum":
            table = enc.get("e") or []
            out.append(table[code] if 0 <= code < len(table) else None)
        elif kind == "tri":
            out.append(_CODE_TO_TRI[code] if 0 <= code < 3 else None)
        elif kind == "bool":
            out.append(bool(code))
        else:
            out.append(code * float(enc["q"]))
    return out


def is_missing(value) -> bool:
    """该帧此通道无数据 (区别于 tri 通道取值为 None)。"""
    return value is _MISSING


def iter_frames(chunk: Chunk, stream: str) -> Iterable[tuple[float, dict]]:
    """按帧还原成 (ts, {通道: 值}); 缺帧的通道直接不出现在该帧的字典里。"""
    data = chunk.streams.get(stream)
    if not data:
        return
    stamps = data["ts"]
    channels = data["channels"]
    for i, ts in enumerate(stamps):
        row = {}
        for key, values in channels.items():
            value = values[i]
            if value is not _MISSING:
                row[key] = value
        yield ts, row
