"""注射泵动作 → 柱塞相位脚本 (PUMP_SYRINGE_ACTIONS 单一真源)
=============================================================
功能:
    声明每个泵动作在三维里的柱塞/阀相位脚本。gen_twin_manifest 把本表烘进
    device-manifest.json 的 pumpSyringe.actions, 三方消费同一份:
      1. 离线片段编译器  three_d/pipeline/clip_compiler.emit_pump_syringe
      2. 实时孪生台      web/src/three-d/twin/bindings/PumpSyringeModel.js
      3. 前端近似演示档  web/src/three-d/demo/flowSim.js (经 expandPumpPlan)
    绝不允许只在其中一处补规则。

归真纪律 (仿真模块阶段①, 2026-08-08 起):
    本表的**相位结构**(段序/端口/速度档名/体积参数名)不再是手抄品 —— 由
    tests/test_pump_manifest_drift_offline.py 逐动作对账 tools/pump/*translator*
    的 plan_*(结构化指令计划, PLC 实收 DT 串的同一产地)。改 translator 不改表、
    或改表不改 translator, 门禁即红。fallback 数值仍与 translator DEFAULT_*
    常量同源; rampS 是演示侧渐近时长, 不参与对账 (真实时长由 V/M 算)。

与 TANK_LIQUID_ACTIONS 看同一批动作事件, 但表达的是**另一个侧面**: develop.fill
既让缸里多 20mL, 也让泵柱塞往复 N 趟. 两张表各挡各的, 互不知道对方存在.

三处与展缸表刻意不同, 别照搬字段名:
  1. 展缸的 volumeFrom 是**连乘**(体积 × 趟数); 这里的 toFrom.add 是**求和**
     (flush 三段相加、aspirate = 气隙 + 样品). 趟数改由 repeatFrom 单独表达 ——
     它循环 phases, 不放大峰值.
  2. 必须是**相位脚本**而不是单一目标: 展缸泵一趟"吸满→打空"起点终点都是 0, 单目标
     模型下柱塞一动不动 —— 而往复运动恰是这里唯一要看的东西.
  3. fallback: 乘法有单位元 1 可以兜底, 加法没有; 缺项按 0 算会把 flush 的峰值从
     25mL 变成 0. 数值与 tools/pump/sample_translator_v2.py 的 DEFAULT_* 常量同源.

op 语义: home 归零(DT 的 Z 指令); aspirate 抽(柱塞上行, 液柱涨); dispense 排.
to/toFrom = 绝对目标 mL; by/byFrom = 相对前一相位终点的增减(符号由 op 决定).
rampS 同展缸: 是渐近趋近的名义时长, 不是真实流量 —— 泵全程无位置反馈.
"""

from __future__ import annotations

PUMP_SYRINGE_ACTIONS = {
    # -- 展开(缸号→泵由 manifest 里每台泵的 tankGroup 直接查, 不在前端重算 //4) ----
    "develop.init": {
        "pump": {"from": "tankGroup", "arg": "target_tank"},
        "phases": [{"op": "home", "to": 0.0, "rampS": 2.0}],
    },
    "develop.fill": {
        # 多溶剂时真实指令是逐通道(口2-5)分段吸到各累计位(develop_translator.
        # plan_forward_instructions), 相位表无法按配比动态分段 —— 门禁以单溶剂严判、
        # 多溶剂只对账终点体积(具名豁免)。
        "pump": {"from": "tankGroup", "arg": "target_tank"},
        "repeatFrom": "up_liquid_repeat_count",
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["solvent_volume_ml"]}, "port": 2, "rampS": 4.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": "output", "rampS": 4.0, "speed": "disp_speed"},
        ],
    },
    "develop.rinse_fill": {
        "pump": {"from": "tankGroup", "arg": "target_tank"},
        "repeatFrom": "rinse_repeat_count",
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["solvent_volume_ml"]}, "port": 2, "rampS": 3.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": "output", "rampS": 3.0, "speed": "disp_speed"},
        ],
    },
    "develop.clean_line": {    # 只洗管路, 缸内液体不动(故展缸表没有它), 但泵在跑
        "pump": {"from": "tankGroup", "arg": "target_tank"},
        "repeatFrom": "rinse_repeat_count",
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["solvent_volume_ml"]}, "port": 2, "rampS": 3.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": "output", "rampS": 3.0, "speed": "disp_speed"},
        ],
    },
    # -- 收集(CAD 未建模, rigged=false; 数据仍走这套表, 面板可见) -----------------
    "collect.init": {
        "pump": {"from": "fixed", "id": "COL"},
        "phases": [{"op": "home", "to": 0.0, "rampS": 2.0}],
    },
    "collect.collect": {
        # 端口已由 collect_translator.plan_collect 证实(金测试冻结的真实指令串
        # /3V..I2A..M..V..I1A0M..R): 吸=2 溶剂口, 打=1 输出口 —— 不再是猜测值,
        # 漂移门禁锁定。前端对无阀几何的泵会自动忽略口号(PumpSyringeModel._portTurns)。
        "pump": {"from": "fixed", "id": "COL"},
        "repeatFrom": "liquid_repeat_count",
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["solvent_volume_ml"]}, "port": 2, "rampS": 3.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": 1, "rampS": 3.0, "speed": "disp_speed"},
        ],
    },
    # -- 上样 ------------------------------------------------------------------
    "sampling.init": {         # 无入参: 只归零
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [{"op": "home", "to": 0.0, "rampS": 2.0}],
    },
    "sampling.clean": {        # 每轮内壁 + 外壁各一次吸排
        "pump": {"from": "fixed", "id": "SMP"},
        "repeatFrom": "cleaning_count",
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["wash_volume_ml"]}, "port": 1, "rampS": 4.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": 3, "rampS": 4.0, "speed": "disp_speed"},
            {"op": "aspirate", "toFrom": {"add": ["wash_volume_ml"]}, "port": 1, "rampS": 4.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": 2, "rampS": 4.0, "speed": "disp_speed"},
        ],
    },
    "sampling.flush": {        # 一次吸满三段之和, 再三级打出; 终态必回 0(translator 不变量)
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [
            {"op": "aspirate",
             "toFrom": {"add": ["flush_volume_ml", "outer_wash_volume_ml", "spot_head_volume_ml"],
                        "fallback": [17.0, 5.0, 3.0]}, "port": 1, "rampS": 8.0, "speed": "asp_speed"},
            {"op": "dispense",
             "toFrom": {"add": ["outer_wash_volume_ml", "spot_head_volume_ml"],
                        "fallback": [5.0, 3.0]}, "port": 3, "rampS": 6.0, "speed": "flush_disp_speed"},
            {"op": "dispense",
             "toFrom": {"add": ["spot_head_volume_ml"], "fallback": [3.0]}, "port": 2, "rampS": 4.0, "speed": "flush_disp_speed"},
            {"op": "dispense", "to": 0.0, "port": 3, "rampS": 3.0, "speed": "spot_head_disp_speed"},
        ],
    },
    "sampling.prep": {         # 吸一段空气缓冲, 停在这个位置不回零
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [{"op": "aspirate", "toFrom": {"add": ["air_buffer_ml"], "fallback": [0.2]},
                    "port": 3, "rampS": 2.0, "speed": "asp_speed"}],
    },
    "sampling.aspirate": {     # 先绝对到气隙位(可缺省), 再相对叠加样品量
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [
            {"op": "aspirate", "toFrom": {"add": ["air_gap_ml"]}, "skipIfMissing": True,
             "port": 3, "rampS": 2.0, "speed": "asp_speed"},
            {"op": "aspirate", "byFrom": {"add": ["sample_volume_ml"]}, "port": 3, "rampS": 4.0, "speed": "asp_speed"},
        ],
    },
    "sampling.rinse_mix": {    # 排空 → 吸润洗液 → 排空 → 补气隙, 其后反复吹打
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [
            {"op": "dispense", "to": 0.0, "rampS": 3.0, "speed": "disp_speed"},
            {"op": "aspirate", "toFrom": {"add": ["rinse_volume_ml"]}, "rampS": 3.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "rampS": 3.0, "speed": "disp_speed"},
            {"op": "aspirate", "toFrom": {"add": ["air_gap_ml"], "fallback": [0.2]},
             "rampS": 1.5, "speed": "asp_speed"},
        ],
        "loop": {
            "repeatFrom": "mix_count",
            "phases": [
                {"op": "aspirate", "byFrom": {"add": ["mix_volume_ml"]}, "rampS": 2.0, "speed": "asp_speed"},
                {"op": "dispense", "byFrom": {"add": ["mix_volume_ml"]}, "rampS": 2.0, "speed": "disp_speed"},
            ],
        },
    },
    "sampling.spot": {         # 点样(legacy Step50): 抽驱动空气 → 打气点样 → 回抽释压
        # 2026-08-08 按 plan_dispense_array (translator 真源) 订正: 旧表只画
        # "dispense by sample_volume" 一段, 与真实柱塞轨迹方向相反 —— 实机是从
        # 空气口(4)**上行**吸驱动空气, 再切输出口(3)绝对打到 0, 最后回抽 1.0mL
        # 释压(DEFAULT_RETRACT_ML, 非动作参数, 故用字面 by)。
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [
            {"op": "aspirate", "byFrom": {"add": ["sample_volume_ml"]}, "port": 4, "rampS": 4.0, "speed": "asp_speed"},
            {"op": "dispense", "to": 0.0, "port": 3, "rampS": 8.0, "speed": "spot_disp_speed"},
            {"op": "aspirate", "by": 1.0, "port": 3, "rampS": 1.0, "speed": "asp_speed"},
        ],
    },
    "sampling.spot_band_layer": {
        # 蛇形分程供液, 实测 500~700s 而 rampS 只给 120 —— 柱塞会提前走到终点然后等 done.
        # 与展缸表"真实动作比 rampS 长时停在目标位, 那恰是物理事实"同一条理由.
        # port=3: 供液全程阀在输出口(plan_spot_band_run 证实)。
        "pump": {"from": "fixed", "id": "SMP"},
        "phases": [{"op": "dispense", "toFrom": {"add": ["spot_end_position_ml"],
                                                 "fallback": [0.0]}, "port": 3, "rampS": 120.0, "speed": "spot_disp_speed"}],
    },
}
