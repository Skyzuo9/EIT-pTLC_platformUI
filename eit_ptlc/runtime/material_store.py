"""物料账本 (四类物料: 盘位 / 上料 / 玻璃板 / 溶剂)
====================================================
功能:
    把 operation 引擎发出的运行事件翻译成物料事实并持久化到 SQLite. 四类物料与其位置由
    **config/material_topology.yaml 单一真源**声明 (load_topology 解析), 本模块不再硬编码:
      1. 盘位    三处位置 —— 货架(12 库位, 另按 (种类,板号,孔号) 记 72 格二态余量) +
                 中转A(刮板拍照) + 中转B(收集平台); 三处都有在位传感器可对账.
      2. 上料    上样料架两处托盘位; **纯传感器读数, 刻意不建软件账** (现值即真值,
                 再建一份只会漂移), 故不参与"账实不一致"判定.
      3. 玻璃板  上料仓(1Z)/下料仓(2Z) 张数, ±1 记账为主线; 另有 feedlift.probe_stack
                 按光电触发位 + 实测堆叠节距反算绝对张数做对账校正 (controller/feedlift_count.py).
      4. 溶剂    溶剂1-4 与洗脱液的瓶内余量 mL, 由注液/洗脱动作参数算量扣减
                 (硬件无任何体积测量: PLC 只有二值的废液管走空检测, 展缸液位是相机相对幅值).
    提供"下一个可用孔位"查询供前端预填输入框, 以及各类物料的人工盘点录入.
    仅用标准库 sqlite3, 不引入额外依赖.

在位传感器的寻址与极性:
    拓扑按「输入字节 + 位号」寻址 (而非中文点名) —— OPC UA 浏览名是 GBK 编码, asyncua 按
    UTF-8 解会成乱码; 而字节节点 IX8-IX12 是 ASCII 名且已验证可读, 且字节读+取位与直读
    IO 容器 bit 节点交叉验证一致 (机器人工具检测1/2/3 两条路都得 [1,1,0]).
    极性必填无默认: nc 常闭 -> False=有料; no 常开 -> True=有料. 曾按 "bit=1 表示有板"
    解读而实测该类接近开关是 NC, 正好相反 —— 故不留默认值, 且带 verified 标注是否已实证.

设计取向 (记账侧建议式; 换板决策侧裁决式):
    记账侧仍是建议式: 账本作为 make_event_sink 的一路接收器在动作完成之后才看到事实,
    且 runtime/events.py 的 sink 契约本身是 best-effort, 故丢写只导致预填不准 (next_fresh /
    suggest_inputs), 不否决任何动作; 把关由流程里既有的 human/confirm 节点完成.

    唯一的例外是 plan_staging: 耗材换板环节按它自动决策 (经 material.plan_staging 动作供
    ptlc_full_v2 的 ensure_* 脚本做 if 分支), 账本在这一条路径上是裁决方. 代价是账实失同步
    会变成撞机或抓空, 故该动作的上位机闭包 (runtime/bootstrap.py::_material_plan_staging)
    必须用中转A/B 在位传感器与判定核对后才放行 —— 那两路极性已现场实证, 是唯一能防撞的信号;
    货架 12 路与物理世界零耦合 (见下方注释), 库位有无只能信人工在架账 rack_occupancy
    (plan_staging/next_fresh/reserve_count 已按它跳过无板库位), 核对不了.

    记账粒度绑在脚本名上 (见 config/material_bindings.yaml 的理由), 不做点位推断.
    只有 vm_node_done 且 status=DONE 才提交; 失败与中断天然不入账.

    单发动作 (POST /api/actions/{name}/run) 走 step_done 也入账, 但**只对动作级绑定**
    (当前只有 liquid_draw). 判据是 effect 能不能自愈, 不是触发路径:
      溶剂余量无任何传感器, 漏记的偏差单向累积且只会偏高 ("以为还有, 其实没了"),
      而单发上液恰是调试期最频繁的动作 —— 必须记;
      玻璃板张数有 feedlift.probe_stack 每 cycle 反算绝对张数校正, 中转占用有已验证光电
      加 plan_staging 开工前防呆硬停 —— 它们能自愈, 维持流程级即可.
    单发扣账在流水里标 "面板单发", 试机空跑造成的假数据由人在物料页覆盖式改回.

    在途 (payload_transit): 记"载荷此刻在哪把夹爪上". 取放是两段式的 ——
    pick 落账时板已离架但尚未落位, 旧账本在这段窗口里仍说板在原处, 中途取消/断电即静默
    失同步且不留痕. 有了在途行, 那段窗口有明确表达, 崩溃后物料页能指出"板N滞留在大爪上",
    三维也能把托盘挂到机械臂上跟手走.

    独立库文件: 绝不与 var/runs.db 合并 —— 后者 max_runs LRU 淘汰最旧运行连带其事件,
    而余量账本不能被淘汰.

表结构:
    material_cells(kind, plate, hole PK, state, sample_id, updated_at, run_id)
        state: FRESH = 此孔可供一件未用耗材; USED = 不可再供料 (装着已用件);
               ABSENT = 件不在位 (被人拿走, 孔空着; 仅人工盘点写入, 流程不产生它)
        USED 的两种情形由 sample_id 区分: 空串 = 已用件在位; 非空 = 装着该样品的已用件 (成品待取)
        三维表现 (2026-08-15 用户定案): 粉桶 FRESH=直立 / USED=倒扣在位 / ABSENT=不画
    staging_occupancy(area PK, kind, plate, since_at, run_id)  -- plate 为 NULL 表示该中转区空
    rack_occupancy(kind, plate PK, present, updated_at, run_id)
        -- 货架库位板级在架人工账: 1=在架; 0=不在 (正在中转, 在夹爪上, 或人工标无板)
        -- 不变量: 板在中转**或在爪上** <=> 其库位 present=0
           (由一切写 staging_occupancy / payload_transit 的路径维护)
    payload_transit(carrier PK, payload, kind, plate, hole, from_loc, to_loc,
                    since_at, run_id, script, epoch)
        -- 载荷此刻在哪把夹爪上; carrier 作主键 => 一把爪最多一件载荷, 互斥由主键保证
        -- 空表 = 两把爪都空手, 是正确初值, 故 _seed 不给它播种
        -- epoch = 记下这行的那个进程 (时间戳-pid); 与本进程不同即"上一次运行遗留",
        --   grid() 里透出为 stale=True。刻意不自动清 —— 账本只反映不裁决
    payload_seat(seat PK, payload, kind, plate, hole, since_at, run_id, script, epoch)
        -- 单件耗材停在工位夹具上 (刮板夹具 / 收集工位); seat 作主键 => 一个座最多一件
        -- 空表 = 三个座都空着, 是正确初值, 故 _seed 不给它播种
        -- ⚠ 它把"在爪上"这个易失态尽早换成"在座上"这个耐久态: 没有它, 单件被放到工位后
        --   在途行无人清 (那几个站侧放料脚本此前在绑定表里一条绑定都没有), 会一路挂到
        --   几分钟后归还中转板 —— 三维照着画就是瓶/桶焊在机械臂上飞完整个周期
    location_presence(location_id PK, raw_bit, present, checked_at)
        -- 最近一次在位对账的传感器快照; raw_bit=原始位, present=按极性折算后的"有料"
        -- location_id: 货架为 rack.<kind>.<plate>, 其余即拓扑里的位置 id
    plate_magazines(magazine PK, count, capacity, updated_at, run_id)   -- feed=上料仓, waste=下料仓
    liquid_bottles(bottle PK, label, volume_ml, capacity_ml, updated_at, run_id)
    seat_occupancy(seat PK, present, updated_at)
        -- 单板停放位 (点样座/刮板拍照台) 有板/无板人工账: 1=有板; 0=无板
        -- 这两处无任何在位传感器 (拓扑里不带 sensor 段), 只能人工记
        -- ⚠ 只供前端展示与人工同步: 不进统计口径 (summary), 不参与 plan_staging /
        --   next_fresh / 预填 / 批次准入, 也不写调度器的 samples.position
    material_events(id PK AUTOINCREMENT, ts, run_id, script, effect, kind, plate, hole,
                    from_state, to_state, detail)  -- append-only 追溯流水, 无淘汰

线程模型:
    on_event 由引擎协程 (事件循环线程) 调用, 查询由异步端点调用; 用 check_same_thread=False
    + 进程内锁串行化, 与 runtime/run_store.py 一致.
"""

from __future__ import annotations

import itertools
import logging
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

log = logging.getLogger(__name__)

# 网格规格: 6 块板 x 6 个孔, 两种耗材各一套
PLATES_PER_KIND = 6
HOLES_PER_PLATE = 6
KINDS = ("collector", "bottle")
AREAS = {"staging-a": "collector", "staging-b": "bottle"}

# 孔位三态
STATE_FRESH = "FRESH"    # 可供一件未用耗材
STATE_USED = "USED"      # 不可再供料 (装着已用件; 三维里粉桶倒扣在位)
STATE_ABSENT = "ABSENT"  # 件不在位 (仅人工盘点写入; 流程选料只认 FRESH, 天然排除它)

#: 薄层板的工艺阶段 (按序递进)。词表与前端 twin/bindings/plateTraceState.STAGE 逐字一致
#: —— 那边是四态外观的开关, 这边是账本列, 两处对不上就会画错。
PLATE_STAGE_BLANK = "blank"
PLATE_STAGE_SPOTTED = "spotted"
PLATE_STAGE_DEVELOPED = "developed"
PLATE_STAGE_SCRAPED = "scraped"
PLATE_STAGES = (PLATE_STAGE_BLANK, PLATE_STAGE_SPOTTED,
                PLATE_STAGE_DEVELOPED, PLATE_STAGE_SCRAPED)
#: 阶段只进不退 (排名越大越靠后); 退回只能靠人工显式设置
PLATE_STAGE_RANK = {stage: index for index, stage in enumerate(PLATE_STAGES)}
STATES = (STATE_FRESH, STATE_USED, STATE_ABSENT)

# 换板决策动作码 (plan_staging 的返回值; 直接进 VM 的 STRING 变量供 ensure_* 脚本分支)
OP_NONE = "NONE"              # 中转板尚有 FRESH 孔, 原地复用, 不动整板
OP_PUT_NEW = "PUT_NEW"        # 中转区空, 从货架取一块有料的板过来
OP_SWAP = "SWAP"              # 中转板已耗尽, 先送回原库位再取新板
OP_EXHAUSTED = "EXHAUSTED"    # 账本里全部板都无 FRESH 孔
OP_BLOCKED = "BLOCKED"        # 有料但全被其他样品预留 / 换板会吞掉他人在保留孔 (等释放后重试)
PLAN_OPS = (OP_NONE, OP_PUT_NEW, OP_SWAP, OP_EXHAUSTED, OP_BLOCKED)

# 玻璃板仓与溶剂瓶不再在此硬编码 —— 唯一真源是 config/material_topology.yaml,
# 经 load_topology 解析后由 MaterialTopology.magazines / .bottles 提供 (两份真源必然漂移)。

# 料库检测光电: 12 位板级在位, 内部索引 1-6=collector(货架上半), 7-12=bottle(货架下半)
# PLC 侧 %IX11.0-7 = 料库检测 1-8, %IX12.0-3 = 料库检测 9-12
# ⚠ IX12 是共享字节: bit4-6 是机器人工具检测1/2/3, 故必须只取低 4 位
#
# 【2026-07-26 现场 A/B 实测: 这 12 位与物理世界零耦合, 对账结果暂不可用】
#   直连真机 PLC 只读整个 IO 映像做三态对照 (货架很多托盘 / 拿掉一块 / 全部拿掉):
#   三次读数**完全相同** —— 料库检测 1-12 恒为 000000000000, 且 IO 容器 115 个点里为 True
#   的始终是同样那 35 个, 无一位翻转。⇒ 正极性(有板该 1)与反极性(空位该 1)都被证伪,
#   **信号根本没到达 PLC**, 不是极性问题, 也不是本模块的读法问题。
#   读法已被交叉验证无误: 同容器的 机器人工具检测1/2/3 用 IO bit 直读 = [True,True,False],
#   与从 Host_Computer.IX12=48 按位解出的 [1,1,0] 完全吻合 (掩码/位序/字节读法都对)。
#   输入映像本身是活的: IX0=203 IX3=86 IX5=85 IX8=228 IX9=91 IX12=48 均非零。
#   排查切分: 料库 9-12 走 %IX12.0-3, 与工作正常的机器人工具检测同字节 ⇒ 该 IO 模块确定在扫描,
#   只可能是传感器侧; 料库 1-8 走 %IX11 整字节 (IX0-IX12 里唯一全 0 者) ⇒ 另多一层模块/总线嫌疑。
#   金属触碰对照实验 (2026-07-26, OPC UA 订阅 50ms 采样, 已证明能抓 1s 级瞬时):
#     触碰货架区域 6 个底层库位 -> IO 全 115 点零响应;
#     触碰上料区域一处         -> 上样料架检测1 立刻 True->False->True, 两次触碰全抓到。
#   ⇒ 工具链与传感器类型都没问题, 是货架这 12 个位置本身没有可用信号。
#   底层对应料库 7-12, 其中 9-12 走 %IX12.0-3 (与工作正常的机器人工具检测同字节, 模块确在扫描)
#   ⇒ "模块没配进总线"亦被排除, 只剩传感器侧 (未安装 / 未供电 / 断线)。
#   ⚠ 极性 (2026-07-27 更正): 7-26 曾据触碰实验判该族为常闭 NC ("空闲 True, 靠近 False"),
#      系误判 —— 当时料架1上有托盘, raw=1 是 NO 的有料态, 触碰只是短暂遮断检测。7-27 托盘
#      对照 (料架2 有托盘=1; 料架1/中转A/B 空=0) + PLC 机器人程序按 NOT 传感器 判"中转位
#      空才搬板" (PLCsoftware/OPCUAtest/机器人PLC侧程序.xml) 互证: 该族实为**常开 NO, 1=有料**。
#      四个单点已翻 no 并实证; 货架 12 位信号未接入, 维持 nc 待硬件接通后按 no 重验再翻。
#   ⚠ 存疑: 全 IO 表里"料架"类点只有 上样料架检测1/2 两个且只有它们工作 —— 货架很可能**根本
#      没做每库位检测**。若属实, 板级对账在硬件层面不成立, 应撤掉页面的光电列与对账按钮
#      (否则永远 12 个红叉, 反而淹没真正的账实不符); 货架余量退回纯人工盘点。待现场确认。
#   软件侧全通 (读取/解码/掩码/对账/落快照均已验证), 现场修好即可用; 在那之前死 0 经 nc
#   解码恒为"有板", 恰与近满架的账本大体一致 —— 只有被标去中转的板会亮红 (账本期望空)。
#   按用户选择保持字面报告, 不加"传感器不可信"的推断。
#   【2026-08-02 决策更新】上一条"保持字面报告"已被推翻: 通用规则改为 verified:false 的
#   传感器只显读数不判定 (ok=None, 见 _reconcile_rack/_reconcile_single/grid), 货架 12 位
#   不再按死 0 判红绿; 板级在架改由人工账 rack_occupancy 记录 (set_rack_presence 录入),
#   且"无板"参与决策: summary 剔除其孔位, plan_staging/next_fresh/reserve_count 跳过无板库位。
#   佐证: 料库检测1..12 在整个 PLC 程序里从未被任何逻辑读过 (只有 IO 地址声明), 属早已
#   废弃的"PLC 负责搬板"架构遗留 (与 plc_nodes.yaml:158-167 那批通道同源), 从未投运验证。
#   注: OPC UA 浏览名是 GBK 编码, asyncua 按 UTF-8 解会成乱码; 按中文节点名查找需先还原:
#       name.encode("utf-8", "surrogateescape").decode("gbk")
PRESENCE_BITS = PLATES_PER_KIND * len(KINDS)   # 12

# 绑定表允许的 effect (闭集; 未知值在加载时即报错)
_EFFECTS = ("staging_load", "staging_unload", "consume", "fill", "plate_take", "plate_put",
            "transit_pick", "transit_place", "plate_seat", "plate_stage")
_ACTION_EFFECTS = ("liquid_draw", "scrape_arm", "powder_fill")

# effect -> material_cells 的余量列名。**必须是模块常量表**, 绝不能让 YAML 里的字符串
# 直接进 SQL —— _do_cell_add 是用 f-string 拼列名的 (sqlite3 的参数化绑不了标识符)。
_CELL_AMOUNT_COLUMN = {"powder_fill": "powder_mm3", "liquid_fill": "liquid_ml"}

# 名义容量 (只用于溢出留痕, 不入库不裁决): 40mL 样品瓶按可用腔容 29.65mL 记 ——
# "40mL" 是瓶身标称(灌到瓶口), 三维液柱能表达的是内腔可用深 78mm × 截面 380.13mm²。
# 78 = 实测肩高 83.0 − 瓶底 5.0, **瓶颈那 12mm 不计体积**(2026-08-07 订正, 原值 85/32.31)。
# 与 config/material_topology.yaml 的 contents[bottle].capacity 及 three_d 的 rig_map
# station_seats[collect-bottle].liquid 互为镜像, 改一处要改三处。
# 粉桶不设名义容量: 一桶一带的用法下不该触顶, 触了也是估算偏差而非账实失同步。
_CELL_CAPACITY = {"liquid_ml": 29.65}

# 在途载荷的搬运器 = 机器人两把夹爪. 名字与 three_d 的 rig_map / device-manifest 的机构 id
# 逐字一致 (controller/robot_controller.py::_TWIN_GRIPPER_BY_TOOL), 前端据此把在途载荷挂到
# TOOL_MOUNT 之下; 错一个字前端静默不动.
# ⚠ 1 号吸盘刀 (玻璃板) 刻意不在此列: 薄层板的位置权威是 experiments.db 的 samples.position,
#   经 /api/scheduler/snapshot 下发, 与本账本是两条独立的链路. 收进来就成了第二套板账本.
CARRIER_PLATE96 = "gripper_plate96"   # 2 号大夹爪: 整板 (6 孔托盘)
CARRIER_VIAL = "gripper_vial"         # 3 号小夹爪: 单件 (收集器 / 收集瓶)
CARRIERS = (CARRIER_PLATE96, CARRIER_VIAL)

# 在途载荷形态
PAYLOAD_TRAY = "tray"    # 整板: 身份 = (kind, plate)
PAYLOAD_ITEM = "item"    # 单件: 身份 = (kind, plate, hole)
PAYLOADS = (PAYLOAD_TRAY, PAYLOAD_ITEM)

# 在途的起讫位置词表 (staging 由 kind 解析成 staging-a / staging-b, 不在绑定表里写死区名 ——
# 一个叶子脚本按 rack_id 入参服务两种耗材, 写死会绑错区)
LOC_RACK = "rack"
LOC_STAGING = "staging"
# 工位夹具 (刮板夹具 / 收集工位): 单件耗材被小夹爪送上去之后停在那儿, 具体是哪个座由绑定的
# seat 字段指定 (与 staging 不同, station 不能由 kind 反查 —— 同一种耗材有两个工位座).
# ⚠ 它的存在是为了让"在爪上"这个易失态尽早换成"在座上"这个耐久态: 没有它, 放件那一刻
#   在途行无人清, 单件会在账本上一直"挂在夹爪上"直到几分钟后归还中转板.
LOC_STATION = "station"
TRANSIT_LOCS = (LOC_RACK, LOC_STAGING, LOC_STATION)

# 进程内 store 实例序号, 参与 epoch 构造 (见 MaterialStore.__init__ 的说明)
_EPOCH_SEQ = itertools.count(1)

_SCHEMA_KEY = "ptlc.material_bindings/v1"
_TOPOLOGY_SCHEMA_KEY = "ptlc.material_topology/v1"

# 传感器极性 (必填, 无默认值): nc 常闭 -> False=有料; no 常开 -> True=有料
POLARITY_NC = "nc"
POLARITY_NO = "no"
_POLARITIES = (POLARITY_NC, POLARITY_NO)


@dataclass(frozen=True)
class SensorBit:
    """一个在位传感器的寻址与解读方式.

    字段:
        name: PLC 中文点名 (仅文档与现场对照, 不参与寻址)
        byte: 输入字节节点名 (如 IX10; ASCII 名, 在 Host_Computer 容器)
        bit: 该字节内的位号 0-7
        polarity: nc 常闭 (False=有料) | no 常开 (True=有料)
        verified: 极性是否已现场实证
        note: 备注 (如"未供电")
    """
    name: str
    byte: str
    bit: int
    polarity: str
    verified: bool = False
    note: str = ""

    def present(self, byte_value: int) -> bool:
        """按本点极性从字节值折算"是否有料".

        参数:
            byte_value: 该字节的原始值
        返回:
            bool, True 表示该位置有料
        """
        raw = bool(int(byte_value) >> self.bit & 1)
        # nc 常闭: 空闲输出 True, 有料时被拉低 -> 取反
        return (not raw) if self.polarity == POLARITY_NC else raw


@dataclass(frozen=True)
class LocationSpec:
    """一个物料位置.

    字段:
        id: 位置标识 (rack / staging-a / feed-1 ...)
        label: 中文显示名
        category: 所属物料种类 key
        area: 对应 staging_occupancy.area (软件记板号的中转区); None = 无软件账
        rack_bits: 货架特例, 12 个 SensorBit (顺序 = collector 1-6 then bottle 1-6); 非货架为 ()
        sensor: 单点传感器; 货架为 None (用 rack_bits)
    """
    id: str
    label: str
    category: str
    area: Optional[str] = None
    rack_bits: tuple = ()
    sensor: Optional[SensorBit] = None


@dataclass(frozen=True)
class CategorySpec:
    """一类物料 (驱动左 Dock 导航与页面分区)."""
    key: str
    label: str
    hint: str
    locations: tuple = ()
    magazines: tuple = ()      # [(id, label, capacity)]
    bottles: tuple = ()        # [(id, label, capacity_ml)]
    seats: tuple = ()          # [(id, label)] —— 单板停放位 (点样座/刮板拍照台), 纯人工账
    payload_seats: tuple = ()  # [(id, label, kind)] —— 单件耗材在工位夹具上的停放位
    contents: tuple = ()       # [(kind, label, unit, capacity)] —— 单件内容物的量纲与名义容量


@dataclass(frozen=True)
class MaterialTopology:
    """物料拓扑: 四类物料及其位置与传感器 (config/material_topology.yaml 的解析结果)."""
    categories: tuple = ()

    @property
    def locations(self) -> tuple:
        """全部位置 (按种类顺序展平)."""
        return tuple(loc for cat in self.categories for loc in cat.locations)

    @property
    def magazines(self) -> dict:
        """玻璃板仓表 {仓号: (显示名, 容量)}, 替代原 MAGAZINES 常量."""
        return {m[0]: (m[1], m[2]) for cat in self.categories for m in cat.magazines}

    @property
    def bottles(self) -> dict:
        """溶剂瓶表 {瓶号: (显示名, 容量mL)}, 替代原 BOTTLES 常量."""
        return {b[0]: (b[1], b[2]) for cat in self.categories for b in cat.bottles}

    @property
    def seats(self) -> dict:
        """单板停放位表 {座号: 显示名}, 真源是拓扑; 座位无传感器, 只有人工账."""
        return {s[0]: s[1] for cat in self.categories for s in cat.seats}

    @property
    def payload_seats(self) -> dict:
        """单件耗材的工位停放位表 {座号: (显示名, 只收哪种耗材)}, 真源是拓扑.

        与 seats 的区别见 material_topology.yaml 的 holder 段: 那边是薄层板的人工账,
        这边是单件耗材的自动账 (transit_place/transit_pick 的 station 分支写它).
        """
        return {s[0]: (s[1], s[2]) for cat in self.categories for s in cat.payload_seats}

    def byte_names(self) -> tuple:
        """本拓扑用到的全部输入字节节点名 (供对账一次性读取), 去重且保持声明序."""
        seen: list[str] = []
        for loc in self.locations:
            for sensor in ((loc.sensor,) if loc.sensor else ()) + tuple(loc.rack_bits):
                if sensor.byte not in seen:
                    seen.append(sensor.byte)
        return tuple(seen)


def _parse_sensor(spec: dict, where: str) -> SensorBit:
    """解析单点传感器声明; 极性/位号非法即抛 (无默认值, 见配置文件说明)."""
    if spec.get("polarity") is False:
        # yaml 1.1 把裸 no/off 解析成布尔 False, 这个坑已实际踩过 —— 指明写法而不是报"缺失"
        raise ValueError(f"物料拓扑 {where}: polarity 裸 no 被 yaml 解析成布尔, 请写带引号的 \"no\"")
    polarity = str(spec.get("polarity") or "")
    if polarity not in _POLARITIES:
        raise ValueError(f"物料拓扑 {where}: polarity 必填且须为 {_POLARITIES}, 实际 {polarity!r}")
    byte = str(spec.get("byte") or "")
    if not re.fullmatch(r"IX\d+", byte):
        raise ValueError(f"物料拓扑 {where}: byte 应形如 IX10, 实际 {byte!r}")
    bit = spec.get("bit")
    if not isinstance(bit, int) or not 0 <= bit <= 7:
        raise ValueError(f"物料拓扑 {where}: bit 应为 0..7 的整数, 实际 {bit!r}")
    return SensorBit(name=str(spec.get("name") or ""), byte=byte, bit=bit,
                     polarity=polarity, verified=bool(spec.get("verified")),
                     note=str(spec.get("note") or ""))


def load_topology(path: str | Path) -> MaterialTopology:
    """读取物料拓扑并做闭集校验.

    功能:
        解析 config/material_topology.yaml: 四类物料、每类的位置、每个位置的传感器
        (字节+位+极性)。校验 schema 版本、key/id 唯一、极性与位号合法、货架必须恰好 12 位。
        任何非法项直接抛错 —— 拓扑写错会让整页在位显示失真, 必须启动即失败。
    参数:
        path: material_topology.yaml 路径
    返回:
        MaterialTopology
    """
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    schema = str(doc.get("schema") or "")
    if schema != _TOPOLOGY_SCHEMA_KEY:
        raise ValueError(f"物料拓扑 schema 应为 {_TOPOLOGY_SCHEMA_KEY}, 实际为 {schema!r}")
    raw_cats = doc.get("categories")
    if not isinstance(raw_cats, list) or not raw_cats:
        raise ValueError("物料拓扑 categories 必须是非空列表")

    cats: list[CategorySpec] = []
    seen_keys: set[str] = set()
    seen_loc_ids: set[str] = set()
    seen_mag: set[str] = set()
    seen_bottle: set[str] = set()
    seen_seat: set[str] = set()
    seen_payload_seat: set[str] = set()
    for raw in raw_cats:
        if not isinstance(raw, dict):
            raise ValueError("物料拓扑 categories 每项必须是映射")
        key = str(raw.get("key") or "")
        if not key:
            raise ValueError("物料拓扑: category 缺 key")
        if key in seen_keys:
            raise ValueError(f"物料拓扑: category key {key!r} 重复")
        seen_keys.add(key)

        locations: list[LocationSpec] = []
        for raw_loc in (raw.get("locations") or []):
            loc_id = str(raw_loc.get("id") or "")
            if not loc_id:
                raise ValueError(f"物料拓扑 {key}: location 缺 id")
            if loc_id in seen_loc_ids:
                raise ValueError(f"物料拓扑: location id {loc_id!r} 重复")
            seen_loc_ids.add(loc_id)
            sensor_spec = raw_loc.get("sensor") or {}
            rack_bits: tuple = ()
            sensor: Optional[SensorBit] = None
            if raw_loc.get("rack_slots"):
                # 货架特例: 12 个位按 (collector 1-6, bottle 1-6) 顺序展开, 共用极性
                raw_bits = sensor_spec.get("rack_bits") or []
                if len(raw_bits) != PRESENCE_BITS:
                    raise ValueError(
                        f"物料拓扑 {loc_id}: rack_bits 应为 {PRESENCE_BITS} 项, 实际 {len(raw_bits)}")
                rack_bits = tuple(
                    _parse_sensor({**sensor_spec, **b}, f"{loc_id}.rack_bits[{i}]")
                    for i, b in enumerate(raw_bits))
            elif sensor_spec:
                sensor = _parse_sensor(sensor_spec, loc_id)
            locations.append(LocationSpec(
                id=loc_id, label=str(raw_loc.get("label") or loc_id), category=key,
                area=(str(raw_loc["area"]) if raw_loc.get("area") else None),
                rack_bits=rack_bits, sensor=sensor))

        magazines: list[tuple] = []
        for raw_m in (raw.get("magazines") or []):
            mid = str(raw_m.get("id") or "")
            if not mid or mid in seen_mag:
                raise ValueError(f"物料拓扑 {key}: magazine id {mid!r} 缺失或重复")
            seen_mag.add(mid)
            magazines.append((mid, str(raw_m.get("label") or mid), int(raw_m.get("capacity") or 0)))

        bottles: list[tuple] = []
        for raw_b in (raw.get("bottles") or []):
            bid = str(raw_b.get("id") or "")
            if not bid or bid in seen_bottle:
                raise ValueError(f"物料拓扑 {key}: bottle id {bid!r} 缺失或重复")
            seen_bottle.add(bid)
            bottles.append((bid, str(raw_b.get("label") or bid),
                            float(raw_b.get("capacity_ml") or 0.0)))

        # 单板停放位: 无传感器故不进 locations (那条路要 sensor/极性), 单列一族
        seats: list[tuple] = []
        for raw_s in (raw.get("seats") or []):
            sid = str(raw_s.get("id") or "")
            if not sid or sid in seen_seat:
                raise ValueError(f"物料拓扑 {key}: seat id {sid!r} 缺失或重复")
            seen_seat.add(sid)
            seats.append((sid, str(raw_s.get("label") or sid)))

        # 单件耗材的工位停放位: 无传感器 (与 seats 同), 但由流程事件自动记账 (与 seats 不同)
        payload_seats: list[tuple] = []
        for raw_p in (raw.get("payload_seats") or []):
            pid = str(raw_p.get("id") or "")
            if not pid or pid in seen_payload_seat:
                raise ValueError(f"物料拓扑 {key}: payload_seat id {pid!r} 缺失或重复")
            seen_payload_seat.add(pid)
            # kind 必填且是闭集: 它是放件时的准入约束, 缺省会让"粉桶放进瓶座"静默通过
            pkind = str(raw_p.get("kind") or "")
            if pkind not in KINDS:
                raise ValueError(
                    f"物料拓扑 {key}: payload_seat {pid!r} 的 kind {pkind!r} 不在 {KINDS}")
            payload_seats.append((pid, str(raw_p.get("label") or pid), pkind))

        # 单件内容物的量纲与名义容量 (粉桶粉柱 / 样品瓶液柱)。
        # 不声明就是"不知道" —— 前端据此整条装量条不渲染, 而不是画成 0%
        # (与 presenceText 返回 '—' 同一条纪律: 不知道不许画成一个数)。
        contents: list[tuple] = []
        seen_content: set[str] = set()
        for raw_c in (raw.get("contents") or []):
            ckind = str(raw_c.get("kind") or "")
            if ckind not in KINDS:
                raise ValueError(
                    f"物料拓扑 {key}: contents 的 kind {ckind!r} 不在 {KINDS}")
            if ckind in seen_content:
                raise ValueError(f"物料拓扑 {key}: contents 的 kind {ckind!r} 重复")
            seen_content.add(ckind)
            capacity = float(raw_c.get("capacity") or 0.0)
            if capacity <= 0:
                raise ValueError(
                    f"物料拓扑 {key}: contents[{ckind}] 的 capacity 必须为正 "
                    f"(不知道就整条别写 —— 写 0 会让页面把'不知道'画成 0%)")
            contents.append((ckind, str(raw_c.get("label") or ckind),
                             str(raw_c.get("unit") or ""), capacity))

        cats.append(CategorySpec(
            key=key, label=str(raw.get("label") or key), hint=str(raw.get("hint") or ""),
            locations=tuple(locations), magazines=tuple(magazines), bottles=tuple(bottles),
            seats=tuple(seats), payload_seats=tuple(payload_seats),
            contents=tuple(contents)))
    return MaterialTopology(categories=tuple(cats))


@dataclass(frozen=True)
class MaterialBindings:
    """记账绑定表: 脚本级 (op: run_script) 与动作级 (op: call) 两段."""
    scripts: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.scripts or self.actions)


def _with_source(detail: str, source: str) -> str:
    """给流水备注挂上触发来源 (如 "面板单发"); source 为空则原样返回.

    单发扣账必须在流水里可辨: 试机空跑 (没接管路/没装瓶) 造成的假数据靠人在物料页
    覆盖式改回, 前提是他能一眼看出哪几条是手点出来的。
    """
    return f"[{source}] {detail}" if source else detail


def _parse_plate_seat_binding(script: str, effect: str, spec: dict,
                              known_seats: dict) -> dict[str, Any]:
    """解析薄层板的板位/工艺阶段绑定.

    参数:
        script: 脚本名 (报错留痕用)
        effect: plate_seat (放上/拿走) | plate_stage (推进阶段)
        spec: YAML 绑定项
        known_seats: 拓扑里的合法座 {id: label}
    返回:
        Dict, 规范化后的绑定项
    Raises:
        ValueError: 座名不在拓扑里 / 阶段不在词表里 / 键写错

    座名两种来源二选一, **不许都给**:
      seat      固定座 (如刮板拍照台)
      seat_from + seat_map   由脚本入参决定 (如 station_id / tank), 映射表必须**逐条列全**
        —— 不做"前缀拼接"这类隐式规则: 拼错一个字会静默落到一个不存在的座上,
        而列全了启动就报错。映射表里没有的入参值 = 该次调用不记板位 (如放到废料仓,
        那条走的是 plate_put 计数)。
    """
    seat = str(spec.get("seat") or "")
    seat_from = str(spec.get("seat_from") or "")
    seat_map = spec.get("seat_map") or {}
    if bool(seat) == bool(seat_from):
        raise ValueError(f"物料绑定 {script}: seat 与 seat_from 必须二选一")
    if seat and seat not in known_seats:
        raise ValueError(f"物料绑定 {script}: seat {seat!r} 不在 {tuple(known_seats)}")
    if seat_from:
        if not isinstance(seat_map, dict) or not seat_map:
            raise ValueError(f"物料绑定 {script}: seat_from 必须配 seat_map")
        for value, target in seat_map.items():
            if str(target) not in known_seats:
                raise ValueError(
                    f"物料绑定 {script}: seat_map[{value!r}] = {target!r} 不在拓扑座里")
    allowed = {"effect", "seat", "seat_from", "seat_map"}
    out: dict[str, Any] = {"effect": effect, "seat": seat, "seat_from": seat_from,
                           "seat_map": {str(k): str(v) for k, v in seat_map.items()}}
    if effect == "plate_seat":
        allowed.add("present")
        if "present" not in spec:
            raise ValueError(f"物料绑定 {script}: plate_seat 必须写 present (放上/拿走)")
        out["present"] = bool(spec["present"])
    else:
        allowed.add("stage")
        stage = str(spec.get("stage") or "")
        if stage not in PLATE_STAGE_RANK:
            raise ValueError(f"物料绑定 {script}: stage {stage!r} 不在 {PLATE_STAGES}")
        out["stage"] = stage
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"物料绑定 {script}: 未知键 {sorted(unknown)}")
    return out


def _parse_transit_binding(script: str, spec: dict, effect: str,
                           known_payload_seats: dict) -> dict[str, Any]:
    """校验并规范化一条在途绑定 (transit_pick / transit_place).

    功能:
        在途绑定挂在 robot_* 叶子脚本上 —— 那一层才有"合爪/松爪"这个物理瞬间。
        kind 一律从入参取 (kind_from, 通常是 rack_id): 一个叶子脚本按 rack_id 服务
        collector 与 bottle 两种耗材, 在绑定表里写死 kind 会有一半绑错。
        同理 from_loc/to_loc 只写 rack | staging, 具体是 staging-a 还是 staging-b
        由 kind 在运行期解析 (AREAS 的反查)。

        station 是唯一的例外, 且例外的方向相反: 它必须写死 seat, 因为同一种耗材有两个
        工位座 (刮板夹具 / 收集工位夹具都收 collector), kind 反查不出来。相应地
        **from_loc=station 时不要 kind_from/plate_from/hole_from** —— 那几个站侧取料脚本
        只有 station_id 入参, 身份只可能从座位行读回来, 从入参取就是猜。
    参数:
        script: 脚本名 (报错定位用); spec: 绑定项原文; effect: 已校验过的 effect 名
        known_payload_seats: 拓扑里合法的工位座 {id: (label, kind)}, 拼错即启动失败
    返回:
        dict, 规范化后的绑定项
    """
    carrier = str(spec.get("carrier") or "")
    if carrier not in CARRIERS:
        raise ValueError(f"物料绑定 {script}: carrier {carrier!r} 不在 {CARRIERS}")

    def _seat_of(loc: str, key: str) -> str:
        """station 位置必须显式声明座号 (且只有 station 允许声明)."""
        seat = str(spec.get("seat") or "")
        if loc == LOC_STATION:
            if seat not in known_payload_seats:
                raise ValueError(
                    f"物料绑定 {script}: {key}=station 的 seat {seat!r} 不在拓扑的 "
                    f"payload_seats {tuple(known_payload_seats)} 里")
            return seat
        if seat:
            raise ValueError(f"物料绑定 {script}: 只有 {key}=station 才能声明 seat")
        return ""

    if effect == "transit_pick":
        payload = str(spec.get("payload") or "")
        if payload not in PAYLOADS:
            raise ValueError(f"物料绑定 {script}: payload {payload!r} 不在 {PAYLOADS}")
        from_loc = str(spec.get("from_loc") or "")
        if from_loc not in TRANSIT_LOCS:
            raise ValueError(f"物料绑定 {script}: from_loc {from_loc!r} 不在 {TRANSIT_LOCS}")
        seat = _seat_of(from_loc, "from_loc")
        if from_loc == LOC_STATION:
            # 身份全部从座位行读: 声明任何取参都是在给"可以从入参猜身份"开口子
            if payload != PAYLOAD_ITEM:
                raise ValueError(f"物料绑定 {script}: from_loc=station 只搬单件 (payload=item)")
            for key in ("kind_from", "plate_from", "hole_from"):
                if spec.get(key):
                    raise ValueError(
                        f"物料绑定 {script}: from_loc=station 不得声明 {key} —— "
                        "站侧取料脚本没有身份入参, 身份只能从 payload_seat 行读回")
        else:
            if not spec.get("kind_from"):
                raise ValueError(f"物料绑定 {script}: transit_pick 必须声明 kind_from")
            # 从货架取: 库位号即板号, 必须有取参; 从中转取: 板号读账本, 不猜
            if from_loc == LOC_RACK and not spec.get("plate_from"):
                raise ValueError(f"物料绑定 {script}: from_loc=rack 必须声明 plate_from")
            if payload == PAYLOAD_ITEM and not spec.get("hole_from"):
                raise ValueError(f"物料绑定 {script}: payload=item 必须声明 hole_from")
        unknown = set(spec) - {"effect", "carrier", "payload", "kind_from", "from_loc",
                               "plate_from", "hole_from", "seat"}
        if unknown:
            raise ValueError(f"物料绑定 {script}: 未知键 {sorted(unknown)}")
        return {
            "effect": effect,
            "carrier": carrier,
            "payload": payload,
            "kind_from": spec.get("kind_from"),
            "from_loc": from_loc,
            "plate_from": spec.get("plate_from"),
            "hole_from": spec.get("hole_from"),
            "seat": seat,
        }

    to_loc = str(spec.get("to_loc") or "")
    if to_loc not in TRANSIT_LOCS:
        raise ValueError(f"物料绑定 {script}: to_loc {to_loc!r} 不在 {TRANSIT_LOCS}")
    seat = _seat_of(to_loc, "to_loc")
    # 放回货架时 plate_from 只作比对 (板的身份以在途行为准, 入参不一致只告警不迁移 ——
    # 迁移等于猜测板的身份, 与 _do_staging_unload 同一条纪律)
    unknown = set(spec) - {"effect", "carrier", "to_loc", "plate_from", "seat"}
    if unknown:
        raise ValueError(f"物料绑定 {script}: 未知键 {sorted(unknown)}")
    return {
        "effect": effect,
        "carrier": carrier,
        "to_loc": to_loc,
        "plate_from": spec.get("plate_from"),
        "seat": seat,
    }


def load_bindings(path: str | Path, topology: MaterialTopology) -> MaterialBindings:
    """读取物料记账绑定表并做闭集校验 (含与拓扑的交叉校验).

    功能:
        解析 config/material_bindings.yaml 的 bindings (脚本级) 与 actions (动作级) 两段,
        校验 schema 版本、effect/kind/area/magazine/bottle 取值, 以及每种 effect 必需的取参字段.
        magazine/bottle 名按传入的拓扑校验 —— 两个文件的名字必须对得上, 拼错即启动失败.
        任何非法项直接抛错, 不静默忽略 —— 绑定表拼错名字或 effect 会导致静默漏账,
        必须启动即失败.
    参数:
        path: material_bindings.yaml 路径
        topology: 物料拓扑 (提供合法的 magazine / bottle 名集)
    返回:
        MaterialBindings, scripts/actions 两段绑定项
    """
    # 拓扑派生的合法名集; 刻意加 known_ 前缀 —— 动作段里有同名局部变量 bottles
    # (该动作声明的瓶列表), 不加前缀会被遮蔽导致"拿自己校验自己"而永远通过
    known_magazines = topology.magazines
    known_bottles = topology.bottles
    known_payload_seats = topology.payload_seats
    known_seats = topology.seats
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    schema = str(doc.get("schema") or "")
    if schema != _SCHEMA_KEY:
        raise ValueError(f"物料绑定表 schema 应为 {_SCHEMA_KEY}, 实际为 {schema!r}")
    raw = doc.get("bindings") or {}
    if not isinstance(raw, dict):
        raise ValueError("物料绑定表 bindings 段必须是映射")
    raw_actions = doc.get("actions") or {}
    if not isinstance(raw_actions, dict):
        raise ValueError("物料绑定表 actions 段必须是映射")

    scripts: dict[str, dict[str, Any]] = {}
    for script, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"物料绑定 {script}: 绑定项必须是映射")
        effect = str(spec.get("effect") or "")
        if effect not in _EFFECTS:
            raise ValueError(f"物料绑定 {script}: effect {effect!r} 不在 {_EFFECTS}")
        if effect in ("plate_take", "plate_put"):
            # 玻璃板计数: 只需仓号, 不涉及耗材种类与中转区
            magazine = str(spec.get("magazine") or "")
            if magazine not in known_magazines:
                raise ValueError(
                    f"物料绑定 {script}: magazine {magazine!r} 不在 {tuple(known_magazines)}")
            unknown = set(spec) - {"effect", "magazine"}
            if unknown:
                raise ValueError(f"物料绑定 {script}: 未知键 {sorted(unknown)}")
            scripts[str(script)] = {"effect": effect, "magazine": magazine}
            continue
        if effect in ("plate_seat", "plate_stage"):
            scripts[str(script)] = _parse_plate_seat_binding(
                str(script), effect, spec, known_seats)
            continue
        if effect in ("transit_pick", "transit_place"):
            scripts[str(script)] = _parse_transit_binding(
                str(script), spec, effect, known_payload_seats)
            continue
        kind = str(spec.get("kind") or "")
        if kind not in KINDS:
            raise ValueError(f"物料绑定 {script}: kind {kind!r} 不在 {KINDS}")
        area = str(spec.get("area") or "")
        if area not in AREAS:
            raise ValueError(f"物料绑定 {script}: area {area!r} 不在 {tuple(AREAS)}")
        if AREAS[area] != kind:
            raise ValueError(f"物料绑定 {script}: 中转区 {area} 只放 {AREAS[area]}, 声明为 {kind}")
        # 整板转运需要板号取参, 单件消耗/归还需要孔号取参
        if effect in ("staging_load", "staging_unload"):
            if not spec.get("plate_from"):
                raise ValueError(f"物料绑定 {script}: effect {effect} 必须声明 plate_from")
        else:
            if not spec.get("hole_from"):
                raise ValueError(f"物料绑定 {script}: effect {effect} 必须声明 hole_from")
        unknown = set(spec) - {"effect", "kind", "area", "plate_from", "hole_from"}
        if unknown:
            raise ValueError(f"物料绑定 {script}: 未知键 {sorted(unknown)}")
        scripts[str(script)] = {
            "effect": effect,
            "kind": kind,
            "area": area,
            "plate_from": spec.get("plate_from"),
            "hole_from": spec.get("hole_from"),
        }

    actions: dict[str, dict[str, Any]] = {}
    for action, spec in raw_actions.items():
        if not isinstance(spec, dict):
            raise ValueError(f"物料动作绑定 {action}: 绑定项必须是映射")
        effect = str(spec.get("effect") or "")
        if effect not in _ACTION_EFFECTS:
            raise ValueError(f"物料动作绑定 {action}: effect {effect!r} 不在 {_ACTION_EFFECTS}")

        def _seat_accepting(key: str, want_kind: str) -> str:
            """取一个座位键并校验它收的耗材类型; 拼错或类型不符即启动失败.

            与 _do_transit_place 的座位准入约束同源 (同一份拓扑): 拼错座名或绑到只收瓶的
            座上, 表现都是**静默永不记账** —— 那是最难查的一类, 必须在加载期就炸。
            """
            seat = str(spec.get(key) or "")
            if seat not in known_payload_seats:
                raise ValueError(f"物料动作绑定 {action}: {key} {seat!r} 不在 "
                                 f"{tuple(known_payload_seats)}")
            accepts = known_payload_seats[seat][1]
            if accepts != want_kind:
                raise ValueError(f"物料动作绑定 {action}: {key} 必须是只收 {want_kind} 的座, "
                                 f"{seat} 收的是 {accepts!r}")
            return seat

        if effect == "scrape_arm":
            # 取的是**动作 result** 的键而不是入参 —— 体积是 cnc_path 算出来的, 它的
            # params 里没有这个东西。这也是它逃出 test_bindings_match_catalog 那道
            # "取参名必须在动作目录里"核对的原因, 替代看门狗是
            # test_scrape_arm_keys_exist_in_action_result。
            if not spec.get("volume_from_result"):
                raise ValueError(f"物料动作绑定 {action}: scrape_arm 必须声明 volume_from_result")
            unknown = set(spec) - {"effect", "volume_from_result",
                                   "area_from_result", "source_from_result"}
            if unknown:
                raise ValueError(f"物料动作绑定 {action}: 未知键 {sorted(unknown)}")
            actions[str(action)] = {
                "effect": effect,
                "volume_from_result": str(spec["volume_from_result"]),
                "area_from_result": spec.get("area_from_result"),
                "source_from_result": spec.get("source_from_result"),
            }
            continue

        if effect == "powder_fill":
            seat = _seat_accepting("seat", "collector")
            unknown = set(spec) - {"effect", "seat"}
            if unknown:
                raise ValueError(f"物料动作绑定 {action}: 未知键 {sorted(unknown)}")
            actions[str(action)] = {"effect": effect, "seat": seat}
            continue

        if not spec.get("volume_from"):
            raise ValueError(f"物料动作绑定 {action}: liquid_draw 必须声明 volume_from")
        bottles = spec.get("bottles") or []
        if not isinstance(bottles, list) or not bottles:
            raise ValueError(f"物料动作绑定 {action}: bottles 必须是非空列表")
        for bottle in bottles:
            if bottle not in known_bottles:
                raise ValueError(
                    f"物料动作绑定 {action}: bottle {bottle!r} 不在 {tuple(known_bottles)}")
        ratio_from = spec.get("ratio_from") or []
        if ratio_from and not isinstance(ratio_from, list):
            raise ValueError(f"物料动作绑定 {action}: ratio_from 必须是列表")
        if ratio_from and len(ratio_from) != len(bottles):
            raise ValueError(
                f"物料动作绑定 {action}: ratio_from ({len(ratio_from)}) 与 bottles "
                f"({len(bottles)}) 长度必须一致 (同序位对应)")
        unknown = set(spec) - {"effect", "volume_from", "count_from", "ratio_from", "bottles",
                               "to_seat", "wet_seat"}
        if unknown:
            raise ValueError(f"物料动作绑定 {action}: 未知键 {sorted(unknown)}")
        # 可选下半段: 抽出来的液体落进 to_seat 那只瓶, 并把 wet_seat 那只粉桶标"已淋洗"。
        # 抽与注是同一次转移的两头, 故做成 liquid_draw 的可选字段而不是第二条绑定 ——
        # YAML 一个 key 只能有一条绑定, collect.collect 这个名字已经被占了。
        # develop.fill / develop.rinse_fill 不写这两个字段 => 行为完全不变(零回归)。
        to_seat = _seat_accepting("to_seat", "bottle") if spec.get("to_seat") else None
        wet_seat = _seat_accepting("wet_seat", "collector") if spec.get("wet_seat") else None
        actions[str(action)] = {
            "effect": effect,
            "volume_from": spec["volume_from"],
            "count_from": spec.get("count_from"),
            "ratio_from": [str(r) for r in ratio_from],
            "bottles": [str(b) for b in bottles],
            "to_seat": to_seat,
            "wet_seat": wet_seat,
        }

    return MaterialBindings(scripts=scripts, actions=actions)


class MaterialStore:
    """物料账本的 SQLite 存储, 兼 VM 事件接收器."""

    def __init__(self, db_path: str | Path = ":memory:", *, topology: MaterialTopology,
                 bindings: Optional[MaterialBindings] = None) -> None:
        """打开 (或创建) 物料账本库并按拓扑播种四类物料.

        参数:
            db_path: SQLite 文件路径; ":memory:" 用于离线测试
            topology: 物料拓扑 (load_topology 的返回) —— 板仓/溶剂瓶/位置与传感器的唯一真源
            bindings: 记账绑定表 (load_bindings 的返回); None 表示不记账, 只做查询与人工盘点
        返回:
            None
        """
        self._path = str(db_path)
        self._topology = topology
        self._magazines = topology.magazines
        self._bottles = topology.bottles
        self._seats = topology.seats
        self._payload_seats = topology.payload_seats
        self._bindings = bindings or MaterialBindings()
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 已进入但未结清的记账节点: (run_id, 所属脚本名, aid) -> (绑定项, 入参)
        # 键必须含脚本名 —— 一个脚本帧内的 AID 不是全局唯一 (operation/vm/thread.py:71-73)
        self._pending: dict[tuple[str, str, str], tuple[dict[str, Any], dict]] = {}
        # 本次运行的根入参 (取 sample_id 用); 由 operation_start 的 inputs 提供
        self._run_inputs: dict[str, dict] = {}
        # 刮取产粉量的两段暂存: cnc_path 算量 (scrape_arm) -> scrape_finish 翻料倒粉时落账
        # (powder_fill)。与 _pending / _run_inputs 同为纯内存态: 两步之间重启后端就丢, 那时
        # powder_fill 只留一条"本次运行没有 armed 的刮取量"的流水, 不编造 —— 与账本
        # "宁可不记不可猜"同一条纪律。
        # **后到覆盖不累加**: cnc_path 在一次运行里可能跑好几遍 (候选/重画/占位, 见
        # config/operation/03_photoscrape/photoscrape_process.yaml 的多处调用), 而真正下发
        # PLC 的是最后一次赋给 cnc 变量的那一份, 于是"最后一次 arm 有效"与 write_cnc_path
        # 消费的那一份天然一致。
        self._scrape_armed: dict[str, dict[str, Any]] = {}
        # 进程纪元: 用来区分"本进程记下的在途/座位"与"上一个进程遗留的"。
        #
        # 为什么需要它: _pending 与 _run_inputs 是纯内存态, 后端在搬运半途重启就没了,
        # 于是放料的 vm_node_done 配不上对、在途行永远清不掉, 三维会把物料焊在机械臂上。
        # 账本本身是持久的(这点核查过, 全部走 SQLite 且每个写路径显式 commit), 缺的只是
        # "这行是谁记的"这一位信息。
        #
        # 刻意**不**与 runs.db 的活跃运行比对: 那边有 max_runs LRU 淘汰(run_store._prune_locked),
        # 老运行被淘汰后判据会从"陈旧"翻成"查无此运行", 语义不稳; 且 run_id 可以是空串
        # (人工/面板路径写的行没有运行号)。为一个标记去耦合两个刻意分开的库, 代价不对等。
        #
        # 取"时间戳-pid-序号"而不是随机串: 人在物料页/流水里看到它时能直接对上是哪次启动。
        # 序号不是画蛇添足 —— 判据的准确说法是"这行是不是**正在回答的这个 store 实例**记的",
        # 而同一进程同一秒里可以有第二个实例 (测试如此, 生产上若有人另开一个 store 读同一个
        # 库文件也如此)。少了它, 那种情形下陈旧行会被误判成可信, 而这正是本机制要防的事。
        self._epoch = f"{int(time.time())}-{os.getpid()}-{next(_EPOCH_SEQ)}"
        # 板仓账面被"外部权威"改写时的观察者; 缺省 None = 真实侧行为逐字不变。
        # 唯一使用者是仿真沙盒 (把账面回灌板堆物理模型), 见 set_magazine_observer。
        self._magazine_observer = None
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS material_cells (
                    kind       TEXT    NOT NULL,
                    plate      INTEGER NOT NULL,
                    hole       INTEGER NOT NULL,
                    state      TEXT    NOT NULL,
                    sample_id  TEXT    NOT NULL DEFAULT '',
                    updated_at REAL    NOT NULL,
                    run_id     TEXT    NOT NULL DEFAULT '',
                    -- ── 单件内容物余量 (2026-08 新增) ──────────────────────────────
                    -- 三列共表而不拆两张: 主键相同、生命周期相同 (consume 归零 / fill 打样品号)、
                    -- grid() 一次查询就出。代价是每种 kind 有一列恒为 0 —— 那不是漏记:
                    --   collector 用 powder_mm3 + eluted;  bottle 用 liquid_ml。
                    --
                    -- ⚠ 三列**刻意不加 CHECK**: ALTER TABLE ADD COLUMN 不重扫已有行, CHECK 只对
                    --   之后的写生效 —— 加了会变成"全新库拒负数、迁移库接受负数"两套行为。
                    --   既然本 store 一贯"只报不裁决"(_draw_bottle 扣到 0 只告警), 就统一在
                    --   Python 侧夹紧 (_do_cell_add / set_cell_amount 各一道 math.isfinite),
                    --   两条路完全一致。
                    powder_mm3 REAL    NOT NULL DEFAULT 0,  -- 粉桶里累计的硅胶粉体积 (mm³)
                    liquid_ml  REAL    NOT NULL DEFAULT 0,  -- 样品瓶里累计的淋洗液 (mL)
                    eluted     INTEGER NOT NULL DEFAULT 0,  -- 粉桶是否已被洗脱液淋过 (三维粉末变色的依据)
                    -- ⚠ state **刻意不加 CHECK** (2026-08-15 起): 三态枚举 STATES 由写入口
                    --   mark() 把关。SQLite 的 CHECK 改不了只能重建表 —— 二态时代的旧约束
                    --   挡住新增的 ABSENT, 正是 _migrate_state_check_locked 要拆的东西;
                    --   同一个坑不留给下一个状态。
                    PRIMARY KEY (kind, plate, hole),
                    CHECK (plate BETWEEN 1 AND 6),
                    CHECK (hole BETWEEN 1 AND 6)
                );
                CREATE TABLE IF NOT EXISTS staging_occupancy (
                    area     TEXT    PRIMARY KEY,
                    kind     TEXT    NOT NULL,
                    plate    INTEGER,
                    since_at REAL    NOT NULL,
                    run_id   TEXT    NOT NULL DEFAULT ''
                );
                -- 货架库位板级在架人工账 (1=在架; 0=正在中转/在夹爪上/人工标无板)。
                -- 不变量: 板在中转或在爪上 <=> 其库位 present=0, 由 _shift_staging_locked
                -- 与 _do_transit_pick / _do_transit_place 共同维护。
                CREATE TABLE IF NOT EXISTS rack_occupancy (
                    kind       TEXT    NOT NULL,
                    plate      INTEGER NOT NULL,
                    present    INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL    NOT NULL,
                    run_id     TEXT    NOT NULL DEFAULT '',
                    PRIMARY KEY (kind, plate),
                    CHECK (kind IN ('collector', 'bottle')),
                    CHECK (plate BETWEEN 1 AND 6),
                    CHECK (present IN (0, 1))
                );
                -- 在途载荷: 载荷此刻在哪把夹爪上。carrier 作主键 => 一把爪最多一件,
                -- 互斥由主键保证, 不需要额外的并发防护。
                -- payload=tray 时 hole 为 NULL; to_loc 在落位前是空串 (取的时候还不知道去哪)。
                CREATE TABLE IF NOT EXISTS payload_transit (
                    carrier  TEXT PRIMARY KEY,
                    payload  TEXT    NOT NULL,
                    kind     TEXT    NOT NULL,
                    plate    INTEGER NOT NULL,
                    hole     INTEGER,
                    from_loc TEXT    NOT NULL,
                    to_loc   TEXT    NOT NULL DEFAULT '',
                    since_at REAL    NOT NULL,
                    run_id   TEXT    NOT NULL DEFAULT '',
                    script   TEXT    NOT NULL DEFAULT '',
                    CHECK (carrier IN ('gripper_plate96', 'gripper_vial')),
                    CHECK (payload IN ('tray', 'item')),
                    CHECK (kind IN ('collector', 'bottle')),
                    CHECK (plate BETWEEN 1 AND 6),
                    CHECK (hole IS NULL OR hole BETWEEN 1 AND 6)
                );
                -- 单件耗材停在工位夹具上 (刮板夹具 / 收集工位)。seat 作主键 => 一个座最多
                -- 一件, 互斥由主键保证。座名不写死进 CHECK, 由拓扑约束 (绑定表加载期校验)。
                -- **不播种** —— 座位空着就是没有行, 空表是正确初值。
                --
                -- 它与 payload_transit 的分工是本次改动的全部要点: 在途是**易失态**
                -- (只在爪上那几秒有效, 进程一死就无人能确认), 座位是**耐久态**
                -- (瓶子停在收集工位上, 后端重启它不会自己跑掉)。放件时把前者换成后者,
                -- 于是崩溃后需要猜的东西少了一大半。epoch 在两张表上的语义因此刻意不同,
                -- 见 _stale_of 的注释。
                CREATE TABLE IF NOT EXISTS payload_seat (
                    seat     TEXT PRIMARY KEY,
                    payload  TEXT    NOT NULL,
                    kind     TEXT    NOT NULL,
                    plate    INTEGER NOT NULL,
                    hole     INTEGER,
                    since_at REAL    NOT NULL,
                    run_id   TEXT    NOT NULL DEFAULT '',
                    script   TEXT    NOT NULL DEFAULT '',
                    epoch    TEXT    NOT NULL DEFAULT '',
                    CHECK (payload IN ('tray', 'item')),
                    CHECK (kind IN ('collector', 'bottle')),
                    CHECK (plate BETWEEN 1 AND 6),
                    CHECK (hole IS NULL OR hole BETWEEN 1 AND 6)
                );
                CREATE TABLE IF NOT EXISTS location_presence (
                    location_id TEXT    PRIMARY KEY,
                    raw_bit     INTEGER NOT NULL,
                    present     INTEGER NOT NULL,
                    checked_at  REAL    NOT NULL,
                    CHECK (raw_bit IN (0, 1)),
                    CHECK (present IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS plate_magazines (
                    magazine   TEXT    PRIMARY KEY,
                    count      INTEGER NOT NULL,
                    capacity   INTEGER NOT NULL,
                    updated_at REAL    NOT NULL,
                    run_id     TEXT    NOT NULL DEFAULT '',
                    CHECK (count >= 0)
                );
                CREATE TABLE IF NOT EXISTS liquid_bottles (
                    bottle      TEXT    PRIMARY KEY,
                    label       TEXT    NOT NULL,
                    volume_ml   REAL    NOT NULL,
                    capacity_ml REAL    NOT NULL,
                    updated_at  REAL    NOT NULL,
                    run_id      TEXT    NOT NULL DEFAULT '',
                    CHECK (volume_ml >= 0)
                );
                -- 单板停放位有板/无板人工账 (点样座/刮板拍照台): 无在位传感器, 只能人工记。
                -- 座名不写死进 CHECK, 由拓扑约束 (seed 只播种拓扑里的座, set_seat_presence
                -- 只认拓扑里的座)。⚠ 只供展示与人工同步, 不参与任何流程判断。
                CREATE TABLE IF NOT EXISTS seat_occupancy (
                    seat       TEXT    PRIMARY KEY,
                    present    INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL    NOT NULL,
                    CHECK (present IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS material_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         REAL NOT NULL,
                    run_id     TEXT NOT NULL DEFAULT '',
                    script     TEXT NOT NULL DEFAULT '',
                    effect     TEXT NOT NULL,
                    kind       TEXT NOT NULL DEFAULT '',
                    plate      INTEGER,
                    hole       INTEGER,
                    from_state TEXT NOT NULL DEFAULT '',
                    to_state   TEXT NOT NULL DEFAULT '',
                    detail     TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_material_events_cell
                    ON material_events(kind, plate, hole, id);
                -- 并行预留账 (多样品并行时 plan 与 consume 之间出现并发者, 单运行时代的
                -- "刻意不做预留"前提失效): plate/hole 为 NULL 即计数级 (批次准入占坑),
                -- 非 NULL 即孔级 (plan_staging 选定具体孔后升级)。consume 落账即清行。
                CREATE TABLE IF NOT EXISTS material_reservations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind       TEXT NOT NULL,
                    plate      INTEGER,
                    hole       INTEGER,
                    sample_id  TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    CHECK (kind IN ('collector', 'bottle')),
                    CHECK (sample_id <> '')
                );
                CREATE INDEX IF NOT EXISTS idx_material_res_cell
                    ON material_reservations(kind, plate, hole);
                CREATE INDEX IF NOT EXISTS idx_material_res_sample
                    ON material_reservations(sample_id, kind);
                """
            )
            # CREATE TABLE IF NOT EXISTS 不会给**已有**表补列, 而 var/materials.db 是真账本
            # (盘点结果都在里面), 只能原地迁移不能重建。ADD COLUMN ... DEFAULT '' 在 SQLite
            # 里只改 schema 行不重写数据行, 对现有库是安全的; 旧行拿到 '' 而 '' 永远不等于
            # 本进程的 epoch, 于是**自动判为上一进程遗留**, 语义恰好正确。
            self._ensure_column_locked("payload_transit", "epoch", "TEXT NOT NULL DEFAULT ''")
            # 单件内容物余量三列 (2026-08 新增)。旧行拿到 0 —— 语义恰好正确: 账本对"这只桶里
            # 已经有多少粉"从来无权威, 0 就是"没记过", 由人在物料页覆盖式录入
            # (POST /api/materials/cell_amount), 与 _seed 里"新格初值 USED"同一条准则。
            self._ensure_column_locked("material_cells", "powder_mm3", "REAL NOT NULL DEFAULT 0")
            self._ensure_column_locked("material_cells", "liquid_ml", "REAL NOT NULL DEFAULT 0")
            self._ensure_column_locked("material_cells", "eluted", "INTEGER NOT NULL DEFAULT 0")
            # 板位的工艺阶段 (blank/spotted/developed/scraped)。**刻意不加 CHECK**:
            # 与上面三列同理 —— ALTER TABLE ADD COLUMN 不重扫已有行, 加了也管不住旧行,
            # 合法值由 set_seat_stage 在写入口把关。
            self._ensure_column_locked("seat_occupancy", "stage",
                                       f"TEXT NOT NULL DEFAULT '{PLATE_STAGE_BLANK}'")
            # 二态时代的 state CHECK 挡住 ABSENT, 只能重建表拆掉 (放在补列之后:
            # 老库先补齐三列, 重建时按显式列清单搬运才不缺列)
            self._migrate_state_check_locked()
            self._conn.commit()
        self._seed()

    def _migrate_state_check_locked(self) -> None:
        """拆掉 material_cells 上二态时代的 state CHECK; 须在已持锁的上下文调用.

        var/materials.db 是真账本只能原地迁移, 而 SQLite 改不了 CHECK —— 唯一途径是
        重建表逐行搬运。幂等: 只有旧 DDL 里还写着 state IN ('FRESH', 'USED') 才动手,
        新库(建表语句已无该约束)与迁移过的库直接跳过。

        参数:
            无
        返回:
            None
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'material_cells'"
        ).fetchone()
        if row is None or "state IN ('FRESH', 'USED')" not in (row["sql"] or ""):
            return
        log.info("[物料] material_cells 带二态 state CHECK, 重建表以放行三态枚举")
        self._conn.executescript(
            """
            ALTER TABLE material_cells RENAME TO material_cells_legacy;
            CREATE TABLE material_cells (
                kind       TEXT    NOT NULL,
                plate      INTEGER NOT NULL,
                hole       INTEGER NOT NULL,
                state      TEXT    NOT NULL,
                sample_id  TEXT    NOT NULL DEFAULT '',
                updated_at REAL    NOT NULL,
                run_id     TEXT    NOT NULL DEFAULT '',
                powder_mm3 REAL    NOT NULL DEFAULT 0,
                liquid_ml  REAL    NOT NULL DEFAULT 0,
                eluted     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, plate, hole),
                CHECK (plate BETWEEN 1 AND 6),
                CHECK (hole BETWEEN 1 AND 6)
            );
            INSERT INTO material_cells
                SELECT kind, plate, hole, state, sample_id, updated_at, run_id,
                       powder_mm3, liquid_ml, eluted
                FROM material_cells_legacy;
            DROP TABLE material_cells_legacy;
            """
        )

    def _ensure_column_locked(self, table: str, name: str, decl: str) -> None:
        """幂等地给已有表补一列; 须在已持锁的上下文调用.

        参数:
            table: 表名; name: 列名; decl: 列声明 (类型 + 约束, 须自带 DEFAULT)
        返回:
            None
        """
        existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        if name not in existing:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _seed(self) -> None:
        """播种 72 格与两个中转区行; 已存在的行一律不覆盖 (幂等, 保住盘点结果).

        新格初值为 USED (空孔) 而非 FRESH: 账本无权威, 谎称有货只会给出错误建议;
        实际装了多少由实验员在物料页盘点录入.
        """
        now = time.time()
        with self._lock:
            for kind in KINDS:
                for plate in range(1, PLATES_PER_KIND + 1):
                    for hole in range(1, HOLES_PER_PLATE + 1):
                        self._conn.execute(
                            "INSERT OR IGNORE INTO material_cells"
                            "(kind, plate, hole, state, sample_id, updated_at, run_id)"
                            " VALUES (?, ?, ?, ?, '', ?, '')",
                            (kind, plate, hole, STATE_USED, now),
                        )
            for area, kind in AREAS.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO staging_occupancy"
                    "(area, kind, plate, since_at, run_id) VALUES (?, ?, NULL, ?, '')",
                    (area, kind, now),
                )
            # 货架在架账 (板级人工账): 初值 = 在架; 建行时正在中转的板置 0 —— 与旧推导语义
            # ("不是中转板就在架上") 一致的迁移, 旧库升级不会把中转里的板错记成在架。
            # 依赖上面 staging_occupancy 先播种/已存在 (读其现值定初值), 顺序不可换。
            staged_now = {row["kind"]: row["plate"] for row in self._conn.execute(
                "SELECT kind, plate FROM staging_occupancy").fetchall()}
            for kind in KINDS:
                for plate in range(1, PLATES_PER_KIND + 1):
                    self._conn.execute(
                        "INSERT OR IGNORE INTO rack_occupancy"
                        "(kind, plate, present, updated_at, run_id) VALUES (?, ?, ?, ?, '')",
                        (kind, plate, 0 if staged_now.get(kind) == plate else 1, now),
                    )
            # 玻璃板仓与溶剂瓶同样初值为空: 账本无权威, 实装多少靠盘点录入
            for magazine, (_label, capacity) in self._magazines.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO plate_magazines"
                    "(magazine, count, capacity, updated_at, run_id) VALUES (?, 0, ?, ?, '')",
                    (magazine, capacity, now),
                )
            for bottle, (label, capacity) in self._bottles.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO liquid_bottles"
                    "(bottle, label, volume_ml, capacity_ml, updated_at, run_id)"
                    " VALUES (?, ?, 0.0, ?, ?, '')",
                    (bottle, label, capacity, now),
                )
            # 单板停放位初值 0 (无板): 同上一准则 —— 账本无权威, 谎称有板只会误导取放
            for seat in self._seats:
                self._conn.execute(
                    "INSERT OR IGNORE INTO seat_occupancy(seat, present, updated_at)"
                    " VALUES (?, 0, ?)",
                    (seat, now),
                )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 写入 (作为引擎 event_sink 之一)
    # ------------------------------------------------------------------

    def on_event(self, event: dict) -> None:
        """消费一条 VM 事件, 在绑定脚本成功结束时记账.

        功能:
            operation_start 记住根入参 (并为根脚本自身的绑定挂一笔待结清);
            vm_node_enter 对 run_script 节点按被调脚本名查绑定表并暂存入参;
            vm_node_done 仅在 status=DONE 时提交; operation_done/failed 结清根脚本并清理残留.
        参数:
            event: VM 事件字典 (类型见 operation/vm/thread.py 的 _emit_*)
        返回:
            None
        """
        if not self._bindings:
            return
        event_type = str(event.get("type") or "")
        run_id = str(event.get("run_id") or "")
        if not run_id:
            return

        if event_type == "operation_start":
            inputs = dict(event.get("inputs") or {})
            self._run_inputs[run_id] = inputs
            # 根脚本没有 run_script 节点包裹 (面板直跑 transfer_*/feedlift_*_cycle 就是这种形态),
            # 其终态由 operation_done/failed 给出, 故用空脚本名与空 aid 作占位键
            binding = self._bindings.scripts.get(str(event.get("operation") or ""))
            if binding is not None:
                self._pending[(run_id, "", "")] = (binding, inputs)
            return

        if event_type == "vm_node_enter":
            op = str(event.get("op") or "")
            # _node_ref 把被调脚本名 (run_script) 或动作名 (call) 都放在 action 字段
            name = str(event.get("action") or "")
            if op == "run_script":
                binding = self._bindings.scripts.get(name)
            elif op == "call":
                binding = self._bindings.actions.get(name)
            else:
                return
            if binding is None:
                return
            key = (run_id, str(event.get("script") or ""), str(event.get("aid") or ""))
            self._pending[key] = (binding, dict(event.get("args") or {}))
            return

        if event_type == "vm_node_done":
            key = (run_id, str(event.get("script") or ""), str(event.get("aid") or ""))
            pending = self._pending.pop(key, None)
            if pending is None:
                return
            if str(event.get("status") or "") != "DONE":
                return      # CANCELLED / ERROR / 被拒: 物料未移动, 不入账
            # result 一并传下去: cnc_path 算出的刮取体积只在动作 result 里 (入参没有它),
            # 而 vm_node_done 早就带着 result 了 (operation/vm/thread.py 的 _emit), 此前
            # 只是没人去读。
            self._commit(run_id, str(event.get("action") or ""), pending[0], pending[1],
                         event.get("ts"), result=dict(event.get("result") or {}))
            return

        if event_type == "step_done":
            # 维护面板单发动作 (POST /api/actions/{name}/run) 的合成事件路径。
            # 它绕过 VM 与资源门 (api/app.py 的 _execute_with_live_events), 只发
            # operation_start + step_start/step_done, 不发任何 vm_node_*, 故与上面的
            # VM 分支**互斥**, 不存在重复扣账 (test_material_wired_offline 有回归钉住)。
            # 只查动作段: manual_service 的气缸/点动也发 step_*, 但那些动作名不在绑定表里。
            # step_done 自带 params (api/app.py 为三维展缸液面补的), 无需 enter->done 配对。
            if str(event.get("status") or "") != "DONE":
                return
            action = str(event.get("action") or "")
            binding = self._bindings.actions.get(action)
            if binding is None:
                return
            self._commit(run_id, action, binding, dict(event.get("params") or {}),
                         event.get("ts"), source="面板单发",
                         result=dict(event.get("result") or {}))
            return

        if event_type in ("operation_done", "operation_failed"):
            root = str(event.get("operation") or "")
            pending = self._pending.pop((run_id, "", ""), None)
            if pending is not None and event_type == "operation_done":
                self._commit(run_id, root, pending[0], pending[1], event.get("ts"))
            # 清理本次运行残留 (异常路径可能留下未结清的进入记录)
            self._run_inputs.pop(run_id, None)
            self._scrape_armed.pop(run_id, None)
            for key in [k for k in self._pending if k[0] == run_id]:
                self._pending.pop(key)
            return

    def _commit(self, run_id: str, script: str, binding: dict[str, Any],
                args: dict, ts: Any, *, source: str = "",
                result: Optional[dict] = None) -> None:
        """按绑定项把一次成功调用落成物料事实.

        参数:
            run_id: 运行号; script: 触发脚本名; binding: 绑定项; args: 该次调用入参
            ts: 事件时刻 (epoch 秒); None 时取当前时间
            source: 触发来源备注 (如 "面板单发"), 写进流水 detail 供人辨认与撤销
            result: 该次调用的动作返回值; 只有 scrape_arm 用它 (量在 result 不在入参)
        返回:
            None
        """
        now = float(ts) if ts is not None else time.time()
        effect = binding["effect"]
        try:
            if effect == "plate_take":
                self._do_plate(run_id, script, binding["magazine"], -1, now)
                return
            if effect == "plate_put":
                self._do_plate(run_id, script, binding["magazine"], +1, now)
                return
            if effect in ("plate_seat", "plate_stage"):
                self._do_plate_seat(run_id, script, binding, args)
                return
            if effect == "liquid_draw":
                self._do_liquid_draw(run_id, script, binding, args, now, source=source)
                return
            if effect == "transit_pick":
                self._do_transit_pick(run_id, script, binding, args, now)
                return
            if effect == "transit_place":
                self._do_transit_place(run_id, script, binding, args, now)
                return
            # ⚠ 动作级 effect 必须在这里 return —— 它们的绑定项没有 kind/area 键,
            #   掉到下面那行 binding["kind"] 就是 KeyError (liquid_draw 早退同理)。
            if effect == "scrape_arm":
                self._do_scrape_arm(run_id, script, binding, result or {}, now)
                return
            if effect == "powder_fill":
                self._do_powder_fill(run_id, script, binding, now, source=source)
                return
        except Exception:
            log.exception("[物料] 记账失败: script=%s effect=%s args=%s", script, effect, args)
            return
        kind = binding["kind"]
        area = binding["area"]
        try:
            if effect == "staging_load":
                self._do_staging_load(run_id, script, kind, area,
                                      self._arg_int(args, binding["plate_from"]), now)
            elif effect == "staging_unload":
                self._do_staging_unload(run_id, script, kind, area,
                                        self._arg_int(args, binding["plate_from"]), now)
            elif effect == "consume":
                self._do_consume(run_id, script, kind, area,
                                 self._arg_int(args, binding["hole_from"]), now)
            elif effect == "fill":
                sample_id = str(self._run_inputs.get(run_id, {}).get("sample_id") or "")
                self._do_fill(run_id, script, kind, area,
                              self._arg_int(args, binding["hole_from"]), sample_id, now)
        except Exception:
            # sink 契约为 best-effort (runtime/events.py:31): 记账失败不得影响推流与其它接收器
            log.exception("[物料] 记账失败: script=%s effect=%s args=%s", script, effect, args)

    @staticmethod
    def _arg_int(args: dict, name: Optional[str]) -> Optional[int]:
        """从调用入参取整数索引; 缺失或非法返回 None (由各 effect 自行告警)."""
        if not name or name not in args:
            return None
        try:
            return int(args[name])
        except (TypeError, ValueError):
            return None

    def _do_staging_load(self, run_id: str, script: str, kind: str, area: str,
                         plate: Optional[int], now: float) -> None:
        """整板从货架库位进中转区: 覆盖该中转区占用."""
        if plate is None or not 1 <= plate <= PLATES_PER_KIND:
            self._log_event(now, run_id, script, "staging_load", kind, None, None,
                            detail=f"板号取参非法 ({plate}), 未更新中转占用")
            log.warning("[物料] %s: 板号取参非法 (%s), 未更新 %s 占用", script, plate, area)
            return
        with self._lock:
            prev = self._shift_staging_locked(area, kind, plate, now, run_id)
            self._conn.commit()
        if prev == plate:
            # 叶子层的 transit_place 已把这块板落到位, 本层只是流程收口 —— 不是"覆盖".
            # 少了这一支, 每次正常转运都会误报一条"账实可能已失同步"的告警。
            detail = "与在途落位一致 (叶子层已落账)"
        elif prev is not None:
            detail = f"覆盖原占用板 {prev} (账实可能已失同步)"
            log.warning("[物料] %s 载入板 %s 前账本记为板 %s, 已覆盖", area, plate, prev)
        else:
            detail = ""
        self._log_event(now, run_id, script, "staging_load", kind, plate, None, detail=detail)

    def _do_staging_unload(self, run_id: str, script: str, kind: str, area: str,
                           plate: Optional[int], now: float) -> None:
        """整板从中转区回货架库位: 清空占用, 并比对是否回到载入时的库位.

        库位不一致时只告警留痕, 不迁移 72 格内容 —— 迁移等于猜测板的身份.
        """
        # rack 回架按 loaded (载入时的板) 记; plate 入参只作下方告警比对, 不迁移不猜测
        with self._lock:
            loaded = self._shift_staging_locked(area, kind, None, now, run_id)
            rack_row = None if plate is None else self._conn.execute(
                "SELECT present FROM rack_occupancy WHERE kind = ? AND plate = ?",
                (kind, plate)).fetchone()
            back_on_rack = rack_row is not None and bool(rack_row["present"])
            self._conn.commit()
        if loaded is None and back_on_rack:
            # 叶子层的 transit_pick 已清空中转位、transit_place 已把板记回架, 本层是收口。
            # 判据用"目标库位已在架"而不是时间戳: 状态本身就是证据, 不需要额外记账。
            detail = "与在途收口一致 (叶子层已落账)"
        elif loaded is None:
            detail = f"账本原记 {area} 为空却执行卸载 (回库位 {plate}), 账实已失同步"
            log.warning("[物料] %s", detail)
        elif plate is not None and plate != loaded:
            detail = f"库位不一致: 载入自板 {loaded}, 卸出至库位 {plate}; 未迁移孔位账本, 请盘点"
            log.warning("[物料] %s", detail)
        else:
            detail = ""
        self._log_event(now, run_id, script, "staging_unload", kind, loaded, None, detail=detail)

    def _shift_staging_locked(self, area: str, kind: str, new_plate: Optional[int],
                              now: float, run_id: str) -> Optional[int]:
        """写中转占用并同步维护货架在架账不变量 (板在中转 <=> 其库位 present=0).

        ⚠ 须在已持有 self._lock 的上下文调用 (锁非可重入), 提交由调用方统一做。
        旧板离开中转即记回架 —— 与旧推导语义一致的保守选择; 板被整个拿走的场景
        由人在物料页再标"无板" (set_rack_presence)。
        返回原占用板号 (调用方用于告警文案)。
        """
        row = self._conn.execute(
            "SELECT plate FROM staging_occupancy WHERE area = ?", (area,)).fetchone()
        prev = row["plate"] if row is not None else None
        self._conn.execute(
            "UPDATE staging_occupancy SET plate = ?, since_at = ?, run_id = ? WHERE area = ?",
            (new_plate, now, run_id, area),
        )
        if prev is not None and prev != new_plate:
            self._conn.execute(
                "UPDATE rack_occupancy SET present = 1, updated_at = ?, run_id = ?"
                " WHERE kind = ? AND plate = ?", (now, run_id, kind, prev))
        if new_plate is not None:
            self._conn.execute(
                "UPDATE rack_occupancy SET present = 0, updated_at = ?, run_id = ?"
                " WHERE kind = ? AND plate = ?", (now, run_id, kind, new_plate))
        return prev

    # ------------------------------------------------------------------
    # 在途 (载荷此刻在哪把夹爪上)
    # ------------------------------------------------------------------

    @staticmethod
    def _area_of_kind(kind: str) -> str:
        """按耗材种类反查中转区 (AREAS 的反查; 一种耗材恰好对应一个区)."""
        return next(area for area, k in AREAS.items() if k == kind)

    def _do_transit_pick(self, run_id: str, script: str, binding: dict[str, Any],
                         args: dict, now: float) -> None:
        """载荷离开原位进夹爪: 写在途行, 并把源位标空.

        源位标空是必须的 —— 否则账本会同时说"板在货架"和"板在爪上", 三维照着画就是两块板。
        从中转取整板时刻意**不**碰 rack_occupancy.present: 板去了爪上而不是回架,
        present 必须继续保持 0 (这正是 _shift_staging_locked 不能直接复用的原因)。
        """
        carrier = binding["carrier"]
        payload = binding["payload"]
        from_loc = binding["from_loc"]
        if from_loc == LOC_STATION:
            # 站侧取件走单独一条路: 身份从座位行读回, 与"从入参取"是两种不同的事,
            # 混在一个函数里会让"没有入参时该怎么办"变成一串隐式短路
            self._do_transit_pick_station(run_id, script, binding, now)
            return
        kind = str(args.get(binding["kind_from"]) or "")
        if kind not in KINDS:
            detail = f"耗材种类取参非法 ({kind!r} 自 {binding['kind_from']}), 未记在途"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "transit_pick", "", None, None, detail=detail)
            return
        area = self._area_of_kind(kind)
        hole = self._arg_int(args, binding["hole_from"]) if payload == PAYLOAD_ITEM else None
        if payload == PAYLOAD_ITEM and (hole is None or not 1 <= hole <= HOLES_PER_PLATE):
            detail = f"孔号取参非法 ({hole}), 未记在途"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "transit_pick", kind, None, None, detail=detail)
            return

        # 定板号与写入必须在**同一个**临界区: 从中转取板时板号是现读账本的,
        # 中间放锁会留一个 TOCTOU 窗口。
        # ⚠ 锁非可重入, 而 _log_event 自取锁 —— 一切留痕都必须在 with 块**之后**做,
        #   在块内直接调 _log_event 会死锁 (且表现为整个进程静默挂起, 不报错)。
        bad = ""
        prev = None
        with self._lock:
            if from_loc == LOC_RACK:
                plate = self._arg_int(args, binding["plate_from"])   # 货架库位号即板号
            else:
                row = self._conn.execute(
                    "SELECT plate FROM staging_occupancy WHERE area = ?", (area,)).fetchone()
                plate = row["plate"] if row is not None else None
            if plate is None or not 1 <= plate <= PLATES_PER_KIND:
                bad = (f"板号取参非法 ({plate})" if from_loc == LOC_RACK
                       else f"账本记 {area} 为空却从中转取板")
            else:
                prev = self._conn.execute(
                    "SELECT payload, kind, plate, hole FROM payload_transit WHERE carrier = ?",
                    (carrier,)).fetchone()
                self._conn.execute(
                    "INSERT OR REPLACE INTO payload_transit(carrier, payload, kind, plate,"
                    " hole, from_loc, to_loc, since_at, run_id, script, epoch)"
                    " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)",
                    (carrier, payload, kind, plate, hole, from_loc, now, run_id, script,
                     self._epoch),
                )
                if payload == PAYLOAD_TRAY:
                    if from_loc == LOC_RACK:
                        self._conn.execute(
                            "UPDATE rack_occupancy SET present = 0, updated_at = ?, run_id = ?"
                            " WHERE kind = ? AND plate = ?", (now, run_id, kind, plate))
                    else:
                        self._conn.execute(
                            "UPDATE staging_occupancy SET plate = NULL, since_at = ?, run_id = ?"
                            " WHERE area = ?", (now, run_id, area))
                self._conn.commit()

        if bad:
            log.warning("[物料] %s: %s, 未记在途", script, bad)
            self._log_event(now, run_id, script, "transit_pick", kind, None, hole,
                            detail=f"{bad}, 未记在途")
            return

        where = "货架库位" if from_loc == LOC_RACK else area
        target = f"板{plate}" if payload == PAYLOAD_TRAY else f"板{plate} 孔{hole}"
        detail = f"{target} 自 {where} 进 {carrier}"
        if prev is not None:
            stale = f"板{prev['plate']}" + (f" 孔{prev['hole']}" if prev["hole"] else "")
            detail += f"; 覆盖未清的在途 {prev['kind']} {stale} (上一次取放没走完)"
            log.warning("[物料] %s 上还挂着未清的在途载荷 (%s %s), 已覆盖", carrier,
                        prev["kind"], stale)
        self._log_event(now, run_id, script, "transit_pick", kind, plate, hole,
                        from_state=where, to_state=carrier, detail=detail)

    def _do_transit_pick_station(self, run_id: str, script: str, binding: dict[str, Any],
                                 now: float) -> None:
        """单件离开工位夹具进小夹爪: 身份从座位行读回, 清座位行, 写在途行.

        与从货架/中转取的根本区别: 这几个站侧取料脚本 (robot_collect_bottle_pick 等)
        **只有 station_id 入参, 没有任何身份入参**。所以身份只有一个来源 —— 放件时
        写下的那一行 payload_seat。座位空着就什么都不做, 只留一条流水:
        凭空造一件载荷比不记账危害大得多 (三维会挂一个不存在的瓶子)。

        参数:
            run_id: 运行号; script: 脚本名; binding: 绑定项; now: 时间戳
        返回:
            None
        """
        carrier = binding["carrier"]
        seat = binding["seat"]
        # ⚠ 锁非可重入且 _log_event 自取锁 —— 留痕一律出块再做 (见 _do_transit_pick 同款注释)
        prev = None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, kind, plate, hole FROM payload_seat WHERE seat = ?",
                (seat,)).fetchone()
            if row is not None:
                prev = self._conn.execute(
                    "SELECT payload, kind, plate, hole FROM payload_transit WHERE carrier = ?",
                    (carrier,)).fetchone()
                self._conn.execute(
                    "INSERT OR REPLACE INTO payload_transit(carrier, payload, kind, plate,"
                    " hole, from_loc, to_loc, since_at, run_id, script, epoch)"
                    " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)",
                    (carrier, row["payload"], row["kind"], row["plate"], row["hole"],
                     LOC_STATION, now, run_id, script, self._epoch),
                )
                self._conn.execute("DELETE FROM payload_seat WHERE seat = ?", (seat,))
                self._conn.commit()

        label = self._payload_seat_label(seat)
        if row is None:
            detail = f"{label} 上无载荷却执行取件 (只跑了 pick 没跑 put?), 未记在途"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "transit_pick", "", None, None, detail=detail)
            return

        target = f"板{row['plate']} 孔{row['hole']}"
        detail = f"{target} 自 {label} 进 {carrier}"
        if prev is not None:
            stale = f"板{prev['plate']}" + (f" 孔{prev['hole']}" if prev["hole"] else "")
            detail += f"; 覆盖未清的在途 {prev['kind']} {stale} (上一次取放没走完)"
            log.warning("[物料] %s 上还挂着未清的在途载荷 (%s %s), 已覆盖", carrier,
                        prev["kind"], stale)
        self._log_event(now, run_id, script, "transit_pick", row["kind"], row["plate"],
                        row["hole"], from_state=label, to_state=carrier, detail=detail)

    def _payload_seat_label(self, seat: str) -> str:
        """工位座的中文显示名; 拓扑里没有就退回座号本身 (只用于流水文案)."""
        return self._payload_seats.get(seat, (seat, ""))[0]

    def _do_transit_place(self, run_id: str, script: str, binding: dict[str, Any],
                          args: dict, now: float) -> None:
        """载荷离开夹爪落到目标位: 清在途行, 并把目标位标占.

        身份一律以在途行为准, 入参只作比对 —— 与 _do_staging_unload 同一条纪律:
        入参与在途不一致时只告警留痕, 绝不按入参迁移 (迁移等于猜测板的身份)。
        """
        carrier = binding["carrier"]
        to_loc = binding["to_loc"]
        want = self._arg_int(args, binding["plate_from"]) if binding.get("plate_from") else None
        # 读与写必须在**同一个**临界区: 中间放锁会留一个 TOCTOU 窗口, 另一路
        # (人工清账 clear_transit 走 HTTP 线程) 可能刚好在那一刻把行清了。
        # ⚠ 锁非可重入且 _log_event 自取锁 —— 留痕一律出块再做 (见 _do_transit_pick 同款注释)。
        prev_staged = None
        prev_seated = None
        kind_reject = ""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, kind, plate, hole, from_loc FROM payload_transit"
                " WHERE carrier = ?", (carrier,)).fetchone()
            if row is not None:
                payload, kind, plate, hole = (
                    row["payload"], row["kind"], row["plate"], row["hole"])
                area = self._area_of_kind(kind)
            if row is not None and to_loc == LOC_STATION:
                seat = binding["seat"]
                accepts = self._payload_seats.get(seat, ("", ""))[1]
                if accepts and accepts != kind:
                    # 只告警不迁移: 与"身份以在途行为准"同一纪律。放错座说明流程或绑定表
                    # 有错, 硬记下去会让账本自洽地描述一件不可能的事
                    kind_reject = accepts
                else:
                    prev = self._conn.execute(
                        "SELECT kind, plate, hole FROM payload_seat WHERE seat = ?",
                        (seat,)).fetchone()
                    prev_seated = dict(prev) if prev is not None else None
                    self._conn.execute(
                        "INSERT OR REPLACE INTO payload_seat(seat, payload, kind, plate,"
                        " hole, since_at, run_id, script, epoch)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (seat, payload, kind, plate, hole, now, run_id, script, self._epoch),
                    )
                    self._conn.execute(
                        "DELETE FROM payload_transit WHERE carrier = ?", (carrier,))
                    self._conn.commit()
            elif row is not None:
                if payload == PAYLOAD_TRAY:
                    if to_loc == LOC_STAGING:
                        staged = self._conn.execute(
                            "SELECT plate FROM staging_occupancy WHERE area = ?",
                            (area,)).fetchone()
                        prev_staged = staged["plate"] if staged is not None else None
                        self._conn.execute(
                            "UPDATE staging_occupancy SET plate = ?, since_at = ?, run_id = ?"
                            " WHERE area = ?", (plate, now, run_id, area))
                        # rack_occupancy.present 在 transit_pick 时已置 0, 落中转位后仍是 0, 保持
                    else:
                        self._conn.execute(
                            "UPDATE rack_occupancy SET present = 1, updated_at = ?, run_id = ?"
                            " WHERE kind = ? AND plate = ?", (now, run_id, kind, plate))
                self._conn.execute("DELETE FROM payload_transit WHERE carrier = ?", (carrier,))
                self._conn.commit()

        if row is None:
            detail = f"{carrier} 上无在途载荷却执行放置 (只跑了 put 没跑 pick?), 未改状态"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "transit_place", "", None, None, detail=detail)
            return

        if to_loc == LOC_STATION:
            where = self._payload_seat_label(binding["seat"])
        elif to_loc == LOC_RACK:
            where = "货架库位"
        else:
            where = area
        target = f"板{plate}" if payload == PAYLOAD_TRAY else f"板{plate} 孔{hole}"
        if kind_reject:
            # 在途行**刻意保留**: 件还在爪上是此刻唯一能确认的事实, 清掉它等于宣称
            # 件已经落在某处, 那是编的
            detail = (f"{self._payload_seat_label(binding['seat'])} 只收 {kind_reject}, "
                      f"爪上是 {kind} {target}, 未落座 (在途行保留, 请盘点)")
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "transit_place", kind, plate, hole,
                            from_state=carrier, to_state="", detail=detail)
            return
        detail = f"{target} 自 {carrier} 落 {where}"
        if want is not None and want != plate:
            detail += f"; 入参目标库位 {want} 与在途板号 {plate} 不一致, 未按入参迁移, 请盘点"
            log.warning("[物料] %s: 入参库位 %s 与在途板号 %s 不一致", script, want, plate)
        if prev_staged is not None and prev_staged != plate:
            detail += f"; 覆盖 {area} 原占用板 {prev_staged} (账实可能已失同步)"
            log.warning("[物料] %s 落位前记为板 %s, 已覆盖", area, prev_staged)
        if prev_seated is not None:
            stale = f"{prev_seated['kind']} 板{prev_seated['plate']} 孔{prev_seated['hole']}"
            detail += f"; 覆盖 {where} 原停放的 {stale} (上一件没被取走)"
            log.warning("[物料] %s 上原停放 %s, 已覆盖", where, stale)
        self._log_event(now, run_id, script, "transit_place", kind, plate, hole,
                        from_state=carrier, to_state=where, detail=detail)

    def _clear_transit_locked(self, carrier: str) -> Optional[dict]:
        """清某夹爪的在途行并返回原内容; 无行返回 None. 须在已持锁的上下文调用."""
        row = self._conn.execute(
            "SELECT payload, kind, plate, hole FROM payload_transit WHERE carrier = ?",
            (carrier,)).fetchone()
        if row is None:
            return None
        self._conn.execute("DELETE FROM payload_transit WHERE carrier = ?", (carrier,))
        return dict(row)

    def _do_consume(self, run_id: str, script: str, kind: str, area: str,
                    hole: Optional[int], now: float) -> None:
        """中转板上某孔的耗材被取走消耗: FRESH -> USED."""
        plate = self._staging_plate(area)
        if plate is None or hole is None or not 1 <= hole <= HOLES_PER_PLATE:
            detail = f"无法定位孔位 (中转板={plate}, 孔号={hole}), 未改余量"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "consume", kind, plate, hole, detail=detail)
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT state, powder_mm3, liquid_ml FROM material_cells"
                " WHERE kind = ? AND plate = ? AND hole = ?",
                (kind, plate, hole)).fetchone()
            prev = row["state"] if row is not None else ""
            leftover = ((float(row["powder_mm3"]) + float(row["liquid_ml"]))
                        if row is not None else 0.0)
            # 内容物余量一并归零 —— FRESH->USED 那一刻件离开托盘孔上工位, 按定义是一件
            # 没用过的空件。**这是跨周期不累积的唯一保障**: 不清的话下一轮 powder_fill
            # 会加在上一轮的残值上, 而没有任何指标会说它错。
            self._conn.execute(
                "UPDATE material_cells SET state = ?, updated_at = ?, run_id = ?,"
                " powder_mm3 = 0, liquid_ml = 0, eluted = 0"
                " WHERE kind = ? AND plate = ? AND hole = ?",
                (STATE_USED, now, run_id, kind, plate, hole),
            )
            # 消耗即清该孔预留 (预留的使命到 consume 落账为止; 谁消耗都清, 账实一致优先)
            self._conn.execute(
                "DELETE FROM material_reservations WHERE kind = ? AND plate = ? AND hole = ?",
                (kind, plate, hole))
            self._conn.commit()
        detail = "" if prev == STATE_FRESH else f"消耗前账本已是 {prev or '缺行'}, 账实可能失同步"
        if prev != STATE_FRESH:
            log.warning("[物料] 消耗 %s 板%s 孔%s 时账本已是 %s", kind, plate, hole, prev or "缺行")
        if leftover > 1e-9:
            # 上一轮的余量没被重置, 或者中间漏记过一次 consume —— 值得留痕但不阻断
            extra = f"清掉上一轮残留内容物 {leftover:.1f} (上轮未重置或漏记 consume)"
            detail = f"{detail}; {extra}" if detail else extra
        self._log_event(now, run_id, script, "consume", kind, plate, hole,
                        from_state=prev, to_state=STATE_USED, detail=detail)

    def _do_fill(self, run_id: str, script: str, kind: str, area: str,
                 hole: Optional[int], sample_id: str, now: float) -> None:
        """已用件归还中转板原孔: 打上样品号; 状态保持/落到 USED (已用件不可再供料)."""
        plate = self._staging_plate(area)
        if plate is None or hole is None or not 1 <= hole <= HOLES_PER_PLATE:
            detail = f"无法定位孔位 (中转板={plate}, 孔号={hole}), 未打样品号"
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, "fill", kind, plate, hole, detail=detail)
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM material_cells WHERE kind = ? AND plate = ? AND hole = ?",
                (kind, plate, hole)).fetchone()
            prev = row["state"] if row is not None else ""
            self._conn.execute(
                "UPDATE material_cells SET state = ?, sample_id = ?, updated_at = ?, run_id = ?"
                " WHERE kind = ? AND plate = ? AND hole = ?",
                (STATE_USED, sample_id, now, run_id, kind, plate, hole),
            )
            # 件回孔即离爪. 静默清 —— robot_collector_return_put 直接绑 fill (无 transit_place
            # 包装, 见 material_bindings.yaml), 它的在途行只能由这里收口; 而走
            # robot_individual_put 的那条路已由 transit_place 清过, 此处是无害的空操作。
            # ⚠ _do_consume 刻意不清: 消耗的那一刻件正**在爪上**, 清了三维就画不出跟手。
            self._clear_transit_locked(CARRIER_VIAL)
            self._conn.commit()
        detail = "" if prev == STATE_USED else f"归还前账本为 {prev or '缺行'}, 漏记过消耗"
        if prev != STATE_USED:
            log.warning("[物料] 归还 %s 板%s 孔%s 时账本为 %s (漏记消耗), 已置 USED",
                        kind, plate, hole, prev or "缺行")
        self._log_event(now, run_id, script, "fill", kind, plate, hole,
                        from_state=prev, to_state=STATE_USED,
                        detail=detail or f"样品 {sample_id or '(未提供)'}")

    def _do_plate(self, run_id: str, script: str, magazine: str, delta: int,
                  now: float) -> None:
        """玻璃板仓计数 ±1; 上料仓已记为 0 还继续取则告警留痕并停在 0 (计数不为负)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM plate_magazines WHERE magazine = ?", (magazine,)).fetchone()
            prev = int(row["count"]) if row is not None else 0
            nxt = prev + delta
            clamped = max(0, nxt)
            self._conn.execute(
                "UPDATE plate_magazines SET count = ?, updated_at = ?, run_id = ?"
                " WHERE magazine = ?",
                (clamped, now, run_id, magazine),
            )
            self._conn.commit()
        if nxt < 0:
            detail = f"{self._magazines[magazine][0]} 账本已记为 0 却仍取板, 账实已失同步 (计数停在 0)"
            log.warning("[物料] %s", detail)
        else:
            detail = f"{self._magazines[magazine][0]} {prev} -> {clamped}"
        self._log_event(now, run_id, script,
                        "plate_take" if delta < 0 else "plate_put", "plate", None, None,
                        from_state=str(prev), to_state=str(clamped), detail=detail)

    def _do_liquid_draw(self, run_id: str, script: str, binding: dict[str, Any],
                        args: dict, now: float, *, source: str = "") -> None:
        """溶剂抽液扣减: 量 = volume × count, 按 ratio 权重分摊到各瓶.

        权重全零 = 配比未填 (没走那路溶剂), 不扣; ratio_from 缺省则全额记到 bottles[0].
        余量不足时扣到 0 并告警留痕 (账本不裁决, 只反映"已经抽过了"这件事).

        source 非空 (面板单发) 时写进流水: 单发的入参来自前端表单而非配方变量, 可能只填了
        必填项. 取不到液量一律走下面的告警分支留痕, **绝不默默按 0 扣** —— 静默扣 0 会让
        "试发过但没记上"和"确实没抽"在流水里长得一模一样.
        """
        volume = self._arg_float(args, binding["volume_from"])
        if volume is None or volume <= 0:
            self._log_event(now, run_id, script, "liquid_draw", "liquid", None, None,
                            detail=_with_source(f"液量取参非法 ({volume}), 未扣减", source))
            log.warning("[物料] %s: 液量取参非法 (%s), 未扣减", script, volume)
            return
        count = self._arg_int(args, binding["count_from"]) if binding["count_from"] else 1
        if count is None or count < 1:
            count = 1
        total = volume * count
        bottles = binding["bottles"]
        ratio_names = binding["ratio_from"]
        if ratio_names:
            weights = [max(0.0, self._arg_float(args, n) or 0.0) for n in ratio_names]
        else:
            weights = [1.0] + [0.0] * (len(bottles) - 1)
        summed = sum(weights)
        if summed <= 0:
            self._log_event(now, run_id, script, "liquid_draw", "liquid", None, None,
                            detail=_with_source(
                                f"配比权重全为零, 未扣减 (总量 {total:.2f}mL)", source))
            log.warning("[物料] %s: 配比权重全为零, 未扣减", script)
            return
        for bottle, weight in zip(bottles, weights):
            if weight <= 0:
                continue
            share = total * weight / summed
            self._draw_bottle(run_id, script, bottle, share, now, source=source)

        # 抽出的总量落进 to_seat 上那只瓶 (抽与注是同一次转移的两头); 顺带把 wet_seat 上
        # 那只粉桶标"已淋洗" —— 洗脱液穿过粉桶才进瓶, 是同一个物理事件。
        # 两个字段都缺 (develop.fill / rinse_fill) 时整段跳过 => 零回归。
        if binding.get("to_seat"):
            self._do_cell_add(run_id, script, "liquid_fill", binding["to_seat"], total, now,
                              source=source)
        if binding.get("wet_seat"):
            self._do_mark_eluted(run_id, script, binding["wet_seat"], now, source=source)

    # ------------------------------------------------------------------
    # 单件内容物余量 (粉 mm³ / 液 mL / 已淋洗)
    # ------------------------------------------------------------------

    def _seated_cell_locked(self, seat: str) -> Optional[tuple[str, int, int]]:
        """读某工位座上停着的件的身份 (kind, plate, hole); 座空 / 整板 / 无孔号返回 None.

        ⚠ 须在**已持锁**的上下文调用 (锁非可重入, 与 _do_transit_pick 同款约束)。
        """
        row = self._conn.execute(
            "SELECT kind, plate, hole FROM payload_seat WHERE seat = ?", (seat,)).fetchone()
        if row is None or row["hole"] is None or row["plate"] is None:
            return None
        return (str(row["kind"]), int(row["plate"]), int(row["hole"]))

    def _do_scrape_arm(self, run_id: str, script: str, binding: dict[str, Any],
                       result: dict, now: float) -> None:
        """cnc_path 算完就把本次刮取产粉量记进内存, 等 scrape_finish 翻料倒粉时落账.

        不写库、不发流水 (只打日志): 这一刻一粒粉都还没刮, 写进流水会让人以为已经进桶了。
        后到覆盖不累加 —— 理由见 __init__ 里 _scrape_armed 的注释。
        """
        volume = self._arg_float(result, binding["volume_from_result"])
        if volume is None or not math.isfinite(volume) or volume < 0:
            log.warning("[物料] %s: 刮取体积取值非法 (%s), 未 arm", script, volume)
            self._scrape_armed.pop(run_id, None)   # 宁可不记, 也不留一份过期的
            return
        self._scrape_armed[run_id] = {
            "volume_mm3": float(volume),
            "area_mm2": self._arg_float(result, binding.get("area_from_result")) or 0.0,
            "source": str(result.get(binding.get("source_from_result") or "") or ""),
        }
        log.debug("[物料] %s: armed 刮取粉量 %.1f mm³", script, volume)

    def _do_powder_fill(self, run_id: str, script: str, binding: dict[str, Any],
                        now: float, *, source: str = "") -> None:
        """翻料倒粉: 把本次 arm 的粉量记到刮板夹具上那只桶所属的托盘格."""
        armed = self._scrape_armed.pop(run_id, None)
        if armed is None:
            # 发生条件: 面板单发 scrape_finish; 或 cnc_path 与本步之间重启了后端。
            # 只留痕不猜 —— 往一个猜出来的量上记粉, 三维会长出一根编造的粉柱。
            self._log_event(now, run_id, script, "powder_fill", "collector", None, None,
                            detail=_with_source("本次运行没有 armed 的刮取量, 未记粉", source))
            return
        note = f"面积 {armed['area_mm2']:.1f}mm²({armed['source'] or '来源未知'})"
        self._do_cell_add(run_id, script, "powder_fill", binding["seat"],
                          armed["volume_mm3"], now, note=note, source=source)

    def _do_cell_add(self, run_id: str, script: str, effect: str, seat: str,
                     amount: Optional[float], now: float, *,
                     note: str = "", source: str = "") -> None:
        """给某工位座上那件耗材所属的托盘格累加余量 (粉 mm³ / 液 mL).

        身份一律从 payload_seat 读回, **绝不从入参猜** —— 与 _do_transit_pick_station 同一条
        纪律: 刮板夹具上此刻是哪只桶, 只有放件时写下的那一行知道 (站侧脚本只有 station_id
        入参)。座空即只留痕, 不编数。

        ⚠ 非有限值 (NaN/Inf) 必须在这里挡住: runtime/material_feedback 的指纹用
          allow_nan=False, 一个 NaN 落进 cells 会让那个 0.5s 推流循环**每一轮都抛异常**
          (catch 后只打日志), 于是 material_state 永不再发、整条实时链静默停摆,
          而前端只表现为"账本卡住了"。
        """
        column = _CELL_AMOUNT_COLUMN[effect]     # 闭集常量表, YAML 里的字符串到不了这里
        if amount is None or not math.isfinite(amount) or amount <= 0:
            self._log_event(now, run_id, script, effect, "", None, None,
                            detail=_with_source(f"量取值非法或为零 ({amount}), 未记账", source))
            return
        # 定身份与写入必须同一临界区 (中间放锁会留 TOCTOU 窗口, 另一路可能刚好把座清了)。
        # ⚠ 一切留痕出锁再做 —— _log_event 自取锁, 锁非可重入。
        prev = nxt = 0.0
        with self._lock:
            seated = self._seated_cell_locked(seat)
            if seated is not None:
                kind, plate, hole = seated
                row = self._conn.execute(
                    f"SELECT {column} AS amount FROM material_cells"
                    " WHERE kind = ? AND plate = ? AND hole = ?",
                    (kind, plate, hole)).fetchone()
                prev = float(row["amount"]) if row is not None else 0.0
                nxt = round(prev + float(amount), 3)
                self._conn.execute(
                    f"UPDATE material_cells SET {column} = ?, updated_at = ?, run_id = ?"
                    " WHERE kind = ? AND plate = ? AND hole = ?",
                    (nxt, now, run_id, kind, plate, hole))
                self._conn.commit()
        if seated is None:
            detail = (f"{self._payload_seat_label(seat)} 上没有件, 无处记 {amount:.1f}, 请盘点")
            log.warning("[物料] %s: %s", script, detail)
            self._log_event(now, run_id, script, effect, "", None, None,
                            detail=_with_source(detail, source))
            return
        kind, plate, hole = seated
        detail = (f"{self._payload_seat_label(seat)} 板{plate}孔{hole}: "
                  f"{prev:.1f} -> {nxt:.1f}")
        if note:
            detail += f" ({note})"
        cap = _CELL_CAPACITY.get(column)
        if cap is not None and nxt > cap:
            detail += f"; 已超名义容量 {cap:.2f} (账实可能失同步, 请盘点)"
            log.warning("[物料] %s: %s", script, detail)
        self._log_event(now, run_id, script, effect, kind, plate, hole,
                        from_state=f"{prev:.1f}", to_state=f"{nxt:.1f}",
                        detail=_with_source(detail, source))

    def _do_mark_eluted(self, run_id: str, script: str, seat: str, now: float, *,
                        source: str = "") -> None:
        """把某工位座上那只粉桶标为"已被洗脱液淋过" (三维据此把粉末换成湿色).

        已经是 1 时不留痕 —— 洗脱循环跑 N 轮只该记一次。
        """
        changed = False
        with self._lock:
            seated = self._seated_cell_locked(seat)
            if seated is not None:
                kind, plate, hole = seated
                row = self._conn.execute(
                    "SELECT eluted FROM material_cells WHERE kind = ? AND plate = ? AND hole = ?",
                    (kind, plate, hole)).fetchone()
                if row is not None and not int(row["eluted"]):
                    self._conn.execute(
                        "UPDATE material_cells SET eluted = 1, updated_at = ?, run_id = ?"
                        " WHERE kind = ? AND plate = ? AND hole = ?",
                        (now, run_id, kind, plate, hole))
                    self._conn.commit()
                    changed = True
        if seated is None or not changed:
            return
        kind, plate, hole = seated
        self._log_event(now, run_id, script, "powder_eluted", kind, plate, hole,
                        from_state="0", to_state="1",
                        detail=_with_source(
                            f"{self._payload_seat_label(seat)} 板{plate}孔{hole} 已被洗脱液淋过",
                            source))

    def _do_plate_seat(self, run_id: str, script: str, binding: dict, args: dict) -> None:
        """薄层板的板位迁移与工艺阶段推进 (plate_seat / plate_stage 的落账).

        参数:
            run_id / script: 流水归属
            binding: 规范化绑定项 (见 _parse_plate_seat_binding)
            args: 该次脚本调用的入参
        返回:
            None

        座名解析不出来 (入参缺失 / 不在 seat_map 里) 就**什么都不做** —— 那不是错误,
        是"这次调用没落在有账的板位上"(如放板到废料仓, 那条走 plate_put 计数)。
        阶段推进一律 advance_only: 重跑同一段不该把板退回去。
        """
        seat = binding.get("seat") or ""
        if not seat:
            key = str(args.get(binding["seat_from"], "") or "")
            seat = binding["seat_map"].get(key, "")
        if not seat:
            return
        if binding["effect"] == "plate_seat":
            self.move_plate_seat(seat, bool(binding["present"]),
                                 run_id=run_id, script=script)
            return
        self.set_seat_stage(seat, binding["stage"], run_id=run_id, script=script,
                            detail="流程推进", advance_only=True)

    def _draw_bottle(self, run_id: str, script: str, bottle: str, amount: float,
                     now: float, *, source: str = "") -> None:
        """单瓶扣减 amount mL; 不足则扣到 0 并告警留痕."""
        with self._lock:
            row = self._conn.execute(
                "SELECT label, volume_ml FROM liquid_bottles WHERE bottle = ?",
                (bottle,)).fetchone()
            if row is None:
                return
            prev = float(row["volume_ml"])
            label = row["label"]
            nxt = prev - amount
            clamped = max(0.0, nxt)
            self._conn.execute(
                "UPDATE liquid_bottles SET volume_ml = ?, updated_at = ?, run_id = ?"
                " WHERE bottle = ?",
                (round(clamped, 3), now, run_id, bottle),
            )
            self._conn.commit()
        if nxt < -1e-9:
            detail = (f"{label} 余量不足: 账本 {prev:.2f}mL 需抽 {amount:.2f}mL, "
                      f"已扣到 0 (账实失同步, 请盘点)")
            log.warning("[物料] %s", detail)
        else:
            detail = f"{label} {prev:.2f} -> {clamped:.2f} mL (抽 {amount:.2f})"
        self._log_event(now, run_id, script, "liquid_draw", "liquid", None, None,
                        from_state=f"{prev:.2f}", to_state=f"{clamped:.2f}",
                        detail=_with_source(detail, source))

    @staticmethod
    def _arg_float(args: dict, name: Optional[str]) -> Optional[float]:
        """从调用入参取浮点量; 缺失或非法返回 None."""
        if not name or name not in args:
            return None
        try:
            return float(args[name])
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # 在位对账 (按拓扑遍历全部声明了传感器的位置)
    # ------------------------------------------------------------------

    def reconcile_presence(self, byte_values: dict, *, ts: float | None = None) -> dict:
        """用 PLC 输入映像与账本做位置级在位对账.

        功能:
            按拓扑逐位置取 (字节, 位) 并按各自极性折算"有料", 落一份快照, 再与账本的期望比对。
            期望值来源分三种:
              货架 (rack_bits): 该板不在中转区即应在货架库位, 已搬去中转则该库位应为空;
              中转 (area 非空): 账本记着板号即期望有料 (软件记板号, 传感器只校验有/无);
              上料 (无 area): **无软件账 ⇒ 无期望值**, 只落现值, 不产生不一致。
            **只报不改** —— 传感器只知有/无, 覆盖不了孔级余量, 且账本是建议式的,
            处置交给人在物料页盘点。
        参数:
            byte_values: {字节节点名: 原始值}, 须覆盖 topology.byte_names() 全部;
            ts: 检测时刻, None 取当前时间
        返回:
            Dict, {checked_at, rows: [...], mismatches: int}
            rows 每项 {location_id, label, category, kind, plate, sensor, raw, present,
                       expected, ok, note, verified}
        """
        missing = [b for b in self._topology.byte_names() if b not in byte_values]
        if missing:
            raise ValueError(f"在位对账缺输入字节: {missing}")
        now = float(ts) if ts is not None else time.time()
        rows: list[dict] = []
        mismatches = 0

        for loc in self._topology.locations:
            if loc.rack_bits:
                rows.extend(self._reconcile_rack(loc, byte_values, now))
            elif loc.sensor is not None:
                rows.append(self._reconcile_single(loc, byte_values, now))
        mismatches = sum(1 for r in rows if r["ok"] is False)
        with self._lock:
            self._conn.commit()
        if mismatches:
            bad = [r["label"] for r in rows if r["ok"] is False]
            log.warning("[物料] 在位对账 %d 处不一致: %s", mismatches, ", ".join(bad))
            self._log_event(now, "", "", "presence", "", None, None,
                            detail=f"在位对账 {mismatches} 处不一致: {', '.join(bad)}")
        return {"checked_at": now, "rows": rows, "mismatches": mismatches}

    def _reconcile_rack(self, loc: LocationSpec, byte_values: dict, now: float) -> list[dict]:
        """货架 12 库位: 按 (kind, plate) 展开, 期望值取自人工在架账."""
        staged = {kind: self._staging_plate(area) for area, kind in AREAS.items()}
        racked = self._rack_presence_map()
        out: list[dict] = []
        for index, sensor in enumerate(loc.rack_bits):
            kind = KINDS[index // PLATES_PER_KIND]
            plate = index % PLATES_PER_KIND + 1
            raw = bool(int(byte_values[sensor.byte]) >> sensor.bit & 1)
            present = sensor.present(byte_values[sensor.byte])
            # 期望来源 = 人工在架账; staged 优先条件保留作不变量被破坏时的双保险
            expected = False if staged.get(kind) == plate else racked.get((kind, plate), True)
            if not sensor.verified:
                # 通用规则: 极性未实证的传感器只显读数不判定 (货架 12 路当前即此态)
                ok, note = None, "极性未核实, 不判定"
            else:
                ok = present == expected
                note = "" if ok else (
                    ("传感器报有板但账本认为已搬去中转" if staged.get(kind) == plate
                     else "传感器报有板但账本记该库位无板") if present
                    else "传感器报无板但账本认为该库位有板")
            out.append(self._presence_row(
                f"{loc.id}.{kind}.{plate}", f"{loc.label} {kind}板{plate}", loc, sensor,
                raw, present, expected, ok, note, now, kind=kind, plate=plate))
        return out

    def _reconcile_single(self, loc: LocationSpec, byte_values: dict, now: float) -> dict:
        """单点位置: 中转按账本板号定期望; 上料无软件账 ⇒ expected/ok 为 None."""
        sensor = loc.sensor
        raw = bool(int(byte_values[sensor.byte]) >> sensor.bit & 1)
        present = sensor.present(byte_values[sensor.byte])
        if loc.area:
            plate = self._staging_plate(loc.area)
            expected = plate is not None
            if not sensor.verified:
                # 通用规则: 极性未实证的传感器只显读数不判定 (expected 照算照显)
                ok, note = None, "极性未核实, 不判定"
            else:
                ok = present == expected
                note = "" if ok else (f"传感器报有料但账本记 {loc.label} 为空" if present
                                      else f"传感器报无料但账本记着板 {plate}")
        else:
            # 无软件账可比 (上料两处): 只落现值, 不判定
            expected = None
            ok = None
            note = ""
        return self._presence_row(loc.id, loc.label, loc, sensor, raw, present,
                                  expected, ok, note, now)

    def _presence_row(self, location_id: str, label: str, loc: LocationSpec,
                      sensor: SensorBit, raw: bool, present: bool,
                      expected: Optional[bool], ok: Optional[bool], note: str,
                      now: float, *, kind: str = "", plate: Optional[int] = None) -> dict:
        """落一行在位快照并返回给前端的行结构 (须在无锁上下文调用, 提交由调用方统一做)."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO location_presence"
                "(location_id, raw_bit, present, checked_at) VALUES (?, ?, ?, ?)",
                (location_id, 1 if raw else 0, 1 if present else 0, now),
            )
        return {"location_id": location_id, "label": label, "category": loc.category,
                "kind": kind, "plate": plate,
                "sensor": sensor.name, "byte": sensor.byte, "bit": sensor.bit,
                "polarity": sensor.polarity, "verified": sensor.verified,
                "raw": raw, "present": present, "expected": expected, "ok": ok,
                "note": note}

    def _staging_plate(self, area: str) -> Optional[int]:
        """读某中转区当前装的板号; 空或无该区返回 None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT plate FROM staging_occupancy WHERE area = ?", (area,)).fetchone()
        if row is None:
            return None
        return row["plate"]

    def _rack_presence_map(self) -> dict[tuple[str, int], bool]:
        """读 12 库位在架账 {(kind, plate): 在架?}; 缺行按在架算 (旧推导语义兜底).

        自取锁, 勿在已持锁时调用 (锁非可重入)。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, plate, present FROM rack_occupancy").fetchall()
        return {(row["kind"], int(row["plate"])): bool(row["present"]) for row in rows}

    def _log_event(self, ts: float, run_id: str, script: str, effect: str, kind: str,
                   plate: Optional[int], hole: Optional[int], *, from_state: str = "",
                   to_state: str = "", detail: str = "") -> None:
        """追加一条追溯流水 (append-only, 不淘汰)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO material_events"
                "(ts, run_id, script, effect, kind, plate, hole, from_state, to_state, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, run_id, script, effect, kind, plate, hole, from_state, to_state, detail),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def grid(self) -> dict:
        """读取三类物料的完整快照, 供前端物料页渲染.

        参数:
            无
        返回:
            Dict, {cells, staging, transit, transit_stale, payload_seats, rack, summary,
                   presence, magazines, bottles, seats, topology}
            cells 每项 {kind, plate, hole, state, sample_id, updated_at, run_id,
                     powder_mm3, liquid_ml, eluted}
                     后三个是**单件内容物余量**, 按 kind 分工: collector 用 powder_mm3(硅胶粉
                     mm³)与 eluted(是否已被洗脱液淋过, 三维粉末据此变色), bottle 用
                     liquid_ml(淋洗液 mL)。不适用的那一列恒为 0, 不是漏记。
                     ⚠ 二者都**无任何测量硬件**: 粉量按视觉轮廓面积×切深×松散系数估,
                     液量按动作参数算 —— 与溶剂瓶余量同一处境, 估错只能人工覆盖
            transit {夹爪id: {carrier, payload, kind, plate, hole, from_loc, since_at,
                     run_id, script, epoch, stale}} —— 只列此刻真有载荷的爪, 两把都空手时是空字典
                     stale=True 表示这行是上一个进程留下的, 没人能确认爪上真有东西
            transit_stale 陈旧在途行的条数 (0 = 全部由本进程记下, 可信)
            payload_seats 每项 {seat, label, accepts, payload, kind, plate, hole, since_at,
                     run_id, script, epoch, stale} —— 单件耗材停在工位夹具上; 只列被占的座
                     ⚠ 有座位行 ⇒ 该件不在托盘孔里, 三维必须把那个孔画空
            rack 每项 {kind, plate, present, updated_at, run_id} (板级在架人工账, 12 行)
            summary 每种耗材 {fresh, used, filled, absent_plates}
                (filled = USED 且带样品号, 即成品待取; absent_plates = 缺板库位数;
                 缺板 = 人工记无板, 且既不在中转也不在爪上; 其孔不计入 fresh/used/filled)
            presence 每项 {kind, plate, di_present, checked_at, expected, ok} (无快照则为空表)
            magazines 每项 {magazine, label, count, capacity, updated_at}
            bottles 每项 {bottle, label, volume_ml, capacity_ml, percent, updated_at}
            seats 每项 {seat, label, present, updated_at} (单板停放位人工账, 只供展示)
        """
        with self._lock:
            cells = self._conn.execute(
                "SELECT kind, plate, hole, state, sample_id, updated_at, run_id,"
                " powder_mm3, liquid_ml, eluted"
                " FROM material_cells ORDER BY kind, plate, hole").fetchall()
            staging = self._conn.execute(
                "SELECT area, kind, plate, since_at, run_id FROM staging_occupancy"
                " ORDER BY area").fetchall()
            presence = self._conn.execute(
                "SELECT location_id, raw_bit, present, checked_at FROM location_presence"
            ).fetchall()
            magazines = self._conn.execute(
                "SELECT magazine, count, capacity, updated_at, run_id FROM plate_magazines"
                " ORDER BY magazine").fetchall()
            bottles = self._conn.execute(
                "SELECT bottle, label, volume_ml, capacity_ml, updated_at, run_id"
                " FROM liquid_bottles ORDER BY bottle").fetchall()
            rack = self._conn.execute(
                "SELECT kind, plate, present, updated_at, run_id FROM rack_occupancy"
                " ORDER BY kind, plate").fetchall()
            seats = self._conn.execute(
                "SELECT seat, present, stage, updated_at FROM seat_occupancy ORDER BY seat"
            ).fetchall()
            transit = self._conn.execute(
                "SELECT carrier, payload, kind, plate, hole, from_loc, to_loc, since_at,"
                " run_id, script, epoch FROM payload_transit ORDER BY carrier").fetchall()
            payload_seats = self._conn.execute(
                "SELECT seat, payload, kind, plate, hole, since_at, run_id, script, epoch"
                " FROM payload_seat").fetchall()
        rows = [dict(row) for row in cells]
        staged = {row["kind"]: row["plate"] for row in staging}
        staged_by_area = {row["area"]: row["plate"] for row in staging}
        transit_rows = [dict(row) for row in transit]
        for row in transit_rows:
            row["stale"] = row.get("epoch") != self._epoch
        # 在爪上的整板: 它的库位 present 已是 0, 但那是"在途"不是"缺板"
        carried = {(r["kind"], int(r["plate"])) for r in transit_rows
                   if r["payload"] == PAYLOAD_TRAY}
        rack_rows = [dict(row) for row in rack]
        present_map = {(r["kind"], int(r["plate"])): bool(r["present"]) for r in rack_rows}
        # 缺板 = 人工记无板, 且既不是当前中转板也不在爪上
        # (在中转/在途的板都不算缺, 其孔照常计入统计)
        absent_by_kind: dict[str, set] = {kind: set() for kind in KINDS}
        for r in rack_rows:
            if r["present"]:
                continue
            if staged.get(r["kind"]) == r["plate"] or (r["kind"], r["plate"]) in carried:
                continue
            absent_by_kind.setdefault(r["kind"], set()).add(r["plate"])
        summary: dict[str, dict[str, int]] = {
            kind: {"fresh": 0, "used": 0, "filled": 0,
                   "absent_plates": len(absent_by_kind.get(kind, ()))} for kind in KINDS}
        for row in rows:
            if row["plate"] in absent_by_kind.get(row["kind"], ()):
                continue      # 全联动: 无板库位的孔不计入任何统计 (板都不在, 余量拿不到)
            bucket = summary.setdefault(
                row["kind"], {"fresh": 0, "used": 0, "filled": 0, "absent_plates": 0})
            if row["state"] == STATE_ABSENT:
                continue  # 件不在位: 与无板库位的孔同理, 不计入任何余量统计
            if row["state"] == STATE_FRESH:
                bucket["fresh"] += 1
            else:
                bucket["used"] += 1
                if row["sample_id"]:
                    bucket["filled"] += 1
        # 在位快照 -> 按拓扑重算期望与一致性 (快照只存传感器现值, 期望随账本变化故每次现算)
        snap = {row["location_id"]: dict(row) for row in presence}
        presence_rows = []
        for loc in self._topology.locations:
            if loc.rack_bits:
                for index in range(len(loc.rack_bits)):
                    kind = KINDS[index // PLATES_PER_KIND]
                    plate = index % PLATES_PER_KIND + 1
                    row = snap.get(f"{loc.id}.{kind}.{plate}")
                    if row is None:
                        continue
                    # 期望来源 = 人工在架账 (present_map 在 transit_pick 时已被置 0);
                    # staged / carried 两个优先条件作不变量双保险,
                    # 极性未实证的传感器只显读数不判定 (ok=None)
                    expected = (False if (staged.get(kind) == plate
                                          or (kind, plate) in carried)
                                else present_map.get((kind, plate), True))
                    present = bool(row["present"])
                    presence_rows.append({
                        "location_id": row["location_id"], "category": loc.category,
                        "label": f"{loc.label} {kind}板{plate}", "kind": kind, "plate": plate,
                        "sensor": loc.rack_bits[index].name,
                        "verified": loc.rack_bits[index].verified,
                        "raw": bool(row["raw_bit"]), "present": present,
                        "expected": expected,
                        "ok": ((present == expected)
                               if loc.rack_bits[index].verified else None),
                        "checked_at": row["checked_at"]})
            elif loc.sensor is not None:
                row = snap.get(loc.id)
                if row is None:
                    continue
                present = bool(row["present"])
                if loc.area:
                    expected = staged_by_area.get(loc.area) is not None
                    # 通用规则: 极性未实证的传感器只显读数不判定
                    ok = (present == expected) if loc.sensor.verified else None
                else:
                    expected, ok = None, None      # 上料两处无软件账, 不判定
                presence_rows.append({
                    "location_id": loc.id, "category": loc.category, "label": loc.label,
                    "kind": "", "plate": None, "sensor": loc.sensor.name,
                    "verified": loc.sensor.verified,
                    "raw": bool(row["raw_bit"]), "present": present,
                    "expected": expected, "ok": ok, "checked_at": row["checked_at"]})
        magazine_rows = []
        for row in magazines:
            item = dict(row)
            item["label"] = self._magazines.get(item["magazine"], (item["magazine"], 0))[0]
            magazine_rows.append(item)
        bottle_rows = []
        for row in bottles:
            item = dict(row)
            cap = float(item["capacity_ml"]) or 1.0
            item["percent"] = round(min(100.0, float(item["volume_ml"]) / cap * 100.0), 1)
            bottle_rows.append(item)
        # 按拓扑声明序输出 (不是库里的字典序): 页面行序应与真源一致, 点样座在刮板台之前。
        # 只列拓扑里还在的座 —— 拓扑删掉某座后旧库残行不该继续显示。
        seat_by_id = {row["seat"]: row for row in seats}
        seat_rows = []
        for seat, label in self._seats.items():
            row = seat_by_id.get(seat)
            seat_rows.append({
                "seat": seat, "label": label,
                "present": bool(row["present"]) if row is not None else False,
                # 工艺阶段: 无板的座一律报 blank (阶段是板的属性, 座上没板就无从谈起)
                "stage": (str(row["stage"] or PLATE_STAGE_BLANK)
                          if row is not None and bool(row["present"])
                          else PLATE_STAGE_BLANK),
                "updated_at": (row["updated_at"] if row is not None else 0.0),
            })
        # 工位座: 按拓扑声明序输出 (与 seats 同一条约定), 只列拓扑里还在且此刻被占的座。
        # 拓扑删掉某座后旧库残行不该继续显示 —— 那会让页面指着一个不存在的位置。
        seated_by_seat = {row["seat"]: dict(row) for row in payload_seats}
        payload_seat_rows = []
        for seat, (label, accepts) in self._payload_seats.items():
            row = seated_by_seat.get(seat)
            if row is None:
                continue          # 空座就是没有行, 不输出占位行 (与 payload_transit 同款)
            row["label"] = label
            row["accepts"] = accepts
            # ⚠ 语义与 transit.stale 刻意相反, 别照搬处理方式:
            #   在途行陈旧 = **可疑** (上个进程以为爪上有东西, 现在没人能确认) -> 三维不挂载;
            #   座位行陈旧 = **仍可信** (瓶子停在收集工位上, 后端重启它不会自己跑掉) -> 照常生效。
            # 这个不对称正是这张表值得存在的全部理由。
            row["stale"] = row.get("epoch") != self._epoch
            payload_seat_rows.append(row)
        return {
            "cells": rows,
            "staging": {row["area"]: dict(row) for row in staging},
            # 按 carrier 索引: 前端 (三维/物料页) 要问的永远是"这把爪上有什么", 不是遍历
            "transit": {row["carrier"]: row for row in transit_rows},
            # 只数在途里陈旧的: 座位陈旧是正常的 (见上), 不该进这个计数
            "transit_stale": sum(1 for r in transit_rows if r["stale"]),
            "payload_seats": payload_seat_rows,
            "rack": rack_rows,
            "summary": summary,
            "presence": presence_rows,
            # 只数判定为 False 的; ok 为 None (上料两处无软件账) 不算不一致
            "presence_mismatches": sum(1 for r in presence_rows if r["ok"] is False),
            "magazines": magazine_rows,
            "bottles": bottle_rows,
            "seats": seat_rows,
            "topology": self.topology_dto(),
        }

    @property
    def magazines(self) -> dict:
        """玻璃板仓表 {仓号: (显示名, 容量)}; 真源是拓扑, 供路由层校验仓号与取容量."""
        return dict(self._magazines)

    @property
    def bottles(self) -> dict:
        """溶剂瓶表 {瓶号: (显示名, 容量mL)}; 真源是拓扑."""
        return dict(self._bottles)

    @property
    def seats(self) -> dict:
        """单板停放位表 {座号: 显示名}; 真源是拓扑; 供路由层校验座号与取显示名."""
        return dict(self._seats)

    @property
    def topology(self) -> MaterialTopology:
        """本账本挂的物料拓扑 (供对账端点取需读的字节名)."""
        return self._topology

    def topology_dto(self) -> dict:
        """把物料拓扑转成前端可直接渲染的结构 (四类树 + 每类位置与传感器).

        参数:
            无
        返回:
            Dict, {categories: [{key, label, hint, locations, magazines, bottles, seats,
                                 payload_seats}]}
            locations 每项 {id, label, area, sensor, byte, bit, polarity, verified, note, slots}
            seats 每项 {id, label} —— 单板停放位无传感器, 故不在 locations 里
            payload_seats 每项 {id, label, accepts} —— 单件耗材的工位停放位, 同样无传感器
            contents 每项 {kind, label, unit, capacity} —— 单件内容物的量纲与名义容量;
                     没声明的 kind 不出现在表里, 前端据此整条装量条不渲染
        """
        cats = []
        for cat in self._topology.categories:
            locs = []
            for loc in cat.locations:
                sensor = loc.sensor or (loc.rack_bits[0] if loc.rack_bits else None)
                locs.append({
                    "id": loc.id, "label": loc.label, "area": loc.area,
                    "slots": len(loc.rack_bits) or 1,
                    "sensor": sensor.name if sensor else "",
                    "byte": sensor.byte if sensor else "",
                    "bit": (sensor.bit if sensor and not loc.rack_bits else None),
                    "polarity": sensor.polarity if sensor else "",
                    "verified": bool(sensor.verified) if sensor else False,
                    "note": sensor.note if sensor else "",
                })
            cats.append({
                "key": cat.key, "label": cat.label, "hint": cat.hint, "locations": locs,
                "magazines": [{"id": m[0], "label": m[1], "capacity": m[2]}
                              for m in cat.magazines],
                "bottles": [{"id": b[0], "label": b[1], "capacity_ml": b[2]}
                            for b in cat.bottles],
                "seats": [{"id": s[0], "label": s[1]} for s in cat.seats],
                "payload_seats": [{"id": p[0], "label": p[1], "accepts": p[2]}
                                  for p in cat.payload_seats],
                "contents": [{"kind": c[0], "label": c[1], "unit": c[2], "capacity": c[3]}
                             for c in cat.contents],
            })
        return {"categories": cats}

    def next_fresh(self, kind: str) -> Optional[dict]:
        """给出下一个建议消耗的孔位 (供前端预填输入框).

        功能:
            中转区已装板时只在该板上找 (单件取放的孔号必须落在当前中转板上);
            中转区为空时在全部板上找首个 FRESH 格, 其板号即建议去货架取的库位。
            按 (板号, 孔号) 升序取首个, 无可用返回 None.
        参数:
            kind: 耗材种类 (collector | bottle)
        返回:
            Dict {kind, rack_slot, hole, staging_plate, from_staging} 或 None
        """
        if kind not in KINDS:
            return None
        area = next((a for a, k in AREAS.items() if k == kind), None)
        staged = self._staging_plate(area) if area else None
        query = ("SELECT plate, hole FROM material_cells"
                 " WHERE kind = ? AND state = ?")
        args: list = [kind, STATE_FRESH]
        if staged is not None:
            query += " AND plate = ?"
            args.append(staged)
        else:
            # 全联动: 人工记"无板"的库位不出建议 (中转有板走上一分支, 不受此限)
            query += (" AND plate IN (SELECT plate FROM rack_occupancy"
                      " WHERE kind = ? AND present = 1)")
            args.append(kind)
        query += " ORDER BY plate ASC, hole ASC LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, args).fetchone()
        if row is None:
            return None
        return {
            "kind": kind,
            "rack_slot": int(row["plate"]),
            "hole": int(row["hole"]),
            "staging_plate": staged,
            "from_staging": staged is not None,
        }

    def plan_staging(self, kind: str, *, reserve_for: str = "") -> dict:
        """给出某类耗材"下一件从哪来"的换板决策 (reserve_for 非空时附带孔级预留).

        功能:
            中转板还有可用 FRESH 孔就原地复用 (NONE); 中转区空则从货架取一块有料的板
            (PUT_NEW); 中转板已耗尽则先把它送回原库位再取新板 (SWAP); 架上也没料则
            EXHAUSTED。货架与中转共用同一套 36 格 (material_cells.plate 即货架库位号),
            板搬进中转不迁移孔位账, 故各路径本身都只是查询。

            并行语义 (多样品调度后, 旧注释"单运行无并发者"的前提失效):
            - "可用" = FRESH 且未被其他样品孔级预留 (reserve_for 即本样品, 自己的预留
              可复用; 空串=匿名调用, 任何在保留孔都不可用);
            - 在架过滤: 人工记"无板"的货架库位 (rack_occupancy.present=0 且非中转板)
              不算候选也不撑 BLOCKED —— 板都不在架上, 派机器人去也只会抓空;
            - 换板防吞: 中转板对本方无可用孔、但板上还有他人未消费的在保留孔时, 不许
              SWAP 送走整板 (会把别人预约的件搬回货架), 返回 BLOCKED 等其消费/释放;
            - reserve_for 非空: 决策成功后本方法把该样品在此 kind 的旧预留 (计数级或
              孔级) 替换为选定孔的孔级预留 —— plan 与 consume 之间的窗口内, 该孔对
              其他样品不可见, 整板也不会被换走。
            真正的余量扣账仍由 config/material_bindings.yaml 在脚本 DONE 时提交。
        参数:
            kind: 耗材种类 (collector | bottle)
            reserve_for: 样品号; 非空则排除"他人"预留并落本样品的孔级预留
        返回:
            Dict, {op, rack_slot, old_rack_slot, hole, staged_plate}
                op            PLAN_OPS 之一
                rack_slot     要从货架取的库位 1-6; NONE / EXHAUSTED / BLOCKED 时为 0
                old_rack_slot 要送回货架的满板库位 1-6; 仅 SWAP 时非 0
                hole          本件要用的板上孔号 1-6; EXHAUSTED / BLOCKED 时为 0
                staged_plate  决策前中转区的板号; 中转空为 0
        """
        if kind not in KINDS:
            raise ValueError(f"耗材种类应为 {KINDS}, 实际为 {kind!r}")
        area = next((a for a, k in AREAS.items() if k == kind), None)
        # _staging_plate 自己要取 self._lock (非可重入), 必须在下面持锁前先读完
        staged = self._staging_plate(area) if area else None
        staged_plate = int(staged) if staged is not None else 0
        who = str(reserve_for or "")
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.plate AS plate, MIN(c.hole) AS hole FROM material_cells c"
                " WHERE c.kind = ? AND c.state = ?"
                "   AND NOT EXISTS (SELECT 1 FROM material_reservations r"
                "                   WHERE r.kind = c.kind AND r.plate = c.plate"
                "                     AND r.hole = c.hole AND r.sample_id <> ?)"
                " GROUP BY c.plate ORDER BY c.plate ASC",
                (kind, STATE_FRESH, who)).fetchall()
            # 中转板上他人未消费的在保留孔数 (换板防吞判据)
            others_on_staged = 0
            if staged_plate != 0:
                others_on_staged = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM material_reservations"
                    " WHERE kind = ? AND plate = ? AND hole IS NOT NULL AND sample_id <> ?",
                    (kind, staged_plate, who)).fetchone()["n"]
            absent_rows = self._conn.execute(
                "SELECT plate FROM rack_occupancy WHERE kind = ? AND present = 0",
                (kind,)).fetchall()
        # {板号: 该板最小可用孔号}; 板不在表里即该板对本方已无余量
        fresh = {int(row["plate"]): int(row["hole"]) for row in rows}
        # 在架过滤: 无板库位不算候选。staged 板豁免 —— 不变量下中转板 present=0 是
        # "在中转"而非缺板, 下方 NONE 原地复用分支必须仍能命中它。
        absent = {int(row["plate"]) for row in absent_rows}
        fresh = {plate: hole for plate, hole in fresh.items()
                 if plate == staged_plate or plate not in absent}

        if staged_plate != 0 and staged_plate in fresh:
            plan = {"op": OP_NONE, "rack_slot": 0, "old_rack_slot": 0,
                    "hole": fresh[staged_plate], "staged_plate": staged_plate}
            self._upgrade_reservation(kind, staged_plate, plan["hole"], who)
            return plan
        # 中转板对本方无可用孔, 但板上还压着他人预约的件: 送走整板 = 吞掉别人的预留
        if staged_plate != 0 and others_on_staged > 0:
            log.warning("[物料] %s 中转板 %s 上有 %d 个他人在保留孔, 换板被拦 (BLOCKED)",
                        kind, staged_plate, others_on_staged)
            return {"op": OP_BLOCKED, "rack_slot": 0, "old_rack_slot": 0,
                    "hole": 0, "staged_plate": staged_plate}
        # 中转空或已耗尽: 到货架另找一块有料的板 (排除中转上那块, 它已被上一分支否掉)
        candidate = next((plate for plate in sorted(fresh) if plate != staged_plate), None)
        if candidate is None:
            # 区分"真没料"与"有料但全被他人预留": 后者等释放即可, 不该提示去盘点补料。
            # 无板库位上滞留的他人预留不算 BLOCKED 依据 (板都不在, 等释放也等不来);
            # 中转板豁免同上方 fresh 过滤。
            with self._lock:
                reserved_fresh = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM material_cells c"
                    " WHERE c.kind = ? AND c.state = ?"
                    "   AND EXISTS (SELECT 1 FROM material_reservations r"
                    "               WHERE r.kind = c.kind AND r.plate = c.plate"
                    "                 AND r.hole = c.hole AND r.sample_id <> ?)"
                    "   AND (c.plate = ? OR c.plate IN (SELECT plate FROM rack_occupancy"
                    "                                   WHERE kind = c.kind AND present = 1))",
                    (kind, STATE_FRESH, who, staged_plate)).fetchone()["n"]
            op = OP_BLOCKED if reserved_fresh > 0 else OP_EXHAUSTED
            return {"op": op, "rack_slot": 0, "old_rack_slot": 0,
                    "hole": 0, "staged_plate": staged_plate}
        plan = {"op": OP_SWAP if staged_plate != 0 else OP_PUT_NEW,
                "rack_slot": candidate, "old_rack_slot": staged_plate,
                "hole": fresh[candidate], "staged_plate": staged_plate}
        self._upgrade_reservation(kind, candidate, plan["hole"], who)
        return plan

    # ------------------------------------------------------------------
    # 并行预留 (批次准入计数级 -> plan_staging 孔级 -> consume 清账)
    # ------------------------------------------------------------------

    def _upgrade_reservation(self, kind: str, plate: int, hole: int, sample_id: str) -> None:
        """把某样品在该 kind 的既有预留替换为孔级预留 (sample_id 为空即跳过)."""
        if not sample_id:
            return
        now = time.time()
        with self._lock:
            self._conn.execute(
                "DELETE FROM material_reservations WHERE kind = ? AND sample_id = ?",
                (kind, sample_id))
            self._conn.execute(
                "INSERT INTO material_reservations(kind, plate, hole, sample_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)", (kind, plate, hole, sample_id, now))
            self._conn.commit()
        log.info("[物料] 预留升级: %s 板%s 孔%s -> 样品 %s", kind, plate, hole, sample_id)

    def reserve_count(self, sample_id: str, kind: str) -> bool:
        """计数级预留一件 (批次准入门): 可用余量 > 他人预留总数才成立.

        "可用余量"只数在架 (人工账 rack_occupancy) 或正在中转的板上的 FRESH 孔 ——
        无板库位的余量拿不到, 不该撑起批次准入。
        幂等: 同样品同 kind 重复调用先清旧行再插新行 (恒一行)。
        返回:
            True 预留成立; False 余量不足 (调用方应拒收该样品/批次)
        """
        if kind not in KINDS:
            raise ValueError(f"耗材种类应为 {KINDS}, 实际为 {kind!r}")
        if not sample_id:
            raise ValueError("reserve_count 需要非空 sample_id")
        now = time.time()
        with self._lock:
            # 锁内不可调 _staging_plate (锁非可重入), staged 用标量子查询表达;
            # staging_occupancy 每 kind 恒一行, plate 为 NULL 时比较恒否, 语义正确
            fresh_total = self._conn.execute(
                "SELECT COUNT(*) AS n FROM material_cells c"
                " WHERE c.kind = ? AND c.state = ?"
                "   AND (c.plate IN (SELECT plate FROM rack_occupancy"
                "                    WHERE kind = c.kind AND present = 1)"
                "        OR c.plate = (SELECT plate FROM staging_occupancy"
                "                      WHERE kind = c.kind))",
                (kind, STATE_FRESH)).fetchone()["n"]
            others = self._conn.execute(
                "SELECT COUNT(*) AS n FROM material_reservations"
                " WHERE kind = ? AND sample_id <> ?", (kind, sample_id)).fetchone()["n"]
            if fresh_total - others <= 0:
                return False
            self._conn.execute(
                "DELETE FROM material_reservations WHERE kind = ? AND sample_id = ?",
                (kind, sample_id))
            self._conn.execute(
                "INSERT INTO material_reservations(kind, plate, hole, sample_id, created_at)"
                " VALUES (?, NULL, NULL, ?, ?)", (kind, sample_id, now))
            self._conn.commit()
        return True

    def release_reservations(self, sample_id: str, kind: Optional[str] = None) -> int:
        """释放某样品的预留 (样品终止/批次收尾); 返回删除行数."""
        if not sample_id:
            return 0
        with self._lock:
            if kind:
                cur = self._conn.execute(
                    "DELETE FROM material_reservations WHERE sample_id = ? AND kind = ?",
                    (sample_id, kind))
            else:
                cur = self._conn.execute(
                    "DELETE FROM material_reservations WHERE sample_id = ?", (sample_id,))
            self._conn.commit()
            n = cur.rowcount or 0
        if n:
            log.info("[物料] 释放预留: 样品 %s (%s) 共 %d 行", sample_id, kind or "全部", n)
        return n

    def reserved_summary(self) -> dict:
        """预留账快照 (快照/对账面板用): 每类的计数级样品与孔级明细."""
        out: dict = {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, plate, hole, sample_id, created_at"
                " FROM material_reservations ORDER BY kind, sample_id").fetchall()
        for row in rows:
            entry = out.setdefault(row["kind"], {"count_level": [], "holes": []})
            if row["plate"] is None:
                entry["count_level"].append(row["sample_id"])
            else:
                entry["holes"].append({"plate": int(row["plate"]), "hole": int(row["hole"]),
                                       "sample_id": row["sample_id"],
                                       "created_at": row["created_at"]})
        return out

    def suggest_inputs(self, script: str, var_names: list[str]) -> dict:
        """给出某脚本输入框的预填建议 (只供前端预填, 不参与任何执行决策).

        功能:
            把"该填哪个库位/孔号"的解析集中在此 (紧邻绑定表), 前端不做任何推断。
            解析规则, 按序:
              1. 变量名自带耗材种类 (如 collector_slot / bottle_rack_slot): 按名定 kind,
                 名含 rack 即要货架库位, 否则要板上孔号;
              2. 变量名为裸 slot_id: 按绑定表定 (kind 与 plate_from/hole_from 二选一);
              3. 其余变量不给建议 (前端退回流程声明的 default)。
        参数:
            script: 脚本名 (绑定表键); var_names: 该脚本的 in 变量名列表
        返回:
            Dict, {script, inputs: {变量名: 建议值}, source: {变量名: 说明}}
        """
        binding = self._bindings.scripts.get(script)
        inputs: dict[str, int] = {}
        source: dict[str, str] = {}
        for name in var_names:
            lowered = str(name).lower()
            if "collector" in lowered:
                kind, want_plate = "collector", "rack" in lowered
            elif "bottle" in lowered:
                kind, want_plate = "bottle", "rack" in lowered
            elif lowered == "slot_id" and binding is not None and binding.get("kind"):
                # 仅盘位类绑定 (staging_load/unload/consume/fill) 有 kind 与 plate_from;
                # 玻璃板计数类绑定没有孔位语义, 不给建议
                kind = binding["kind"]
                want_plate = binding.get("plate_from") is not None
            else:
                continue
            hit = self.next_fresh(kind)
            if hit is None:
                continue
            inputs[name] = hit["rack_slot"] if want_plate else hit["hole"]
            source[name] = (f"{kind} 货架库位" if want_plate
                            else f"{kind} 板上孔号 (中转板 {hit['staging_plate']})"
                            if hit["from_staging"] else f"{kind} 板上孔号")
        return {"script": script, "inputs": inputs, "source": source}

    def list_events(self, *, kind: str | None = None, plate: int | None = None,
                    hole: int | None = None, limit: int = 200) -> list[dict]:
        """读追溯流水 (按 id 倒序即时间倒序); 三个过滤条件可任意组合.

        参数:
            kind/plate/hole: 过滤条件, None 表示不过滤
            limit: 条数上限
        返回:
            list[dict], 行结构同 material_events 表
        """
        query = "SELECT * FROM material_events"
        conds: list[str] = []
        args: list = []
        if kind:
            conds.append("kind = ?")
            args.append(kind)
        if plate is not None:
            conds.append("plate = ?")
            args.append(int(plate))
        if hole is not None:
            conds.append("hole = ?")
            args.append(int(hole))
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 人工盘点 (实验员在物料页录入; 账本的唯一权威录入口)
    # ------------------------------------------------------------------

    def mark(self, kind: str, plate: int, hole: int, state: str, *,
             sample_id: str = "", detail: str = "人工盘点") -> None:
        """人工设置单个孔位状态.

        参数:
            kind: 耗材种类; plate: 货架板号 1-6; hole: 板上孔号 1-6
            state: FRESH | USED | ABSENT; sample_id: 样品号 (USED 时表示成品待取); detail: 流水备注
        返回:
            None
        """
        self._check_cell(kind, plate, hole)
        if state not in STATES:
            raise ValueError(f"孔位状态应为 {STATES}, 实际为 {state!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM material_cells WHERE kind = ? AND plate = ? AND hole = ?",
                (kind, plate, hole)).fetchone()
            prev = row["state"] if row is not None else ""
            # 标 FRESH = 补货换上新件、标 ABSENT = 件被拿走 ⇒ 内容物一并清零(件不在,
            # 孔里自然没有粉与液)。标 USED 则**不清** —— mark(USED, sample_id=...) 是在
            # 登记成品待取, 清了就把那只桶/瓶里的粉与液抹了, 而那正是"成品"本身。
            extra = (", powder_mm3 = 0, liquid_ml = 0, eluted = 0"
                     if state in (STATE_FRESH, STATE_ABSENT) else "")
            self._conn.execute(
                "UPDATE material_cells SET state = ?, sample_id = ?, updated_at = ?,"
                f" run_id = ''{extra}"
                " WHERE kind = ? AND plate = ? AND hole = ?",
                (state, sample_id, now, kind, plate, hole),
            )
            self._conn.commit()
        self._log_event(now, "", "", "manual", kind, plate, hole,
                        from_state=prev, to_state=state, detail=detail)

    def mark_plate(self, kind: str, plate: int, state: str, *,
                   detail: str = "人工盘点(整板)") -> None:
        """人工把整块板的 6 个孔设为同一状态 (装满/清空的常用录入).

        参数:
            kind: 耗材种类; plate: 货架板号 1-6; state: FRESH | USED | ABSENT; detail: 流水备注
        返回:
            None
        """
        for hole in range(1, HOLES_PER_PLATE + 1):
            self.mark(kind, plate, hole, state, sample_id="", detail=detail)

    def set_staging(self, area: str, plate: Optional[int], *,
                    detail: str = "人工盘点") -> None:
        """人工设置某中转区当前装的板号 (面板单跑叶子脚本导致失同步时用).

        同步维护货架在架账不变量: 新中转板的库位置"不在", 被替换/置空的旧板记回架
        (板被整个拿走的场景由人再标"无板")。

        参数:
            area: staging-a | staging-b; plate: 板号 1-6, None 表示该区空; detail: 流水备注
        返回:
            None
        """
        if area not in AREAS:
            raise ValueError(f"中转区应为 {tuple(AREAS)}, 实际为 {area!r}")
        if plate is not None and not 1 <= int(plate) <= PLATES_PER_KIND:
            raise ValueError(f"板号应在 1..{PLATES_PER_KIND}, 实际为 {plate!r}")
        now = time.time()
        value = None if plate is None else int(plate)
        with self._lock:
            self._shift_staging_locked(area, AREAS[area], value, now, "")
            self._conn.commit()
        self._log_event(now, "", "", "manual", AREAS[area], value, None,
                        detail=f"{detail}: {area} -> {'空' if value is None else f'板{value}'}")

    def clear_transit(self, carrier: str, *, land_at: str = "",
                      detail: str = "人工盘点") -> dict:
        """人工清掉某夹爪的在途载荷 (流程中途取消/断电后, 板滞留在爪上时用).

        功能:
            这是在途态存在的意义所在 —— 旧账本在那段窗口里静默失同步且不留痕, 人无从下手。
            land_at 决定把整板算作落在哪:
              ""(默认)  只清在途行, 不动任何位置账 —— 板被人拿走了/去向不明, 随后由人在
                        货架或中转位一节自行更正;
              "rack"    记回它原来的货架库位 (present=1);
              "staging" 记进对应中转区。
            单件载荷 (payload=item) 一律只清行: 件的去向由 consume/fill 表达, 位置账里没有它。
        参数:
            carrier: gripper_plate96 | gripper_vial; land_at: "" | rack | staging
            detail: 流水备注
        返回:
            dict, 被清掉的在途行内容; 本来就空手则为空字典
        """
        if carrier not in CARRIERS:
            raise ValueError(f"搬运器应为 {CARRIERS}, 实际为 {carrier!r}")
        # 只认 rack / staging 两个**位置账里有对应行**的去处。station 虽然也在 TRANSIT_LOCS
        # 里, 但工位座是 payload_seat 那张表, 人工往那儿放要走 seat_payload_manually —— 放这里
        # 会写到 staging_occupancy 去 (且随后的 where 查表直接 KeyError)。
        if land_at and land_at not in (LOC_RACK, LOC_STAGING):
            raise ValueError(
                f"落位应为 '' 或 {(LOC_RACK, LOC_STAGING)}, 实际为 {land_at!r}"
                "; 工位座请用 clear_payload_seat / seat_payload_manually")
        now = time.time()
        with self._lock:
            row = self._clear_transit_locked(carrier)
            if row is not None and land_at and row["payload"] == PAYLOAD_TRAY:
                kind, plate = row["kind"], int(row["plate"])
                if land_at == LOC_RACK:
                    self._conn.execute(
                        "UPDATE rack_occupancy SET present = 1, updated_at = ?, run_id = ''"
                        " WHERE kind = ? AND plate = ?", (now, kind, plate))
                else:
                    self._conn.execute(
                        "UPDATE staging_occupancy SET plate = ?, since_at = ?, run_id = ''"
                        " WHERE area = ?", (plate, now, self._area_of_kind(kind)))
            self._conn.commit()
        if row is None:
            return {}
        where = {"": "去向不明", LOC_RACK: "货架库位", LOC_STAGING: "中转区"}[land_at]
        target = (f"板{row['plate']}" if row["payload"] == PAYLOAD_TRAY
                  else f"板{row['plate']} 孔{row['hole']}")
        self._log_event(now, "", "", "manual", row["kind"], row["plate"], row["hole"],
                        from_state=carrier, to_state=where,
                        detail=f"{detail}: 清 {carrier} 在途 {target} -> {where}")
        return row

    def clear_payload_seat(self, seat: str, *, detail: str = "人工盘点") -> dict:
        """人工清掉某工位座上的单件 (人把它拿走了 / 流程中途取消后座位行滞留时用).

        与 clear_transit 对称, 但**没有 land_at**: 件被人从刮板夹具上拿走之后去了哪里,
        账本无从知道, 也不该猜。清完之后由人在中转板那一节自行更正孔位状态 ——
        与 clear_transit 的 land_at="" 是同一条纪律。

        参数:
            seat: 拓扑 payload_seats 里的座号; detail: 流水备注
        返回:
            dict, 被清掉的座位行内容; 座上本来就空则为空字典
        """
        if seat not in self._payload_seats:
            raise ValueError(f"工位座应为 {tuple(self._payload_seats)}, 实际为 {seat!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, kind, plate, hole FROM payload_seat WHERE seat = ?",
                (seat,)).fetchone()
            if row is not None:
                self._conn.execute("DELETE FROM payload_seat WHERE seat = ?", (seat,))
                self._conn.commit()
        if row is None:
            return {}
        label = self._payload_seat_label(seat)
        self._log_event(now, "", "", "manual", row["kind"], row["plate"], row["hole"],
                        from_state=label, to_state="去向不明",
                        detail=f"{detail}: 清 {label} 上的 板{row['plate']} 孔{row['hole']}")
        return dict(row)

    def seat_payload_manually(self, seat: str, kind: str, plate: int, hole: int, *,
                              detail: str = "人工盘点") -> None:
        """人工把一个单件耗材记到某工位座上 (盘点发现座上有件而账本没有时用).

        与 clear_payload_seat 互为反向。**刻意不动 material_cells**: 孔位状态由人在
        盘位一节自行更正 —— 与清账之后"由人更正孔账"是同一条纪律, 这里替人改孔账
        会把座位账与孔位账搅在一起。

        与流程路径的"kind 不符只告警"不同, 人工录入没有"身份以在途行为准"的权威冲突,
        准入不符**硬拒** —— 拒绝就是防手滑 (刮板夹具只收 collector)。

        参数:
            seat: 拓扑 payload_seats 里的座号; kind/plate/hole: 件的身份 (孔位寻址)
            detail: 流水备注
        返回:
            None
        Raises:
            ValueError: 座号非法 / 孔位非法 / kind 与座位准入不符 / 座上已记有件 /
                        该件已记为在某夹爪上
        """
        if seat not in self._payload_seats:
            raise ValueError(f"工位座应为 {tuple(self._payload_seats)}, 实际为 {seat!r}")
        self._check_cell(kind, plate, hole)
        label, accepts = self._payload_seats[seat]
        if kind != accepts:
            raise ValueError(f"{label} 只收 {accepts}, 不能放 {kind}")
        now = time.time()
        with self._lock:
            # 读+验+写同一临界区 (锁非可重入, 不得调其它带锁方法; 锁外查有 TOCTOU 窗)
            row = self._conn.execute(
                "SELECT kind, plate, hole FROM payload_seat WHERE seat = ?",
                (seat,)).fetchone()
            if row is not None:
                raise ValueError(
                    f"{label} 上已记有 {row['kind']} 板{row['plate']} 孔{row['hole']}, "
                    f"请先清账再放件")
            carried = self._conn.execute(
                "SELECT carrier FROM payload_transit"
                " WHERE payload = ? AND kind = ? AND plate = ? AND hole = ?",
                (PAYLOAD_ITEM, kind, int(plate), int(hole))).fetchone()
            if carried is not None:
                raise ValueError(
                    f"该件 ({kind} 板{plate} 孔{hole}) 记为在 {carried['carrier']} 爪上, "
                    f"请先清在途再放件 (否则同一件东西账上出现两处)")
            # epoch 用本进程值: 人工放件是"此刻亲眼所见", 天然可信 (stale=False)
            self._conn.execute(
                "INSERT INTO payload_seat(seat, payload, kind, plate, hole, since_at,"
                " run_id, script, epoch) VALUES (?, ?, ?, ?, ?, ?, '', '', ?)",
                (seat, PAYLOAD_ITEM, kind, int(plate), int(hole), now, self._epoch))
            self._conn.commit()
        self._log_event(now, "", "", "manual", kind, int(plate), int(hole),
                        from_state="去向不明", to_state=label,
                        detail=f"{detail}: 放 {kind} 板{plate} 孔{hole} 到 {label}")

    def set_rack_presence(self, kind: str, plate: int, present: bool, *,
                          detail: str = "人工盘点") -> None:
        """人工设置货架某库位的板级在架状态 (有板/无板).

        货架 12 路光电无信号 (见文件头现场记录), 板在不在架上只能人工记账。
        「无板」参与决策: 该板的孔不计入可用统计, plan_staging / next_fresh /
        reserve_count 一律跳过该库位。板正在中转位时拒改 —— 其在架态由中转占用
        经 _shift_staging_locked 维护, 请先在中转位一节更正 (置空或改板号)。

        参数:
            kind: 耗材种类; plate: 货架板号 1-6; present: True=有板, False=无板
            detail: 流水备注
        返回:
            None
        """
        if kind not in KINDS:
            raise ValueError(f"耗材种类应为 {KINDS}, 实际为 {kind!r}")
        if not 1 <= int(plate) <= PLATES_PER_KIND:
            raise ValueError(f"板号应在 1..{PLATES_PER_KIND}, 实际为 {plate!r}")
        area = next(a for a, k in AREAS.items() if k == kind)
        now = time.time()
        with self._lock:
            # staged 检查必须锁内直查 (锁非可重入, 不得调 _staging_plate; 锁外查有 TOCTOU 窗)
            row = self._conn.execute(
                "SELECT plate FROM staging_occupancy WHERE area = ?", (area,)).fetchone()
            staged = row["plate"] if row is not None else None
            if staged == int(plate):
                raise ValueError(
                    f"{kind} 板{plate} 当前记为在中转位, 在架态由中转占用维护; "
                    f"请先在中转位一节更正 (置空或改板号)")
            prev_row = self._conn.execute(
                "SELECT present FROM rack_occupancy WHERE kind = ? AND plate = ?",
                (kind, int(plate))).fetchone()
            prev = bool(prev_row["present"]) if prev_row is not None else True
            self._conn.execute(
                "UPDATE rack_occupancy SET present = ?, updated_at = ?, run_id = ''"
                " WHERE kind = ? AND plate = ?",
                (1 if present else 0, now, kind, int(plate)),
            )
            self._conn.commit()
        self._log_event(now, "", "", "manual", kind, int(plate), None,
                        from_state="PRESENT" if prev else "ABSENT",
                        to_state="PRESENT" if present else "ABSENT",
                        detail=f"{detail}: 货架库位{plate} -> {'有板' if present else '无板'}")

    def set_seat_presence(self, seat: str, present: bool, *,
                          detail: str = "人工盘点") -> None:
        """人工设置单板停放位 (点样座/刮板拍照台) 的有板/无板.

        这两处无任何在位传感器 (IX8-IX12 已用位里没有它们的板检测), 故只能人工记账。
        用途刻意收窄为**前端展示与人工同步**: 人手动把板从座上拿走/放上时在物料页点一下,
        让界面与现场一致。与 set_rack_presence 的关键差别 —— 这个状态**不参与任何决策**
        (不进 summary 统计, 不参与 plan_staging / next_fresh / 预填 / 批次准入),
        也不写调度器的 samples.position (那份账仍是流程内的唯一权威)。
        因此这里不需要 set_rack_presence 那段中转占用互斥检查: 座位与中转位无不变量关系。

        参数:
            seat: 拓扑 seats 里的座号 (spot_seat | scrape_table)
            present: True=有板, False=无板
            detail: 流水备注
        返回:
            None
        """
        if seat not in self._seats:
            raise ValueError(f"板位应为 {tuple(self._seats)}, 实际为 {seat!r}")
        now = time.time()
        with self._lock:
            prev_row = self._conn.execute(
                "SELECT present FROM seat_occupancy WHERE seat = ?", (seat,)).fetchone()
            prev = bool(prev_row["present"]) if prev_row is not None else False
            # 板被拿走时阶段一并归零: 阶段是**板**的属性, 座上没板就无从谈起;
            # 留着旧阶段会让下一块放上来的空白板凭空显示成"已点样"。
            if present:
                self._conn.execute(
                    "UPDATE seat_occupancy SET present = 1, updated_at = ? WHERE seat = ?",
                    (now, seat))
            else:
                self._conn.execute(
                    "UPDATE seat_occupancy SET present = 0, stage = ?, updated_at = ?"
                    " WHERE seat = ?", (PLATE_STAGE_BLANK, now, seat))
            self._conn.commit()
        # kind 记 "seat" 而非耗材种类: 流水页据此把这两条与孔账/货架账区分开
        self._log_event(now, "", "", "manual", "seat", None, None,
                        from_state="PRESENT" if prev else "ABSENT",
                        to_state="PRESENT" if present else "ABSENT",
                        detail=f"{detail}: {self._seats[seat]} -> "
                               f"{'有板' if present else '无板'}")

    def set_seat_stage(self, seat: str, stage: str, *, run_id: str = "", script: str = "",
                       detail: str = "人工设置", advance_only: bool = False) -> bool:
        """设置某板位上那块板的工艺阶段 (blank/spotted/developed/scraped).

        参数:
            seat: 拓扑 seats 里的座号 (spot_seat | scrape_table | tank_1..tank_8)
            stage: 目标阶段, 必须在 PLATE_STAGES 里
            run_id / script: 流程推进时带上, 人工设置留空
            detail: 流水备注
            advance_only: True 时只许前进 (流程推进用: 重跑一段不该把板退回去)
        返回:
            bool, 是否真的改了

        与 set_seat_presence 的边界一致: 阶段**不参与任何耗材孔决策与统计口径**,
        它只是板的外观维度 (三维四态板的开关) 与人工可读的进度。
        座上无板时拒写 —— 阶段是板的属性, 空座上的阶段是无意义的。
        """
        if seat not in self._seats:
            raise ValueError(f"板位应为 {tuple(self._seats)}, 实际为 {seat!r}")
        if stage not in PLATE_STAGE_RANK:
            raise ValueError(f"工艺阶段应为 {PLATE_STAGES}, 实际为 {stage!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT present, stage FROM seat_occupancy WHERE seat = ?",
                (seat,)).fetchone()
            if row is None or not bool(row["present"]):
                return False
            prev = str(row["stage"] or PLATE_STAGE_BLANK)
            if prev == stage:
                return False
            if advance_only and PLATE_STAGE_RANK.get(prev, 0) >= PLATE_STAGE_RANK[stage]:
                return False
            self._conn.execute(
                "UPDATE seat_occupancy SET stage = ?, updated_at = ? WHERE seat = ?",
                (stage, now, seat))
            self._conn.commit()
        self._log_event(now, run_id, script, "plate_stage", "seat", None, None,
                        from_state=prev, to_state=stage,
                        detail=f"{detail}: {self._seats[seat]} {prev} -> {stage}")
        return True

    def move_plate_seat(self, seat: str, present: bool, *, run_id: str = "",
                        script: str = "", stage: str = "", detail: str = "") -> None:
        """流程侧的板位迁移 (放板 present=True / 取板 present=False).

        参数:
            seat: 座号; present: 放上还是拿走
            run_id / script: 记流水用
            stage: 放板时可带初始阶段 (取板忽略); 留空则保持原值
            detail: 流水备注
        返回:
            None

        与 set_seat_presence 的差别只在流水的归属 (那条记 manual, 这条记 run/script)。
        取板一律把阶段归零, 理由同 set_seat_presence。
        """
        if seat not in self._seats:
            raise ValueError(f"板位应为 {tuple(self._seats)}, 实际为 {seat!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT present, stage FROM seat_occupancy WHERE seat = ?",
                (seat,)).fetchone()
            prev = bool(row["present"]) if row is not None else False
            next_stage = (str(stage) if (present and stage in PLATE_STAGE_RANK)
                          else (str(row["stage"] or PLATE_STAGE_BLANK) if row is not None
                                and present else PLATE_STAGE_BLANK))
            self._conn.execute(
                "UPDATE seat_occupancy SET present = ?, stage = ?, updated_at = ?"
                " WHERE seat = ?",
                (1 if present else 0, next_stage, now, seat))
            self._conn.commit()
        self._log_event(now, run_id, script, "plate_seat", "seat", None, None,
                        from_state="PRESENT" if prev else "ABSENT",
                        to_state="PRESENT" if present else "ABSENT",
                        detail=detail or f"{self._seats[seat]} -> "
                                         f"{'有板' if present else '无板'}")

    def liquid_drawn_total_ml(self) -> float:
        """账本累计从溶剂瓶扣掉的总量 mL (liquid_draw 流水的逐条扣减之和).

        参数:
            无
        返回:
            float, 累计扣减 mL; 无流水则 0.0

        量取自流水的 from_state/to_state 差 (那是**真扣掉的**数, 瓶见底时被夹到 0,
        与请求量刻意不同 —— 报请求量会把"账实失同步"这件事抹平)。
        供仿真沙盒把它与虚拟泵的吸入积分并排显示: 账本按动作参数扣是真机的真实盲区
        (没有流量计), 沙盒**不改这个口径**, 只让差异看得见。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT from_state, to_state FROM material_events WHERE effect = ?",
                ("liquid_draw",)).fetchall()
        total = 0.0
        for row in rows:
            try:
                total += float(row["from_state"]) - float(row["to_state"])
            except (TypeError, ValueError):
                continue
        return round(total, 4)

    def magazine_count(self, magazine: str) -> int:
        """读某玻璃板仓的当前账面板数.

        参数:
            magazine: feed=上料仓 | waste=下料仓
        返回:
            int, 账面板数; 缺行时为 0

        供 feedlift.probe_stack 对账用 (实测张数 vs 账面张数)。
        """
        if magazine not in self._magazines:
            raise ValueError(f"板仓应为 {tuple(self._magazines)}, 实际为 {magazine!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM plate_magazines WHERE magazine = ?", (magazine,)).fetchone()
        return int(row["count"]) if row is not None else 0

    def set_magazine_observer(self, observer) -> None:
        """注册"板仓账面被外部权威改写"的观察者 (仿真沙盒把账面回灌板堆模型用).

        参数:
            observer: (counts, detail) -> None; counts 为 {板仓: 新账面张数},
                detail 为流水备注; 传 None 表示注销
        返回:
            None

        触发点**只有两个** —— set_magazine (人工盘点 / 光电盘点校正) 与 import_rows
        (整表采纳), 即"外部权威直接指定张数"的两条路。
        ⚠ 流程记账 _do_plate 的 ±1 **刻意不触发**: 那条路的物理事件在沙盒里已由
        FeedLiftModel 自行处理 (取板扣减绑 A12 DONE 且吸盘 ON, 见
        mock/behavior/feedlift.py 头注), 再回灌一次就是双重扣减, 并会重新引入那段头注
        论证过的时序矛盾 (账本扣减发生在脚本 DONE, 晚于流程中段第二次 probe)。
        观察者在事务提交且流水落定之后、self._lock 之外调用, 且可能来自工作线程
        (adopt 走 asyncio.to_thread), 故实现必须是纯内存同步操作, 不得回调本账本、不得阻塞。
        """
        self._magazine_observer = observer

    def _notify_magazine_override(self, counts: dict, detail: str) -> None:
        """触发板仓改写观察者; 观察者抛错只记 warning, 绝不让人工盘点写失败."""
        observer = self._magazine_observer
        if observer is None:
            return
        try:
            observer(counts, detail)
        except Exception:
            log.warning("[物料] 板仓改写观察者异常 (账面已写入, 不回滚)", exc_info=True)

    def set_magazine(self, magazine: str, count: int, *, detail: str = "人工盘点") -> None:
        """设置某玻璃板仓的板数 (人工盘点, 或 feedlift.probe_stack 的光电行程实测校正).

        参数:
            magazine: feed=上料仓 | waste=下料仓; count: 板数 (>=0); detail: 流水备注
        返回:
            None
        """
        if magazine not in self._magazines:
            raise ValueError(f"板仓应为 {tuple(self._magazines)}, 实际为 {magazine!r}")
        value = int(count)
        if value < 0:
            raise ValueError(f"板数不能为负, 实际为 {count!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM plate_magazines WHERE magazine = ?", (magazine,)).fetchone()
            prev = int(row["count"]) if row is not None else 0
            self._conn.execute(
                "UPDATE plate_magazines SET count = ?, updated_at = ?, run_id = ''"
                " WHERE magazine = ?",
                (value, now, magazine),
            )
            self._conn.commit()
        self._log_event(now, "", "", "manual", "plate", None, None,
                        from_state=str(prev), to_state=str(value),
                        detail=f"{detail}: {self._magazines[magazine][0]} -> {value} 张")
        self._notify_magazine_override({magazine: value}, detail)

    def set_bottle(self, bottle: str, volume_ml: float, *, detail: str = "人工盘点") -> None:
        """人工设置某溶剂瓶余量 (硬件无体积测量, 只能靠盘点/换瓶时录入).

        参数:
            bottle: 瓶标识 (solvent_1..4 | eluent); volume_ml: 余量 mL (>=0); detail: 流水备注
        返回:
            None
        """
        if bottle not in self._bottles:
            raise ValueError(f"溶剂瓶应为 {tuple(self._bottles)}, 实际为 {bottle!r}")
        value = float(volume_ml)
        if value < 0:
            raise ValueError(f"余量不能为负, 实际为 {volume_ml!r}")
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT label, volume_ml FROM liquid_bottles WHERE bottle = ?",
                (bottle,)).fetchone()
            prev = float(row["volume_ml"]) if row is not None else 0.0
            label = row["label"] if row is not None else bottle
            self._conn.execute(
                "UPDATE liquid_bottles SET volume_ml = ?, updated_at = ?, run_id = ''"
                " WHERE bottle = ?",
                (round(value, 3), now, bottle),
            )
            self._conn.commit()
        self._log_event(now, "", "", "manual", "liquid", None, None,
                        from_state=f"{prev:.2f}", to_state=f"{value:.2f}",
                        detail=f"{detail}: {label} -> {value:.2f} mL")

    def set_cell_amount(self, kind: str, plate: int, hole: int, *,
                        powder_mm3: Optional[float] = None,
                        liquid_ml: Optional[float] = None,
                        eluted: Optional[bool] = None,
                        detail: str = "人工盘点") -> None:
        """人工设置单件内容物余量 (粉 mm³ / 液 mL / 是否已淋洗).

        与 set_bottle 同一条纪律: 硬件对这两个量没有任何测量 —— 粉量是按视觉轮廓面积 ×
        切深 × 松散系数**估**出来的, 液量是按动作参数算的, 估错了只能靠人覆盖式改回。
        试机空跑造成的假数据也走这里清。

        **缺省的字段一律不动** (三个都是 Optional 而不是给默认值): 这样"把粉量清零"不会
        顺带抹掉已淋洗标志, "标已淋洗"也不会把粉量清零。三个全 None 直接抛错而不是静默
        返回成功 —— 那种请求一定是调用方写错了。

        参数:
            kind/plate/hole: 孔位寻址; powder_mm3/liquid_ml: 余量 (>=0 有限数);
            eluted: 是否已被洗脱液淋过; detail: 流水备注
        返回:
            None
        Raises:
            ValueError: 孔位非法 / 余量为负或非有限数 / 三个字段全缺
        """
        self._check_cell(kind, plate, hole)
        sets: list[tuple[str, Any]] = []
        for column, value in (("powder_mm3", powder_mm3), ("liquid_ml", liquid_ml)):
            if value is None:
                continue
            number = float(value)
            # 非有限值必须挡在入库前: material_feedback 的 _fingerprint 用 allow_nan=False,
            # 一个 NaN 落进 cells 会让那个 0.5s 推流循环**每一轮都抛异常**(catch 后只打日志),
            # 整条实时链静默停摆而前端只表现为"账本卡住了"。
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{column} 必须是 >= 0 的有限数, 实际为 {value!r}")
            sets.append((column, round(number, 3)))
        if eluted is not None:
            sets.append(("eluted", 1 if eluted else 0))
        if not sets:
            raise ValueError("powder_mm3 / liquid_ml / eluted 至少要给一项")

        now = time.time()
        assignments = ", ".join(f"{column} = ?" for column, _ in sets)
        params = [value for _, value in sets]
        with self._lock:
            row = self._conn.execute(
                "SELECT powder_mm3, liquid_ml, eluted FROM material_cells"
                " WHERE kind = ? AND plate = ? AND hole = ?", (kind, plate, hole)).fetchone()
            before = {c: row[c] for c in ("powder_mm3", "liquid_ml", "eluted")} if row else {}
            self._conn.execute(
                f"UPDATE material_cells SET {assignments}, updated_at = ?, run_id = ''"
                " WHERE kind = ? AND plate = ? AND hole = ?",
                (*params, now, kind, plate, hole),
            )
            self._conn.commit()
        changes = ", ".join(
            f"{column} {before.get(column, 0)} -> {value}" for column, value in sets)
        self._log_event(now, "", "", "manual", kind, int(plate), int(hole),
                        detail=f"{detail}: {changes}")

    @staticmethod
    def _check_cell(kind: str, plate: int, hole: int) -> None:
        """校验孔位寻址三元组; 非法即抛错."""
        if kind not in KINDS:
            raise ValueError(f"耗材种类应为 {KINDS}, 实际为 {kind!r}")
        if not 1 <= int(plate) <= PLATES_PER_KIND:
            raise ValueError(f"板号应在 1..{PLATES_PER_KIND}, 实际为 {plate!r}")
        if not 1 <= int(hole) <= HOLES_PER_PLATE:
            raise ValueError(f"孔号应在 1..{HOLES_PER_PLATE}, 实际为 {hole!r}")

    # ------------------------------------------------------------------
    # 快照导出/导入 (仿真沙盒采纳真机账本用)
    # ------------------------------------------------------------------

    #: 参与快照的表 (白名单; 顺序即导入顺序)。
    #: 刻意**不含** material_events (真机历史不属于沙盒时间线, 搬过去会让沙盒流水
    #: 冒充成"发生过的事") 与 location_presence (传感器现值, 由沙盒自己的合成层产生)。
    SNAPSHOT_TABLES = (
        "material_cells", "staging_occupancy", "rack_occupancy",
        "plate_magazines", "liquid_bottles", "seat_occupancy",
        "payload_transit", "payload_seat", "material_reservations",
    )

    def export_rows(self) -> dict:
        """导出账本快照 (白名单表全行).

        参数:
            无
        返回:
            Dict, {表名: [行字典, ...]}; 行字典的键即列名, 值是 SQLite 原值
        """
        out: dict = {}
        with self._lock:
            for table in self.SNAPSHOT_TABLES:
                rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
                out[table] = [dict(row) for row in rows]
        return out

    def import_rows(self, snapshot: dict, *, detail: str = "沙盒采纳") -> dict:
        """用快照整体替换账本 (单事务 DELETE + INSERT).

        功能:
            供仿真沙盒把真机账本搬进 :memory: 副本。**epoch 原样保留** ——
            导入方进程的 epoch 与快照里的不同, 于是 payload_transit 的行在
            grid() 里自动判 stale=True, 语义恰好诚实 ("上一个世界留下的在途,
            沙盒无法确认爪上真有东西"), 不需要额外代码。
            未在快照里出现的表不动 (调用方给部分快照即部分替换)。
        参数:
            snapshot: export_rows 的产物 (或其子集); detail: 流水备注
        返回:
            Dict, {表名: 导入行数}
        Raises:
            ValueError: 快照含白名单外的表 (防把 events/presence 混进来)
        """
        unknown = [table for table in snapshot if table not in self.SNAPSHOT_TABLES]
        if unknown:
            raise ValueError(f"快照含不可导入的表: {unknown}; "
                             f"允许的是 {self.SNAPSHOT_TABLES}")
        counts: dict = {}
        now = time.time()
        with self._lock:
            try:
                for table, rows in snapshot.items():
                    self._conn.execute(f"DELETE FROM {table}")
                    for row in rows:
                        columns = ", ".join(row)
                        marks = ", ".join("?" for _ in row)
                        self._conn.execute(
                            f"INSERT INTO {table}({columns}) VALUES ({marks})",
                            tuple(row.values()))
                    counts[table] = len(rows)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        total = sum(counts.values())
        self._log_event(now, "", "", "adopt", "", None, None,
                        detail=f"{detail}: 导入 {len(counts)} 张表共 {total} 行")
        log.info("[物料] %s: %s", detail,
                 ", ".join(f"{table}={count}" for table, count in counts.items()))
        # 只在快照确实带了板仓表时通知: 部分快照 (只导某几张表) 不该让观察者收到
        # 一份"其实没人改过"的张数, 那会把回灌变成周期性覆写
        if "plate_magazines" in snapshot:
            self._notify_magazine_override(
                {name: self.magazine_count(name) for name in self._magazines}, detail)
        return counts

    def close(self) -> None:
        """关闭数据库连接."""
        with self._lock:
            self._conn.close()
