"""设备状态录制与回放 (3D DVR)。

三维场景是状态向量的纯函数, 因此"像监控一样回放设备"不需要存视频, 只需按高频存下
状态向量, 回放时喂回同一套渲染代码。实测编码后整月约 2–3 GB, 而同时长一路 1080p
监控视频约 1.3 TB。

模块分工:
    channels  精度策略 (每个通道的物理量化步长与死区) 与期望通道清单
    codec     列式分块编解码: 量化 → 死区 → 时间轴差分 → zstd, 每块自带关键帧
"""

from eit_ptlc.runtime.recording.channels import ChannelSpec, spec_for
from eit_ptlc.runtime.recording.codec import (
    CHUNK_MAGIC,
    Chunk,
    ChunkBuilder,
    decode_chunk,
    encode_chunk,
)

__all__ = [
    "ChannelSpec",
    "spec_for",
    "CHUNK_MAGIC",
    "Chunk",
    "ChunkBuilder",
    "encode_chunk",
    "decode_chunk",
]
