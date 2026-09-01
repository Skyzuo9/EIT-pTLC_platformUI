"""物料一键审查路由
==================
功能:
    注册"一键审查"端点: 把账 (materials.db) 与实 (PLC 传感器 / 机器人工具态 /
    调度器) 的全部核对跑一遍, 分四组返回统一行结构。核对逻辑全在
    runtime/material_audit.py 的纯函数里, 本模块只做取数与组装。

    跨 material_store + plc + scheduler + executor.robot 四个 app.state 依赖,
    故独立成文件 (material_routes.py 的模块契约是"全部从 material_store 读写",
    不该被打破)。

    失败语义 = **分组降级, 整体 200**: 审查的产品是跨域体检合集, PLC 断链恰是最需要
    看软件双账与人工清单的时刻。但纪律不变 —— 任一输入字节读失败/读到 None,
    依赖字节的行整组置 error 或逐行 skip 并写明原因, **绝不当 0 用** (那会拼出一张
    骗人的全空快照); robot/scheduler 各自失败只 skip 各自的行。
    material_store 未就绪仍整体 503 (没有账, 审查无从谈起)。

    **只报不改**: 审查不写任何账 (reconcile_presence 落的在位快照是它自己的产品);
    行内 fix 只是给前端渲染"以实为准"按钮的建议, 动作名是闭集, 执行永远走既有
    写端点且由人显式确认。会动轴的板仓实测绝不在此触发, 只给跳转。

端点 (前缀 /api):
    POST /materials/audit    一键审查: {checked_at, counts, groups, raw, grid}
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.runtime import material_audit

log = logging.getLogger(__name__)


def register_material_audit_routes(app: FastAPI) -> None:
    """把一键审查端点注册到应用。"""

    def _store(request: Request):
        store = getattr(request.app.state, "material_store", None)
        if store is None:
            raise HTTPException(503, "物料账本未就绪")
        return store

    @app.post("/api/materials/audit")
    async def post_materials_audit(request: Request):
        """一键审查: 传感器在位 / 派生核对 / 软件双账 / 人工核对项 四组."""
        store = _store(request)
        state = request.app.state
        plc = getattr(state, "plc", None)

        # -- 读 PLC 输入字节 (纪律: 失败/None 绝不当 0 用) --------------------
        byte_values: dict[str, int] = {}
        byte_error = ""
        if plc is None:
            byte_error = "PLC 控制器未就绪, 无法读取在位传感器"
        else:
            for name in store.topology.byte_names():
                try:
                    value = await plc.read_host_var(name)
                except Exception as exc:
                    byte_error = f"读取输入字节 {name} 失败 (未发布或 PLC 断链): {exc}"
                    break
                if value is None:
                    byte_error = (f"输入字节 {name} 读回空值; 节点存在但无值, "
                                  f"通常是 PLC 未运行或输入映像未刷新")
                    break
                byte_values[name] = int(value)

        # -- 传感器在位组 (整组全有或全无) -----------------------------------
        checked_at = time.time()
        recon_rows: list[dict] = []
        if byte_error:
            presence_group = {"key": "presence", "label": "传感器在位核对",
                              "error": byte_error, "rows": []}
        else:
            recon = store.reconcile_presence(byte_values)
            checked_at = recon["checked_at"]
            recon_rows = recon["rows"]
            presence_group = {"key": "presence", "label": "传感器在位核对",
                              "error": None,
                              "rows": material_audit.presence_rows(recon_rows)}

        # 账本快照在 reconcile 之后取 (在位快照是 grid 的一部分, 先写后读)
        grid = store.grid()

        # -- 派生核对组 (字节相关行在字节失败时逐行 skip, 缸态独立取数) -------
        derived_rows: list[dict] = []
        if byte_error:
            derived_rows.append(material_audit.skip_row(
                "derived.magazine", "板仓 vs 仓底接近开关", byte_error))
            derived_rows.append(material_audit.skip_row(
                "derived.collect_bottle", "收集工位瓶位", byte_error))
        else:
            derived_rows.extend(material_audit.magazine_bottom_rows(
                byte_values.get("IX8", 0), grid.get("magazines", [])))
            bottle_presence = next(
                (row for row in recon_rows if row.get("location_id") == "collect-bottle"),
                None)
            bottle_row = material_audit.collect_bottle_row(
                bottle_presence, grid.get("payload_seats", []))
            if bottle_row is not None:
                derived_rows.append(bottle_row)

        # 机器人工具态: 忙时/不可达时 skip, 不等待 (照 sim adopt 的先例)
        robot_skip = ""
        mounted_tool = None
        executor = getattr(state, "executor", None)
        robot = getattr(executor, "robot", None) if executor is not None else None
        if robot is None:
            robot_skip = "主栈机器人不可达"
        else:
            try:
                if robot.is_busy():
                    robot_skip = "机器人运动中, 本次未核对工具态"
                else:
                    # mounted_tool 是内存持久态, 读它不打 TCP 不碰动作锁
                    mounted_tool = int(robot.mounted_tool)
            except Exception as exc:
                robot_skip = f"工具态读取失败: {exc}"
        derived_rows.append(material_audit.tool_state_row(
            byte_values.get("IX12") if not byte_error else None, mounted_tool,
            skip_reason=robot_skip if (robot_skip or byte_error) else ""))

        # 调度器快照 (座位双账 / 孤儿预留 / 缸占用共用)
        samples = None
        owners: dict = {}
        sched_error = ""
        scheduler = getattr(state, "scheduler", None)
        if scheduler is None:
            sched_error = "调度器未装配"
        else:
            try:
                snapshot = scheduler.snapshot()
                owners = dict(snapshot.get("tanks") or {})
                samples = [dict(sample)
                           for batch in snapshot.get("batches", [])
                           for sample in batch.get("samples", [])]
            except Exception as exc:
                sched_error = f"调度器快照失败: {exc}"

        # 缸态: 与输入字节独立取数, 失败只 skip 本行
        if plc is None:
            derived_rows.append(material_audit.skip_row(
                "derived.tank", "展缸状态", "PLC 控制器未就绪"))
        else:
            try:
                tank_states = await plc.read_all_tank_states()
            except Exception as exc:
                derived_rows.append(material_audit.skip_row(
                    "derived.tank", "展缸状态", f"Tank_State 读取失败: {exc}"))
            else:
                if samples is None:
                    derived_rows.append(material_audit.skip_row(
                        "derived.tank", "展缸状态",
                        f"{sched_error}, 无法判定缸占用归属"))
                else:
                    derived_rows.extend(
                        material_audit.tank_rows(tank_states, owners))
        derived_group = {"key": "derived", "label": "派生核对", "error": None,
                         "rows": derived_rows}

        # -- 软件双账组 (不依赖 PLC) ----------------------------------------
        try:
            reserved = store.reserved_summary()
        except Exception as exc:
            # 预留表读失败不连坐其余双账行 (照调度器 _reservations_safe 的兜底口径)
            log.warning("[审查] 预留账读取失败: %s", exc)
            reserved = {}
        ledger_group = {"key": "ledger", "label": "软件双账", "error": None,
                        "rows": (material_audit.ledger_rows(
                                     grid, samples, reserved, sched_error)
                                 + material_audit.capacity_drift_rows(grid))}

        # -- 人工核对项组 ----------------------------------------------------
        manual_group = {"key": "manual", "label": "人工核对项", "error": None,
                        "rows": material_audit.manual_rows(grid.get("topology") or {})}

        groups = [presence_group, derived_group, ledger_group, manual_group]
        raw = {name: {"value": value, "bits": format(value & 0xFF, "08b")}
               for name, value in byte_values.items()}
        if "IX12" in byte_values:
            raw["IX12"]["tool_detect_bits"] = [
                bool(byte_values["IX12"] >> b & 1) for b in (4, 5, 6)]
        return {"checked_at": checked_at,
                "counts": material_audit.count_rows(groups),
                "groups": groups, "raw": raw, "grid": grid}
