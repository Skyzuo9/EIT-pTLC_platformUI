# Sample Pump V2 — 空气驱动上样点样策略设计

## 概述

为 SY-03B (T-04) 上样注射泵设计一套新的指令翻译器 v2，采用"空气驱动"策略替代 v1 的"气泡分段清洗"策略。

### 动机

v1 策略需要在管路中预制 [清洗液-气泡-清洗液-气泡-...] 分段柱，制备过程复杂，对泵腔状态（必须空腔才能吸气泡）有严格约束。v2 策略将清洗步骤独立出来，利用空气段驱动样品从点样头打出，流程更简洁、可控。

### 物理模型

**关键原理：样品不进入注射泵，而是暂存在长管路（>25mL）中。** 泵只处理清洗液和空气。

```
[注射泵]──[T-04阀]──Port3(输出)──[长管路 >25mL]──[三通阀]──A:上样针
                                                          └──B:点样头
```

当泵从上样针侧抽吸时，空气/样品进入管路，**等体积的清洗液被置换入泵腔**。之后泵切换至废液口将这些被置换出的清洗液排掉，再从空气口抽取驱动空气，最后向点样流路打出——空气推动管路中的样品柱从点样头排出。

### 与 v1 的核心差异

| | v1 (气泡分段) | v2 (空气驱动) |
|---|---|---|
| 清洗 | 无独立清洗步骤 | Step 1: 独立清洗指令（PLC循环） |
| 样品位置 | 管路前端 | 管路前端（同） |
| 样品是否入泵 | 否（尾段隔离） | 否（空气隔离） |
| 废液处理 | 无 | Step 4: 排清洗液到废液口 |
| 驱动方式 | 分段气泡 + 尾段清洗液 | 独立驱动空气段 |
| 指令数 | ~N×2 + 尾段数 + 2 | 固定 6 条 |

---

## 工作流

### Step 1: 清洗管路

PLC 循环调用的单次复合指令。注射泵从清洗液端口吸满一管 → 打向输出口，清洗上样针和点样器。结束后管路充满清洗液，泵腔为空。

```
吸清洗液 (wash_port) → 打输出口 (output_port)
```

### Step 2: 回抽空气段

上样针在**空气**中。泵从输出口吸 `sample_vol + margin`。空气从针尖进入管路，等体积清洗液被置换入泵腔。

```
纯吸: output_port, volume = sample_vol + margin
```

泵腔: `(sample_vol + margin)` 清洗液（含管路死体积中的残余液）
管路: `[针端] (sample_vol + margin) 空气 [清洗液向阀端]`

### Step 3: 吸取样品

上样针插入**样品液**。泵从输出口吸 `sample_vol`。样品进入管路前端，等体积清洗液被置换入泵腔。

```
纯吸: output_port, volume = sample_vol
```

泵腔: `(2×sample_vol + margin)` 清洗液
管路: `[针端] sample_vol 样品 | (sample_vol + margin) 空气 [清洗液向阀端]`

### Step 4: 排清洗液至废液口

泵切换至废液口，全打出 (A0 归零)。泵腔内被置换出的清洗液排入废液。

```
纯打: waste_port, A0 (全打出归零)
```

泵腔: 空
管路: `[针端] sample_vol 样品 | (sample_vol + margin) 空气 [剩余清洗液]`

### Step 5: 抽取驱动空气

泵切换至空气口，吸 `sample_vol` 空气。

```
纯吸: air_port, volume = sample_vol
```

泵腔: `sample_vol` 驱动空气
管路: 不变

### Step 6: 点样打出

三通阀切换至点样流路 (A→B)，泵向输出口全打出。驱动空气推动管路中的液柱，样品从点样头排出。

```
纯打: output_port, A0 (全打出归零)
```

出口顺序: 驱动空气 → (管路中) 剩余清洗液 → 空气段 → 样品

---

## 指令序列

共 6 条 DT 指令，固定数量（与 sample_vol / margin 无关）：

| # | 步骤 | 指令类型 | DT 操作 | 构建函数 |
|---|------|---------|---------|---------|
| 0 | Step 1 | 复合 吸→打 | 吸清洗液→打输出口 | `build_segment_cmd` (复用v1) |
| 1 | Step 2 | 纯吸 | 从输出口吸 air | `build_aspirate_cmd` (复用v1) |
| 2 | Step 3 | 纯吸 | 从输出口吸 sample | `build_aspirate_cmd` (复用v1) |
| 3 | Step 4 | 纯打 | 全打出到废液口 A0 | `build_dispense_all_cmd` (复用v1) |
| 4 | Step 5 | 纯吸 | 从空气口吸 air | `build_aspirate_cmd` (复用v1) |
| 5 | Step 6 | 纯打 | 全打出到输出口 A0 | `build_dispense_all_cmd` (复用v1) |

**指令不可合并的原因：** Step 1→2 之间需要 PLC 判断清洗循环完成；Step 2→3 之间需要移针（空气→样品液）；Step 3→4 之间需要切废液口；Step 4→5 之间需要切空气口；Step 5→6 之间需要三通阀切换 (A→B)。每条指令之间都需要外部动作或 PLC 判断。

---

## API 设计

### 主翻译函数

```python
def translate_sample_v2_cmd(
    sample_volume_ml: float,
    *,
    margin_volume_ml: float = 1.0,
    wash_volume_ml: float = 25.0,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
```

### 辅助函数

```python
def calc_v2_volume_budget(
    sample_volume_ml: float,
    margin_volume_ml: float,
) -> dict:
    """计算 v2 流程各阶段的体积预算。
    
    Returns:
        {
            "step2_volume": sample_vol + margin,       # 空气段
            "step3_volume": sample_vol,                 # 样品
            "step4_waste_volume": 2*sample_vol + margin, # 排废液
            "step5_volume": sample_vol,                 # 驱动空气
            "step6_volume": sample_vol,                 # 点样打出
            "peak_pump_volume": 2*sample_vol + margin,  # 泵腔峰值
            "within_capacity": bool,                    # 是否在量程内
        }
    """
```

### 校验函数

```python
def validate_sample_v2_params(
    sample_volume_ml: float,
    margin_volume_ml: float,
    syringe_ml: float = SYRINGE_ML,
) -> None:
    """校验参数合法性，不合法抛出 ValueError。"""
```

---

## 端口映射

沿用 v1 代码 (`sample_pump_translator.py`) 的实际端口映射：

| 端口 | 常量 | 连接 | 用途 |
|------|------|------|------|
| Port 1 | `WASH_PORT` | 清洗液储液瓶 | Step 1 清洗液入口 |
| Port 2 | `WASTE_PORT` | 废液瓶 | Step 4 排废液 |
| Port 3 | `OUTPUT_PORT` | → 三通阀 C | Step 1/2/3/6 输出/输入 |
| Port 4 | `AIR_PORT` | 空气（直通大气） | Step 5 驱动空气入口 |

**注意：** 此映射与 `docs/sample_bubble_strategy.md` 不一致——文档中 Port 2 为空气、Port 4 为输出口。以代码为准（代码反映了最终物理接线）。

---

## 参数默认值

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `sample_volume_ml` | — (必填) | 上样体积，典型 5mL |
| `margin_volume_ml` | 1.0 | 空气余量，确保空气段完整隔离 |
| `wash_volume_ml` | 25.0 | Step 1 单次清洗体积（满量程） |
| `SYRINGE_ML` | 25.0 | 注射泵量程 |
| `ASP_SPEED` | 400 | 吸液速度 |
| `DISP_SPEED` | 400 | 打液速度（上限 500） |
| `STEP_DELAY` | 500 | 步骤间延迟 (ms) |

---

## 体积约束

### 量程约束

泵腔峰值体积出现在 Step 2+3 之后：

```
peak = 2 × sample_vol + margin ≤ SYRINGE_ML (25mL)
```

以典型值 `sample_vol=5mL, margin=1mL` 计算：peak = 11mL，远低于 25mL 量程。

最大允许上样体积（margin=1mL）：`sample_vol ≤ (25 - 1) / 2 = 12mL`。

### Step 1 清洗体积约束

```
wash_volume_ml ≤ SYRINGE_ML
```

默认值为满量程 25mL。

---

## 文件结构

```
UI-Upper/scripts/
├── sample_pump_translator.py      # v1 (保持不变)
├── sample_pump_translator_v2.py   # v2 (新增)
├── test_sample.py                 # v1 测试 (保持不变)
└── test_sample_v2.py              # v2 测试 (新增)
```

### v2 模块结构 (sample_pump_translator_v2.py)

```
常量定义 (端口、量程、速度)
  ├── WASH_PORT, WASTE_PORT, AIR_PORT, OUTPUT_PORT
  ├── SYRINGE_STEPS, SYRINGE_ML
  ├── ASP_SPEED, DISP_SPEED, STEP_DELAY
  └── DEFAULT_MARGIN_ML, DEFAULT_WASH_ML

复用 v1 构建函数 (从 sample_pump_translator 导入)
  ├── build_segment_cmd()
  ├── build_aspirate_cmd()
  └── build_dispense_all_cmd()

v2 核心
  ├── translate_sample_v2_cmd()     # 主翻译函数
  ├── calc_v2_volume_budget()       # 体积预算
  └── validate_sample_v2_params()  # 参数校验

辅助函数 (可与 v1 共用)
  ├── pump_init_cmd()
  └── pump_query_cmd()

命令行预览 (__main__)
```

### v2 测试脚本结构 (test_sample_v2.py)

```
命令行参数解析
  ├── sample_vol (必填, positional)
  ├── --margin (默认 1.0)
  ├── --wash (默认 25.0)
  ├── --addr (默认 "1")
  ├── --valve (T04/T06, 默认 T04)
  ├── --wash-port, --waste-port, --air-port, --output-port
  ├── --asp-speed, --disp-speed, --delay
  └── --tail (v1 兼容参数, 忽略)

交互模式 (无命令行参数时)
  └── 提示输入 sample_vol, margin 等

输出
  ├── 参数摘要
  ├── 体积预算表
  ├── 6 条 DT 指令 (带阶段标签)
  └── 初始化/状态查询指令
```

---

## 错误处理

与 v1 一致的策略：

- `sample_volume_ml ≤ 0` → `ValueError`
- `margin_volume_ml < 0` → `ValueError`（余量可为 0，表示无额外空气余量）
- `2 × sample_vol + margin > syringe_ml` → `ValueError`（泵腔超量程）
- `wash_volume_ml > syringe_ml` → `ValueError`
- `disp_speed > 500` → `ValueError`

---

## 测试用例

| 用例 | sample_vol | margin | 预期 |
|------|-----------|--------|------|
| 典型值 | 5.0 | 1.0 | 6条指令，peak=11mL |
| 零余量 | 5.0 | 0.0 | 6条指令，peak=10mL |
| 大体积 | 10.0 | 2.0 | 6条指令，peak=22mL |
| 超量程 | 13.0 | 1.0 | ValueError (27mL > 25mL) |
| 非法样品体积 | 0 | 1.0 | ValueError |
| 负余量 | 5.0 | -1.0 | ValueError |

---

## 待定事项

- [ ] PLC 侧 Step 1 清洗循环的具体实现方式（循环次数、终止条件）
- [ ] 三通阀切换的精确时序（是否需要指令间额外延迟）
- [ ] 实际管路体积的精确值（影响 Step 2 空气段是否足够隔离样品和清洗液）
