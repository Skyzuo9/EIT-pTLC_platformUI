"""eit_ptlc - pTLC 全自动平台统一上位机控制包
================================================
功能:
    pTLC 设备 (机械臂 / 上样点样 / 展开 / 拍照刮板 / 收集) 的统一上位机控制.
    按 config / driver / controller / action / operation / api 单向分层组织,
    上位机经 OPC UA 统一 L2 动作通道驱动 PLC, 经 Dobot TCP 直连驱动机械臂.

分层依赖 (单向):
    config -> driver -> controller -> action -> operation -> api
    runtime 装配全部; web (Vue3) 仅经 api.

详见 plans/ptlc-5-tcp-plc-opc-linear-dragonfly.md.
"""

__version__ = "0.1.0"
