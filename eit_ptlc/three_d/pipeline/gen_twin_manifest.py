"""
功能: 生成 device-manifest.json —— 三维模型与上位机实时数据之间的唯一绑定契约.

数据来源(三方合流):
    1. 上位机配置(只读)  E:/eit_lab/pTLC_platformUI/eit_ptlc/config/
       - manual_points.yaml : 各工位的气缸与伺服轴清单(轴 id 与中文标签的权威来源)
       - actions/<组>/*.yaml : 动作目录(用于生成每个工位的动作前缀)
       - points/plc/*.yaml   : 各轴示教点与 limits —— 仅用于与 rig_map range_mm 的
         一致性校验(越界会被前端 clamp 冻住, 见 --strict-limits), 不写入 manifest
    2. rig_map.yaml       : 装配归属与轴的三维装配声明
    3. work/structure.json: Blender full 阶段导出的实际节点层级(含世界包围盒)

合并策略: 以生成结果为准, 但若已存在 manifest 且其中的字段是手工调过的
(相机机位/轴正负号/零位偏移), 则保留手工值 —— 这些是只能靠目视核对得出的量,
不应被每次重跑覆盖. 人工标记两种形制见 merge_preserving: 相机机位认字段内的
manual: true(实时页「保存视角」写入); 轴三项认条目上的 _manual_<字段> 标记,
后者当前无人使用 —— 标定值(sign/zero_offset_mm/range_mm)的唯一固化点是 rig_map.yaml.

用法:
    python gen_twin_manifest.py
    python gen_twin_manifest.py --check          # 只检查漂移, 不写文件(仍执行限位校验)
    python gen_twin_manifest.py --strict-limits  # 限位校验有警告时以非零退出
    python gen_twin_manifest.py --eit-root <上位机路径>

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 models/device-manifest.json)
"""

from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import math
import os
import re
import time

import numpy as np
import yaml

# 前端相机的垂直视场角(度), 需与 web/src/three-d/twin/scene/CameraRig.js 中的 fov 保持一致
CAMERA_FOV_DEG = 42.0

from common import ensure_dir, load_config, log, write_report
from pump_syringe_spec import PUMP_SYRINGE_ACTIONS  # noqa: F401  (再导出: 既有测试按本模块名 import)
from scene_kinematics import GlbScene

# 上位机仓库默认位置(只读)
DEFAULT_EIT_ROOT = os.environ.get("PTLC_CONTROL_ROOT", "")

# rig_map 的工位 id -> 上位机节点 id. 没有对应遥测节点的用 None.
# 这份映射也决定了前端点击工位时去哪个节点取状态.
STATION_LABELS = {
    "SAMPLING": "上样工站",
    "COLLECT": "收集工站",
    "DEVELOP": "展开工站",
    "PHOTOSCRAPE": "拍照刮板工站",
    "FEEDLIFT": "上下料位",
    "PUMP": "泵站",
    "RAIL": "地轨",
    "STAGINGA": "中转托盘位",
    "ROBOT": "机械臂",
    "FRAME": "机架与外罩",
    "RACK": "料架",
    "TOOLING": "工具站",
    "MISC": "其它",
}

# 健康度配色: 与前端 Effects/TwinBindings 共用
HEALTH_STYLES = {
    "ok": {"color": "#39d98a", "intensity": 3.0, "pulse": 0.0},
    "busy": {"color": "#f4b740", "intensity": 4.5, "pulse": 1.1},
    "error": {"color": "#ff5c5c", "intensity": 6.0, "pulse": 3.0},
    "offline": {"color": "#5a6472", "intensity": 0.3, "pulse": 0.0},
    "unknown": {"color": "#7b8aa5", "intensity": 1.0, "pulse": 0.0},
}

# 整机三色塔灯配色: 由 PLC 三色灯输出位经 signal_light 事件驱动, 整罩单色红>黄>绿.
# color 写进材质 emissive(基色 albedo 保持烘焙值不动); green 与管线 MAT_STATUS_LIGHT
# 同配方(#35d17a×2.5; GLB 内被 glTF 导出归一化为 ~43ff96×2.05, 接管仅轻微亮度差).
# off = 全灭(自发光归零, 剩浅色灯罩); stale = 断流未知态, 对齐 healthStyles.offline.
SIGNAL_LIGHT_STYLES = {
    "red": {"color": "#ff3b30", "intensity": 6.0, "pulse": 0.0},
    "yellow": {"color": "#f4b740", "intensity": 4.5, "pulse": 0.0},
    "green": {"color": "#35d17a", "intensity": 2.5, "pulse": 0.0},
    "off": {"color": "#000000", "intensity": 0.0, "pulse": 0.0},
    "stale": {"color": "#5a6472", "intensity": 0.3, "pulse": 0.0},
}

# 展缸状态码 -> 液面高度与颜色.
# 编码来自上位机 config/plc_nodes.yaml 对 Tank_State 的注释:
#   0=Idle, 10=Prepping, 50=Draining, 55=BlowAir, 56=Drying, 98=DrainedIdle, 90=Error
# 其中仅 98(已排空) 语义确凿, 其余高度值为观感取值, 现场核对后可直接改这里.
#
# 配色(2026-08-03 用户指认深绿"不像液体"后重定): 展开剂是无色有机溶剂, 故全部落在
# **淡蓝~近无色**这一个窄带里, 让它先像液体、再谈相位区分; 相位主要靠液位高度和面板
# 文字表达, 颜色只做很轻的冷暖偏移. 只有故障(90)跳出该带用暖红报警.
# 本表是液体颜色的**运行时真源** —— TwinBindings._updateTanks 每帧按它覆写材质色,
# 管线侧 MAT_LIQUID 的基色只在预览渲染时可见, 改色要两处一起动.
TANK_STATE_STYLES = {
    "0": {"level": 0.0, "color": "#20242e", "label": "空闲"},
    "10": {"level": 0.35, "color": "#8ac9e2", "label": "准备中"},
    "20": {"level": 0.75, "color": "#6fb9d8", "label": "展开中"},
    # 40 是 resource_manager.TankStatus.DEVELOPING 的实际取值(plc_nodes 注释里标着
    # legacy, 但 PC 侧枚举仍在用). 缺这一条会落进 default, 展开中被当成"运行中".
    "40": {"level": 0.75, "color": "#6fb9d8", "label": "展开中"},
    "50": {"level": 0.25, "color": "#7fadc2", "label": "排液中"},
    "55": {"level": 0.06, "color": "#aebfc9", "label": "吹气"},
    "56": {"level": 0.02, "color": "#c2ccd2", "label": "干燥"},
    "90": {"level": 0.5, "color": "#d98a8a", "label": "故障"},
    "98": {"level": 0.0, "color": "#20242e", "label": "已排空"},
    "default": {"level": 0.6, "color": "#6fb9d8", "label": "运行中"},
}

# 会让展缸里液体增减的动作 —— 液面动画的主驱动源.
#
# 为什么不能只靠 Tank_State: 整个"润洗+上液+放板"阶段它恒等于 10(PREPPING), 液面只会
# 跳一次就不动了, 表达不出"注液的过程". 真正带缸号与体积的是动作事件的 args
# (VM 的 vm_node_enter / 单动作路径的 step_start).
#
# rampS 是"渐近趋近的名义时长", 不是真实流量曲线 —— 泵动作全程 L2 字段静默
# (见 config/actions/02_develop/plc_develop.yaml 的 stall_timeout 注释), 上位机拿不到
# 任何进度反馈. 前端用指数趋近, 先快后缓、永不过冲, 动作 done 时吸附到终值; 真实动作
# 比 rampS 长时液面就停在目标位, 那恰是物理事实(缸已满, 泵在跑后续循环).
#
# develop.clean_line 只洗管路、不动缸内液体, 故意不列.
#
# demoFillFrom 只服务**离线单动作演示**: 排液动作的入参里一滴体积都没有(只有 settle_s /
# drain_duration_s 这类时长), 缸里原本有多少液这条动作本身不知道. 动作页据此去动作目录
# 取配对注液动作的参数默认值算出一个建议起始液位, 预填进"起始液位 (mL)"输入框 —— 那是个
# **假设**, 前端必须把它写在步骤标签与 note 上. 流程演示不看这个键(流程自带上下文, 起始
# 液位由前面那条注液动作真实推导), 实时链也不看(它只读已知键).
TANK_LIQUID_TANK_ARG = "target_tank"
TANK_LIQUID_ACTIONS = {
    "develop.fill": {          # code 22 上液
        "dir": "fill",
        "volumeFrom": ["solvent_volume_ml", "up_liquid_repeat_count"],
        "rampS": 12.0,
    },
    "develop.rinse_fill": {    # code 21 润洗注液
        "dir": "fill",
        "volumeFrom": ["solvent_volume_ml", "rinse_repeat_count"],
        "rampS": 10.0,
    },
    "develop.rinse_suction": { # code 26 润洗抽吸: 先沉降 settle_s 再抽走
        "dir": "drain",
        "rampS": 8.0,
        "delayFromArg": "settle_s",
        "demoFillFrom": "develop.rinse_fill",
    },
    "develop.drain": {         # code 50 排液闭环: 时长直接由参数给出
        # 注意 drain_duration_s 在 PLC 侧是"废液管走空判据的持续时长"而非排空总时长
        # (动作还有 blow_s 30s 与 dry_duration_s). 这里当 rampS 用是一处**继承来的**
        # 近似, 实时链早已如此 —— 两侧对齐比单侧更物理值钱.
        "dir": "drain",
        "rampS": 10.0,
        "rampFromArg": "drain_duration_s",
        "demoFillFrom": "develop.fill",
    },
}

# ---------------------------------------------------------------------------
# 驻位液体动作表(工位座位实例内的液面, 目前只有收集样品瓶)
#
# 与 TANK_LIQUID_ACTIONS 的两处刻意不同, 别照搬:
#   1. 展缸的 volumeFrom 是**连乘出总量**(体积×趟数), 一条斜坡到底; 这里 volumeFrom
#      只给**单轮体积**, 轮数由 repeatFrom 单独表达(borrow 自 PUMP_SYRINGE_ACTIONS) ——
#      因为要演的是"每轮泵吸排→正压排液液面涨一截→沉淀"的逐轮节拍, 不是一次涨到位.
#   2. 时长两套都写死在契约里: roundS 是**实机值**(步骤标签写它), demoS 是**演示压缩值**
#      (时间轴用它). 三个消费方(clip_compiler.emit_station_liquid / flowSim.
#      emitStationLiquid / actionSim.stationLiquidSteps)全部只读本表, 不各自换算 ——
#      展缸那套"同一条规则三处手抄"的漂移风险(clip_compiler.py emit_tank_liquid 头注
#      明写过这条纪律)在这里从结构上消掉.
#
# roundS 实机出处(collect.collect = PLC A30, config/actions/03_collect/plc_collect.yaml):
#   pump 2.1s   = 泵吸+排两相位, t = 步数/V + M/1000, 默认 0.1mL=24步, V=500 半步/s,
#                 M=1000ms(config/app.yaml pump.collect) → 每相位 1.05s ×2
#   transfer 20s = "关进液、开排液和正压排液 20 秒"(动作注释原文) —— 溶剂经滤芯落进
#                 样品瓶的窗口, **液面上升对应这一拍**, 不是泵的 dispense
#   settle 5s   = "等待 5 秒沉淀"(同上)
# demoMaxRounds: liquid_repeat_count 编译期解出且超过它时只演前 N 轮(flowNotes 留痕),
# 免得 20 轮把片段拖到十分钟.
STATION_LIQUID_ACTIONS = {
    "collect-bottle": {
        "collect.collect": {
            "dir": "fill",
            "volumeFrom": ["solvent_volume_ml"],
            "repeatFrom": "liquid_repeat_count",
            "roundS": {"pump": 2.1, "transfer": 20.0, "settle": 5.0},
            "demoS": {"pump": 1.0, "transfer": 6.0, "settle": 2.0},
            "demoMaxRounds": 3,
        },
    },
}

# ---------------------------------------------------------------------------
# 耗材内容物(粉桶里的硅胶粉 / 将来别的耗材内容物)的**几何与单位契约**.
#
# 与 STATION_LIQUID_ACTIONS 的分工完全不同, 这里**刻意不建动作表**: 粉没有任何按动作
# 入参参数化的量 —— 收多少粉由"视觉轮廓面积 × 切深 × 松散系数"决定, 那三个数一个来自
# 运行期视觉、一个来自 app.yaml 标定、一个是配置常量, 没有一个是动作入参。硬建一张
# actions 表只能往里填常量, 那是**假的参数化**: 面板改参数它不动, 却看着像能动。
# 粉量的真源因此是两条: 离线链走片段通道(clip_compiler 按标定现算), 实时链走物料账本。
#
# 键名故意与液体那套不同名(capacityMm3/mm3PerMm 而不是 capacityMl/mlPerMm):
# 把 mm³ 喂进 levelFromMl 会立刻算出 NaN 而不是悄悄画错高度 —— 见 powderPivot.levelFromMm3。
CONSUMABLE_CONTENT_KINDS = {
    "scrape-holder": {
        "kind": "powder",
        "label": "硅胶粉",
        "accepts": "collector",
        # 观感放大 ×6: **有意不写进 rig_map**(与收集瓶的 exaggeration 不同) —— 它是演示
        # 口径不是几何声明。真机参考带 8×0.6cm = 480mm²(plc_photoscrape.yaml:103),
        # 配 total_depth 1.0mm 与松散系数 1.6 得 768mm³; 在内衬孔粉腔(Ø18.4 × 73mm,
        # 自由截面 265.9mm², 容积 19410.7mm³)里 ×6 时典型带高 17.3mm、占腔深 23.7%,
        # 饱和点抬到 20.2cm² —— 放大再往上抬会让稍大的带直接顶满看不出层次。
        "exaggeration": 6.0,
        # 松散系数: 与 app.yaml 的 gcode.scrape.bulk_factor 同源(粉刮下来是松散的,
        # 体积大于实体硅胶层)。给在这里是为了让 powderPivot.contentAmount 的"现算"那一
        # 级回退(账本还没这一列时)不必去读控制侧配置。
        "bulkFactor": 1.6,
        # 洗脱后的颜色: 淋洗液把硅胶粉浸透, 由干粉的哑白转成湿润的深灰褐。
        "elutedColor": "#8a7d6b",
    },
    "collect-holder": {
        "kind": "powder",
        "label": "硅胶粉",
        "accepts": "collector",
        "exaggeration": 6.0,
        "bulkFactor": 1.6,
        "elutedColor": "#8a7d6b",
    },
}

# ---------------------------------------------------------------------------
# 注射泵柱塞包络 —— 表本体已迁至 pump_syringe_spec.py (2026-08-08 阶段①泵链路归真):
# 相位结构(段序/端口/速度档名/体积参数名)由 tests/test_pump_manifest_drift_offline.py
# 逐动作对账 tools/pump/*translator* 的 plan_* (PLC 实收 DT 串的同一产地)。
# 本文件只负责经 resolve_pump_syringe 把表烘进 manifest; schema 注释见 spec 模块头。
# 顶部 `from pump_syringe_spec import PUMP_SYRINGE_ACTIONS` 保持既有
# `gen_twin_manifest.PUMP_SYRINGE_ACTIONS` 导入路径可用。
# ---------------------------------------------------------------------------


def read_yaml(path: str) -> dict:
    """
    功能: 读取 YAML; 文件不存在返回空字典.
    参数:
        path: 文件路径
    返回值: dict
    """
    if not os.path.isfile(path):
        log(f"提示: 未找到 {path}, 跳过")
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_structure(path: str) -> dict[str, dict]:
    """
    功能: 载入 Blender 导出的节点层级清单, 按路径建索引.
    参数:
        path: structure.json 路径
    返回值: dict, 路径 -> 节点信息
    """
    if not os.path.isfile(path):
        raise SystemExit(f"错误: 未找到结构清单 {path}\n请先运行 03_clean_model.py --stage full")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {node["path"]: node for node in data.get("nodes", [])}


def load_plate_clearance(work_dir: str) -> dict[str, dict]:
    """载入 verify_plate_clearance 的实测产物, 按**驱动轴 id** 建索引。

    缺文件时**不报错**只警告: 它要跑 Blender, 比 manifest 本身重得多, 单跑 manifest
    调参时不该被它卡住。代价是 axes[] 少一个 geometryMinMm, 前端那侧退回只按 rangeMm
    夹(与老 manifest 同一条兼容路径) —— 不会画错, 只是少一层兜底。
    """
    path = os.path.join(work_dir, "plate_clearance.json")
    if not os.path.isfile(path):
        log(f"警告: 未找到 {path} —— 料仓几何下界将缺席; 跑 verify_plate_clearance.py 生成")
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {entry["axisId"]: entry for entry in data.get("magazines", []) if entry.get("axisId")}


def find_node(structure: dict[str, dict], suffix: str) -> str | None:
    """
    功能: 按节点名(路径末段)查找其完整路径.
    参数:
        structure: 结构索引
        suffix: 节点名
    返回值: str | None, 完整路径
    """
    for path, node in structure.items():
        if node["name"] == suffix:
            return path
    return None


#: 两只吸盘的贴板面允许的不共面量(米). 5e-5 = 0.05mm, 比 CAD 网格化公差(0.4mm)还严 ——
#: 同一块电爪连接板上的两只同型吸盘在图纸里本就严格共面, 差一丝都说明装配或换版出了事.
PLATE_GRIP_COPLANAR_TOL_M = 5e-5

#: 认橡胶杯时, "伸得最远"必须比次远多出这么多(米)才算认得准。
#: 2mm 远小于实测差距(橡胶杯 −71.6 vs 气路接头 −47.0, 差 24.6mm), 又远大于任何建模噪声。
RUBBER_REACH_MARGIN_M = 2e-3


def _matches(name: str, matcher: dict) -> bool:
    """rig_map 通用的 {equals|contains} 名字匹配(与 blender_clean 侧同义)。"""
    if "equals" in matcher:
        return name == str(matcher["equals"])
    if "contains" in matcher:
        return str(matcher["contains"]) in name
    raise ValueError(f"匹配器既没有 equals 也没有 contains: {matcher}")


def _signed_permutation(rot: np.ndarray, tol: float = 1e-4) -> tuple[list[int], list[float]] | None:
    """把旋转矩阵拆成 局部轴 -> (世界轴, 符号); 不是轴对齐旋转时返回 None。

    只有轴对齐时, structure.json 的**世界** AABB 才能无损换算成局部尺寸 ——
    否则包围盒会在旋转里膨胀(与 plateGeometry.measurePlateAnchor 头注释第 2 条同款教训)。
    """
    perm, signs = [], []
    for col in range(3):
        axis = rot[:, col]
        index = int(np.argmax(np.abs(axis)))
        if abs(abs(axis[index]) - 1.0) > tol or np.linalg.norm(np.delete(axis, index)) > tol:
            return None
        perm.append(index)
        signs.append(1.0 if axis[index] > 0 else -1.0)
    if sorted(perm) != [0, 1, 2]:
        return None
    return perm, signs


def resolve_plate_contact_ignore(rig_map: dict, structure: dict[str, dict]) -> list[str]:
    """把 rig_map 的 `plate_contact.ignore` 解成节点路径 —— 柔性接触的排除集。

    为什么要有它: 接触判据把"板扎进硬表面"如实显示成板与吸盘之间的一条缝(超行程的部分
    不吸收), 这条设计是对的; 但有几处的"扎进去"是**建模约定或正常工况**而非错误, 于是
    每次经过都闪一下缝。2026-08-06 在 sampling_load 上逐帧量到两处, 出处与实测值写在
    rig_map 那一段的注释里(点样座/刮板台的 1.5mm 沉入, 以及取板时板本就嵌在料仓框架内)。

    为什么落在配置而不是前端写死: plateContact 的排除集有一条成文纪律 ——
    "排除集**从 manifest 派生**, 不硬编码节点名"。这里把它延续下来。

    matcher 两种:
        {contains: 名字片段}  按**零件名**匹配, 命中几个算几个(同名多实例一起排)
        {subtree: 节点名}     整棵子树, 只回根路径, 前端自己 traverse

    Returns:
        节点路径列表(去重、排序)
    """
    spec = (rig_map.get("plate_contact") or {}).get("ignore") or []
    paths: set[str] = set()
    for matcher in spec:
        if "subtree" in matcher:
            name = str(matcher["subtree"])
            hit = [path for path, node in structure.items() if node["name"] == name]
            if not hit:
                raise ValueError(f"plate_contact.ignore: 找不到子树根节点 {name}")
            paths.update(hit)
        elif "contains" in matcher:
            token = str(matcher["contains"])
            hit = [path for path, node in structure.items() if token in node["name"]]
            if not hit:
                raise ValueError(
                    f"plate_contact.ignore: 没有零件名含 {token!r} —— "
                    "CAD 换版改名了? 排除集失效会让那处重新闪缝, 故这里硬失败而不是静默跳过"
                )
            paths.update(hit)
        else:
            raise ValueError(f"plate_contact.ignore: matcher 既没有 contains 也没有 subtree: {matcher}")
    return sorted(paths)


def resolve_plate_grip(rig_map: dict, structure: dict[str, dict],
                       scene: GlbScene) -> tuple[str, dict] | None:
    """实测"薄层板相对吸盘"的刚体位姿, 供前端持板时钉局部位姿。

    为什么要有它: 此前前端吸附走的是"保世界位姿换父"(reparentPreservingWorld),
    等于把取板那一刻的**示教残差原样冻进去** —— 板与吸盘的相对关系于是每站一个样。
    2026-08-05 用 verify_plate_seats 量到 rotary-up 两站在法兰系下差 134.0mm
    (= 7Y 99 + 8Y 35, 两根没被片段驱动的工位轴), rotary-down 的料仓两站差 530mm
    (1Z/2Z 顶升没被驱动)。而吸盘对板的关系本该是**纯刀具几何**: 同一把刀、任何站、
    任何机械臂朝向下都一样。所以这里直接量吸盘, 一次得出与站无关的常量。

    量法(不写死任何方向, 换刀具/改吸盘间距重跑即自动跟上):
      · 吸盘轴向  = 单只吸盘包围盒最长的那根局部轴(SAB22 是细长体, 56mm vs 24mm);
      · 轴向正负  = 取离本节点原点**远**的那一端 —— 近端是 KQ2E06 气路接头, 远端才是
                    贴板的橡胶唇口;
      · 接触面    = 两只吸盘在轴向上的公共远端(必须共面, 否则刀具装歪了);
      · 对中心    = 两只吸盘中心的中点, 投影到接触面上。

    Returns:
        (机构 id, plateGrip 块) —— rig_map 里没有任何机构声明 plate_grip 时为 None
    Raises:
        ValueError: 声明了 plate_grip 但几何对不上(数量/直径/间距/共面性)
    """
    spec = next((item for item in (rig_map.get("actuators") or []) if item.get("plate_grip")), None)
    if spec is None:
        return None
    grip_cfg = spec["plate_grip"]
    owner = f"actuators[{spec.get('id')}].plate_grip"

    node_path = find_node(structure, spec["node"])
    if node_path is None:
        raise ValueError(f"{owner}: 机构节点未进入结构清单: {spec['node']}")

    matcher = grip_cfg["cups"]
    expect = int(matcher.get("expect_count", 2))
    # 只取直属子层(吸盘本体), 不要它自己的网格子件 —— 否则一只吸盘会被数成三个
    prefix = f"{node_path}/"
    depth = len(node_path.split("/")) + 1
    cup_items = [
        (path, node) for path, node in sorted(structure.items())
        if path.startswith(prefix) and len(path.split("/")) == depth
        and _matches(node["name"], matcher)
        and node.get("size") and node.get("center")
    ]
    cups = [node for _path, node in cup_items]
    if len(cups) != expect:
        raise ValueError(
            f"{owner}: 期望 {expect} 只吸盘, 实际命中 {len(cups)} 个"
            f"(匹配器 {matcher}; 命中 {[n['name'] for n in cups]})"
        )

    world = scene.world_matrix(node_path)
    decomposed = _signed_permutation(world[:3, :3])
    if decomposed is None:
        raise ValueError(
            f"{owner}: {spec['node']} 的世界旋转不是轴对齐的, 无法把 structure.json 的"
            "世界包围盒无损换算成局部尺寸 —— 需要改走逐顶点实测(见 measurePlateAnchor)"
        )
    perm, _signs = decomposed
    inverse = np.linalg.inv(world)

    measured = []
    for node in cups:
        center_world = np.append(np.asarray(node["center"], dtype=float), 1.0)
        center_local = (inverse @ center_world)[:3]
        # 局部第 k 轴的尺寸 = 世界第 perm[k] 轴的尺寸(已断言轴对齐)
        size_local = np.asarray([float(node["size"][perm[k]]) for k in range(3)])
        measured.append((center_local, size_local))

    axis_index = int(np.argmax(measured[0][1]))
    plane_axes = [k for k in range(3) if k != axis_index]

    # 远端 = 离本节点原点更远的那一头(近端是气路接头)
    ends = []
    for center_local, size_local in measured:
        half = size_local[axis_index] / 2.0
        candidates = (center_local[axis_index] - half, center_local[axis_index] + half)
        ends.append(max(candidates, key=abs))
    if abs(ends[0] - ends[1]) > PLATE_GRIP_COPLANAR_TOL_M:
        raise ValueError(
            f"{owner}: 两只吸盘的接触面不共面(相差 {abs(ends[0] - ends[1]) * 1000:.3f}mm) —— "
            "刀具装歪或 CAD 换版; 拒绝按它摆板"
        )
    contact = float(np.mean(ends))

    diameters = [float(size_local[k]) for _c, size_local in measured for k in plane_axes]
    nominal_d = float(grip_cfg["cup_diameter_mm"]) / 1000.0
    tol_d = float(grip_cfg.get("cup_diameter_tol_mm", 0.5)) / 1000.0
    if any(abs(value - nominal_d) > tol_d for value in diameters):
        raise ValueError(
            f"{owner}: 吸盘直径实测 {[round(v * 1000, 2) for v in diameters]}mm, "
            f"与声明 {nominal_d * 1000:.1f}±{tol_d * 1000:.1f}mm 不符"
        )

    span_vec = measured[1][0] - measured[0][0]
    span = float(np.linalg.norm(span_vec))
    nominal_span = float(grip_cfg["cup_span_mm"]) / 1000.0
    tol_span = float(grip_cfg.get("cup_span_tol_mm", 1.0)) / 1000.0
    if abs(span - nominal_span) > tol_span:
        raise ValueError(
            f"{owner}: 吸盘中心距实测 {span * 1000:.2f}mm, "
            f"与声明 {nominal_span * 1000:.1f}±{tol_span * 1000:.1f}mm 不符"
        )

    center_mid = np.mean([center for center, _s in measured], axis=0)
    contact_point = center_mid.copy()
    contact_point[axis_index] = contact

    axis_local = np.zeros(3)
    axis_local[axis_index] = 1.0 if contact > 0 else -1.0

    stroke = float(grip_cfg["cup_stroke_mm"]) / 1000.0
    # 被吸住时波纹段已经压掉的量。缺省 0 = 老行为(板贴自由唇口), 老 rig_map 仍能跑。
    carry_compression = float(grip_cfg.get("carry_compression_mm", 0.0)) / 1000.0
    rubbers = [
        _resolve_cup_rubber(structure, scene, world, axis_index, contact, path, owner)
        for path, _node in cup_items
    ]
    free_lengths = [item["freeLenM"] for item in rubbers]
    if max(free_lengths) - min(free_lengths) > PLATE_GRIP_COPLANAR_TOL_M:
        raise ValueError(
            f"{owner}: 两只吸盘的橡胶段不等长"
            f"({[round(v * 1000, 2) for v in free_lengths]}mm) —— CAD 换版或选错了子件"
        )
    if carry_compression < 0:
        raise ValueError(f"{owner}: carry_compression_mm 不能为负({carry_compression * 1000:.2f})")
    # 持板压缩与后续行程是**叠加**的(见 rig_map 里 cup_stroke_mm 的语义注释), 故按两者之和
    # 判上界 —— 只判其中一个会让"持板已压 17.8 + 再让 6"悄悄压过橡胶段总长而变成穿模。
    if carry_compression + stroke >= min(free_lengths):
        raise ValueError(
            f"{owner}: 持板压缩 {carry_compression * 1000:.1f}mm + 行程 {stroke * 1000:.1f}mm "
            f"不小于橡胶段自由长度 {min(free_lengths) * 1000:.1f}mm —— 压到负长度不是柔性是穿模"
        )

    return spec["id"], {
        # 局部系里"从刀具本体指向板"的单位向量(= 吸盘伸出方向)
        "axisLocal": [round(float(v), 8) for v in axis_local],
        # 接触面上、两只吸盘正中的那个点(局部系, 米) —— 板贴的就是这里
        "contactLocalM": [round(float(v), 8) for v in contact_point],
        # 吸盘连线方向; 前端拿它把板的面内 +X 钉死, 免得方板每次转载朝向随机
        "spanAxisLocal": [round(float(v), 8) for v in (span_vec / span)],
        "cupCount": len(cups),
        "cupDiameterM": round(float(np.mean(diameters)), 8),
        "cupSpanM": round(span, 8),
        # 波纹可压缩行程: 板顶到硬表面时吸盘在**持板压缩之上**再让这么多, 超出即"露缝"
        "strokeM": round(stroke, 8),
        # 被吸住时波纹段已经压掉的量: 板骑的是压缩后的唇口, 不是自由长度的唇口。
        # 由示教点反解标定得来(见 rig_map 的出处注释), 0 = 老行为。
        "carryCompressionM": round(carry_compression, 8),
        # 两只橡胶段 —— 前端按 s=(freeLen−compression)/freeLen 缩放它们表达压缩
        "rubbers": rubbers,
    }


def _resolve_cup_rubber(structure: dict[str, dict], scene: GlbScene, actuator_world: np.ndarray,
                        axis_index: int, contact: float, cup_path: str, owner: str) -> dict:
    """认出一只吸盘里的**橡胶波纹段**, 并算好前端压缩它所需的三个量。

    怎么认: **按几何不按名字**。吸盘由两件组成 —— 近端是 KQ2E06 气路接头, 远端是橡胶杯,
    只有橡胶杯伸到接触面(唇口)。所以取"沿吸盘轴伸到 contact 的那个子网格"。
    名字("schmalz_…")是供应商串, 换个供应商就断, 不能当判据。

    产出的三个量让前端只做一次缩放 + 一次平移, 不必在浏览器里重新推导节点局部系:
        scaleAxis          橡胶节点**自己局部系**里与吸盘轴对应的那根轴(0/1/2)
        freeLenM           自由长度(米), 压缩比例 = (freeLen − compression)/freeLen
        mountOffsetParent  节点原点 → **安装端**的向量(父空间, 米)。
                           前端: `pos = basePos + mountOffsetParent × (1 − s)`
                           —— 于是缩放绕安装端发生, 唇口往回缩正好等于压缩量。
    """
    prefix = f"{cup_path}/"
    depth = len(cup_path.split("/")) + 1
    children = [
        (path, node) for path, node in sorted(structure.items())
        if path.startswith(prefix) and len(path.split("/")) == depth
        and node.get("size") and node.get("center")
    ]
    if not children:
        raise ValueError(f"{owner}: 吸盘 {cup_path} 下没有子网格, 认不出橡胶段")

    inverse_actuator = np.linalg.inv(actuator_world)
    decomposed = _signed_permutation(actuator_world[:3, :3])
    perm, _signs = decomposed          # 上游已断言轴对齐, 这里直接复用
    reach = []
    for path, node in children:
        center = (inverse_actuator @ np.append(np.asarray(node["center"], dtype=float), 1.0))[:3]
        half = float(node["size"][perm[axis_index]]) / 2.0
        far = max((center[axis_index] - half, center[axis_index] + half), key=abs)
        reach.append((path, node, far, half * 2.0))

    # 伸得最远的那一个就是橡胶杯(近端的气路接头够不着唇口)。
    # 判据用"最远"而不是"与接触面等高": contact 是两只吸盘的**均值**平面, 而两只实测
    # 相差 0.1mm, 拿绝对容差去比会两只都落选(2026-08-05 首版就是这么挂的)。
    # "最远 + 与次远拉开明显距离"既稳又能在选错子件时报出来 —— 接头比橡胶杯短 24mm,
    # 真正的歧义只会发生在 CAD 换版把两件做成同长时。
    order = sorted(reach, key=lambda item: -abs(item[2]))
    rubber_path, _node, far, free_len = order[0]
    if len(order) > 1 and abs(far) - abs(order[1][2]) < RUBBER_REACH_MARGIN_M:
        raise ValueError(
            f"{owner}: 吸盘 {cup_path} 里分不清哪个子件是橡胶杯 —— "
            f"各子件轴向远端 {[(p.rsplit('/', 1)[-1], round(f * 1000, 2)) for p, _n, f, _l in reach]}mm, "
            f"最远与次远相差不足 {RUBBER_REACH_MARGIN_M * 1000:.0f}mm"
        )
    if abs(abs(far) - abs(contact)) > RUBBER_REACH_MARGIN_M:
        raise ValueError(
            f"{owner}: 橡胶杯 {rubber_path} 的唇口在 {far * 1000:.2f}mm, "
            f"与两只吸盘的接触面均值 {contact * 1000:.2f}mm 差得离谱 —— 选错子件了"
        )

    # 安装端 = 背离接触面的那一头
    mount_actuator = contact - np.sign(contact) * free_len
    index = scene.index_of(rubber_path)
    rubber_world = scene.world_matrix(rubber_path)
    cup_world = scene.world_matrix(cup_path)
    rubber_local = scene.local_matrix(index)          # 父(吸盘)空间的 4x4

    # 节点原点与安装端, 都换算到吸盘(父)空间
    to_cup = np.linalg.inv(cup_world) @ actuator_world
    origin_actuator = (inverse_actuator @ rubber_world)[:3, 3]
    delta_actuator = np.zeros(3)
    delta_actuator[axis_index] = mount_actuator - origin_actuator[axis_index]
    # 面内两轴上原点与安装端同轴(圆柱体), 只有轴向有差
    mount_offset_parent = to_cup[:3, :3] @ delta_actuator

    # 自检 1: 父链不许带缩放。前端是在**父空间**里做 `pos += offset × (1−s)` 的, 父链一旦
    # 有缩放, 同一个数产生的世界位移就不是这个数 —— 而 to_cup 又会把 offset 本身一并放缩,
    # 两头同时错。轴对齐断言管不到这一条(缩放不破坏轴对齐)。
    column_norms = [float(np.linalg.norm(to_cup[:3, index])) for index in range(3)]
    if any(abs(norm - 1.0) > 1e-6 for norm in column_norms):
        raise ValueError(
            f"{owner}: 吸盘 {cup_path} 到机构之间的变换带缩放(列范数 "
            f"{[round(n, 6) for n in column_norms]}) —— 父空间的补偿平移换算不过去"
        )
    # 自检 2: 纯旋转必然保长。不等长就说明上面那条没拦住, 或 delta 被谁改过。
    if abs(float(np.linalg.norm(mount_offset_parent)) - float(np.linalg.norm(delta_actuator))) > 1e-9:
        raise ValueError(
            f"{owner}: 补偿平移换算后长度变了("
            f"{np.linalg.norm(delta_actuator) * 1000:.4f} -> "
            f"{np.linalg.norm(mount_offset_parent) * 1000:.4f}mm)"
        )
    # ⚠ **前端不再用这个值**(2026-08-06)。它是**节点局部**量, 而这里算它用的是
    #   work/machine.full.glb, 前端加载的却是 04 压缩后的 models/machine*.glb ——
    #   KHR_mesh_quantization 会把反量化 scale 烘进节点并挪走原点(同一只橡胶杯, 原点
    #   距唇口在 full 里 63.57mm、在压缩版里 17.50mm)。于是这里算出的 +28.57mm 对
    #   full.glb 是**对的**, 用到压缩版上却把杯子往外推, 持板时杯子从板面穿出去。
    #   **节点局部的平移量在两份 GLB 之间不可搬运, 而本步骤也修不了这一条 ——
    #   04 压缩排在两条 manifest 之后(见 runtime/three_d_authoring._rebuild_steps),
    #   生成契约时压缩版还不存在。** 只有运行期知道自己那份 GLB 的节点原点, 所以
    #   plateContact._mountOffsetOf 改成运行期实测, 本字段只当**取不到翻转节点时的兜底**。
    #   下面两条自检仍留着: 它们保证这个兜底值至少在 full.glb 语义下自洽。

    # 吸盘轴在橡胶节点自己的局部系里是哪一根
    axis_actuator = np.zeros(3)
    axis_actuator[axis_index] = 1.0
    axis_local = np.linalg.inv(rubber_local[:3, :3]) @ (to_cup[:3, :3] @ axis_actuator)
    scale_axis = int(np.argmax(np.abs(axis_local)))
    residual = np.linalg.norm(np.delete(axis_local, scale_axis))
    if residual > 1e-4 * max(np.linalg.norm(axis_local), 1.0):
        raise ValueError(
            f"{owner}: 橡胶段 {rubber_path} 的局部系与吸盘轴不轴对齐(残差 {residual:.3g}) —— "
            "单轴缩放表达不了这种压缩, 需要改走顶点位移"
        )

    return {
        "node": rubber_path,
        "scaleAxis": scale_axis,
        "freeLenM": round(float(free_len), 8),
        "mountOffsetParent": [round(float(v), 8) for v in mount_offset_parent],
    }


#: rig_map 的 station -> app.yaml `pump:` 段的工位键. 速度档按工位分组, 不按泵分组.
PUMP_SPEED_STATION = {"PUMP": "develop", "SAMPLING": "sampling", "COLLECT": "collect"}


def collect_pump_speeds(eit_root: str) -> dict:
    """
    功能: 把上位机 app.yaml 的 `pump:` 段(各工位的 V/M 档)快照进 manifest.

    为什么要快照: 前端算相位时长要用 `t = 步数/V + M/1000`, 而 V/M 的真源是
    `config.pump`(可在线改)。前端优先拉 `GET /api/config/pump` 取实时值, 拉不到时
    (离线打开、后端没起)就用这份构建期快照兜底 —— 总比退回写死的 rampS 强。

    这份快照**不是**真源, 只是兜底; 与后端 tools/pump/profiles.py 的回退链同一个道理。

    参数: eit_root 上位机仓库根目录
    返回值: dict, {工位: {档名: 数值}}; 读不到返回 {}
    """
    path = os.path.join(eit_root, "config", "app.yaml")
    if not eit_root or not os.path.isfile(path):
        log(f"警告: 找不到 {path}, manifest 不带泵速快照 —— 前端只能靠实时接口")
        return {}
    try:
        section = (read_yaml(path) or {}).get("pump") or {}
    except Exception as exc:                       # noqa: BLE001 - 快照缺了不该阻断出图
        log(f"警告: 读 app.yaml 的 pump 段失败({exc}), manifest 不带泵速快照")
        return {}
    out: dict = {}
    for station, values in section.items():
        if not isinstance(values, dict):
            continue
        # 只收数值档(速度/延时); spot_end_position_ml 那种工艺量不属于这里
        out[str(station)] = {
            str(k): float(v) for k, v in values.items()
            if isinstance(v, (int, float)) and (k.endswith("_speed") or k == "step_delay")
        }
    return out


def resolve_pump_syringe(rig_map: dict, structure: dict[str, dict],
                         clean_report: dict, pump_speeds: dict | None = None) -> dict | None:
    """
    功能: 解析三台注射泵的柱塞组与液柱节点, 生成 manifest.pumpSyringe 绑定契约.

    与展缸液面的两处实质差异:
      · 柱塞与液柱都是 03 步**合成**的几何(CAD 里根本没有柱塞零件), 节点真名只能从
        03 报告取, 不能字面拼路径 —— 与运动轴要取 CARRIAGE 真名同一个理由.
      · 行程/量程是**声明值**不是实测值: 针筒是一根光管, 内腔无可测特征, 体素扫描
        给不出腔体. 60mm/25mL/6000 步是厂家额定规格, 真源在 rig_map.pumps.

    缸号→泵的路由用每台泵自己的 tankGroup 直接查表, **不在前端重算 (t-1)//4+1** ——
    那样两侧各有一份同样的算术, 改缸组划分时必漂.

    参数:
        rig_map: rig_map.yaml 内容(pumps 段给语义)
        structure: structure.json 索引(给节点全路径)
        clean_report: 03 报告(给 build_pump_visuals 造出来的节点真名与行程)
    返回值: dict | None, 未启用或一台都没声明时为 None
    """
    spec = rig_map.get("pumps") or {}
    if not spec.get("enabled"):
        return None
    visuals = clean_report.get("pump_visuals") or {}
    built = {
        entry["id"]: entry
        for entry in (visuals.get("instances") or [])
        if isinstance(entry, dict) and entry.get("id")
    }

    pumps = []
    for index, item in enumerate(spec.get("items") or []):
        pump_id = str(item.get("id") or "").strip()
        if not pump_id:
            continue
        built_entry = built.get(pump_id) or {}
        plunger_name = built_entry.get("plunger_node")
        liquid_name = built_entry.get("liquid_node")
        valve_name = built_entry.get("valve_node")
        plunger_path = find_node(structure, plunger_name) if plunger_name else None
        liquid_path = find_node(structure, liquid_name) if liquid_name else None
        valve_path = find_node(structure, valve_name) if valve_name else None
        declared = bool(item.get("rigged"))
        rigged = declared and plunger_path is not None and liquid_path is not None
        if declared and not rigged:
            # 静默失败不许再有: 声明了要驱动却找不到节点, 必须喊出来
            log(f"警告: 注射泵 {pump_id} 在 rig_map 标了 rigged, 但 03 产物里找不到 "
                f"柱塞({plunger_name})或液柱({liquid_name}) —— 按未装配处理, 三维不动")
        if rigged and valve_path is None:
            # 阀指针缺了不影响柱塞/液柱, 降级成"不转"即可, 但同样不许静默
            log(f"警告: 注射泵 {pump_id} 找不到阀指针节点({valve_name}), 阀位动画降级为不转")
        axis_tag = str(built_entry.get("travel_axis_gltf") or "+y").lower()
        valve_axis_tag = str(built_entry.get("valve_axis_gltf") or "-z").lower()
        valve_vec = [0.0, 0.0, 0.0]
        valve_vec["xyz".index(valve_axis_tag[1])] = -1.0 if valve_axis_tag[0] == "-" else 1.0
        lead_name = built_entry.get("lead_node")
        lead_path = find_node(structure, lead_name) if lead_name else None
        if rigged and lead_path is None:
            # 丝杆缺了不影响柱塞/液柱/阀位, 降级成"不转"即可, 但同样不许静默
            log(f"警告: 注射泵 {pump_id} 找不到丝杆节点({lead_name}), 丝杆旋转降级为不转")
        lead_axis_tag = str(built_entry.get("lead_axis_gltf") or "+y").lower()
        lead_vec = [0.0, 0.0, 0.0]
        lead_vec["xyz".index(lead_axis_tag[1])] = -1.0 if lead_axis_tag[0] == "-" else 1.0
        pumps.append({
            "index": index,
            "id": pump_id,
            "label": item.get("label") or pump_id,
            "station": item.get("station"),
            "dtAddr": int(item.get("dt_addr") or 0),
            "valve": item.get("valve"),
            # 缸号清单; 只有展开泵有, 上样/收集泵是 fixed 路由
            "tankGroup": list(item.get("tank_group") or []),
            # 打液出口通道号; 动作表里写 "port": "output" 的相位解析到它.
            # 缺省(收集泵)时该相位不转阀 —— 宁可不动也不编一个端口号.
            "outputPort": int(item["output_port"]) if item.get("output_port") else None,
            "plungerNode": plunger_path,
            "liquidNode": liquid_path,
            # 柱塞是**平移**: position = base + travelAxis × travelM × level
            "travelAxis": [0.0, -1.0, 0.0] if axis_tag.startswith("-") else [0.0, 1.0, 0.0],
            "travelM": float(built_entry.get("travel_m") or 0.0),
            "strokeMm": float(built_entry.get("stroke_mm") or spec.get("stroke_mm") or 60.0),
            # 阀指针盘绕进深轴**旋转**: quaternion = base × axisAngle(valveAxis, 2π×port/valvePorts)
            # 真机 Runze 阀是定子带端口、转子在内部, 外面看不到整头转; 这里转的是面心指针盘.
            "valveNode": valve_path,
            "valveAxis": valve_vec,
            "valvePorts": int(built_entry.get("valve_ports") or 4),
            # 端口不是绕轴心 360° 均布 —— 实物阀头的接口全挤在下半圈(2026-08-05 用户实测),
            # 03 建了接头的那些角在这里原样带下去. 前端拿它算指针角; 缺这一项才退回均布.
            "valvePortAngles": [float(a) for a in (built_entry.get("valve_port_angles") or [])],
            # 相位时长按 `步数/V + M/1000` 算, V/M 按**工位**分档(app.yaml 的 pump 段)
            "speedStation": PUMP_SPEED_STATION.get(str(item.get("station") or ""), ""),
            # 丝杆: 绕自身竖轴转, 满行程 turnsPerStroke 圈(梯形丝杆导程 6mm / 行程 60mm = 10).
            # 光杆芯留在静态组里 —— 光面圆柱绕自身轴转看不出来, 转的是螺纹那一层.
            "leadNode": lead_path,
            "leadAxis": lead_vec,
            "leadTurnsPerStroke": float(built_entry.get("lead_turns_per_stroke") or 0.0),
            "rigged": rigged,
        })
    if not pumps:
        return None
    return {
        "syringeMl": float(spec.get("syringe_ml") or 25.0),
        "strokeMm": float(spec.get("stroke_mm") or 60.0),
        "stepsPerStroke": int(spec.get("steps_per_stroke") or 6000),
        # 各工位的 V/M 档快照(构建期取自 app.yaml)。前端优先拉 GET /api/config/pump 的
        # 实时值, 拉不到才用这份 —— 与后端 profiles.py 的回退链同一个道理。
        "speeds": pump_speeds or {},
        # 恒真: 柱塞位置**永远**没有传感器确认(plc_nodes.yaml 里没有回读通道), 这不是
        # "暂时没收到反馈"而是"这条链路上不存在反馈". 前端据此恒标 estimated.
        "estimated": True,
        "pumps": pumps,
        "actions": PUMP_SYRINGE_ACTIONS,
    }


def resolve_signal_light(rig_map: dict, structure: dict[str, dict]) -> dict | None:
    """
    功能: 解析整机三色塔灯的灯罩节点, 生成 manifest.signalLight 绑定契约.

    与已停用的 status_lights(逐工位示意灯条)是两回事: 这里声明的是真实塔灯零件,
    运行时由上位机 signal_light 事件(PLC 三色灯输出位 %QX0.0-0.2)驱动整罩换色.
    tower_split 被回退成整灯单节点时, 同一 pattern 仍命中唯一节点, 自然降级为整灯发光.
    参数:
        rig_map: rig_map.yaml 内容
        structure: 结构索引
    返回值: dict | None, signalLight 条目; 未启用时 None
    """
    cfg = rig_map.get("signal_light") or {}
    if not cfg.get("enabled"):
        return None
    pattern = re.compile(cfg.get("pattern", r"^3D_Model_upload_ZHD24"))
    # exclude_suffix 兼容单串与列表(tower_split 拆出 _HOUSING 外壳与 _CAP 顶盖两个金属件,
    # 两个都得排掉才只剩灯罩); str.endswith 原生吃 tuple
    exclude = cfg.get("exclude_suffix", ("_HOUSING", "_CAP"))
    if isinstance(exclude, str):
        exclude = (exclude,)
    exclude = tuple(str(item) for item in exclude if item)
    hits = [
        path for path, node in structure.items()
        if pattern.match(node["name"]) and not (exclude and node["name"].endswith(exclude))
    ]
    if len(hits) != 1:
        raise ValueError(
            f"signal_light 命中 {len(hits)} 个节点(应恰为 1): {hits} —— "
            "三色灯在模型里改名了或 exclude_suffix 没滤干净, 修 rig_map.signal_light 或重跑 03"
        )
    return {
        "glbNode": hits[0],
        "event": "signal_light",
        "staleMs": int(cfg.get("stale_ms", 3000)),
        "styles": SIGNAL_LIGHT_STYLES,
    }


def resolve_lights(rig_map: dict, structure: dict[str, dict]) -> list[dict]:
    """解析工艺灯(拍照补光/紫外面光源)的节点, 产出 manifest.lights 绑定契约。

    与 signalLight 的差别: 那盏报的是机器状态, 这些是**工艺动作的一部分** ——
    由片段的 `light` 连续通道按真机时序驱动(开灯 → 稳定 → 拍 → 熄)。

    节点是 03 步按材质合并出的静态块 `STATIC_<材质名>`, 所以**灯能不能分别驱动取决于
    material_semantics 的分组**。命中数 ≠ 1 一律硬失败: 命中 0 说明材质分组变了或没重跑 03,
    命中多个说明合并块被拆散 —— 两种情况下静默降级都会变成"灯不亮/亮错一盏", 而画面
    看起来完全正常, 没有任何指标会报警。

    Args:
        rig_map: rig_map.yaml 内容
        structure: 结构索引

    Returns:
        lights 条目数组; 未声明时空数组
    """
    lights = []
    for spec in rig_map.get("lights") or []:
        name = str(spec.get("node") or "")
        if not name:
            continue
        hits = [path for path, node in structure.items() if node["name"] == name]
        if len(hits) != 1:
            raise ValueError(
                f"lights[{spec.get('id')}] 的节点 {name} 命中 {len(hits)} 个(应恰为 1): {hits} —— "
                "多半是 material_semantics 的分组变了或 03 步没重跑; "
                "灯是按材质合并成 STATIC_<材质名> 块的, 分组一动节点名就变"
            )
        lights.append({
            "id": spec["id"],
            "label": spec.get("label", spec["id"]),
            "glbNode": hits[0],
            "color": spec.get("color", "#ffffff"),
            "peakIntensity": float(spec.get("peak_intensity", 1.0)),
            "defaultLevel": float(spec.get("default_level", 0.0)),
            "bloom": bool(spec.get("bloom", True)),
            # 受照对象: 灯本体常常看不见(补光灯埋在台面下), 真正读得出的是被照亮的东西
            "illuminates": spec.get("illuminates") or None,
            "illuminatesNodes": _resolve_illuminated_nodes(spec, structure),
        })
    return lights


def resolve_spindles(rig_map: dict, structure: dict[str, dict]) -> list[dict]:
    """解析主轴(持续自转的切削刀具), 产出 manifest.spindles 绑定契约。

    与 actuators 的 `motion: rotate` 的分工见 rig_map.spindles 段头注释: 那边是有限角、
    值是时间的纯函数; 主轴是无限角、相位按转速积分, 只能把**开关**做成通道、相位交给
    渲染层逐帧累加。所以这里透传的是 `rpm` 与 `axis`, 不是 outputRange。

    节点由 03 步的 build_spindle_cutters 现造(TOOL_ 前缀, 不参与静态合并), 命中数 ≠ 1
    一律硬失败 —— 命中 0 说明 03 没重跑或 rig_map.spindles 与 03 产物脱节, 静默降级的
    现象是"刀不转", 画面完全正常且没有任何指标会报警。

    Args:
        rig_map: rig_map.yaml 内容
        structure: 结构索引

    Returns:
        spindles 条目数组; 未声明时空数组
    """
    spindles = []
    for spec in rig_map.get("spindles") or []:
        name = str(spec.get("node") or "")
        if not name:
            continue
        hits = [path for path, node in structure.items() if node["name"] == name]
        if len(hits) != 1:
            raise ValueError(
                f"spindles[{spec.get('id')}] 的节点 {name} 命中 {len(hits)} 个(应恰为 1): {hits} —— "
                "该节点由 03 步 build_spindle_cutters 现造, 多半是没重跑 03 或声明改过了"
            )
        trigger = spec.get("trigger") or {}
        spindles.append({
            "id": spec["id"],
            "label": spec.get("label", spec["id"]),
            "station": spec.get("station"),
            "glbNode": hits[0],
            "axis": [float(v) for v in (spec.get("axis") or [0, 1, 0])],
            "rpm": float(spec.get("rpm", 6000)),
            "diameterMm": float(spec.get("diameter_mm", 0.0)),
            # 触发源: 实时链按这条动作的 vm_node_enter/done 开关主轴(PLC 无主轴独立信号)
            "triggerAction": trigger.get("action") or None,
        })
    return spindles


def _resolve_illuminated_nodes(spec: dict, structure: dict[str, dict]) -> list[dict]:
    """解析一盏灯的**节点级受照对象**(如补光灯正上方那扇会跟着亮的盖板玻璃)。

    与 `illuminates: plate` 的分工: plate 是舞台上动态生成的板, 只有挂了 PlateStage 的
    链才有(而且板只在放板那一段在场); 这里是模型里**本来就存在**的静态零件, 两条链
    (离线 Studio / 实时 Twin)都能驱动。

    命中数 ≠ 1 一律硬失败, 与灯本体同一口径: 静默降级的现象是"灯照旧不亮", 而画面
    完全正常、没有任何指标会报警 —— 这正是 2026-08-05 那次"实时页闪光灯不闪"的形状。

    Args:
        spec: rig_map.lights 的单条声明
        structure: 结构索引

    Returns:
        [{glbNode, peakIntensity}]; 未声明时空数组
    """
    resolved = []
    for entry in spec.get("illuminates_nodes") or []:
        name = str(entry.get("node") or "")
        if not name:
            raise ValueError(f"lights[{spec.get('id')}].illuminates_nodes 有条目缺 node")
        hits = [path for path, node in structure.items() if node["name"] == name]
        if len(hits) != 1:
            raise ValueError(
                f"lights[{spec.get('id')}] 的受照节点 {name} 命中 {len(hits)} 个(应恰为 1): {hits} —— "
                "该零件在模型里改名/被合并了, 修 rig_map.lights[].illuminates_nodes 或重跑 03"
            )
        resolved.append({
            "glbNode": hits[0],
            # 缺省跟随灯本体: 但受照物多半是被照亮而非自发光, 通常要显式调低
            "peakIntensity": float(entry.get("peak_intensity", spec.get("peak_intensity", 1.0))),
        })
    return resolved


def camera_preset(node: dict, all_bounds: dict) -> dict:
    """
    功能: 依据工位包围盒推算一个合理的相机机位(位置 + 目标点).

    两条硬性要求, 缺一个观感就崩:
      1. 工位要在画面里足够大 —— 距离按工位自身尺寸定;
      2. 镜头必须在整机外面 —— 否则像地轨这种位于机器正中的工位, 相机会直接
         落进机柜内部, 看到的全是钣金内壁. 因此在按工位尺寸算出距离之后,
         还要沿水平方向把相机推到整机水平轮廓之外, 再留一段余量.

    参数:
        node: 工位节点信息(含 center/size)
        all_bounds: 整机包围盒 {center, size}
    返回值: dict, {pos: [x,y,z], target: [x,y,z]}
    """
    center = node.get("center")
    size = node.get("size")
    if not center or not size:
        return {}

    machine_center = all_bounds["center"]
    machine_size = all_bounds["size"]

    # 水平方向: 整机中心 -> 工位中心; 工位恰在中心时退化为默认斜前方
    dx = center[0] - machine_center[0]
    dz = center[2] - machine_center[2]
    length = (dx * dx + dz * dz) ** 0.5
    if length < 1e-3:
        dx, dz, length = 0.6, 1.0, 1.166
    dx, dz = dx / length, dz / length

    radius = max(max(size) * 0.5, 0.12)

    # 距离一: 让工位刚好填满画面. 半径 r 的外接球要塞进垂直视场角 f, 需要
    # distance = r / sin(f/2); 乘 0.9 让工位略微溢出, 观感更饱满.
    fit_distance = radius / math.sin(math.radians(CAMERA_FOV_DEG) / 2) * 0.9

    # 距离二: 相机必须落在整机水平轮廓之外. 大多数工位都在机器内部,
    # 若只按填充度算距离, 相机会直接落进机柜里, 看到的全是钣金内壁.
    # 把方向向量投影到半宽/半深上, 取较大者即"出机身"所需距离(自机器中心量起).
    half_x = machine_size[0] * 0.5
    half_z = machine_size[2] * 0.5
    exit_from_center = max(abs(dx) * half_x, abs(dz) * half_z) + 0.5
    # 换算成"自工位中心量起"的距离: 工位中心本身已经偏离机器中心一段
    offset_along_dir = dx * (center[0] - machine_center[0]) + dz * (center[2] - machine_center[2])
    exit_distance = exit_from_center - offset_along_dir

    distance = max(fit_distance, exit_distance)
    # 视线高度: 略高于工位中心. 抬太高会变成俯视机器顶部, 工位内部机构反而被
    # 上层结构挡住; 俯视 20 度左右既有立体感又能平视到机构本体.
    height = center[1] + radius * 0.5 + 0.2

    return {
        "pos": [
            round(center[0] + dx * distance, 3),
            round(height, 3),
            round(center[2] + dz * distance, 3),
        ],
        "target": [round(center[0], 3), round(center[1], 3), round(center[2], 3)],
    }


def collect_action_prefixes(eit_root: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    功能: 扫描上位机的动作目录, 归纳每个动作组的名称前缀与完整动作名清单.

    上位机的动作 YAML 是"一个文件多个动作", 动作名就是文件的顶层键(如 sampling.init、
    develop.drain), 而不是某个 name 字段 —— 早期按 name 字段解析会得到零结果.

    参数:
        eit_root: 上位机仓库根目录
    返回值: tuple[dict, dict], (组名 -> 前缀列表, 组名 -> 动作全名列表)
    """
    actions_dir = os.path.join(eit_root, "config", "actions")
    prefixes: dict[str, set[str]] = {}
    names: dict[str, set[str]] = {}

    for path in glob.glob(os.path.join(actions_dir, "*", "*.yaml")):
        group = os.path.basename(os.path.dirname(path))
        data = read_yaml(path)
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            # 动作条目一定是映射且带有 kind 字段; 其余顶层键(如注释性配置)跳过
            if not isinstance(value, dict) or "kind" not in value:
                continue
            names.setdefault(group, set()).add(key)
            if "." in key:
                prefixes.setdefault(group, set()).add(key.split(".", 1)[0] + ".")

    return (
        {group: sorted(values) for group, values in prefixes.items()},
        {group: sorted(values) for group, values in names.items()},
    )


# 上位机动作组目录名 -> rig_map 工位 id
ACTION_GROUP_TO_STATION = {
    "01_sampling": "SAMPLING",
    "02_develop": "DEVELOP",
    "03_collect": "COLLECT",
    "04_photoscrape": "PHOTOSCRAPE",
    "05_feedlift": "FEEDLIFT",
    "06_rail": "RAIL",
    "07_robot": "ROBOT",
    "08_pump": "PUMP",
    "10_vision": "PHOTOSCRAPE",
    "11_staging_a": "STAGINGA",
}


def collect_axes_from_eit(eit_root: str) -> dict[str, dict]:
    """
    功能: 从上位机 manual_points.yaml 读取伺服轴清单(轴 id 与中文标签的权威来源).
    参数:
        eit_root: 上位机仓库根目录
    返回值: dict, 轴 id -> {label, station}
    """
    data = read_yaml(os.path.join(eit_root, "config", "manual_points.yaml"))
    axes: dict[str, dict] = {}
    for station_key, station in (data.get("stations") or {}).items():
        for axis in station.get("axes", []) or []:
            axis_id = axis.get("id")
            if not axis_id:
                continue
            axes[axis_id] = {
                "label": axis.get("label") or axis_id,
                "eit_station": station_key,
            }
    return axes


def sha256_file(path: str) -> str | None:
    """功能: 计算真源文件 SHA-256；缺失时返回 None。"""
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_manual_controls_from_eit(eit_root: str) -> dict:
    """从 manual_points.yaml 编译 11 轴与 51 机构的只读实时目录。"""
    path = os.path.join(eit_root, "config", "manual_points.yaml")
    data = read_yaml(path)
    axes: list[dict] = []
    mechanisms: list[dict] = []
    for station_key, station in (data.get("stations") or {}).items():
        for axis in station.get("axes", []) or []:
            if not axis.get("id"):
                continue
            axes.append({
                "id": axis["id"],
                "label": axis.get("label") or axis["id"],
                "station": station_key,
                "positionField": "fActPos",
                "velocityField": "fActVel",
                "jogPositiveField": "xJogPos",
                "jogNegativeField": "xJogNeg",
                "jogVelocityFixed": axis.get("jog_vel_fixed"),
                "velocityMax": axis.get("vel_max"),
            })
        for mechanism in station.get("cylinders", []) or []:
            mechanism_id = mechanism.get("id")
            if not mechanism_id:
                continue
            has_feedback_on = isinstance(mechanism.get("fb_on"), dict)
            has_feedback_off = isinstance(mechanism.get("fb_off"), dict)
            label = mechanism.get("label") or mechanism_id
            if mechanism_id == "pump_vacuum":
                kind = "pump"
            elif any(word in label for word in ("阀", "电机")):
                kind = "valve"
            else:
                kind = "cylinder"
            mechanisms.append({
                "id": mechanism_id,
                "label": label,
                "station": station_key,
                "kind": kind,
                "hasFeedbackOn": has_feedback_on,
                "hasFeedbackOff": has_feedback_off,
                "feedbackAvailable": has_feedback_on or has_feedback_off,
                "fallbackSource": "commanded" if not (has_feedback_on or has_feedback_off) else None,
            })
    return {
        "manualPointsHash": sha256_file(path),
        "axes": sorted(axes, key=lambda item: item["id"]),
        "mechanisms": sorted(mechanisms, key=lambda item: item["id"]),
    }


def collect_plc_points(eit_root: str) -> list[dict]:
    """
    功能: 读取上位机 points/plc/*.yaml 的伺服示教点(仅用于限位一致性校验).

    三种形态统一展平:
        plc_servo_target    : 条目列表, 每条带 actpos(sampling/feedlift/photo)
        plc_servo_composite : 条目 -> members[], actpos 在 member 上(spotting)
        plc_servo           : 条目列表, 无 actpos(rail 的离散召回位, 靠文件名匹配轴)
    文件里的 sync: 等字典段与本校验无关, 一律跳过.

    参数:
        eit_root: 上位机仓库根目录
    返回值: list[dict], 每条 {file, stem, key, label, node, actpos, value,
            limits_min, limits_max}
    """
    points: list[dict] = []
    for path in sorted(glob.glob(os.path.join(eit_root, "config", "points", "plc", "*.yaml"))):
        data = read_yaml(path)
        if not isinstance(data, dict):
            continue
        file_name = os.path.basename(path)
        stem = os.path.splitext(file_name)[0]

        def flatten(entry: dict, key_prefix: str = "") -> None:
            limits = entry.get("limits") or {}
            points.append({
                "file": file_name,
                "stem": stem,
                "key": f"{key_prefix}{entry.get('key', '?')}",
                "label": entry.get("label") or "",
                "node": entry.get("node"),
                "actpos": entry.get("actpos"),
                "value": entry.get("value"),
                "limits_min": limits.get("min"),
                "limits_max": limits.get("max"),
            })

        for section_value in data.values():
            if not isinstance(section_value, list):
                continue
            for entry in section_value:
                if not isinstance(entry, dict):
                    continue
                members = entry.get("members")
                if isinstance(members, list):
                    for member in members:
                        if isinstance(member, dict):
                            flatten(member, key_prefix=f"{entry.get('key', '?')}.")
                else:
                    flatten(entry)
    return points


def check_axis_limits(axes: list[dict], points: list[dict]) -> dict:
    """
    功能: 双向校验 rig_map 的 range_mm —— 既不能太小(盖不住实机), 也不能太大(超出轨道).

    两个方向的后果都不报错、只表现为"看着对但不对", 所以必须在生成期暴露:
        · 太小: 前端 MachineStateDriver.setAxisMm 用 rangeMm 做 clamp, 实机走出
          range_mm 时模型被静默钳在边界上冻住;
        · 太大: 动作页滑杆/拖拽能把滑车拖出它所骑的导轨, 观感穿模且无任何提示 ——
          历史上 axis_7y 的 [0,400] 是模组行程(CFG4-L10-100)的 4 倍、地轨 [0,3000]
          是 3.3 倍, 病根是把模组**本体长**当成了行程.

    对应规则:
        1. 主规则: 点位的 actpos == 轴的 telemetry.key(控制侧 flat 节点与 rig_map
           遥测键字面同名, 覆盖 sampling/feedlift/photo/spotting 全部点位).
        2. rail 特例: plc_servo 离散召回位没有 actpos, 按"文件名 stem == 轴
           telemetry.node 去掉 plc. 前缀"匹配, 且仅当该节点下只有一根轴(避免歧义);
           控制侧日后给这些点补上 actpos 字段后主规则自动接管, 本特例即可退役.
        3. 名义软界降级: 某条点位的 limits 跨度 > 该轴 strokeMm 时, 它不可能是物理限位
           (±500 的 spotting/photo 软界、rail 的 0~3000 拒绝阈都属此类), 降级为提示 ——
           照抄它们只会把 range 撑回"随意"的状态. 判据是数据驱动的, 不写死白名单.
           示教 value 是真实走到过的位置, **不参与降级**, 一律硬校验.
        4. 超行程反向校验: range_mm 跨度 > strokeMm 即警告. strokeMm 缺省则跳过 3/4,
           退回旧行为(只查欠覆盖), 保持对未声明该字段的轴兼容.

    参数:
        axes: manifest 的 axes 列表(取 id/label/rangeMm/strokeMm/telemetry)
        points: collect_plc_points 的产物
    返回值: dict, {"warnings": [...], "notes": [...]}
    """
    def fmt(value) -> str:
        return f"{value:g}" if isinstance(value, (int, float)) else str(value)

    def node_stem_of(axis: dict) -> str:
        node = (axis.get("telemetry") or {}).get("node") or ""
        return node[4:] if node.startswith("plc.") else node

    warnings: list[str] = []
    notes: list[str] = []

    by_actpos: dict[str, list[dict]] = {}
    by_stem: dict[str, list[dict]] = {}
    for point in points:
        if point.get("actpos"):
            by_actpos.setdefault(point["actpos"], []).append(point)
        else:
            by_stem.setdefault(point["stem"], []).append(point)

    axes_per_stem: dict[str, int] = {}
    for axis in axes:
        stem = node_stem_of(axis)
        axes_per_stem[stem] = axes_per_stem.get(stem, 0) + 1

    matched: set[int] = set()
    for axis in axes:
        telemetry_key = (axis.get("telemetry") or {}).get("key")
        stem = node_stem_of(axis)
        range_mm = axis.get("rangeMm") or [0, 0]
        lo, hi = range_mm[0], range_mm[1]
        head = f"{axis['id']}({axis.get('label', '')}) range_mm=[{fmt(lo)}, {fmt(hi)}]"
        stroke = axis.get("strokeMm")

        # ⚠ 口径转换: rangeMm 与控制侧 limits 都是**控制侧 mm**, 而 strokeMm 是**物理 mm**,
        # 两者差一个 scaleMm(见 rig_map axis_4x: 控制侧 1mm = 物理 2mm)。不乘回来就会
        # 把 4X 的 159.5 控制 mm 与 319 物理 mm 直接比, 结论碰巧"通过"但推理是错的,
        # 将来增益一改就会静默失灵。
        scale = float(axis.get("scaleMm", 1.0)) or 1.0
        unit = "mm" if scale == 1.0 else f"控制mm ×{fmt(scale)}"

        # 规则 4: 超行程反向校验(与有没有控制侧点位无关, 故排在 candidates 判空之前)
        if isinstance(stroke, (int, float)) and stroke > 0:
            span = (hi - lo) * scale
            if span > stroke + 1e-6:
                warnings.append(
                    f"{head}({unit}) 折算物理跨度 {fmt(span)} 超过模组行程 "
                    f"strokeMm={fmt(stroke)} (超 {fmt(span - stroke)}) —— 动作页能把滑车拖出导轨"
                )

        candidates = list(by_actpos.get(telemetry_key, []))
        if stem in by_stem and axes_per_stem.get(stem) == 1:
            candidates.extend(by_stem[stem])
        if not candidates:
            notes.append(
                f"{axis['id']}({axis.get('label', '')}) 在控制侧 points/plc 无对应示教点"
                f"(telemetry.key={telemetry_key}), 未校验"
            )
            continue
        for point in candidates:
            matched.add(id(point))
            where = f"{point['file']}:{point['key']}"
            lim_min, lim_max = point.get("limits_min"), point.get("limits_max")
            # 规则 3: limits 跨度大于模组行程 ⇒ 物理上不可能, 判为名义软界, 只提示
            nominal = (
                isinstance(stroke, (int, float)) and stroke > 0
                and isinstance(lim_min, (int, float)) and isinstance(lim_max, (int, float))
                and (lim_max - lim_min) * scale > stroke + 1e-6   # 同上: 折算成物理 mm 再比
            )
            if nominal:
                notes.append(
                    f"{head} 不照抄 {where} 的 limits[{fmt(lim_min)}, {fmt(lim_max)}]: "
                    f"跨度 {fmt(lim_max - lim_min)} > 模组行程 {fmt(stroke)}, 判为名义软界"
                )
            else:
                exceed = []
                if lim_min is not None and lim_min < lo:
                    exceed.append(f"limits.min={fmt(lim_min)} 越下界")
                if lim_max is not None and lim_max > hi:
                    exceed.append(f"limits.max={fmt(lim_max)} 越上界")
                if exceed:
                    warnings.append(f"{head} 无法覆盖 {where} ({'; '.join(exceed)})")
            # 示教值是实机真走到过的位置, 不受名义软界降级影响, 一律硬校验
            value = point.get("value")
            if isinstance(value, (int, float)) and not lo <= value <= hi:
                warnings.append(f"{head} 无法覆盖 {where} 示教值 value={fmt(value)}")

    for point in points:
        if id(point) not in matched:
            notes.append(
                f"控制侧点位 {point['file']}:{point['key']}"
                f"(actpos={point.get('actpos')}) 未匹配到任何轴, 未校验"
            )
    return {"warnings": warnings, "notes": notes}


#: 中转区 area <- 耗材种类。与上位机 runtime/material_store.py 的 AREAS 常量同构;
#: 那边是唯一真源, 这里改动必须同步过去(两处都只有两行, 刻意不做跨仓引用)。
AREA_BY_KIND = {"collector": "staging-a", "bottle": "staging-b"}


def load_payload_grips(path: str) -> dict:
    """读 `generated/payload-grips.json` —— 载荷相对 TOOL_MOUNT 的刚体位姿。

    由 `fit_station_alignment.py --emit-grips` 从**取料示教位姿**实测得出
    (`inv(mount_world) @ node_world`), 与 `resolve_plate_grip` 为薄层板量吸盘几何是同一件事:
    载荷对刀具的关系与工位无关, 必须显式给出而不是靠"保世界位姿换父"隐式导出。

    为什么运行期必须要它: 实时页的在途行是在 `robot_group_rack_pick` **DONE** 时才落账,
    而那个脚本以 `P7 -> P1 -> require_anchor(P1)` 收尾 —— 换父那一刻机械臂早已退回 home,
    离取料点一米开外, 保世界位姿会把托盘冻在货架的世界位置却挂在 home 的法兰下
    (现象: 托盘在虚空里跟着机械臂转)。片段(/3d/demo)不受影响是因为它的 attach 紧跟合爪,
    那一刻臂正停在示教点 —— 演示靠时刻, 实时页没有那个时刻。

    文件缺失不失败: 老构建没有它时前端退回保世界位姿(三级阶梯的最后一级), 只是刷新后
    可能错位, 不该让整个 manifest 生成挂掉。

    Returns:
        {载荷 id: {position: [3], quaternion: [4]}}; 文件不存在时为空字典
    """
    if not os.path.exists(path):
        log(f"⚠ 没有 {os.path.basename(path)}, 载荷挂载将退回保世界位姿 —— 跑 "
            f"`fit_station_alignment.py --emit-grips` 产出它")
        return {}
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    grips = doc.get("grips") or {}
    parsed: dict[str, dict] = {}
    for payload_id, entry in grips.items():
        record = {
            "position": [float(v) for v in entry["position"]],
            "quaternion": [float(v) for v in entry["quaternion"]],
        }
        # 单件锚点扩展字段(fit_item_grips 逐件产出), 类型校验后透传。白名单漏收的
        # 表现是前端磁吸静默退回 Box3 几何中心、编译器不修 dock —— 全程零报错
        # (2026-08-06 设计时点名的坑), 所以宁可在这里逐字段收全。
        free_axes = entry.get("freeAxes")
        # 空表也透传: freeAxes=[] 是"三轴全锚定"(瓶居中, 2026-08-07 定案)的显式声明,
        # 与"字段缺失"两端消费虽等价, 显式进 manifest 测试才有得断言
        if isinstance(free_axes, list) and all(
                isinstance(axis, list) and len(axis) == 3 for axis in free_axes):
            record["freeAxes"] = [[float(v) for v in axis] for axis in free_axes]
        grab_local = entry.get("grabLocal")
        if isinstance(grab_local, list) and len(grab_local) == 3:
            record["grabLocal"] = [float(v) for v in grab_local]
        if isinstance(entry.get("grabFeature"), str):
            record["grabFeature"] = str(entry["grabFeature"])
        if isinstance(entry.get("grabDiameterMm"), (int, float)):
            record["grabDiameterMm"] = float(entry["grabDiameterMm"])
        if isinstance(entry.get("halfGapOpenMm"), (int, float)):
            record["halfGapOpenMm"] = float(entry["halfGapOpenMm"])
        # 逐件闭合深度(fit_item_grips 唯一真源: 瓶颈=销贴颈 0.2543, 粉桶=摇篮同心 0.817)。
        # 漏收的表现: 编译器静默退 holdValue 0.101, 粉桶弧臂只动 1.26mm 离桶 ~9mm ——
        # 正是 2026-08-07 用户报障的"闭合离外径差很多"的一半病根。
        if isinstance(entry.get("closeValue"), (int, float)):
            record["closeValue"] = float(entry["closeValue"])
        parsed[str(payload_id)] = record
    return parsed


def build_payloads(rig_map: dict, inventory: dict, structure: dict[str, dict],
                   grips: dict | None = None) -> tuple[list[dict], list[dict]]:
    """把 inventory 展开成 attachments(可携带) + states(可显隐) 两张表。

    **两张表刻意不是同一批对象**:
      - attachments 只收"夹爪真的会去抓的东西"(rig_map.payloads 声明的 26 项)。它会被
        MachineStateDriver._bind() 全量解析、被 home() 全量 restoreLocal, 而 home() 是
        每次向后 seek 的热路径, 不放不必要的条目。
      - states 收**全部** inventory 托盘与逐孔耗材(14 + 84 = 98)。片段要在开场点亮源
        托盘的六个孔件, 而货架侧的孔件并不参与单件转移 —— 能显隐 ≠ 能被抓走。
        (这两者一度被写成同一批, 结果片段引用了没声明的 state id, 表现是"播了但孔件
        不出现"且毫无报错。web/tests/three-d/clipFamilies.test.js 锁住了这条。)

    路径一律取自已经解析好的 inventory(它自己已对缺节点硬失败), 不重复解析,
    也不允许在 payloads 段里另写一份节点路径 —— 那会变成第二份真源。

    座位键(seat)与上位机的物料坐标一一对应, 供片段编译器与实时托管账本共用:
        rack:{kind}:{plate} / staging:{area} / hole:{area}:{hole}

    Args:
        rig_map: rig_map.yaml 全文
        inventory: 已构建好的 manifest inventory 段

    Returns:
        (attachments, states) 两个列表

    Raises:
        ValueError: ref 未知, 或 grip 缺失
    """
    attachments: list[dict] = []
    states: list[dict] = []
    seen: set[str] = set()
    state_seen: set[str] = set()

    def emit_state(node_path: str, state_id: str = "") -> None:
        # 默认叶名即 id(inventory 那条路的不变量, TrayBinding 靠它反查 mountLocal);
        # 站侧座位显式给合成 id —— 它们引用的是 CAD 原名, 叶名不适合当稳定 id。
        state_id = state_id or node_path.rsplit("/", 1)[-1]
        if state_id in state_seen:
            return
        state_seen.add(state_id)
        # initial:false 与 TwinBindings._bindMaterials 的"先全部隐藏"对齐; 离线片段
        # 自己点亮要用的那几件, 实时链由物料账本快照决定。
        states.append({
            "id": state_id,
            "node": node_path,
            "property": "visible",
            "initial": False,
        })

    for entry in inventory["rack"] + inventory["staging"]:
        emit_state(entry["node"])
        for item_path in entry["items"]:
            emit_state(item_path)

    def emit(node_path: str, *, kind: str, grip: str, seat: str,
             payload_id: str = "", known_debt: str = "") -> None:
        # 叶名即 id: INV_RACK_COLLECTOR_1 / INV_STAGING_A_ITEM_3, 全局唯一。
        # 站侧座位显式给合成 id(见 emit_state 同款说明)。
        payload_id = payload_id or node_path.rsplit("/", 1)[-1]
        if payload_id in seen:
            raise ValueError(f"载荷 id 重复: {payload_id}(payloads 的 ref 有重叠)")
        seen.add(payload_id)
        payload = {"kind": kind, "grip": grip, "seat": seat}
        # 夹持位姿: 整板来自 fit_station_alignment --emit-grips(示教反解), 单件来自
        # fit_item_grips(夹爪几何+逐件抓取特征)。按语义拆两处落 manifest:
        # grabLocal/grabFeature/grabDiameterMm 是**件局部系**数据, 提升为 payload 顶层
        # 字段; mountLocal 只留 mount 系的 position/quaternion/freeAxes。操作副本 ——
        # grips 字典被两份 manifest 生成共用, 不许原地改。
        # ⚠ grabLocal 的局部系是**运行期 GLB**(machine.official-cr5.glb)的节点局部系,
        #   不是 work/machine.full.glb 的 —— 量化件两边的节点原点/scale 都不同, 混了就是
        #   几十毫米的偏差(瓶实测 37.3mm)。搬帧在 fit_item_grips.rebase_grab_local 做,
        #   本函数只透传。同一条坑见下面 mountOffsetParent 的注释。
        mount_local = (grips or {}).get(payload_id)
        if mount_local is not None:
            mount_local = dict(mount_local)
            for extra_key in ("grabLocal", "grabFeature", "grabDiameterMm",
                              "halfGapOpenMm", "closeValue"):
                if extra_key in mount_local:
                    payload[extra_key] = mount_local.pop(extra_key)
            payload["mountLocal"] = mount_local
        if known_debt:
            # 随产物进浏览器: 欠账在 manifest 里看得见, 且由单测锁死条数
            payload["knownDebt"] = known_debt
        attachments.append({"id": payload_id, "node": node_path, "payload": payload})

    for raw in rig_map.get("payloads") or []:
        ref = str(raw.get("ref") or "")
        kind = str(raw.get("kind") or "")
        grip = str(raw.get("grip") or "")
        if not grip:
            raise ValueError(f"payloads[{ref}] 缺 grip(决定夹爪 holdValue)")
        if ref == "rack":
            for entry in inventory["rack"]:
                emit(entry["node"], kind=kind, grip=grip,
                     seat=f"rack:{entry['kind']}:{entry['plate']}")
        elif ref == "staging":
            for entry in inventory["staging"]:
                emit(entry["node"], kind=kind, grip=grip, seat=f"staging:{entry['area']}")
        elif ref == "staging.items":
            for entry in inventory["staging"]:
                for hole, item_path in enumerate(entry["items"], start=1):
                    emit(item_path, kind=kind, grip=grip,
                         seat=f"hole:{entry['area']}:{hole}")
        elif ref == "rack.items":
            for entry in inventory["rack"]:
                area = AREA_BY_KIND.get(entry["kind"])
                for hole, item_path in enumerate(entry["items"], start=1):
                    emit(item_path, kind=kind, grip=grip,
                         seat=f"rackhole:{area}:{entry['plate']}:{hole}")
        else:
            raise ValueError(
                f"未知的 payloads.ref: {ref!r}(可用: rack / staging / staging.items / rack.items)"
            )

    # 站侧交接座位: 工位夹具上那一份"目的实例"。它们不属于任何托盘, 在 GLB 里是正式 CAD 的
    # 原生零件(没有 INV_* 稳定名), 所以按**叶名**解析 —— 三条硬断言就是为这条路径准备的。
    #
    # ⚠ 断言必须落在这里而不是运行期: runtime_specs 的 resolve_runtime_node 对
    #   attachments/states 是 strict=False, 解析不到就原样保留叶名; 到了浏览器
    #   _bindAttachment 只把它推进 this.missing、setState 直接短路 —— 全程零报错。
    known_debt = {str(item.get("id") or "")
                  for item in rig_map.get("station_seats_known_debt") or []}
    for raw in rig_map.get("station_seats") or []:
        seat = str(raw.get("seat") or "")
        payload_id = str(raw.get("id") or "")
        leaf = str(raw.get("node") or "")
        if not (seat and payload_id and leaf):
            raise ValueError(f"station_seats 条目缺 seat/id/node: {raw!r}")
        hits = [path for path, node in structure.items() if node["name"] == leaf]
        if len(hits) != 1:
            raise ValueError(
                f"站侧座位 {seat} 的节点 {leaf!r} 在结构清单里命中 {len(hits)} 次(要求恰好 1)"
                " —— 03 重跑后 Blender 副本后缀变了, 或出现了同名实例。"
                " 见 rig_map.station_seats 头注释的四条对策")
        node_path = hits[0]
        parent_leaf = node_path.rsplit("/", 2)[-2] if "/" in node_path else ""
        if parent_leaf != str(raw.get("parent") or ""):
            raise ValueError(
                f"站侧座位 {seat} 的父级变了: 期望 {raw.get('parent')!r}, 实际 {parent_leaf!r}"
                f"({node_path}) —— 装配被重新分组, 目的实例已不再跟着原机构走")
        debt = str(raw.get("known_debt") or "")
        if debt and debt not in known_debt:
            raise ValueError(
                f"站侧座位 {seat} 的 known_debt={debt!r} 不在 station_seats_known_debt 白名单里"
                " —— 欠账可以有, 但必须是那张表里点过名的")
        emit(node_path, kind=str(raw.get("kind") or "item"),
             grip=str(raw.get("grip") or ""), seat=seat,
             payload_id=payload_id, known_debt=debt)
        emit_state(node_path, payload_id)
    return attachments, states


def build_manifest(config: dict, eit_root: str) -> dict:
    """
    功能: 汇总三方数据构造完整的 manifest.
    参数:
        config: pipeline 配置
        eit_root: 上位机仓库根目录
    返回值: dict, manifest 内容
    """
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    rig_map = read_yaml(os.path.join(pipeline_dir, "rig_map.yaml"))
    if rig_map.get("schema") != "ptlc.rigmap/v2":
        raise ValueError(f"rig_map schema 必须是 ptlc.rigmap/v2: {rig_map.get('schema')}")
    structure = load_structure(os.path.join(config["paths"]["work"], "structure.json"))
    # 吸盘持板几何要读 GLB 的节点旋转 —— structure.json 只有世界包围盒中心, 没有朝向
    # (与 scene_kinematics 头注释同一条理由)。用的是 03 full 的产物, 与 structure.json 同源。
    full_glb = os.path.join(config["paths"]["work"], "machine.full.glb")
    if not os.path.isfile(full_glb):
        raise SystemExit(f"错误: 未找到 {full_glb}\n请先运行 03_clean_model.py --stage full")
    plate_grip = resolve_plate_grip(rig_map, structure, GlbScene(full_glb))
    plate_contact_ignore = resolve_plate_contact_ignore(rig_map, structure)
    clearance = load_plate_clearance(config["paths"]["work"])
    eit_axes = collect_axes_from_eit(eit_root)
    manual_controls = collect_manual_controls_from_eit(eit_root)
    action_prefixes, action_names = collect_action_prefixes(eit_root)

    # 整机包围盒: 取所有 ST_* 根节点的并集
    xs, ys, zs = [], [], []
    for path, node in structure.items():
        if "/" in path or not node["name"].startswith("ST_"):
            continue
        center, size = node.get("center"), node.get("size")
        if not center or not size:
            continue
        for i, arr in enumerate((xs, ys, zs)):
            arr.extend([center[i] - size[i] / 2, center[i] + size[i] / 2])
    machine_bounds = {
        "center": [round((min(a) + max(a)) / 2, 3) for a in (xs, ys, zs)],
        "size": [round(max(a) - min(a), 3) for a in (xs, ys, zs)],
    }

    # -- 工位 ---------------------------------------------------------------
    stations = []
    for spec in rig_map.get("stations", []):
        station_id = spec["id"]
        root_path = f"ST_{station_id}"
        node = structure.get(root_path)
        if node is None:
            # ST_ROBOT 这类嵌套工位(挂在地轨滑车之下, 真实路径是
            # ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT)按叶名兜底 —— 此前直接
            # continue 把 ROBOT 整条丢了, 21 个 robot.* 动作都没进 manifest.
            nested_path = find_node(structure, root_path)
            if nested_path:
                node = structure.get(nested_path)
                root_path = nested_path
        if node is None:
            continue

        # 没有任何几何的工位(如泵站, 其实体在柜内且未单独建组): 仍然保留条目以便展示
        # 遥测与动作, 但不给三维节点路径, 免得前端徒劳查找后报"节点缺失".
        has_geometry = bool(node.get("size")) and max(node.get("size") or [0]) > 1e-4

        # 该工位下的状态灯
        light_path = find_node(structure, f"LIGHT_STATUS_{station_id}")

        # 该工位对应的动作前缀与动作清单
        prefixes: list[str] = []
        names: list[str] = []
        for group, station in ACTION_GROUP_TO_STATION.items():
            if station == station_id:
                prefixes.extend(action_prefixes.get(group, []))
                names.extend(action_names.get(group, []))

        stations.append(
            {
                "id": station_id,
                "nodeId": spec.get("node_id"),
                "label": spec.get("label") or STATION_LABELS.get(station_id, station_id),
                "glbNode": root_path if has_geometry else None,
                "hasGeometry": has_geometry,
                "statusLight": light_path,
                "camera": camera_preset(node, machine_bounds) if has_geometry else {},
                "actionPrefixes": sorted(set(prefixes)),
                "actions": sorted(set(names)),
                "bounds": {"center": node.get("center"), "size": node.get("size")},
            }
        )

    # 03 报告(Blender full 阶段的实测产出)在下面多处要用: 轴的 CARRIAGE 真名、
    # 机器人关节链、展缸盖的架/层配对与几何量 —— 统一在这里读一次.
    clean_report = {}
    report_path = os.path.join(config["paths"]["work"], "03_clean_model.report.json")
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as handle:
            clean_report = json.load(handle)

    # -- 展缸 ---------------------------------------------------------------
    # 缸号 → 盖气缸机构 id: 由 03 报告的 tank_lids 段给出(架/层配对是那里定的),
    # 前端据此把 mechanism_state 的开/关反馈显示到对应缸上 —— 没有这条映射就只能
    # 在"展缸1气缸1"这种 PLC 名和"展缸 1"这种缸号之间靠人脑对.
    lid_mechanism_by_tank = {
        str(entry.get("tank")): entry.get("id")
        for entry in ((clean_report.get("tank_lids") or {}).get("tanks") or [])
        if entry.get("tank") and entry.get("id")
    }
    tanks = []
    for index in range(1, (rig_map.get("tanks", {}) or {}).get("expect_count", 8) + 1):
        tank_path = find_node(structure, f"TANK_{index}")
        liquid_path = find_node(structure, f"LIQUID_{index}")
        if tank_path is None:
            continue
        tanks.append(
            {
                "index": index - 1,          # 与上位机 Tank_State 数组下标对齐(0 基)
                "id": f"tank{index}",
                "label": f"展缸 {index}",
                "glbNode": tank_path,
                "liquidNode": liquid_path,
                "lidMechanismId": lid_mechanism_by_tank.get(f"TANK_{index}"),
                "stateFrom": {"node": "plc.develop", "key": "Tank_State", "index": index - 1},
            }
        )

    # 液面的体积↔高度换算契约. 腔体尺寸由 03 的体素扫描实测(build_tanks.
    # measure_trough_cavity), 这里只做搬运 —— CAD 改了跟着变, 前端不写死任何毫米数.
    # 注意 freeAreaMm2 是**实测自由截面积**, 不等于液面盒的底面积(盒是把非矩形的自由
    # 空间拟合成的矩形). 前端一律用它反算高度, 盒只负责画; 这样体积是准的.
    tanks_section = clean_report.get("tanks") or {}
    cavity = tanks_section.get("liquid_cavity")
    tank_liquid = None
    if cavity and any(tank.get("liquidNode") for tank in tanks):
        tank_liquid = {
            "cavity": {
                "floorZMm": cavity["floor_z_mm"],
                "rimZMm": cavity["rim_z_mm"],
                "usableDepthMm": cavity["usable_depth_mm"],
                "freeAreaMm2": cavity["free_area_mm2"],
                "capacityMl": cavity["capacity_ml"],
                "mlPerMm": cavity["ml_per_mm"],
            },
            # 观感放大系数: 视觉高度 = 物理高度 × 本值, 到槽口封顶. 面板显示的 mL 不受影响.
            "exaggeration": tanks_section.get("liquid_exaggeration", 1.0),
            "pipeHoldupMl": tanks_section.get("liquid_pipe_holdup_ml", 0.0),
            "tankArg": TANK_LIQUID_TANK_ARG,
            "actions": TANK_LIQUID_ACTIONS,
        }

    # -- 驻位液体(座位实例内的液面, 通用表) ---------------------------------
    # 几何与 cavity 由 03 的 build_station_bottle_liquid 产出(声明值, 非实测 —— 光壁
    # 玻璃瓶内腔无可测特征, 与 pumps 段针筒"厂家额定值"同理), 这里只搬运并解析节点路径.
    # 与 tankLiquid 的分工: 那是"8 个展缸共用一份实测 cavity"的专表, 一字不动;
    # 本表逐条自带 cavity/exaggeration/动作规则, 前端 MachineStateDriver._bindLiquids
    # 与 clip_compiler 两处都按"查得到就用, 查不到走老路"消费 —— 整段可一键回退
    # (rig_map 座位 liquid.enabled=false → 03 不建液柱 → 本表为空).
    liquids = []
    for item in ((clean_report.get("bottle_liquid") or {}).get("items") or []):
        leaf = str(item.get("node") or "")
        liquid_path = find_node(structure, leaf)
        if liquid_path is None:
            # 与 station_seats 同纪律: 显式声明解析不到必须硬失败, 不能静默缺条目
            raise ValueError(
                f"驻位液体: 03 报告声明了液柱 {leaf!r}, 结构清单里却找不到 —— "
                "GLB 与 03 报告不同批? 重跑 03_clean_model.py --stage full")
        seat = str(item.get("seat") or "")
        item_cavity = item.get("cavity") or {}
        liquids.append({
            "id": f"liq_{seat.replace('-', '_')}",
            "node": liquid_path,
            "seat": seat,
            "attachmentId": item.get("attachment_id"),
            "cavity": {
                "usableDepthMm": item_cavity["usable_depth_mm"],
                "freeAreaMm2": item_cavity["free_area_mm2"],
                "capacityMl": item_cavity["capacity_ml"],
                "mlPerMm": item_cavity["ml_per_mm"],
            },
            "exaggeration": item.get("exaggeration", 1.0),
            "actions": STATION_LIQUID_ACTIONS.get(seat, {}),
        })

    # -- 耗材内容物(粉桶里的硅胶粉) -----------------------------------------
    # 几何与 cavity/chamber 由 03 的 build_station_powder 产出(腔段实测、内径按内衬声明),
    # 观感与单位契约由 CONSUMABLE_CONTENT_KINDS 发放, 这里只做合流与节点路径解析.
    # 与 liquids 同一条降级纪律: rig_map 座位 powder.enabled=false → 03 不建粉柱 →
    # 本段为空 → 两条链都空跑不报错(片段里粉通道照样在, 数据仍在账本里).
    consumable_kinds = []
    for item in ((clean_report.get("station_powder") or {}).get("items") or []):
        leaf = str(item.get("node") or "")
        powder_path = find_node(structure, leaf)
        if powder_path is None:
            # 与驻位液体同纪律: 显式声明解析不到必须硬失败, 不能静默缺条目
            raise ValueError(
                f"耗材内容物: 03 报告声明了粉柱 {leaf!r}, 结构清单里却找不到 —— "
                "GLB 与 03 报告不同批? 重跑 03_clean_model.py --stage full")
        seat = str(item.get("seat") or "")
        spec = CONSUMABLE_CONTENT_KINDS.get(seat) or {}
        item_cavity = item.get("cavity") or {}
        consumable_kinds.append({
            "id": f"powder_{seat.replace('-', '_')}",
            "node": powder_path,
            "seat": seat,
            "attachmentId": item.get("attachment_id"),
            "kind": spec.get("kind", "powder"),
            "label": spec.get("label", ""),
            "accepts": spec.get("accepts", "collector"),
            # 键名与液体那套**故意不同名**, 理由见 CONSUMABLE_CONTENT_KINDS 的头注
            "cavity": {
                "usableDepthMm": item_cavity["usable_depth_mm"],
                "freeAreaMm2": item_cavity["free_area_mm2"],
                "capacityMm3": item_cavity["capacity_mm3"],
                "mm3PerMm": item_cavity["mm3_per_mm"],
            },
            # 腔段(item 局部轴向, 米): 粉恒定贴 c1 端(吹气头那一头), 故要两端不只要深度
            "chamber": item.get("chamber") or {},
            "exaggeration": spec.get("exaggeration", 1.0),
            "bulkFactor": spec.get("bulkFactor", 1.0),
            "elutedColor": spec.get("elutedColor", ""),
        })

    # -- 注射泵 -------------------------------------------------------------
    pump_syringe = resolve_pump_syringe(rig_map, structure, clean_report,
                                        collect_pump_speeds(eit_root))

    # -- 运动轴 -------------------------------------------------------------
    # 用 03 报告的真名定位: 多轴之后 CARRIAGE 空对象会被 Blender 唯一化改名
    # (CARRIAGE.001 等), 叠轴(parent_axis)的路径还会嵌套, 字面拼路径只对第一根轴成立.
    # 报告里该段是 build_axis_carriages 的整体返回 {"axes": [...]}, 故要多剥一层
    axes_section = clean_report.get("axes") or {}
    axes_entries = axes_section.get("axes") if isinstance(axes_section, dict) else axes_section
    axes_report = {
        entry.get("id"): entry
        for entry in (axes_entries or [])
        if isinstance(entry, dict)
    }

    axes = []
    for spec in rig_map.get("axes", []):
        axis_id = spec["id"]
        eit_info = eit_axes.get(axis_id, {})
        carriage_path = None
        if spec.get("rigged"):
            recorded = (axes_report.get(axis_id) or {}).get("carriage_node")
            if recorded:
                carriage_path = find_node(structure, recorded)
            if carriage_path is None:
                literal = f"ST_{spec['station']}/AXIS_{axis_id.upper()}/CARRIAGE"
                if literal in structure:
                    carriage_path = literal
                else:
                    # 宁可判未装配也不能按名字盲抓别的轴的 CARRIAGE 绑错对象
                    log(f"警告: 轴 {axis_id} 的 CARRIAGE 无法定位(报告未记录且字面路径不存在), 按未装配处理")

        range_mm = spec.get("range_mm", [0, 0])
        travel_m = spec.get("travel_m")
        span_mm = max(range_mm[1] - range_mm[0], 1e-6)
        # mm -> 场景单位(米)的比例: 若声明了模型上的实际行程, 按行程等比映射;
        # 否则按 1 mm = 0.001 m 的物理比例(适用于模型与实机 1:1 的轴)
        mm_to_unit = (travel_m / span_mm) if travel_m else 0.001

        entry = {
            "id": axis_id,
            "station": spec["station"],
            "label": spec.get("label") or eit_info.get("label") or axis_id,
            "glbNode": carriage_path,
            "rigged": bool(spec.get("rigged")) and carriage_path is not None,
            "axis": spec.get("axis", [1, 0, 0]),
            "sign": spec.get("sign", 1),
            "mmToUnit": round(mm_to_unit, 8),
            "zeroOffsetMm": spec.get("zero_offset_mm", 0.0),
            # 增益: 控制侧 1mm 折算成几个物理 mm. 缺省 1.0 = 控制侧就是真毫米.
            # 唯一非 1 的是 axis_4x(=2.0, 2026-08-06 卡尺实测 11.28→22.6 定案) ——
            # 那根轴是自制同步带 + 步进, 标度把每转行程配成了实际的一半.
            # sign 保持纯方向语义(±1), 增益单列, 别把两者混在一起.
            # ⚠ 这是临时补偿, 4X/5Z 换伺服后要改回 1.0, 见
            #   docs/上样4X_5Z临时标度增益_换伺服后作废_20260806.md
            "scaleMm": float(spec.get("scale_mm", 1.0)),
            "rangeMm": range_mm,
            # 该轴所骑直线模组/导轨的物理行程(mm). range_mm 的硬上界, 也是判定
            # 控制侧 limits 是否为"名义软界"的依据, 见 check_axis_limits.
            # 缺省(未声明)时下游一律跳过这两条校验, 不做任何推断.
            "strokeMm": spec.get("stroke_mm"),
            "telemetry": spec.get("telemetry", {}),
        }
        # 几何下界: 再往下滑车驮的板会扎进固定结构(实测, 见 verify_plate_clearance)。
        #
        # 与 rangeMm 分开表达而不是把 rangeMm 收窄: rangeMm 镜像控制侧 limits, 是真源,
        # 三维不得擅自改它 —— 实机确实能走到 −50。这里只约束**画面**: 差额来自简化的
        # 200×200 实心板盒(实机放置板在光电处有让位孔), 属于模型精度, 不是机器的事。
        # 标定页走 setAxisMm 的 unclamped 分支, 不受本条影响, 仍能试探全行程。
        geometry_min = (clearance.get(axis_id) or {}).get("minAxisMm")
        if geometry_min is not None and geometry_min > range_mm[0]:
            entry["geometryMinMm"] = round(float(geometry_min), 3)
        axes.append(entry)

    # -- 机器人与可更换工具 --------------------------------------------------
    # 关节枢轴/轴向只存在于 03 步的报告里(blender_clean.build_robot_joints 产出),
    # structure.json 只有层级与包围盒; clean_report 已在运动轴一节提前载入.
    robot_spec = rig_map.get("robot", {}) or {}

    joints_info = clean_report.get("robot_joints") or {}
    joints = [
        {
            "id": joint["id"],
            "node": joint["node"],
            "originNode": joint.get("origin_node"),
            "linkNode": joint.get("link_node"),
            # 官方关节全是 local-Z；Blender Z-up 导出 glTF 后为 local-Y。
            "axis": joint["axis"],
            "sign": joint.get("sign", 1),
            "zeroOffsetDeg": joint.get("zero_offset_deg", 0.0),
            "limitDeg": joint.get("limit_deg", [-360.0, 360.0]),
            "originXyzM": joint.get("origin_xyz_m"),
            "originRpyRad": joint.get("origin_rpy_rad"),
        }
        for joint in joints_info.get("joints", [])
    ]
    rigged = bool(joints_info.get("rigged")) and len(joints) == 6
    robot = {
        "id": "robot",
        "label": "机械臂 (DOBOT CR5)",
        "glbNode": find_node(structure, "ST_ROBOT") or "ST_ROBOT",
        "jointsRigged": rigged,
        "kinematicsSource": joints_info.get("kinematics_source"),
        "baseTransform": joints_info.get("base_transform", {}),
        "referencePointHash": joints_info.get("reference_point_hash"),
        "calibrationVersion": joints_info.get("calibration_version"),
        "joints": joints,
        "flangeNode": joints_info.get("flange_node", "CR5_LINK6"),
        "toolMount": (joints_info.get("tool_mount") or {}).get("node"),
        "toolMountTransform": joints_info.get("tool_mount_transform", {}),
        "customMountAlignment": joints_info.get("custom_mount_alignment", {}),
        "toolTransforms": joints_info.get("tool_transforms", {}),
        "telemetry": robot_spec.get("telemetry", {}),
        "note": (
            "关节链来自固定提交的 Dobot CR5 xacro；ORIGIN/ROTOR 刚体链与实机点表标定"
            if rigged
            else "官方 CR5 关节链尚未成功构建"
        ),
    }
    tools = []
    tool_specs = {item.get("id"): item for item in rig_map.get("tools", [])}
    for tool in (clean_report.get("tools") or {}).get("tools", []):
        if not tool.get("found"):
            continue
        source_spec = tool_specs.get(tool["id"], {})
        mount_transform = source_spec.get("mount_transform") or {}
        declaration = {
            "id": tool["id"],
            "controllerTool": source_spec.get("controller_tool"),
            "label": tool.get("label", tool["id"]),
            "glbNode": find_node(structure, tool["node"]) or tool["node"],
            "dockNode": tool.get("dock_node"),
            "dock": tool.get("dock"),
            "mountNode": (joints_info.get("tool_mount") or {}).get("node") or "TOOL_MOUNT",
        }
        if mount_transform.get("position_m") is not None:
            declaration["mountPosition"] = mount_transform["position_m"]
        if mount_transform.get("quaternion_xyzw") is not None:
            declaration["mountQuaternion"] = mount_transform["quaternion_xyzw"]
        if mount_transform.get("source"):
            declaration["mountCalibration"] = mount_transform["source"]
        tools.append(declaration)

    def resolve_runtime_node(value, *, strict=False, owner=""):
        """把 rig_map 的叶名解析成实际 GLB 路径；空值保持为空。

        strict=True 时解析失败直接 raise —— actuators/linkages 是几何绑定,
        静默回退原值会让前端"按叶名兜底也查不到"而机构一动不动, 且全程零报错.
        """
        if not isinstance(value, str) or not value:
            return value
        resolved = find_node(structure, value)
        if resolved is None:
            if strict:
                raise ValueError(
                    f"rig_map {owner} 的节点未进入结构清单: {value}"
                    "(检查 03 full 是否已重跑、build 块是否命中)"
                )
            return value
        return resolved

    def runtime_specs(key: str) -> list[dict]:
        """复制通用驱动声明，并把其中的节点引用解析为浏览器可用路径。

        actuators/linkages 以 strict 解析(见 resolve_runtime_node); 其 build/catalog
        块分别是 blender_clean / 本脚本的输入, 剥掉后才进浏览器产物。
        """
        strict = key in ("actuators", "linkages")
        result = []
        for raw in rig_map.get(key, []) or []:
            item = copy.deepcopy(raw)
            owner = f"{key}[{item.get('id')}]"
            item.pop("build", None)
            item.pop("catalog", None)
            # plate_grip 是**匹配器声明**, 浏览器要的是它解出来的实测值(plateGrip),
            # 与 build/catalog 同理: 输入块剥掉, 只把产物送进产物。
            item.pop("plate_grip", None)
            if plate_grip and item.get("id") == plate_grip[0]:
                item["plateGrip"] = plate_grip[1]
            for field in ("node", "glbNode", "parent", "defaultParent"):
                if field in item:
                    item[field] = resolve_runtime_node(item[field], strict=strict, owner=owner)
            for member in item.get("members", []) or []:
                for field in ("node", "glbNode"):
                    if field in member:
                        member[field] = resolve_runtime_node(member[field], strict=strict, owner=owner)
            result.append(item)
        return result

    def solve_lid_kinematics(kin: dict, lift_mm: float) -> tuple[float, float, float]:
        """曲柄滑块提盖: 由抬升 h 反解滑车行程 s 与摆角 θ.

        三者被 |铰点−枢轴|=R 一条约束锁死, 只有一个自由度 —— 这就是动作页只该
        暴露一个主参数的原因(分别调会让盖与摆臂脱节, 表现为连接处错位)。
        与 web/src/three-d/motion/linkageKinematics.js 是同一组公式, 改一处必须改另一处。
        """
        d0 = float(kin["d0Mm"])
        v0 = float(kin["v0Mm"])
        radius = float(kin["radiusMm"])
        max_lift = float(kin["maxLiftMm"])
        min_lift = float(kin.get("minLiftMm", 0.0))
        if not (min_lift <= lift_mm <= max_lift):
            raise ValueError(
                f"展缸盖抬升 {lift_mm}mm 越界 [{min_lift}, {max_lift}]mm"
                f"(摆臂半径 {radius}mm 扣奇异余量 {kin.get('singularMarginMm')}mm)"
            )
        travel = math.sqrt(max(radius ** 2 - (v0 - lift_mm) ** 2, 0.0)) - d0
        theta = math.degrees(math.asin((d0 + travel) / radius) - math.asin(d0 / radius))
        return lift_mm, travel, theta

    def tank_lid_linkages() -> list[dict]:
        """从 03 报告的 tank_lids 段展开 8 条展缸盖 linkage(id=PLC 的 dev_t*_cyl*).

        分工: 03 只管**实测几何**(枢轴/铰点/半径/成员归属, 变了必须重跑 Blender),
        运动参数(抬升/行程/摆角)在这里按 rig_map 的 lift_mm 现值重算 —— 所以调开度
        只需重跑 manifest 两步+部署(秒级), 与轴的 sign/zero_offset 调参同一节奏.

        不带 catalog(条目已在上位机 manual_points 的 51 机构目录里), rigged 由并入
        rigged_mechanisms 集合翻真.
        """
        cfg = rig_map.get("tank_lids") or {}
        if not cfg.get("enabled"):
            return []
        section = clean_report.get("tank_lids") or {}
        entries = section.get("tanks") or []
        if not section.get("enabled") or not entries:
            raise ValueError(
                "rig_map.tank_lids 已启用, 但 work/03_clean_model.report.json 没有 "
                "tank_lids 产出 —— 先重跑 03_clean_model.py --stage full, "
                "防止 manifest 与 GLB 漂移"
            )
        result = []
        for entry in entries:
            linkage = copy.deepcopy(entry.get("linkage") or {})
            owner = f"tank_lids[{linkage.get('id')}]"
            if not linkage.get("id") or not linkage.get("members"):
                raise ValueError(f"03 报告 {owner} 条目缺 id/members")
            kin = linkage.get("kinematics") or {}
            roles = kin.get("roles") or []
            if len(roles) != len(linkage["members"]):
                raise ValueError(f"{owner} 的 kinematics.roles 与 members 不同长")
            lift_declared = cfg.get("lift_mm")
            if lift_declared is not None:
                lift, travel, theta = solve_lid_kinematics(kin, float(lift_declared))
                kin.update({
                    "liftMm": round(lift, 2),
                    "travelMm": round(travel, 2),
                    "thetaDeg": round(theta, 2),
                })
                # 反相语义: 值 1=关盖=GLB 基准态(输出 0) —— outputRange 一律 [行程, 0]
                by_role = {"rocker": round(theta, 2), "lid": round(lift, 2),
                           "carriage": round(travel, 2)}
                for member, role in zip(linkage["members"], roles):
                    if role not in by_role:
                        raise ValueError(f"{owner} 未知成员角色 {role}")
                    member["outputRange"] = [by_role[role], 0]
            linkage["transitionS"] = float(cfg.get("transition_s", linkage.get("transitionS", 1.0)))
            for member in linkage["members"]:
                member["node"] = resolve_runtime_node(member["node"], strict=True, owner=owner)
            result.append(linkage)
        return result

    lid_linkages = tank_lid_linkages()
    lid_ids = {item["id"] for item in lid_linkages}

    rigged_mechanisms = {
        item.get("id")
        for key in ("actuators", "linkages")
        for item in (rig_map.get(key, []) or [])
        if item.get("id")
    } | lid_ids
    rigged_axes = {item["id"] for item in axes if item.get("rigged")}
    realtime_axes = [
        {**item, "rigged": item["id"] in rigged_axes}
        for item in manual_controls["axes"]
    ]
    # 机器人末端执行器不在上位机 manual_points.yaml 的 51 机构目录里(它们走机器人
    # DO2/DO6), 其 realtime 目录条目从 rig_map 带 catalog 块的条目派生 —— 前端
    # MechanismStateStore 按 knownIds 过滤事件, 不进目录的 id 会被静默丢弃。
    plc_mechanism_ids = {item["id"] for item in manual_controls["mechanisms"]}
    # 展缸盖复用 PLC 目录 id: 必须逐字存在, 防拼错/架-缸配对漂移出"永不驱动"的幽灵条目
    missing_lid_ids = sorted(lid_ids - plc_mechanism_ids)
    if missing_lid_ids:
        raise ValueError(
            f"tank_lids 的机构 id 不在上位机 manual_points 目录: {missing_lid_ids}"
        )
    robot_mechanisms = []
    # mechanisms_catalog 是**纯目录段**: 有实时状态但没有几何的机构(如吸盘真空 rob_suction)。
    # 它刻意不进上面的 rigged_mechanisms(那里只扫 actuators/linkages), 于是自然 rigged:false ——
    # 放进 actuators 会被标成 rigged:true, 然后 MachineStateDriver._bind 把它计入 missing、
    # TwinBindings._updateMechanisms 每帧告警, 制造一个永远驱动不了的"幽灵条目"。
    for key in ("actuators", "linkages", "mechanisms_catalog"):
        for item in rig_map.get(key, []) or []:
            catalog = item.get("catalog")
            if not catalog:
                continue
            mech_id = item.get("id")
            if mech_id in plc_mechanism_ids:
                raise ValueError(f"rig_map {key} 的机构 id 与 PLC 目录冲突: {mech_id}")
            entry = {
                "id": mech_id,
                "label": catalog.get("label") or item.get("label") or mech_id,
                "station": catalog.get("station", "robot"),
                "kind": catalog.get("kind", "cylinder"),
                "hasFeedbackOn": bool(catalog.get("hasFeedbackOn", False)),
                "hasFeedbackOff": bool(catalog.get("hasFeedbackOff", False)),
                "feedbackAvailable": bool(catalog.get("feedbackAvailable", False)),
                "fallbackSource": catalog.get("fallbackSource", "commanded"),
            }
            # 夹爪三态: 前端持料状态机按 mounted tool(2/3)反查机构 id, 契约随目录下发
            if catalog.get("controllerTool") is not None:
                entry["controllerTool"] = int(catalog["controllerTool"])
            robot_mechanisms.append(entry)
    realtime_mechanisms = [
        {**item, "rigged": item["id"] in rigged_mechanisms}
        for item in manual_controls["mechanisms"] + robot_mechanisms
    ]

    inventory_cfg = rig_map.get("inventory") or {}
    consumable_cfg = inventory_cfg.get("consumables") or {}
    holes_per_tray = int(consumable_cfg.get("holesPerTray", 6))
    inventory = {
        "rack": [],
        "staging": [],
        "magazines": [],
        "visibleStates": consumable_cfg.get("visibleStates", ["FRESH"]),
        "visibleWhenSampleId": bool(consumable_cfg.get("visibleWhenSampleId", True)),
    }

    def item_paths(owner_node: str) -> list[str]:
        paths = []
        for hole in range(1, holes_per_tray + 1):
            item_name = f"{owner_node}_ITEM_{hole}"
            item_path = find_node(structure, item_name)
            if item_path is None:
                raise ValueError(f"托盘耗材节点未进入结构清单: {item_name}")
            paths.append(item_path)
        return paths

    for kind, entries in (inventory_cfg.get("rack") or {}).items():
        for raw in entries or []:
            node_path = find_node(structure, raw["node"])
            if node_path is None:
                raise ValueError(f"物料托盘节点未进入结构清单: {raw['node']}")
            inventory["rack"].append({
                "kind": kind,
                "plate": int(raw["plate"]),
                "node": node_path,
                "items": item_paths(raw["node"]),
            })
    for raw in inventory_cfg.get("staging") or []:
        node_path = find_node(structure, raw["node"])
        if node_path is None:
            raise ValueError(f"中转托盘节点未进入结构清单: {raw['node']}")
        inventory["staging"].append({
            "area": raw["area"],
            "kind": raw["kind"],
            "node": node_path,
            "items": item_paths(raw["node"]),
        })
    for raw in inventory_cfg.get("magazines") or []:
        node_path = find_node(structure, raw["node"])
        if node_path is None:
            raise ValueError(f"板仓模板节点未进入结构清单: {raw['node']}")
        node_info = structure[node_path]
        # 模板就是正式 CAD 玻璃板，堆叠间距取它的真实厚度，不手填近似尺寸。
        size = node_info.get("size") or [0, 0, 0]
        magazine = {
            "id": raw["id"],
            "node": node_path,
            "stackAxis": raw.get("stackAxis", [0, 1, 0]),
            "stackSign": raw.get("stackSign", 1),
            "spacingM": round(float(size[1]), 8),
        }
        # 托边交接: 板不被滑车顶着时坐的固定托边(verify_plate_clearance 实测)。前端
        # MachineStateDriver 据此在轴低于交接值时把板托在托边高度 —— 板停、滑车继续走,
        # 否则板堆随滑车穿过托边(2026-08-07 用户报的穿模)。容缺姿态同 load_plate_clearance:
        # 字段缺席就不写, 前端退回"刚性随滑车"的老行为, 不会画错只是少这层修正。
        ledge_entry = next(
            (item for item in clearance.values() if item.get("id") == raw["id"]), None)
        ledge_axis = (ledge_entry or {}).get("ledgeAxisMm")
        if ledge_axis is not None:
            magazine["axisId"] = ledge_entry["axisId"]
            magazine["ledgeAxisMm"] = round(float(ledge_axis), 3)
        else:
            log(f"警告: 料仓 {raw['id']} 缺 ledgeAxisMm 实测 —— 前端板堆将退回刚性随滑车; "
                "跑 verify_plate_clearance.py 补测")
        inventory["magazines"].append(magazine)

    # 上样孔板(24 孔深孔板): 节点名与孔栅格由 03 步实测后写进报告, 这里只透传 ——
    # 前端要做"当前吸的是哪个孔"的高亮/液位就靠它, 不必自己按规格再算一遍孔心
    # (算两遍迟早漂, 且漂了不报错). 控制侧的孔位下发走的是 config/calibration.yaml
    # 的仿射标定, **与这里无关** —— 本段只描述三维里画了什么, 不是下发依据.
    sample_cfg = clean_report.get("sample_plates") or {}
    for raw in sample_cfg.get("slots") or []:
        node_path = find_node(structure, raw["node"])
        if node_path is None:
            raise ValueError(f"上样孔板节点未进入结构清单: {raw['node']}")
        inventory.setdefault("samplePlates", []).append({
            "slot": int(raw["slot"]),
            "node": node_path,
            "spec": raw["spec"],
            "seatZM": round(float(raw["seat_z_mm"]) / 1000.0, 8),
            "topZM": round(float(raw["top_z_mm"]) / 1000.0, 8),
            "wells": [{"well": w["well"], "row": w["row"], "col": w["col"],
                       "centerM": w["center"]} for w in raw.get("wells") or []],
        })
    if sample_cfg.get("slots"):
        inventory["samplePlateSpec"] = {
            "installed": sample_cfg["installed"],
            "label": sample_cfg["label"],
            "grid": sample_cfg["grid"],
            "pitchMm": sample_cfg["pitch_mm"],
            "wellTopMm": sample_cfg["well_top_mm"],
            "wellDepthMm": sample_cfg["well_depth_mm"],
            "heightMm": sample_cfg["height_mm"],
            "footprintMm": sample_cfg["footprint_mm"],
            "wellVolumeMl": sample_cfg["well_volume_ml"],
        }

    # 夹持位姿由 fit_station_alignment --emit-grips 从取料示教位姿实测, 这里只透传。
    # 它与 GLB 同源(同一份 machine.full.glb), 但产出在管线之外, 所以缺失不失败。
    grips = load_payload_grips(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "generated", "payload-grips.json"))
    payload_attachments, payload_states = build_payloads(rig_map, inventory, structure, grips)

    signal_light = resolve_signal_light(rig_map, structure)
    lights = resolve_lights(rig_map, structure)
    spindles = resolve_spindles(rig_map, structure)

    return {
        "version": 2,
        # 构建戳: 前端消费页拿它当模型 URL 的 cache-buster(?v=generatedAt) —— manifest
        # 每次加载都带 ?t= 强刷, 模型只在真出新构建时失效缓存. merge_preserving 不保留它.
        "generatedAt": int(time.time()),
        "generatedFrom": {
            "structure": "work/structure.json",
            "rigMap": "pipeline/rig_map.yaml",
            "rigMapSchema": rig_map.get("schema"),
            "eitRoot": "PTLC_CONTROL_ROOT",
            "referencePointHash": joints_info.get("reference_point_hash"),
            "kinematicsCommit": (joints_info.get("kinematics_source") or {}).get("commit"),
            "manualPointsHash": manual_controls.get("manualPointsHash"),
        },
        "units": {"sceneUnit": "m"},
        "machine": {"label": "PTLC 自动化设备", "bounds": machine_bounds},
        "healthStyles": HEALTH_STYLES,
        "tankStateStyles": TANK_STATE_STYLES,
        "tankLiquid": tank_liquid,
        "liquids": liquids,
        "consumableContents": {"kinds": consumable_kinds},
        "pumpSyringe": pump_syringe,
        "stations": stations,
        "tanks": tanks,
        "axes": axes,
        "robot": robot,
        "tools": tools,
        "inventory": inventory,
        "nodes": runtime_specs("nodes"),
        "actuators": runtime_specs("actuators"),
        "linkages": runtime_specs("linkages") + lid_linkages,
        "attachments": runtime_specs("attachments") + payload_attachments,
        "states": runtime_specs("states") + payload_states,
        "sockets": runtime_specs("sockets"),
        "signalLight": signal_light,
        "lights": lights,
        "spindles": spindles,
        # 柔性接触的排除集(见 resolve_plate_contact_ignore 与 rig_map 的 plate_contact 段)
        "plateContactIgnore": plate_contact_ignore,
        "realtime": {
            "protocol": "ptlc.realtime/v1",
            "renderDelayMs": 100,
            "staleMs": 500,
            "events": ["robot_pose", "axis_pose", "mechanism_state", "material_state", "signal_light",
                       "scrape_state"],
            "materialHeartbeatMs": 5000,
            "materialStaleMs": 12000,
            "telemetryFallbackHz": 1,
            "axes": realtime_axes,
            "mechanisms": realtime_mechanisms,
        },
    }


# 重跑时需要保留的手工字段(这些只能靠目视核对得出, 不应被自动生成覆盖)
PRESERVE_FIELDS = {
    "stations": ["camera"],
    "axes": ["sign", "zeroOffsetMm", "mmToUnit"],
}


def merge_preserving(generated: dict, existing: dict) -> dict:
    """
    功能: 用已存在的 manifest 中的手工字段覆盖新生成的对应字段.

    人工标记有两种形制, 对应两类写入方:
        dict 值字段(stations.camera): 实时页「保存视角」在字段**内部**写 manual: true
            (stationViewWriter.js 的定点文本补丁), 标记随字段自体存续, 不需要 sidecar;
        标量字段(axes 三项): 手工编辑者在条目上放 _manual_{field}: true。
    2026-08-15 之前这里只认 sidecar, 而全仓没有任何写入方产生它 —— 人工机位一重跑
    管线就被静默冲掉, 正是"保存的视角后端重启后消失"的第二病根。
    参数:
        generated: 新生成的 manifest
        existing: 磁盘上已有的 manifest
    返回值: dict, 合并后的 manifest
    """
    for section, fields in PRESERVE_FIELDS.items():
        old_by_id = {item["id"]: item for item in existing.get(section, [])}
        for item in generated.get(section, []):
            old = old_by_id.get(item["id"])
            if not old:
                continue
            for field in fields:
                if field not in old:
                    continue
                value = old[field]
                in_band = isinstance(value, dict) and bool(value.get("manual"))
                if in_band or old.get(f"_manual_{field}"):
                    item[field] = value
                    if not in_band:
                        item[f"_manual_{field}"] = True
    return generated


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()

    parser = argparse.ArgumentParser(description="生成 device-manifest.json")
    parser.add_argument("--eit-root", default=DEFAULT_EIT_ROOT, help="上位机仓库根目录(只读)")
    parser.add_argument("--output", default=None)
    parser.add_argument("--check", action="store_true", help="只比对差异, 不写文件")
    parser.add_argument(
        "--strict-limits",
        action="store_true",
        help="控制侧 limits/示教值越出 range_mm 时以非零退出(默认仅警告)",
    )
    args = parser.parse_args()

    output = args.output or os.path.join(config["paths"]["models"], "device-manifest.json")

    if not args.eit_root or not os.path.isdir(args.eit_root):
        raise SystemExit("PTLC_CONTROL_ROOT 未设置或无效；拒绝把开发机绝对路径写入浏览器产物")

    manifest = build_manifest(config, args.eit_root)

    if os.path.isfile(output):
        with open(output, "r", encoding="utf-8") as handle:
            manifest = merge_preserving(manifest, json.load(handle))

    rigged = sum(1 for a in manifest["axes"] if a["rigged"])
    log(
        f"工位 {len(manifest['stations'])} 个 · 展缸 {len(manifest['tanks'])} 个 · "
        f"运动轴 {len(manifest['axes'])} 条(已装配 {rigged})"
    )
    signal_light = manifest.get("signalLight")
    log(f"三色塔灯: {signal_light['glbNode'] if signal_light else '未声明(rig_map.signal_light 未启用)'}")
    for station in manifest["stations"]:
        light = "有灯" if station["statusLight"] else "无灯"
        log(
            f"  {station['id']:<12} {station['label']:<10} 节点={station['nodeId'] or '-':<16} "
            f"{light} 动作={len(station['actions'])}"
        )

    # 限位一致性校验: 控制侧示教点必须落在 range_mm 内, 否则轴绑定后实机走到
    # 界外会被前端 clamp 静默冻住. --check 模式也执行, 让漂移检查同时暴露限位缺口.
    limit_check = check_axis_limits(manifest["axes"], collect_plc_points(args.eit_root))
    for line in limit_check["warnings"]:
        log(f"警告: {line}")
    for line in limit_check["notes"]:
        log(f"提示: {line}")
    if limit_check["warnings"]:
        log(
            f"限位校验: {len(limit_check['warnings'])} 条警告 —— 请在绑定该轴时把 rig_map 的 "
            "range_mm 扩到控制侧限位并集, 或与控制侧确认收紧 limits"
        )
        if args.strict_limits:
            raise SystemExit(f"--strict-limits: 限位校验未通过({len(limit_check['warnings'])} 条警告)")
    else:
        log("限位校验: 控制侧示教点全部落在 range_mm 内")

    if args.check:
        log("--check 模式: 未写入文件")
        return

    ensure_dir(output)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    log(f"已写入: {output}")

    write_report(
        os.path.join(config["paths"]["work"], "gen_twin_manifest.report.json"),
        {
            "output": output,
            "stations": len(manifest["stations"]),
            "tanks": len(manifest["tanks"]),
            "axes": len(manifest["axes"]),
            "axes_rigged": rigged,
            "limit_check": limit_check,
        },
    )


if __name__ == "__main__":
    main()
