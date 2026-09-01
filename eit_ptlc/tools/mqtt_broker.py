"""内置极简 MQTT 3.1.1 Broker (纯标准库 asyncio, 零外部依赖)
================================================================
功能:
    为液位监测提供进程内自包含的 MQTT 消息中转. 香橙派 (paho) 发布液位数据/状态/LWT,
    上位机 (paho) 订阅并下发命令, 全部经本 broker 转发. 只实现液位实际用到的 MQTT 3.1.1
    子集 (CONNECT/PUBLISH/SUBSCRIBE/UNSUBSCRIBE/PINGREQ/DISCONNECT + LWT + retain +
    通配符 + QoS 0/1), 不追求完整 MQTT 5.0 一致性.

为何:
    原液位 broker 跑在外部电脑上, 易随该机下线而失联. 改为上位机自带 broker: 零外部软件/
    依赖, 随 pTLC launcher 一起启动, broker 生命周期跟随上位机, 不再依赖任何第三方机器.

运行:
    python -m eit_ptlc.tools.mqtt_broker --host 0.0.0.0 --port 1883

支持的报文与特性:
    - CONNECT/CONNACK: 解析 client_id/keepalive/clean session/LWT, 一律接受 (匿名, 忽略账密)
    - PUBLISH/PUBACK: QoS 0 直转, QoS 1 回 PUBACK 后转发 (发往订阅者按其订阅 QoS 降级, 不重传)
    - SUBSCRIBE/SUBACK: 支持通配符 + (单层) 与 # (多层/末层), 订阅即补发匹配的 retained 消息
    - UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP
    - DISCONNECT: 优雅断开, 丢弃 LWT (不发遗嘱)
    - LWT (遗嘱): 连接非优雅断开 (keepalive 超时/TCP 断) 时 broker 代发 will 消息 (在线判定命脉)
    - retain: 保留每个 topic 最后一条 retained 消息, 新订阅者接入即补发, 空 payload 清除保留

限制:
    - 不支持 QoS 2 (液位未用), 收到 QoS 2 PUBLISH 按 QoS 0 尽力投递, 不回 PUBREC
    - 不持久化 session (clean session 语义), 不做账密鉴权 (局域网内匿名)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import struct

log = logging.getLogger("mqtt_broker")

# MQTT 3.1.1 控制报文类型 (固定报头高 4 位)
CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
PUBREC = 5
PUBREL = 6
PUBCOMP = 7
SUBSCRIBE = 8
SUBACK = 9
UNSUBSCRIBE = 10
UNSUBACK = 11
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14


class Session:
    """单个客户端连接会话 (订阅表 + 遗嘱 + 写通道)."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.client_id = ""
        self.keepalive = 0
        self.subscriptions: dict[str, int] = {}   # topic filter -> 订阅 QoS
        self.will: tuple[str, bytes, int, bool] | None = None  # (topic, payload, qos, retain)
        self.peer = writer.get_extra_info("peername")


def _encode_remaining_length(length: int) -> bytes:
    """功能: 把剩余长度编码为 MQTT 变长字节 (每字节低 7 位, 高位为续标志).

    参数:
        length: 剩余长度 (非负整数)
    返回:
        bytes, 1~4 字节的变长编码
    """
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length > 0:
            byte |= 0x80
        out.append(byte)
        if length == 0:
            break
    return bytes(out)


def _topic_matches(topic_filter: str, topic: str) -> bool:
    """功能: 判断发布 topic 是否匹配订阅 filter (支持 + 单层与 # 末层通配).

    参数:
        topic_filter: 订阅过滤器 (可含 + / #)
        topic: 实际发布主题 (不含通配)
    返回:
        bool, 匹配为 True
    """
    filter_parts = topic_filter.split("/")
    topic_parts = topic.split("/")
    for index in range(len(filter_parts)):
        part = filter_parts[index]
        if part == "#":
            # # 为末层多层通配, 匹配剩余全部层级 (含零层, 故 a/# 也匹配 a)
            return True
        if index >= len(topic_parts):
            return False
        if part == "+":
            continue
        if part != topic_parts[index]:
            return False
    return len(filter_parts) == len(topic_parts)


class Broker:
    """极简 MQTT broker: 管理会话/订阅/retained, 转发发布并代发遗嘱."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._sessions: set[Session] = set()
        self._retained: dict[str, tuple[bytes, int]] = {}   # topic -> (payload, qos)
        self._packet_id = 0

    # ------------------------------------------------------------------
    # 报文构造
    # ------------------------------------------------------------------
    def _next_packet_id(self) -> int:
        """功能: 生成 1~65535 循环的报文标识符 (发往订阅者的 QoS1 PUBLISH 用)."""
        self._packet_id = (self._packet_id % 65535) + 1
        return self._packet_id

    @staticmethod
    def _make_publish(topic: str, payload: bytes, qos: int, retain: bool, packet_id: int | None) -> bytes:
        """功能: 构造 PUBLISH 报文 (broker 转发给订阅者用)."""
        flags = (qos << 1) | (1 if retain else 0)
        topic_bytes = topic.encode("utf-8")
        variable = struct.pack(">H", len(topic_bytes)) + topic_bytes
        if qos > 0 and packet_id is not None:
            variable += struct.pack(">H", packet_id)
        body = variable + payload
        header = bytes([(PUBLISH << 4) | flags]) + _encode_remaining_length(len(body))
        return header + body

    async def _send(self, session: Session, data: bytes) -> None:
        """功能: 向会话写通道发送字节并 drain, 失败静默 (由读循环感知断开)."""
        try:
            session.writer.write(data)
            await session.writer.drain()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 连接处理
    # ------------------------------------------------------------------
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """功能: 处理单个 TCP 连接的完整 MQTT 生命周期 (CONNECT -> 循环 -> 断开代发遗嘱)."""
        session = Session(writer)
        graceful = False
        try:
            # 首包必须是 CONNECT (10s 内)
            first = await self._read_packet(reader, timeout=10.0)
            if first is None or first[0] != CONNECT:
                writer.close()
                return
            self._parse_connect(session, first[2])
            # 同 client_id 的旧会话先踢掉 (重连不残留)
            for other in list(self._sessions):
                if other.client_id == session.client_id:
                    self._sessions.discard(other)
                    try:
                        other.writer.close()
                    except Exception:
                        pass
            self._sessions.add(session)
            await self._send(session, b"\x20\x02\x00\x00")   # CONNACK: 接受, 无 session present
            log.info("客户端接入: id=%s peer=%s keepalive=%s will=%s",
                     session.client_id, session.peer, session.keepalive, session.will is not None)
            # keepalive*1.5 无包即判死 (触发遗嘱); keepalive=0 则不超时
            read_timeout = session.keepalive * 1.5 if session.keepalive > 0 else None
            while True:
                packet = await self._read_packet(reader, timeout=read_timeout)
                if packet is None:
                    break
                if await self._dispatch(session, packet) == "close":
                    graceful = True
                    break
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            log.exception("连接处理异常: id=%s", session.client_id)
        finally:
            self._sessions.discard(session)
            # 非优雅断开 (掉线/超时) 代发遗嘱; 优雅 DISCONNECT 已丢弃遗嘱
            if graceful is False and session.will is not None:
                topic, payload, qos, retain = session.will
                log.info("代发遗嘱 (LWT): id=%s topic=%s", session.client_id, topic)
                await self._publish(topic, payload, qos, retain)
            try:
                writer.close()
            except Exception:
                pass

    async def _read_packet(self, reader: asyncio.StreamReader, timeout: float | None):
        """功能: 读取一个完整 MQTT 报文.

        参数:
            reader: 流读取器
            timeout: 等待首字节的超时秒数 (None 为不超时)
        返回:
            (报文类型, 固定报头低 4 位 flags, 可变头+载荷 bytes), 断开/超时返回 None
        """
        try:
            if timeout is not None:
                head = await asyncio.wait_for(reader.readexactly(1), timeout)
            else:
                head = await reader.readexactly(1)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None
        byte1 = head[0]
        packet_type = byte1 >> 4
        flags = byte1 & 0x0F
        remaining = await self._read_remaining_length(reader)
        data = await reader.readexactly(remaining) if remaining > 0 else b""
        return packet_type, flags, data

    @staticmethod
    async def _read_remaining_length(reader: asyncio.StreamReader) -> int:
        """功能: 读取 MQTT 变长剩余长度字段 (最多 4 字节)."""
        multiplier = 1
        value = 0
        for _ in range(4):
            byte = (await reader.readexactly(1))[0]
            value += (byte & 0x7F) * multiplier
            if (byte & 0x80) == 0:
                return value
            multiplier *= 128
        raise ValueError("剩余长度字段超过 4 字节, 报文非法")

    @staticmethod
    def _parse_connect(session: Session, data: bytes) -> None:
        """功能: 解析 CONNECT 可变头+载荷, 填充会话的 client_id/keepalive/遗嘱."""
        index = 0
        proto_len = struct.unpack_from(">H", data, index)[0]
        index += 2 + proto_len            # 跳过协议名 (MQTT/MQIsdp)
        index += 1                        # 跳过协议级别
        connect_flags = data[index]
        index += 1
        session.keepalive = struct.unpack_from(">H", data, index)[0]
        index += 2
        # 载荷: client_id
        cid_len = struct.unpack_from(">H", data, index)[0]
        index += 2
        session.client_id = data[index:index + cid_len].decode("utf-8", "ignore")
        index += cid_len
        # 遗嘱 (will flag = bit2)
        if (connect_flags & 0x04) != 0:
            wt_len = struct.unpack_from(">H", data, index)[0]
            index += 2
            will_topic = data[index:index + wt_len].decode("utf-8", "ignore")
            index += wt_len
            wm_len = struct.unpack_from(">H", data, index)[0]
            index += 2
            will_payload = data[index:index + wm_len]
            index += wm_len
            will_qos = (connect_flags >> 3) & 0x03
            will_retain = (connect_flags & 0x20) != 0
            session.will = (will_topic, will_payload, will_qos, will_retain)
        # username/password (bit7/bit6) 一律忽略 (匿名局域网)

    # ------------------------------------------------------------------
    # 报文分发
    # ------------------------------------------------------------------
    async def _dispatch(self, session: Session, packet) -> str | None:
        """功能: 按报文类型分发处理, 返回 'close' 表示应关闭连接 (优雅断开)."""
        packet_type, flags, data = packet
        if packet_type == PUBLISH:
            await self._handle_publish(session, flags, data)
        elif packet_type == SUBSCRIBE:
            await self._handle_subscribe(session, data)
        elif packet_type == UNSUBSCRIBE:
            await self._handle_unsubscribe(session, data)
        elif packet_type == PINGREQ:
            await self._send(session, b"\xd0\x00")     # PINGRESP
        elif packet_type == DISCONNECT:
            session.will = None                        # 优雅断开丢弃遗嘱
            return "close"
        elif packet_type == PUBACK:
            pass                                       # 订阅者对 QoS1 的确认, 不重传故忽略
        # 其余 (PUBREC/PUBREL/PUBCOMP 等 QoS2) 液位未用, 忽略
        return None

    async def _handle_publish(self, session: Session, flags: int, data: bytes) -> None:
        """功能: 解析并转发 PUBLISH, QoS1 先回 PUBACK; 维护 retained."""
        retain = (flags & 0x01) != 0
        qos = (flags >> 1) & 0x03
        index = 0
        topic_len = struct.unpack_from(">H", data, index)[0]
        index += 2
        topic = data[index:index + topic_len].decode("utf-8", "ignore")
        index += topic_len
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack_from(">H", data, index)[0]
            index += 2
        payload = data[index:]
        # QoS1: 先向发布者确认 (QoS2 不支持, 不回 PUBREC)
        if qos == 1 and packet_id is not None:
            await self._send(session, b"\x40\x02" + struct.pack(">H", packet_id))
        await self._publish(topic, payload, qos, retain)

    async def _publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        """功能: 转发一条消息给所有匹配订阅者, 并按 retain 维护保留消息.

        参数:
            topic: 发布主题; payload: 载荷; qos: 发布 QoS; retain: 是否保留
        """
        if retain is True:
            if len(payload) > 0:
                self._retained[topic] = (payload, qos)
            else:
                self._retained.pop(topic, None)        # 空载荷 = 清除该主题保留
        for target in list(self._sessions):
            matched_qos = None
            for topic_filter, sub_qos in target.subscriptions.items():
                if _topic_matches(topic_filter, topic):
                    matched_qos = sub_qos
                    break                              # 每会话至多投递一次
            if matched_qos is None:
                continue
            send_qos = min(qos, matched_qos)
            packet_id = self._next_packet_id() if send_qos > 0 else None
            # 转发时 retain 位置 0 (retain=1 仅用于新订阅补发保留消息)
            await self._send(target, self._make_publish(topic, payload, send_qos, False, packet_id))

    async def _handle_subscribe(self, session: Session, data: bytes) -> None:
        """功能: 解析 SUBSCRIBE, 登记订阅, 回 SUBACK, 并补发匹配的 retained 消息."""
        index = 0
        packet_id = struct.unpack_from(">H", data, index)[0]
        index += 2
        filters: list[tuple[str, int]] = []
        while index < len(data):
            flen = struct.unpack_from(">H", data, index)[0]
            index += 2
            topic_filter = data[index:index + flen].decode("utf-8", "ignore")
            index += flen
            req_qos = data[index]
            index += 1
            filters.append((topic_filter, req_qos))
        granted = bytearray()
        for topic_filter, req_qos in filters:
            grant = min(req_qos, 1)                     # 最高支持 QoS1
            session.subscriptions[topic_filter] = grant
            granted.append(grant)
        suback_body = struct.pack(">H", packet_id) + bytes(granted)
        await self._send(session, bytes([SUBACK << 4]) + _encode_remaining_length(len(suback_body)) + suback_body)
        # 补发匹配的 retained 消息 (retain 位置 1)
        for topic, (payload, rqos) in list(self._retained.items()):
            for topic_filter, req_qos in filters:
                if _topic_matches(topic_filter, topic):
                    send_qos = min(rqos, req_qos, 1)
                    packet_id2 = self._next_packet_id() if send_qos > 0 else None
                    await self._send(session, self._make_publish(topic, payload, send_qos, True, packet_id2))
                    break

    async def _handle_unsubscribe(self, session: Session, data: bytes) -> None:
        """功能: 解析 UNSUBSCRIBE, 移除订阅, 回 UNSUBACK."""
        index = 0
        packet_id = struct.unpack_from(">H", data, index)[0]
        index += 2
        while index < len(data):
            flen = struct.unpack_from(">H", data, index)[0]
            index += 2
            topic_filter = data[index:index + flen].decode("utf-8", "ignore")
            index += flen
            session.subscriptions.pop(topic_filter, None)
        await self._send(session, b"\xb0\x02" + struct.pack(">H", packet_id))

    # ------------------------------------------------------------------
    # 服务入口
    # ------------------------------------------------------------------
    async def serve(self) -> None:
        """功能: 启动 TCP 监听并常驻服务."""
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        log.info("MQTT broker 已监听 %s", addrs)
        async with server:
            await server.serve_forever()


def main() -> None:
    """功能: 命令行入口, 解析 --host/--port 并常驻运行 broker."""
    parser = argparse.ArgumentParser(description="pTLC 内置极简 MQTT broker (液位消息中转)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0, 使香橙派可连)")
    parser.add_argument("--port", type=int, default=1883, help="监听端口 (默认 1883)")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    broker = Broker(args.host, args.port)
    try:
        asyncio.run(broker.serve())
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C, broker 退出")


if __name__ == "__main__":
    main()
