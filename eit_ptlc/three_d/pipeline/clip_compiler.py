"""把上位机 operation 脚本编译成三维动画片段(ptlc.clip/v3)的通用库。

与 sync_ptlc_robot.py 的关系: 那个脚本原本内联了一个只认"单层工具分支"的迷你解释器,
只够编译 robot_tool_pick / robot_tool_put 两条。转移路线是 `run_script` 多层嵌套 + 按
(rack_id, slot_id) 分十二支的结构, 需要一个真正的分支求值与内联器, 于是抽到本模块,
两边共用。

三条纪律(与既有资产管线一致, 违反即抛错而不是降级):
  1. **绝不手填生产关节角** —— 关节值只能来自 PointRegistry 的实测点或 sample_move_l
     的离线 IK; 点表 SHA 会写进片段, 前端 compileClip 逐字校验。
  2. **运行期看到的每一处近似都要在编译期就失败** —— 落位残差、未知动作、取不到的
     分支, 一律 raise, 不 log 警告后继续。
  3. **不猜运行期状态** —— operation 里读实时反馈的分支(robot.query 的工具号、
     material.plan_staging 的换板决策)由调用方以显式假设传入, 并写进片段 description,
     不在编译器里编一个"大概是这样"的默认值。
"""

from __future__ import annotations

import math
import re
import sys
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

from robot_kinematics import forward_kinematics, sample_move_l
from scene_kinematics import GlbScene, RobotPosture

# 泵档回退链与运行链同源 (阶段①泵链路归真): 经 eit_ptlc 包取 profiles 的
# pump_default_hint(传值 > config.pump > translator 常量)。管线脚本平时以
# 目录内顶层模块互相 import, 故这里显式把仓库根挂上 sys.path。
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from eit_ptlc.tools.pump.offline_defaults import install_pump_defaults_from_app_yaml  # noqa: E402
from eit_ptlc.tools.pump.profiles import pump_default_hint  # noqa: E402


#: operation YAML 的搜索目录(相对 control_root/config/operation), 按优先级。
OPERATION_DIRS = (
    "05_transfer", "06_robot", "08_rail", "04_collect", "03_photoscrape",
    "01_sampling", "02_develop", "07_feedlift", "00_system",
)

#: 地轨站位毫米只有一份真源: 控制侧 config/points/plc/rail.yaml 的 plc_servo[].value,
#: 由 load_rail_slots() 实读。这里**不留副本** —— 曾有一张与点表数值恰好相同的常量表
#: (RAIL_SLOT_REFERENCE), 导出给前端当"点表读不到时的兜底", 于是"读到了"与"没读到"长得
#: 一模一样; 现场重新示教地轨后, 演示会继续播陈旧值且没有任何指标会报警。

#: 控制器工具号 -> GLB 工具节点。与 sync_ptlc_robot.TOOL_ASSET 同一份事实。
TOOL_ASSET = {1: "TOOL_SUCTION", 2: "TOOL_PLATE96", 3: "TOOL_VIAL"}

#: 工具号 -> 夹爪联动组 id。与上位机 robot_controller._TWIN_GRIPPER_BY_TOOL 逐字一致。
GRIPPER_BY_TOOL = {2: "rob_grip_plate96", 3: "rob_grip_vial"}

#: 吸盘翻转执行器 id。与 rig_map.actuators / robot_controller._TWIN_FLIP_ID 逐字一致。
FLIP_ACTUATOR_ID = "rob_flip_suction"

#: 取放基准点(点表里的 P 号) -> 薄层板停放位。
#:
#: 判据与前端 PlateTransferTracker.POINT_TO_SLOT **逐字一致**, 但这里是编译期:
#: 一个 robot_suction_put/pick 脚本服务三个落点(station_id ∈ spotting/scrape/waste)、
#: robot_tank_put/pick 服务 8 个缸, 光看脚本名分不出落点; 而实读全部脚本确认
#: **每个吸/放动作都紧跟在它的基准点之后, 无一例外**。所以"最近一次命中本表的点"
#: 就是那次吸/放的落点。
#: ⚠ 命名进近点与过渡点(P1/P4/P5/P63/P75/P84/P59/P86)绝不进表 —— 它们会把落点冲掉。
#: ⚠ P64 也不进表: robot_suction_pick.yaml:184 注明"取放同基点 P65; P64 弃用, 勿再引用"。
PLATE_POINT_SLOT = {
    "P21": "feedlift",
    "P19": "spot_seat",
    "P65": "scrape_table",
    "P22": "waste",
    **{f"P{10 + n}": f"tank:{n}" for n in range(1, 9)},
}

#: 板锚点的 CAD 零件名 -> 停放位(固定落点)。缸位一律按 parent 名 `TANK_N` 反查 ——
#: CAD 实例编号是乱的(玻璃-1.010→TANK_1、玻璃-1.007 根本是废板仓), 按序号推必错。
#: 与前端 PlateSlots.FIXED_ANCHOR_NAMES / resolveAnchors 同一份规则, 改一处必须改两处。
PLATE_ANCHOR_FIXED = {
    "玻璃-1": "spot_seat",
    "玻璃-1.002": "scrape_table",
    "INV_MAGAZINE_FEED_TEMPLATE": "feedlift",
    "INV_MAGAZINE_WASTE_TEMPLATE": "waste",
}

#: 片段里那块板的 id。片段只演一块板(标称轨迹), 并行多板是实时页 PlateBinding 的事。
PLATE_CLIP_ID = "plate"

#: 视觉纠偏补光灯的 id(与 rig_map.lights 逐字一致)。
VISION_LIGHT_ID = "vision_fill"
#: 补光渐亮/熄灭时长(秒)。真机 DO7 是瞬时通断, 但 LED 到稳态、相机自动增益收敛都要一点
#: 时间, 而且**一帧爆闪在动画里既看不清也很廉价** —— 计划里明确要求"渐亮 → 稳态 →
#: 快照瞬间微过曝 → 熄灭", 不做成单帧。
VISION_LIGHT_RISE_S = 0.25
VISION_LIGHT_FALL_S = 0.35
#: 快照瞬间的微过曝: 稳态 1.0, 曝光那一下顶到这个系数再落回。
VISION_LIGHT_FLASH = 1.0
#: 稳态亮度(0..1 系数)。留一点余量给上面的过曝。
VISION_LIGHT_HOLD = 0.82
#: 触发拍照本身占的时间(秒) —— 相机往返, 没有配置依据, 取一个不夸张的观感值。
VISION_SHUTTER_S = 0.3

#: 气缸类动作 -> (机构 id, 取哪个入参当目标态)。这些动作在真机上是"写一个目标位",
#: 在动画里就是把对应 actuator 驱到 0/1。机构当前多为 rigged:false(无几何),
#: MachineStateDriver.setActuator 找不到条目会静默返回 false —— 片段照播、气缸不动,
#: 与"data-only 不驱动几何"的既有纪律一致, 不因此拒绝生成片段。
CYLINDER_ACTIONS = {
    "staging_a.locator_a": ("sta_powder_locator", "target"),
    "staging_a.locator_b": ("col_bottle_locator", "target"),
    "photoscrape.press_cylinder": ("ps_press", "pressed"),
    "photoscrape.locate_cylinder": ("ps_locator", "clamped"),
    "collect.bottle_locator": ("col_bottle_locator", "target"),
}

#: 无参气缸动作 -> (机构 id, 目标值)。上位机把"伸出/缩回"做成了两个动作码而不是一个带参动作。
CYLINDER_ACTIONS_FIXED = {
    "sampling.place_locate": ("smp_locator", 1.0),
    "sampling.place_release": ("smp_locator", 0.0),
    "collect.clamp": ("col_clamp", 1.0),
    "collect.release_clamp": ("col_clamp", 0.0),
    "collect.extend": ("col_extend", 1.0),
    "collect.retract": ("col_extend", 0.0),
}

#: 展缸盖开合 -> (联动组模板, 目标值)。缸号 1-4 = PLC 组 1 = dev_t1_cyl1..4,
#: 缸号 5-8 = 组 2 —— 这个配对的真源是 rig_map.tanks.first_rack(按实物指认过),
#: manual_points 的 dev_t{架}_cyl{层} 与 PLC 的 Expand_Group/Expand_Number 都从它派生。
#: retract(31) = 放板缸回原点 = 开盖; extend(32) = 到动点 = 关盖。
#:
#: init(10) 与 rinse_fill(21) 不是"专门开合盖"的动作, 但它们的 desc 明写了会驱动同一个缸:
#: init "所选缸的气缸、进液、排液、吹气手/自动输出全部清零"(清零 = 回原点 = 开盖),
#: rinse_fill "把所选缸的进液阀、排液阀和气缸自动输出都置TRUE"(置位 = 到动点 = 关盖)。
#: 它们另外还驱动泵与阀, 那部分归 FLUID_ACTIONS 说明 —— 三维暂不表现流体。
TANK_LID_ACTIONS = {
    "develop.plate_retract": 0.0,
    "develop.plate_extend": 1.0,
    "develop.init": 0.0,
    "develop.rinse_fill": 1.0,
}

#: 全部 **rigged** 机构的起手态 -> (值, 出处)。一条都不许拍脑袋。
#:
#: 为什么非有它不可: 片段的 home 段此前只有 axis_mm/joints_deg/liquid_ml, 而前端
#: clipSchema.js 对缺失的 home 一律 `?? 0`; 另一边 MachineStateDriver.home() 把机构复位到
#: **CAD 基位**(零位移)。两者只在 outputRange **升序**时才碰巧一致 —— manifest 里有 10 个
#: 机构是**降序**的(col_lift [70,0] / col_clamp [7.5,0] / 8 条缸盖 [47.36,0]), 它们的
#: CAD 基位对应 value **1**。2026-08-06 实测后果: col_lift 264/270 段停在落位、col_clamp
#: 263/270 段停在紧闭、8 个缸盖从 t=0 就开着(开盖那步成了 0→0 的空动作)。
#:
#: 消费端早就就绪 —— clipSchema.js 为 home.actuators/home.linkages 逐条建通道, 即使该机构
#: 一步都没有(理由见它那段"只在 home 里声明、没有任何步骤的量会被静默丢掉"的注释)。
#: 所以这是**纯生产端**缺口, 前端一行都不用改。
#:
#: 手写片段 clips/develop.lid_cycle.yaml 的头注释早就把这个坑和解法都写下来了
#: ("home 必须显式全 1 —— 通道隐式初值是 0, 缺省会让未到步骤的盖在 t=0 就呈开盖态,
#: 与 rig.home() 恢复的关盖基准位打架"), 编译器一直没学会。
#:
#: ⚠ 覆盖**全部** rigged 机构而不只是被本片段驱动的那些。"驱了才声明"正是今天缺陷的形状:
#: 没驱动的机构没有通道, 于是停在 CAD 基位, 而那对降序的十条是反的。
MECHANISM_HOME: dict[str, tuple[float, str]] = {
    # ── 收集工位: 五个输出的原点由 PLC 动作码 10 一次性定义 ──────────────────
    "col_press": (0.0, "SEQUENCE_ACTIONS[collect.init] 动作码10「下压气缸·回原点」"),
    "col_clamp": (0.0, "SEQUENCE_ACTIONS[collect.init] 动作码10「夹持气缸·松开」"),
    "col_lift": (0.0, "SEQUENCE_ACTIONS[collect.init] 动作码10「升降气缸·回原点」"
                      "; rig_map col_lift 注: 值0 = 抬起 70mm 让瓶子进出"),
    "col_extend": (0.0, "SEQUENCE_ACTIONS[collect.init] 动作码10「伸缩气缸·回原点」"
                        "; rig_map gap_check 断言 CAD = 缩回"),
    # ── 拍照刮板工位 ────────────────────────────────────────────────────────
    "ps_shade": (0.0, "SEQUENCE_ACTIONS[photoscrape.init] 动作码10「遮光气缸·回上位」"),
    "ps_rotate": (0.0, "SEQUENCE_ACTIONS[photoscrape.retr_stoprot]「复位到刮取位」"),
    "ps_press": (0.0, "rig_map ps_press 注: CAD 基准态是抬起(值0 = 松开 = 零位移)"),
    "ps_locator": (0.0, "rig_map ps_locator gap_check 断言 CAD = 松开(净空 2.5mm)"),
    # ── 上样工位 ────────────────────────────────────────────────────────────
    "smp_locator": (0.0, "CYLINDER_ACTIONS_FIXED[sampling.place_release] -> 0"
                         "; rig_map gap_check 断言 CAD = 松开"),
    # ── 机器人末端 ──────────────────────────────────────────────────────────
    "rob_flip_suction": (0.0, "rig_map 头注: 吸盘 1=上翻, 0=下翻(用户确认)"),
    "rob_grip_plate96": (0.0, "rig_map 三态: 0 = 张开 = GLB 基准位"),
    "rob_grip_vial": (0.0, "rig_map 三态: 0 = 张开 = GLB 基准位"),
    # ── 展缸盖 ×8: 唯一取 1 的一族 ──────────────────────────────────────────
    # 缸盖静置时是**关着**的(挡溶剂挥发), 而 1 恰好也是 GLB 建模基准态 —— 出处是手写片段
    # clips/develop.lid_cycle.yaml 的头注释, 它当年就是为这个坑写的。
    **{f"dev_t{group}_cyl{index}": (
        1.0, "clips/develop.lid_cycle.yaml 头注: 1 = 动点 = 关盖 = GLB 建模基准态"
             "; 该片段手写声明 home 全 1")
        for group in (1, 2) for index in (1, 2, 3, 4)},
}

#: 工位轴的静态停放位(毫米) —— MECHANISM_HOME 的轴类姊妹表, 同一条纪律: 值必须有出处。
#:
#: 只收"PLC 初始化把它送到**非零常量**停放位"的轴; 其余轴(4X/3Y/5Z/6X 等)的 PLC 回零
#: 目标恰是 0, 与前端隐式初值一致, 不必列。SEAT_AXES 是另一类(取放时的**在位**声明,
#: 值随点表变), 两表键不相交。
#:
#: 9X 缺声明的实测后果(2026-08-06): flow.photoscrape_load(拍照刮板-上料)全程刮板停在
#: 未让位端 —— clipSchema.js 对"有步无 home"的轴通道给 0mm, MachineStateDriver.home()
#: 对无通道的轴停 CAD 基位(-48.67), 两条路都不是 PLC 真实的 335 停放位, 而"准备"结尾
#: 明明把刀送到了 335。ClipBuilder.__init__ 把本表播进 home_axis_mm(声明起手态)与
#: axis_mm(让重复的回停放位步按零位移跳过, 见 emit_axis)。
STATION_AXIS_HOME: dict[str, tuple[float, str]] = {
    "axis_9x": (335.0,
                "PLC 拍照刮板.xml: 刮板轴9XDATE.fAbsTarget:=335(让位-刮板X到放板位); "
                "同源 STATION_AXIS_ACTIONS[photoscrape.cam_x335] 与 "
                "SEQUENCE_ACTIONS[photoscrape.init/align_home](9X 的\"回零\"实际是 335)"),
    "axis_10z": (0.0,
                 "PLC PhotoScrape_L2 A10_init: 10Z 绝对回 0(抬刀); "
                 "SEQUENCE_ACTIONS[photoscrape.init] 首步同源"),
}

#: 刮取演示的**标称条带**(板 cm 帧 bbox: x0, y0, x1, y1; 帧定义与 controller/plate_coords.py
#: 同源: 原点=板左下角, x=机床X, y=机床Y)。
#:
#: 真值是运行期视觉的 summary.json bands[].bbox_cm, **每次运行都不同, 编译期拿不到** ——
#: 与 PLATE_VISION_ASSUMPTION 同一条纪律: 编不出来的运行期事实写成看得见的显式假设,
#: 并随 flowNotes 落进片段。量级取"横贯大半板宽的中部条带": 带长 160mm、带高 20mm
#: (20mm 带高按刀径 2mm × (1−重叠 0.4) = 1.2mm 步距折算 ≈ 真机 17 列的量级, 自洽)。
SCRAPE_DEMO_BAND_CM: tuple[float, float, float, float] = (2.0, 8.0, 18.0, 10.0)

#: 粉桶粉柱的片段 id, 与 gen_twin_manifest 的 CONSUMABLE_CONTENT_KINDS 键逐字对应
#: (id = f"powder_{seat.replace('-','_')}")。
#:
#: **编译期常量, 刻意不查 manifest**: 粉柱几何还没进管线时片段照编、前端空跑不报错
#: (setter 查不到 entry 就静默不动) —— 与 CYLINDER_ACTIONS 那批 data-only 机构同一条
#: 降级路径, 等管线落地自动生效。
SCRAPE_POWDER_ID = "powder_scrape_holder"

#: 收集工位那只粉桶里的粉柱 id(同上一条纪律)。桶是同一只 —— 机器人把它从刮板夹具
#: 搬到收集夹具 —— 但三维里是**两个实例**, 故粉柱也是两根, 按段各自声明起手态。
COLLECT_POWDER_ID = "powder_collect_holder"

#: 演示条带面积**折算系数**: 把 SCRAPE_DEMO_BAND_CM 折算到真机参考带的量级.
#:
#: ⚠ 这个系数不是观感微调, 少了它整个分层就看不出来 —— 而且**画面正常、无任何报错**:
#: SCRAPE_DEMO_BAND_CM 是 160×20mm = 3200mm² 的**演示夸张带**(见上方注释: 带高 20mm
#: 是为了在画面上看得见), 配 total_depth 1.0mm × bulk 1.6 得 5120mm³, 而粉腔容量只有
#: 19410.7mm³ —— 乘上观感放大 ×6 之后两刀的液位**双双 clamp 成 1.000**, 即"第一刀就满桶,
#: 第二刀还是满桶", 分层完全不可见。
#: ×0.15 后有效面积 = 480mm², 正是真机参考带 8×0.6cm(plc_photoscrape.yaml:103)的面积,
#: 两刀分别是 0.119 / 0.237 —— 清晰可辨且都不到饱和。
#: 真机上这个折算不存在: 面积由视觉 summary 逐次给出, 本系数只补偿演示带的夸张。
SCRAPE_DEMO_POWDER_AREA_RATIO = 0.15

def demo_powder_total_mm3(calib: dict) -> float:
    """一次完整刮取(全部刀次跑完)能吸进桶里的粉量, mm³.

    式子只有这一份: emit_scrape 逐刀累加到它, PHASE_ENTRY_STATE 的起手态按它的倍数
    声明 —— 两处各写一遍就会漂成"刮取段吸了 768、收集段起手 750", 而画面上看不出来。
    与后端账本 ScrapeArrays.scrape_volume_mm3 同构(面积 × 切深 × 松散系数)。

    Args:
        calib: load_gcode_calib 产物
    Returns:
        粉量 mm³
    """
    x0, y0, x1, y1 = SCRAPE_DEMO_BAND_CM
    area_mm2 = ((x1 - x0) * 10.0) * ((y1 - y0) * 10.0) * SCRAPE_DEMO_POWDER_AREA_RATIO
    return area_mm2 * calib["total_depth_mm"] * calib["bulk_factor"]


#: 刮取演示的列数。真机列数由刀覆盖自动推导 ≈ 带宽/步距 = 160/1.2 ≈ 133 列
#: (app.yaml gcode.tool.cutter_diameter_mm × (1−overlap_ratio)) —— 逐列演出来是两分钟的
#: 重复画面, 拍平到 5 列并记 flowNotes(与"for 循环只编第 1 轮"同一类拍平)。
SCRAPE_DEMO_COLUMNS = 5

#: 板名义边长(cm)。CAD 名义 200mm, 与前端 plateGeometry.PLATE_NOMINAL_M 同源;
#: 只用于把标称条带换算成板上归一位置, 不参与任何轴定位。
SCRAPE_DEMO_PLATE_CM = 20.0

#: 刮刀主轴 id, 与 rig_map.spindles[].id 逐字一致(前端按 id 直配, 错一个字就静默不转)。
#: PLC 没有主轴的独立信号, 所以"刀在转"= photoscrape.scrape(A40) 这条动作在跑 ——
#: 编译期与实时期用的是同一条判据(实时侧见 TwinBindings 的 vm_node 分支)。
SCRAPE_SPINDLE_ID = "ps_spindle"

#: 点样站"机床 mm → 板 cm"的站位映射(x: 6X 载喷射头, y: 7Y 载点样座/板)。
#:
#: 点样站没有刮板站那种 app.yaml gcode.plate_origin_* 标定(6X/7Y 从未参与视觉闭环),
#: 所以这张映射是**演示标定常量**, 不是现场标定值 —— 但带端点毫米**不抄进来**:
#: emit_spot 实读点表 spot_pose.x_start/x_end/y_height(现场重新示教后三维跟着变),
#: 只有"毫米零点在板上的落点"冻结在此。数值出处(双链交叉, 残差如实记):
#:   x_origin_mm = 61.2 —— CAD/rig_map 推导链: axis_6x sign=-1 / zero_offset=-4.001,
#:     喷射头沿 glTF −Z 扫, 板 `玻璃-1` z∈[−29.1, 170.9](200mm, rig_map axis_6x 证据
#:     节), 反解 6X 毫米值与板 cm x 的仿射得 x_cm=(mm−61.2)/10。取 CAD 链为准的理由:
#:     它与驱动演示动画的是同一套 rig_map 数字, 色带端点与画面里的喷头逐帧自洽。
#:     交叉核对: vision_output/TEST-PS-001 origin_band 反推 x_origin≈54.1(Δ7mm ——
#:     喷嘴口≠零件包围盒中心的量级; 且该案例是 data/samples/case1 罐头照, 无法确证
#:     与现役示教值同源, 故只作旁证)。
#:   y_origin_mm = 18.4 / y_dir = -1 —— **在景实测喷嘴尖定标**(2026-08-07, worldBox 探针):
#:     扫线时刻(7Y=−20)量 `喷射头-1` 子树世界包围盒尖端轴线, 转板局部得 y_cm=3.837,
#:     三采样点恒定(6X 不动横向), 悬高实测 5.5mm 与 rig_map axis_6x 证据逐字吻合(量的
#:     确实是喷嘴尖) ⇒ y_origin = −20 + 38.4 = 18.4。方向(y_dir=−1)由演示页目检定:
#:     首版 +1 把带画到离喷头远的那条边(用户报反), 翻正后再消 10.8mm 原点偏。
#:     历史链(降为旁证): 罐头视觉案例 origin_band y_cm=2.7586 反推 y_origin=7.6 ——
#:     与在景实测差 10.8mm, 说明 data/samples/case1 的照片并非本 CAD 位形下的喷涂,
#:     以在景自洽为准(色带必须与动画里的喷头同线, 那才是演示的验收判据)。
#:   x_dir = +1 —— x 侧与扫线运动同构(cm x 随 6X 毫米增大而增大), 前端世界向由同一
#:     manifest 轴规格推出, 构造上自洽; 若现场重标发现反向, 只改这里(前端经 motion-map
#:     的 spotBandCalib 消费同一份, 见 machineDirsWorld)。x_origin 已被同一轮在景实测
#:     反向确认: 扫线两端(补掉 seek 掐头去尾的 5% 行程后)各自反解得 61.15, 与 61.2
#:     差 0.05mm。
#: ⚠ 锚错 1cm 画面照样"看着对"(色带仍横在板上) —— 本仓最忌惮的错型。验收动作:
#:   演示页目检色带与喷头扫线**同线**(它们由同一 rig 驱动, 错位/错边即映射错);
#:   自动断言在 shot_plate_traces.py(worldBox 尖端 vs 色带线, <2mm)。
SPOT_BAND_CALIB = {
    "x_origin_mm": 61.2,
    "x_dir": 1,
    "y_origin_mm": 18.4,
    "y_dir": -1,
}

#: 点样色带的半宽(cm)。带宽无任何参数化真源(y 只给一条示教行), 视觉实测值是:
#: TEST-PS-001 origin_band bbox 高 76px / 1769px ROI ≈ 8.6mm ⇒ 半宽 0.45cm。
#: ⚠ 现值 0.225 是 2026-08-09 用户要求的**观感减半**, 不是新的实测结论 —— 别把它
#:   误读成标定漂移。要恢复实测值只需改回 0.45 并重编含 spotRegions 的片段
#:   (sampling_execute / sampling_cycle / sampling_multi_* / pf_s2_spot / ptlc_full_v2)。
#:   它同时经 motion_map_document 的 spotBandCalib.bandHalfCm 导给实时页, 一处改两处变。
SPOT_BAND_HALF_CM = 0.225

#: 展开润湿前沿的目标高度(板 cm 帧 y)。展开过程中没有板面高度真值(液位视觉给的是
#: ROI 百分比, 无 cm 映射, 见 waterlevel.yaml/water_level_calib.json), 唯一有 cm 的
#: 是刮板工位事后拍照的 summary.solvent_front.y_cm —— TEST-PS-001 实测 14.72cm。
#: 与 SCRAPE_DEMO_* 同一条纪律: 编不出来的运行期事实写成看得见的显式假设 + flowNotes。
WET_FRONT_TARGET_CM = 14.7

#: 展开润湿上行的演示时长(秒)。真值是液位等待(hard_cap 3600s, 实际几百到上千秒),
#: 压缩到与排液(10s)同量级的一段, 真值记 flowNotes —— 与扫线步 max_s 钳制同款处理。
WET_DEMO_RISE_S = 8.0

#: 轴行程由**运行期**决定的动作 -> (说明, 时长秒)。
#:
#: 这些动作在真机上不是绝对定位: 1Z/2Z 是"向上/向下 JOG 搜光电开关跳变"(停在哪取决于
#: 仓里还剩几张板), 7Y 的目标存在 PLC 的 HMI 数组槽里、PC 侧配置根本没有这个数。
#: 所以片段只出一个**有语义的时间格**, 让流程的节奏和步骤表是对的, 但**绝不编一个绝对
#: 位置**去驱动轴 —— 编出来的堆高/轴位看着很真, 却没有任何指标会告诉你它是假的。
#: (同一处理见 vision.capture_plate_offset。)
#: 上料/下料仓的取料高度(毫米)。**标称值** —— 真机是"向上 JOG 搜光电", 停位随仓内
#: 张数变(触发位 = z_empty − N×pitch), 那是运行期量。这里取 PC 侧搜索窗口上界
#: (config/points/plc/feedlift.yaml 的 feedlift_1z_search_high = 512, 与实测
#: z_empty 512.127/512.515 同量级)作为演示的标称取料高度。
#:
#: 交叉验证: 以展开缸为基准反推, 板锚点需要抬高 530.7mm(上料)/534.1mm(下料)才能落到
#: 机器人取放点; 与 512 差 18.6/21.6mm, 落在这几个工位已知的 13~19mm 整站摆位底噪里。
#: 也就是说 **CAD 建模位 ≈ 1Z 零位(板堆完全降下), 取料发生在 ~512~530** ——
#: 此前把零位当成取料点是错的, 板因此被画在仓底、悬在吸盘下方约半米。
FEEDLIFT_PICK_MM = 512.0
#: feed_lower 的让位量: 动作定义里写死的相对 −5mm(plc_feedlift.yaml 动作码 12)。
FEEDLIFT_LOWER_MM = FEEDLIFT_PICK_MM - 5.0

#: 工位轴的绝对定位动作 -> (轴 id, 目标毫米, 标签, 标称速度 mm/s)。
#: 目标值全部有出处, 不是编的: 见每条末尾的注明。
STATION_AXIS_ACTIONS = {
    "feedlift.feed_raise":  ("axis_1z", FEEDLIFT_PICK_MM,  "上料1Z·升轴到取料光电", 120.0),
    "feedlift.feed_lower":  ("axis_1z", FEEDLIFT_LOWER_MM, "上料1Z·降轴5mm让位", 60.0),
    "feedlift.feed_clear":  ("axis_1z", 0.0,               "上料1Z·降轴至光电消失", 120.0),
    "feedlift.unload_ready": ("axis_2z", FEEDLIFT_PICK_MM,  "下料2Z·升到放废料位", 120.0),
    "feedlift.unload_bury":  ("axis_2z", 0.0,               "下料2Z·埋料至光电消失", 120.0),
    # 9X 载的是**刀**: 335 是"让位-刮板X到放板位"(PLC 硬编码), 把刀退出板区好放板
    "photoscrape.cam_x335": ("axis_9x", 335.0, "刮板9X·刀让位到335", 100.0),
}

#: 埋料动作 -> 被埋的那个料仓落点。滑车一降, **坐在这个落点上的**板就随行进仓、
#: 在托边处并入板堆(见 ClipBuilder._bury_plate_if_needed); 板在机器人手上或坐在
#: 别的落点时与这次埋料无关, 不得收走 —— 此前不分青红皂白地 hide, pf_s11_unload
#: 开头的"测量清零"埋料把机器人手上的板都收掉了, 落位那一刻又凭空冒回来。
PLATE_BURY_SLOTS = {
    "feedlift.unload_bury": "waste",
    "feedlift.feed_clear": "feedlift",
}
PLATE_BURY_ACTIONS = frozenset(PLATE_BURY_SLOTS)

#: 板随滑车下降的停画高度(mm, 轴口径)。
#:
#: 出处: verify_plate_clearance.LEDGE_HANDOFF + work/plate_clearance.json 逐三角形扫掠
#: (2026-08-05) —— 512mm 行程里板与固定结构的交叠**只在**托边那一档(waste 为
#: axisMm∈[-7.5,2.5]、feed 为 [-2.5,7.5], 深 25.0mm), 其余档位 ≤0.61mm, 低于
#: verify_plate_clearance.MAX_PENETRATION_MM(1.0)的判红线。10mm 同时压住两仓的
#: 交叠带上界(2.5/7.5), 是"板还坐在滑车顶着的板堆上"的最后一个净空档。
#: 不直接 import verify_plate_clearance 取数: 那个模块级联 gen_twin_manifest, 编译器
#: 不该为一个常量背上整条 manifest 链。
PLATE_BURY_RIDE_STOP_MM = 10.0

#: 落点 -> (板托座所骑的工位轴, 机器人来取放时该轴必须在的毫米值, 出处)。
#:
#: 为什么要有它: 这四个落点的板托座**骑在工位轴上**, 轴不在位, CAD 锚点就停在建模位而
#: 机器人去了另一处。2026-08-05 实测这个差: 点样座 7Y 与刮板台 8Y 在法兰系下差 134.0mm,
#: 上下料仓差 530mm —— 板画出来就是飘在吸盘外面。片段自己不驱这些轴时(单片段的常态),
#: 就把它写进 `home.axis_mm` 声明成起手状态: 那不是编造运动, 板本来就在那个高度等着。
#:
#: 值一律要有出处。verify_plate_seats 会拿它摆位后复核各站残差是否一致, 改错了会红。
#: 值有两种形态: float = 常量(出处见第三元素); "point:<key>" = **实读点表**(见
#: seat_axes_resolved)。会随现场示教变的位置一律用后者。
SEAT_AXES: dict[str, tuple[str, float | str, str]] = {
    # 上下料仓: 顶升到取料光电位(PLC 动作码 11/21, 见下面 FEEDLIFT_PICK_MM)
    "feedlift": ("axis_1z", 512.0, "FEEDLIFT_PICK_MM (PLC FeedLift_L2 A11)"),
    "waste": ("axis_2z", 512.0, "FEEDLIFT_PICK_MM (PLC FeedLift_L2 A21)"),
    # 刮板台: 放板位 = 0。PLC PhotoScrape_L2 的 A10_init_初始化 / A35_cam_回零 都绝对回 0,
    # 上位机侧同一份写在下面 SEQUENCE_ACTIONS 的 photoscrape.init / align_home。
    "scrape_table": ("axis_8y", 0.0, "PLC PhotoScrape_L2 A10/A35 放板位=0"),
    # 点样座: 放板位 = `HMI_点样轴7Y.position[1]`(PLC Sampling_L2/A31_放板移轴 原文)。
    # 2026-08-05 OPC 实读 = 56.0, 已收进 config/points/plc/spotting.yaml 的 spot_7y_place,
    # 故这里**实读点表**而不是写常量 —— 现场重新示教后三维跟着变, 与地轨 load_rail_slots
    # 同一条纪律(常量兜底会在重新示教后安静地演一个陈旧位置)。
    #
    # 此前这里是 -40.85, 出处写着"几何反解, 待现场读数": 拿刮板台 8Y=0 定出 rotary-up 的
    # 刀具基准后一维搜索 7Y 而得。实读一到, 这个**毫米**表述作废(该用实读的 56.0)——
    # 但被证伪的只是毫米数, 不是反解本身: 反解给出的**位移** δ=−80.85mm 在三个不同
    # zero_offset 下逐次吻合(z=40 报 −40.85mm、z=56 报 −24.85mm, δ 恒等), 是与标定无关的
    # 几何量。2026-08-05 正是拿它与实读 56.0 联立, 判出 rig_map 的 axis_7y **sign 反了**
    # (+1 下无解), 订正为 sign=−1 / zero_offset_mm=−24.85 —— 推导见该轴条目。
    "spot_seat": ("axis_7y", "point:spot_7y_place", "PLC HMI_点样轴7Y.position[1] 实读(点表)"),
}


@lru_cache(maxsize=8)
def seat_axes_resolved(control_root: Path) -> dict[str, tuple[str, float | None, str]]:
    """把 SEAT_AXES 里的点位引用解成毫米。

    值有两种形态: float 是常量(出处见第三元素); `"point:<key>"` 表示**实读点表**。
    后者是给"现场会重新示教"的位置用的 —— 抄成常量的那份在重新示教后不会报错, 只会
    安静地演一个陈旧位置(地轨的常量兜底就是这么被删掉的)。

    Args:
        control_root: 上位机仓库根

    Returns:
        {落点: (轴 id, 毫米 或 None, 出处)}; 点表里查不到时值为 None 并在出处里写明
    """
    points = load_servo_points(control_root)
    resolved: dict[str, tuple[str, float | None, str]] = {}
    for slot, (axis_id, value, why) in SEAT_AXES.items():
        if isinstance(value, str) and value.startswith("point:"):
            key = value[len("point:"):]
            found = points.get(key)
            resolved[slot] = ((axis_id, found, f"{why} = {found}") if found is not None
                              else (axis_id, None, f"{why} —— 点表里没有 {key}"))
        else:
            resolved[slot] = (axis_id, value, why)
    return resolved


@dataclass(frozen=True)
class PhaseEntry:
    """一条工位阶段片段的起手态声明(见 PHASE_ENTRY_STATE)。

    Attributes:
        liquid_after: 前置段脚本名。缸内起手液量 = 该脚本按其**默认配方**跑完后的液量,
            现算不写常量。空串表示这一段起手是空缸(不声明)。
        plate_at: 板的起手落点模板, 按片段入参格式化(如 `"tank:{tank}"`)。空串表示
            这一段起手时板不在场(或由片段自己的吸/放动作交代)。
        why: 出处 —— 哪条上层流程规定了这个前后关系。改表必须同时改这句。
        states: 前置段留在场上的载荷 id(manifest.states 里的 id, 如接粉收集器)。
            与 plate_at 同一条理由: home() 把 states 全部置 false, 前置段放进来的
            载荷不声明就整段隐身 —— 典型是 photoscrape_process 末尾"翻料倒粉",
            粉桶(STA_SCRAPE_HOLDER)不点亮就是在空翻一只气缸。
        powders: 前置段留在桶里的粉 (粉柱id, **满刮取的倍数**, 洗脱色相位 0..1, 出处)。
            倍数而不是绝对 mm³: 粉量随 app.yaml 的切深/松散系数变, 抄一个 768 进来就是
            第二份真源 —— 实际值由 demo_powder_total_mm3(calib) × 本倍数现算, 与刮取段
            逐刀累加到的终值同源。1.0 = 前置段完整刮了一趟。
            与 liquid_after 的**计算式**刻意相反, 这里是**声明式**, 三条理由:
              · 真源不同 —— 粉量编译期算不出(真机走视觉轮廓, 演示走标称带折算),
                不像液量那样"把前置脚本按默认配方跑一遍"就有;
              · 代价不同 —— photoscrape_process 是 67 步带 IK 的流程, 为了取一个粉量
                把它整段预跑一遍不值当;
              · 承接方式不同 —— 粉是**换实例**(机器人把桶整只搬走)而不是搬体积。
            与 states 同一条清场理由: home() 把粉一律归零(空桶是静止态), 不声明就是
            "收集-执行在演一只空桶"。
        mechanisms: 前置段留下的机构状态 (机构id, 值, 出处) —— 在 MECHANISM_HOME 全局
            起手态上按段覆盖。与 states 同一条理由: 全局表只描述"动作码 10 初始化后"的
            静置态, 而阶段片段接的是**前一段的收尾**。典型是收集上料: A41(scrape_finish)
            把翻料缸留在倒粉位(值1), A42 复位排在机器人取桶**之后** —— 全局 home 的 0
            会让粉桶以未翻形态被按"翻料位示教点"抓走, 观感即"隔空虚空转化"。
    """

    liquid_after: str
    plate_at: str
    why: str
    states: tuple[str, ...] = ()
    mechanisms: tuple[tuple[str, float, str], ...] = ()
    powders: tuple[tuple[str, float, float, str], ...] = ()


#: 工位阶段片段的**起手态**。
#:
#: 为什么要有它: 单段片段不含前置段, 于是"缸里已注好液""板已经在缸里"这些由前置段留下的
#: 状态在片段里无从体现 —— 而运行期的清场是无条件的: MachineStateDriver.home() 把 8 个缸
#: 全部 setLiquidMl(id, 0), MachineRig.home() 紧跟着 plateStage.clear(), 且 ClipPlayer 每
#: 一次向后 seek 都要走这一遭。片段自己不声明, 就永远是空缸无板。
#:
#: flow.develop_cycle.* 之所以是对的, 纯粹因为 run_script 被内联成一条时间轴, 靠连续性
#: 蒙对 —— 不是因为它声明了什么。单段片段没有那份连续性, 只能显式声明。
#:
#: 与 SEAT_AXES 同一条纪律: **声明的是状态, 不是编造运动** —— 板本来就在缸里等着, 液本来
#: 就注好了。值一律要有出处(PhaseEntry.why), 液量更是现算而不是抄一个 60.0 进来:
#: develop_prepare 的 develop_volume_ml(20) × up_liquid_repeat_count(3) 改了, 三维跟着变。
PHASE_ENTRY_STATE: dict[str, PhaseEntry] = {
    # 展开四段式(develop_cycle: prepare -> load -> execute -> unload)
    "develop_load": PhaseEntry(
        "develop_prepare", "", "develop_cycle: prepare 已注液, 板是放进满缸的"),
    "develop_execute": PhaseEntry(
        "develop_prepare", "tank:{tank}",
        "develop_cycle: prepare 注液 + load 已把板放进缸并夹持"),
    # unload 不在表里且不该进来: 执行段末的 develop.drain 已把缸排空(Tank_State=98),
    # 而它自己的 robot_tank_pick 会经 _plate_transfer 发出"板在位"起手式。
    #
    # 并行流程(11_parallel)里的同两段。pf_s3_tank_prep 的 body 就是 run_script:
    # develop_prepare, 故液量出处与上面完全同源。
    "pf_s5_to_tank": PhaseEntry(
        "develop_prepare", "", "pf_s3_tank_prep 内联 develop_prepare 已注液"),
    "pf_s6_develop_wait": PhaseEntry(
        "develop_prepare", "tank:{tank}",
        "pf_s3 注液 + pf_s5(内联 develop_load) 已把板放进缸"),
    # 拍照刮板执行段: 板与接粉收集器都是前置段留下的。出处是 photoscrape_process.yaml
    # body 首行 comment(逐字): "接粉收集器已由 transfer_collector_staging_a_to_scrape
    # 放入并定位; 板已由 photoscrape_place 放入定位"。刮板台的 SEAT_AXES 起手位 = 8Y 0.0。
    "photoscrape_process": PhaseEntry(
        "", "scrape_table",
        "photoscrape_process.yaml body 首行 comment: 板由 photoscrape_place 放入定位, "
        "接粉收集器由 transfer_collector_staging_a_to_scrape 放入",
        states=("STA_SCRAPE_HOLDER",)),
    # 点样执行段: 板是前置段(sampling_load)留在点样座上的。SEAT_AXES 把 spot_seat 解到
    # spot_7y_place(实读 56.0 = 放板位, 恰是 load 收尾把板放下的位置), 随后片段自己的
    # spot_band_layer 步演出 56 → 喷涂位的真实落位 —— "驱过不覆盖"护栏保证不被抹掉。
    "sampling_execute": PhaseEntry(
        "", "spot_seat",
        "sampling_cycle: load 已放板(robot_suction_put station_id=spotting)并夹紧定位"
        "(sampling_load 尾步 sampling.place_locate 动作码32)",
        mechanisms=(("smp_locator", 1.0,
                     "sampling_load 尾步 sampling.place_locate(动作码32)夹紧未复位"),)),
    "sampling_multi_execute": PhaseEntry(
        "", "spot_seat",
        "同 sampling_execute: 多样品执行段同样接在 load 之后, 板已在点样座",
        mechanisms=(("smp_locator", 1.0, "同 sampling_execute"),)),
    # 并行流程里的同一段: pf_s2_spot 内联 sampling_execute, 前置段 pf_s1_load 内联
    # sampling_load(见 11_parallel/pf_s1_load.yaml 尾步), 板同样已在点样座并夹紧。
    "pf_s2_spot": PhaseEntry(
        "", "spot_seat",
        "pf_s1_load 内联 sampling_load 已放板并夹紧(serial_v1/parallel_v1 配方序)",
        mechanisms=(("smp_locator", 1.0, "同 sampling_execute"),)),
    # 收集四段式(collect_cycle: prepare -> load -> execute -> unload)。
    #
    # 翻料缸 ps_rotate: photoscrape_process 收尾 scrape_finish(A41) 把接粉收集器翻到
    # 倒粉位(值1)且**不复位** —— 复位(A42 retr_stoprot)排在 collect_load 里机器人取桶
    # 之后(collect_load.yaml 注释逐字: "接粉收集器已由机器人取走并退出后, 才允许旋转/
    # 停旋转气缸复位")。粉桶随 ps_rotate 转 180°(rig_map scrape-holder note), 起手不
    # 声明就是"未翻的桶被按翻料位示教点抓走"。片段内 retr_stoprot 照旧把 1 驱回 0。
    # 粉的承接: 桶是**换实例**搬过去的(机器人从刮板夹具取桶 → 放进收集夹具), 于是
    # 起手声明也换 id —— 上料段起手时粉还在刮板工位那只桶里(POWDER_SCRAPE_HOLDER),
    # 执行/下料段起手时已在收集工位那只(POWDER_COLLECT_HOLDER)。
    # 这正是"声明式而不是计算式"的由来: 没有任何"体积搬运"可算, 换的是实例。
    "collect_load": PhaseEntry(
        "", "", "photoscrape_process 收尾 A41 已翻料倒粉; A42 复位在取桶之后",
        mechanisms=(("ps_rotate", 1.0,
                     "A41 scrape_finish 后未复位; A42 排在取桶之后(collect_load.yaml)"),),
        powders=((SCRAPE_POWDER_ID, 1.0, 0.0,
                  "photoscrape_process 刮完一趟, 粉在刮板工位那只桶里等着被取走"),)),
    "collect_cycle": PhaseEntry(
        "", "", "周期起手接续 photoscrape_process 的翻料收尾, 同 collect_load",
        mechanisms=(("ps_rotate", 1.0, "同 collect_load"),),
        powders=((SCRAPE_POWDER_ID, 1.0, 0.0, "同 collect_load"),)),
    # 执行段: 全程无机器人取放 —— 瓶与粉桶都是上一段(collect_load)留在收集工位上的,
    # 不点亮就是空治具做动作; 伸缩缸以 collect.extend(动作码22)伸出收束, 起手=1。
    # (瓶/桶的目的实例挂在 ACTUATOR_COL_EXTEND / ACTUATOR_COL_LIFT 下, 见 rig_map
    # station_seats —— col_extend 起手 1 时瓶随治具停在伸出位, 几何自洽。)
    "collect_execute": PhaseEntry(
        "", "", "collect_load 已放入粉桶(收集夹具夹持)与收集瓶, 尾步 collect.extend 伸出",
        states=("STA_COLLECT_BOTTLE", "STA_COLLECT_HOLDER"),
        mechanisms=(("col_extend", 1.0, "collect_load 尾步 collect.extend(动作码22)"),),
        # 粉已随桶搬到收集工位。tint 仍是 0(未洗) —— 本段演的正是淋洗, 洗脱色由片段
        # 自己的 powder tint 步驱起来, 起手就写 1 等于"还没洗就已经变色了"。
        powders=((COLLECT_POWDER_ID, 1.0, 0.0,
                  "collect_load 已把装着粉的桶放进收集夹具; 本段起手粉未洗"),)),
    # 下料段: 瓶/桶由片段自己的取件动作在 t=0 点亮(先取后放), 不必重复声明 states;
    # 伸缩缸起手=1(执行段尾步 transport_extend 以伸出送瓶收束)。liquid_after 承接执行段
    # 洗脱进瓶的液量(驻位液体, seed 从丢弃 builder 的 station_liquid_ml 收) —— 不声明
    # 就是"带着一只空瓶下料", 洗脱这一段白演了。
    "collect_unload": PhaseEntry(
        "collect_execute", "",
        "collect_execute 尾步 transport_extend 伸出送瓶; 瓶内带着按默认配方洗脱的液",
        mechanisms=(("col_extend", 1.0,
                     "SEQUENCE_ACTIONS[collect.transport_extend] 末步 col_extend→1"),),
        # 桶里的粉**已被淋洗过**(tint=1): 本段是收集四段式的收尾, 上一段 collect_execute
        # 的整段戏就是让淋洗液冲过粉柱。不声明就是"洗完一趟粉还是原色下料", 洗脱这一段
        # 与瓶里的液一样白演了 —— 与 liquid_after 承接液量是同一条理由的两个侧面。
        powders=((COLLECT_POWDER_ID, 1.0, 1.0,
                  "collect_execute 已用淋洗液冲过粉柱, 粉呈洗脱后的湿润色"),)),
    # 收集瓶取放脚本单独编译时的起手态。内联在 collect_load/unload 里跑时靠时间轴连续性
    # 蒙对(同本表开头 flow.develop_cycle.* 那段注释的理由), 单编就没有那份连续性。
    # 伸缩缸起手=1 的出处是两条上层流程的**排序**, 逐行可查:
    #   collect_load.yaml   : `collect.extend`(动作码22)紧排在 run_script 本脚本的前一行
    #                         → 瓶是放进**已伸出**的治具的;
    #   collect_unload.yaml : 本脚本先跑, `collect.retract` 排在其后 → 取瓶时治具仍伸出。
    # 不声明的后果不是"差一点": 收集瓶的目的实例挂在 ACTUATOR_COL_EXTEND 下(rig_map
    # station_seats), 起手 0 = 把瓶按缩回位摆着、却拿伸出位的示教点去抓。2026-08-07 实测
    # 抓取修正 87.60mm(X 分量 −85.44mm ≈ PB10x80 全行程 80mm), 已逼近 100mm 护栏, 观感
    # 就是瓶子被隔空吸进爪里 —— 与 collect_load 那条 ps_rotate 声明是同一类账。
    "transfer_bottle_staging_b_to_collect": PhaseEntry(
        "", "", "collect_load.yaml: collect.extend 紧排在 run_script 本脚本之前",
        mechanisms=(("col_extend", 1.0,
                     "collect_load.yaml: collect.extend(动作码22)在本脚本前一行"),)),
    "transfer_bottle_collect_to_staging_b": PhaseEntry(
        "", "", "collect_unload.yaml: 本脚本先跑, collect.retract 排在其后",
        mechanisms=(("col_extend", 1.0,
                     "collect_unload.yaml: collect.retract 排在本脚本之后, 取瓶时仍伸出"),)),
}


#: 仍然只占一个时间格的动作: 行程由运行期决定、或目标值 PC 侧根本拿不到。
#: 绝不为它们编一个绝对位置 —— 编出来的轴位看着很真, 却没有任何指标会说它是假的。
SEARCH_AXIS_ACTIONS = {
    "feedlift.probe_stack": ("探测板堆张数", 0.4),
    # 刮取路径是 PLC SoftMotion 按 g_* 数组插补出来的, 数组本身由 write_cnc_path /
    # write_pass_z 两条写点动作下发。A40 只是"置 CNC 启动然后等完成信号" —— PC 侧从头到尾
    # 没有**那一条**路径(每次运行随视觉结果变)。
    # 本条目 2026-08-06 起只服务**单动作/近似档**(motionMap 经 searchAxisActions 出时间格):
    # 流程精编译档在 emit_call 里先一步拦截, 走 emit_scrape() 按**演示标称条带**表现刀路
    # 与刮取遮罩(标称值与真值的边界见 SCRAPE_DEMO_BAND_CM 的注释, 并逐条记 flowNotes)。
    "photoscrape.scrape": ("刮板台·CNC 刮取(路径由 PLC SoftMotion 插补, 未表现刀路)", 8.0),
}

#: 多步定值动作 -> 步骤序列。目标是**烧在 PLC 程序里的常量**, PC 侧没有任何配置项记着
#: 它们, 但每条动作的 desc 逐字写明了驱哪个执行件到哪 —— 那就是这张表的出处, 每条末尾
#: 都注明了动作码。与 flow_params.yaml 同一条纪律: 编译期拿不到的事实写成看得见的声明,
#: 而不是猜; 现场改了 PLC 程序, 改的是这张表, 不是散在两处的 if 分支。
#:
#: 步骤形态(前端 actionSim.js 与后端 emit_call 读同一份, 字段名即契约):
#:   {"kind":"axis",     "axis":轴id, "toMm":毫米, "label":标签, "speedMmS":标称速度}
#:   {"kind":"point",    "arg":入参名, "axis":轴id, "label":标签, "speedMmS":标称速度,
#:                       "member":成员名(可选, 复合点位才有)}
#:        目标毫米来自 point_ref 入参指向的示教点(**实读点表**, 不是常量);
#:        复合点位(点样位置)按 `<点位key>.<成员key>` 取, member 就是那个后缀
#:   {"kind":"well",     "label":标签, "speedMmS":标称速度}
#:        4X/3Y 同时走到演示样品孔(DEMO_SAMPLE_WELL); 目标由上位机的仿射标定实算
#:   {"kind":"actuator", "id":机构id, "value":0/1, "label":标签}
#:   {"kind":"linkage",  "id":联动组id, "value":0/1, "label":标签}
SEQUENCE_ACTIONS: dict[str, tuple[dict, ...]] = {
    # 动作码 10: 清遮光等输出 -> 10Z=0 -> 9X=335 -> 确认遮光上位 -> 8Y=0
    "photoscrape.init": (
        {"kind": "axis", "axis": "axis_10z", "toMm": 0.0, "label": "刮板10Z·抬刀回零", "speedMmS": 60.0},
        {"kind": "axis", "axis": "axis_9x", "toMm": 335.0, "label": "刮板9X·刀让位到335", "speedMmS": 100.0},
        {"kind": "actuator", "id": "ps_shade", "value": 0.0, "label": "遮光气缸·回上位"},
        {"kind": "axis", "axis": "axis_8y", "toMm": 0.0, "label": "拍照8Y·回放板位", "speedMmS": 120.0},
    ),
    # 动作码 34: 8Y **载的是板**(9X 载刀), 把板送进暗箱到相机位再落遮光罩。
    # 暗箱里的紫外面光源 PC 侧没有任何开关信号, 所以不编 DO, 它按 rig_map.lights 常亮。
    "photoscrape.cam_photopos": (
        {"kind": "point", "arg": "ref_8y", "axis": "axis_8y",
         "label": "拍照8Y·板送进暗箱", "speedMmS": 120.0},
        {"kind": "actuator", "id": "ps_shade", "value": 1.0, "label": "遮光气缸·落下"},
    ),
    # 动作码 35: 遮光回上位 -> 8Y 绝对回 0
    "photoscrape.cam_photohome": (
        {"kind": "actuator", "id": "ps_shade", "value": 0.0, "label": "遮光气缸·回上位"},
        {"kind": "axis", "axis": "axis_8y", "toMm": 0.0, "label": "拍照8Y·板退出暗箱", "speedMmS": 120.0},
    ),
    # 动作码 43: 只**要求**遮光上位(不驱它), 再 10Z=0 / 9X=335 / 8Y=0。
    # 9X 的"回零"实际是 335 毫米工位停放位, 不是机床零点 —— desc 特意点明。
    "photoscrape.align_home": (
        {"kind": "axis", "axis": "axis_10z", "toMm": 0.0, "label": "对位10Z·抬刀回零", "speedMmS": 60.0},
        {"kind": "axis", "axis": "axis_9x", "toMm": 335.0, "label": "对位9X·回335停放位", "speedMmS": 100.0},
        {"kind": "axis", "axis": "axis_8y", "toMm": 0.0, "label": "对位8Y·回零", "speedMmS": 120.0},
    ),
    # 动作码 41: 关真空与无刷电机(无几何), 置旋转气缸自动 = 翻料倒粉
    "photoscrape.scrape_finish": (
        {"kind": "actuator", "id": "ps_rotate", "value": 1.0, "label": "旋转气缸·翻料倒粉"},
    ),
    # 动作码 42: 取桶后把旋转气缸自动清 FALSE = 回刮取位
    "photoscrape.retr_stoprot": (
        {"kind": "actuator", "id": "ps_rotate", "value": 0.0, "label": "旋转气缸·复位到刮取位"},
    ),
    # 动作码 10: 先 5Z=0 抬针, 再 4X/6X/7Y=0。3Y **只写目标不发移动命令**, 故不产步。
    "sampling.init": (
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针回零", "speedMmS": 20.0},
        {"kind": "axis", "axis": "axis_4x", "toMm": 0.0, "label": "上样4X·回零", "speedMmS": 10.0},
        {"kind": "axis", "axis": "axis_6x", "toMm": 0.0, "label": "点样6X·回零", "speedMmS": 50.0},
        {"kind": "axis", "axis": "axis_7y", "toMm": 0.0, "label": "点样7Y·回零", "speedMmS": 50.0},
    ),
    # 动作码 50: 吸取样品。轴序列照 PLC Sampling_L2/A50_absorb_吸收液体 的原文:
    #   5Z→0 抬针(气隔断在原位空气中做) → 4X/3Y 走孔位 → 5Z→position[2] 下探 → 回抽 → 5Z→0
    # 孔位不是常量: 4X/3Y 读的是 PC 写的 Sampling_4X/3Y_Target, 由 CalibrationService.push_well
    # 按孔实时算(仿射标定在 config/calibration.yaml, 实测三点)。演示用哪个孔由 flow_params
    # 声明, 见 well 步。5Z 下探深度 = 点表 sample_5z_dip(HMI slot 2, 实读 46.5)。
    "sampling.aspirate": (
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针(建气隔断)", "speedMmS": 20.0},
        {"kind": "well", "label": "上样4X/3Y·移到样品孔", "speedMmS": 10.0},
        {"kind": "point", "point": "sample_5z_dip", "axis": "axis_5z",
         "label": "上样5Z·下探进孔", "speedMmS": 20.0},
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针出孔", "speedMmS": 20.0},
    ),
    # 动作码 20: 清洗/充液润洗共用。4X 进清洗位有点表(sampling_4x_wash, 替代旧 position[9]);
    # 6X 清洗位与 5Z 深度仍烧在 PLC 里, 故只演 4X 那一段, 其余归 FLUID_TIME_ACTIONS 的时间格。
    "sampling.clean": (
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针", "speedMmS": 20.0},
        {"kind": "point", "point": "sampling_4x_wash", "axis": "axis_4x",
         "label": "上样4X·移到清洗位", "speedMmS": 10.0},
    ),
    "sampling.flush": (
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针", "speedMmS": 20.0},
        {"kind": "point", "point": "sampling_4x_wash", "axis": "axis_4x",
         "label": "上样4X·移到清洗位", "speedMmS": 10.0},
    ),
    # 动作码 30: 点样7Y 到**放板位** —— PLC A31_放板移轴 原文读 HMI_点样轴7Y.position[1],
    # 2026-08-05 实读 = 56.0, 已收进点表 spot_7y_place。走 point 步 = 实读点表, 现场重新
    # 示教后动画跟着变(此前这条只占一个时间格, 于是板托座整段停在建模位)。
    "sampling.place_axis": (
        {"kind": "point", "point": "spot_7y_place", "axis": "axis_7y",
         "label": "点样7Y·移到放板位", "speedMmS": 50.0},
    ),
    # 动作码 61: 点样7Y 到**喷涂位** = HMI_点样轴7Y.position[2] = 实读 −20.0
    # = Spot_7Y_Target = 点表 spot_pose.y_height(三者逐字对上, 见 spotting.yaml 注释)。
    "sampling.spray_axis": (
        {"kind": "point", "point": "spot_pose.y_height", "axis": "axis_7y",
         "label": "点样7Y·移到喷涂位", "speedMmS": 50.0},
    ),
    # 动作码 40: 只抬针(泵那段归流体)
    "sampling.prep": (
        {"kind": "axis", "axis": "axis_5z", "toMm": 0.0, "label": "上样5Z·抬针离液", "speedMmS": 20.0},
    ),
    # 动作码 60/61: 点样位置是个**复合点位**(spot_pose), 三个成员分驻 6X 与 7Y。
    # 先把 7Y 落到点样高度, 再让 6X 从起点扫到终点 —— 那条扫描带就是"条带点样"。
    # 顺序在这里显式定死, 前端读同一张表, 两边不可能演出不同的路线。
    "sampling.spot": (
        {"kind": "point", "arg": "ref_spot", "member": "y_height", "axis": "axis_7y",
         "label": "点样7Y·落到点样高度", "speedMmS": 50.0},
        {"kind": "point", "arg": "ref_spot", "member": "x_start", "axis": "axis_6x",
         "label": "点样6X·移到起点", "speedMmS": 50.0},
    ),
    "sampling.spot_band_layer": (
        {"kind": "point", "arg": "ref_spot", "member": "y_height", "axis": "axis_7y",
         "label": "点样7Y·落到点样高度", "speedMmS": 50.0},
        {"kind": "point", "arg": "ref_spot", "member": "x_start", "axis": "axis_6x",
         "label": "点样6X·移到条带起点", "speedMmS": 50.0},
        {"kind": "point", "arg": "ref_spot", "member": "x_end", "axis": "axis_6x",
         "label": "点样6X·扫到条带终点(供液)", "speedMmS": 5.0},
    ),
    # 动作码 10: 清瓶定位/下压/夹持/升降/伸缩五个输出(泵那段归流体)
    "collect.init": (
        {"kind": "actuator", "id": "col_press", "value": 0.0, "label": "下压气缸·回原点"},
        {"kind": "linkage", "id": "col_clamp", "value": 0.0, "label": "夹持气缸·松开"},
        {"kind": "actuator", "id": "col_lift", "value": 0.0, "label": "升降气缸·回原点"},
        {"kind": "actuator", "id": "col_extend", "value": 0.0, "label": "伸缩气缸·回原点"},
        {"kind": "actuator", "id": "col_bottle_locator", "value": 0.0, "label": "瓶定位气缸·回原点"},
    ),
    # 动作码 23: 伸缩回原点 -> 升降到动点 -> 下压置位
    "collect.lift_press": (
        {"kind": "actuator", "id": "col_extend", "value": 0.0, "label": "伸缩气缸·缩回"},
        {"kind": "actuator", "id": "col_lift", "value": 1.0, "label": "升降气缸·顶升到动点"},
        {"kind": "actuator", "id": "col_press", "value": 1.0, "label": "下压气缸·下压"},
    ),
    # 动作码 41: 下压回原点 -> 升降回原点 -> 伸缩到动点
    "collect.transport_extend": (
        {"kind": "actuator", "id": "col_press", "value": 0.0, "label": "下压气缸·抬起"},
        {"kind": "actuator", "id": "col_lift", "value": 0.0, "label": "升降气缸·落回原点"},
        {"kind": "actuator", "id": "col_extend", "value": 1.0, "label": "伸缩气缸·伸出"},
    ),
}

#: 演示用的样品孔 —— (孔板实例 id, 行, 列)。
#:
#: 上样 4X/3Y 是**仿射轴**: 目标不是常量, 由 CalibrationService 按孔实时算了写进
#: Sampling_4X/3Y_Target(PLC 的 A50_absorb 读的就是这两个 flat 节点), 仿射标定实测于
#: config/calibration.yaml。所以"演哪个孔"是编排问题不是几何问题 —— 与 flow_params.yaml
#: 声明入参取值域同一条纪律: 编译期定不下来的事写成看得见的声明, 而不是猜一个。
#: 取 4×6 #1 的 A1: 它是该实例三个标定孔之一, 坐标是实测的而非外插。
DEMO_SAMPLE_WELL = ("plate_4x6_1", 1, 1)

#: 目标毫米直接来自动作入参的轴动作 -> (轴 id, 入参名, 标签, 标称速度 mm/s)。
#: 只收**PLC 直收裸毫米、无帧变换**的那种; align_move 的 x_mm/y_mm 在 PLC 内部还要过
#: K/O 帧变换, 不是 9X 的裸毫米, 因此不在此表(见 UNRESOLVED_ACTIONS)。
PARAM_AXIS_ACTIONS = {
    # 动作码 44: PLC 接受连续 0~18mm, 以 5mm/s 移动 10Z
    "photoscrape.align_z": ("axis_10z", "z_mm", "对位10Z·升降", 5.0),
}

#: 只驱动泵/阀/真空一类**流体执行件**的动作 -> 它到底驱了什么。
#:
#: 这些执行件在 rig_map 里全是纯状态条目(无几何) —— 所以它们既不是"做不到", 也不是
#: "什么都没发生", 而是"泵体与阀本身三维不表现"。说清楚驱的是哪台泵哪个阀, 比一句
#: "目标毫米在 PLC 内部"诚实得多: 泵动作**根本没有目标毫米**。
#: 表里同时收两类: 只驱流体的, 与另有机构动作、流体只是其中一部分的(如
#: develop.rinse_fill 还要关盖) —— 后者照样出动画, 这段话作为注脚附在旁边。
#:
#: ⚠ 措辞不要再写成"三维不表现流体": 展缸那四条(fill/rinse_fill/rinse_suction/drain)
#: 现在**会画缸内液面**(见 ClipBuilder.emit_tank_liquid), 没画的只是泵体与阀。一句笼统的
#: "不表现流体"会让人以为画面上那段液面涨落是假的。
FLUID_ACTIONS = {
    "develop.init": "所选缸的进液阀/排液阀/吹气阀清零, 并按组初始化1号或2号注射泵",
    "develop.clean_line": "按缸组的1号/2号注射泵, 只走管路清洗指令",
    "develop.rinse_fill": "所选缸的进液阀与排液阀置位, 按次数循环发送润洗泵指令",
    "develop.fill": "所选缸的进液阀 + 按组的注射泵, 按次数循环上液",
    "develop.drain": "所选缸的排液阀、吹气阀与大真空泵(排液闭环 FSM)",
    "develop.rinse_suction": "所选缸的进液阀/排液阀/吹气阀(承接 A21 打开的排液路径)",
    "collect.init": "3号注射泵初始化, 以及进液/排液/正压排液输出清零",
    "collect.collect": "收集进液阀、排液阀、正压排液与3号注射泵, 按次数洗脱循环",
    "sampling.init": "上样三通与吹气输出清零, 并向4号注射泵发初始化指令",
    "sampling.prep": "4号注射泵自口3绝对回抽, 在针尖建立气隔断",
    "pump.vacuum_on": "大真空泵站位[11]置位(实际输出由泵管理 FB 对全部站位取 OR)",
    "pump.vacuum_off": "大真空泵站位[11]清零(全部站位为假时才真正撤销输出)",
}

#: 有真实机械运动、但**目标值 PC 侧根本拿不到**的动作 -> 说清楚缺在哪。
#:
#: 与 SEARCH_AXIS_ACTIONS(行程由运行期光电决定)分开: 那些是"没有目标值", 这些是
#: "有目标值但存在别处"。两种都不编绝对位置 —— 编出来的轴位看着很真, 却没有任何指标
#: 会说它是假的。写清楚缺口在哪, 现场补上读数就能升级成 SEQUENCE/STATION 的一条。
UNRESOLVED_ACTIONS = {
    "photoscrape.align_move":
        "对位 XY 的 x_mm/y_mm 在 PLC 内部还要过 K/O 帧变换, 不是 9X/8Y 的裸毫米; "
        "且现役工程的板区窗为空集, 任何下降请求恒被拒(ErrorCode 422) —— 用「实机对照」",
    "photoscrape.scrape":
        "刮取路径由 PLC SoftMotion 按 g_* 数组插补, 数组本身由 write_cnc_path / "
        "write_pass_z 两条写点动作下发 —— 单动作/近似档无法复现该插补, 用「实机对照」; "
        "流程精编译档按演示标称条带表现(emit_scrape, 标称≠实况, 见片段 flowNotes)",
    "sampling.clean":
        "轴先进清洗位: 4X 走点表的 sampling_4x_wash, 但 6X 清洗位与 5Z 下降深度都烧在 "
        "PLC 里, PC 侧无记录 —— 只能演一半, 索性不演, 用「实机对照」",
    "sampling.flush":
        "与 clean 共用动作码 20, 缺口同上(6X 清洗位与 5Z 深度在 PLC 内部) —— 用「实机对照」",
    "sampling.aspirate":
        "4X/3Y 的孔位由上位机运行期按样品盘算出后下发, 5Z 下降深度在 PLC 的 "
        "HMI_上样轴5Z轴.position[2] —— 单动作演示两者都没有, 用「实机对照」",
    "sampling.rinse_mix":
        "4X/3Y 回的是运行期那个原样品孔, 5Z 深度同样在 PLC 的 HMI 槽 —— 用「实机对照」",
    "robot.step": "步进是相对当前位姿的增量, 单动作演示没有起点 —— 用「实机对照」",
    "robot.jog_start": "点动是持续运动, 停在哪取决于何时 jog_stop —— 用「实机对照」",
}

#: 只读/纯上位机动作: 不产生任何机构运动, 编译时跳过(不是"未知动作")。
#: feedlift 那两条是**校验类**: init 只清 jog 命令位再核对 1Z/2Z 是否已在零位,
#: debug_check_photoelectric_edge 的 desc 明写"不发任何JOG或定位命令"。
IGNORED_ACTIONS = frozenset({
    "robot.query", "robot.home_ensure", "robot.set_mounted_tool",
    "robot.set_do", "robot.enable", "robot.disable", "robot.connect", "robot.clear_error",
    "material.plan_staging", "material.check_availability",
    "develop.release_tank", "develop.capture_reference",
    "photoscrape.wait_rot",
    "feedlift.init", "feedlift.debug_check_photoelectric_edge", "feedlift.preflight",
})

#: 天然不驱动机构的动作类别 —— 与前端 actionSim 的判定逐字一致。
#:
#: 有了它, 上位机新加一个 host/vision/camera/plc_write 动作就**不必再来补 IGNORED_ACTIONS**:
#: 之前每加一个只读动作, 引用它的整条流程就报"未知动作"编不出来, 而那条动作压根不产生
#: 运动。IGNORED_ACTIONS 从此只留"kind 看不出来、得逐条判"的那些(plc_l2 里的账本类)。
#:
#: plc_write 在列: 写点动作只把数值下发进 PLC 的目标节点, 机构由**后续的 L2 动作**驱动
#: (photoscrape.write_cnc_path 写 g_* 数组, 真正插补的是 photoscrape.scrape)。它们的入参
#: 常常引用上一步视觉的返回值, 求值必然失败 —— 为一个不动机构的动作让整条流程编不出来
#: 是纯粹的损失。
STILL_ACTION_KINDS = frozenset({"host", "vision", "camera", "plc_write"})

#: 只驱流体、但**确实占着时间**的动作 -> (说明, 名义时长秒)。
#:
#: 与 FLUID_ACTIONS 是一份事实的两面: 那张表告诉前端"这条动作驱的是泵/阀, 三维不表现",
#: 这张表让编译器出一个**有语义的时间格**, 免得一条 20 秒的洗脱循环在时间轴上消失 ——
#: 整条流程的节奏会因此变形, 而画面看着完全正常。时长取动作 desc 里写明的循环次数与
#: 沉降/正压时长的量级, 是观感值不是物理量, 与 SEARCH_AXIS_ACTIONS 同一条约定。
#:
#: 展缸那三条(fill/drain/rinse_suction)如今**只在退化路径上**用这张表: 正常情况下它们
#: 走 emit_tank_liquid 画缸内液面, 只有缸号或体积解不出来时才退回这里的时间格。
#: 涉泵的三条(collect.collect/develop.clean_line/sampling.rinse_mix)同理**只是退化路径**:
#: 正常情况下柱塞行程由 emit_pump_syringe 画出(泵体已程序化建模, 不再"三维不表现"),
#: 只有入参是运行期量或泵没几何(rigged:false)时才退回时间格。
FLUID_TIME_ACTIONS = {
    "collect.collect": ("收集·加液/排液洗脱循环(泵入参未解出, 未表现柱塞行程)", 6.0),
    "develop.fill": ("展缸·上液(进液阀 + 注射泵)", 5.0),
    "develop.drain": ("展缸·排液闭环(排液/吹气阀 + 大真空泵)", 8.0),
    "develop.clean_line": ("展缸·清洗管路(泵入参未解出, 未表现柱塞行程; 只洗管路不动缸内液体)", 5.0),
    "develop.rinse_suction": ("展缸·润洗抽吸(进液/排液/吹气阀)", 6.0),
    # 下面这条**有真实轴运动**, 但目标值 PC 侧拿不到(见 UNRESOLVED_ACTIONS 的逐条说明)。
    # 与 SEARCH_AXIS_ACTIONS 同一条约定: 只出一个有语义的时间格, 让流程节奏与步骤表是对的,
    # 但**绝不编一个绝对位置**去驱轴 —— 编出来的针位看着很真, 却没有指标会说它是假的。
    # aspirate/clean/flush 的**轴**已经能演了(见 SEQUENCE_ACTIONS), 泵行程也已能演
    # (emit_pump_syringe), 这里只兜"泵入参解不出"的残余情形。
    "sampling.rinse_mix": ("上样·原孔润洗混匀(泵入参未解出; 4X/3Y 回的是运行期那个原样品孔, 未表现轴)", 6.0),
}

#: 取件/放件脚本 -> 座位键模板。与 gen_twin_manifest.build_payloads 生成的 seat 同构。
#: 用脚本名精确匹配而不是 `_pick`/`_put` 正则: robot_scrape_holder_pick_exit 名字里带
#: _pick 却没有任何夹爪动作, 正则会误判。
SEAT_TEMPLATES = {
    "robot_group_rack_pick": ("rack:{rack_id}:{slot_id}", "pick"),
    "robot_group_rack_put": ("rack:{rack_id}:{slot_id}", "put"),
    "robot_group_staging_pick": ("staging:{area}", "pick"),
    "robot_group_staging_put": ("staging:{area}", "put"),
    "robot_individual_pick": ("hole:{area}:{slot_id}", "pick"),
    "robot_individual_put": ("hole:{area}:{slot_id}", "put"),
    "robot_collector_return_put": ("hole:staging-a:{slot_id}", "put"),
    # 站侧交接 (小夹爪 <-> 工位夹具)。座名是**定值**不带参 —— 同一种耗材有两个工位座
    # (刮板夹具与收集工位夹具都收 collector), 只能逐脚本写死, 与上位机
    # config/material_topology.yaml 的 payload_seats id 逐字一致。
    #
    # 挂在**含夹爪动作的那一半**上: put_enter 只走位不松爪 (松爪在 put_exit),
    # pick_exit 是持件退出、全程不动夹爪。挂错半边的表现是"载荷在机械臂还没到位时就落下来"。
    #
    # ⚠ 少了这 6 条的后果不只是载荷交接: _closing_on_payload 靠这张表判"这次合爪是不是去
    #   夹东西", 于是 2026-08-05 实测的 22 处空爪紧闭里有 18 处是**真取件被误判**
    #   (从刮板夹具取收集器、从收集工位取瓶), 画面上爪子会把物料捏穿。
    "robot_scrape_holder_pick_enter": ("scrape-holder", "pick"),
    "robot_scrape_holder_put_exit": ("scrape-holder", "put"),
    "robot_collect_bottle_pick": ("collect-bottle", "pick"),
    "robot_collect_bottle_put": ("collect-bottle", "put"),
    "robot_collect_holder_pick_enter": ("collect-holder", "pick"),
    "robot_collect_holder_put_exit": ("collect-holder", "put"),
}

#: 顶层 operation 本身就是取放脚本的"半程"片段(演示页「动作」列的单动作条目):
#: 取的半程以持件结束(ends_holding), 放的半程以持件开始(starts_holding, 见
#: ClipBuilder.preload_payload)。只按**顶层** operation 名匹配(compile_plate_route 查),
#: 复合流程内联同名脚本不受影响 —— 那里的取放在同一条时间轴里天然成对。
#: 键必须同时在 SEAT_TEMPLATES 里, 否则解不出座位, 半程携带无从谈起。
STANDALONE_HALF_CARRY = {
    "robot_individual_pick": "ends_holding",
    "robot_group_rack_pick": "ends_holding",
    "robot_group_staging_pick": "ends_holding",
    "robot_individual_put": "starts_holding",
    "robot_group_rack_put": "starts_holding",
    "robot_group_staging_put": "starts_holding",
    "robot_collector_return_put": "starts_holding",
}

#: 耗材种类 -> 中转区。与上位机 runtime/material_store.py 的 AREAS 同构。
AREA_BY_KIND = {"collector": "staging-a", "bottle": "staging-b"}

#: 抓取修正的编译期护栏(毫米)。与前端 MachineStateDriver.PAYLOAD_GRAB_MAX_TRAVEL_M(0.1m)
#: 两名一数, 谁动都要同步 —— 前端那道闸只拦播放侧; 编译器没有闸时, 383.67mm 的姿态账错
#: (STA_SCRAPE_HOLDER 骑 9X 未摆位)曾静默烤进片段(2026-08-07 实测)。合法的示教-CAD
#: 失配最大实测 58.8mm, 100 给 ~1.7× 余量。
PAYLOAD_GRAB_MAX_TRAVEL_MM = 100.0

#: 实例帧映射的自洽容差(米/无量纲混合的矩阵元素绝对值)。同一零件的两份 CAD 拷贝必须全等,
#: 于是每个共享网格解出的 Ms·Md⁻¹ 应当逐元素相同。1e-6 是**实测定的**: 2026-08-13 在
#: models/machine.official-cr5.glb 上逐对量过, 五条单件路线的离散在 0 ~ 4.2e-7 之间
#: (粉桶 4 个子件、瓶 1 个), 1e-6 给 ~2.4× 余量; 而不全等的样品瓶托盘离散是 2.0, 差六个
#: 数量级 —— 这个阈值区分得干干净净, 不存在"擦边"。
INSTANCE_FRAME_TOLERANCE = 1e-6

MAX_INLINE_DEPTH = 8

#: 液面演示时长上限(秒)。排液闭环的 drain_duration_s 上限是 600s、吹气还有 30s, 照实画
#: 会让一条流程在时间轴上彻底变形而画面看着完全正常。与 FLUID_TIME_ACTIONS 的时长同一条
#: 约定: 是观感值不是物理量, 被压缩时**在步骤标签上写出真值**。
#: 前端近似档 demo/actionSim.js、demo/flowSim.js 的 LIQUID_MAX_RAMP_S 与本值同义。
TANK_LIQUID_MAX_RAMP_S = 20.0

#: 注射泵单相位演示时长上限(秒)。与 TANK_LIQUID_MAX_RAMP_S 同一条约定: 真实时长按
#: t = ΔmL×(步/mL)/V + M/1000 算(换算真源 tools/pump/mvp_staged_clean.py:106), 超上限
#: 压到上限并**在步骤标签上写出真值** —— spot_band_layer 实测 500~700s, 照实画一条
#: 上样流程会拉到十几分钟。
PUMP_MAX_RAMP_S = TANK_LIQUID_MAX_RAMP_S
#: 换阀名义时长(秒), 与前端 PumpSyringeModel.VALVE_RAMP_S 同值: 切液路很快, 与柱塞
#: 十几秒的行程不是一个量级。
PUMP_VALVE_S = 0.4
#: 展开后的相位预算。实时台是 64(PumpSyringeModel.MAX_PHASES); 演示片段按 8 收紧 ——
#: sampling.clean 现场填过 20 轮×4 相位, 逐轮演完观感与 2 轮没有区别, 时间轴却多出
#: 几分钟。压缩的是**轮数**不是相位(终点体积不变), 压缩时写 flowNotes。
PUMP_DEMO_MAX_PHASES = 8


def tank_lid_linkage(tank: int) -> str:
    """缸号 -> 缸盖联动组 id。

    缸号 1-4 = PLC 组 1 = dev_t1_cyl1..4, 5-8 = 组 2。配对真源见 TANK_LID_ACTIONS 的注释。
    单独成函数是因为编译期(emit_call)与导出给前端的映射表都要用它, 两处各写一遍必漂。
    """
    if not 1 <= int(tank) <= 8:
        raise ValueError(f"展缸号越界: {tank}")
    tank = int(tank)
    return f"dev_t{1 if tank <= 4 else 2}_cyl{(tank - 1) % 4 + 1}"


def motion_map_document() -> dict:
    """把"动作 -> 三维机构"的全部映射表序列化成前端可读的 JSON 文档。

    为什么要导出而不是让前端抄一份: 前端的即时近似展开(flowSim.js/actionSim.js)需要
    同一套判据 —— 哪个动作驱动哪根轴到多少毫米、哪个是气缸、哪些压根不产生机构运动。
    这些表近百条且会随现场标定继续长; 手抄两份必然漂, 而漂了的表现是"演示里播了一段
    根本不存在的运动", 没有任何自动指标会报警。

    本仓已经为"两边各留一份公式"付过一次代价: linkageKinematics.js 与
    gen_twin_manifest.solve_lid_kinematics 是同一条曲柄滑块公式的两个副本, 只能靠两侧
    各挂一个回归测试锁住。映射表比那条公式大两个数量级, 只能单向导出。

    返回:
        可直接 json.dump 的字典 (schema: ptlc.action-motion-map/v1)
    """
    return {
        "schema": "ptlc.action-motion-map/v1",
        "note": (
            "由 clip_compiler.motion_map_document() 生成; 唯一真源在 Python 侧, 前端只读不抄。"
            "液面动作表**刻意不在本表**: 它的真源是 device-manifest.tankLiquid.actions"
            "(gen_twin_manifest.TANK_LIQUID_ACTIONS), 前端直接读 manifest —— 同一件事导两条路"
            "就是新造一条漂移路径。"
        ),
        "stationAxisActions": {
            action: {
                "axis": axis_id,
                "toMm": float(target_mm),
                "label": label,
                "speedMmS": float(speed),
            }
            for action, (axis_id, target_mm, label, speed) in STATION_AXIS_ACTIONS.items()
        },
        "searchAxisActions": {
            action: {"label": label, "durationS": float(seconds)}
            for action, (label, seconds) in SEARCH_AXIS_ACTIONS.items()
        },
        "sequenceActions": {
            action: [dict(step) for step in steps]
            for action, steps in SEQUENCE_ACTIONS.items()
        },
        "paramAxisActions": {
            action: {"axis": axis_id, "arg": field, "label": label, "speedMmS": float(speed)}
            for action, (axis_id, field, label, speed) in PARAM_AXIS_ACTIONS.items()
        },
        "fluidActions": dict(FLUID_ACTIONS),
        "unresolvedActions": dict(UNRESOLVED_ACTIONS),
        "cylinderActions": {
            action: {"id": mechanism, "arg": field}
            for action, (mechanism, field) in CYLINDER_ACTIONS.items()
        },
        "cylinderActionsFixed": {
            action: {"id": mechanism, "value": float(value)}
            for action, (mechanism, value) in CYLINDER_ACTIONS_FIXED.items()
        },
        "tankLidActions": {action: float(value) for action, value in TANK_LID_ACTIONS.items()},
        "tankLidLinkage": {str(tank): tank_lid_linkage(tank) for tank in range(1, 9)},
        "ignoredActions": sorted(IGNORED_ACTIONS),
        "platePointSlot": dict(PLATE_POINT_SLOT),
        # 工位阶段片段的起手态(见 PHASE_ENTRY_STATE)。导的是**声明**不是算好的液量:
        # 前端 flowSim 拿 liquidAfter 指名的脚本走一遍自己的 walk, 与编译器算同一个数 ——
        # 导一个 60.0 过去等于在 JS 侧存了第二份配方, 改 develop_volume_ml 那天就漂了。
        "phaseEntryState": {
            operation: {"liquidAfter": entry.liquid_after, "plateAt": entry.plate_at,
                        "why": entry.why, "states": list(entry.states),
                        "mechanisms": {mechanism: value
                                       for mechanism, value, _why in entry.mechanisms}}
            for operation, entry in PHASE_ENTRY_STATE.items()
        },
        # 点样站"机床 mm → 板 cm"的站位映射(见 SPOT_BAND_CALIB) —— **导映射不导毫米**:
        # 端点毫米前端自己读 /api/points 的 spot_pose 活值(与地轨站位同一条纪律), 过同一
        # 条仿射即得标称色带 —— 实时页"点样板"的条带与编译产物不造第二份真源。
        "spotBandCalib": {
            "xOriginMm": SPOT_BAND_CALIB["x_origin_mm"], "xDir": SPOT_BAND_CALIB["x_dir"],
            "yOriginMm": SPOT_BAND_CALIB["y_origin_mm"], "yDir": SPOT_BAND_CALIB["y_dir"],
            "bandHalfCm": SPOT_BAND_HALF_CM,
            "plateSizeCm": [SCRAPE_DEMO_PLATE_CM, SCRAPE_DEMO_PLATE_CM],
            "machine": {"xAxis": "axis_6x", "yAxis": "axis_7y"},
            "frame": "plate-cm",
        },
        # 展开润湿前沿的演示目标高度(板 cm) —— 实时页"展开板"复用同一显式假设
        "wetFrontTargetCm": WET_FRONT_TARGET_CM,
        # 注意: 地轨站位毫米**不导出**。前端自己读 /api/points, 读不到就如实说读不到 ——
        # 见本文件顶部关于 RAIL_SLOT_REFERENCE 的那段。
        "gripperByTool": {str(tool): gid for tool, gid in GRIPPER_BY_TOOL.items()},
        "toolAsset": {str(tool): node for tool, node in TOOL_ASSET.items()},
        "flipActuatorId": FLIP_ACTUATOR_ID,
        "visionLightId": VISION_LIGHT_ID,
    }

#: require_anchor 当断言用时的位置容差(mm)。给到 5mm 是因为点表里存在 pose/joint 半新态
#: (见 ClipBuilder._consistent_joint), 同一个物理点的两种记法本就能差到毫米级; 真正要拦的是
#: "整段运动缺失"那种几十上百毫米的错。
ANCHOR_ASSERT_TOLERANCE_MM = 5.0


class CompileError(RuntimeError):
    """编译期硬失败。片段宁可不生成, 也不带着近似值进浏览器。"""


# --------------------------------------------------------------------------- #
# 表达式与分支求值
# --------------------------------------------------------------------------- #

def evaluate_expression(node: Any, bindings: dict[str, Any]) -> Any:
    """求一个 ptlc.script/v1 表达式的值。

    只支持转移路线实际用到的形态: 字面量、变量、==/!=/and/or/not。遇到读运行期状态的
    表达式(field 取反馈快照的字段等)一律抛错 —— 那种分支必须由调用方以显式假设消解,
    编译器不猜。

    Args:
        node: 表达式节点
        bindings: 当前作用域的变量绑定

    Returns:
        求值结果

    Raises:
        CompileError: 表达式形态不受支持, 或引用了未绑定的变量
    """
    if not isinstance(node, dict):
        return node
    if "lit" in node:
        return node["lit"]
    if "var" in node:
        name = node["var"]
        if name not in bindings:
            raise CompileError(f"表达式引用了未绑定的变量: {name}(调用方须显式给定)")
        return bindings[name]
    if "unop" in node:
        if node["unop"] != "not":
            raise CompileError(f"不支持的一元运算: {node['unop']}")
        return not evaluate_expression(node.get("operand"), bindings)
    if "binop" in node:
        op = node["binop"]
        left = evaluate_expression(node.get("left"), bindings)
        right = evaluate_expression(node.get("right"), bindings)
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "and":
            return bool(left) and bool(right)
        if op == "or":
            return bool(left) or bool(right)
        # 数值比较: 纠偏收敛门 abs(drz) > 0.8 这类。两边都来自显式假设或字面量,
        # 求值是确定的; 不支持时才会掉进下面的抛错。
        if op in (">", "<", ">=", "<="):
            try:
                lv, rv = float(left), float(right)
            except (TypeError, ValueError) as exc:
                raise CompileError(f"比较运算 {op} 的操作数不是数: {left!r} / {right!r}") from exc
            return {">": lv > rv, "<": lv < rv, ">=": lv >= rv, "<=": lv <= rv}[op]
        raise CompileError(f"不支持的二元运算: {op}")
    if "call" in node:
        # 表达式里的纯函数。只放行**无副作用、结果只取决于入参**的那几个;
        # 任何要读运行期状态的调用一律抛错(第 3 条纪律)。
        name = str(node.get("call") or "")
        pure = {"abs": abs, "min": min, "max": max, "float": float, "int": int}
        if name not in pure:
            raise CompileError(f"表达式里不支持的调用: {name}(只放行纯函数 {sorted(pure)})")
        values = [evaluate_expression(item, bindings) for item in (node.get("args") or [])]
        return pure[name](*values)
    if "field" in node:
        # 取字典字段, 典型是视觉纠偏结果 voff_rz.valid / .drz_deg。
        # 这**仍然不是在猜运行期状态**: 被取的那个变量必须由调用方以显式假设整体传进来
        # (见 PLATE_VISION_ASSUMPTION), 没传就照旧抛错。
        holder = evaluate_expression(node.get("field"), bindings)
        name = node.get("name")
        if not isinstance(holder, dict):
            raise CompileError(f"字段取值 .{name} 的宿主不是字典(调用方须以显式假设给定整体)")
        if name not in holder:
            raise CompileError(f"显式假设里缺字段 {name}: 已有 {sorted(holder)}")
        return holder[name]
    raise CompileError(f"不支持的表达式(可能读了运行期反馈): {sorted(node)}")


def evaluate_optional(node: Any, bindings: dict[str, Any]) -> Any:
    """能静态求值就返回值, 求不出来返回 None(不抛)。

    只给**决策外壳**用(循环起点、可静态求值的 assign)。它与 evaluate_expression 的分工是
    死的: 凡是要拿去驱动几何的值一律走 evaluate_expression, 求不出来就硬失败; 只有"这一轮
    从几开始""这个变量能不能顺手绑上"这类外壳量才允许"拿不到就算了"。
    """
    try:
        return evaluate_expression(node, bindings)
    except CompileError:
        return None


def select_branch(node: dict, bindings: dict[str, Any]) -> list[dict]:
    """求一个 if 节点该走哪一支。

    Args:
        node: op=='if' 的节点
        bindings: 变量绑定

    Returns:
        命中分支的指令列表(都不命中则为空列表)
    """
    if evaluate_expression(node.get("cond"), bindings):
        return node.get("then") or []
    for alternative in node.get("elifs") or []:
        if evaluate_expression(alternative.get("cond"), bindings):
            return alternative.get("body") or []
    return node.get("else") or []


# --------------------------------------------------------------------------- #
# 输入加载
# --------------------------------------------------------------------------- #

def load_operation(control_root: Path, name: str) -> dict:
    """按名字在 config/operation 下找 operation YAML。

    OPERATION_DIRS 先按优先级找, **找不到再兜全部子目录**。

    为什么要兜底: 目录是会新增的(09_full、11_parallel 都是后加的), 而这张常量表没人记得
    同步。表现不是报"配置漏了", 而是 13 条流程报"找不到 operation: pf_s1_load"——
    脚本明明在盘上。flow_discovery._iter_operation_files 早就改成扫全部目录了(它的
    docstring 就写着"含未登记在 OPERATION_DIRS 的目录"), 发现器与编译器各扫各的必然漂。

    Args:
        control_root: 上位机仓库根(只读)
        name: operation 名(不含扩展名)

    Returns:
        解析后的文档

    Raises:
        CompileError: 找不到
    """
    root = control_root / "config" / "operation"
    ordered = [root / folder for folder in OPERATION_DIRS]
    ordered += sorted(
        item for item in (root.iterdir() if root.is_dir() else [])
        if item.is_dir() and not item.name.startswith(".") and item not in ordered
    )
    for folder in [root, *ordered]:
        candidate = folder / f"{name}.yaml"
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8"))
    raise CompileError(f"找不到 operation: {name}")


def resolve_plate_anchors(scene: "GlbScene | None") -> dict[str, str]:
    """从 GLB 层级解析"停放位 -> 板锚点节点名"。

    缸号按 parent 名 `TANK_N` 反查(见 PLATE_ANCHOR_FIXED 的警告)。解析不到的落点
    直接不进表 —— 调用方据此不出 `mount`, 让运行期退回"保世界位姿", 而不是编个位置。

    Args:
        scene: 已加载的 GLB 层级; None 时返回空表

    Returns:
        {停放位: 节点名}
    """
    if scene is None:
        return {}
    anchors: dict[str, str] = {}
    for index, node in enumerate(scene.nodes):
        name = str(node.get("name") or "")
        if not name:
            continue
        parent = scene.parent.get(index)
        parent_name = scene.name_of(parent) if parent is not None else ""
        tank = re.fullmatch(r"TANK_(\d)", parent_name)
        if tank and name.startswith("玻璃-"):
            anchors[f"tank:{int(tank.group(1))}"] = name
            continue
        slot = PLATE_ANCHOR_FIXED.get(name)
        if slot:
            anchors[slot] = name
    return anchors


def verify_tank_pairing(scene, posture, registry, rail_mm: float) -> list[str]:
    """核对"机器人展缸取放点"与"三维 TANK_1..8 锚点"的编号是否对得上。

    判据是**架内相对量**: 一个架里的 4 个缸只差高度, 同一副吸盘、同一朝向, 所以
    "法兰 → 该缸锚点"的竖直偏置在架内必须是同一个数。

    只用相对量、不碰绝对量, 是因为"示教关节角 → GLB 世界位姿"这条链还有几百毫米的
    系统偏差(拿落点唯一的 P21/P19/P65/P22 验过, 最近锚点都认错); 而系统偏差在架内
    比较里整体抵消, 所以架内比较是可信的。

    为什么这个必须**拦住**而不是记个警告: 这类错画出来"看着完全正常" —— 板稳稳落进一个
    缸, 缸盖也开合, 只是那不是机器实际用的那个缸。没有任何自动指标会报警(见
    PTLC 三维计划 §9 与 three_d/docs/CLAUDE.md 第 26 条)。

    Args:
        scene: GlbScene
        posture: RobotPosture
        registry: PointRegistry
        rail_mm: 展开区的地轨位置

    Returns:
        问题描述; 空表示编号自洽
    """
    if scene is None or posture is None:
        return []
    anchors = resolve_plate_anchors(scene)
    by_name = {point.robot_name: point for point in registry.points}
    verticals: dict[int, float] = {}
    for tank in range(1, 9):
        point = by_name.get(f"P{10 + tank}")
        anchor = anchors.get(f"tank:{tank}")
        if point is None or anchor is None or not point.joint:
            return []                       # 缺数据就不下结论, 不拿半份数据当证据
        mount = posture.mount_world(joints_deg=list(point.joint), rail_mm=rail_mm)[:3, 3]
        verticals[tank] = float(mount[1] - scene.world_matrix(anchor)[:3, 3][1]) * 1000.0

    problems = []
    for rack, tanks in ((1, (1, 2, 3, 4)), (2, (5, 6, 7, 8))):
        values = [verticals[n] for n in tanks]
        spread = max(values) - min(values)
        if spread <= 60.0:
            continue
        detail = ", ".join(f"缸{n}={verticals[n]:+.1f}mm" for n in tanks)
        problems.append(
            f"第{rack}架内 4 个缸的法兰-锚点竖直偏置不一致(极差 {spread:.0f}mm): {detail}。"
            "同一架内只差高度, 这个数必须相同 —— 不同就说明两套编号对不上。"
        )
    return problems


#: dock 反解的正交性容差。除掉节点 scale 之后剩下的必须是纯旋转, 残差只该来自 GLB 里那点
#: 各向异性噪声 —— 中转B 六只瓶的 scale 是 [0.047500003, 0.047499999, 0.047500003],
#: 各向异性比 1.000000083, 实测残差 1.7e-7。1e-5 给 ~60× 余量; 而"scale 拿错"这类真错误
#: 的残差是 1e-1 量级(少除一个 0.0475 就是 0.998), 隔着四个数量级, 分得干净。
DOCK_ORTHOGONALITY_TOLERANCE = 1e-5


def _dock_of(local: np.ndarray, node_scale) -> dict[str, list[float]]:
    """局部 4x4 -> 片段 detach.dock 的 {position, quaternion}。

    ⚠ node_scale 是**该节点自身的 scale**, 必须先除掉再取四元数, 不能图省事直接喂
    `Rotation.from_matrix(local[:3, :3])`: scipy(1.11.4)的 from_matrix 对带缩放的矩阵
    **不做归一化**, 会安静地解出一个完全无关的旋转 —— 逐 scale 实测(2026-08-13,
    3000 次随机姿态): scale=1 误差 2.2e-16, scale=0.5 已达 4.1e-2, 而 04_optimize 的
    meshopt 量化把中转B那六只样品瓶压成的 **scale=0.0475** 下, 角误差中位 **68.1°**、
    最大 106.1°。此前 dock 就是这么烤的, 于是那六只瓶的落位姿态整个是错的, 且全程零报错
    (前端只会看到一个合法的单位四元数)。

    反解式必须与前端逐字互逆: MachineStateDriver.dockPayload 只写 position/quaternion、
    原样保留 node.scale, 前端复原的是 R(q)·diag(node_scale)。
    另: 载荷祖先链上没有任何非单位 scale(2026-08-13 全量核对 105 个载荷 + TOOL_MOUNT),
    所以 reparentPreservingWorld 的分解不会改动节点自身的 scale —— CAD 声明的那份就是
    播放期那份。

    Raises:
        CompileError: 除掉 scale 后仍不正交(说明传进来的 scale 不是该节点那份)
    """
    rotation = local[:3, :3] @ np.diag(1.0 / np.asarray(node_scale, dtype=float))
    residual = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    if residual > DOCK_ORTHOGONALITY_TOLERANCE:
        raise CompileError(
            f"落位局部矩阵除掉节点 scale {np.round(node_scale, 8).tolist()} 后仍不正交"
            f"(残差 {residual:.3e} > {DOCK_ORTHOGONALITY_TOLERANCE:.0e}) —— "
            "传进来的 scale 不是该节点世界矩阵里烤着的那份, dock 反解不出姿态")
    return {
        "position": [round(float(value), 8) for value in local[:3, 3]],
        "quaternion": [
            round(float(value), 8) for value in Rotation.from_matrix(rotation).as_quat()
        ],
    }


def load_rail_slots(control_root: Path) -> dict[int, float]:
    """读控制侧地轨站位表(slot -> mm)。

    真源是 config/points/plc/rail.yaml 的 plc_servo[].value(PC 侧 canonical 坐标),
    不在三维侧另写一份 —— 站位坐标现场会改。

    Args:
        control_root: 上位机仓库根

    Returns:
        {slot: mm}

    Raises:
        CompileError: 文件缺失或没有解析出 6 个站位
    """
    path = control_root / "config" / "points" / "plc" / "rail.yaml"
    if not path.is_file():
        raise CompileError(f"地轨站位表缺失: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    slots = {
        int(item["slot"]): float(item["value"])
        for item in document.get("plc_servo") or []
        if item.get("slot") is not None
    }
    if len(slots) != 6:
        raise CompileError(f"地轨站位表应有 6 个站位, 实际 {len(slots)}: {sorted(slots)}")
    return slots


def load_vision_capture_s(control_root: Path) -> float:
    """补光稳定期(秒) = app.yaml 的 pallas_vision.light_settle_ms —— 从控制侧 app.yaml 实读, 不在动画里编一个观感值。

    真机时序是"开 DO7 补光 → 等 light_settle_ms 稳定 → 触发拍照 → finally 关灯"。
    这里只返回**有依据的那一段**: settle。触发往返与熄灭另按 VISION_* 常量摆,
    合起来就是灯的关键帧节奏。读不到配置(如离线跑)时退回 1.0s。
    """
    path = control_root / "config" / "app.yaml"
    settle_ms = 1000.0
    if path.is_file():
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            settle_ms = float((cfg.get("pallas_vision") or {}).get("light_settle_ms", settle_ms))
        except (yaml.YAMLError, TypeError, ValueError):
            pass
    return settle_ms / 1000.0


@lru_cache(maxsize=8)
def load_gcode_calib(control_root: Path) -> dict:
    """刮取标定 = app.yaml 的 gcode 段 —— 从控制侧实读, 缺键 fail-fast 不给默认值。

    这些数直接定 9X/8Y/10Z 的绝对轴位(板原点、面高、桶偏移), 兜一个默认值等于
    安静地把刀演到错的位置 —— 与 load_rail_slots 同一条纪律, 而与
    load_vision_capture_s 那种"只影响灯节奏"的观感量不同。

    cm→机床 mm 的换算**逐字对齐 controller/cnc_path.py 的 `_to_machine`/`_CORNER_FLIP`**
    (管线脚本不 import 应用包, 见本文件头部的 sys.path 说明): 改那边必须改这里。

    Returns:
        {origin_x_mm, origin_y_mm, flip_x, flip_y, surface_z_mm, total_depth_mm,
         num_passes, feed_rate_mm_min, bottle_x_offset_mm, collector_x_positive,
         align_clearance_mm, cutter_diameter_mm, overlap_ratio}
    """
    path = control_root / "config" / "app.yaml"
    if not path.is_file():
        raise CompileError(f"app.yaml 缺失, 拿不到刮取标定: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    gcode = cfg.get("gcode") or {}
    tool = gcode.get("tool") or {}
    scrape = gcode.get("scrape") or {}

    def need(section: dict, key: str, where: str):
        value = section.get(key)
        if value is None:
            raise CompileError(f"app.yaml 的 {where}.{key} 缺失 —— 刮取演示的轴位要它定, 不兜默认值")
        return value

    corner = str(need(gcode, "origin_corner", "gcode"))
    corner_flip = {  # 与 cnc_path._CORNER_FLIP 逐字一致
        "lower-left": (False, False),
        "top-right": (True, True),
        "top-left": (False, True),
        "bottom-right": (True, False),
    }
    if corner not in corner_flip:
        raise CompileError(f"gcode.origin_corner 非法: {corner!r}(合法: {sorted(corner_flip)})")
    flip_x, flip_y = corner_flip[corner]
    return {
        "origin_x_mm": float(need(gcode, "plate_origin_x", "gcode")),
        "origin_y_mm": float(need(gcode, "plate_origin_y", "gcode")),
        "flip_x": flip_x,
        "flip_y": flip_y,
        "surface_z_mm": float(need(gcode, "plate_surface_z_mm", "gcode")),
        "align_clearance_mm": float(need(gcode, "align_clearance_mm", "gcode")),
        "total_depth_mm": float(need(scrape, "total_depth_mm", "gcode.scrape")),
        "num_passes": max(1, int(need(scrape, "num_passes", "gcode.scrape"))),
        "feed_rate_mm_min": float(need(scrape, "feed_rate", "gcode.scrape")),
        "bottle_x_offset_mm": float(need(tool, "bottle_x_offset_mm", "gcode.tool")),
        "collector_x_positive": bool(gcode.get("collector_x_positive", True)),
        "cutter_diameter_mm": float(need(tool, "cutter_diameter_mm", "gcode.tool")),
        "overlap_ratio": float(need(scrape, "overlap_ratio", "gcode.scrape")),
        # 松散系数: 刮下来的粉是松散的, 体积大于被切掉的实体硅胶层。它与上面那些不同,
        # **给默认值 1.0**(= 不放大) —— 后端 ScrapeArrays 引入这一项时就是这么定的
        # (默认 1.0 保证零回归, app.yaml 显式写 1.6), 这里跟着同一条约定, 不 fail-fast。
        "bulk_factor": float(scrape.get("bulk_factor", 1.0)),
    }


@lru_cache(maxsize=8)
def load_action_kinds(control_root: Path) -> dict[str, str]:
    """读控制侧动作台账, 出 {动作名: kind}。

    真源是 config/actions/**/*.yaml(顶层 key 就是动作名)。有了它, 编译器判"这条动作产不产
    生机构运动"可以按 kind 走, 而不是靠一张手工维护的忽略表 —— 上位机每加一个 host/vision
    只读动作, 引用它的整条流程就报"未知动作"编不出来, 而那条动作压根不动机构。

    Args:
        control_root: 上位机仓库根

    Returns:
        {动作名: kind}; 目录缺失时返回空表(调用方退回原有的忽略表判定)
    """
    kinds: dict[str, str] = {}
    folder = control_root / "config" / "actions"
    if not folder.is_dir():
        return kinds
    for path in sorted(folder.rglob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict):
            continue
        for name, spec in document.items():
            if isinstance(spec, dict) and spec.get("kind"):
                kinds[str(name)] = str(spec["kind"])
    return kinds


@lru_cache(maxsize=8)
def load_demo_well_mm(control_root: Path) -> tuple[float, float] | None:
    """演示用样品孔的 (4X mm, 3Y mm) —— 复用上位机的仿射解算, 三维侧不重算一份。

    真源是 config/calibration.yaml 的实测标定点; 解算走 controller.plate_catalog →
    plate_affine.solve_affine。在三维侧另写一遍仿射就是本仓吃过亏的"两边各留一份公式"。

    Args:
        control_root: 上位机仓库根

    Returns:
        (x_mm, y_mm); 该实例还没标定或取不到时返回 None(调用方据此跳过这一步, 不编位置)
    """
    try:
        sys.path.insert(0, str(control_root.parent))
        from eit_ptlc.controller.plate_affine import Well  # pylint: disable=import-outside-toplevel
        from eit_ptlc.controller.plate_catalog import PlateCatalog  # pylint: disable=import-outside-toplevel

        instance_id, row, col = DEMO_SAMPLE_WELL
        catalog = PlateCatalog.load(
            control_root / "config" / "plates.yaml",
            control_root / "config" / "calibration.yaml",
        )
        if not catalog.is_calibrated(instance_id):
            return None
        return catalog.well_target(instance_id, Well(int(row), int(col)))
    except Exception as exc:  # noqa: BLE001 —— 取不到就不演这一步, 不该拖垮整条流程
        # 但**必须说出为什么**: 静默返回 None 的话, "孔位没演" 与 "孔板没标定" 长得一样
        print(f"[i] 演示样品孔取不到, 该步将不发: {type(exc).__name__}: {exc}")
        return None


@lru_cache(maxsize=8)
def load_servo_points(control_root: Path) -> dict[str, float]:
    """读控制侧全部 PLC 伺服示教点(点位 key -> 毫米)。

    真源是 config/points/plc/*.yaml 的 `plc_servo_target` 与 `plc_servo_composite`。
    这些值原本是 PLC 里的硬编码常量(如拍照 8Y=420), 现已逐点收编成 PC 侧单一真源并可
    现场重新示教 —— 所以片段**必须实读**, 不能在三维侧再抄一份常量: 抄下来的那份在
    重新示教后不会报错, 只会安静地演一个陈旧位置。

    复合点(点样位置)的成员按 `<点位key>.<成员key>` 入表, 避免第二个复合点静默撞名。
    `pending: true` **照收**: 那个标记的意思是"PLC 侧 flat 节点还没建, 不许下发/读实际位",
    点表自己的注释也写着"可离线存值 (PC 真源)" —— 值仍是真值, 只是推不下去。
    (早先这里把 pending 排除掉是对的, 因为当时 5Z 两条的 value 还是 0.0 占位; 2026-08-05
     从在线 PLC 实读补上 45.0/46.5 之后, 那条理由就不成立了。)
    真正不该入表的是**没有 value**的条目 —— 下面按 value is None 挡。

    Args:
        control_root: 上位机仓库根

    Returns:
        {点位 key: 毫米}; 目录缺失时返回空表(调用方按"点表不可用"处理)
    """
    points: dict[str, float] = {}
    folder = control_root / "config" / "points" / "plc"
    if not folder.is_dir():
        return points
    for path in sorted(folder.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for item in document.get("plc_servo_target") or []:
            if item.get("key") is None or item.get("value") is None:
                continue
            points[str(item["key"])] = float(item["value"])
        # struct 槽位点(值还在 HMI 数组里、尚未收编成 flat *_Target 的那些): 地轨 6 站与
        # 点样放板位都是这一形态。它们没有 pending 概念 —— 有 value 就是实读记下来的。
        for item in document.get("plc_servo") or []:
            if item.get("key") is None or item.get("value") is None:
                continue
            points[str(item["key"])] = float(item["value"])
        for item in document.get("plc_servo_composite") or []:
            for member in item.get("members") or []:
                if member.get("key") is None or member.get("value") is None:
                    continue
                points[f"{item['key']}.{member['key']}"] = float(member["value"])
    return points


def default_bindings(document: dict) -> dict[str, Any]:
    """取一个 operation 的变量默认值。

    `io: in` 是入参默认值; `io: var` / `io: out` 里**带 default 的**也一并取 —— 它们是脚本
    自己声明的编译期常量(如视觉纠偏的收敛阈值 drz_threshold_deg=0.8, 或跨段上下文
    collector_hole 的初值 1), 读它不等于猜运行期状态。
    不带 default 的一律不入表: 那种是运行期才被赋值的(如 voff_rz 这类反馈结果),
    必须由调用方以显式假设给定, 否则求值时照旧抛"引用了未绑定的变量"。
    """
    result: dict[str, Any] = {}
    for item in document.get("vars") or []:
        io = item.get("io")
        if io == "in":
            result[item["name"]] = _coerce_default(item)
        elif io in ("var", "out") and item.get("default") is not None:
            result[item["name"]] = _coerce_default(item)
    return result


def _coerce_default(item: dict) -> Any:
    """按声明类型把 YAML 里的默认值转成真实类型。

    脚本里数值默认值常被写成字符串(如 drz_threshold_deg 的 `default: '0.8'`),
    不转的话比较运算会拿字符串去比大小。
    """
    value = item.get("default")
    kind = str(item.get("type") or "").upper()
    if value is None or not isinstance(value, str):
        return value
    try:
        if kind == "FLOAT":
            return float(value)
        if kind == "INT":
            return int(value)
        if kind == "BOOL":
            return value.strip().lower() in ("true", "1", "yes")
    except ValueError:
        return value
    return value


# --------------------------------------------------------------------------- #
# 载荷账
# --------------------------------------------------------------------------- #

class PayloadLedger:
    """座位 -> 载荷 的编译期账本, 从 manifest.attachments 的 payload.seat 反查。

    片段里的 attach/detach 需要三样东西: 载荷 id、目的父级节点路径、以及落位后
    要显隐交换的那一对实例。全部从 manifest 取, 不在片段生成器里另写一份路径。
    """

    def __init__(self, manifest: dict) -> None:
        self.by_seat: dict[str, dict] = {}
        self.by_id: dict[str, dict] = {}
        for entry in manifest.get("attachments") or []:
            payload = entry.get("payload")
            if not payload:
                continue
            node = str(entry["node"])
            record = {
                "id": entry["id"],
                "node": node,
                "parent": node.rsplit("/", 1)[0] if "/" in node else "",
                "seat": payload["seat"],
                "kind": payload["kind"],
                "grip": payload["grip"],
                # 单件抓取锚点(fit_item_grips 产出, 经 manifest 透传): _grab_corrected
                # 拿它把烤进片段的夹持变换/dock 修到与前端磁吸同一个位姿。None 安全。
                "mountLocal": payload.get("mountLocal"),
                "grabLocal": payload.get("grabLocal"),
                # 逐件夹持闭合(见 _close_value_for): 瓶颈 0.2543 / 粉桶摇篮同心 0.817
                "grabFeature": payload.get("grabFeature"),
                "closeValue": payload.get("closeValue"),
            }
            self.by_seat[payload["seat"]] = record
            self.by_id[entry["id"]] = record

    def require(self, seat: str) -> dict:
        record = self.by_seat.get(seat)
        if record is None:
            raise CompileError(
                f"manifest 里没有座位 {seat} 的载荷声明 —— 先在 rig_map.payloads 里补 ref"
            )
        return record

    def items_of(self, payload_id: str, holes: int = 6) -> list[str]:
        """一块**托盘**的逐孔耗材 id(它们是托盘的子节点, 随托盘一起走)。

        单件载荷返回空表: 它自己就是耗材, 没有下一层。按托盘规则拼会得到
        `INV_STAGING_B_ITEM_3_ITEM_1` 这种不存在的 id —— 发出去之后前端 setState 查不到
        stateSpecs 只会静默 no-op, 而既有的"state 目标未声明"检查只覆盖 index.families
        展开的那几十个片段, 200 个 flow.* 一个都不查。
        """
        record = self.by_id.get(payload_id)
        if record is None:
            raise CompileError(f"未知载荷 id: {payload_id}(不在 manifest.attachments 里)")
        if record["kind"] != "tray":
            return []
        return [f"{payload_id}_ITEM_{hole}" for hole in range(1, holes + 1)]


# --------------------------------------------------------------------------- #
# 编译上下文
# --------------------------------------------------------------------------- #

class ClipBuilder:
    """把指令流逐条翻译成片段步骤, 并维护地轨/夹爪/载荷的编译期状态。"""

    def __init__(
        self,
        *,
        control_root: Path,
        registry,
        calibration: dict,
        manifest: dict,
        rail_slots: dict[int, float],
        assume_tool: int,
        transfer: "TransferSpec | None" = None,
        scene: "GlbScene | None" = None,
        payload_frames: dict | None = None,
        plate: bool = False,
    ) -> None:
        self.control_root = control_root
        # 泵档持久值(config.pump)接入 profiles provider —— emit_pump_syringe 的
        # speed_of 经 pump_default_hint 走与执行器逐字同构的回退链; 幂等, 失败回常量。
        install_pump_defaults_from_app_yaml(control_root / "config" / "app.yaml")
        self.registry = registry
        self.calibration = calibration
        self.manifest = manifest
        self.rail_slots = rail_slots
        self.ledger = PayloadLedger(manifest)
        self.assume_tool = assume_tool
        #: 补光稳定期(秒), 从控制侧 app.yaml 的 light_settle_ms 实读, 不写死
        self.vision_capture_s = load_vision_capture_s(control_root)
        #: 全部 PLC 伺服示教点(key -> mm), 从控制侧 points/plc/*.yaml 实读。
        #: SEQUENCE_ACTIONS 里的 point 步靠它把 point_ref 入参解成毫米。
        self.servo_points = load_servo_points(control_root)
        #: 动作名 -> kind, 从控制侧 config/actions 实读(见 STILL_ACTION_KINDS)
        self.action_kinds = load_action_kinds(control_root)
        #: 落点 -> (工位轴, 毫米, 出处), 点位引用已解开(见 seat_axes_resolved)
        self.seat_axes = seat_axes_resolved(control_root)
        #: 演示样品孔的 (4X, 3Y) 毫米; 未标定则 None(那一步不发, 见 emit_sequence 的 well 分支)
        self.demo_well_mm = load_demo_well_mm(control_root)
        self.transfer = transfer
        self.scene = scene
        self.posture = RobotPosture(scene, manifest) if scene is not None else None
        #: 取料瞬间定下的"托盘相对法兰"刚体变换
        self._grip_transform: np.ndarray | None = None
        self._pick_joints: list[float] | None = None
        self._pick_rail: float = 0.0
        self._carried_node: str = ""
        #: 载荷几何参考帧(generated/payload-poses.json 的 poses 段)
        self.payload_frames: dict | None = payload_frames
        #: 上一次落位的平移校正量(示教坐标系与 CAD 之间的标定残差, mm)
        self._last_alignment_mm: float = 0.0
        #: 每次落位的"示教点推算 vs CAD 实测"残差, 由调用方做门禁
        self.dock_residuals: list[dict] = []
        #: pose 与 joint 不自洽的点(基准迁移只改了 pose, joint 还没走示教闭环刷新)
        self.stale_joint_points: list[dict] = []

        # -- 薄层板行踪(只有板路线/流程片段开) ------------------------------ #
        #: 是否为片段生成 `plate` 原语
        self.plate = bool(plate)
        #: 停放位 -> 板锚点节点名
        self.plate_anchors = resolve_plate_anchors(scene) if self.plate else {}
        #: 最近一次命中 PLATE_POINT_SLOT 的点所对应的停放位
        self._plate_slot: str | None = None
        #: 板**当前坐在**的落点; 在机器人手上(或未出场/已并入板堆)时为 None。
        #: 与 _plate_slot 语义不同: 那个是"最近路过哪个基准点"(吸和放都会命中),
        #: 这个才回答"埋料时板到底在不在被埋的料仓里"。
        self._plate_at: str | None = None
        #: 板是否已经在片段里出场
        self._plate_shown = False
        #: 起手式(插在片段开头的两步), 由第一次吸/放动作反推
        self.plate_intro: list[dict] = []
        #: 取放点与落点锚点的几何核对(供诊断: 同一个架内应当是同一个偏置)
        self.plate_anchor_checks: list[dict] = []
        #: 吸盘翻转执行器当前的指令值(0=下翻/1=上翻), 算持板位姿要用
        self._flip_value = 0.0
        #: 片段里是否已经发生过机械臂运动(require_anchor 据此决定"采纳"还是"断言")
        self._moved = False
        #: 路线声明的"起手就持板, 板取自这个落点"(见 TransferSpec.carry_in)
        self.carry_in = ""
        #: **全局显式假设**: 内联到任何子脚本时, 只要它声明了同名 var 就注入这个值。
        #: 用来消解那些"读运行期测量结果"的入参(典型是视觉纠偏的 voff_rz/voff_xy)。
        #: 顶层路线可以用 spec.inputs 直接给, 但流程段是**隔了两三层**才走到用它的脚本,
        #: 中间那层的 inputs 里并没有这个键 —— 所以必须有一条能穿透内联的通道。
        #: 它不是"默认值": 值本身写在 PLATE_VISION_ASSUMPTION 里, 并随片段落进 YAML。
        self.assumptions: dict[str, Any] = {}

        home_point = registry.get("robot-main.home")
        if home_point.joint is None:
            raise CompileError("robot-main.home 没有实测 joint")
        self.home_joints = list(home_point.joint)
        self.current_joints = list(home_point.joint)
        self.home_rail_mm = float(rail_slots[4])
        self.current_rail_mm = self.home_rail_mm
        #: 地轨是否已被"钉住"(显式 rail.move / 点位槽码收养 / 已参与过载荷姿态账)。
        #: 未钉住时首个带槽码的 move_l 点把它的站位**收养进 home 声明**(见
        #: _ensure_point_rail); 钉住之后不一致 = 编排与示教世界真错位, 硬失败。
        self._rail_pinned = False
        #: 各直线轴当前停在哪(毫米, 控制器口径)。emit_axis 据此跳过零位移步。
        #: 地轨有初值(片段起手就在 4 号工具位); 有静态停放位的工位轴按 STATION_AXIS_HOME
        #: 起手(如 9X 常驻 335 让位位); 其余工位轴起手态由各自的 init 动作定, 没被驱动过
        #: 就是 None —— 那时第一次驱动一定发步。
        self.axis_mm: dict[str, float] = {"axis_11y": self.home_rail_mm}
        #: 片段起手时工位轴的声明位(见 _register_seat_axis 与 SEAT_AXES)。
        self.home_axis_mm: dict[str, float] = {}
        # 静态停放位双播种: home 声明起手状态(否则前端停 0/CAD 基位), axis_mm 让
        # "回停放位"步按零位移跳过 —— 副作用是 photoscrape_prepare 那两步让位动画消失,
        # 这是对的: 准备开场时刀本来就驻在让位位(2026-08-06 用户确认取这头)。
        for _axis_id, (_park_mm, _why) in STATION_AXIS_HOME.items():
            self.home_axis_mm[_axis_id] = float(_park_mm)
            self.axis_mm[_axis_id] = float(_park_mm)
        #: 已发步的执行器值(emit/_note_mechanism 跟踪) —— _posed_world 拿它把骑机构的
        #: 站座(翻料缸上的接粉座、收集工位的瓶/桶)摆到播放态再取姿态。
        self.actuator_value: dict[str, float] = {}
        self._rigged_axis_ids: set[str] = {
            str(axis.get("id")) for axis in manifest.get("axes") or [] if axis.get("rigged")}
        #: 阶段起手态对全局机构 home 的按段覆盖(PhaseEntry.mechanisms 播种,
        #: mechanism_home() 应用)。典型: collect_load 起手翻料缸=1(倒粉位)。
        self.home_mechanism_overrides: dict[str, float] = {}

        # -- 展缸液面 ---------------------------------------------------------- #
        #: 液面契约, **整段来自 manifest** —— 唯一真源是 gen_twin_manifest.TANK_LIQUID_ACTIONS,
        #: 前端 TankLiquidModel 与 demo/actionSim.js 消费的也是这同一份。本文件绝不再声明
        #: 一张液面动作表: 那就是第三份真源, 而它漂了的表现是"演示里注了 40mL、实况页显示
        #: 20mL", 两边都看着挺正常, 没有任何指标会报警。
        self.tank_liquid: dict = dict(manifest.get("tankLiquid") or {})
        #: 编译期各缸已推到的体积(缸号 1-8 -> mL)。跨动作跟踪, 见 emit_tank_liquid ——
        #: 有了它, 流程里的排液动作不需要任何假设, 起点就是前一条注液动作留下的体积。
        self.tank_volume_ml: dict[int, float] = {}
        #: 片段起手时各缸的声明液量(写进 home.liquid_ml)。与 home_axis_mm 同一条理由:
        #: 液面盒的建模位是**满到槽口**, 不声明就停在满缸。
        self.home_liquid_ml: dict[str, float] = {}
        #: 片段起手时各粉桶的声明粉量/洗脱色(写进 home.powder_mm3 / home.powder_tint)。
        #: 与 home_liquid_ml 同一条理由: MachineStateDriver.home() 把粉一律清零并复位
        #: 未洗色, 不声明就是"收集-执行在演一只空桶"。真源是 PHASE_ENTRY_STATE.powders。
        self.home_powder_mm3: dict[str, float] = {}
        self.home_powder_tint: dict[str, float] = {}

        # -- 驻位液体(座位实例内液面, 如收集样品瓶) ----------------------------- #
        #: 契约整段来自 manifest["liquids"](真源 gen_twin_manifest.STATION_LIQUID_ACTIONS),
        #: 逐条自带 cavity/exaggeration 与动作规则; **实机时长 roundS 与演示时长 demoS 也
        #: 都在表里**, 三个消费方(本文件 emit_station_liquid / flowSim.emitStationLiquid /
        #: actionSim.stationLiquidSteps)只读不换算 —— 展缸那套"同一条规则三处手抄"的漂移
        #: 风险在这里从结构上消掉。查不到表就退回 FLUID_TIME_ACTIONS 时间格, 整条链路
        #: 一键回退(rig_map 座位 liquid.enabled=false → 03 不建液柱 → manifest 无本表)。
        self.station_liquids: dict[str, dict] = {}
        for _liq in (manifest.get("liquids") or []):
            for _liq_action in (_liq.get("actions") or {}):
                if _liq_action in self.station_liquids:
                    raise CompileError(
                        f"manifest.liquids 里动作 {_liq_action} 被两条液体同时认领 —— "
                        "同一动作往哪只容器注液必须唯一")
                self.station_liquids[_liq_action] = _liq
        #: 编译期各驻位液体已推到的体积(liquid id -> mL)。跨动作/跨段跟踪, 与
        #: tank_volume_ml 同构; collect_unload 的起手承接靠 seed 从丢弃 builder 收它。
        self.station_liquid_ml: dict[str, float] = {}

        # -- 注射泵 ------------------------------------------------------------ #
        #: 泵契约, **整段来自 manifest** —— 唯一真源是 gen_twin_manifest.PUMP_SYRINGE_ACTIONS,
        #: 前端 PumpSyringeModel(实时台)与 demo/flowSim.js(近似档)消费的也是这同一份。
        #: 与 tank_liquid 同一条铁律: 本文件绝不再声明一张泵动作表。
        self.pump_syringe: dict = dict(manifest.get("pumpSyringe") or {})
        #: 编译期各泵已推到的针筒体积(泵 id -> mL)。跨动作跟踪, 与 tank_volume_ml 同理:
        #: sampling.prep 停在气隙位、aspirate 在其上相对叠加, 是一条跨动作的连续行程。
        self.pump_volume_ml: dict[str, float] = {}
        #: 编译期各泵阀指针当前所在口(泵 id -> 1 基口号)。换阀步只在口变化时发。
        self.pump_valve_port: dict[str, int] = {}
        #: 片段起手时各泵的声明体积/阀位(写进 home.pump_ml / home.pump_port)。只在片段
        #: 真的驱动了该泵时写 —— 非泵片段的 home 块逐字节不变。
        self.home_pump_ml: dict[str, float] = {}
        self.home_pump_port: dict[str, int] = {}

        self.steps: list[dict] = []
        self.trajectories: dict[str, list[list[float]]] = {}
        #: 座位栈: 内联到某个取放脚本时压栈, 供夹爪动作查"当前在操作哪个座位"。
        self._seat_stack: list[tuple[str, str]] = []
        #: 脚本帧栈 (脚本名, 该脚本的座位或 None)。与 _seat_stack 平行, 区别是**每个**
        #: 内联脚本都压, 不只是有座位的那些。
        #:
        #: 为什么需要第二个栈: 夹爪合拢分两种物理动作 —— "夹住载荷"(开度 = holdValue) 与
        #: "空爪紧闭"(开度 = 满行程, 卸爪前把爪收起来免得刮到刀库)。区分它们的唯一可靠依据
        #: 是这条 gripper-close **词法上写在谁的正文里**:
        #:   robot_tool_put 的空爪紧闭是从取料脚本的入口 prologue (run_script
        #:   robot_tool_ensure -> emit_tool_change) 里展开出来的, 那一刻
        #:   `_seat_stack[-1]` 仍是外层取料脚本的座位 (role='pick'), 而 `_in_gripper` 也仍是
        #:   None (真取件那一刻同样是 None) —— **两个直觉判据都会判错这 4 处**。
        #:   只有"最内层脚本帧是不是取料脚本"能把它们分开。
        self._script_stack: list[tuple[str, tuple[str, str] | None]] = []
        #: 已经被夹爪拿起、尚未放下的载荷 id。
        self._in_gripper: str | None = None
        self.notes: list[str] = []
        #: 编译**顶层工艺流程**(而不是转移片段)时置 True, 见 run_instruction 的说明。
        self.flow_mode: bool = False
        #: 流程模式下每一处"外壳被拍平"的记录, 随片段落盘 —— 看动画的人必须知道
        #: 这条时间轴取了哪个分支、循环只演了第几轮。
        self.flow_notes: list[str] = []
        #: 刮取条带声明(板 cm 帧), 随片段落盘进 compiled.scrapeRegions —— 前端
        #: PlateStage.setScrape 按它换算板面遮罩。键是板 id(片段里恒为 PLATE_CLIP_ID)。
        self.scrape_regions: dict[str, dict] = {}
        #: emit_scrape 已展开过一次(pass 循环里第 2 刀起只演时间格, 见该方法注释)。
        self._scrape_emitted = False
        #: 点样色带声明(板 cm 帧), 随片段落盘进 compiled.spotRegions —— 前端
        #: PlateStage.setSpot 按它换算板面遮罩(帧链与 scrape 完全同构)。
        self.spot_regions: dict[str, dict] = {}
        #: 色带通道已发射过(润洗轮重点同一条带时只演轴运动, 色带保持已满, 见 emit_spot)。
        self._spot_emitted = False
        #: 展开润湿声明(板 cm 帧), 随片段落盘进 compiled.wetRegions —— 前端
        #: PlateStage.setWet 按它换算(缸内板走重力锚定, 见 scrapeOverlay.gravityDirsWorld)。
        self.wet_regions: dict[str, dict] = {}
        #: 润湿通道已发射过(同段第二次 wait_level 只出时间格)。
        self._wet_emitted = False
        #: 本片段驱过的、**没有几何**的机构(rigged:false)。随片段落盘供门禁区分
        #: "确实没几何"与"打错 id" —— 见 _mechanism_channel。
        self.data_only_mechanisms: set[str] = set()
        #: 换刀 prologue 的嵌套深度(>0 即禁止载荷交接) —— 见 emit_tool_action 的闸门注释。
        self._in_tool_change = 0
        #: 载荷起手式: 第一次取某件载荷时点亮它的源实例(与它的逐孔件)。
        #: 必须有 —— MachineStateDriver.home() 把 manifest.states 全部置 false, 开闸而不补
        #: 起手式的结果是"片段一开始什么都看不见, 机械臂抓着空气走一趟, 落位那一刻目的
        #: 实例凭空出现"。与 plate_intro 同一条纪律: 各步 at:0 / dur:0, 不占时间轴。
        self.payload_intro: list[dict] = []
        self._intro_seen: set[str] = set()
        #: 以"父托盘"身份被点亮过的 id。与 _intro_seen 分开存: 塞进 _intro_seen 会让
        #: 后续真正的整盘取件误判"点过了", 跳过它逐孔件的点亮。
        self._intro_parent_seen: set[str] = set()
        #: 起手持件的占位 dock(preload_payload 发出, _put_payload 到位时回填真值)。
        #: 持引用原地 update —— 步骤表存的是同一个 dict, yaml 落盘时已是真值。
        self._preload_dock: dict | None = None

    # -- 步骤发射 ---------------------------------------------------------- #

    def emit(self, label: str, duration: float, body: dict, *, ease: str | None = None,
             at: float | None = None) -> None:
        """发一步。`at` 缺省 = 上一步结束(前端 compileClip 的光标规则); 显式给 at 即并行。

        显式 at 目前只有 emit_scrape 用(刮取遮罩要与轴冲程**同 at 同 dur**推进)。
        ⚠ 给绝对 at 的步必须晚于任何会平移时间轴的插入 —— 现状安全: insert_steps 只在
        收尾插 at:0/dur:0 的起手式, 不占时间。若将来有人往中段插**占时**步, 这里的绝对
        时刻会整体错位, 先改这条约定再动手。
        """
        self._note_mechanism(body)
        step: dict[str, Any] = {"label": label}
        if at is not None:
            step["at"] = round(float(at), 3)
        step["dur"] = round(float(duration), 3)
        if ease is not None:
            step["ease"] = ease
        step["do"] = body
        self.steps.append(step)

    def _timeline_end_s(self) -> float:
        """当前时间轴末端(秒) —— 与前端 compileClip 的 at/dur 光标规则逐字一致:
        每步 at 缺省为上一步(声明序)的 at+dur, 显式 at 则直接采用。"""
        cursor = 0.0
        for step in self.steps:
            cursor = float(step.get("at", cursor)) + float(step.get("dur", 0.0))
        return round(cursor, 3)

    def insert_steps(self, index: int, steps: list[dict]) -> None:
        """在片段中间插入若干步, **并重排 moveLTrajectories 的键**。

        轨迹表是按步骤下标索引的(`self.trajectories[str(index)]`), 插一步就会把它后面
        所有 move_l 的轨迹错位一格 —— 表现是"某段直线运动播的是别人的轨迹", 画面照样
        流畅, 只是机械臂穿过了它本不该穿过的地方。所以插入必须走这一个入口。

        Args:
            index: 插入位置
            steps: 要插入的步骤(按给定顺序)
        """
        if not steps:
            return
        shift = len(steps)
        self.steps[index:index] = steps
        self.trajectories = {
            str(int(key) + shift if int(key) >= index else int(key)): value
            for key, value in self.trajectories.items()
        }

    def emit_follow(self, label: str, duration: float, body: dict) -> None:
        """紧跟上一步结束时刻的步骤(clip 的 at 缺省即上一步结束)。

        载荷交接刻意用**顺序**而不是并行: attach 必须在夹爪合拢**之后**发生, detach
        必须在张开之后, 实例交换又必须在落位补间跑完之后 —— 这个先后顺序就是正确性
        本身, 并行会让"松爪瞬间板已经换成目的实例"这种错帧出现。
        """
        self._note_mechanism(body)
        self.steps.append({"label": label, "dur": round(float(duration), 3), "do": body})

    def _note_mechanism(self, body: dict) -> None:
        """跟踪执行器已发步值(emit 与 emit_follow **都**要过这里 —— follow 不走 emit,
        只挂一处会漏)。linkage 不跟踪: 载荷不骑在夹爪指上, _actuator_overrides_for 若
        真遇到会硬死。"""
        actuator = body.get("actuator") if isinstance(body, dict) else None
        if actuator and "to" in actuator:
            self.actuator_value[str(actuator["id"])] = float(actuator["to"])

    # -- 指令翻译 ---------------------------------------------------------- #

    def run_body(self, instructions: Iterable[dict], bindings: dict[str, Any], depth: int) -> None:
        for instruction in instructions or []:
            self.run_instruction(instruction, bindings, depth)

    def run_instruction(self, instruction: dict, bindings: dict[str, Any], depth: int) -> None:
        op = instruction.get("op")
        if op in (None, "comment"):
            return
        if op == "if":
            try:
                branch = select_branch(instruction, bindings)
            except CompileError:
                # 条件读的是运行期反馈(“板到位了吗”这类), 编译期求不出来。
                # 转移片段照旧硬失败; 顶层流程取第一支并记账 —— 与前端即时近似同一条约定,
                # 两边取不同的支会让"精编译"与"近似"演出两条不同的路线, 那比两边都近似更糟。
                if not self.flow_mode:
                    raise
                self.flow_notes.append("条件分支按“条件成立”那一支编排; 实机按现场反馈选")
                branch = instruction.get("then") or []
            self.run_body(branch, bindings, depth)
            return
        if op == "run_script":
            self.inline_script(instruction, bindings, depth)
            return
        if op == "call":
            self.emit_call(instruction, bindings)
            return
        if self.flow_mode and self.run_shell_instruction(instruction, bindings, depth):
            return
        if op in ("assign", "human", "raise", "try", "while", "for"):
            # 转移路线里不该出现这些(它们属于决策外壳与工艺流程)。出现了说明选错了
            # 编译目标, 硬失败比悄悄跳过安全 —— 跳过会产出一段"看着能播但少了动作"的片段。
            raise CompileError(f"转移片段不支持指令 op={op}(出现在编译目标里说明选错了脚本)")
        raise CompileError(f"未知指令 op={op}")

    def run_shell_instruction(self, instruction: dict, bindings: dict[str, Any], depth: int) -> bool:
        """把**决策外壳**语句拍平成一条时间轴 —— 只在编译顶层工艺流程时启用。

        为什么这里可以放宽, 而转移片段那边不行:

        转移片段(robot_suction_pick 之类)是**动作序列**, 里面出现 while/assign 就说明选错了
        编译目标, 硬失败是对的。顶层工艺流程(sampling_full、system_init_all…)则天生带决策
        外壳 —— 101 条里绝大多数含 with_resources/try/for/parallel。对它们硬失败的结果不是
        "拦住了一个错误", 而是**83 条流程里 69 条永远编不出来**, 演示栏只能退回前端的即时
        近似, 而那一级解不出派生点、也没有 move_l 轨迹。

        所以这里拍平的是"哪条路径", 拍平方式**逐条记进 flow_notes 随片段落盘**;
        **单步内容的纪律一点没松**: 点位缺实测关节角、FK 残差超限、落点越界、未知动作,
        照旧 CompileError。放宽的是外壳, 不是几何。

        Args:
            instruction: 语句
            bindings: 当前作用域
            depth: 内联深度

        Returns:
            True 表示本函数已经处理; False 交回调用方按原规则报错
        """
        op = instruction.get("op")
        if op in ("with_resources", "try"):
            # 资源持有与异常兜底都不产生运动: 透明穿过, 只走正常路径(catch 段不编)
            self.run_body(instruction.get("body") or [], bindings, depth)
            return True
        if op == "parallel":
            self.flow_notes.append("并行块按分支先后依次编排; 实机是同时进行")
            for branch in instruction.get("branches") or []:
                self.run_body(branch, bindings, depth)
            return True
        if op == "for":
            # 只编第一轮, 并把循环变量绑成 start 的字面值 —— "只演一轮"的字面意思就是
            # 演第一轮。start 取不到确定值时不绑: 宁可这一轮里的动作报缺参数, 也不编一个缸号。
            first = evaluate_optional(instruction.get("start"), bindings)
            scoped = dict(bindings)
            name = str(instruction.get("var") or "")
            if name and first is not None:
                scoped[name] = first
            self.flow_notes.append(
                f"for 循环只编第 1 轮({name}={first if first is not None else '未知'}); 实机跑完整轮数")
            self.run_body(instruction.get("body") or [], scoped, depth)
            return True
        if op in ("while", "repeat"):
            self.flow_notes.append(f"{op} 循环只编一轮; 实机的轮数由运行期条件决定")
            self.run_body(instruction.get("body") or [], bindings, depth)
            return True
        if op == "human":
            self.emit(f"人工确认: {instruction.get('prompt') or instruction.get('kind') or 'confirm'}",
                      0.35, {"wait": {}})
            return True
        if op == "raise":
            # 异常路径不属于这条时间轴
            return True
        if op == "assign":
            # 只认能静态求值的赋值; 求不出来的**不报错也不猜**, 让引用它的那一步自己去撞
            # "引用了未绑定的变量" —— 报错要落在真正用到它的地方, 而不是这里。
            target = instruction.get("target")
            name = target.get("var") if isinstance(target, dict) else None
            value = evaluate_optional(instruction.get("value"), bindings)
            if name and value is not None:
                bindings[str(name)] = value
            return True
        return False

    def inline_script(self, instruction: dict, bindings: dict[str, Any], depth: int) -> None:
        if depth >= MAX_INLINE_DEPTH:
            raise CompileError(f"run_script 内联深度超过 {MAX_INLINE_DEPTH}, 疑似成环")
        name = str(instruction.get("script"))
        document = load_operation(self.control_root, name)
        child = default_bindings(document)
        declared = {str(item.get("name")) for item in (document.get("vars") or []) if item.get("name")}
        for key, value in self.assumptions.items():
            if key in declared and key not in child:
                child[key] = value
        for key, expression in (instruction.get("inputs") or {}).items():
            child[key] = evaluate_expression(expression, bindings)
        self._apply_staging_plan_assumption(name, child, declared)

        if self._resolve_by_assumption(name, child, depth):
            return

        seat = self._seat_for(name, child)
        # 两个栈都压: _seat_stack 只收有座位的脚本(载荷交接要它), _script_stack 收全部 ——
        # 夹爪该发"夹持"还是"空爪紧闭", 判的是这条 gripper-close 写在**谁的正文**里, 而不是
        # "当前处在谁的座位作用域内"。二者会分叉, 见 _closing_on_payload 的说明。
        self._script_stack.append((name, seat))
        if seat is not None:
            self._seat_stack.append(seat)
        try:
            self.run_body(document.get("body") or [], child, depth + 1)
        finally:
            if seat is not None:
                self._seat_stack.pop()
            self._script_stack.pop()

    def _resolve_by_assumption(self, script_name: str, child_bindings: dict[str, Any],
                               depth: int = 0) -> bool:
        """用显式假设消解那些"读运行期权威态再决定做不做"的子脚本。

        这类脚本(robot_tool_ensure 读 robot.query 的 mounted_tool)在编译期没有真值。
        既不能猜一个默认值, 也不能把两条分支都编进去。做法是: 调用方声明本段开始时的
        状态, 假设成立就走"什么都不用做"的那一支(与真机 current==needed 的快路径逐字
        对应), 假设不成立就**硬失败** —— 那说明选错了编译目标或参数。

        Args:
            script_name: 被调子脚本名
            child_bindings: 已求值的入参

        顶层工艺流程(flow_mode)则不同: 换刀是它工作的一部分, 拒编等于 25 条流程直接报废。
        那里改成**把换刀真编出来** —— 见 emit_tool_change。

        Args:
            script_name: 被调子脚本名
            child_bindings: 已求值的入参

        Returns:
            True 表示已由假设消解, 调用方不应再内联它

        Raises:
            CompileError: 假设不成立(仅转移片段)
        """
        if script_name != "robot_tool_ensure":
            return False
        needed = int(child_bindings.get("needed"))
        if needed == self.assume_tool:
            self.notes.append(f"robot_tool_ensure(needed={needed}) 按「已挂该刀」跳过")
            return True
        if self.flow_mode:
            self.emit_tool_change(needed, depth)
            return True
        raise CompileError(
            f"robot_tool_ensure 需要 {needed} 号刀, 但本段的显式假设是已挂 {self.assume_tool} 号刀; "
            "转移片段不编译换刀过程(它是独立的 robot.tool_pickup/return 片段)"
        )

    def emit_tool_change(self, needed: int, depth: int = 0) -> None:
        """把一次换刀编成真实动作: 放回当前刀 -> 取需要的那把。

        不是"假设已经挂好了"。robot_tool_ensure 在真机上读 robot.query 决定做不做, 编译期
        读不到那个反馈; 但**当前挂的是几号刀本来就是本段的显式声明**(assume_tool), 所以
        needed != assume_tool 时该做什么是确定的 —— 与脚本里 `if current != needed` 那一支
        逐字对应。于是这里不内联 robot_tool_ensure(它头两句要读运行期反馈), 而是直接内联它
        那一支真正要跑的两个子脚本, 出来的是**实测示教点 + 离线 IK 的真轨迹**。

        Args:
            needed: 目标刀号
        """
        previous = self.assume_tool
        self.flow_notes.append(f"换刀已按 {previous} 号刀 → {needed} 号刀编出实际轨迹")
        # 深度照传, 不重置: 换刀脚本目前不再 run_script 别人, 但把计数器清零等于把
        # 成环护栏拆了 —— 那种护栏只在被拆之后才显出价值。
        #
        # 整段标成"换刀中": robot_tool_put 的 2/3 号刀分支里有 gripper-close(卸爪前把爪
        # 收起来免得刮到刀库), 而换刀是从取放脚本的入口 prologue 展开的 —— 此刻
        # _seat_stack 顶上正是那个取料座位。不挡住的话那一下会被 emit_tool_action 当成
        # 取件, 静默 attach 一个错的载荷。
        self._in_tool_change += 1
        try:
            if previous:
                self.inline_script(
                    {"script": "robot_tool_put", "inputs": {"tool_id": {"lit": previous}}},
                    {}, depth)
            self.assume_tool = needed
            self.inline_script(
                {"script": "robot_tool_pick", "inputs": {"tool_id": {"lit": needed}}}, {}, depth)
        finally:
            self._in_tool_change -= 1

    def _apply_staging_plan_assumption(self, name: str, bindings: dict[str, Any],
                                       declared: set[str]) -> None:
        """给换板决策脚本强制覆盖运行期出参 —— 见 STAGING_PLAN_ASSUMPTION。

        强制覆盖(而不是 setdefault)是必须的: 那几个变量在脚本里带 default, default_bindings
        已经把它们收进 bindings 了, 温和注入永远进不去。
        """
        if name not in STAGING_PLAN_SCRIPTS:
            return
        applied = {key: value for key, value in STAGING_PLAN_ASSUMPTION.items()
                   if key in declared}
        if not applied:
            raise CompileError(
                f"{name} 在 STAGING_PLAN_SCRIPTS 里, 但它一个决策出参都没声明 —— "
                "脚本改过了, STAGING_PLAN_ASSUMPTION 的键要跟着改")
        bindings.update(applied)
        note = f"{name} 的换板决策取显式假设 {applied}(运行期由 material.plan_staging 给出)"
        if note not in self.flow_notes:
            self.flow_notes.append(note)

    def run_operation(self, name: str, document: dict, bindings: dict[str, Any]) -> None:
        """跑片段自己的那个顶层 operation, 并把它当作一帧压进脚本栈。

        为什么不能直接 `run_body`: 顶层 operation 本身可以就是取放脚本
        (`flow.robot_individual_pick.*` 这一族的 operation 正是 robot_individual_pick)。
        那条路不经过 inline_script, 于是脚本栈是空的, `_closing_on_payload` 判成"不在取料
        脚本里", 合爪就发了空爪紧闭 (1.0) 而不是夹持 (0.101) —— 爪子把瓶子捏穿。
        2026-08-05 实测到这一步: 复合流程 (collect_load) 里的同一个脚本是对的, 单独成片段
        的那一族是错的, 差别只在于"是不是被内联进来的"。

        Args:
            name: operation 名; document: 已加载的 operation 文档; bindings: 已求值的入参
        """
        declared = {str(item.get("name")) for item in (document.get("vars") or [])
                    if item.get("name")}
        self._apply_staging_plan_assumption(name, bindings, declared)
        seat = self._seat_for(name, bindings)
        # 与 inline_script 同一套双栈。只压脚本栈不压座位栈的后果(2026-08-06 实测):
        # 顶层 operation 本身就是取放脚本时(flow.robot_individual_pick/put.* 这一族),
        # emit_tool_action 从 _seat_stack 查不到落座, 载荷交接被静默跳过 —— 那 12 条片段
        # 爪子空手开合, 耗材原地不动。_closing_on_payload 的空爪/夹持判定走 _script_stack,
        # 行为不变。
        self._script_stack.append((name, seat))
        if seat is not None:
            self._seat_stack.append(seat)
        try:
            self.run_body(document.get("body") or [], bindings, 0)
        finally:
            if seat is not None:
                self._seat_stack.pop()
            self._script_stack.pop()

    def _seat_for(self, script_name: str, child_bindings: dict[str, Any]) -> tuple[str, str] | None:
        template = SEAT_TEMPLATES.get(script_name)
        if template is None:
            return None
        pattern, role = template
        kind = child_bindings.get("rack_id")
        fields = dict(child_bindings)
        fields["area"] = AREA_BY_KIND.get(str(kind), "")
        try:
            return pattern.format(**fields), role
        except KeyError as exc:
            raise CompileError(f"{script_name} 缺少解析座位所需的入参: {exc}") from exc

    # -- 动作翻译 ---------------------------------------------------------- #

    def emit_call(self, instruction: dict, bindings: dict[str, Any]) -> None:
        action = str(instruction.get("action") or "")

        # 入参**按需求值**, 不在入口一次性算完。
        # 理由不是省几次运算: 有些动作的入参引用的是运行期测量结果(如 feedlift.probe_stack
        # 的 z_prev 取自上一次探测赋给 p0 的 DICT), 而这些动作在片段里本就只占一个时间格、
        # 一个入参都不看。急着求值会让编译在"根本用不到的值"上硬失败 —— 实测
        # sampling_load 就因此编不出来。谁用谁求, 求不出来的才是真问题。
        def args_of() -> dict:
            return {
                key: evaluate_expression(value, bindings)
                for key, value in (instruction.get("args") or {}).items()
            }

        if action in STATION_AXIS_ACTIONS:
            axis_id, target_mm, label, speed = STATION_AXIS_ACTIONS[action]
            # 埋料且板正坐在被埋料仓里: 板锚点骑在滑车上, 让它随行降到托边上方
            # (那之前全程净空, 见 PLATE_BURY_RIDE_STOP_MM), 在并入板堆的物理时刻
            # 收走, 滑车再走完最后一段 —— 在下降起点就收走是当众消失(用户可见 bug)。
            riding = (self.plate and self._plate_shown
                      and self._plate_at == PLATE_BURY_SLOTS.get(action))
            current = self.axis_mm.get(axis_id)
            if (riding and current is not None
                    and current > PLATE_BURY_RIDE_STOP_MM
                    and target_mm < PLATE_BURY_RIDE_STOP_MM):
                self.emit_axis(axis_id, PLATE_BURY_RIDE_STOP_MM, label, speed_mm_s=speed)
                self._bury_plate_if_needed(action)
                self.emit_axis(axis_id, target_mm, f"{label}·滑车续降到底",
                               speed_mm_s=speed)
                return
            self._bury_plate_if_needed(action)
            self.emit_axis(axis_id, target_mm, label, speed_mm_s=speed)
            return
        # 刮取要**先于** SEARCH_AXIS 拦下: 流程精编译档按演示标称条带表现刀路与遮罩;
        # SEARCH_AXIS/UNRESOLVED 两表里的条目保留 —— 单动作/近似档(motionMap)仍靠它们
        # 出时间格与缺口说明, 删掉就断了那条链(motionMap.js 按表展开)。
        if action == "photoscrape.scrape":
            self.emit_scrape()
            return
        # 展开的润湿前沿: 挂在 capture_reference(执行段起点、三个展开族流程的必经点)上,
        # 而不是只挂 wait_level —— 后者在默认编译入参下结构性不可达(ref_result={} → 走
        # "参考失败→人工门"那一支, auto_drain 默认 false 时另一支也到不了它)。两处都拦,
        # _wet_emitted 保证只表现一次。必须先于 IGNORED_ACTIONS(capture_reference 在其中)
        # 与 STILL_ACTION_KINDS 拦下, 与 photoscrape.scrape 同款; 不求值入参(阈值引用
        # 运行期液位服务, 而润湿前沿的几何是显式演示假设, 一个入参都不用)。
        if action in ("develop.capture_reference", "develop.wait_level"):
            self.emit_wet()
            return
        if action in IGNORED_ACTIONS or action in SEARCH_AXIS_ACTIONS:
            if action in SEARCH_AXIS_ACTIONS:
                label, seconds = SEARCH_AXIS_ACTIONS[action]
                self.emit(label, seconds, {"wait": {}})
            return
        # 驻位液体(收集样品瓶): 泵与收集器托架看不出流体, 但**瓶里的液面看得见** ——
        # 正压排液把洗脱液经滤芯压进样品瓶, 那正是"收集"这个动作唯一可见的产出。
        # 织入顺序与 develop.rinse_fill 的"盖→泵→液"同款: 先试柱塞行程(COL 泵已有合成
        # 几何时有戏), 再发逐轮液面; 泵行程编出来了就把液面里的"泵吸排"占位拍省掉。
        # 求值兜底与 tankLiquid 分支同一条纪律: 入参是运行期量就退回时间格, 风险为零。
        if action in self.station_liquids:
            station_args: dict | None
            try:
                station_args = args_of()
            except CompileError as exc:
                station_args = None
                self.flow_notes.append(f"{action} 的入参是运行期量({exc}), 未表现液面")
            if station_args is not None:
                pump_shown = (action in (self.pump_syringe.get("actions") or {})
                              and self.emit_pump_syringe(action, station_args))
                if self.emit_station_liquid(action, station_args, pump_shown=pump_shown):
                    return
                if pump_shown:
                    return
            label, seconds = FLUID_TIME_ACTIONS.get(action, (f"{action}(泵与阀)", 5.0))
            self.emit(label, seconds, {"wait": {}})
            return
        # 会动缸内液面的那几条从这里放行, 落到下面 args_of() 之后的 emit_tank_liquid;
        # 其余(develop.clean_line / sampling.rinse_mix)行为不变。collect.collect 已被上面
        # 的驻位液体分支拦下(manifest 没有 liquids 段时仍落回本分支的时间格)。
        # clean_line 只洗管路、不动缸内液体, 它本来就**刻意不在** tankLiquid.actions 里。
        if action in FLUID_TIME_ACTIONS and action not in (self.tank_liquid.get("actions") or {}):
            # 涉泵的先试柱塞行程(collect.collect / develop.clean_line / sampling.rinse_mix):
            # 行程步自带真实时长语义, 编出来了时间格就多余。求值兜底与液面分支同一条纪律 ——
            # 入参是运行期量时如实退回时间格, 绝不让整条流程编不出来。
            if action in (self.pump_syringe.get("actions") or {}):
                pump_args: dict | None
                try:
                    pump_args = args_of()
                except CompileError as exc:
                    pump_args = None
                    self.flow_notes.append(f"{action} 的入参是运行期量({exc}), 未表现泵行程")
                if pump_args is not None and self.emit_pump_syringe(action, pump_args):
                    return
            label, seconds = FLUID_TIME_ACTIONS[action]
            self.emit(label, seconds, {"wait": {}})
            return
        # 展缸注/排液: 泵与阀本体没有几何, 但**缸里的液面是看得见的**, 那正是要演的。
        #
        # 为什么在这里自带一次求值, 而不是挪到下面那个共用的 `args = args_of()` 之后:
        # 那一句刻意排在所有只读动作之后(见它上方的注释 —— 有些动作的入参引用运行期结果,
        # 急着求值会让整条流程编不出来, sampling_load 就这么栽过)。把液面动作挪下去,
        # 等于给它们**新增**一条失败路径: 入参写成运行期表达式的流程会从"编译成功"变成
        # "整条降级为近似"。自带一次带兜底的求值, 求不出来就退回原先的时间格, 风险为零。
        #
        # develop.rinse_fill 不在这里 —— 它同时要关盖, 归 TANK_LID_ACTIONS 那条分支处理
        # (两件事叠加), 而那条分支本来就在 args_of() 之后, 风险轮廓不变。
        if action in (self.tank_liquid.get("actions") or {}) and action not in TANK_LID_ACTIONS:
            liquid_args: dict | None
            try:
                liquid_args = args_of()
            except CompileError as exc:
                liquid_args = None
                self.flow_notes.append(f"{action} 的入参是运行期量({exc}), 未表现液面")
            # 泵行程与缸液面**叠加**而不是二选一, 与 TANK_LID 分支"盖+液"同款; 注液则更进
            # 一步 —— 打出去的那一趟与缸里涨的那一截同 at 同 dur(见 _tank_fill_pourer)。
            # 泵解不出/是排液/逐趟一趟都没涨成时, 退回 emit_tank_liquid 的整段斜坡。
            pour = finish = None
            if liquid_args is not None:
                pour, finish = self._tank_fill_pourer(action, liquid_args)
                self.emit_pump_syringe(action, liquid_args, on_dispense=pour)
            if finish is not None and finish():
                return
            if liquid_args is not None and self.emit_tank_liquid(action, liquid_args):
                return
            label, seconds = FLUID_TIME_ACTIONS.get(action, (f"{action}(泵与阀)", 5.0))
            self.emit(f"{label}(缸号/体积未解出, 未表现液面)", seconds, {"wait": {}})
            return
        if action == "robot.home":
            # 真机是"从点位注册表取 role=home 的点做 move_j", 不是控制器内建 Home
            self.emit_move("robot-main.home", "move_j", {})
            return
        if action == "vision.capture_plate_offset":
            self.emit_vision_capture()
            return
        if action == "photoscrape.capture":
            self.emit("刮板台·相机曝光", VISION_SHUTTER_S, {"wait": {}})
            return
        # 只读类动作(host/vision/camera)在这里就返回, **必须赶在 args_of() 之前**:
        # 它们的入参常常引用运行期结果(如 photoscrape.analyze 的 after_path 取自上一步
        # 拍照返回的 DICT), 求值一定失败。为一个根本不驱动机构的动作而让整条流程编不出来,
        # 是纯粹的损失 —— 上面两条是本类里唯二有可见表现的(补光灯、快门), 已先行处理。
        if self.action_kinds.get(action) in STILL_ACTION_KINDS:
            return
        args = args_of()
        if action == "robot.require_anchor":
            self.apply_anchor(str(args.get("point_id") or ""))
            return
        if action in ("rail.ensure", "rail.move"):
            self.emit_rail(int(args.get("Rail_Target_Position")))
            return
        if action == "robot.move_to_point":
            self.emit_move(str(args.get("point_id_or_robot_name")), str(args.get("motion")), args)
            return
        if action == "robot.tool_action":
            self.emit_tool_action(str(args.get("action") or ""))
            return
        if action == "robot.dwell":
            self.emit("等待", float(args.get("duration_ms", 0)) / 1000.0, {"wait": {}})
            return
        # 条带点样先于 SEQUENCE 拦下: 轴步仍照 SEQUENCE_ACTIONS 那张前后端共用表逐步发
        # (emit_spot 内部照表执行), 只在扫线步上并行叠一条色带渐现通道 + 落盘 spotRegions。
        # 泵段照旧叠加(轴先泵后, 与下面 SEQUENCE 分支同款)。
        if action == "sampling.spot_band_layer":
            self.emit_spot(args)
            self.emit_pump_syringe(action, args)
            return
        if action in SEQUENCE_ACTIONS:
            self.emit_sequence(action, SEQUENCE_ACTIONS[action], args)
            # 轴先泵后(sampling.aspirate: 5Z 下探进孔之后柱塞才回抽; collect.init: 气缸
            # 复位后柱塞归零) —— 泵段是 SEQUENCE 声明之外的**叠加**, 不进那张前后端共用表:
            # 表只描述轴/气缸, 泵相位的真源在 manifest.pumpSyringe.actions。
            self.emit_pump_syringe(action, args)
            return
        if action in PARAM_AXIS_ACTIONS:
            axis_id, field, label, speed = PARAM_AXIS_ACTIONS[action]
            target_mm = args.get(field)
            if target_mm is None:
                raise CompileError(f"{action} 缺入参 {field}, 无法定出 {axis_id} 目标")
            self.emit_axis(axis_id, float(target_mm), f"{label}→{float(target_mm):g}mm",
                           speed_mm_s=speed)
            return
        if action in TANK_LID_ACTIONS:
            tank = int(args.get("target_tank") or 0)
            if not 1 <= tank <= 8:
                raise CompileError(f"{action} 的 target_tank 越界: {tank}")
            linkage = tank_lid_linkage(tank)
            value = TANK_LID_ACTIONS[action]
            self.emit(
                f"{tank}号缸{'开盖' if value < 0.5 else '关盖'}",
                1.2,
                {"linkage": {"id": linkage, "to": value}},
                ease="inout",
            )
            # develop.rinse_fill 既关盖又注液, 两件事**叠加**而不是二选一(它同时在
            # TANK_LID_ACTIONS 与 tankLiquid.actions 两张表里)。develop.init 只在前者,
            # emit_tank_liquid 查不到表直接返回 False。
            # 泵行程夹在盖与液面之间(先抽后注), 同样是叠加: develop.init 归零柱塞,
            # rinse_fill 抽/排一轮; 泵表查不到或缸号解不出时 emit_pump_syringe 自己返回 False。
            #
            # 注液不再排在泵段之后单发一条整段斜坡, 而是**每趟 dispense 涨一截**(见
            # _tank_fill_pourer 的头注); 逐趟一趟都没涨成才退回 emit_tank_liquid。
            pour, finish = self._tank_fill_pourer(action, args)
            self.emit_pump_syringe(action, args, on_dispense=pour)
            if finish is None or not finish():
                self.emit_tank_liquid(action, args)
            return
        if action in CYLINDER_ACTIONS:
            mechanism, field = CYLINDER_ACTIONS[action]
            self.emit_cylinder(action, mechanism, 1.0 if bool(args.get(field)) else 0.0)
            return
        if action in CYLINDER_ACTIONS_FIXED:
            mechanism, value = CYLINDER_ACTIONS_FIXED[action]
            self.emit_cylinder(action, mechanism, value)
            return
        raise CompileError(f"未知动作: {action}(要么补进映射表, 要么补进 IGNORED_ACTIONS)")

    def emit_sequence(self, action: str, steps: tuple[dict, ...], args: dict) -> None:
        """把 SEQUENCE_ACTIONS 的一条声明展开成动画步。

        表是**前后端共用**的(经 motion_map_document 导出给 actionSim.js), 所以这里只准
        照表执行, 不准再加分支 —— 一旦这里多做一步而表里没写, 演示页与片段就又对不上了,
        而那正是本函数替换掉的那批内联 if 分支留下的病。

        Args:
            action: 动作名(只用于报错定位)
            steps: 步骤声明序列
            args: 已求值的动作入参

        Raises:
            CompileError: 步骤形态不认识, 或 point 步的入参/点位取不到
        """
        for step in steps:
            kind = step["kind"]
            if kind == "axis":
                self.emit_axis(step["axis"], float(step["toMm"]), step["label"],
                               speed_mm_s=float(step["speedMmS"]))
            elif kind == "point":
                key = step.get("point") or args.get(step.get("arg") or "")
                if not key:
                    raise CompileError(f"{action} 缺 point_ref 入参 {step.get('arg')}")
                if step.get("member"):
                    key = f"{key}.{step['member']}"
                if str(key) not in self.servo_points:
                    raise CompileError(f"{action} 引用的示教点不在点表里: {key}")
                self.emit_axis(step["axis"], self.servo_points[str(key)], step["label"],
                               speed_mm_s=float(step["speedMmS"]))
            elif kind == "well":
                # 孔位是仿射算出来的, 没标定就**不发这一步** —— 编一个孔位比不动更糟
                if self.demo_well_mm is None:
                    self.emit(f"{step['label']}(孔板未标定, 未表现)", 0.4, {"wait": {}})
                    continue
                x_mm, y_mm = self.demo_well_mm
                self.emit_axis("axis_4x", x_mm, f"{step['label']}·4X", speed_mm_s=float(step["speedMmS"]))
                self.emit_axis("axis_3y", y_mm, f"{step['label']}·3Y", speed_mm_s=float(step["speedMmS"]))
            elif kind in ("actuator", "linkage"):
                # 通道以 manifest 为准, 而不是照抄表里写的 kind ——
                # 表是人手写的, 写错了(col_clamp 那种 linkage 被写成 actuator)运行期只会
                # 静默不动。顺带让 data-only 机构在这条路上也被记下来, 与 emit_cylinder 一致。
                self.emit(step["label"], 0.5,
                          {self._mechanism_channel_for_emit(step["id"]):
                           {"id": step["id"], "to": float(step["value"])}}, ease="inout")
            else:
                raise CompileError(f"{action} 的步骤形态不认识: {kind}")

    def emit_rail(self, slot: int) -> None:
        self.emit_axis("axis_11y", float(self.rail_slots[slot]), f"地轨到位{slot}", speed_mm_s=200.0)

    def emit_axis(self, axis_id: str, target_mm: float, label: str,
                  *, speed_mm_s: float = 100.0, min_s: float = 0.4, max_s: float = 6.0,
                  ease: str = "inout") -> float:
        """把任意直线轴驱到某个毫米值, 并记住它现在停在哪。

        "已在位就不发步"这条对地轨之外的轴同样要紧: 工位轴常被连着调用两次
        (如 photoscrape.init 与 cam_x335 都写 9X=335), 每次都发一步会在时间轴上
        堆出一串零位移的假动作。

        时长按位移线性折算 —— 这是**观感节拍**不是物理量, 真机速度由 PLC 的
        jog_vel/vel_max 定, 片段不冒充它。

        Args:
            axis_id: 轴 id(须在 manifest.axes 里且 rigged, 否则前端静默忽略)
            target_mm: 目标毫米值(轴的控制器口径, 不是模型位移)
            label: 步骤标签
            speed_mm_s: 折算时长用的标称速度
            ease: 缓动。伺服观感默认 inout; 匀速工艺段(刮取冲程/收集扫掠)传 linear
        Returns:
            实际发出的步时长(秒, 与落盘值同精度)。零位移跳步返回 0.0 —— 要与本步
            并行的步(如刮取遮罩)**必须**用这个返回值对齐: min_s/max_s 钳制会让
            "自己按位移÷速度再算一遍"的时长与实际步长差出几倍(收集扫掠 160mm 被
            max_s 钳到 6s, 不取返回值 clear 前沿会跑得比桶快一倍)。
        """
        current = self.axis_mm.get(axis_id)
        if axis_id == "axis_11y":
            # 显式驱动即钉住 —— 零位移跳步也算表过态(rail.move 到位 = 编排定了站位),
            # 之后再遇到别的站位示教的 move_l 点就该硬失败而不是被收养改写(_ensure_point_rail)
            self._rail_pinned = True
        if current is not None and abs(target_mm - current) < 1e-6:
            return 0.0
        travel = abs(target_mm - current) if current is not None else abs(target_mm)
        duration = round(max(min_s, min(max_s, travel / max(speed_mm_s, 1e-6))), 3)
        self.emit(label, duration, {"axis": {"id": axis_id, "to_mm": target_mm}}, ease=ease)
        self.axis_mm[axis_id] = target_mm
        if axis_id == "axis_11y":
            self.current_rail_mm = target_mm
        return duration

    def emit_vision_capture(self) -> None:
        """视觉纠偏(P86)的一次补光拍照 —— 按真机时序摆灯的关键帧。

        真机(controller/pallas_vision_client.py::_run_with_light):
            开机器人 DO7 补光 → 等 light_settle_ms(app.yaml, 现役 1000ms) → 触发拍照
            → finally 关灯
        所以片段是四步: 渐亮 → 稳态(settle 全长) → 快照瞬间微过曝 → 熄灭。
        **不做成一帧爆闪**: 真机补光是 1s 量级的稳态过程, 单帧闪既不像也看不清。

        注意一次放板会走到这里 2~3 次(robot_suction_put.yaml 里 P86 出现三处:
        测 Rz、纠偏后测 dx/dy、XY 纠偏预览), 逐次都会完整闪一遍 —— 这是对的, 真机就是这样。
        """
        light = {"light": {"id": VISION_LIGHT_ID, "to": VISION_LIGHT_HOLD}}
        self.emit("视觉补光·开灯", VISION_LIGHT_RISE_S, light, ease="out")
        # 稳定期: 灯保持稳态(同值关键帧), 时长就是 light_settle_ms
        self.emit("视觉补光·稳定", self.vision_capture_s, dict(light), ease="linear")
        self.emit("视觉纠偏·曝光",  VISION_SHUTTER_S,
                  {"light": {"id": VISION_LIGHT_ID, "to": VISION_LIGHT_FLASH}}, ease="out")
        self.emit("视觉补光·熄灭", VISION_LIGHT_FALL_S,
                  {"light": {"id": VISION_LIGHT_ID, "to": 0.0}}, ease="inout")

    def emit_scrape(self) -> None:
        """photoscrape.scrape 的流程精编译档展开 —— 按演示标称条带演"刮松 → 收集"两段.

        真机 A40 是"置 CNC 启动等完成", 路径由 PLC SoftMotion 按 g_* 数组插补, 数组随
        每次视觉结果变, 编译期拿不到**那一条**路径(SEARCH_AXIS_ACTIONS 老注释, 单动作/
        近似档仍照它出时间格)。本方法演的是**同一套标定下的标称条带**: 机床原点/面高/
        切深/进给/桶偏移全部实读 app.yaml gcode 段(load_gcode_calib), 只有条带 bbox 与
        列数是显式标称值(SCRAPE_DEMO_*), 边界逐条记 flowNotes —— 与 emit_vision_capture
        "按真机时序摆灯"同一族: 把一条编不出来的动作展开成有出处的可见时序。

        序列对齐 controller/cnc_path.py 的路径结构, **逐刀展开**(2026-08-06):
          主轴启动 → 对每一刀 k=1..N:
            对位(8Y 条带下缘 / 9X 第 1 列) → 10Z 下刀到 pass_z_list[k]
            → 逐列往复(9X 步进 + 8Y 冲程, **板动刀不动**; loosen 遮罩与冲程同 at 同 dur
              并行, 前沿随刀的列位推进)
            → 9X 让位 −bottle_x_offset(粉桶在刀 +X 侧, 让位后桶口对到条带上)
            → 8Y 对条带中线 → −X 收集扫掠(clear 遮罩并行, "残粉 −X 回走"见 cnc_path.py
              头注释), 同时 pass 相位跳到 k —— 遮罩据此把已收段落到第 k 层深度
          → 末刀抬刀 → 主轴停 → 9X 回停放位(STATION_AXIS_HOME, 衔接其后 scrape_finish)。

        两处 2026-08-06 的订正(用户目检):
        · **不再拍平 pass 循环**。旧实现只演第 1 刀就把粉"按收尽表现"(一刀见玻璃),
          与真机 num_passes=2 / 每刀 total_depth/N 的分层工艺不符。现在逐刀出刀路,
          `pass` 相位逐刀推进, **只有最后一刀才露玻璃**。旧注释担心的"loosen 重新从 0 爬
          会让条带长回硅胶"在分层模型下不成立: 第 2 刀重新 loosen 的是**第 1 刀留下的
          残余层**, 不是已露的玻璃。
        · **收集段不再升降 10Z**。粉桶已改挂 axis_9x(见 rig_map 的 ps_rotate 头注释),
          桶口高度由结构固定, "降桶/抬桶"两步没有了对应几何; 且真机整条路径跑在同一个
          g_pass_z 上(plc_nodes.yaml 的 CNC 节点表注释), 收集段刀本来就不抬。
        """
        if self._scrape_emitted:
            # 同一条流程里 photoscrape.scrape 再次出现(不是 pass 循环 —— 那个已在本方法
            # 内部逐刀展开)。刀路不重复演, 只出一个时间格。
            label, seconds = SEARCH_AXIS_ACTIONS["photoscrape.scrape"]
            self.emit(f"{label}·再次", seconds, {"wait": {}})
            self.flow_notes.append("photoscrape.scrape 在本流程里再次出现: 只演时间格, 不重复刀路")
            return
        self._scrape_emitted = True

        calib = load_gcode_calib(self.control_root)
        x0, y0, x1, y1 = SCRAPE_DEMO_BAND_CM

        def to_x(cm: float) -> float:
            # 板 cm → 机床 mm, 逐字对齐 cnc_path._to_machine(9X/8Y 的 zero_offset 正是
            # 按同一对原点反解进 rig_map 的, 所以机床 mm 就是轴的控制器口径)
            return round(calib["origin_x_mm"] - cm * 10.0 if calib["flip_x"]
                         else calib["origin_x_mm"] + cm * 10.0, 3)

        def to_y(cm: float) -> float:
            return round(calib["origin_y_mm"] - cm * 10.0 if calib["flip_y"]
                         else calib["origin_y_mm"] + cm * 10.0, 3)

        columns = max(1, int(SCRAPE_DEMO_COLUMNS))
        col_w_cm = (x1 - x0) / columns
        feed_mm_s = max(1.0, calib["feed_rate_mm_min"] / 60.0)
        passes = max(1, int(calib["num_passes"]))
        depth_per_pass = calib["total_depth_mm"] / passes
        # 与 controller/cnc_path.py:1031-1039 同一式: pass_z[k] = 面 + k×总深/N
        pass_z_list = [round(calib["surface_z_mm"] + k * depth_per_pass, 3)
                       for k in range(1, passes + 1)]
        # 桶在刀 +X 侧 bottle_x_offset_mm(collector_x_positive=false 时在 −X 侧, 让位取反)
        offset = calib["bottle_x_offset_mm"] * (1.0 if calib["collector_x_positive"] else -1.0)
        # 本次刮取一共能吸进桶里多少粉(mm³) = 有效条带面积 × 总切深 × 松散系数。
        # 三个因子的出处各不相同, 都不是拍脑袋:
        #   面积 —— 演示标称带 × SCRAPE_DEMO_POWDER_AREA_RATIO(真机走视觉 summary 轮廓)
        #   切深 —— app.yaml gcode.scrape.total_depth_mm(与 pass_z 同一个标定)
        #   松散 —— app.yaml gcode.scrape.bulk_factor(粉刮下来是松散的, 体积大于实体层)
        # 与后端账本 (ScrapeArrays.scrape_volume_mm3) 是同一条式子, 口径必须一致 ——
        # 漂了的表现是"演示里桶装了一半、实况页桶快满了", 没有任何指标会报警。
        band_area_mm2 = ((x1 - x0) * 10.0) * ((y1 - y0) * 10.0) * SCRAPE_DEMO_POWDER_AREA_RATIO
        powder_total_mm3 = demo_powder_total_mm3(calib)

        # 主轴先转起来再下刀(真机 A40 置 CNC 启动即带主轴; 刀不转就扎进板里不像话)
        self.emit("刮取·主轴启动(Ø%g 铣刀)" % calib["cutter_diameter_mm"], 0.4,
                  {"spindle": {"id": SCRAPE_SPINDLE_ID, "on": True}})

        for index, pass_z in enumerate(pass_z_list, start=1):
            tag = f"第{index}/{passes}刀"
            # 每刀开头回到条带起点。第 2 刀起同时把两条前沿重置为 0(step 缓动, 瞬时):
            # 它们是"本刀的推进进度", 不是累计量; 累计深度由 pass 相位单独承载。
            reposition_at = self._timeline_end_s()
            self.emit_axis("axis_8y", to_y(y0), f"刮取·板对位条带下缘(8Y) {tag}", speed_mm_s=120.0)
            self.emit_axis("axis_9x", to_x(x0 + col_w_cm / 2),
                           f"刮取·9X 对位第1列 {tag}", speed_mm_s=120.0)
            if index > 1:
                for phase in ("loosen", "clear"):
                    self.emit(f"刮取·{phase} 前沿归零 {tag}", 0.001,
                              {"scrape": {"id": PLATE_CLIP_ID, "phase": phase, "to": 0.0}},
                              ease="step", at=reposition_at)
            # 下刀慢进(与 PARAM_AXIS 对位检查内环 10Z 同速 5mm/s), 抬刀快回。
            self.emit_axis("axis_10z", pass_z,
                           f"刮取·下刀(面{calib['surface_z_mm']:g} + 累计切深"
                           f"{round(index * depth_per_pass, 3):g}mm) {tag}",
                           speed_mm_s=5.0)

            # 逐列往复: 8Y 冲程按真机进给折算时长(linear 匀速工艺段), loosen 遮罩与冲程
            # 同 at 同 dur 并行 —— 前沿位置与刀的 9X 列位逐帧对得上(验收脚本按此反投影)。
            for column in range(1, columns + 1):
                self.emit_axis("axis_9x", to_x(x0 + (column - 0.5) * col_w_cm),
                               f"刮取·9X 步进第{column}/{columns}列 {tag}",
                               speed_mm_s=80.0, min_s=0.25)
                start = self._timeline_end_s()
                stroke_s = self.emit_axis(
                    "axis_8y", to_y(y1 if column % 2 else y0),
                    f"刮取·第{column}列冲程({'↑' if column % 2 else '↓'}) {tag}",
                    speed_mm_s=feed_mm_s, ease="linear")
                if stroke_s > 0:
                    self.emit(f"刮取·硅胶刮松 {column}/{columns} {tag}", stroke_s,
                              {"scrape": {"id": PLATE_CLIP_ID, "phase": "loosen",
                                          "to": round(column / columns, 4)}},
                              ease="linear", at=start)

            # 收集段: 刀留在本刀切深上(真机同一个 g_pass_z 跑完刮+收), 只走 9X/8Y。
            self.emit_axis("axis_9x", round(to_x(x1) - offset, 3),
                           f"收集·9X 让位{-offset:g}mm(粉桶对准条带末端) {tag}", speed_mm_s=120.0)
            self.emit_axis("axis_8y", to_y((y0 + y1) / 2),
                           f"收集·板对位条带中线(8Y) {tag}", speed_mm_s=120.0)
            start = self._timeline_end_s()
            sweep_s = self.emit_axis("axis_9x", round(to_x(x0) - offset, 3),
                                     f"收集·粉桶压过条带回扫(−X) {tag}",
                                     speed_mm_s=feed_mm_s, ease="linear")
            if sweep_s > 0:
                # pass 相位在回扫**开头**跳到 k: 遮罩把"已被前沿扫过"的一段落到第 k 层,
                # 未扫过的仍停在第 k−1 层。此刻 clear 刚归零, 没有任何一段在第 k 层, 安全。
                self.emit(f"收集·切到第{index}层 {tag}", sweep_s,
                          {"scrape": {"id": PLATE_CLIP_ID, "phase": "pass", "to": index}},
                          ease="step", at=start)
                done = "露玻璃" if index == passes else f"露第{index}层残余硅胶"
                self.emit(f"收集·硅胶粉收尽{done} {tag}", sweep_s,
                          {"scrape": {"id": PLATE_CLIP_ID, "phase": "clear", "to": 1.0}},
                          ease="linear", at=start)
                # 粉进桶: 与 clear 前沿**同一拍并行**, 板上少多少粉、桶里就多多少粉。
                # 挂在 −X 回扫上有 PLC 台账出处: A40 把真空阀与吸粉无刷电机同时置 TRUE
                # (整条刀路全程吸), A41(scrape_finish)才把两者清 FALSE —— 即"粉在每刀的
                # 回扫里进桶, A41 一粒不加"。
                # 逐刀累加到 k/passes: 分层刮取每刀带走总深的 1/N, 粉量同比例。
                # 翻料倒粉时粉滑到桶另一端**不发步** —— 那是姿态派生量(粉柱落点按当帧
                # 世界四元数算, 见 powderPivot), 免费搭车, 发步反而会与姿态打架。
                self.emit(f"收集·粉进桶(累计 {index}/{passes}) {tag}", sweep_s,
                          {"powder": {"id": SCRAPE_POWDER_ID, "phase": "fill",
                                      "to": round(powder_total_mm3 * index / passes, 1)}},
                          ease="linear", at=start)

        self.emit_axis("axis_10z", 0.0, "刮取·抬刀(全部刀次完成)", speed_mm_s=25.0)
        self.emit("刮取·主轴停转", 0.4, {"spindle": {"id": SCRAPE_SPINDLE_ID, "on": False}})
        park_mm, _park_why = STATION_AXIS_HOME["axis_9x"]
        self.emit_axis("axis_9x", park_mm, "刮取·9X 回停放位", speed_mm_s=150.0)

        self.scrape_regions[PLATE_CLIP_ID] = {
            "frame": "plate-cm",
            "plateSizeCm": [SCRAPE_DEMO_PLATE_CM, SCRAPE_DEMO_PLATE_CM],
            "bandCm": list(SCRAPE_DEMO_BAND_CM),
            "loosen": {"axis": "x", "dir": 1},
            "clear": {"axis": "x", "dir": -1},
            # 分层刮取: 总层数与单层厚度。前端据此把 pass 相位换算成残余硅胶厚度
            # (残余 = (passes − pass) / passes × 硅胶层厚), 只有 pass == passes 才露玻璃。
            "passes": passes,
            "depthPerPassMm": round(depth_per_pass, 4),
            "totalDepthMm": round(calib["total_depth_mm"], 4),
        }
        step_mm = calib["cutter_diameter_mm"] * (1.0 - calib["overlap_ratio"])
        real_columns = max(1, round((x1 - x0) * 10.0 / max(step_mm, 1e-6)))
        self.flow_notes.append(
            f"photoscrape.scrape 按演示标称条带表现: 板cm bbox {SCRAPE_DEMO_BAND_CM}, "
            f"{columns} 列(真机按步距 {step_mm:g}mm ≈ {real_columns} 列); "
            f"逐刀展开 {passes} 刀 × 每刀切深 {depth_per_pass:g}mm(总深 "
            f"{calib['total_depth_mm']:g}mm), 末刀才露玻璃; 收集按条带中线一趟 −X 回扫 —— "
            "真实刀路由 PLC SoftMotion 按每次视觉 summary 插补, 真值用「实机对照」")
        self.flow_notes.append(
            f"粉桶进粉按演示条带折算: 有效面积 {band_area_mm2:g}mm²"
            f"(标称带 ×{SCRAPE_DEMO_POWDER_AREA_RATIO:g}, 对齐真机参考带 480mm²) × 总深 "
            f"{calib['total_depth_mm']:g}mm × 松散系数 {calib['bulk_factor']:g} = "
            f"{powder_total_mm3:g}mm³, 逐刀累加; 真机粉量由视觉轮廓面积逐次给出")

    def emit_spot(self, args: dict) -> None:
        """条带点样(sampling.spot_band_layer): 轴步照共用表发, 扫线步叠色带渐现通道。

        轴步严格照 SEQUENCE_ACTIONS["sampling.spot_band_layer"] 那张前后端共用表逐步
        解点发射(与 emit_sequence 的 point 分支同一段解析逻辑) —— 表仍是唯一的路线真源,
        本方法只additive 两件事: ①扫线步改 linear(匀速工艺段)并用 emit_axis **返回值**
        对齐并行的色带通道(max_s 钳制下自己再算一遍时长必错, 见 emit_axis 的返回值注释);
        ②按 SPOT_BAND_CALIB 把实读的示教毫米换算成板 cm 条带, 落盘 spotRegions。

        润洗轮会再次点同一条带: 轴步照发(6X 往返是真实运动), 色带通道保持已满不再发 ——
        通道值是 t 的纯函数, 1→0→1 会演出"色带消失再重现"。

        Raises:
            CompileError: point 步的入参/点位取不到(与 emit_sequence 同一失败面)
        """
        steps = SEQUENCE_ACTIONS["sampling.spot_band_layer"]
        values: dict[str, float] = {}
        for step in steps:
            key = step.get("point") or args.get(step.get("arg") or "")
            if not key:
                raise CompileError(f"sampling.spot_band_layer 缺 point_ref 入参 {step.get('arg')}")
            if step.get("member"):
                key = f"{key}.{step['member']}"
            if str(key) not in self.servo_points:
                raise CompileError(f"sampling.spot_band_layer 引用的示教点不在点表里: {key}")
            member = str(step.get("member") or key)
            values[member] = self.servo_points[str(key)]
            if member == "x_end":
                # 扫线步: 匀速工艺段(供液斜坡), 色带前沿与喷头逐帧同步
                start = self._timeline_end_s()
                sweep_s = self.emit_axis(step["axis"], values[member], step["label"],
                                         speed_mm_s=float(step["speedMmS"]), ease="linear")
                if sweep_s > 0 and not self._spot_emitted:
                    self._spot_emitted = True
                    self.emit("点样·色带渐现", sweep_s,
                              {"spot": {"id": PLATE_CLIP_ID, "band": 1, "to": 1.0}},
                              ease="linear", at=start)
                    self._register_spot_region(values)
                    travel_mm = abs(values.get("x_end", 0.0) - values.get("x_start", 0.0))
                    true_s = travel_mm / max(float(step["speedMmS"]), 1e-6)
                    if true_s > sweep_s + 0.5:
                        self.flow_notes.append(
                            f"点样扫线 {travel_mm:g}mm@{step['speedMmS']:g}mm/s 真值约 "
                            f"{true_s:.0f}s, 片段按节拍钳到 {sweep_s:g}s(emit_axis max_s); "
                            "且真机每程后往返吹干、蛇形扫最多60程, 片段只演单程")
                # 润洗轮(_spot_emitted 已置位): 色带已满, 只演轴运动
            else:
                self.emit_axis(step["axis"], values[member], step["label"],
                               speed_mm_s=float(step["speedMmS"]))

    def _register_spot_region(self, values: dict[str, float]) -> None:
        """按 SPOT_BAND_CALIB 把示教毫米换算成板 cm 条带, 落盘 spotRegions。"""
        calib = SPOT_BAND_CALIB
        x0_cm = (values["x_start"] - calib["x_origin_mm"]) / 10.0 * calib["x_dir"]
        x1_cm = (values["x_end"] - calib["x_origin_mm"]) / 10.0 * calib["x_dir"]
        y_cm = (values["y_height"] - calib["y_origin_mm"]) / 10.0 * calib["y_dir"]
        self.spot_regions[PLATE_CLIP_ID] = {
            "frame": "plate-cm",
            "plateSizeCm": [SCRAPE_DEMO_PLATE_CM, SCRAPE_DEMO_PLATE_CM],
            "bands": [{
                "bandCm": [round(min(x0_cm, x1_cm), 3), round(y_cm - SPOT_BAND_HALF_CM, 3),
                           round(max(x0_cm, x1_cm), 3), round(y_cm + SPOT_BAND_HALF_CM, 3)],
                # 渐现方向 = 扫线方向(x_start → x_end)
                "fill": {"axis": "x", "dir": 1 if x1_cm >= x0_cm else -1},
            }],
            # 前端 machineDirsWorld 的轴 id 与标定方向 —— 与本表同源, 不在前端猜
            "machine": {"xAxis": "axis_6x", "yAxis": "axis_7y",
                        "xDir": calib["x_dir"], "yDir": calib["y_dir"]},
        }
        self.flow_notes.append(
            f"点样色带按 SPOT_BAND_CALIB 标称映射(板cm x {min(x0_cm, x1_cm):.1f}~"
            f"{max(x0_cm, x1_cm):.1f}, y {y_cm:.1f}±{SPOT_BAND_HALF_CM:g}); 端点毫米实读点表 "
            "spot_pose, 站位零点是演示标定常量(出处见该常量注释), 真值用实机对照")

    def emit_wet(self) -> None:
        """液位等待(develop.wait_level): 演板面润湿前沿由下向上爬升。

        真机这一步是几百到上千秒的等待(hard_cap 3600s), 可见的物理过程正是溶剂沿硅胶
        面爬升 —— 压缩成 WET_DEMO_RISE_S 的匀速上行, 真值记 flowNotes。前沿目标高度是
        显式演示假设(WET_FRONT_TARGET_CM), 展开中没有板面高度真值。
        排液(develop.drain)后前沿界线仍在 —— 干燥的板上溶剂前沿本就留一条可见界线,
        通道保持 1 不回退。
        """
        if not self.plate:
            # 无板片段(理论上 develop 流程不会走到; 防御) —— 只出时间格
            self.emit("展开·液位等待(无板, 未表现润湿)", 0.4, {"wait": {}})
            return
        if self._wet_emitted:
            self.emit("展开·液位等待(润湿已表现)", 0.4, {"wait": {}})
            return
        self._wet_emitted = True
        self.emit("展开·溶剂前沿上行(压缩演示)", WET_DEMO_RISE_S,
                  {"wet": {"id": PLATE_CLIP_ID, "to": 1.0}}, ease="linear")
        self.wet_regions[PLATE_CLIP_ID] = {
            "frame": "plate-cm",
            "plateSizeCm": [SCRAPE_DEMO_PLATE_CM, SCRAPE_DEMO_PLATE_CM],
            # 润湿区 = 板下沿(y=0, 点样线那条边, 浸在溶液槽里)到前沿目标高度
            "bandCm": [0.0, 0.0, SCRAPE_DEMO_PLATE_CM, WET_FRONT_TARGET_CM],
            "fill": {"axis": "y", "dir": 1},
            # 缸内板与机床轴不对齐, 前端走重力锚定(scrapeOverlay.gravityDirsWorld)
            "anchor": "gravity",
        }
        self.flow_notes.append(
            f"液位等待按润湿前沿表现: 0→{WET_FRONT_TARGET_CM:g}cm(板cm, 假设值出处见 "
            f"WET_FRONT_TARGET_CM)匀速 {WET_DEMO_RISE_S:g}s; 真机是液位闭环等待"
            "(hard_cap 3600s), 前沿高度那时由液位百分比与时间共同决定, 真值用实机对照")

    def _ensure_point_rail(self, point) -> None:
        """把 move_l 点位声明的地轨槽码兑现成看得见的账。

        点表槽码的语义是"到达本点时地轨应在的工位定位"(point_registry.RobotPoint.rail)。
        示教 pose 是机器人**基座系**的, 只有配上示教时的地轨站位才落在那个世界位置 ——
        拿 home 的 4 号位(500mm)去烤 3 号站(350mm)示教的点, 机械臂在世界系整体错开一段
        站距(实测 collector_return_put: 150mm 差投影到闭合轴 138.3mm, 被 100mm 护栏逮住;
        旧锚点修正一直在静默吸收这笔账)。

        与 preload_payload/apply_anchor 同一条纪律 —— 声明状态、如实呈现, 不编造也不隐瞒:
          未钉住 → **收养**该站位为片段起手态(真机跑单段前, 派发器已把地轨召回到位;
            这里把该运行期前提写进 t=0 的 home 声明, 不是中途瞬移);
          已钉住(显式 rail.move、先前收养、或载荷姿态账已用过当前值) → 补发一步**看得见
            的地轨召回**: 地轨是离散召回轴, 编排层(派发器/流程)持有它的运动权, 单段 YAML
            里不写 —— 典型是 collector_return_put 的 P1 prologue 内联 tool_ensure 把地轨
            表态在 4 号工具位(500), 而落点示教于 3 号(350): 真机在两步之间必有一次召回,
            片段把它画出来(此前是静默拿 500 烤 350 的示教点, 世界系整体错开一段站距,
            由锚点修正暗中吸收 —— 138.3mm 那笔账)。
        move_j 不参与: 关节复现与地轨无关(P45 这类过渡点在哪个站位都按同一组关节走)。
        """
        slot = getattr(point, "rail", None)
        if slot is None:
            return
        target = float(self.rail_slots[int(slot)])
        if abs(self.current_rail_mm - target) < 1e-6:
            self._rail_pinned = True
            return
        if self._rail_pinned:
            self.emit_rail(int(slot))
            return
        if abs(self._pick_rail - self.home_rail_mm) < 1e-6:
            # preload 在 body 之前, 其"取件姿态"诊断快照跟着 home 走
            self._pick_rail = target
        self.home_rail_mm = target
        self.current_rail_mm = target
        self.axis_mm["axis_11y"] = target
        self._rail_pinned = True

    def emit_move(self, point_id: str, motion: str, args: dict) -> None:
        point = self.registry.require_motion(point_id, motion)
        if motion == "move_l":
            self._ensure_point_rail(point)
        velocity = float(args.get("vel") or point.vel)
        index = len(self.steps)

        if motion == "move_j":
            if point.joint is None or max(abs(value) for value in point.joint) < 1e-9:
                raise CompileError(f"{point_id} 的 move_j 没有有效实测 joint")
            target = list(point.joint)
        elif motion == "move_l":
            # 端点优先用实测关节角(它是真值, 比数值反解准), **但必须先验证它与示教 pose 自洽**。
            #
            # 为什么要验: 点表里存在"pose 已迁移、joint 未刷新"的半新态 —— 吸附基准从
            # P64 统一到板中心 P65 时, 一次性迁移脚本只改了 pose 的 xy, joint 留在旧基准上
            # (见 docs/机器人吸附基准换算备忘 第 6 节, 那里明说收尾要走示教闭环 capture→commit
            # 才能"用真实反馈同时刷新 pose 与 joint")。展缸点 P11-P18 实测就差着整整一个
            # 基准差 |v|≈22mm。这种点上 pose 才是真机验证过的那个, joint 是旧的。
            #
            # 所以: 自洽就用 joint(省一次反解且更准), 不自洽就退回从 pose 反解, 并把差额记下来
            # —— 让"哪些点还没走示教闭环"变成可见的账, 而不是被 IK 静默抹平。
            trusted_joint = self._consistent_joint(point)
            path = sample_move_l(
                self.current_joints, point.pose, self.calibration, tool=point.tool,
                target_joint_deg=trusted_joint,
            )
            target = path[-1]
            self.trajectories[str(index)] = path
            actual = forward_kinematics(target, self.calibration, tool=point.tool)
            error_mm = math.sqrt(
                sum((actual[i, 3] * 1000.0 - point.pose[i]) ** 2 for i in range(3))
            )
            if error_mm > 1.0:
                raise CompileError(f"{point_id} move_l 终点 FK 误差 {error_mm:.3f}mm")
        else:
            raise CompileError(f"不支持的机器人运动: {motion}")

        delta = max(abs(a - b) for a, b in zip(self.current_joints, target))
        divisor = max(8.0, velocity) * (0.75 if motion == "move_j" else 0.5)
        duration = round(min(4.0, max(0.35, delta / divisor)), 3)
        self.emit(
            point.label or point.alias or point.point_id,
            duration,
            {"robot_point": {"id": point.point_id, "motion": motion}},
            ease="inout" if motion == "move_j" else "linear",
        )
        self.current_joints = target
        self._moved = True
        # 落点跟踪: **只有命中取放基准点才更新**。进近/退离/过渡点必须放行不更新,
        # 否则退刀路径会把刚认定的落点冲掉(与前端 PlateTransferTracker 同一条纪律)。
        slot = PLATE_POINT_SLOT.get(str(getattr(point, "robot_name", "") or ""))
        if slot is not None:
            self._plate_slot = slot

    def apply_anchor(self, point_id: str) -> None:
        """把 `robot.require_anchor` 当成**起手姿态的声明**来用, 而不是空操作。

        每个 robot_* 原子脚本的头注释都写着"进/出 require_anchor 为安全门" —— 它声明的是
        本段开始时机械臂必然在哪个点。编译期把它当空操作跳过, 后果不是少画一步, 而是
        **第一段 move_l 的起点错了**: 例如 robot_feed_lift_pick_exit 声明起于 P21(料仓里),
        跳过后编译器以为还在 Home, 于是要在 Home 与料仓之间拉一条 600mm 的笛卡尔直线 ——
        那条线真机从不走, 中途还解不出 IK(实测残差 1.5mm 卡在门禁上)。

        两种语义:
          片段还没发生任何运动 → **采纳**该点为起手姿态(这正是安全门要表达的意思);
          已经动过           → 当作**断言**核对, 对不上就是编排或编译出了问题, 硬失败。

        Args:
            point_id: 安全门声明的点

        Raises:
            CompileError: 已有姿态与声明的锚点不符
        """
        if not point_id:
            return
        try:
            point = self.registry.get(point_id)
        except Exception:  # pylint: disable=broad-except
            return  # 点表里没有的锚点(派生名/别名)不猜, 退回旧的"跳过"语义
        joint = getattr(point, "joint", None)
        if joint is None or len(joint) != 6 or max(abs(v) for v in joint) < 1e-9:
            return  # 没有实测关节角就不采纳 —— 绝不用一个编出来的姿态当起点
        if not self._moved:
            self.current_joints = list(joint)
            # 片段声明的 home 也要跟着改: 播放器在 t=0 摆的是 home 姿态, 只改编译期的
            # current_joints 会让"播放器从原点起手、第一段轨迹却从锚点起算", 差一整段。
            self.home_joints = list(joint)
            # 起手姿态刚刚落定(关节 = 安全门声明的锚点, 地轨 = 路线声明的站位), 此刻正是
            # 算"板相对吸盘"的唯一正确时机 —— 板还在源落点的 CAD 位姿上, 吸盘已贴上去。
            if self.plate and self.carry_in and not self._plate_shown:
                self._plate_shown = True
                # 这一支是精确的: 起手姿态就是取料点本身(安全门声明的), 地轨也已按
                # rail_slot 就位 —— 板此刻正贴在吸盘上, 保世界位姿换父即可, 零标定。
                self._register_seat_axis(self.carry_in)
                self.plate_intro = [
                    {"label": "板在位(起手)", "at": 0, "dur": 0,
                     "do": {"plate": {"id": PLATE_CLIP_ID, "at": self.carry_in}}},
                    {"label": "板挂上吸盘", "at": 0, "dur": 0,
                     "do": {"plate": {"id": PLATE_CLIP_ID, "carry": True,
                                      "from": self.carry_in}}},
                ]
                self._plate_slot = self.carry_in
                self._plate_at = None  # intro 末态: 板在吸盘上, 不坐任何落点
            return
        actual = forward_kinematics(self.current_joints, self.calibration, tool=point.tool)
        expected = forward_kinematics(list(joint), self.calibration, tool=point.tool)
        error_mm = float(np.linalg.norm((actual[:3, 3] - expected[:3, 3]) * 1000.0))
        if error_mm > ANCHOR_ASSERT_TOLERANCE_MM:
            raise CompileError(
                f"安全门 require_anchor({point_id}) 与编译期姿态不符: 相距 {error_mm:.1f}mm "
                "—— 要么编排里少了一段运动, 要么这个锚点写错了"
            )

    def _consistent_joint(self, point) -> list[float] | None:
        """实测关节角与示教 pose 自洽时返回它, 否则返回 None 并记一笔"待示教闭环"。

        判据是 FK(joint) 与 pose 的位置差 ≤ 1mm —— 同一个物理位姿的两种记法, 差到毫米级
        就说明其中一个过期了(典型是基准迁移只改了 pose)。

        @param point PointRegistry 的点
        @returns 可信的关节角, 或 None
        """
        joint = getattr(point, "joint", None)
        if joint is None or len(joint) != 6 or max(abs(v) for v in joint) < 1e-9:
            return None
        actual = forward_kinematics(list(joint), self.calibration, tool=point.tool)
        error_mm = math.sqrt(sum((actual[i, 3] * 1000.0 - point.pose[i]) ** 2 for i in range(3)))
        if error_mm <= 1.0:
            return list(joint)
        self.stale_joint_points.append({
            "point": point.point_id,
            "poseVsJointMm": round(error_mm, 3),
        })
        return None

    # -- 薄层板 ------------------------------------------------------------ #

    def _bury_plate_if_needed(self, action: str) -> None:
        """滑车带着板堆沉到托边之后, 把坐在仓里的那块板收走。

        为什么要收: `feedlift.unload_bury` / `feed_clear` 把滑车降到 0, 板锚点骑在滑车上,
        那块**独立画出来的**板要是画到底就扎进固定托边 —— 2026-08-05 逐三角形实测,
        托边开口比板四周各小 25mm, 板堆不被滑车顶着时就坐在它上面, 交叠 25.0mm。

        为什么不在下降**前**收(2026-08-07 订正): 扫掠数据(PLATE_BURY_RIDE_STOP_MM 的
        出处)证明 512mm 行程只有托边那最后一档有交叠, 其余全程净空 —— 板本该随滑车
        可见地沉进仓里, 在托边处被接住并入板堆。此前在下降前就 hide, 板在 512mm 高处
        凭空消失、滑车空降到底, 正是用户报的"最后 Z 轴下降时板消失"。调用方
        (emit_call 的 STATION_AXIS_ACTIONS 分支)现在先把轴降到 PLATE_BURY_RIDE_STOP_MM
        再调本函数, 收走点就落在并入板堆的物理时刻。

        为什么只收**坐在被埋料仓里**的板(_plate_at 守卫): 埋料动作与板的位置无关地
        乱收, 会把机器人手上的板也收掉 —— pf_s11_unload 开头的"测量清零"埋料就把
        持板中的板 hide 了, 板从吸盘上消失、落位那刻又冒出来。

        物理上此刻它已并入板堆, 不再是一块被追踪的板 —— 所以是"不该再画", 而不是
        "画了但要躲开"。板堆本身另由 material_state 的张数驱动(PlateFaceLayer.setMagazine),
        与这块个体板是两本账, 收走它不会让仓里少一张; 但演示页不走那条链、根本不画
        板堆, 所以并入点必须选在托边处 —— 选在下降起点就是当众消失。
        """
        if not self.plate or not self._plate_shown:
            return
        bury_slot = PLATE_BURY_SLOTS.get(action)
        if bury_slot is None or self._plate_at != bury_slot:
            return
        self.emit("板并入仓内板堆(不再单独画)", 0.0,
                  {"plate": {"id": PLATE_CLIP_ID, "hide": True}})
        self._plate_shown = False
        self._plate_slot = None
        self._plate_at = None

    def _register_seat_axis(self, slot: str) -> None:
        """把某落点的板托座工位轴声明成片段的起手状态(见 SEAT_AXES)。

        只在该轴**本片段还没被驱动过**时声明 —— 已经驱过就说明片段自己把状态交代清楚了,
        再按 SEAT_AXES 覆盖一遍反而会盖掉真实编排(如 flow.feedlift_load_cycle 是先
        1Z→0 再→512, 那个 0 是"埋料至光电消失", 不该被起手声明抹掉)。

        这不是编造运动: 机器人来取放时板本来就在那个高度等着, 声明的是**状态**不是位移。
        """
        entry = self.seat_axes.get(slot)
        if entry is None:
            return
        axis_id, value, _why = entry
        if value is None or axis_id in self.axis_mm:
            return
        self.home_axis_mm[axis_id] = float(value)
        self.axis_mm[axis_id] = float(value)

    def _check_plate_anchor(self, slot: str) -> None:
        """核对"取放点声称的落点"与"机械臂实际到达的位置"是否对得上。

        只做**相对**比较, 不声称能算出绝对的持板偏置(那条链还没验通)。判据是:
        同一个架内的几个缸, 法兰到各自锚点的偏置向量应当**完全一致**(同一副吸盘、
        同一个朝向、只是高度不同)。一致就说明配对是对的; 差一整个层距就说明两套编号
        对不上 —— 而这种错**不会有任何自动指标报警**, 板会安安静静地放进另一个缸。
        """
        anchor = self.plate_anchors.get(slot)
        if anchor is None or self.scene is None or self.posture is None:
            return
        # 板托座骑在工位轴上, 复核时必须把那些轴一起摆到位 —— 只摆机器人不摆托座, 量出来
        # 的是"CAD 建模位 vs 机器人真实位"那个假差(2026-08-05 之前记的 530mm 就是它)。
        axes_mm = {axis_id: value for axis_id, value in self.axis_mm.items()
                   if axis_id in {spec[0] for spec in SEAT_AXES.values()}}
        pose = {"joints_deg": self.current_joints, "rail_mm": self.current_rail_mm,
                "axes_mm": axes_mm}
        mount = self.posture.mount_world(**pose)[:3, 3]
        offset = mount - self.posture.node_world(anchor, **pose)[:3, 3]
        self.plate_anchor_checks.append({
            "slot": slot,
            "anchor": anchor,
            "seatAxesMm": {k: round(v, 3) for k, v in sorted(axes_mm.items())},
            "flangeToAnchorMm": [round(float(v) * 1000.0, 1) for v in offset],
        })


    def _plate_transfer(self, kind: str) -> dict:
        """吸/放动作对应的 `plate` 原语, 并在需要时补出起手式。

        Args:
            kind: 'on'(吸起) 或 'off'(放下)

        Returns:
            该步的 do 体

        Raises:
            CompileError: 吸/放之前没经过任何取放基准点(落点无从确定)
        """
        slot = self._plate_slot
        if slot is None:
            raise CompileError(
                f"吸盘{'吸气' if kind == 'on' else '放气'}之前没有经过任何取放基准点 —— "
                f"板从哪来/到哪去无从确定。要么编排少了基准点, 要么该点没进 PLATE_POINT_SLOT"
            )
        if not self._plate_shown:
            self._plate_shown = True
            if kind == "on":
                # 取板起手式: 板本来就在源落点上等着
                self.plate_intro = [{
                    "label": "板在位", "at": 0, "dur": 0,
                    "do": {"plate": {"id": PLATE_CLIP_ID, "at": slot}},
                }]
            else:
                # 放板片段(develop_load / photoscrape_plate_load 这类"机器人已持板进场"):
                # 起手就把板挂到吸盘上, 整段转运都画得出来。
                #
                # 2026-08-05 之前这里是 `hide: True`(落位那一刻才画), 原因是当时没有可信的
                # "板相对吸盘"局部位姿: 试过在编译期从示教点反算, 拿点样座与刮板台交叉验算
                # 差了 155mm。**那 155mm 不是反算链坏, 是这两站的板托座骑在没被驱动的 7Y/8Y
                # 上**(实测 99 + 35 = 134mm, 见 SEAT_AXES)。现在位姿改由 manifest 的
                # plateGrip 给 —— 直接量吸盘几何得来, 与站、与示教残差全都无关, 于是这条
                # 待办自然到期。
                self.plate_intro = [{
                    "label": "板(起手时已在机器人手上)", "at": 0, "dur": 0,
                    "do": {"plate": {"id": PLATE_CLIP_ID, "carry": True, "from": slot}},
                }]
        self._register_seat_axis(slot)
        self._check_plate_anchor(slot)
        if kind == "on":
            self._plate_at = None  # 吸起: 板离座上手
            # `from` 只用来定尺寸与硅胶朝向(板池是复用的) —— 见 PlateStage.carry
            return {"plate": {"id": PLATE_CLIP_ID, "carry": True, "from": slot}}
        self._plate_at = slot  # 放下: 板落座
        return {"plate": {"id": PLATE_CLIP_ID, "at": slot}}

    def _actuator_transition_s(self, actuator_id: str, fallback: float) -> float:
        """取某条 actuator 的标称行程时长(秒); manifest 里没有或非法则回退 fallback.

        真源是 rig_map 的 transitionS, 经 gen_twin_manifest 进 manifest —— 片段与实时
        孪生因此共用同一个数, 不会各写各的。
        """
        for item in (self.manifest.get("actuators") or []):
            if item.get("id") != actuator_id:
                continue
            value = item.get("transitionS")
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
            break
        return fallback

    def mechanism_home(self) -> tuple[dict[str, float], dict[str, float]]:
        """全部 rigged 机构的起手态, 写进片段的 home.actuators / home.linkages。

        枚举源是 manifest 的 actuators[] 与 linkages[] —— 那两张表**就是** rigged 集合。
        刻意不从 realtime.mechanisms 枚举: 那里还有几十条 rigged:false 的 data-only 条目
        (sta_powder_locator / col_bottle_locator 等), 给它们建通道等于建一堆永远写不进几何
        的空通道(前端 setActuator 查不到条目就返回 false), 还会让 home 的键集与 manifest
        的机构集对不上 —— 而"键集恰好相等"正是产物门禁判"home 漏机构"的判据。

        Returns:
            (actuators, linkages) 两张 {id: 起手值}

        Raises:
            CompileError: manifest 里有 rigged 机构没在 MECHANISM_HOME 里声明。宁可编不
                出来 —— 漏一条的表现是那个机构在 270 个片段里都停在 CAD 基位, 而画面
                看着完全正常(这正是 2026-08-06 之前 col_lift/col_clamp 的处境)。
        """
        actuators, linkages = mechanism_home_of(self.manifest)
        # 阶段起手态的按段覆盖(见 PhaseEntry.mechanisms / seed_entry_state): 键在播种时
        # 已经 _mechanism_channel 校验过, 两张表都不命中只可能是 manifest 与播种间漂移。
        for mechanism, value in self.home_mechanism_overrides.items():
            if mechanism in actuators:
                actuators[mechanism] = value
            elif mechanism in linkages:
                linkages[mechanism] = value
            else:
                raise CompileError(
                    f"起手态覆盖的机构 {mechanism} 不在 rigged 集合里 —— manifest 变了")
        return actuators, linkages

    def _mechanism_channel(self, mechanism: str) -> str:
        """机构 id -> 片段原语通道。与前端 demo/actionSim.js 的 mechanismOf 逐字同义。

        三态而不是两态, 因为有三种情形长得不一样但后果完全不同:
          actuator / linkage —— 有几何, 按各自的通道发;
          data-only          —— rigged:false, 只存在于 realtime.mechanisms(中转两个定位
                                气缸就是这样, 上位机有 DO 但三维没建几何)。仍按 actuator
                                发(前端静默忽略是既有纪律), 但要记下来;
          查无此 id          —— 表里打错了字, **硬失败**。
        今天这三种被一视同仁地静默忽略, 于是 CYLINDER_ACTIONS_FIXED 把 collect.clamp 映到
        col_clamp(那是个 **linkage**)之后, 8 步 / 5~7 个片段整段无效而零报错 ——
        收集流程的表现是"松开(走 SEQUENCE_ACTIONS 的 linkage, 生效)→ 夹紧(走这里, 不动)"。

        Args:
            mechanism: 机构 id
        Returns:
            "actuator" | "linkage" | "data-only"
        Raises:
            CompileError: 三张表里都没有这个 id
        """
        for item in self.manifest.get("actuators") or []:
            if item.get("id") == mechanism:
                return "actuator"
        for item in self.manifest.get("linkages") or []:
            if item.get("id") == mechanism:
                return "linkage"
        for item in ((self.manifest.get("realtime") or {}).get("mechanisms") or []):
            if item.get("id") == mechanism:
                return "data-only"
        raise CompileError(
            f"机构 {mechanism} 在 manifest 的 actuators/linkages/realtime.mechanisms 三张表里"
            " 都没有 —— 多半是 CYLINDER_ACTIONS* 或 SEQUENCE_ACTIONS 里打错了 id")

    def _mechanism_channel_for_emit(self, mechanism: str) -> str:
        """发一步机构动作时该用哪个原语通道; data-only 记账后按 actuator 发。

        没几何的机构照旧按 actuator 发(真机上它确实是一只气缸, 前端静默忽略是既有纪律),
        但要记进 compiled.dataOnlyMechanisms —— 让"没几何"与"打错 id"在产物里分得开。
        """
        channel = self._mechanism_channel(mechanism)
        if channel == "data-only":
            self.data_only_mechanisms.add(mechanism)
            return "actuator"
        return channel

    def emit_cylinder(self, action: str, mechanism: str, value: float) -> None:
        verb = "夹紧/伸出" if value >= 0.5 else "松开/缩回"
        channel = self._mechanism_channel_for_emit(mechanism)
        self.emit(f"{action} {verb}", 0.5, {channel: {"id": mechanism, "to": value}}, ease="inout")

    def _tank_id(self, tank: int) -> str | None:
        """缸号(1-8) -> manifest 里那条液面几何的 id; 没有液面几何时返回 None。

        **从 manifest 反查而不是拼 f"tank{n}"**: 少一个只存在于两处代码里的字符串约定。
        某个缸的溶液槽没被 build_tanks 认出来时, 只有那一个缺 liquidNode。
        """
        entry = next(
            (item for item in (self.manifest.get("tanks") or []) if item.get("index") == tank - 1),
            None,
        )
        if not entry or not entry.get("id") or not entry.get("liquidNode"):
            return None
        return str(entry["id"])

    def seed_entry_state(self, entry: PhaseEntry, bindings: dict[str, Any]) -> None:
        """把"前置段留下的状态"播种成本片段的起手态(见 PHASE_ENTRY_STATE)。

        必须在 `run_operation` **之前**调用: 本段自己的排液动作要靠 tank_volume_ml 才知道
        起点是 60mL 而不是 0 —— 晚一步, emit_tank_liquid 就已经按空缸把排液退化成
        `wait{}` 并打上"缸内已是空的"的标签了。

        液量的算法只有一份: 拿一个**丢弃用**的 ClipBuilder 把前置段脚本按其默认配方跑一遍,
        只取它的 tank_volume_ml, 步骤/关节/载荷一概不要。这样配方默认值(develop_volume_ml
        × up_liquid_repeat_count)改了三维跟着变, 不在这里留第二个 60.0。

        丢弃用 builder **刻意不带 scene/payload_frames/plate**: 它只用来跟一个体积数,
        带上就要白建一遍 RobotPosture 与板锚点表。前置段(develop_prepare)全是工位动作、
        没有任何机械臂运动, 不触 IK / moveL, 于是代价可忽略。

        Args:
            entry: 起手态声明
            bindings: 本片段已求值的入参(至少含缸号)

        Raises:
            CompileError: 前置段算出 0 液量 —— 那意味着上游配方不再注液, 是必须被人看见的
                事实, 不能静默生成一条空缸片段
        """
        if entry.liquid_after:
            prelude = ClipBuilder(
                control_root=self.control_root, registry=self.registry,
                calibration=self.calibration, manifest=self.manifest,
                rail_slots=self.rail_slots, assume_tool=self.assume_tool,
            )
            # 这两个开关必须跟宿主一致, 否则前置段根本跑不完:
            #   flow_mode   —— 决策外壳(with_resources / try / while)只在流程档被容忍,
            #                  不继承就在 develop_prepare 的 with_resources 上抛"未知指令";
            #   assumptions —— 那些"读运行期测量结果"的入参靠它消解。
            prelude.flow_mode = self.flow_mode
            prelude.assumptions = dict(self.assumptions)
            document = load_operation(self.control_root, entry.liquid_after)
            prelude_bindings = default_bindings(document)
            for key in ("tank", "target_tank"):
                if key in prelude_bindings and key in bindings:
                    prelude_bindings[key] = bindings[key]
            prelude.run_operation(entry.liquid_after, document, prelude_bindings)
            left_in_tank = any(volume > 0 for volume in prelude.tank_volume_ml.values())
            # 驻位液体(收集样品瓶)与缸同等算数: collect_unload 的前置段(collect_execute)
            # 一滴缸液都不动, 留下的全在瓶里 —— 只看缸就会把这条合法声明误杀。
            left_in_station = any(volume > 0 for volume in prelude.station_liquid_ml.values())
            if not left_in_tank and not left_in_station:
                raise CompileError(
                    f"起手态声明说本段起于 {entry.liquid_after} 之后({entry.why}), "
                    f"但那一段按默认配方跑完一滴液都没留下 —— 要么配方改了, 要么这条声明过期了。"
                    "宁可不生成, 也不静默演一个空缸"
                )
            for tank, volume in prelude.tank_volume_ml.items():
                tank_id = self._tank_id(tank)
                if tank_id is None:
                    continue
                # 两处都要写: tank_volume_ml 让本段的排液知道起点, home_liquid_ml 让片段
                # 落盘时带上 home.liquid_ml(否则 clipSchema 不建通道, 播放器停在 home() 的 0)
                self.tank_volume_ml[tank] = volume
                self.home_liquid_ml.setdefault(tank_id, round(volume, 3))
            # 驻位液体同构承接: station_liquid_ml 让本段后续动作知道起点(将来有排瓶动作
            # 也不用假设), home.liquid_ml 让下料片段起手瓶里就带着洗脱液
            for liquid_id, volume in prelude.station_liquid_ml.items():
                if volume <= 0:
                    continue
                self.station_liquid_ml[liquid_id] = volume
                self.home_liquid_ml.setdefault(liquid_id, round(volume, 3))

        if entry.plate_at:
            try:
                slot = entry.plate_at.format(**bindings)
            except KeyError as exc:
                # 裸 KeyError 会被 _write_flow_clips 吞成一条看不懂的 failure
                raise CompileError(
                    f"起手态落点模板 {entry.plate_at!r} 引用了本段没有的入参 {exc} "
                    f"—— 要么模板写错了, 要么这条流程的入参名变了({entry.why})"
                ) from exc
            # 形状照抄 _plate_transfer 的取板分支 —— plate.flow.develop_unload.* 的第一步
            # 正是这个(`plate: {at: tank:N}` @ at:0/dur:0), 已验证可用。
            #
            # **不调** _check_plate_anchor: 那是拿机械臂当前位姿做的相对复核, 而起手态下
            # 机械臂根本不在缸边, 复核出来的偏置没有意义。compiled.plateAnchorChecks
            # 对这类片段保持为空是正确的, 不是漏了。
            self._register_seat_axis(slot)
            self.plate_intro = [{
                "label": "板在位(前置段已放入)", "at": 0, "dur": 0,
                "do": {"plate": {"id": PLATE_CLIP_ID, "at": slot}},
            }]
            self._plate_shown = True
            self._plate_slot = slot
            self._plate_at = slot  # 前置段把板留在了这个落点上

        # 前置段留在场上的载荷(如接粉收集器): 形状照抄载荷起手式(emit_tool_action 的
        # _intro_seen 分支), at:0/dur:0 的 state 步。不点亮的话, photoscrape_process 末尾
        # 的"翻料倒粉"就是在空翻一只旋转气缸 —— 桶(STA_SCRAPE_HOLDER)manifest 初始不可见。
        for state_id in entry.states:
            if state_id in self._intro_seen:
                continue
            self._intro_seen.add(state_id)
            self.payload_intro.append({
                "label": f"{state_id} 显示(前置段已放入)", "at": 0, "dur": 0,
                "do": {"state": {"id": state_id, "value": True}}})

        # 前置段留下的机构状态(如翻料缸停在倒粉位): 在 MECHANISM_HOME 全局起手态上按段
        # 覆盖(mechanism_home() 应用)。声明的是**状态**不是编造运动 —— 片段随后驱动该
        # 机构时, 步骤照常从这个起手值出发(如 collect_load 的 retr_stoprot 把 1 驱回 0)。
        for mechanism, value, why in entry.mechanisms:
            channel = self._mechanism_channel(mechanism)  # 打错 id 在此硬失败
            if channel == "data-only":
                raise CompileError(
                    f"起手态机构 {mechanism} 是 rigged:false 的 data-only 条目, 没有几何"
                    f" 可摆 —— 这条声明是错觉({why})")
            self.home_mechanism_overrides[mechanism] = float(value)
            note = f"起手态 {mechanism}={value:g}: {why}"
            if note not in self.flow_notes:
                self.flow_notes.append(note)

        # 前置段留在桶里的粉(如收集段起手时桶里已装着刮取段吸进去的粉)。
        # 与 mechanisms 同构的声明式承接, 但**不硬失败**: 粉柱几何还没进管线时
        # manifest 里没有它, 而那正是设计好的降级路径(前端 setter 查不到就静默不动)。
        if entry.powders:
            full_mm3 = demo_powder_total_mm3(load_gcode_calib(self.control_root))
            for powder_id, ratio, tint, why in entry.powders:
                volume_mm3 = round(full_mm3 * float(ratio), 1)
                self.home_powder_mm3.setdefault(powder_id, volume_mm3)
                if float(tint) > 0:
                    self.home_powder_tint.setdefault(powder_id, float(tint))
                note = (f"起手态 {powder_id}={volume_mm3:g}mm³(满刮取 ×{float(ratio):g})"
                        f"{'(已洗脱)' if float(tint) > 0 else ''}: {why}")
                if note not in self.flow_notes:
                    self.flow_notes.append(note)

    def _tank_fill_pourer(self, action: str, args: dict):
        """为一条展缸**注液**动作造"逐趟涨液面"的发射器, 返回 (pour, finish)。

        为什么要逐趟, 而不是像 2026-08-09 之前那样一条斜坡到底: 编译器原先把一条动作的
        泵行程**全部发完才发那一条整段液面斜坡**, 于是 develop_prepare 的 170.6 s 里
        140.6 s(82%)缸内恒为 0 —— 4 趟 10 mL 润洗泵行程期间缸里一动不动, 而展缸泵的几何
        在 ST_PUMP 工位, 镜头对着展缸时根本不在画面里。表现就是用户报的"吸 10 mL 没有
        任何动画, 20 mL 才有"(那个 20 其实是随后那条整段斜坡的终点)。节拍与
        emit_station_liquid 的"逐轮泵吸排 → 液面涨一截"同构。

        每趟的增量取**泵这一趟真打出去的 delta**, 而不是"契约总量 / 趟数":
        相位被 PUMP_DEMO_MAX_PHASES 压过轮数时前者自动对、后者会算错。压缩造成的差额由
        finish() 按契约总量补一条 —— 与泵那条"压缩轮数不截相位, 终点体积不变"同一条纪律。

        注液仍是**绝对目标**(与 emit_tank_liquid 的头注同一条约定): 逐趟累加封顶在契约总量,
        所以缸里已有液时可能提前封顶、少涨几趟, 但终点体积与改前逐位相同。

        Args:
            action: 动作名
            args: 已求值的动作入参

        Returns:
            (pour, finish); 这条动作不该走逐趟(不在表里/是排液/缸号或体积解不出/该缸没有
            液面几何)时返回 (None, None), 由调用方退回 emit_tank_liquid 的整段斜坡 ——
            那条路径的行为逐字节不变。
        """
        spec = (self.tank_liquid.get("actions") or {}).get(action)
        cavity = self.tank_liquid.get("cavity") or {}
        if not spec or not cavity or spec.get("dir") != "fill":
            return None, None
        tank_arg = self.tank_liquid.get("tankArg") or "target_tank"
        try:
            tank = int(args.get(tank_arg))
        except (TypeError, ValueError):
            return None, None
        if not 1 <= tank <= 8:
            return None, None
        tank_id = self._tank_id(tank)
        if tank_id is None:
            return None, None

        # 契约总量: 与 emit_tank_liquid 的 fill 分支**逐字同式**(体积×趟数连乘, 缺项按 1,
        # 扣管路存液, 封顶槽容)。这里不新造规则 —— 规则真源仍是 manifest["tankLiquid"]。
        total_ml = 1.0
        for key in spec.get("volumeFrom") or []:
            try:
                value = float(args.get(key))
            except (TypeError, ValueError):
                value = 0.0
            total_ml *= value if value > 0 else 1.0
        if not total_ml > 0:
            return None, None
        total_ml = max(0.0, total_ml - float(self.tank_liquid.get("pipeHoldupMl") or 0.0))
        capacity_ml = float(cavity.get("capacityMl") or 0.0)
        if capacity_ml > 0:
            total_ml = min(total_ml, capacity_ml)

        start_ml = self.tank_volume_ml.get(tank, 0.0)
        state = {"ml": start_ml, "poured": 0}

        def pour(at: float, dur: float, delta_ml: float) -> None:
            """泵打出去一趟 -> 缸里同 at 同 dur 涨一截。"""
            prev_ml = state["ml"]
            target_ml = min(prev_ml + max(0.0, float(delta_ml)), total_ml)
            # 零位移不发假斜坡(与 emit_tank_liquid/emit_axis 同一条)
            if abs(target_ml - prev_ml) < 0.05:
                return
            self.emit(
                f"{tank}号缸注液 {prev_ml:.1f} → {target_ml:.1f} mL",
                dur,
                {"liquid": {"id": tank_id, "to_ml": round(target_ml, 3)}},
                ease="out",
                at=at,
            )
            state["ml"] = target_ml
            state["poured"] += 1

        def finish() -> bool:
            """收尾: 记账 + 补足被压缩掉的余量。一趟都没涨成就交还给整段斜坡。"""
            if not state["poured"]:
                return False
            # 首次驱动才声明 home(与 emit_tank_liquid 同构): 起手体积是**驱动前**的累计值
            if tank_id not in self.home_liquid_ml:
                self.home_liquid_ml[tank_id] = round(start_ml, 3)
            if total_ml - state["ml"] >= 0.05:
                self.emit(
                    f"{tank}号缸注液 {state['ml']:.1f} → {total_ml:.1f} mL(泵段已压缩轮数, 补足余量)",
                    min(float(spec.get("rampS") or 8.0), TANK_LIQUID_MAX_RAMP_S),
                    {"liquid": {"id": tank_id, "to_ml": round(total_ml, 3)}},
                    ease="out",
                )
                state["ml"] = total_ml
            self.tank_volume_ml[tank] = state["ml"]
            return True

        return pour, finish

    def emit_tank_liquid(self, action: str, args: dict) -> bool:
        """把一条展缸注/排液动作译成液面斜坡步。

        体积规则**不在这里定义**: 整张表来自 manifest["tankLiquid"](真源是
        gen_twin_manifest.TANK_LIQUID_ACTIONS), 本方法只做查表、按表连乘入参、发一步。
        任何在这里补一条新规则的改动都是在造第三份真源, 见 __init__ 里 tank_liquid 的注释。

        与前端 demo/flowSim.js 的 emitTankLiquid 必须保持同构: 两边都跨动作跟踪缸内体积,
        否则同一条流程在"精编译"档与"近似"档的液面高低对不上, 而两档看着都挺正常。

        **注液的常规路径已不在这里**: 有泵行程可并的注液走 _tank_fill_pourer 逐趟发,
        本方法只在那条路走不通(泵没几何/路由不到/入参是运行期量/一趟都没涨成)时兜底,
        以及排液(走真空不走泵, 本就该一条斜坡到底)。改这里的体积规则前先看那边。

        Args:
            action: 动作名
            args: 已求值的动作入参

        Returns:
            是否真的发了液面步(缸号解不出、该缸没有液面几何时返回 False, 由调用方兜底)
        """
        spec = (self.tank_liquid.get("actions") or {}).get(action)
        cavity = self.tank_liquid.get("cavity") or {}
        if not spec or not cavity:
            return False

        tank_arg = self.tank_liquid.get("tankArg") or "target_tank"
        try:
            tank = int(args.get(tank_arg))
        except (TypeError, ValueError):
            return False
        if not 1 <= tank <= 8:
            # **不猜**: 缸号是运行期量时如实退回时间格, 与 flowSim 的 deferred 同一条纪律
            return False

        tank_id = self._tank_id(tank)
        if tank_id is None:
            return False

        capacity_ml = float(cavity.get("capacityMl") or 0.0)
        pipe_holdup_ml = float(self.tank_liquid.get("pipeHoldupMl") or 0.0)
        prev_ml = self.tank_volume_ml.get(tank, 0.0)

        if spec.get("dir") == "fill":
            # 体积 = 各来源参数连乘(体积 × 趟数), 缺哪个按 1 算 —— 逐字对应
            # TankLiquidModel._resolve 的 fill 分支(流程 YAML 只写部分入参时, 其余由
            # 动作目录的 default 在执行器侧补齐, 编译期同样看不到)。
            target_ml = 1.0
            for key in spec.get("volumeFrom") or []:
                try:
                    value = float(args.get(key))
                except (TypeError, ValueError):
                    value = 0.0
                target_ml *= value if value > 0 else 1.0
            if not target_ml > 0:
                return False
            # 注液是**绝对目标**而不是往上累加(体积 × 趟数已经是缸内总量), 与实时侧
            # TankLiquidModel.onActionEnter 的 `channel.target = targetMl` 一致。
            # 代价: 同一缸连发两次 develop.fill 画面上不动 —— 配方里那是靠
            # up_liquid_repeat_count 表达的, 不是靠调两次。与实时侧对齐比"物理上加起来"值钱。
            target_ml = max(0.0, target_ml - pipe_holdup_ml)
            if capacity_ml > 0:
                target_ml = min(target_ml, capacity_ml)
        else:
            target_ml = 0.0

        if tank_id not in self.home_liquid_ml:
            self.home_liquid_ml[tank_id] = round(prev_ml, 3)
        self.tank_volume_ml[tank] = target_ml

        verb = "注液" if spec.get("dir") == "fill" else "排液"
        if abs(target_ml - prev_ml) < 0.05:
            # 零位移不发假斜坡(与 emit_axis 跳过零位移步同一条), 但要说出为什么没动
            why = "缸内已是空的" if target_ml <= 0.05 else "缸内已是该液量"
            self.emit(f"{tank}号缸{verb}({why}, 无液面变化)", 1.0, {"wait": {}})
            return True

        # 沉降延时(润洗抽吸的 settle_s): 先静置再抽 —— 这是实时侧 TankLiquidModel.step()
        # 里 running.delayS 的关键帧写法, 观感等价
        delay_s = 0.0
        if spec.get("delayFromArg"):
            try:
                delay_s = float(args.get(spec["delayFromArg"]) or 0.0)
            except (TypeError, ValueError):
                delay_s = 0.0
        if delay_s > 0:
            self.emit(f"{tank}号缸静置沉降 {delay_s:.0f}s", min(delay_s, TANK_LIQUID_MAX_RAMP_S),
                      {"wait": {}})

        ramp_s = float(spec.get("rampS") or 8.0)
        if spec.get("rampFromArg"):
            try:
                from_arg = float(args.get(spec["rampFromArg"]) or 0.0)
            except (TypeError, ValueError):
                from_arg = 0.0
            if from_arg > 0:
                ramp_s = from_arg
        dur = min(ramp_s, TANK_LIQUID_MAX_RAMP_S)
        time_note = f"(实机 {ramp_s:.0f}s, 演示压到 {dur:.0f}s)" if ramp_s > dur else ""

        self.emit(
            f"{tank}号缸{verb} {prev_ml:.1f} → {target_ml:.1f} mL{time_note}",
            dur,
            {"liquid": {"id": tank_id, "to_ml": round(target_ml, 3)}},
            # out(先快后缓、永不过冲)最接近实时侧的指数趋近观感; inout 会在起步处
            # 出现一段假的加速
            ease="out",
        )
        return True

    def emit_station_liquid(self, action: str, args: dict, pump_shown: bool = False) -> bool:
        """把一条驻位液体动作(collect.collect)译成逐轮"泵段→液面斜坡→沉淀"步序。

        规则不在这里定义: 单轮体积(volumeFrom 连乘)、轮数(repeatFrom)、实机时长(roundS,
        写进标签)与演示时长(demoS, 上时间轴)全部来自 manifest["liquids"][*].actions
        (真源 gen_twin_manifest.STATION_LIQUID_ACTIONS)。前端镜像是 TankLiquidModel.
        resolveStationLiquidPlan(flowSim/actionSim 共用), 两侧同构由片段语料测试
        (web/tests/three-d/stationLiquid.test.js)锁住。

        与 emit_tank_liquid 的三处刻意不同(与契约头注同一段话, 别抄错):
          1. 展缸是"体积×趟数连乘出总量、一条斜坡到底"; 这里逐轮累加 —— 要演的是
             "每轮泵吸排→液面涨一截→沉淀"的节拍, 不是一次涨到位;
          2. 液面上升对应的是**正压排液 20s 窗口**(溶剂经滤芯落进瓶), 不是泵 dispense
             的那一秒 —— 所以斜坡拍叫"正压排液入瓶";
          3. 轮数超 demoMaxRounds 只演前 N 轮并记 flowNotes(终点体积如实截断, 不虚报)。

        Args:
            action: 动作名
            args: 已求值的动作入参
            pump_shown: 柱塞行程是否已单独编出(编出了就省掉"泵吸排"占位拍, 免得双份泵戏)

        Returns:
            是否真的发了液面步(契约缺失/单轮体积解不出时返回 False, 由调用方兜底)
        """
        entry = self.station_liquids.get(action)
        if not entry:
            return False
        spec = (entry.get("actions") or {}).get(action) or {}
        liquid_id = str(entry.get("id") or "")
        cavity = entry.get("cavity") or {}
        capacity_ml = float(cavity.get("capacityMl") or 0.0)
        if spec.get("dir") != "fill" or not liquid_id or capacity_ml <= 0:
            return False

        # 单轮体积 = volumeFrom 连乘, 缺哪个按 1 算 —— 逐字对应 resolveStationLiquidPlan
        per_round_ml = 1.0
        for key in spec.get("volumeFrom") or []:
            try:
                value = float(args.get(key))
            except (TypeError, ValueError):
                value = 0.0
            per_round_ml *= value if value > 0 else 1.0
        if not per_round_ml > 0:
            return False

        rounds_total = 1
        if spec.get("repeatFrom"):
            try:
                raw_rounds = int(args.get(spec["repeatFrom"]))
                rounds_total = raw_rounds if raw_rounds > 0 else 1
            except (TypeError, ValueError):
                rounds_total = 1
        max_rounds = int(spec.get("demoMaxRounds") or rounds_total)
        rounds_shown = min(rounds_total, max_rounds)
        if rounds_shown < rounds_total:
            self.flow_notes.append(
                f"{action} 共 {rounds_total} 轮洗脱, 演示只演前 {rounds_shown} 轮"
                f"(demoMaxRounds, 液面终点如实停在 {rounds_shown} 轮的量)")

        real = {"pump": 2.1, "transfer": 20.0, "settle": 5.0, **(spec.get("roundS") or {})}
        demo = {"pump": 1.0, "transfer": 6.0, "settle": 2.0, **(spec.get("demoS") or {})}
        prev_ml = self.station_liquid_ml.get(liquid_id, 0.0)
        # 首次驱动才声明 home(与 home_liquid_ml 的展缸用法同构): 起手体积是驱动前的累计值
        if liquid_id not in self.home_liquid_ml:
            self.home_liquid_ml[liquid_id] = round(prev_ml, 3)

        for round_no in range(1, rounds_shown + 1):
            target_ml = min(prev_ml + per_round_ml, capacity_ml)
            if not pump_shown:
                self.emit(
                    f"收集·泵吸排洗脱剂 {per_round_ml:g} mL"
                    f"(第 {round_no}/{rounds_total} 轮, 实机≈{real['pump']:g}s)",
                    min(float(demo["pump"]), TANK_LIQUID_MAX_RAMP_S), {"wait": {}})
            ramp_s = min(float(demo["transfer"]), TANK_LIQUID_MAX_RAMP_S)
            transfer_at = self._timeline_end_s()
            self.emit(
                f"收集·正压排液入瓶 {prev_ml:.2f} → {target_ml:.2f} mL"
                f"(实机≈{real['transfer']:g}s, 演示压到 {ramp_s:g}s)",
                ramp_s,
                {"liquid": {"id": liquid_id, "to_ml": round(target_ml, 3)}},
                ease="out",
            )
            # 粉换色与排液**同一拍并行**: 洗脱液正是这一拍穿过粉柱落进瓶里的, 干粉被浸透
            # 转成湿润色。只在第一轮发 —— 粉一旦湿了, 后续几轮再冲也不会更湿, 逐轮重发
            # 只会让通道上多几个同值关键帧。
            if round_no == 1:
                self.emit(
                    "收集·洗脱液浸透硅胶粉(粉色转湿润)", ramp_s,
                    {"powder": {"id": COLLECT_POWDER_ID, "phase": "tint", "to": 1.0}},
                    ease="out", at=transfer_at,
                )
            self.emit(
                f"收集·静置沉淀(实机≈{real['settle']:g}s)",
                min(float(demo["settle"]), TANK_LIQUID_MAX_RAMP_S), {"wait": {}})
            prev_ml = target_ml
        self.station_liquid_ml[liquid_id] = prev_ml
        return True

    def _pump_of(self, pump_spec: dict, args: dict) -> dict | None:
        """按动作表的 pump 段解析出 manifest 里的那台泵。

        缸号路由查每台泵自己的 tankGroup, **不重算 (target_tank-1)//4+1** —— 那个算术的
        权威在 tools/pump/develop_translator.py, 这里再抄一份就是两个真源, 改缸组必漂。
        与前端 PumpSyringeModel._pumpIndex 同一判据。

        Args:
            pump_spec: 动作表条目的 pump 段({from: fixed|tankGroup, id?/arg?})
            args: 已求值的动作入参

        Returns:
            manifest.pumpSyringe.pumps 里的条目; 路由不到返回 None
        """
        pumps = self.pump_syringe.get("pumps") or []
        source = pump_spec.get("from")
        if source == "fixed":
            wanted = pump_spec.get("id")
            for pump in pumps:
                if pump.get("id") == wanted:
                    return pump
            return None
        if source == "tankGroup":
            try:
                tank = int(args.get(pump_spec.get("arg") or ""))
            except (TypeError, ValueError):
                return None
            for pump in pumps:
                if tank in (pump.get("tankGroup") or []):
                    return pump
        return None

    def emit_pump_syringe(self, action: str, args: dict,
                          on_dispense: Callable[[float, float, float], None] | None = None,
                          ) -> bool:
        """把一条泵动作译成柱塞行程步(`pump`)与换阀步(`pump_valve`)。

        相位规则**不在这里定义**: 整张表来自 manifest["pumpSyringe"](真源是
        gen_twin_manifest.PUMP_SYRINGE_ACTIONS), 本方法只做查表、展开相位、按 V/M 算时长、
        发步。任何在这里补一条新规则的改动都是在造第三份真源 —— 前端实时台
        (PumpSyringeModel)与近似档(flowSim 经 expandPumpPlan)消费的是同一份表。

        展开语义逐条对齐 PumpSyringeModel._expand/_phaseTarget/_sum/_phaseTiming/_resolvePort:
          · repeatFrom/loop.repeatFrom 超出相位预算时**压缩轮数不截相位**(终点体积不变),
            压缩了就写 flowNotes;
          · to/toFrom 绝对目标, by/byFrom 相对前一相位终点(符号由 op 定), 全部夹 [0, 量程];
          · 时长 = ΔmL×(步/mL)/V + M/1000, V 取 action args > manifest 速度快照(构建期
            collect_pump_speeds 从 app.yaml 拍的), 取不到退相位 rampS; 超 PUMP_MAX_RAMP_S
            压缩并在标签写真值 —— 与缸液面同一条"观感值不是物理量"的约定;
          · 端口 "output" → 该泵的 outputPort; 解不出口号(典型: 收集泵没有被单测钉死的
            指令串, manifest 刻意不给 outputPort)就**跳过换阀步只发柱塞步**, 呼应 rig_map
            "宁可阀指针不转, 也不编一个"。

        跨动作跟踪与缸液面同构: pump_volume_ml 记各泵当前体积(sampling.prep 停在气隙位,
        aspirate 在其上相对叠加), 首次驱动某泵时把**驱动前**的体积写进 home.pump_ml。

        Args:
            action: 动作名
            args: 已求值的动作入参
            on_dispense: 每发完一条**打向本泵 outputPort** 的 dispense 行程步就回调一次,
                入参 (at, dur, delta_ml) —— 那一趟的起止时刻与真打出去的体积。展缸注液
                靠它把液面斜坡与泵行程并到同一拍上, 见 _tank_fill_pourer。
                回调**必须在这里、紧跟泵步之后**发步, 不能攒到最后统一补: `_timeline_end_s`
                是顺序扫描, 显式 at 会把光标拨回去(见 emit 的头注)。

        Returns:
            是否发了泵步(动作不驱泵/路由不到/泵没几何/全零行程时 False, 由调用方兜底)
        """
        spec = (self.pump_syringe.get("actions") or {}).get(action)
        if not spec:
            return False
        pump = self._pump_of(spec.get("pump") or {}, args)
        if pump is None:
            return False
        pump_id = str(pump.get("id"))
        label_prefix = str(pump.get("label") or pump_id)
        if not pump.get("rigged") or not pump.get("plungerNode"):
            # 泵在数据上照跑(实时台面板可见), 三维没几何 —— 如实注记一次, 时间格由调用方兜
            note = f"{label_prefix} 未建几何(rigged:false), 泵行程仅以时间格表现"
            if note not in self.flow_notes:
                self.flow_notes.append(note)
            return False

        syringe_ml = float(self.pump_syringe.get("syringeMl") or 25.0)
        steps_per_ml = float(self.pump_syringe.get("stepsPerStroke") or 6000.0) / syringe_ml

        def clamp_ml(value: float) -> float:
            return min(max(value, 0.0), syringe_ml)

        def number_of(raw) -> float | None:
            """入参转正数; 缺失/非数/非正一律 None(与前端 Number()+>0 判据同形)。"""
            if isinstance(raw, bool):
                return None
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None
            return value if value > 0 else None

        def sum_of(source: dict) -> float | None:
            """求和(缺项走 fallback)。是**求和**不是连乘 —— 缸液面那边是体积×趟数故用乘法,
            这里 flush 是三段体积相加, 缺项按 0 会把峰值抹平, 所以动作表里给了 fallback。"""
            keys = source.get("add") or []
            fallbacks = source.get("fallback") or []
            total, hit = 0.0, 0
            for i, key in enumerate(keys):
                value = number_of(args.get(key))
                if value is not None:
                    total += value
                    hit += 1
                    continue
                fallback = number_of(fallbacks[i]) if i < len(fallbacks) else None
                if fallback is not None:
                    total += fallback
            if hit == 0 and not total > 0:
                return None
            return total

        def target_of(phase: dict, prev: float) -> float | None:
            if phase.get("op") == "home":
                return 0.0
            direction = -1.0 if phase.get("op") == "dispense" else 1.0
            to, by = phase.get("to"), phase.get("by")
            if isinstance(to, (int, float)) and not isinstance(to, bool):
                return clamp_ml(float(to))
            if isinstance(by, (int, float)) and not isinstance(by, bool):
                return clamp_ml(prev + direction * float(by))
            if phase.get("toFrom"):
                amount = sum_of(phase["toFrom"])
                if amount is None:
                    return None if phase.get("skipIfMissing") else clamp_ml(prev)
                return clamp_ml(amount)
            if phase.get("byFrom"):
                amount = sum_of(phase["byFrom"])
                if amount is None:
                    return None if phase.get("skipIfMissing") else clamp_ml(prev)
                return clamp_ml(prev + direction * amount)
            return None

        def speed_of(key) -> float | None:
            """V/M 回退链, 与执行器逐字同构(profiles._speed_kwargs / pump_default_hint):
            动作入参 > config.pump 持久值(ClipBuilder 构造时经 offline_defaults 安装
            provider) > translator 常量。旧的"manifest 速度快照"层已删(阶段①归真) ——
            快照是 manifest 构建期拍的, app.yaml 改档后不重建 manifest 就陈旧;
            现在编译时直读 config.pump, 演示时长与实机同源。"""
            if not key:
                return None
            from_args = number_of(args.get(key))
            if from_args is not None:
                return from_args
            return number_of(pump_default_hint(str(pump.get("speedStation") or ""), key))

        def port_of(phase: dict) -> int | None:
            port = phase.get("port")
            if port == "output":
                out = pump.get("outputPort")
                return int(out) if isinstance(out, (int, float)) and not isinstance(out, bool) and out else None
            if isinstance(port, bool) or not isinstance(port, (int, float)):
                return None
            value = int(port)
            if value < 1:
                return None
            total = int(pump.get("valvePorts") or 0)
            # 越界的口号一律当没写 —— 转到一个不存在的口比不转更糟
            return None if (total > 0 and value > total) else value

        # 本泵的出液口。on_dispense 只对打向它的那一趟回调 —— 别的口是溶剂口/废液口,
        # 打过去缸里不该涨。manifest 没给 outputPort 时恒为 None, 一趟都不回调,
        # 调用方自然退回整段斜坡(与"宁可阀指针不转, 也不编一个"同一条)。
        output_port = port_of({"port": "output"})

        # -- 展开: 轮数压缩(与 PumpSyringeModel._expand 同一算法, 预算换成演示档的 8) --
        def count_of(key: str) -> int:
            raw = args.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                return 1
            value = int(raw)
            return value if value > 0 and float(raw).is_integer() else 1

        loop = spec.get("loop") or {}
        outer_wanted = count_of(spec["repeatFrom"]) if spec.get("repeatFrom") else 1
        inner_wanted = (count_of(loop["repeatFrom"]) if loop.get("repeatFrom") else 1) if loop else 0
        outer_len = len(spec.get("phases") or [])
        inner_len = len(loop.get("phases") or [])
        outer, inner = outer_wanted, inner_wanted
        while outer * outer_len + inner * inner_len > PUMP_DEMO_MAX_PHASES and (outer > 1 or inner > 1):
            if inner * inner_len >= outer * outer_len and inner > 1:
                inner -= 1
            elif outer > 1:
                outer -= 1
            else:
                break

        start_ml = self.pump_volume_ml.get(pump_id, 0.0)
        prev = start_ml
        current_port = self.pump_valve_port.get(pump_id)
        verb_of = {"home": "柱塞归零", "aspirate": "吸液", "dispense": "排液"}
        emitted = False

        def run_phase(phase: dict) -> None:
            nonlocal prev, current_port, emitted
            target = target_of(phase, prev)
            if target is None:
                return
            port = port_of(phase)
            if port is not None and port != current_port:
                self.emit(f"{label_prefix}·阀→{port}号口", PUMP_VALVE_S,
                          {"pump_valve": {"id": pump_id, "port": port}}, ease="inout")
                current_port = port
                emitted = True
            delta = abs(target - prev)
            if delta < 0.01:
                # 零行程不发假斜坡(与 emit_axis/emit_tank_liquid 同一条); 换阀步照发
                prev = target
                return
            ramp_s, hold_s = PUMP_MAX_RAMP_S, 0.0
            speed = speed_of(phase.get("speed"))
            delay = speed_of("step_delay")
            if delay is not None:
                hold_s = delay / 1000.0
            real_s = (delta * steps_per_ml) / speed if speed else float(phase.get("rampS") or 3.0)
            dur = min(real_s, PUMP_MAX_RAMP_S)
            time_note = f"(实机 {real_s:.0f}s, 演示压到 {dur:.0f}s)" if real_s > dur else ""
            verb = verb_of.get(str(phase.get("op")), "行程")
            # 行程步的起点 —— 要在发它之前取。只有真有人要并行才算(顺序扫描, 不白花)
            stroke_at = self._timeline_end_s() if on_dispense is not None else 0.0
            self.emit(
                f"{label_prefix}·{verb} {prev:.1f} → {target:.1f} mL{time_note}",
                dur,
                {"pump": {"id": pump_id, "to_ml": round(target, 3)}},
                # out 与缸液面同款: 先快后缓、永不过冲
                ease="out",
            )
            # 缸内液面与这一趟 dispense 同 at 同 dur 并行。**位置不能挪到下面的稳液步之后**:
            # 那样光标会被从 stroke_at+dur+hold_s 拨回 stroke_at+dur, 之后每一步都错位 hold_s。
            # 判据用 current_port(阀这一刻真在哪个口)而不是 phase["port"]: 相位不写口时
            # 沿用上一相位的口, 拿 phase 判会漏掉那种写法。
            if (on_dispense is not None and str(phase.get("op")) == "dispense"
                    and output_port is not None and current_port == output_port):
                on_dispense(stroke_at, dur, delta)
            if hold_s > 0:
                # 实机每段移动后停 M 毫秒稳液 —— "一段一段"的节奏就在这, 不压缩(≤1.5s)
                self.emit(f"{label_prefix}·稳液 {hold_s:.1f}s", hold_s, {"wait": {}})
            prev = target
            emitted = True

        for _ in range(outer):
            for phase in spec.get("phases") or []:
                run_phase(phase)
        for _ in range(inner):
            for phase in loop.get("phases") or []:
                run_phase(phase)

        if not emitted:
            return False

        # 首次驱动才声明 home(与 home_liquid_ml 同构): 起手体积是**驱动前**的累计值,
        # 阀起手恒 1 号口(0° 那侧是接针筒的平口, 没有口 —— 与前端通道初值同一条约定)
        if pump_id not in self.home_pump_ml:
            self.home_pump_ml[pump_id] = round(start_ml, 3)
        if pump_id not in self.home_pump_port:
            self.home_pump_port[pump_id] = 1
        self.pump_volume_ml[pump_id] = prev
        if current_port is not None:
            self.pump_valve_port[pump_id] = current_port
        if outer < outer_wanted or inner < inner_wanted:
            self.flow_notes.append(
                f"{action} 实机 {outer_wanted}"
                + (f"×{inner_wanted}" if inner_wanted else "")
                + f" 轮, 演示压到 {outer}" + (f"×{inner}" if inner_wanted else "") + " 轮(终点体积不变)"
            )
        return True

    def emit_tool_action(self, verb: str) -> None:
        if verb in ("quick-change-lock", "quick-change-release"):
            asset = TOOL_ASSET[self.assume_tool]
            self.emit(
                "快换锁紧" if verb.endswith("lock") else "快换释放",
                0.45,
                {"tool": {"action": "lock" if verb.endswith("lock") else "release", "id": asset}},
            )
            return
        # 吸盘上下翻转: 真机是 1 号刀上的 HRQ10A 双气旋转气缸(DO2/DO6 互锁), 三维侧就是
        # rob_flip_suction 这条 actuator。语义与 robot_controller._TWIN_ACTION_STATE 对齐:
        # rotary-up = 1 = 托板朝上(点样/刮板位从板下方托板), rotary-down = 0 = 持板朝下
        # (料仓取板与展缸/废料仓放板)。时长取 rig_map 的 transitionS。
        if verb in ("rotary-up", "rotary-down"):
            if self.assume_tool != 1:
                raise CompileError(f"{verb} 只有 1 号刀(玻璃吸盘)允许, 当前假设挂的是 {self.assume_tool} 号刀")
            up = verb == "rotary-up"
            self._flip_value = 1.0 if up else 0.0
            # 时长取 manifest 里这条 actuator 的 transitionS(真源是 rig_map), 别写死 ——
            # 2026-08-05 之前这里是硬编码 0.6, 而注释却说"取 rig_map 的 transitionS":
            # 改标称值时 demo 的两个 JS 站点跟着变、编译出来的片段不变, 两条路径悄悄分叉。
            self.emit(
                "吸盘上翻(托板朝上)" if up else "吸盘下翻(持板朝下)",
                self._actuator_transition_s(FLIP_ACTUATOR_ID, 0.6),
                {"actuator": {"id": FLIP_ACTUATOR_ID, "to": 1.0 if up else 0.0}},
                ease="inout",
            )
            return

        # 吸盘真空: rob_suction 是 rigged:false 的纯状态机构(没有几何可驱)。
        # 板片段里这一步就是**板的交接时刻**: 吸气 = 板跟手, 放气 = 板落到当前落点。
        # 落点由"最近一次取放基准点"静态定出(见 PLATE_POINT_SLOT), 不是猜的。
        # 非板片段仍只出一个有语义的时间格(真机上 DO3 置位本身是瞬时的)。
        if verb in ("suction-on", "suction-off"):
            if self.assume_tool != 1:
                raise CompileError(f"{verb} 只有 1 号刀(玻璃吸盘)允许, 当前假设挂的是 {self.assume_tool} 号刀")
            on = verb == "suction-on"
            body = self._plate_transfer("on" if on else "off") if self.plate else {"wait": {}}
            label = "吸盘吸气" + ("·板跟手" if self.plate else "") if on else \
                    "吸盘放气" + ("·板落位" if self.plate else "")
            self.emit(label, 0.35, body)
            return

        if verb not in ("gripper-open", "gripper-close"):
            self.emit(verb, 0.3, {"wait": {}})
            return

        gripper = GRIPPER_BY_TOOL.get(self.assume_tool)
        seat = self._seat_stack[-1] if self._seat_stack else None
        closing = verb == "gripper-close"

        if gripper is None:
            self.emit(verb, 0.3, {"wait": {}})
        else:
            to = self._gripper_target(gripper, closing)
            # 反向绊线: 合爪算出 0.0(=张开态) 只可能是三态判据失效, 不可能是正确结果。
            # 上一版正是恒发 0.0 而无人发觉 —— 让这种缺陷从"静默"变成"编不出来"。
            if closing and to == 0.0:
                raise CompileError(
                    f"{gripper} 合爪算出 0.0 (= 张开态) —— 三态判据失效, 见 _closing_on_payload")
            self.emit(
                "夹爪夹持" if closing else "夹爪张开",
                0.4,
                {"linkage": {"id": gripper, "to": to}},
                ease="inout",
            )

        # 载荷交接的闸门。2026-08-06 之前这里写的是 `seat is None or self.transfer is None`,
        # 而 compile_plate_route(**全部 flow.* 片段走的那条路)恒传 transfer=None ——
        # 于是演示页「转移」分组 9 条流程 44 个片段一次 attach 都没有: 机械臂走位、夹爪开合
        # 都对, 爪子里什么都没有。同一个 operation 被编两遍(另一遍是 transfer.tray.*, 有交接),
        # 用户点到的正是没交接的这一遍。
        #
        # 换成 _in_tool_change: 换刀 prologue 里 robot_tool_put 的**空爪紧闭**不是取件,
        # 而它可能在某个 role=pick 的座位作用域内被展开(取放脚本的入口就 run_script
        # robot_tool_ensure) —— 不挡住的话那一下会静默 attach 一个错的载荷。
        if seat is None or self._in_tool_change:
            return
        seat_key, role = seat
        if closing and role == "pick":
            self._pick_payload(seat_key)
        elif not closing and role == "put":
            self._put_payload(seat_key)

    # -- 载荷交接 ---------------------------------------------------------- #

    def _intro_parent(self, parent_path: str) -> None:
        """t=0 点亮一个父托盘, 幂等。取件源侧与放件目的侧共用。

        托盘 state=false 时整棵子树不可见(three.js 父级 visible 压过子级), 所以无论是
        "从它上面取一件"还是"往它上面放一件", 托盘都必须在**片段起手**就在场:
        detach 事件的时刻取步骤的 `at` 而不是 `at+dur`(见 clipSchema 的离散事件分支),
        换父那一刻托盘还隐着的话, 件连同托盘一起消失整个落位补间(0.45s), 补间结束才
        三条 state 一起闪出来 —— 2026-08-13 用户报障"最后放粉桶时粉桶支架没有, 是后续
        闪现出来的", 病根就是目的侧父托盘此前排在补间**之后**发。

        父级不在载荷账里(站台常设件)就不发, 站台本来常显。
        """
        parent_id = parent_path.rsplit("/", 1)[-1]
        if parent_id not in self.ledger.by_id:
            return
        if parent_id in self._intro_seen or parent_id in self._intro_parent_seen:
            return
        self._intro_parent_seen.add(parent_id)
        self.payload_intro.append({
            "label": f"{parent_id} 显示", "at": 0, "dur": 0,
            "do": {"state": {"id": parent_id, "value": True}}})

    def _intro_payload(self, record: dict) -> None:
        """载荷起手式点亮(源实例 + 单件的父托盘 + 托盘的逐孔件), 幂等。

        home() 把 states 全部置 false, 不点亮的话整段"抓着空气走", 落位那一刻目的实例
        才凭空出现。单件载荷还得点亮父托盘: 托盘 state=false 时整棵子树不可见(three.js
        父级 visible 压过子级), 只点瓶子等于没点(2026-08-06 用户报障)。只点托盘本身、
        不点其余孔件 —— 演示要的是"托盘 + 对应的那一件"。
        """
        if record["id"] in self._intro_seen:
            return
        self._intro_seen.add(record["id"])
        if record["kind"] != "tray":
            self._intro_parent(record["parent"])
        self.payload_intro.append({
            "label": f"{record['id']} 显示", "at": 0, "dur": 0,
            "do": {"state": {"id": record["id"], "value": True}}})
        for item in self.ledger.items_of(record["id"]):
            self.payload_intro.append({
                "label": f"{item} 显示", "at": 0, "dur": 0,
                "do": {"state": {"id": item, "value": True}}})

    def preload_payload(self, script_name: str, bindings: dict[str, Any]) -> None:
        """"起手持件": 放件半程片段(STANDALONE_HALF_CARRY=starts_holding)开场时载荷已在爪中。

        取件发生在片段之外(演示页单动作条目只演放的半程), 所以这不是编造运动, 而是与
        carry_in(板)/ends_holding(取半程)同一条纪律: 把编译期拿不到的运行期事实写成
        看得见的声明。做法: 点亮载荷与父托盘 → t=0 detach 到 TOOL_MOUNT(dock 先占位,
        snap 让前端直接就位, 免磁吸补间与超限误报) → 爪给到夹持开度。
        夹持变换此刻还没有基准(要等机械臂走到放件点), 由 _put_payload 惰性回填占位
        dock —— 起手、随爪、落位全程同一刚体关系, 落位残差因此≈0。
        """
        seat = self._seat_for(script_name, bindings)
        if seat is None:
            return
        seat_key, _role = seat
        record = self.ledger.require(seat_key)
        if self._in_gripper is not None:
            raise CompileError(
                f"起手持件时爪里已经有 {self._in_gripper} —— STANDALONE_HALF_CARRY 被复合流程误用")
        self._in_gripper = record["id"]
        self._carried_node = record["node"]
        # off-screen 取件语义: 残差诊断的"取件姿态"取片段起手态
        self._pick_joints = list(self.current_joints)
        self._pick_rail = self.current_rail_mm
        self._intro_payload(record)
        self._preload_dock = {"position": [0.0, 0.0, 0.0], "quaternion": [0.0, 0.0, 0.0, 1.0]}
        self.emit("起手·持件在爪", 0.0, {"detach": {
            "id": record["id"], "parent": "TOOL_MOUNT",
            "dock": self._preload_dock, "snap": True}})
        self.emit_follow("起手·爪至夹持开度", 0.0, {"linkage": {
            "id": record["grip"], "to": self._close_value_for(record)}})

    def _pick_payload(self, seat_key: str) -> None:
        record = self.ledger.require(seat_key)
        if self._in_gripper is not None:
            raise CompileError(
                f"座位 {seat_key} 取件时爪里已经有 {self._in_gripper} —— 编译目标的取放不成对"
            )
        self._in_gripper = record["id"]
        self._intro_payload(record)
        # 夹持变换: 取料瞬间"托盘相对法兰"的刚体关系。此后托盘随爪走的一切都由它决定。
        if self.posture is not None:
            # 姿态账一旦入账就钉住地轨: 之后若有异站示教点想收养改写 home, 硬失败
            self._rail_pinned = True
            mount = self.posture.mount_world(
                joints_deg=self.current_joints, rail_mm=self.current_rail_mm)
            source_world = self._posed_world(record["node"])
            # 单件按抓取锚点修正(_grab_corrected, 托盘原样): 烤进片段的随爪/dock 与前端
            # 磁吸从此是同一个位姿, 放件不再弹跳
            self._grip_transform = self._grab_corrected(
                record, np.linalg.inv(mount) @ source_world)
            self._pick_joints = list(self.current_joints)
            self._pick_rail = self.current_rail_mm
            self._carried_node = record["node"]
        # 标签按载荷形态分: 步骤表是给人看的, 写"整板随爪"却飞走一个瓶子会误导排查
        label = "整板随爪" if record["kind"] == "tray" else "单件随爪"
        self.emit_follow(label, 0.0, {"attach": {"id": record["id"], "parent": "TOOL_MOUNT"}})

    def _put_payload(self, seat_key: str) -> None:
        if self._in_gripper is None:
            raise CompileError(f"座位 {seat_key} 放件时爪里是空的 —— 编译目标的取放不成对")
        destination = self.ledger.require(seat_key)
        carried = self.ledger.by_id[self._in_gripper]
        body: dict[str, Any] = {"id": carried["id"], "parent": destination["parent"]}

        if (self.posture is not None and self._grip_transform is None
                and self._preload_dock is not None):
            # 起手持件的惰性回填: 夹持变换 = 到位放件此刻的 inv(法兰) ∘ 座位 CAD 世界位姿。
            # 同一个 T 既回填 t=0 占位 dock(起手持件位姿), 又供下面正常落位使用 ——
            # 起手、随爪、落位全程同一刚体关系, 落位残差因此≈0。
            self._rail_pinned = True
            mount = self.posture.mount_world(
                joints_deg=self.current_joints, rail_mm=self.current_rail_mm)
            self._grip_transform = self._grab_corrected(
                carried, np.linalg.inv(mount) @ self._posed_world(carried["node"]))
            self._preload_dock.update(
                _dock_of(self._grip_transform, self._node_scale(carried["node"])))
            self._preload_dock = None

        swap_dock: dict | None = None
        if self.posture is not None and self._grip_transform is not None:
            # 落位世界位姿 = 放料示教点的法兰位姿 ∘ 取料时定下的夹持变换。
            # 真源是实机示教点, 不是 CAD —— 单件转移的目的地(刮板凹槽/收集夹具)在 GLB 里
            # 根本没有节点, 只有这条路走得通; 整板的目的地有 CAD 节点, 正好拿来做复核门禁。
            mount = self.posture.mount_world(
                joints_deg=self.current_joints, rail_mm=self.current_rail_mm)
            world = mount @ self._grip_transform
            if destination["kind"] == "tray":
                world = self._align_to_cad(world, destination)
            else:
                # 单件不做 CAD 平移校正: 目的实例改由下面的实例交换落到"件刚落到的那个
                # 几何位姿"上, CAD 摆放不再是单件落位的真源(2026-08-13 用户定案: 机械臂
                # 把粉桶从收集工位取回中转A托盘时**不翻桶**, 示教点才是真的)。
                # _last_alignment_mm 必须显式清零 —— 它只在 _align_to_cad 的成功路径末尾
                # 被写, 不清就会把**上一次落位**的值泄漏进 _record_dock_residual。
                self._last_alignment_mm = 0.0
            # dock 局部系的父级也要摆到播放态: ACTUATOR_PS_ROTATE 自己就骑在 9X 滑车上,
            # 建模位父系烤出的 dock 局部值同样错一整段滑车行程
            parent_world = self._posed_world(destination["parent"])
            local = np.linalg.inv(parent_world) @ world
            body["dock"] = _dock_of(local, self._node_scale(carried["node"]))
            if destination["kind"] != "tray" and destination["id"] != carried["id"]:
                swap_dock = _dock_of(
                    local @ self._instance_frame_map(carried, destination),
                    self._node_scale(destination["node"]))
            self._record_dock_residual(seat_key, destination, world, mount @ np.linalg.inv(
                self.posture.mount_world(joints_deg=self._pick_joints,
                                        rail_mm=self._pick_rail)))
        # 落进 state=false 的父托盘 = 连件带盘消失整个落位补间(detach 事件取步骤的 at,
        # 不是 at+dur)。父托盘的点亮因此必须在 t=0, 不能跟在补间后面。
        if destination["kind"] != "tray":
            self._intro_parent(destination["parent"])
        self.emit_follow("载荷落位", 0.45, {"detach": body})

        # 实例交换: 源实例与目的实例是两个 CAD 节点(同一块板在货架与中转各有一份几何)。
        if destination["id"] != carried["id"]:
            if swap_dock is not None:
                # 单件: 先把目的实例摆到"源实例刚落到的那个几何位姿", 再显示它。
                # 不做这一步, 交换那一帧就是一次肉眼可见的瞬移 —— 实测(2026-08-13, 按共享
                # 唯一 mesh 逐子件量): 收集工位那只粉桶 → 中转A托盘 角点跳 125.3mm(形心
                # 97.5mm, 整只桶端对端翻个儿), 刮板桶 → 收集工位桶 跳 35.7mm(绕桶轴自旋
                # 180°, 吹气头甩到另一侧)。跳变全部来自**两份 CAD 拷贝各自的子件局部帧
                # 不同**, 不是标定残差 —— 同姿态建模的收集器板只跳 2.6mm 就是对照组。
                # snap=true: 这不是一段落位轨迹, 而是"把另一份同件摆到同一处"的瞬时声明,
                # 走磁吸补间既没有物理对应物又会触发 10mm 落位阈值误报。
                self.emit_follow("目的实例就位", 0.0, {"detach": {
                    "id": destination["id"], "parent": destination["parent"],
                    "dock": swap_dock, "snap": True}})
            self.emit_follow("隐藏源实例", 0.0, {"state": {"id": carried["id"], "value": False}})
            self.emit_follow("显示目的实例", 0.0, {"state": {"id": destination["id"], "value": True}})
            for item in self.ledger.items_of(destination["id"]):
                self.emit_follow(f"{item} 显示", 0.0, {"state": {"id": item, "value": True}})
            # 目的实例是**放件放出来的**, 记进 _intro_seen: 复合流程(collect_cycle)后段
            # 再取它时, _intro_payload 不得再补 t=0 起手式 —— 否则收集工位的瓶/桶从片段
            # 一开始就被预亮, 与源头那份同件重影, 观感即"工位上凭空常驻一只虚空粉桶"。
            self._intro_seen.add(destination["id"])
            for item in self.ledger.items_of(destination["id"]):
                self._intro_seen.add(item)
        self._in_gripper = None

    def _actuator_value_of(self, actuator_id: str) -> float:
        """执行器当前值: 已发步值 → PhaseEntry 起手态 → MECHANISM_HOME(rigged 全覆盖)。"""
        if actuator_id in self.actuator_value:
            return self.actuator_value[actuator_id]
        if actuator_id in self.home_mechanism_overrides:
            return float(self.home_mechanism_overrides[actuator_id])
        entry = MECHANISM_HOME.get(actuator_id)
        if entry is None:
            raise CompileError(f"执行器 {actuator_id} 不在 MECHANISM_HOME —— rigged 集漂了")
        return float(entry[0])

    def _actuator_overrides_for(self, path: str) -> dict[int, np.ndarray]:
        """该节点**自身及祖先链**上的执行器覆盖(骑机构的站座要先把机构摆到播放态)。

        自身必须算进去: _put_payload 拿 `_posed_world(destination["parent"])` 求 dock 的
        局部系, 而单件的目的父级往往**就是那只气缸节点本身**(收集瓶的父级就是
        ACTUATOR_COL_EXTEND)。只收严格祖先时它自己的行程被漏掉 —— 编译器按缩回位烤
        dock, 前端却把 dock 挂在伸出位的节点下, 落点整整差一个行程。2026-08-07 实测:
        收集瓶落位差 80.00mm(PB10x80 全行程), 前端报"距落位目标 85.1mm"。
        """
        if self.scene is None or self.posture is None:
            return {}
        try:
            index = self.scene.index_of(path)
        except KeyError:
            return {}
        chain: set[int] = {index}
        cursor = self.scene.parent.get(index)
        while cursor is not None:
            chain.add(cursor)
            cursor = self.scene.parent.get(cursor)
        result: dict[int, np.ndarray] = {}
        for spec in self.manifest.get("actuators") or []:
            node = spec.get("node") or spec.get("glbNode")
            if not node:
                continue
            try:
                spec_index = self.scene.index_of(str(node))
            except KeyError:
                continue
            if spec_index not in chain:
                continue
            result.update(self.posture.actuator_override(
                spec, self._actuator_value_of(str(spec["id"]))))
        for spec in self.manifest.get("linkages") or []:
            for member in spec.get("members") or []:
                node = member.get("node")
                if not node:
                    continue
                try:
                    member_index = self.scene.index_of(str(node))
                except KeyError:
                    continue
                if member_index in chain:
                    raise CompileError(
                        f"载荷 {path} 骑在夹爪联动组 {spec.get('id')} 的指上 —— 未实现的姿态账")
        return result

    def _posed_world(self, path: str) -> np.ndarray:
        """播放态节点世界位姿: 基础层级 + 已跟踪工位轴 + 载荷祖先执行器全部摆到位。

        此前取源/目的姿态用裸 world_matrix: STA_SCRAPE_HOLDER 骑 9X 滑车(home 335 vs
        GLB 基位 −48.67), 烤出的夹持变换在闭合轴上错 **383.67mm** 而全程零报错 ——
        前端磁吸的 100mm 闸只拦它那半边(2026-08-07 实测; 昨日 75.2mm dock 告警是尾巴)。
        TOOL_MOUNT 的 mount_world 不经此路: 它只受关节/地轨驱动, 本就带覆盖。
        """
        axes = {axis_id: mm for axis_id, mm in self.axis_mm.items()
                if axis_id != "axis_11y" and axis_id in self._rigged_axis_ids}
        overrides = self.posture.overrides(
            joints_deg=self.current_joints, rail_mm=self.current_rail_mm, axes_mm=axes)
        overrides.update(self._actuator_overrides_for(path))
        return self.scene.world_matrix(path, overrides)

    def _node_scale(self, path: str) -> np.ndarray:
        """节点自身的 scale(GLB 声明值)。dock 反解要按它除, 见 _dock_of。"""
        node = self.scene.nodes[self.scene.index_of(path)]
        return np.asarray(node.get("scale") or [1.0, 1.0, 1.0], dtype=float)

    def _instance_mesh_frames(self, path: str) -> dict[int, np.ndarray]:
        """载荷子树里**唯一出现**的网格 -> 该网格节点相对载荷节点的局部矩阵。

        用途见 _instance_frame_map。只收唯一出现的网格: 一只托盘下挂着 6 只同款瓶子,
        它们共用同一个 mesh, 收进来就无从判断源侧的第几只该对上目的侧的第几只 ——
        实测拿它们乱配会把孔距(154mm)当成姿态差。
        """
        root = self.scene.index_of(path)
        found: dict[int, list[np.ndarray]] = {}
        stack: list[tuple[int, np.ndarray]] = [(root, np.eye(4))]
        while stack:
            index, upstream = stack.pop()
            # 根自身的局部矩阵**不算进去**: 要的是"相对载荷节点"的帧, 载荷节点本身的
            # 位姿正是待求量。
            local = upstream if index == root else upstream @ self.scene.local_matrix(index)
            mesh = self.scene.nodes[index].get("mesh")
            if mesh is not None:
                found.setdefault(int(mesh), []).append(local)
            for child in self.scene.nodes[index].get("children") or []:
                stack.append((int(child), local))
        return {mesh: mats[0] for mesh, mats in found.items() if len(mats) == 1}

    def _instance_frame_map(self, carried: dict, destination: dict) -> np.ndarray:
        """源实例帧 -> 目的实例帧的刚体映射 Ms·Md⁻¹。

        为什么需要: 同一个零件在 CAD 里有两份拷贝(刮板夹具上那只粉桶 与 收集工位那只),
        两份的**子件局部帧并不一致** —— 实测差到整整 180°。于是"把源实例摆在 X 处"与
        "把目的实例摆在 X 处"根本不是同一个画面。要让实例交换看不出来, 必须把目的节点
        摆到 `落位位姿 @ Ms·Md⁻¹` 上, 而不是它自己的 CAD 位姿。

        对应关系只能按 **mesh 索引**认: 两份拷贝的叶名不同(INV_STAGING_B_ITEM_1 下挂的是
        `样品瓶-1.0xx`, 收集工位那份直接叫 `样品瓶-2`), 名字对不上; 而两份共享同一批 mesh。

        Raises:
            CompileError: 没有共享的唯一网格, 或各网格解出的映射不一致(两份拷贝不全等,
                说明模型坏了 —— 不许挑一个用)。
        """
        source = self._instance_mesh_frames(carried["node"])
        target = self._instance_mesh_frames(destination["node"])
        shared = sorted(set(source) & set(target))
        if not shared:
            raise CompileError(
                f"载荷 {carried['id']} -> {destination['id']} 没有共享的唯一网格 —— "
                "实例交换算不出保姿态的落位。两份 CAD 拷贝的网格不同源, 检查 03 步的"
                "合并保护(join_static_per_station)是否把其中一份并进了静态块")
        maps = [source[mesh] @ np.linalg.inv(target[mesh]) for mesh in shared]
        spread = max(float(np.max(np.abs(matrix - maps[0]))) for matrix in maps)
        if spread > INSTANCE_FRAME_TOLERANCE:
            raise CompileError(
                f"载荷 {carried['id']} -> {destination['id']} 的实例帧映射不自洽: "
                f"{len(shared)} 个共享网格解出的映射最大离散 {spread:.3e} > "
                f"{INSTANCE_FRAME_TOLERANCE:.0e} —— 两份 CAD 拷贝不全等")
        return maps[0]

    def _grab_corrected(self, record: dict, transform: np.ndarray) -> np.ndarray:
        """把 as-is 夹持变换按抓取锚点做位置修正 —— 与 MachineStateDriver.attach 磁吸**逐字同式**。

        单件(kind=item)带 mountLocal.position + grabLocal 时: 让件的抓取特征点(瓶=瓶颈
        中点, 收集器=注射器桶身)落到四销笼锚点上, freeAxes 上的分量放手(长度轴咬哪段由
        示教点决定, 2026-08-05 定案; 桶身类连销轴也放开)。只动平移, 姿态保留。
        两端不同式的表现: 播放期磁吸把件挪到锚点, 放件时刻烤死的 dock 还在 as-is 位姿 ——
        件硬弹回 + 前端"clip 的 dock 与实际取料位姿不同源"误告警(2026-08-06 实测 58.8mm)。
        """
        mount_local = record.get("mountLocal") or {}
        anchor = mount_local.get("position")
        grab_local = record.get("grabLocal")
        if record.get("kind") != "item" or not anchor or not grab_local:
            return transform
        anchor = np.asarray(anchor, dtype=float)
        feature = (transform @ np.append(np.asarray(grab_local, dtype=float), 1.0))[:3]
        shift = anchor - feature
        for axis in mount_local.get("freeAxes") or []:
            axis = np.asarray(axis, dtype=float)
            norm = float(np.linalg.norm(axis))
            if norm < 1e-9:
                continue
            axis = axis / norm
            shift = shift - axis * float(shift @ axis)
        travel_mm = float(np.linalg.norm(shift)) * 1000.0
        if travel_mm > PAYLOAD_GRAB_MAX_TRAVEL_MM:
            raise CompileError(
                f"载荷 {record.get('id')} 抓取修正 {travel_mm:.1f}mm > "
                f"{PAYLOAD_GRAB_MAX_TRAVEL_MM:.0f}mm —— 源姿态账坏了(轴/机构没摆到位?)。"
                f"分量(mount 系 mm) {[round(float(v) * 1000.0, 1) for v in shift]}; "
                f"axis_mm {sorted((k, round(v, 1)) for k, v in self.axis_mm.items())}; "
                f"actuators {sorted(self.actuator_value.items())}")
        corrected = transform.copy()
        corrected[:3, 3] += shift
        return corrected

    def _align_to_cad(self, world: np.ndarray, destination: dict) -> np.ndarray:
        """把示教点推算出来的落位, 平移校正到 CAD 目的地的几何位置上。**只服务整板**。

        为什么只校正**平移**不动姿态: 姿态是机器人真实放料的朝向, 由示教点决定, 那是
        物理事实; 而平移上的 6~23 mm 是示教坐标系与 CAD 坐标系之间的标定残差(实测值,
        见 dockResiduals)。把残差吃在落位补间里, 托盘就正好坐进 CAD 的托盘位。

        ⚠ 2026-08-13 起**单件不再走这条路**(_put_payload 按 kind 分流)。两条理由:
          1. 单件的目的地 CAD 摆放不是落位真源 —— 用户定案"机械臂把粉桶从收集工位取回
             中转A 时不翻桶", 而中转A 那六只桶的 CAD 摆放是正立的, 差整整 180°;
          2. 只校平移不校姿态, 挡不住实例交换那一帧的姿态跳变(实测 35.7~125.3mm), 单件
             改由 _instance_frame_map 把目的实例摆到"件刚落到的那个几何位姿"上, 从构造上
             就没有跳变可言, 不需要也不该再往 CAD 拉。
        整板保留: 它的目的地有可复核的 CAD 座位(dockResiduals 门禁 + 孔序看门狗)。

        没有几何参考帧(payload_frames 未提供 / 该载荷无网格)时原样返回 —— 不猜。
        """
        frames = self.payload_frames or {}
        # 先复位: 它只在成功路径末尾被写, 早退会让**上一次落位**的值泄漏进
        # _record_dock_residual 的 alignment_mm —— 那份残差是给人排查用的, 串了值比没有更糟。
        self._last_alignment_mm = 0.0
        source_id = self._carried_node.rsplit("/", 1)[-1]
        source_frame = frames.get(source_id)
        dest_frame = frames.get(destination["id"])
        if source_frame is None or dest_frame is None:
            return world
        source_center = np.asarray(source_frame["localCenter"], dtype=float)
        dest_center = np.asarray(dest_frame["localCenter"], dtype=float)
        predicted = (world @ np.append(source_center, 1.0))[:3]
        target = (self._posed_world(destination["node"])
                  @ np.append(dest_center, 1.0))[:3]
        aligned = world.copy()
        aligned[:3, 3] = world[:3, 3] + (target - predicted)
        self._last_alignment_mm = float(np.linalg.norm(target - predicted) * 1000.0)
        return aligned

    def _record_dock_residual(self, seat_key: str, destination: dict, world: np.ndarray,
                              carry: np.ndarray) -> None:
        """把"示教点推算的落位"与"CAD 目的地实测"比一比, 存下残差供门禁判定。

        这是一条**可证伪的几何断言**(与 blender_clean._check_dock_frames 同一路数):
        示教点与 CAD 若同源, 整板落位就该落在 CAD 托盘位上; 差得多说明两套坐标不同源,
        那么单件那几条"没有 CAD 可比"的路线也不能信。
        """
        cad = self._posed_world(destination["node"])
        frames = self.payload_frames or {}
        source_frame = frames.get(self._carried_node.rsplit("/", 1)[-1])
        dest_frame = frames.get(destination["id"])
        if source_frame is not None and dest_frame is not None:
            predicted = (world @ np.append(np.asarray(source_frame["localCenter"]), 1.0))[:3]
            target = (cad @ np.append(np.asarray(dest_frame["localCenter"]), 1.0))[:3]
            position_mm = float(np.linalg.norm(predicted - target) * 1000.0)
        else:
            position_mm = float("nan")
        self.dock_residuals.append({
            "seat": seat_key,
            "payload": destination["id"],
            "position_mm": round(position_mm, 4),
            "alignment_mm": round(self._last_alignment_mm, 4),
            "source": self._carried_node,
            "carry": [round(float(v), 9) for v in carry.reshape(-1)],
        })

    def _close_value_for(self, record: dict) -> float:
        """载荷的夹持闭合值。

        逐件值(fit_item_grips 唯一真源, 经 manifest payload.closeValue 透传):
        瓶颈 = 销面贴颈 0.2543, 粉桶 = 摇篮同心 0.817(2026-08-07 定案 —— rig_map
        holdValue 0.101 是"瓶身贴销"的旧标定, 用在粉桶上弧臂只动 1.26mm 离桶 ~9mm,
        即用户报障"闭合离外径差很多"的一半病根, 另一半是锚点见 _grab_corrected)。
        无逐件值的载荷(整板托盘/plate96)**显式**回落 manifest holdValue —— 与旧行为
        逐字节一致; 有 grabFeature 却缺 closeValue 一律硬死, 不许静默退旧值。
        """
        close = record.get("closeValue")
        if close is not None:
            close = float(close)
            linkage = next((item for item in self.manifest.get("linkages") or []
                            if item.get("id") == record["grip"]), {})
            limit = float((linkage.get("inputRange") or [0, 1])[1])
            if not 0.0 < close <= limit:
                raise CompileError(
                    f"载荷 {record['id']} 的 closeValue {close} 越界 (0,{limit}] —— grips 数据坏了")
            return close
        if record.get("grabFeature"):
            raise CompileError(
                f"载荷 {record['id']} 有 grabFeature={record['grabFeature']} 却缺 closeValue "
                "—— gen_twin_manifest 白名单漏收或 fit_item_grips 未重跑")
        return _hold_value_of(self.manifest, record["grip"])

    def _gripper_target(self, gripper_id: str, closing: bool) -> float:
        """夹爪开度三态 + 逐件夹持值。与前端 TwinBindings._updateMechanisms 的三态同构:

            0                        = 张开 (GLB 基准位)
            _close_value_for(载荷)   = 夹住载荷 (逐件: 瓶颈 0.2543 / 粉桶 0.817 /
                                       无逐件值回落 holdValue —— 实时/近似链因拿不到
                                       载荷身份, 有意停留在 holdValue 兜底层)
            满行程                   = 空爪紧闭 (卸爪前收爪)

        真源: 逐件值出自 fit_item_grips(经 manifest payload), 兜底与满行程实读 manifest
        linkage, 缺就硬失败。

        ⚠ 2026-08-05 之前这里是一个 property, 在 `self.transfer is None` (即全部 flow.*
          片段) 时恒返回 0.0 —— 而 0.0 正是"张开"。于是"夹爪张开"与"夹爪夹持"两步发一模一样
          的值: 270 个片段里 103 个"夹爪夹持"有 79 个夹的是空气, 小夹爪 46 个合爪步骤无一
          会动。全程零报错、零日志, 时间轴上那一步还照样占 0.4 秒。

        Args:
            gripper_id: 联动组 id (rob_grip_plate96 / rob_grip_vial)
            closing: 本次是合爪还是张开

        Returns:
            归一化开度
        """
        if not closing:
            return 0.0
        if self._closing_on_payload():
            # 座位取自 _script_stack 顶帧(与 _closing_on_payload 同一判据位, 不用
            # _seat_stack —— 两栈会分叉, 见 _script_stack 的注)
            seat = self._script_stack[-1][1]
            record = self.ledger.require(seat[0])
            if record["grip"] != gripper_id:
                raise CompileError(
                    f"合爪 {gripper_id} 但座位 {seat[0]} 的载荷声明 grip={record['grip']} "
                    "—— 工具/座位错配")
            return self._close_value_for(record)
        return _empty_close_value_of(self.manifest, gripper_id)

    def _closing_on_payload(self) -> bool:
        """这次合爪是"夹住载荷"还是"空爪紧闭"? 判最内层脚本帧的角色, 理由见 _script_stack。"""
        if not self._script_stack:
            return False           # 顶层 operation 正文里的合爪: 没有取放语义, 按空爪算
        _name, seat = self._script_stack[-1]
        return seat is not None and seat[1] == "pick"


# --------------------------------------------------------------------------- #
# 转移路线
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class TransferSpec:
    """一条可编译的转移路线(路线 + 参数 = 一个片段)。"""

    clip_name: str
    label: str
    operation: str
    inputs: dict[str, Any]
    kind: str
    source_seat: str
    dest_seat: str
    tool: int
    #: 2026-08-05 起夹爪开度不再由路线携带 —— ClipBuilder._gripper_target 直接从 manifest
    #: 实读三态。留一份在路线上就是留第二个真源, 而 flow.* 片段根本没有路线可携带
    #: (那正是"79 个夹爪夹持发张开值"的成因)。
    dock_poses: dict[str, dict] | None = None
    #: 本段开始时机器人**已经持着板**, 板从这个落点取来的。
    #: 只用于"取板动作的后半段"(robot_*_pick_exit): 那半段里没有任何吸/放动作,
    #: 落点无从由 PLC_POINT_SLOT 反推, 只能由路线显式声明 —— 与 PLATE_VISION_ASSUMPTION
    #: 同一套办法: 编译期拿不到的运行期事实, 写成看得见的假设, 而不是编一个默认值。
    carry_in: str = ""
    #: 本段**以持件结束**是路线自身的性质而不是缺陷(取放脚本的前半段就是这样)。
    #: 与 carry_in 同一条纪律: 编译期拿不到的运行期事实写成看得见的声明, 而不是把
    #: 收尾门禁整个关掉 —— 关掉之后"复合流程被改到取放不配对"就再没人拦得住。
    ends_holding: bool = False
    #: 本段开始时地轨必须在哪个站位。取放动作的后半段(*_pick_exit)自己不移轨 —— 它靠
    #: 前半段把轨送到位。不声明的话编译期会拿 Home 的轨位配取料点的关节角, 差出整整
    #: 一个站位(实测 ~330mm), 板与吸盘的相对关系就全错了。
    rail_slot: int = 0


#: 整板转移的四条路线。参数域是货架库位 1-6, 与上位机 slot_id 逐字一致。
TRAY_ROUTES = (
    ("collector", "to_staging", "transfer_collector_rack_to_staging_a",
     "收集器组 货架→中转A", "rack:collector:{slot}", "staging:staging-a"),
    ("collector", "to_rack", "transfer_collector_staging_a_to_rack",
     "收集器组 中转A→货架", "staging:staging-a", "rack:collector:{slot}"),
    ("bottle", "to_staging", "transfer_bottle_rack_to_staging_b",
     "瓶组 货架→中转B", "rack:bottle:{slot}", "staging:staging-b"),
    ("bottle", "to_rack", "transfer_bottle_staging_b_to_rack",
     "瓶组 中转B→货架", "staging:staging-b", "rack:bottle:{slot}"),
)


def tray_transfer_specs(manifest: dict, dock_poses: dict | None = None) -> list[TransferSpec]:
    """列出全部整板转移片段(4 条路线 × 6 个库位 = 24 个)。"""
    # 只作**开编前的预检**: 值本身由 ClipBuilder._gripper_target 现读, 这里提前撞一次是为了
    # 让"manifest 缺 holdValue"在列路线时就报, 而不是编到一半才报。
    _hold_value_of(manifest, "rob_grip_plate96")
    specs = []
    for kind, direction, operation, label, source, dest in TRAY_ROUTES:
        for slot in range(1, 7):
            specs.append(TransferSpec(
                clip_name=f"transfer.tray.{kind}.{direction}.slot{slot}",
                label=f"{label} · 库位{slot}",
                operation=operation,
                inputs={"slot_id": slot},
                kind=kind,
                source_seat=source.format(slot=slot),
                dest_seat=dest.format(slot=slot),
                tool=2,
                dock_poses=dock_poses or {},
            ))
    return specs


# --------------------------------------------------------------------------- #
# 薄层板路线(吸盘)
# --------------------------------------------------------------------------- #

#: 薄层色谱板的全部搬运路线。板全程由 1 号刀"玻璃吸盘"取放, 与整板转移(2 号大夹爪)
#: 是两套机构。这些路线合起来就是板的完整旅程:
#:   上料仓 → 点样座 → 刮板台(展开前拍照) → 展缸 → 刮板台(展开后拍照+刮取) → 废板仓
#: 名字里的 station_id / tank_id 与上位机 operation 的入参逐字一致。
#: 视觉纠偏结果的**显式假设**: 识别成功、零偏移。
#: 编译器第 3 条纪律是"不猜运行期状态", 所以这个不能由编译器编一个默认值 —— 它必须
#: 作为路线参数显式写在这里, 并随片段的 operation.inputs 一起落进 YAML, 让人看得见。
#: 取零偏移的理由: 片段是**标称轨迹**演示, 而 dx/dy/Δθ 是每次拍照才有的实测量;
#: 用任何非零值都等于伪造一次并不存在的纠偏。识别失败那条分支是 HITL 人工门, 无动画价值。
PLATE_VISION_ASSUMPTION = {
    "voff_rz": {"valid": True, "dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0, "err": 0},
    "voff_xy": {"valid": True, "dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0, "err": 0},
}

#: 换板决策的**运行期出参**显式假设。与 PLATE_VISION_ASSUMPTION 逐字同一条纪律:
#: 编译期拿不到的运行期事实写成看得见的声明, 而不是编一个默认值。
#:
#: material.plan_staging 读物料账本给出动作码与库位, 编译期没有真值。不给的话它们停在
#: 脚本声明的 default(rack_slot=0), 而 0 让 robot_group_rack_pick 的 12 支
#: (rack_id, slot_id) 分支**一支都不命中** —— select_branch 返回空 else, 整段取料被
#: **静默跳过**、片段照样落盘。2026-08-06 实测: flow.ensure_bottle_staged 现有 35 步里
#: 没有任何取料动作, 而演示栏一直标着"精编译"。
#:
#: 取 SWAP 是因为它是三支里最长的一支(先把耗尽的板送回货架, 再取新板), 演出来的动作最完整。
STAGING_PLAN_ASSUMPTION = {"op": "SWAP", "rack_slot": 1, "old_rack_slot": 1, "hole": 1}

def mechanism_home_of(manifest: dict) -> tuple[dict[str, float], dict[str, float]]:
    """全部 rigged 机构的起手态, 写进片段的 home.actuators / home.linkages。

    枚举源是 manifest 的 actuators[] 与 linkages[] —— 那两张表**就是** rigged 集合。
    刻意不从 realtime.mechanisms 枚举: 那里还有几十条 rigged:false 的 data-only 条目
    (sta_powder_locator / col_bottle_locator 等), 给它们建通道等于建一堆永远写不进几何的
    空通道(前端 setActuator 查不到条目就返回 false), 还会让 home 的键集与 manifest 的机构
    集对不上 —— 而"键集恰好相等"正是产物门禁判"home 漏机构"的判据。

    模块级而不是 ClipBuilder 方法: 换刀片段走的是 sync_ptlc_robot 里那个不建 ClipBuilder
    的迷你编译器, 它一样要写 home(那两条片段在演示页照播)。

    Args:
        manifest: device-manifest
    Returns:
        (actuators, linkages) 两张 {id: 起手值}
    Raises:
        CompileError: manifest 里有 rigged 机构没在 MECHANISM_HOME 里声明。宁可编不出来 ——
            漏一条的表现是那个机构在 270 个片段里都停在 CAD 基位, 而画面看着完全正常
            (这正是 2026-08-06 之前 col_lift / col_clamp 的处境)。
    """
    out: dict[str, dict[str, float]] = {"actuators": {}, "linkages": {}}
    missing: list[str] = []
    for section in ("actuators", "linkages"):
        for item in manifest.get(section) or []:
            mechanism_id = str(item.get("id") or "")
            if not mechanism_id:
                continue
            declared = MECHANISM_HOME.get(mechanism_id)
            if declared is None:
                missing.append(mechanism_id)
                continue
            out[section][mechanism_id] = float(declared[0])
    if missing:
        raise CompileError(
            f"manifest 里的机构 {sorted(missing)} 没在 clip_compiler.MECHANISM_HOME 里声明起手态"
            " —— 每条都要写明出处(PLC 初始化动作码 / rig_map 的 gap_check 断言 / 手写片段的"
            "头注释), 不许拍脑袋填 0")
    return out["actuators"], out["linkages"]


#: 需要上面那条假设的脚本。**必须强制覆盖**而不是走 builder.assumptions ——
#: 那条通道的判据是 `key in declared and key not in child`, 而 default_bindings 已经把
#: 带 default 的 `io: var` 收进 child, 于是永远注不进去。
STAGING_PLAN_SCRIPTS = frozenset({"ensure_bottle_staged", "ensure_collector_staged"})

PLATE_ROUTES = (
    ("plate.feed_pick", "上料仓取板", "robot_feed_lift_pick_enter", {}),
    ("plate.feed_exit", "持板退出料仓", "robot_feed_lift_pick_exit", {}, "feedlift", 1),
    ("plate.spot_put", "放板到点样座(含视觉纠偏)", "robot_suction_put",
     {"station_id": "spotting", **PLATE_VISION_ASSUMPTION}),
    ("plate.spot_pick", "从点样座取板", "robot_suction_pick", {"station_id": "spotting"}),
    ("plate.scrape_put", "放板到刮板台", "robot_suction_put", {"station_id": "scrape"}),
    ("plate.scrape_pick", "从刮板台取板", "robot_suction_pick", {"station_id": "scrape"}),
    ("plate.waste_put", "废板入下料仓", "robot_suction_put", {"station_id": "waste"}),
)

#: 展缸进出板: 8 个缸各一条。
PLATE_TANK_ROUTES = (
    ("plate.tank{n}_put", "板入展缸{n}", "robot_tank_put", "tank_id"),
    ("plate.tank{n}_pick", "板出展缸{n}", "robot_tank_pick", "tank_id"),
)

#: **流程级**片段: 上位机工位阶段脚本(operation 的 ui.role = station_phase), 一段就是
#: 界面上一个可点的按钮 —— "上样-上料""拍照刮板-板上料"这一层。
#:
#: 与上面那些 `robot_*` 原子路线的区别不只是粒度: 流程段自带**工位联动**(升降上料取板、
#: 定位气缸夹紧、缸盖开合、地轨就位), 所以片段里能看见的不止机械臂那一条手臂在动。
#: 编译器天然支持 —— `run_body` 本来就会内联 `run_script`, 原子路线只是被嵌进来而已。
PLATE_FLOW_ROUTES = (
    ("plate.flow.sampling_load", "上样-上料", "sampling_load", {}),
    ("plate.flow.sampling_unload", "上样-下料", "sampling_unload", {}),
    ("plate.flow.photoscrape_load", "拍照刮板-板上料", "photoscrape_plate_load", {}),
    ("plate.flow.photoscrape_unload", "拍照刮板-下料", "photoscrape_unload", {}),
)

#: 带缸号参数的流程段。缸号进 `nameTemplate`, 界面上就是一个下拉框(见 _clip_families)。
PLATE_FLOW_TANK_ROUTES = (
    ("plate.flow.develop_load.tank{n}", "展开-上料 · {n}号缸", "develop_load", "tank"),
    ("plate.flow.develop_unload.tank{n}", "展开-下料 · {n}号缸", "develop_unload", "tank"),
)


def plate_route_specs() -> list[TransferSpec]:
    """列出全部薄层板片段: 23 条原子搬运路线 + 4 条流程段 + 2 × 8 缸参数化流程段。

    这里复用 TransferSpec 的字段承载"路线 + 参数", 但 **source_seat/dest_seat 留空**:
    板不是 GLB 里的库存节点(它是前端按 2mm 玻璃 + 硅胶程序化生成的), 走不了
    PayloadLedger 那套整板载荷交接。板的行踪改由编译期的 PLATE_POINT_SLOT 静态定出,
    以 `plate` 原语写进片段(见 ClipBuilder._plate_transfer)。
    """
    specs = []
    for clip_name, label, operation, inputs, *rest in PLATE_ROUTES:
        specs.append(TransferSpec(
            clip_name=clip_name, label=label, operation=operation,
            inputs=dict(inputs), kind="plate", source_seat="", dest_seat="", tool=1,
            carry_in=rest[0] if rest else "", rail_slot=rest[1] if len(rest) > 1 else 0,
        ))
    for template, label, operation, key in PLATE_TANK_ROUTES:
        for tank in range(1, 9):
            specs.append(TransferSpec(
                clip_name=template.format(n=tank), label=label.format(n=tank),
                operation=operation, inputs={key: tank},
                kind="plate", source_seat="", dest_seat="", tool=1,
            ))
    for clip_name, label, operation, inputs in PLATE_FLOW_ROUTES:
        specs.append(TransferSpec(
            clip_name=clip_name, label=label, operation=operation,
            inputs=dict(inputs), kind="plate-flow", source_seat="", dest_seat="", tool=1,
        ))
    for template, label, operation, key in PLATE_FLOW_TANK_ROUTES:
        for tank in range(1, 9):
            specs.append(TransferSpec(
                clip_name=template.format(n=tank), label=label.format(n=tank),
                operation=operation, inputs={key: tank},
                kind="plate-flow", source_seat="", dest_seat="", tool=1,
            ))
    return specs


def rail_calib_stamp(builder) -> dict | None:
    """片段的地轨标定指纹 —— 写进 source 段, 让片段自述"我是按哪套标定烘的"。

    为什么非记不可: 片段里的 `axis.to_mm` 是运行期按 manifest 换算的, 改标定就跟着变;
    但机械臂与载荷的落位是**编译期烘死的**(见 ClipBuilder._put_payload → RobotPosture.
    mount_world, 那条链读的正是 axis_11y 的 zeroOffsetMm/sign/rangeMm), 标完零点不重
    编译片段, dock 位姿与 moveL 轨迹就与新标定对不上, 而且不报任何错.
    既有的 referencePointHash 抓不到这件事 —— 它和 robot-points.json 出自同一次运行,
    永远自洽, 一起陈旧时照样全绿.

    三态(前端据此分档, 别把它们混成一个布尔):
      dict  —— 有烘焙落位, 且记下了当时的标定, 可比对;
      None  —— 本次编译没有场景(scene is None), 压根没烘任何落位, 无从陈旧;
      键缺失 —— 旧编译器的产物, 未标记, 一律当作"需重新编译"(不许默认判绿).
    """
    posture = getattr(builder, "posture", None)
    return posture.rail_fingerprint() if posture is not None else None


def operation_source_path(control_root: Path, name: str) -> str:
    """operation 在控制侧仓库里的相对路径(写进片段的 source 段, 供人回溯)。"""
    for folder in OPERATION_DIRS:
        if (control_root / "config" / "operation" / folder / f"{name}.yaml").is_file():
            return f"config/operation/{folder}/{name}.yaml"
    return f"config/operation/?/{name}.yaml"


def compile_plate_route(
    spec: TransferSpec,
    *,
    control_root: Path,
    registry,
    calibration: dict,
    manifest: dict,
    rail_slots: dict[int, float],
    scene: GlbScene | None = None,
    payload_frames: dict | None = None,
) -> dict:
    """把一条薄层板搬运路线 / 顶层流程编译成 ptlc.clip/v3 文档。

    与 compile_transfer 的差别在于**路线元数据**(flow_mode / carry_in / assumptions /
    plate 原语), 而**不在**载荷交接: 2026-08-06 起两条路都做交接。
    在那之前这里传 transfer=None, 而 emit_tool_action 拿它当交接的总闸 —— 于是全部
    flow.* 片段一次 attach 都没有, 演示页「转移」分组 44 个片段全是"虚空转运"。

    板(薄层色谱板)的显隐与跟手仍由 plate 原语 + 运行期 PlateBinding 负责, 与托盘/单件
    那套 attach/detach 是两条独立链路。

    Args:
        payload_frames: 载荷几何参考帧(generated/payload-poses.json 的 poses)。
            **必须传** —— 缺了它 _align_to_cad 拿不到帧直接原样返回, 落位停在示教点推算位、
            与 CAD 差 6~23mm, 紧接着的实例交换会肉眼可见地跳一下; 而 transfer.tray.*
            正是靠这条校正才不跳。同一条几何两条编译路径给不同结果就是新造一条分叉。

    Raises:
        CompileError: 任何编译期不确定性(未知动作、取不到的分支、落位残差超限)
    """
    builder = ClipBuilder(
        control_root=control_root, registry=registry, calibration=calibration,
        manifest=manifest, rail_slots=rail_slots, assume_tool=spec.tool, transfer=None,
        scene=scene, payload_frames=payload_frames, plate=True,
    )
    # 顶层工艺流程与转移片段走同一个编译器, 但对"决策外壳"的容忍度不同 —— 见
    # ClipBuilder.run_shell_instruction 的说明。kind 由 flow_discovery.to_transfer_spec 打。
    builder.flow_mode = spec.kind == "plate-flow"
    # 起手刀号来自 flow_discovery.infer_initial_tool(流程首个 robot_tool_ensure 的显式
    # 声明), 不再恒等于 1 —— 恒 1 的年代, 收集/刮板一族(起手就要 3 号小夹爪)会被编出
    # 一段真机上不存在的换刀 prologue + 地轨 168→500→168 空跑。
    tool_intro = {1: "起手·装吸盘", 2: "起手·装96孔板夹爪", 3: "起手·装小夹爪"}.get(
        spec.tool, f"起手·装{spec.tool}号刀")
    builder.emit(tool_intro, 0.0, {"tool": {"action": "lock", "id": TOOL_ASSET[spec.tool], "snap": True}})
    if builder.flow_mode and spec.tool != 1:
        builder.flow_notes.append(
            f"起手挂 {spec.tool} 号刀 —— 按流程首个 robot_tool_ensure(needed={spec.tool}) "
            "推断(flow_discovery.infer_initial_tool)")
    builder.carry_in = spec.carry_in
    builder.assumptions = dict(PLATE_VISION_ASSUMPTION)
    if spec.rail_slot:
        # 半段片段的地轨前置(见 TransferSpec.rail_slot); 必须早于 require_anchor 采纳起手姿态
        builder.emit_rail(spec.rail_slot)

    document = load_operation(control_root, spec.operation)
    bindings = default_bindings(document)
    bindings.update(spec.inputs)
    # robot_tool_ensure 读的是运行期工具号; 以"已是吸盘"消解该分支(真机由 robot_tool_ensure 保证)
    bindings.setdefault("needed", spec.tool)
    # 起手态**必须早于 run_operation**: 本段自己的排液动作要靠 tank_volume_ml 才知道起点
    # 是 60mL 而不是 0。晚一步, emit_tank_liquid 就已经按空缸把排液编成 `wait{}`、
    # 并打上"缸内已是空的"的标签了。
    entry_state = PHASE_ENTRY_STATE.get(spec.operation)
    if entry_state is not None:
        builder.seed_entry_state(entry_state, bindings)
    # 半程携带声明(见 STANDALONE_HALF_CARRY): 放的半程起手持件, 取的半程放行持件收尾
    half_carry = STANDALONE_HALF_CARRY.get(spec.operation)
    if half_carry == "starts_holding":
        builder.preload_payload(spec.operation, bindings)
    builder.run_operation(spec.operation, document, bindings)

    if not builder.steps:
        raise CompileError(f"{spec.clip_name} 没有生成任何步骤")
    if not builder.plate_intro and not builder.flow_mode:
        raise CompileError(
            f"{spec.clip_name} 全程没有吸/放动作, 路线也没有声明 carry_in —— "
            "那么这一段里那块板到底在哪就是猜的, 宁可不生成"
        )
    # 顶层流程里"全程没有吸/放动作"是常态而不是错误: robot_home_check、
    # robot_startup_check、collect_prepare 这些本来就不搬板。它们照编, 只是片段里没有
    # plate 原语 —— 与"板在哪是猜的"完全两回事(那种情形只出现在带板的半段路线里)。
    if (builder._in_gripper is not None and not spec.ends_holding
            and half_carry != "ends_holding"):
        raise CompileError(
            f"{spec.clip_name} 编译结束时载荷仍在爪里: {builder._in_gripper} —— "
            "若这一段本就以持件结束(取放脚本的前半段), 在路线上显式写 ends_holding=True "
            "或收进 STANDALONE_HALF_CARRY")
    # 起手式插在"装吸盘"之后: 各步都是 at:0 / dur:0, 不占时间也不移动后面的时间轴。
    # 载荷起手式排在板起手式之前 —— 两者都是 at:0, 顺序只影响可读性。
    builder.insert_steps(1, builder.payload_intro + builder.plate_intro)
    home_actuators, home_linkages = builder.mechanism_home()

    return {
        "schema": "ptlc.clip/v3",
        "name": spec.clip_name,
        "label": spec.label,
        "description": (
            "由 PointRegistry 与上位机 operation 编译; 禁止手工填写生产关节角。"
            f"显式假设: 本段开始时已挂 {spec.tool} 号刀, 机械臂在 P1 安全位。"
            "板的落点由编译期的取放基准点静态定出(见 clip_compiler.PLATE_POINT_SLOT), "
            "以 plate 原语写进片段; 实时页则由 PlateBinding 按调度器账本跟手, 两条链互不干涉。"
        ),
        "operation": {"name": spec.operation, "inputs": dict(spec.inputs)},
        "assumptions": {"vision": PLATE_VISION_ASSUMPTION},
        # 决策外壳被拍平的地方逐条随片段落盘: 看动画的人必须知道这条时间轴取了哪个分支、
        # 循环只演了第几轮, 否则会把它当成实况
        **({"flowNotes": builder.flow_notes} if builder.flow_notes else {}),
        "source": {
            "operation": operation_source_path(control_root, spec.operation),
            "referencePointHash": registry.source_sha256,
            "kinematicsCommit": calibration["kinematics_source"]["commit"],
            "calibrationVersion": calibration["version"],
            "railCalib": rail_calib_stamp(builder),
        },
        "home": {
            # 工位轴的起手声明(板托座骑在它们上面, 不摆到位板就画在建模位): 见 SEAT_AXES
            "axis_mm": {"axis_11y": builder.home_rail_mm, **builder.home_axis_mm},
            "joints_deg": list(builder.home_joints),
            # 机构起手态: 覆盖**全部** rigged 机构, 不只本片段驱动的那些 —— 见 MECHANISM_HOME。
            # 不声明的机构会停在 CAD 基位, 而那对 outputRange 降序的十条(col_lift/col_clamp/
            # 8 条缸盖)恰好是反的。
            "actuators": home_actuators,
            "linkages": home_linkages,
            # 展缸起手液量。不声明的后果**与轴相反**: MachineStateDriver.home() 会把 8 个缸
            # 一律 setLiquidMl(id, 0) 并隐藏液面盒, 于是不声明是**空缸**而不是满缸。
            # (这里原先写着"不声明就停在满缸"—— 那是 home() 落地清零之前的事实, 已作废;
            #  clipSchema.js 里那句同源的话一并订正过了。)
            #
            # 因此"本段起于满缸"必须显式说出来, 那正是 PHASE_ENTRY_STATE 的职责:
            # develop_load 全程一条液面动作都没有, 不播种就演成"把板放进空缸"。
            # 只在非空时写 —— 不含 develop 动作的一百多条片段产物逐字节不变, diff 干净。
            **({"liquid_ml": builder.home_liquid_ml} if builder.home_liquid_ml else {}),
            # 注射泵起手体积/阀位, 与 liquid_ml 同一条纪律: 只在片段真的驱了泵时写。
            # 不声明的后果与液面同向 —— home() 把泵清到 0mL/1号口, 而"上一动作停在气隙位"
            # 这类起手态必须显式声明, clipSchema 才会为它建通道。
            **({"pump_ml": builder.home_pump_ml} if builder.home_pump_ml else {}),
            **({"pump_port": builder.home_pump_port} if builder.home_pump_port else {}),
            # 粉桶起手粉量与洗脱色, 与 liquid_ml 同一条纪律(只在非空时写, diff 干净)。
            # 真源是 PHASE_ENTRY_STATE.powders 的声明式承接: 粉是**换实例**搬走的,
            # 算不出也不该算 —— 详见 PhaseEntry.powders 的字段注释。
            **({"powder_mm3": builder.home_powder_mm3} if builder.home_powder_mm3 else {}),
            **({"powder_tint": builder.home_powder_tint} if builder.home_powder_tint else {}),
        },
        "steps": builder.steps,
        "compiled": {
            "moveLTrajectories": builder.trajectories,
            "staleJointPoints": builder.stale_joint_points,
            "plateAnchorChecks": builder.plate_anchor_checks,
            # 驱过但没几何的机构: 门禁据此把"确实没几何"与"打错 id"分开
            "dataOnlyMechanisms": sorted(builder.data_only_mechanisms),
            # 痕迹几何声明(板 cm 帧, emit_scrape/emit_spot/emit_wet 写入)。只在非空时写
            # —— 与 home.liquid_ml 同款: 不含痕迹的两百多条片段产物逐字节不变, diff 干净。
            **({"scrapeRegions": builder.scrape_regions} if builder.scrape_regions else {}),
            **({"spotRegions": builder.spot_regions} if builder.spot_regions else {}),
            **({"wetRegions": builder.wet_regions} if builder.wet_regions else {}),
        },
    }


def _hold_value_of(manifest: dict, linkage_id: str) -> float:
    for linkage in manifest.get("linkages") or []:
        if linkage.get("id") == linkage_id:
            value = linkage.get("holdValue")
            if value is None:
                raise CompileError(f"夹爪 {linkage_id} 缺 holdValue —— 夹住载荷的开度不能猜")
            return float(value)
    raise CompileError(f"manifest 里没有夹爪联动组 {linkage_id}")


def _empty_close_value_of(manifest: dict, linkage_id: str) -> float:
    """空爪紧闭的开度 = 该联动组值域上界 (每指走完名义行程)。

    **不写 1.0 常量**: 值域不是天然 [0,1] —— col_clamp 的 outputRange 就是递减的,
    写死会在有人改值域那天安静地发一个越界值。与 _hold_value_of 同一条纪律: 实读 manifest,
    缺就硬失败。
    """
    for linkage in manifest.get("linkages") or []:
        if linkage.get("id") == linkage_id:
            span = linkage.get("inputRange")
            if not (isinstance(span, list) and len(span) == 2):
                raise CompileError(
                    f"夹爪 {linkage_id} 缺 inputRange —— 空爪紧闭的开度不能猜")
            return float(span[1])
    raise CompileError(f"manifest 里没有夹爪联动组 {linkage_id}")


def compile_transfer(
    spec: TransferSpec,
    *,
    control_root: Path,
    registry,
    calibration: dict,
    manifest: dict,
    rail_slots: dict[int, float],
    scene: GlbScene | None = None,
    payload_frames: dict | None = None,
) -> dict:
    """把一条转移路线编译成 ptlc.clip/v3 文档。

    Args:
        spec: 路线与参数
        control_root: 上位机仓库根(只读)
        registry: PointRegistry
        calibration: CR5 标定
        manifest: device-manifest(取载荷声明与夹爪 holdValue)
        rail_slots: 地轨站位表

    Returns:
        片段文档(可直接 yaml.safe_dump)

    Raises:
        CompileError: 任何编译期不确定性
    """
    builder = ClipBuilder(
        control_root=control_root, registry=registry, calibration=calibration,
        manifest=manifest, rail_slots=rail_slots, assume_tool=spec.tool, transfer=spec,
        scene=scene, payload_frames=payload_frames,
    )
    source = builder.ledger.require(spec.source_seat)
    builder.ledger.require(spec.dest_seat)

    # 起手式: 本段开始时刀已在腕上(真机由 robot_tool_ensure 保证; 这里以显式假设消解
    # 那个读运行期工具号的分支), 源托盘与它的耗材可见, 目的位空。
    builder.emit("起手·装刀", 0.0, {"tool": {"action": "lock", "id": TOOL_ASSET[spec.tool], "snap": True}})
    builder.emit_follow("显示源托盘", 0.0, {"state": {"id": source["id"], "value": True}})
    for item in builder.ledger.items_of(source["id"]):
        builder.emit_follow(f"{item} 显示", 0.0, {"state": {"id": item, "value": True}})
    # 源是孔件(hole:*)时 items_of 为空, 上面点亮的其实是单件自己 —— 还得点它的父托盘,
    # 否则父级 visible=false 压着, 开场依旧什么都看不见(与 _pick_payload 同病)。
    if source["kind"] != "tray":
        source_parent = source["parent"].rsplit("/", 1)[-1]
        if source_parent in builder.ledger.by_id:
            builder.emit_follow(f"{source_parent} 显示", 0.0,
                                {"state": {"id": source_parent, "value": True}})

    document = load_operation(control_root, spec.operation)
    bindings = default_bindings(document)
    bindings.update(spec.inputs)
    # robot_tool_ensure 读的是运行期工具号; 以"已是本段所需刀"消解该分支(= 真机 NONE 快路径)。
    bindings.setdefault("needed", spec.tool)
    builder.run_operation(spec.operation, document, bindings)

    if builder._in_gripper is not None:
        raise CompileError(f"{spec.clip_name} 编译结束时载荷仍在爪里: {builder._in_gripper}")
    if not builder.steps:
        raise CompileError(f"{spec.clip_name} 没有生成任何步骤")
    home_actuators, home_linkages = builder.mechanism_home()

    return {
        "schema": "ptlc.clip/v3",
        "name": spec.clip_name,
        "label": spec.label,
        "description": (
            "由 PointRegistry 与上位机 operation 编译; 禁止手工填写生产关节角。"
            f"显式假设: 本段开始时已挂 {spec.tool} 号刀(真机由 robot_tool_ensure 保证), "
            "机械臂在 P1 安全位。"
        ),
        "operation": {"name": spec.operation, "inputs": dict(spec.inputs)},
        "source": {
            "operation": f"config/operation/05_transfer/{spec.operation}.yaml",
            "referencePointHash": registry.source_sha256,
            "kinematicsCommit": calibration["kinematics_source"]["commit"],
            "calibrationVersion": calibration["version"],
            "railCalib": rail_calib_stamp(builder),
        },
        "home": {
            # 工位轴的起手声明(板托座骑在它们上面, 不摆到位板就画在建模位): 见 SEAT_AXES
            "axis_mm": {"axis_11y": builder.home_rail_mm, **builder.home_axis_mm},
            "joints_deg": list(builder.home_joints),
            # 见 compile_plate_route 同一处的说明
            "actuators": home_actuators,
            "linkages": home_linkages,
        },
        "steps": builder.steps,
        "compiled": {
            "moveLTrajectories": builder.trajectories,
            "staleJointPoints": builder.stale_joint_points,
            "dockResiduals": builder.dock_residuals,
            # 见 compile_plate_route 同一处的说明
            "dataOnlyMechanisms": sorted(builder.data_only_mechanisms),
        },
    }
