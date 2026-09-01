#!/usr/bin/env python3
"""
上位机 MQTT 测试工具
用于验证下位机的 MQTT 通信 + MJPEG 流式传输是否正常。

功能:
  1. 订阅所有上行主题, 打印收到的液位数据/参数/ack
  2. 提供命令行菜单, 向下位机发送控制指令
  3. stream_start 后打印 HTTP URL 供浏览器直接打开

用法:
  python mqtt_test_upper.py --broker 192.168.10.226
"""

import json
import time
import argparse
import paho.mqtt.client as mqtt


TOPICS_SUBSCRIBE = [
    ("water_level/data",         0),  # 全通道数据
    ("water_level/status",       0),  # 设备状态
    ("water_level/alarm",        1),  # 报警
    ("water_level/ch/#",         0),  # 各单通道
    ("water_level/param/detect", 0),  # 检测参数
    ("water_level/ack",          1),  # 命令确认
]

# 默认配置
DEFAULT_ORANGEPI_IP = "192.168.0.168"
DEFAULT_STREAM_PORT = 8080


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[上位机] 已连接 MQTT Broker")
        for topic, qos in TOPICS_SUBSCRIBE:
            client.subscribe(topic, qos)
            print(f"  订阅: {topic}")
    else:
        print(f"[上位机] 连接失败 rc={rc}")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        payload_str = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        payload_str = msg.payload.decode(errors="replace")

    print(f"\n{'='*50}")
    print(f"主题: {msg.topic}")
    print(f"数据: {payload_str}")
    print(f"{'='*50}")


def send_command(client, cmd, payload_dict):
    topic = f"water_level/cmd/{cmd}"
    payload = json.dumps(payload_dict, ensure_ascii=False)
    client.publish(topic, payload, qos=1)
    print(f"[发送] {topic} → {payload}")


def input_channel(prompt="通道号 (1-8): "):
    """输入通道号，返回整数"""
    s = input(prompt).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        print("无效通道号")
        return None


def detect_param_submenu(client):
    """检测参数 CRUD 子菜单"""
    menu = """
  ┌────────────────────────────────────┐
  │  检测参数 CRUD                     │
  ├────────────────────────────────────┤
  │  1. get_detect_param (查询)        │
  │  2. set_detect_param (设置)        │
  │  3. save_detect_param (保存到文件) │
  │  4. load_detect_param (从文件加载) │
  │  0. 返回上级                       │
  └────────────────────────────────────┘"""

    while True:
        print(menu)
        choice = input("  请选择: ").strip()

        if choice == "1":
            ch = input_channel("通道号 (1-8, 回车=all): ")
            send_command(client, "get_detect_param",
                         {"channel": ch if ch else "all"})

        elif choice == "2":
            ch = input_channel("通道号 (1-8): ")
            if ch is None:
                continue
            print("  输入参数 (key=value, 每行一个, 空行结束):")
            print("  可用: height_offset_cm, height_gain, roi_sobel_ksize,")
            print("        roi_crop_x, roi_crop_y, water_sobely_ksize,")
            print("        water_edge_threshold, water_blur_ksize")
            params = {}
            while True:
                line = input("    ").strip()
                if not line:
                    break
                if "=" not in line:
                    print("    格式: key=value")
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                try:
                    v = float(v) if "." in v or not v.lstrip("-").isdigit() else int(v)
                except ValueError:
                    pass  # 保持字符串
                params[k] = v
            if params:
                send_command(client, "set_detect_param",
                             {"channel": ch, "params": params})

        elif choice == "3":
            ch = input_channel("通道号 (1-8, 回车=all): ")
            send_command(client, "save_detect_param",
                         {"channel": ch if ch else "all"})

        elif choice == "4":
            ch = input_channel("通道号 (1-8, 回车=all): ")
            send_command(client, "load_detect_param",
                         {"channel": ch if ch else "all"})

        elif choice == "0":
            break
        else:
            print("  无效选择")

        time.sleep(0.3)


def stream_submenu(client, orange_ip, stream_port):
    """MJPEG 流控制子菜单"""
    menu = f"""
  ┌──────────────────────────────────┐
  │  MJPEG 流控制                    │
  ├──────────────────────────────────┤
  │  1. stream_start (激活通道)      │
  │  2. stream_stop (停用通道)       │
  │  3. stream_stop_all (全部停用)   │
  │                                  │
  │  MJPEG URL 格式:                 │
  │  http://{orange_ip}:{stream_port}/stream/chN       │
  │  http://{orange_ip}:{stream_port}/stream/chN?raw=1 │
  │  http://{orange_ip}:{stream_port}/stream/grid      │
  │  0. 返回上级                      │
  └──────────────────────────────────┘"""

    while True:
        print(menu)
        choice = input("  请选择: ").strip()

        if choice == "1":
            ch = input_channel("通道号 (1-8): ")
            if ch is None:
                continue
            send_command(client, "stream_start", {"channel": ch})
            print(f"  → 浏览器打开: http://{orange_ip}:{stream_port}/stream/ch{ch}")

        elif choice == "2":
            ch = input_channel("通道号 (1-8): ")
            if ch is None:
                continue
            send_command(client, "stream_stop", {"channel": ch})

        elif choice == "3":
            send_command(client, "stream_stop", {"channel": "all"})

        elif choice == "0":
            break
        else:
            print("  无效选择")

        time.sleep(0.3)


def active_channels_submenu(client):
    """通道启停控制子菜单 (set_active_channels)"""
    menu = """
  ┌────────────────────────────────────┐
  │  通道启停控制 (set_active_channels)│
  ├────────────────────────────────────┤
  │  1. 激活通道 (action: add)         │
  │  2. 停用通道 (action: remove)      │
  │  3. 全量替换 (action: set)         │
  │                                    │
  │  提示: 通道号用逗号分隔, 如 1,3,5  │
  │  当前活跃状态见 water_level/status │
  │  0. 返回上级                       │
  └────────────────────────────────────┘"""

    def _parse_channels():
        s = input("  通道号 (逗号分隔, 回车=取消): ").strip()
        if not s:
            return None
        try:
            return [int(x.strip()) for x in s.split(",") if x.strip()]
        except ValueError:
            print("  无效通道号")
            return None

    while True:
        print(menu)
        choice = input("  请选择: ").strip()

        if choice == "1":
            channels = _parse_channels()
            if channels:
                send_command(client, "set_active_channels",
                             {"action": "add", "channels": channels})

        elif choice == "2":
            channels = _parse_channels()
            if channels:
                send_command(client, "set_active_channels",
                             {"action": "remove", "channels": channels})

        elif choice == "3":
            channels = _parse_channels()
            if channels is None:
                # 允许空列表 = 停用全部通道
                confirm = input("  确认停用全部通道? (y/N): ").strip().lower()
                if confirm != "y":
                    continue
                channels = []
            stream_s = input("  stream_channels (逗号分隔, 回车=无): ").strip()
            payload = {"action": "set", "channels": channels}
            if stream_s:
                try:
                    payload["stream_channels"] = [int(x.strip()) for x in stream_s.split(",") if x.strip()]
                except ValueError:
                    print("  无效 stream_channels")
                    continue
            send_command(client, "set_active_channels", payload)

        elif choice == "0":
            break
        else:
            print("  无效选择")

        time.sleep(0.3)


def interactive_menu(client, orange_ip, stream_port):
    menu = f"""
╔══════════════════════════════════════╗
║       上位机 MQTT 控制菜单           ║
╠══════════════════════════════════════╣
║  1. 重置标定 (单通道)                ║
║  2. 重置标定 (全部)                  ║
║  3. 设置上报周期                     ║
║  4. 设置报警阈值                     ║
║  5. 检测参数 CRUD ▸                  ║
║  6. MJPEG 流控制 ▸                   ║
║  7. 查询设备状态                     ║
║  8. 重启摄像头                       ║
║  9. 通道启停控制 ▸                   ║
║  0. 退出                             ║
║                                      ║
║  Orange Pi: {orange_ip}:{stream_port}                ║
╚══════════════════════════════════════╝
"""
    while True:
        print(menu)
        choice = input("请选择: ").strip()

        if choice == "1":
            ch = input_channel("通道号 (1-8): ")
            if ch is not None:
                send_command(client, "reset", {"channel": ch})

        elif choice == "2":
            send_command(client, "reset", {"channel": "all"})

        elif choice == "3":
            sec = input("上报周期(秒, 如 1.0): ").strip()
            if sec:
                send_command(client, "set_interval", {"interval": float(sec)})

        elif choice == "4":
            lo = input("低液位报警(cm, 留空不设): ").strip()
            hi = input("高液位报警(cm, 留空不设): ").strip()
            payload = {}
            if lo:
                payload["min"] = float(lo)
            if hi:
                payload["max"] = float(hi)
            if payload:
                send_command(client, "set_threshold", payload)

        elif choice == "5":
            detect_param_submenu(client)

        elif choice == "6":
            stream_submenu(client, orange_ip, stream_port)

        elif choice == "7":
            send_command(client, "query_status", {})

        elif choice == "8":
            ch = input_channel("通道号 (1-8): ")
            if ch is not None:
                send_command(client, "restart_camera", {"channel": ch})

        elif choice == "9":
            active_channels_submenu(client)

        elif choice == "0":
            print("退出")
            break

        else:
            print("无效选择")

        if choice not in ("5", "6", "9"):
            time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser(description="上位机 MQTT 测试工具")
    parser.add_argument("--broker", type=str, required=True,
                        help="MQTT Broker IP")
    parser.add_argument("--port", type=int, default=1883,
                        help="MQTT Broker 端口 (默认 1883)")
    parser.add_argument("--orange-ip", type=str, default=DEFAULT_ORANGEPI_IP,
                        help=f"香橙派 IP (默认 {DEFAULT_ORANGEPI_IP})")
    parser.add_argument("--stream-port", type=int, default=DEFAULT_STREAM_PORT,
                        help=f"MJPEG HTTP 端口 (默认 {DEFAULT_STREAM_PORT})")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="upper_computer_test")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()
    time.sleep(1)

    try:
        interactive_menu(client, args.orange_ip, args.stream_port)
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
