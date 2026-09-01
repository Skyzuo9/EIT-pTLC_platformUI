"""上位机泵指令翻译器包
======================
功能:
    从 legacy UI-Upper/scripts 移植的 SY-03B 注射泵 DT 协议指令翻译器, 供 PLC L2
    验收工具把语义参数 (体积/比例/次数) 转换为泵转发指令串/数组, 写入 PLC 预留变量.
    各翻译器为纯函数, 逻辑与 legacy 一致, 仅改包内导入路径.
模块:
    sample_translator    - 上样点样泵 v1 基础指令构建 (T-04 阀头)
    sample_translator_v2 - 上样点样 v2 空气驱动策略 4 数组构建
    collect_translator   - 收集泵单溶剂吸打复合指令 (T-04, 地址 3)
    develop_translator   - 展开 4 溶剂通道配比泵转发指令 (T-06)
    profiles             - 动作 -> 语义参数表 + builder (产出 PLC 通道字典)
"""
