"""仿真沙盒栈 (SimStack): 整机行为级虚拟 PLC + 真实执行链的独立副本
====================================================================
功能:
    在**任意**主模式 (sim/real) 的后端进程内, 起一套与真机执行链逐字同构、
    但与真实世界完全隔离的仿真栈:

        VmThread → ActionExecutor → PlcController → OpcUaDriver
            → 第二台 Mock OPC UA Server (127.0.0.1:48491, 253 节点同构)
            → L2 FSM (瞬移到位) + manual FSM (轴积分/气缸反馈) + 排液 FSM
        SimRobotTransport(带姿态观察者) / 独立 EventBus / RunStore(:memory:)
        / MaterialStore(:memory:) / realtime+material 反馈循环

    三维仿真页 (/3d/sim) 经 /api/sim/* 设定状态、执行动作/流程, 经
    /api/sim/ws/events 订阅沙盒事件 —— 渲染链与实时页完全同一套 (TwinFeed)。

隔离纪律 (违反即是事故, 改动本文件先过这一遍):
    * 沙盒 driver 只连 127.0.0.1:48491, 永不触真 PLC/真机器人/真相机;
    * RunStore/MaterialStore 全内存, runs.db/materials.db/experiments.db 不被打开;
    * 独立 EventBus —— 沙盒事件绝不进 /api/ws/events (主通道消费者无 origin
      过滤, 且 axis_pose/mechanism_state 按 seq 判新鲜, 混流会互顶);
    * executor 的 manual_guard=None、maintenance_gate=None —— 真实单点会话/
      PLC 下载互不拦截沙盒, 沙盒也不占真实 MaintenanceGate 租约;
    * 不装配调度器/实验库/节点遥测 —— 那些属于真实世界;
    * 标定写入类 host 方法 (feedlift_calib_record) 一律拒绝执行。

阶段现状 (仿真模块三期计划, 2026-08-10 阶段③主体落地):
    行为层在 mock/behavior/, 数据来自**编排说明书** specs/*.yaml —— 从 CODESYS
    现役工程逐字提取的 PLC 内部工序 (段号/互锁/错误码/时序常量 + POU 锚点与 ST
    哈希), 由 spec_loader 加载, 两层漂移看门狗守着 (离线 pytest + 在线
    tools/plc_spec_drift)。已复刻:
      · FeedLift 全部动作: JOG 搜索光电边沿 + 停住确认 + 前置互锁门 + 错误码
        301~308; 板堆物理模型 (触发位 = 空仓基准位 − 张数×节距) 与取放板扣减;
      · Collect/StagingA/Pump 三工位全动作 (含 A22 无瓶互锁、A23 缺瓶 201);
      · Develop 的 31/32 放板缸、26 抽吸四相 (402 硬上限)、10/20/21/22 阀位与泵段;
        50/51 排液仍走既有后台 FSM 与桥, 且已接时间倍率;
      · 传感器合成层 (behavior/sensors) 是沙盒唯一的 IX8~IX12 写者: 光电/仓底由
        板堆模型推导, 中转/瓶位由物料账本推导, 料库 12 路恒 0 (复刻真机未供电);
      · 有 flat Target 的轴按 manual_points vel_max 匀速连续运动; 虚拟泵逐真实 DT
        指令积分柱塞/阀位并广播 pump_state; 时间倍率 SimClock 全行为层生效;
      · 物料账本可从主栈整表采纳 (POST /api/sim/adopt), 沙盒有自己的
        /api/sim/materials/* 全套端点 (与真库完全隔离)。
    尚缺 (路线图): Sampling/PhotoScrape 的轴序与泵段仍走近似链 (make_station_motion
    一次推全部对, 不分动作码); PhotoScrape 的 CNC 刮取按黑盒计时未做;
    机器人仍是线性插值而非轨迹规划。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable

import yaml

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.config.loader import _parse_gcode, load_manual_points, load_plc_nodes
from eit_ptlc.config.models import AppConfig
from eit_ptlc.controller.calibration_service import CalibrationService
from eit_ptlc.controller.camera_controller import CameraController
from eit_ptlc.controller.cnc_path import CncPathController
from eit_ptlc.controller.manual_service import ManualService
from eit_ptlc.controller.pallas_vision_client import neutral_offset
from eit_ptlc.controller.plate_catalog import PlateCatalog
from eit_ptlc.controller.plc_controller import PlcController
from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.points_service import PointsService
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.controller.scrape_reconcile import ScrapeReconcileController
from eit_ptlc.controller.vision_controller import VisionService
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.driver.robot_sim import SimRobotTransport
from eit_ptlc.controller.feedlift_count import MAGAZINE_AXIS
from eit_ptlc.mock.behavior.clock import SimClock
from eit_ptlc.mock.behavior.feedlift import build_model as build_feedlift_model
from eit_ptlc.mock.behavior.develop import make_develop_dispatcher
from eit_ptlc.mock.behavior.feedlift import (
    make_feedlift_dispatcher,
    make_ledger_reflow,
    run_stack_watch_loop,
)
from eit_ptlc.mock.behavior.motion import make_rail_motion, make_station_motion
from eit_ptlc.mock.behavior.pump import create_pumps, make_pump_hook, make_pump_publisher
from eit_ptlc.mock.behavior.sensors import SensorModel, run_sensor_loop
from eit_ptlc.mock.behavior.stations import (
    make_collect_dispatcher,
    make_pump_dispatcher,
    make_staging_a_dispatcher,
)
from eit_ptlc.mock.behavior.spec_loader import load_station_spec
from eit_ptlc.mock.behavior.synthetic import SyntheticLedger
from eit_ptlc.mock.behavior.tank_liquid import (
    build_model as build_tank_liquid_model,
    run_tank_liquid_loop,
)
from eit_ptlc.mock.manual_plc import (
    _container_parent_path,
    build_manual_mock_tree,
    manual_read,
    manual_write,
    run_manual_fsm,
)
from eit_ptlc.mock.plc_server import (
    build_mock_server,
    mock_read,
    mock_write,
    run_l2_fsm,
    run_tank_drain_fsm,
)
from eit_ptlc.mock.sim_axes import (
    ACT_POS_ALIASES,
    AXIS_BY_ID,
    AXIS_LINKS,
    TELEPORT_MIRRORS,
    rail_on_done_factory,
)
from eit_ptlc.operation.resources import ResourceError, ResourceGate, load_resource_specs
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.runtime.events import EventBus, make_event_sink
from eit_ptlc.runtime.material_feedback import material_feedback_loop
from eit_ptlc.runtime.material_store import (
    AREAS,
    OP_BLOCKED,
    OP_EXHAUSTED,
    MaterialStore,
    load_bindings,
    load_topology,
)
from eit_ptlc.runtime.realtime_feedback import realtime_feedback_loop
from eit_ptlc.runtime.sim_plate_projection import project_plate_positions
from eit_ptlc.runtime.run_store import RunStore
from eit_ptlc.action.models import ActionStatus

log = logging.getLogger(__name__)

#: 沙盒 Mock OPC UA 监听地址 —— 与 sim 主栈 (48490) 并存; 测试可传参覆盖
SANDBOX_URL = "opc.tcp://127.0.0.1:48491/eit_ptlc/sandbox/"

#: 与 bootstrap._ALL_L2_STATIONS 同值 (不 import bootstrap: 避免环)
_L2_STATIONS = ("Sampling", "Collect", "Develop", "PhotoScrape", "FeedLift", "Pump", "Rail", "StagingA")


def _build_ik_solver():
    """尽力构造 CR5 逆解闭包 ((pose6, seed_deg6, tool) -> joint6 | None)。

    真源复用 three_d/pipeline/robot_kinematics (官方 xacro 链 + cr5_ptlc_v1 标定 +
    关节限位 + 失败即拒) —— 不在运行时再抄一份公式。任一环失败 (scipy/标定缺席)
    返回 None **静默降级**: 沙盒照常起, 只是无关节角的派生点段臂姿保持。
    """
    try:
        pipeline_dir = Path(__file__).resolve().parents[1] / "three_d" / "pipeline"
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))
        from robot_kinematics import load_calibration, pose_matrix, solve_ik
        calibration = load_calibration()
    except Exception as exc:                  # noqa: BLE001  (降级不阻断建栈)
        log.warning("[SimStack] IK 不可用 (%s): 无关节角的派生点段臂姿将保持", exc)
        return None

    def ik(pose6, seed_deg, tool):
        try:
            joints = solve_ik(pose_matrix(pose6), seed_deg, calibration, tool=tool)
        except Exception:
            return None
        return [float(value) for value in joints]

    return ik


class SimStack:
    """一套已启动的仿真沙盒 (见模块头)。经 build_sim_stack 构造, stop() 收口。"""

    def __init__(self, **parts) -> None:
        self.__dict__.update(parts)
        # 板位投影的版本号与内容指纹 (见 plate_positions); 沙盒重建即从 0 起
        self._plate_revision = 0
        self._plate_fingerprint = ""

    @property
    def time_scale(self) -> float:
        return self.clock.rate

    @time_scale.setter
    def time_scale(self, rate: float) -> None:
        """时间倍率: 行为层 (轴运动/泵积分/换阀/延时) 的下一次等待即生效。"""
        self.clock.rate = float(rate)

    # ------------------------------------------------------------------
    # 状态面
    # ------------------------------------------------------------------
    async def state_snapshot(self) -> dict:
        """全量状态: 轴 mm(flat 镜像)/机器人/机构(单点快照)/物料账本。"""
        axes = {}
        for link in AXIS_LINKS:
            try:
                axes[link.axis_id] = {
                    "mm": float(await mock_read(self.server, link.act_pos)),
                    "label": link.label,
                }
            except Exception:
                axes[link.axis_id] = {"mm": None, "label": link.label}
        fb = self.robot_transport.query()
        try:
            rail_homed = bool(await mock_read(self.server, "Rail_Homed"))
        except Exception:
            rail_homed = None
        manual_snap = None
        if self.manual is not None:
            try:
                manual_snap = await self.manual.realtime_snapshot()
            except Exception:
                log.debug("[SimStack] 单点快照失败", exc_info=True)
        materials = await asyncio.to_thread(self.material_store.grid)
        # 执行器统一命名空间: PLC 气缸 ∪ 机器人末端 —— 逐字镜像 realtime_feedback_loop
        # 拼 mechanism_state 事件的做法。**契约**: 这张表的键集 = PUT 能写的键集
        # (气缸走 mechanisms, 末端走 robot.effectors), 有单测钉住。
        mechanisms = dict((manual_snap or {}).get("mechanisms") or {})
        effector_ids: list = []
        try:
            mechanisms.update(self.executor.robot.mechanism_snapshot())
            # 能力面 (这把刀能点哪几个末端) 与显示面 (已被命令过的) 是两回事:
            # rob_suction 没有 CAD 基准位, 未命令过时刻意不发布显示态 —— 但它一直可写。
            # 前端据此出行, 不必复抄刀↔机构映射。
            effector_ids = list(self.executor.robot.twin_mechanism_ids())
        except Exception:
            log.debug("[SimStack] 机器人末端机构快照失败", exc_info=True)
        return {
            "time_scale": self.time_scale,
            "axes": axes,
            "robot": {"joint": list(fb.joint), "pose": list(fb.pose),
                      "tool": int(self.robot_transport.mounted_tool),
                      "effectors": effector_ids},
            "rail": {"homed": rail_homed},
            "mechanisms": mechanisms,
            "manual": manual_snap,          # 机构命令/反馈原始快照 (与实时页同形)
            "pumps": {pump_id: model.snapshot() for pump_id, model in self.pumps.items()},
            "tanks": self.tank_liquid.snapshot(),
            "materials": materials,
        }

    async def plate_positions(self) -> dict:
        """薄层板位置的只读投影 (见 runtime/sim_plate_projection).

        参数:
            无
        返回:
            Dict, L1 板位快照

        revision 只在**内容变化**时 +1: 消费者 PlateLedgerStore 对相等 revision 幂等
        丢弃 (省一次全量 diff), 每帧递增会让它每 3 秒白算一遍。变小则被判成"后端重启"
        并触发全量 resync —— 沙盒重建时 revision 从 0 起, 语义恰好正确。
        """
        grid = await asyncio.to_thread(self.material_store.grid)
        payload = project_plate_positions(
            seats=grid.get("seats") or [], magazines=grid.get("magazines") or [],
            feedlift_model=self.feedlift_model, revision=self._plate_revision)
        fingerprint = json.dumps(
            {"batches": payload["batches"], "magazines": payload["magazines"]},
            ensure_ascii=False, sort_keys=True)
        if fingerprint != self._plate_fingerprint:
            self._plate_fingerprint = fingerprint
            self._plate_revision += 1
            payload["revision"] = self._plate_revision
        return payload

    async def diagnostics(self) -> dict:
        """只读诊断: 八工位 L2 现状 + 前置门逐条真因 + 传感器位语义 + 板堆模型 + 合成值台账.

        参数:
            无
        返回:
            Dict {stations, sensors, feedlift, synthetic}

        它与 state_snapshot 刻意分家: 那边是**可设面的回读**, 这边是**只读诊断**。
        同一批事实两个出口就会漂 —— 这正是本次 P0 缺陷 (板堆模型与账本双真源) 的同类病。
        """
        from eit_ptlc.action.plc_error_hints import describe as describe_error
        from eit_ptlc.mock.behavior.diagnostics import (
            feedlift_block, sensor_block, station_rows)
        from eit_ptlc.mock.behavior.sensors import SENSOR_BYTES
        from eit_ptlc.mock.behavior.spec_loader import load_station_spec

        snapshots: dict = {}
        specs: dict = {}
        for station in _L2_STATIONS:
            try:
                snapshots[station] = await self.plc.snapshot(station)
            except Exception as exc:              # 单工位读失败不连坐
                snapshots[station] = {"error": str(exc)}
            try:
                specs[station] = load_station_spec(station)
            except Exception:
                log.debug("[SimStack] 工位 %s 无编排说明书", station, exc_info=True)

        values: dict = {}
        for name in SENSOR_BYTES:
            try:
                values[name] = int(await mock_read(self.server, name))
            except Exception:
                values[name] = None

        positions: dict = {}
        for magazine, axis in MAGAZINE_AXIS.items():
            try:
                link = AXIS_BY_ID[f"axis_{axis}z"]
                positions[magazine] = float(await mock_read(self.server, link.act_pos))
            except Exception:
                positions[magazine] = None

        return {
            "stations": station_rows(snapshots, specs,
                                     feedlift_model=self.feedlift_model,
                                     describe=describe_error, context="sim"),
            "sensors": sensor_block(values),
            "feedlift": feedlift_block(self.feedlift_model, positions),
            # 本次会话用了几处合成值 —— 没有这一块, 合成就退回成一个更隐蔽的零偏桩
            "synthetic": self.synthetic.snapshot(),
            "pumps": await asyncio.to_thread(self._pump_ledger_block),
            "tanks": self.tank_liquid.snapshot(),
        }

    def _pump_ledger_block(self) -> dict:
        """泵积分量与账本扣减量并排 (差异只呈现, 不回写).

        参数:
            无
        返回:
            Dict {aspirated_total_ml, dispensed_total_ml, ledger_drawn_ml, diverged,
                  note, items: [{id, aspirated_ml, dispensed_ml, plunger_ml, busy}]}

        **账本口径一个字不改**: 真机没有流量计, 按动作参数扣就是真机的真实盲区,
        沙盒去按泵的实际吸入量扣就成了"沙盒比真机准" —— 与 parity 纪律相反。这里
        只把两个数摆在一起。

        `diverged` 是**单向**判据: 只在"账本扣的比泵取过的还多"时为真 —— 那个方向
        无歧义地错 (扣了泵根本没取过的量)。反方向 (泵取得多) 是正常的: 清洗与润洗
        照样抽液却不记账。双向判据会天天误报, 误报的看门狗等于没有看门狗。
        """
        aspirated = sum(model.aspirated_ml for model in self.pumps.values())
        dispensed = sum(model.dispensed_ml for model in self.pumps.values())
        drawn = self.material_store.liquid_drawn_total_ml()
        return {
            "aspirated_total_ml": round(aspirated, 3),
            "dispensed_total_ml": round(dispensed, 3),
            "ledger_drawn_ml": round(drawn, 3),
            "diverged": drawn > aspirated + _PUMP_LEDGER_TOL_ML,
            "note": "账本按动作参数扣 (与真机同口径, 真机无流量计); 泵按真实 DT 指令积分。"
                    "泵吸得多是正常的 (清洗润洗不记账); 账本扣得多才是错。",
            # 逐泵一行直接取 snapshot() —— 步数换 mL 的常量只有 pump.py 那一份
            "items": [model.snapshot() for _, model in sorted(self.pumps.items())],
        }

    async def apply_state(self, patch: dict) -> dict:
        """局部写状态。返回 {applied: [...], rejected: [{path, reason}]}。

        写轴 = flat ActPos(+别名) 与 manual 伺服结构 fActPos 同写 —— 前者是
        上位机业务读的镜像, 后者是 20Hz axis_pose 的采样源; 真 PLC 里两者由
        每扫描镜像保持一致, 沙盒在写入口一次写齐。
        """
        applied: list[str] = []
        rejected: list[dict] = []
        for axis_id, value in dict(patch.get("axes") or {}).items():
            link = AXIS_BY_ID.get(str(axis_id))
            if link is None:
                rejected.append({"path": f"axes.{axis_id}", "reason": "未知轴 id"})
                continue
            try:
                mm = float(value)
                await self._write_axis_mm(link, mm)
                applied.append(f"axes.{axis_id}")
            except Exception as exc:
                rejected.append({"path": f"axes.{axis_id}", "reason": str(exc)})
        robot = dict(patch.get("robot") or {})
        # 只有本体三项 (joint/pose/tool) 才算 "robot" 被应用; 末端执行器逐个记自己的路径,
        # 否则一个只带 effectors 的 patch 会记出一条谁也没写的 applied
        if any(robot.get(key) is not None for key in ("joint", "pose", "tool")):
            try:
                joint = robot.get("joint")
                pose = robot.get("pose")
                if joint is not None or pose is not None:
                    self.robot_transport.set_state(pose=pose, joint=joint)
                if robot.get("tool") is not None:
                    from eit_ptlc.driver.robot_transport import MountedTool
                    self.robot_transport.set_mounted_tool(MountedTool(int(robot["tool"])))
                applied.append("robot")
            except Exception as exc:
                rejected.append({"path": "robot", "reason": str(exc)})
        # 末端执行器排在 robot 之后: 换刀必须先于动末端, 否则工具门控会挡下同一 patch 里
        # "先挂 1 号刀再开吸盘"这种再正常不过的写法
        for mech_id, value in dict(robot.get("effectors") or {}).items():
            path = f"robot.effectors.{mech_id}"
            try:
                await self._write_effector(str(mech_id), bool(value))
                applied.append(path)
            except LookupError as exc:
                rejected.append({"path": path, "reason": str(exc)})
            except Exception as exc:
                rejected.append({"path": path, "reason": str(exc)})
        rail = dict(patch.get("rail") or {})
        if "homed" in rail:
            try:
                await mock_write(self.server, "Rail_Homed", bool(rail["homed"]))
                applied.append("rail.homed")
            except Exception as exc:
                rejected.append({"path": "rail.homed", "reason": str(exc)})
        for magazine, entry in dict(patch.get("feedlift") or {}).items():
            entry = dict(entry or {})
            if "count" in entry:
                # 板仓张数有属主 (账本), 这里开第二条捷径就是第二个写者
                rejected.append({
                    "path": f"feedlift.{magazine}.count",
                    "reason": "板仓张数的唯一写者是账本: "
                              "POST /api/sim/materials/magazine {magazine, count}; "
                              "写完自动回灌板堆模型"})
            if "homed" not in entry:
                continue
            if magazine not in self.feedlift_model.homed:
                rejected.append({"path": f"feedlift.{magazine}.homed",
                                 "reason": f"未知板仓 {magazine!r}"})
                continue
            self.feedlift_model.homed[magazine] = bool(entry["homed"])
            applied.append(f"feedlift.{magazine}.homed")
        for index, present in dict((patch.get("site") or {}).get("feed_rack") or {}).items():
            try:
                slot = int(index)
            except (TypeError, ValueError):
                rejected.append({"path": f"site.feed_rack.{index}", "reason": "料架位号应为整数"})
                continue
            if slot not in self.sensor_model.feed_rack_present:
                rejected.append({"path": f"site.feed_rack.{slot}",
                                 "reason": "上样料架只有 1 号与 2 号两处"})
                continue
            self.sensor_model.feed_rack_present[slot] = bool(present)
            applied.append(f"site.feed_rack.{slot}")
        for mech_id, value in dict(patch.get("mechanisms") or {}).items():
            try:
                await self._write_cylinder(str(mech_id), bool(value))
                applied.append(f"mechanisms.{mech_id}")
            except KeyError:
                rejected.append({"path": f"mechanisms.{mech_id}", "reason": "未知执行器 id"})
            except Exception as exc:
                rejected.append({"path": f"mechanisms.{mech_id}", "reason": str(exc)})
        # 泵相位: "吸了一半停电重开"是真实初态, 此前 pumps 只在读面出现没有写口
        for pump_id, entry in dict(patch.get("pumps") or {}).items():
            entry = dict(entry or {})
            model = self.pumps.get(str(pump_id))
            if model is None:
                rejected.append({"path": f"pumps.{pump_id}",
                                 "reason": f"未知泵 id; 可选 {sorted(self.pumps)}"})
                continue
            try:
                model.set_state(plunger_ml=entry.get("plunger_ml"),
                                valve_port=entry.get("valve_port"))
                # 直写后补一帧 pump_state, 三维柱塞与面板回读立刻跟随 (与轴同款单向流)
                self.pump_publisher(model)()
                applied.append(f"pumps.{pump_id}")
            except Exception as exc:
                rejected.append({"path": f"pumps.{pump_id}", "reason": str(exc)})
        # 展缸液量: "板在 3 号缸泡着、液面到哪"是个真实初态, 此前后端连这个变量都没有。
        # 写面形状 {"tanks": {"3": {"volume_ml": 50}}}; 读面在 state.tanks.volumes 下,
        # 外层还挂着容量与排液时长两项元数据, 故键名刻意分开 (volumes ≠ tanks)。
        for tank, entry in dict(patch.get("tanks") or {}).items():
            if not isinstance(entry, dict) or "volume_ml" not in entry:
                continue
            try:
                self.tank_liquid.set_volume(int(tank), float(entry["volume_ml"]))
                applied.append(f"tanks.{tank}.volume_ml")
            except Exception as exc:
                rejected.append({"path": f"tanks.{tank}.volume_ml", "reason": str(exc)})
        return {"applied": applied, "rejected": rejected}

    async def reset_home(self) -> dict:
        """规范 home: 全轴 0 / 机器人回 home 点 / 气缸全断电 / Rail 已回零。"""
        for link in AXIS_LINKS:
            await self._write_axis_mm(link, 0.0)
        home_pt = self.point_registry.get(self.home_point)
        self.robot_transport.set_state(pose=home_pt.pose, joint=home_pt.joint)
        await mock_write(self.server, "Rail_Homed", True)
        if self.manual_map is not None:
            for mech_id in self.manual_map.cylinders:
                try:
                    await self._write_cylinder(str(mech_id), False)
                except Exception:
                    pass
        return {"ok": True}

    async def _write_axis_mm(self, link, mm: float) -> None:
        await mock_write(self.server, link.act_pos, mm)
        for alias in ACT_POS_ALIASES.get(link.act_pos, ()):
            await mock_write(self.server, alias, mm)
        if self._servo_root is not None:
            await manual_write(self.server, self._servo_root + (link.struct, "fActPos"), mm)

    async def _write_cylinder(self, mech_id: str, value: bool) -> None:
        cyl = self.manual_map.cylinders[mech_id]      # KeyError → 调用方转 rejected
        paths = self._manual_paths
        ref = cyl.auto_ro or cyl.manual               # 自动位优先 (manual FSM 非会话态吃自动位)
        await manual_write(self.server, paths[ref.container] + (ref.name,), value)

    async def _write_effector(self, mech_id: str, value: bool) -> None:
        """写机器人末端执行器 (吸盘/夹爪/翻转) 的目标态.

        参数:
            mech_id: 孪生机构 id; value: 目标布尔态
        返回:
            None
        Raises:
            LookupError: 当前挂刀不提供该机构 (含 id 根本不存在)

        **必须走真的 tool_action, 不许直改孪生缓存**, 三条理由:
          ① 缓存只有 tool_action 会写 (_record_twin_mechanism), 直写等于抄第二份状态机;
          ② 沙盒的板堆扣减判据 _suction_on 读的就是这份缓存 —— 走 tool_action 才能让
             "手动开吸盘 -> A12 让位 -> 上料仓 −1" 这条因果在沙盒里真实成立;
          ③ mechanism_state 的实时发布由同一缓存驱动, 于是三维与面板回读立刻跟随。
        """
        action = self.executor.robot.tool_action_for_mechanism(mech_id, value)
        if action is None:
            mounted = int(self.robot_transport.mounted_tool)
            raise LookupError(
                f"当前腕上是 {mounted or '无 (裸腕)'} 号刀, 不提供机构 {mech_id!r}; "
                f"先写 robot.tool 再写它")
        await asyncio.to_thread(self.executor.robot.tool_action, action)

    # ------------------------------------------------------------------
    # 运行面
    # ------------------------------------------------------------------
    async def run_action_with_events(self, name: str, params: dict, *,
                                     mode: str | None, label: str | None = None) -> dict:
        """单个原子动作直跑 + 合成事件包裹 (逐字段镜像主栈 app.py::_execute_with_live_events)。

        三维的泵/液面包络链 (TwinFeed._handleLiquidAction) 吃 step_start/step_done 的
        `params` —— 不发事件这条链就全瞎 (2026-08-09 用户实测: 单动作跑 flush 泵不动)。
        emit 落沙盒 bus (前端实时) + 沙盒物料账本 (单发也如实记账);
        run_store 刻意不入 —— 与主栈"手点不污染履历"同一条理由。
        """
        from eit_ptlc.action.models import ActionStatus
        emit = make_event_sink(self.bus.publish, self.material_store.on_event)
        rid = uuid.uuid4().hex[:12]
        params = dict(params or {})
        t0 = time.time()
        emit({"type": "operation_start", "operation": name, "atomic": True,
              "run_id": rid, "label": label or name, "ts": t0})
        emit({"type": "step_start", "run_id": rid, "step": "a1", "action": name,
              "params": dict(params), "index": 0, "status": "RUNNING", "ts": t0})
        result = await self.executor.execute(name, params, request_id=rid,
                                             current_mode=mode)
        t1 = time.time()
        status = result.status.value
        emit({"type": "step_done", "run_id": rid, "step": "a1", "action": name, "index": 0,
              "params": dict(params),
              "status": status, "message": result.message, "result": result.result, "ts": t1})
        done_type = ("operation_done" if result.status is ActionStatus.DONE
                     else "operation_failed")
        emit({"type": done_type, "operation": name, "run_id": rid,
              "status": status, "message": result.message, "ts": t1})
        return {
            "action": result.action, "status": status,
            "accepted": result.accepted, "message": result.message,
            "reject_code": result.reject_code.value if result.reject_code else None,
            "error_code": result.error_code, "result": result.result,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def stop(self) -> None:
        """反向收口 (对齐 create_sim_app finally 块的顺序)。幂等。

        先置停止位再**取消**任务: 行为层 (轴运动/泵积分) 可能在长 sleep 中,
        只置位等自然退出会让销毁挂到该段跑完 (倍率 1 时一段吸排就是几十秒)。
        """
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self.stop_event.set()
        # 机器人插值在执行器线程里阻塞睡, 不吃 asyncio 取消 —— 置中断位让它停在当前位
        try:
            self.robot_transport.stop()
        except Exception:
            log.debug("[SimStack] 机器人插值中断异常", exc_info=True)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await self.driver.disconnect()
        except Exception:
            log.debug("[SimStack] driver 断开异常", exc_info=True)
        self.robot_transport.close()
        try:
            await self.server.stop()
        except Exception:
            log.debug("[SimStack] mock server 关闭异常", exc_info=True)
        self.run_store.close()
        self.material_store.close()
        log.info("[SimStack] 沙盒已销毁")


async def build_sim_stack(
    config: AppConfig,
    *,
    registry: ActionRegistry,
    resolve_script: Callable[[str], dict],
    mode_provider: Callable[[], str | None],
    read_config_section: Callable[[str], dict] | None = None,
    opcua_url: str = SANDBOX_URL,
    time_scale: float = 1.0,
) -> SimStack:
    """构造并启动一套仿真沙盒。

    参数:
        config: AppConfig (只读使用: 点表/拓扑/相机等路径)
        registry: 动作目录 (与主栈共享同一份加载结果)
        resolve_script: 流程名 -> 节点树 (通常绑主栈 ScriptRepo)
        mode_provider: 当前控制模式 (与主栈共享, 动作 modes 门语义一致)
        read_config_section: (section)->dict 活配置读取 (gcode 等); None 则每次
            从 config 路径同步读 —— 与主栈 ConfigService 同源即可
        opcua_url: 沙盒 Mock 监听地址 (测试传随机端口)
        time_scale: 时间倍率 (阶段③生效, 先行透传)
    """
    cfg_dir = config.plc.nodes_file.parent
    node_map = load_plc_nodes(config.plc.nodes_file)
    server = await build_mock_server(opcua_url, node_map)
    manual_map = None
    try:
        manual_map = load_manual_points(cfg_dir / "manual_points.yaml")
        await build_manual_mock_tree(server, manual_map)
    except FileNotFoundError:
        log.warning("[SimStack] 未找到单点控制点表, 沙盒不建单点容器 (axis_pose 将缺席)")
    except Exception:
        log.error("[SimStack] 单点容器构建失败", exc_info=True)
        manual_map = None
    await server.start()

    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    clock = SimClock(rate=time_scale)
    reader = lambda name: mock_read(server, name)          # noqa: E731
    writer = lambda name, value: mock_write(server, name, value)  # noqa: E731

    # 轴速度真源: manual_points 各轴 vel_max (定位速度限幅); 点表缺席给保守 20mm/s
    speed_by_node: dict[str, float] = {}
    if manual_map is not None:
        vel_by_axis = {axis.id: float(axis.vel_max) for axis in manual_map.axes.values()}
        for link in AXIS_LINKS:
            speed_by_node[link.act_pos] = vel_by_axis.get(link.axis_id, 20.0)

    def speed_of(act_pos_node: str) -> float:
        return speed_by_node.get(act_pos_node, 20.0)

    # 虚拟泵注册表 (栈级: 柱塞/阀状态跨动作延续) + pump_state 广播器
    bus = EventBus()
    pumps = create_pumps()
    # 展缸液量: 容量与排液时长读三维 manifest (03 管线实测的溶液槽, 后端不抄第二份数字)。
    # 建得早是因为沙盒的 develop.wait_level 要拿它合成溶剂前沿。
    tank_liquid_model = build_tank_liquid_model(_load_twin_manifest(config))
    pump_publisher = make_pump_publisher(bus)

    # 物料账本先于 L2 装配建好: FeedLift 板堆模型要拿它的板仓张数做初值,
    # 传感器合成层要拿它的中转/座位占用合成 IX 位
    topology = load_topology(cfg_dir / "material_topology.yaml")
    material_store = MaterialStore(
        ":memory:", topology=topology,
        bindings=load_bindings(cfg_dir / "material_bindings.yaml", topology))

    # 单点容器路径表: 气缸类行为要用它写自动位/读到位反馈 (原在下方 servo_root 处
    # 才算, 此处提前算一份 —— 同一个纯计算, 不引入第二份真源)
    manual_paths_early = None
    if manual_map is not None:
        manual_paths_early = {k: _container_parent_path(manual_map, k) + (v,)
                              for k, v in manual_map.containers.items()}

    # 阶段③ FeedLift: 板堆物理模型 (行为任务在 robot/servo_root 就绪后再建, 见下)
    feedlift_spec = load_station_spec("FeedLift")
    feedlift_model = build_feedlift_model(
        cfg_dir, topology.magazines,
        {name: material_store.magazine_count(name) for name in ("feed", "waste")})
    # 账本 -> 板堆模型的唯一回灌口。上面那行取的只是**建栈这一刻**的初值, 而账本此刻
    # 还是空的 (:memory: 新建); adopt / 人工盘点 / 光电盘点校正三条路都在之后发生 ——
    # 没有这个观察者, 模型就永远停在 0 张, 仓底接近开关恒 FALSE, FeedLift 全部动作
    # 必然 10 秒超时报 301/302。
    material_store.set_magazine_observer(make_ledger_reflow(feedlift_model))

    #: 阶段③已按编排说明书复刻整段行为的工位 (dispatch 旁路 motion 近似链)
    #: FeedLift 的任务延后到 robot/servo_root 就绪后建 (见下方), 其余在本循环里建。
    _CHOREOGRAPHED = ("FeedLift", "Collect", "StagingA", "Pump", "Develop")
    vacuum_slots: set = set()

    def _step_writer(station: str):
        """构造某工位的段号写入器 (行为层喂上位机停滞看门狗用)."""
        async def _set_step(value) -> None:
            await mock_write(server, f"{station}_L2_Step", int(value or 0))
        return _set_step

    for prefix in _L2_STATIONS:
        if prefix in _CHOREOGRAPHED and prefix != "FeedLift":
            # 无 flat 轴的三个工位: 气缸/阀/泵段全在行为层, 此处直接建任务
            spec = load_station_spec(prefix)
            if prefix == "Collect":
                dispatch = make_collect_dispatcher(
                    server, spec, manual_map=manual_map, manual_paths=manual_paths_early,
                    clock=clock, stop_event=stop, set_step=_step_writer(prefix),
                    pump_hook=make_pump_hook(server, prefix, pumps, clock, pump_publisher))
            elif prefix == "StagingA":
                dispatch = make_staging_a_dispatcher(
                    server, spec, manual_map=manual_map, manual_paths=manual_paths_early,
                    clock=clock, stop_event=stop, set_step=_step_writer(prefix))
            elif prefix == "Develop":
                dispatch = make_develop_dispatcher(
                    server, spec, manual_map=manual_map, manual_paths=manual_paths_early,
                    clock=clock, stop_event=stop, set_step=_step_writer(prefix),
                    pump_hook=make_pump_hook(server, prefix, pumps, clock, pump_publisher))
            else:
                dispatch = make_pump_dispatcher(
                    server, spec, manual_map=manual_map,
                    manual_paths=manual_paths_early, vacuum_slots=vacuum_slots)
            # Develop 的 50/51 由行为层交回 (返回 None), 故仍要开排液语义桥
            tasks.append(asyncio.create_task(
                run_l2_fsm(server, prefix, stop, dispatch=dispatch,
                           develop_tank_semantics=(prefix == "Develop")),
                name=f"sim-l2-{prefix}"))
            continue
        if prefix == "FeedLift":
            # 它要用机器人吸盘态与 servo 结构路径 —— 两者都在下面才构造, 故延后建
            continue
        kwargs: dict = {
            "slow_ticks": 5,                               # 有进度的短动作 (非瞬时 DONE)
            # 瞬移镜像保留作运动收尾的兜底 (motion 完成后 ActPos 已在位, 镜像是幂等写)
            "mirror_on_done": TELEPORT_MIRRORS.get(prefix, ()),
        }
        # 阶段③行为链: 先轴运动(真实 vel_max 匀速)后泵消费(按动作码), 全部在 RUNNING
        # 态内完成才写 DONE —— 与真 PLC "运动结束/泵空闲才报完成" 同序。
        hooks: list = []
        if prefix == "Rail":
            hooks.append(make_rail_motion(server, speed_of, clock, stop))
            kwargs["on_done"] = rail_on_done_factory(reader, writer)
        elif prefix in TELEPORT_MIRRORS:
            hooks.append(make_station_motion(
                server, prefix, TELEPORT_MIRRORS[prefix], speed_of, clock, stop))
        hooks.append(make_pump_hook(server, prefix, pumps, clock, pump_publisher))
        if hooks:
            async def _motion(code: int, _hooks=tuple(hooks)) -> None:
                for hook in _hooks:
                    await hook(code)
            kwargs["motion"] = _motion
        if prefix == "Develop":
            kwargs["develop_tank_semantics"] = True
        tasks.append(asyncio.create_task(
            run_l2_fsm(server, prefix, stop, **kwargs), name=f"sim-l2-{prefix}"))
    # 排液 FSM 接时间倍率: 此前它是全沙盒唯一不吃倍率的环节 (默认 35 秒比真机还慢)
    tasks.append(asyncio.create_task(run_tank_drain_fsm(server, stop, clock=clock),
                                     name="sim-tank-drain"))
    if manual_map is not None:
        tasks.append(asyncio.create_task(
            run_manual_fsm(server, stop, manual_map, reader, writer), name="sim-manual-fsm"))

    # flat → struct 同步: 真 PLC 是 struct→flat 每扫描镜像; 沙盒阶段②的行为源
    # (瞬移/状态写) 落在 flat, 反向抄进 struct 供 20Hz axis_pose 采样。
    servo_root = None
    manual_paths = manual_paths_early          # 同一份路径表 (上方已算)
    if manual_paths is not None:
        servo_root = manual_paths.get("servo")

        async def _axis_link_loop() -> None:
            while not stop.is_set():
                for link in AXIS_LINKS:
                    try:
                        value = float(await mock_read(server, link.act_pos))
                        await manual_write(server, servo_root + (link.struct, "fActPos"), value)
                    except Exception:
                        pass
                await asyncio.sleep(0.05)

        tasks.append(asyncio.create_task(_axis_link_loop(), name="sim-axis-link"))

    # 就绪初态: 未回零时 auto_rail 路径直接拒绝, 沙盒默认是"一台已回零的机器"
    await mock_write(server, "Rail_Homed", True)

    driver = OpcUaDriver(opcua_url, node_map, reconnect_wait_timeout=10.0,
                         subscription_queue_size=config.plc.subscription_queue_size,
                         subscription_sampling_ms=config.plc.subscription_sampling_ms,
                         request_timeout=config.plc.request_timeout,
                         watchdog_interval=config.plc.watchdog_interval,
                         max_inflight_requests=config.plc.max_inflight_requests)
    await driver.connect()
    plc = PlcController(driver, poll_interval=0.05, action_timeout=config.plc.action_timeout,
                        stall_timeout=config.plc.action_stall_timeout,
                        soft_recheck=config.plc.action_soft_recheck)
    point_registry = PointRegistry.load(config.robot.points_file,
                                        source_version=config.robot.point_source_version,
                                        meta_path=config.robot.points_meta_file)
    home_pt = point_registry.get(config.robot.home_point)
    # 插值模式 (仅沙盒; 主 sim 栈仍即时完成): 20Hz 播帧喂前端 RobotPoseBuffer,
    # 无关节角的派生点经 IK 现解 —— 机械臂在 /3d/sim 里才有连续可见的运动。
    robot_transport = SimRobotTransport(pose=home_pt.pose, joint=home_pt.joint,
                                        interpolate=True, clock=clock,
                                        ik_solver=_build_ik_solver())
    robot_transport.connect()
    robot = RobotController(robot_transport, point_registry, home_point=config.robot.home_point,
                            jog_speed_percent=config.robot.jog_speed_percent,
                            step_distance_mm=config.robot.step_distance_mm,
                            step_angle_deg=config.robot.step_angle_deg,
                            maintenance_gate=None)

    # robot_pose 事件: 沙盒 transport 开插值模式 (上方构造), 运动期 20Hz 逐帧经
    # 观察者流出; 状态直写 (set_state) 也播一帧。线程编排对齐 bootstrap
    # (观察者在执行器线程回调, call_soon_threadsafe 递回事件循环)。
    loop = asyncio.get_running_loop()
    pose_state = {"seq": 0}

    def _observe_robot_pose(frame) -> None:
        import time as _time
        captured_at = _time.time()

        def _publish() -> None:
            pose_state["seq"] += 1
            bus.publish({"type": "robot_pose", "joint": list(frame.joint),
                         "pose": list(frame.pose), "tool": int(robot.mounted_tool),
                         "mode": int(frame.robot_mode), "ts": captured_at,
                         "seq": pose_state["seq"]})
        loop.call_soon_threadsafe(_publish)

    robot_transport.set_feedback_observer(_observe_robot_pose)

    # ── 阶段③ FeedLift 行为 + 传感器合成 (至此 robot/servo_root 均已就绪) ──────
    async def _write_feedlift_axis(axis_number: int, mm: float) -> None:
        """按轴号写升降轴位置 (flat + 别名 + struct 三写, 与 _write_axis_mm 同口径)."""
        link = AXIS_BY_ID[f"axis_{axis_number}z"]
        await mock_write(server, link.act_pos, mm)
        for alias in ACT_POS_ALIASES.get(link.act_pos, ()):
            await mock_write(server, alias, mm)
        if servo_root is not None:
            await manual_write(server, servo_root + (link.struct, "fActPos"), mm)

    def _suction_on() -> bool:
        """吸盘此刻是否吸住 (板离堆的物理判据).

        取机器人孪生缓存的 rob_suction: confirmed(到位反馈)优先, 缺则 commanded ——
        与 adopt 采纳机构态同一准则。裸腕/未挂 1 号刀时该机构不发布 -> False。
        """
        try:
            snapshot = robot.mechanism_snapshot()
        except Exception:
            return False
        entry = snapshot.get("rob_suction") or {}
        state = entry.get("confirmed")
        if state is None:
            state = entry.get("commanded")
        return bool(state)

    tasks.append(asyncio.create_task(run_l2_fsm(
        server, "FeedLift", stop,
        dispatch=make_feedlift_dispatcher(
            server, feedlift_spec, feedlift_model, clock=clock, stop_event=stop,
            write_axis=_write_feedlift_axis, suction_on=_suction_on),
    ), name="sim-l2-FeedLift"))

    # 板堆的机器人侧增量: A21 置 armed 后, 吸盘松开那一刻下料仓 +1 (判据见 spec A21 notes)
    tasks.append(asyncio.create_task(
        run_stack_watch_loop(feedlift_model, _suction_on, clock=clock, stop_event=stop),
        name="sim-feedlift-stack"))

    async def _read_feedlift_axis(magazine: str) -> float:
        link = AXIS_BY_ID[f"axis_{MAGAZINE_AXIS[magazine]}z"]
        return float(await mock_read(server, link.act_pos))

    async def _read_cylinder_fb(mech_id: str, which: str):
        """读某气缸的到位反馈位 (缺该口回 None; manual FSM 未装配时同)."""
        if manual_map is None or manual_paths is None:
            return None
        cyl = manual_map.cylinders.get(mech_id)
        ref = getattr(cyl, which, None) if cyl is not None else None
        if ref is None:
            return None
        try:
            return bool(await manual_read(server, manual_paths[ref.container] + (ref.name,)))
        except Exception:
            return None

    sensor_model = SensorModel(material_store, feedlift_model,
                               _read_feedlift_axis, _read_cylinder_fb,
                               mounted_tool=lambda: int(robot.mounted_tool))
    tasks.append(asyncio.create_task(
        run_sensor_loop(server, sensor_model, stop, clock=clock), name="sim-sensors"))

    tasks.append(asyncio.create_task(
        run_tank_liquid_loop(server, tank_liquid_model, pumps,
                             manual_map=manual_map, manual_paths=manual_paths,
                             clock=clock, stop_event=stop, publish=bus.publish),
        name="sim-tank-liquid"))

    run_store = RunStore(":memory:")
    points = PointsService(cfg_dir / "points", robot.registry,
                           driver=driver, robot=robot,
                           robot_points_file=config.robot.points_file,
                           robot_meta_file=config.robot.points_meta_file,
                           point_source_version=config.robot.point_source_version)
    camera = CameraController.from_config(replace(config.camera, mock=True))

    def _read_section(section: str) -> dict:
        if read_config_section is not None:
            try:
                return read_config_section(section) or {}
            except Exception:
                return {}
        try:
            raw = yaml.safe_load(Path(config.plc.nodes_file.parent / "app.yaml").read_text(
                encoding="utf-8")) or {}
            return raw.get(section) or {}
        except Exception:
            return {}

    # 合成值登记簿: 沙盒里给不出真值的 host 方法在这里盖章留痕 (见 behavior/synthetic)
    synthetic = SyntheticLedger(bus.publish)
    vision_methods = _build_sandbox_vision_methods(
        config=config, plc=plc, material_store=material_store, topology=topology,
        bus=bus, read_section=_read_section, server=server, synthetic=synthetic,
        clock=clock, tank_liquid_model=tank_liquid_model,
        feedlift_model=feedlift_model)

    def _axis_limits(key: str):
        t = points.target_entry(key)
        return None if t is None else (t.min_limit, t.max_limit)

    calibration = CalibrationService(
        PlateCatalog.load(cfg_dir / "plates.yaml", cfg_dir / "calibration.yaml"),
        driver, cfg_dir / "calibration.yaml",
        x_limits=_axis_limits("sampling_4x"), y_limits=_axis_limits("sampling_3y"))

    manual = None
    if manual_map is not None:
        manual = ManualService(driver=driver, plc=plc, manual_map=manual_map,
                               bus=bus, maintenance_gate=None,
                               vm_provider=lambda: None, stations=_L2_STATIONS)

    executor = ActionExecutor(registry, robot=robot, plc=plc, points=points,
                              driver=driver, calibration=calibration, camera=camera,
                              vision_methods=vision_methods,
                              auto_rail=config.plc.auto_rail,
                              maintenance_gate=None, manual_guard=None,
                              error_hint_context="sim")

    async def _resource_hook(action: str) -> None:
        result = await executor.execute(action, {}, current_mode=mode_provider())
        if result.status is not ActionStatus.DONE:
            raise ResourceError(f"资源钩子动作 {action} 未成功: {result.status.value} {result.message}")

    res_gate = ResourceGate(load_resource_specs(cfg_dir / "resources.yaml"),
                            activator=_resource_hook)
    vm = VmController(executor=executor, res_gate=res_gate,
                      resolve_script=resolve_script,
                      event_sink=make_event_sink(bus.publish, run_store.on_event,
                                                 material_store.on_event),
                      mode_provider=mode_provider, maintenance_gate=None)

    if manual is not None:
        tasks.append(asyncio.create_task(
            realtime_feedback_loop(manual, bus, stop,
                                   robot_states=robot.mechanism_snapshot),
            name="sim-realtime-feedback"))
    tasks.append(asyncio.create_task(
        material_feedback_loop(material_store, bus, stop), name="sim-material-feedback"))

    stack = SimStack(
        server=server, driver=driver, plc=plc, robot=robot,
        robot_transport=robot_transport, point_registry=point_registry,
        home_point=config.robot.home_point,
        points=points, calibration=calibration, manual=manual, manual_map=manual_map,
        executor=executor, res_gate=res_gate, vm=vm, bus=bus, clock=clock,
        pumps=pumps, pump_publisher=pump_publisher,
        tank_liquid=tank_liquid_model,
        run_store=run_store, material_store=material_store,
        stop_event=stop, tasks=tasks,
        opcua_url=opcua_url,
        feedlift_model=feedlift_model, sensor_model=sensor_model,
        synthetic=synthetic,
        _servo_root=servo_root, _manual_paths=manual_paths,
    )
    log.info("[SimStack] 沙盒就绪: Mock PLC %s, L2 %s (FeedLift 走编排说明书)",
             opcua_url, _L2_STATIONS)
    return stack


def _load_twin_manifest(config: AppConfig) -> dict:
    """读三维 device-manifest (沙盒页用的那一份 official-cr5).

    参数:
        config: 应用配置 (取 three_d.workspace_root)
    返回:
        Dict; 读不到则空 dict (展缸容量随之为 0, 液量恒 0 并在模型里留 warning)

    为什么要读它: 展缸溶液槽尺寸是 03 管线**实测**产出的 (210×40×25mm 满 102.48mL),
    在后端抄一份数字就会与三维分叉。同理排液时长也取那边的 rampS。
    """
    path = (Path(config.three_d.workspace_root) / "models"
            / "device-manifest.official-cr5.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("[SimStack] 读不到三维 manifest %s, 展缸液量将恒为 0", path)
        return {}


#: 溶剂前沿爬满整块板的名义时长 (秒)。**沙盒名义值** —— 真机没有任何通道声明它
#: (液位相机报的是实时百分比, 不是预期时长), 故这是 wait_level 合成链上唯一编出来的
#: 数; 它经 clock 缩放, time_scale=20 下十几秒就跑完。合成结果自报 synthetic, 见
#: mock/behavior/synthetic 的头注。
_SIM_FRONT_CLIMB_S = 300.0

#: 泵吸入量与账本扣减量的比较容差 (mL)。取 0.5 是因为两者的最小分辨力不同 ——
#: 泵是逐 0.05s 积分的连续量, 账本是逐条动作的离散量, 一条动作在途时天然差一段。
_PUMP_LEDGER_TOL_ML = 0.5


def _level_params(config: AppConfig, tank: int) -> dict:
    """取某缸的液位通道参数 (阈值真源: config/water_level_calib.json 的 params).

    参数:
        config: 应用配置; tank: 缸号 1..8 (与液位通道号同号)
    返回:
        Dict, 该通道的 params; 读不到则空 dict (阈值解析随后会如实报错)
    """
    path = config.plc.nodes_file.parent / "water_level_calib.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("[SimStack] 读不到液位标定 %s", path)
        return {}
    return dict((raw.get(str(int(tank))) or {}).get("params") or {})


def _build_sandbox_vision_methods(*, config: AppConfig, plc, material_store, topology,
                                  bus, read_section, server, synthetic,
                                  clock, tank_liquid_model, feedlift_model) -> dict:
    """沙盒版 host/vision 方法表。

    与 bootstrap._build_shared_state 的闭包组同名同签名, 差异逐条声明:
      * analyze 强制 mock; capture_plate_offset **自述合成**零偏 (见该闭包注释);
      * wait_level **自述合成**溶剂前沿 (由展缸液量模型推, 见该闭包注释);
      * capture_reference 走"服务未启用"降级语义;
      * feedlift_calib_record 拒绝 (会写真实标定文件);
      * material_plan_staging **不做**中转在位传感器核对 (沙盒无物理世界,
        决策纯按沙盒账本) —— 这是与真实链唯一的语义差, 写在这里不藏在行为里。
    """
    vision_svc = VisionService(output_dir=config.vision.output_dir, mock_mode=True,
                               image_plate_orientation=config.vision.image_plate_orientation,
                               auto_rectify_tilt=config.vision.auto_rectify_tilt,
                               rectify_min_angle_deg=config.vision.rectify_min_angle_deg,
                               min_row_score=config.vision.min_row_score,
                               image_plate_rotation_deg=config.vision.image_plate_rotation_deg)
    cnc_ctrl = CncPathController(lambda: _parse_gcode(read_section("gcode")),
                                 image_root_provider=lambda: Path(config.vision.output_dir),
                                 event_sink=bus.publish)
    scrape_reconcile = ScrapeReconcileController(
        image_root_provider=lambda: Path(config.vision.output_dir))

    async def _analyze(sample_id, before_path, after_path, **overrides):
        merged = {k: v for k, v in overrides.items() if v is not None}
        return await vision_svc.analyze_action(sample_id, before_path, after_path, **merged)

    async def _refuse(reason: str):
        raise ValueError(reason)

    _VISION_HOST = "vision.capture_plate_offset"
    _VISION_REASON = ("仿真沙盒无对位相机; 板的位姿由沙盒自己写, 板就在名义位, "
                      "故按零偏合成 —— 这是沙盒世界的真值, 不是对真机的结论")

    async def _capture_plate_offset(apply_rz: bool = False, **kwargs):
        """合成纠偏结果 (零偏), 并**自报是合成的**.

        参数:
            apply_rz: 是否叠加 Δθ; 沙盒零偏下取值不影响结果, 保留形参以对齐真机签名
        返回:
            Dict, 与真机同键 (dx_mm/dy_mm/drz_deg/err/valid/source) + synthetic 自述字段

        此前这里直接抛异常拒绝, 理由写的是"零偏桩会骗人"。顾虑对了一半, 但代价没被
        算进去: `robot_suction_put` 无条件调本方法四次, 而它被 7 条操作引用 ⇒ 沙盒里
        **任何放板都必定中途硬失败**, 一条完整流程都跑不完。

        正面回答那半个顾虑: **骗人的不是零偏本身** —— 沙盒里板的位姿是沙盒自己写的,
        板就在名义位, 零偏就是这个世界里的真值; 骗人的是把它当成对真机的结论。所以
        改成"允许编但必须自报": 结果体带 synthetic 标记, 每次调用登记进 SyntheticLedger,
        经 sim_synthetic 事件与诊断面板留痕。

        主体走真机侧同一个 neutral_offset(), 不在这里另写一份键集 —— 两份形状各自
        演化才是真会骗人的那种。
        """
        if _VISION_HOST in getattr(server, "_eit_vision_reject", ()):
            # 故障注入: 合成零偏抹掉了真机的识别失败分支 (robot_suction_put 里那两段
            # "确认=重拍一次"的人工处置), 用它把那条路演练回来。失败码取配置真源。
            fail_code = int(config.pallas_vision.err_fail_code)
            log.info("[沙盒·视觉] 注入识别失败 err=%d", fail_code)
            result = neutral_offset("sim_synthetic")
            result.update({"err": fail_code, "valid": False})
            result.update(synthetic.record(
                _VISION_HOST, f"故障注入: 识别失败 err={fail_code}"))
            return result
        result = neutral_offset("sim_synthetic")
        result.update(synthetic.record(_VISION_HOST, _VISION_REASON))
        return result

    _LEVEL_HOST = "develop.wait_level"
    _LEVEL_REASON = ("仿真沙盒没有液位相机; 溶剂前沿按缸内液量与浸泡时长合成 "
                     f"(爬满整块板名义 {_SIM_FRONT_CLIMB_S:.0f}s, 经 time_scale 缩放)")

    async def _wait_level(target_tank: int, stage: str = "t1",
                          hard_cap_s: float = 3600.0, confirm_n: int = 2,
                          staleness_s: float = 30.0, **kwargs):
        """合成液位等待: 前沿由展缸液量模型推出, 并**自报是合成的**.

        参数:
            target_tank: 目标缸 1..8; stage: 阈值档 t1/t2
            hard_cap_s: 展开时长硬上限, 到点返回 hard_cap (与真机同语义)
            confirm_n / staleness_s: 真机的去抖与陈旧判据; 沙盒无采样流, 只回显
        返回:
            Dict, 与真机 wait_level 同键 (status/front_percent/threshold/stage/
            elapsed_s/reason) + synthetic 自述字段

        阈值走真机侧同一个 resolve_threshold (通道 params 的 trigger_percent_t2 与
        t1_offset), 不在沙盒另定一套档位。

        **空缸永远等不到**: front_percent 恒 0 直到 hard_cap —— 与真机一致, 也是
        "先设液量再跑展开"这条因果在沙盒里成立的证据。
        """
        from eit_ptlc.controller.waterlevel_trigger import resolve_threshold
        tank = int(target_tank)
        params = _level_params(config, tank)
        try:
            threshold = resolve_threshold(params, str(stage))
        except Exception as exc:
            raise ValueError(f"[沙盒] 液位阈值未配置: {exc}") from exc

        # 名义耗时按 clock.elapsed 量, **不许**累加请求的 sleep 时长 (见该方法注释:
        # 累加法在 rate=16 下把 600 名义秒记成实际的 242 秒, 硬上限提前 2.5 倍触发)
        started = clock.mark()
        elapsed = 0.0
        front = 0.0
        status = "hard_cap"
        while elapsed < float(hard_cap_s):
            front = tank_liquid_model.front_percent(tank, climb_s=_SIM_FRONT_CLIMB_S)
            if front >= threshold:
                status = "reached"
                break
            await clock.sleep(0.2)
            elapsed = clock.elapsed(started)
        result = {"status": status, "front_percent": round(front, 2),
                  "threshold": threshold, "stage": str(stage),
                  "elapsed_s": round(elapsed, 3), "reason": ""}
        if _LEVEL_HOST in getattr(server, "_eit_level_degraded", ()):
            # 故障注入: 合成前沿抹掉了真机的检测降级分支 (流程据此走"退化人工门")
            result.update({"status": "degraded", "reason": "注入: 液位检测降级"})
        result.update(synthetic.record(_LEVEL_HOST, _LEVEL_REASON))
        return result

    async def _capture_reference(**kwargs):
        return {"ok": False, "has_ref": False, "elapsed_s": 0.0}

    async def _align_readout(**kwargs):
        from eit_ptlc.controller.align_check import build_align_readout
        g = _parse_gcode(read_section("gcode"))
        axes = await plc.read_scrape_axes()
        return build_align_readout(axes, g)

    async def _photoscrape_wait_rot(target: str = "extend", timeout_s: float = 6.0) -> dict:
        from eit_ptlc.controller.photoscrape_rot import wait_rot

        async def _read_ix9():
            try:
                return await plc.read_host_var("IX9")
            except Exception:
                return None
        return await wait_rot(_read_ix9, target=str(target), timeout_s=float(timeout_s))

    async def _feedlift_read_pos(magazine: str) -> dict:
        from eit_ptlc.controller.feedlift_count import MAGAZINE_AXIS
        if magazine not in MAGAZINE_AXIS:
            raise ValueError(f"板仓应为 {tuple(MAGAZINE_AXIS)} 之一, 收到 {magazine!r}")
        axis = MAGAZINE_AXIS[magazine]
        return {"magazine": magazine, "axis": axis,
                "z_mm": round(await plc.read_feedlift_pos(axis), 3)}

    async def _feedlift_probe(magazine: str, z_prev=None, expect_taken=None,
                              reconcile: bool = False, z_clear=None) -> dict:
        """沙盒版光电盘点; 判据与真机链 (bootstrap._feedlift_probe) 逐条对齐.

        parity 是本闭包存在的全部意义: 真机能拦住的缺陷, 沙盒必须也拦得住,
        否则"在沙盒里演练过"就成了假保证。
        """
        from eit_ptlc.controller.feedlift_count import (
            MAGAZINE_AXIS, MIN_APPROACH_MM, evaluate)
        axis = MAGAZINE_AXIS[magazine]
        # The real runtime reads the deployment's field calibration.  The
        # sandbox owns an isolated FeedLiftModel which may explicitly fall
        # back to its deterministic simulation fixture when the checked-in
        # field file is intentionally uncalibrated; probing must use that same
        # model calibration or motion and measurement disagree.
        calib = feedlift_model.calib[magazine]
        z_mm = await plc.read_feedlift_pos(axis)
        if z_clear is not None:
            # 陈旧读数守卫: 清零位与触发位几乎相同 = 逼近动作根本没走, 读到的是上次停轴位
            approach = round(z_mm - float(z_clear), 3)
            if approach <= MIN_APPROACH_MM:
                raise ValueError(
                    f"[沙盒] 逼近动作返回 DONE 但轴几乎没动 (清零位 {float(z_clear):.3f}mm → "
                    f"触发位 {z_mm:.3f}mm, 逼近仅 {approach:.3f}mm): 读数是陈旧值, 已拒绝采用")
        result = evaluate(z_mm, calib, z_prev=z_prev, expect_taken=expect_taken)
        if not result["ok"]:
            raise ValueError("[沙盒] " + result["text"])
        if result["warn"] or result["pitch_drift"]:
            log.warning("[沙盒·升降板仓] %s", result["text"])
        if reconcile and result.get("count") is not None:
            ledger = material_store.magazine_count(magazine)
            if ledger != result["count"]:
                # 与真机同口径: 实测是真值, 差得多提到 warning 让漏账可见
                level = log.warning if abs(ledger - result["count"]) > 1 else log.info
                level("[沙盒·升降板仓] %s 账面 %d 张, 光电行程实测 %d 张, 按实测校正",
                      topology.magazines[magazine][0], ledger, result["count"])
            material_store.set_magazine(magazine, result["count"], detail="沙盒光电盘点")
        return result

    async def _feedlift_preflight(magazine: str) -> dict:
        from eit_ptlc.controller.feedlift_count import preflight_gate
        ix8 = await plc.read_host_var("IX8")
        result = preflight_gate(magazine, int(ix8 or 0), True)
        if not result["ok"]:
            raise ValueError("[沙盒] " + result["text"])
        return result

    _kind_to_area = {kind: area for area, kind in AREAS.items()}

    async def _material_check_availability(need_collector: bool = False,
                                           need_bottle: bool = False,
                                           exclude_sample: str = "") -> dict:
        plans: dict = {}
        short: list = []
        blocked: list = []
        for kind, needed in (("collector", bool(need_collector)), ("bottle", bool(need_bottle))):
            if needed is False:
                continue
            plan = material_store.plan_staging(kind) if not exclude_sample else \
                material_store.plan_staging(kind, reserve_for=str(exclude_sample))
            plans[kind] = plan
            if plan["op"] == OP_EXHAUSTED:
                short.append(kind)
            elif plan["op"] == OP_BLOCKED:
                blocked.append(kind)
        if short:
            raise ValueError(f"[沙盒账本] 耗材余量不足: {', '.join(short)}")
        if blocked:
            raise ValueError(f"[沙盒账本] 耗材被占用: {', '.join(blocked)}")
        return {"ok": True, "plans": plans}

    async def _material_plan_staging(kind: str, reserve_for: str = "") -> dict:
        plan = material_store.plan_staging(kind, reserve_for=str(reserve_for or ""))
        if plan["op"] == OP_EXHAUSTED:
            raise ValueError(f"[沙盒账本] {kind} 已无未用孔")
        if plan["op"] == OP_BLOCKED:
            raise ValueError(f"[沙盒账本] {kind} 可用孔已被预留")
        return plan

    return {
        "generate_cnc_path": cnc_ctrl.generate_cnc_path,
        "scraped_overlay": scrape_reconcile.scraped_overlay,
        "analyze": _analyze,
        "capture_plate_offset": _capture_plate_offset,
        "wait_level": _wait_level,
        "capture_reference": _capture_reference,
        "align_readout": _align_readout,
        "photoscrape_wait_rot": _photoscrape_wait_rot,
        "feedlift_probe": _feedlift_probe,
        "feedlift_preflight": _feedlift_preflight,
        "feedlift_read_pos": _feedlift_read_pos,
        "feedlift_calib_record": lambda **kw: _refuse(
            "仿真沙盒禁用 feedlift.calib_record: 它会覆盖真实标定文件"),
        "material_check_availability": _material_check_availability,
        "material_plan_staging": _material_plan_staging,
    }
