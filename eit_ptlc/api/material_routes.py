"""物料账本路由
============
功能:
    注册五类物料 (盘位 / 上料 / 玻璃板 / 溶剂 / 板位) 的查询、人工盘点与在位对账端点到
    FastAPI 应用。各类及其位置与传感器的真源是 config/material_topology.yaml,
    经 /materials/topology 透出, 前端左侧导航与页面分区据此渲染, 不再硬编码。
    全部从 app.state.material_store (MaterialStore) 读写; 未就绪返回 503。
    账本是建议式的: next/suggest 只给前端预填输入框用, 不参与任何执行决策;
    在位对账只报不改 (传感器只知有/无, 知不了孔级余量; 上料两处无软件账故不判定)。

端点 (前缀 /api):
    GET  /materials                       四类物料完整快照 (盘位/上料/玻璃板/溶剂 + 在位对账)
    GET  /materials/topology              四类物料树 (位置与传感器); 前端据此渲染
    GET  /materials/next?kind=            下一个建议消耗的孔位; 无可用返回 available=false
    GET  /materials/suggest?script=&vars= 某脚本输入框的预填建议 (变量名 -> 建议值)
    GET  /materials/events?kind=&plate=&hole=  追溯流水 (倒序)
    POST /materials/mark                  人工盘点: 单孔或整板置状态
    POST /materials/staging               人工盘点: 设置某中转区当前装的板号
    POST /materials/transit               人工清账: 清掉某夹爪上滞留的在途载荷
    POST /materials/payload_seat          人工盘点工位座: 只给 seat=清账, 带 kind/plate/hole=放件
    POST /materials/rack                  人工盘点: 设置货架库位板级在架状态 (有板/无板)
    POST /materials/magazine              人工盘点: 设置玻璃板仓板数
    POST /materials/bottle                人工盘点: 设置溶剂瓶余量 mL
    POST /materials/cell_amount           人工盘点: 设置单件内容物 (粉 mm³ / 液 mL / 已淋洗)
    POST /materials/seat                  人工盘点: 设置单板停放位有板/无板 (只供展示)
    POST /materials/reservations/release  人工释放某样品的物料预留 (孤儿预留处置口)
    POST /materials/reconcile             读 PLC 输入映像与账本做位置级在位对账
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.runtime.material_store import KINDS

log = logging.getLogger(__name__)


def register_material_routes(app: FastAPI, *, prefix: str = "/api/materials",
                             store_getter=None, plc_getter=None) -> None:
    """把物料账本路由注册到应用。

    功能:
        默认参数下行为与历史版本逐字相同 (挂 /api/materials, 从 app.state 取账本与
        PLC)。仿真沙盒再注册一次并换掉三个参数, 即得到一组挂在 /api/sim/materials
        的镜像端点 —— 15 个 handler 的校验与话术是同一份契约, 抄一份必漂。
    参数:
        app: FastAPI 应用; prefix: 端点前缀
        store_getter: (request) -> MaterialStore; 缺省取 app.state.material_store
        plc_getter: (request) -> PlcController; 缺省取 app.state.plc
    返回:
        None
    """

    def _default_store(request: Request):
        store = getattr(request.app.state, "material_store", None)
        if store is None:
            raise HTTPException(503, "物料账本未就绪")
        return store

    def _default_plc(request: Request):
        return getattr(request.app.state, "plc", None)

    _store = store_getter or _default_store
    _plc = plc_getter or _default_plc

    @app.get(f"{prefix}")
    async def get_materials(request: Request):
        return _store(request).grid()

    @app.get(f"{prefix}/next")
    async def get_material_next(request: Request, kind: str):
        if kind not in KINDS:
            raise HTTPException(400, f"耗材种类应为 {KINDS} 之一, 收到 {kind!r}")
        hit = _store(request).next_fresh(kind)
        if hit is None:
            # 账本无可用余量: 前端据此退回流程声明的 default, 不报错 (账本无权威)
            return {"available": False, "kind": kind}
        return {"available": True, **hit}

    @app.get(f"{prefix}/suggest")
    async def get_material_suggest(request: Request, script: str, vars: str = ""):
        """输入框预填建议; vars 为逗号分隔的 in 变量名列表. 无建议时 inputs 为空对象."""
        names = [v.strip() for v in vars.split(",") if v.strip()]
        return _store(request).suggest_inputs(script, names)

    @app.get(f"{prefix}/events")
    async def get_material_events(request: Request, kind: str | None = None,
                                  plate: int | None = None, hole: int | None = None,
                                  limit: int = 200):
        events = _store(request).list_events(kind=kind, plate=plate, hole=hole, limit=limit)
        return {"events": events}

    @app.post(f"{prefix}/mark")
    async def post_material_mark(request: Request):
        """人工盘点: body 含 kind/state 必填, plate 必填; hole 省略表示整板."""
        body = await request.json()
        store = _store(request)
        kind = str(body.get("kind") or "")
        state = str(body.get("state") or "")
        plate = body.get("plate")
        hole = body.get("hole")
        if plate is None:
            raise HTTPException(400, "缺少 plate (货架板号 1-6)")
        try:
            if hole is None:
                store.mark_plate(kind, int(plate), state)
            else:
                store.mark(kind, int(plate), int(hole), state,
                           sample_id=str(body.get("sample_id") or ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/staging")
    async def post_material_staging(request: Request):
        """人工盘点: body 含 area 必填, plate 为板号或 null (表示该区空)."""
        body = await request.json()
        store = _store(request)
        area = str(body.get("area") or "")
        plate = body.get("plate")
        try:
            store.set_staging(area, None if plate is None else int(plate))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/transit")
    async def post_material_transit(request: Request):
        """人工清账: body 含 carrier 必填, land_at 可选 ("" | rack | staging).

        用在流程中途取消/断电后板滞留在夹爪上的场景 —— 这正是在途态存在的意义:
        旧账本在取放窗口里静默失同步且不留痕, 人无从下手。
        land_at 省略即"去向不明", 只清在途行不替人猜板落在哪。
        """
        body = await request.json()
        store = _store(request)
        try:
            store.clear_transit(str(body.get("carrier") or ""),
                                land_at=str(body.get("land_at") or ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/payload_seat")
    async def post_material_payload_seat(request: Request):
        """人工盘点工位座: body 只有 seat = 清账; 带 kind/plate/hole 三元组 = 放件.

        清账与 /transit 对称但**没有 land_at**: 件被人从刮板夹具上拿走之后去了哪里,
        账本无从知道也不该猜。清完之后由人在中转板那一节自行更正孔位状态。
        放件是清账的反向 (盘点发现座上有件而账本没有): 形状照 /staging 的
        "null 清 / int 设" 先例, 三元组只给一部分按写错拒 400。
        """
        body = await request.json()
        store = _store(request)
        identity = [body.get("kind"), body.get("plate"), body.get("hole")]
        given = [value for value in identity if value is not None]
        try:
            if not given:
                store.clear_payload_seat(str(body.get("seat") or ""))
            elif len(given) == len(identity):
                store.seat_payload_manually(
                    str(body.get("seat") or ""), str(body.get("kind") or ""),
                    int(body.get("plate") or 0), int(body.get("hole") or 0))
            else:
                raise HTTPException(
                    400, "放件需要 kind/plate/hole 三项齐全; 清账则三项都不给")
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/reservations/release")
    async def post_material_reservation_release(request: Request):
        """人工释放某样品的物料预留: body 含 sample_id 必填, kind 可选.

        批次异常收尾后卡死的计数级/孔级预留会白白挡住其它样品取料 —— 一键审查的
        "孤儿预留"行指到这里, 这是唯一的人工释放口。幂等: 没有可删行不报错。
        若该样品其实还要跑, 它开工时会重新预留, 释放不会造成永久伤害。
        """
        body = await request.json()
        store = _store(request)
        sample_id = str(body.get("sample_id") or "")
        if not sample_id:
            raise HTTPException(400, "缺少 sample_id")
        kind = body.get("kind")
        released = store.release_reservations(sample_id, str(kind) if kind else None)
        log.info("[物料] 人工释放预留: 样品 %s (%s) 共 %d 行",
                 sample_id, kind or "全部", released)
        return store.grid()

    @app.post(f"{prefix}/rack")
    async def post_material_rack(request: Request):
        """人工盘点: body 含 kind/plate/present (bool). 板在中转位时 400 (先更正中转占用).

        货架 12 路光电无信号, 板级在架只能人工记账; "无板"参与决策 (统计剔除,
        plan_staging/next_fresh/reserve_count 跳过该库位)。
        """
        body = await request.json()
        store = _store(request)
        present = body.get("present")
        if not isinstance(present, bool):
            raise HTTPException(400, "present 应为布尔值 (true=有板, false=无板)")
        try:
            store.set_rack_presence(str(body.get("kind") or ""),
                                    int(body.get("plate") or 0), present)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/magazine")
    async def post_material_magazine(request: Request):
        """人工盘点玻璃板仓: body 含 magazine (feed|waste) 与 count."""
        body = await request.json()
        store = _store(request)
        try:
            store.set_magazine(str(body.get("magazine") or ""), int(body.get("count") or 0))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/bottle")
    async def post_material_bottle(request: Request):
        """人工盘点溶剂瓶: body 含 bottle 与 volume_ml."""
        body = await request.json()
        store = _store(request)
        try:
            store.set_bottle(str(body.get("bottle") or ""), float(body.get("volume_ml") or 0.0))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/cell_amount")
    async def post_material_cell_amount(request: Request):
        """人工盘点单件内容物: body 含 kind/plate/hole, 及 powder_mm3 / liquid_ml / eluted 至少一项.

        粉量与液量都是**估算值**(粉 = 视觉轮廓面积 × 切深 × 松散系数, 液 = 动作参数 × 次数),
        无任何测量硬件 —— 与溶剂瓶余量同一处境, 故与 POST /materials/bottle 一样只能靠人
        覆盖式改回。试机空跑造成的假数据也走这里清。
        缺省的字段不动: 清粉量不会顺带抹掉已淋洗标志。
        """
        body = await request.json()
        store = _store(request)
        eluted = body.get("eluted")
        if eluted is not None and not isinstance(eluted, bool):
            raise HTTPException(400, "eluted 应为布尔值 (true=已被洗脱液淋过)")
        try:
            store.set_cell_amount(
                str(body.get("kind") or ""), int(body.get("plate") or 0),
                int(body.get("hole") or 0),
                powder_mm3=body.get("powder_mm3"), liquid_ml=body.get("liquid_ml"),
                eluted=eluted)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.post(f"{prefix}/seat")
    async def post_material_seat(request: Request):
        """人工盘点单板停放位: body 含 seat, 以及 present (bool) 与/或 stage (str).

        板位 (点样座 / 刮板拍照台 / 8 个展缸) 无任何在位传感器, 故只有这一份账。
        ⚠ 边界 (2026-08-13 订正): 流程也会写它 (material_bindings 的 plate_seat /
        plate_stage), 但它**仍不参与任何耗材孔决策与统计口径** —— 不写调度器的
        samples.position, 不进 plan_staging / next_fresh / 批次准入 / summary。

        present 与 stage 可单给也可同给; 同给时先摆板再定阶段 (空座写阶段会被拒)。
        """
        body = await request.json()
        store = _store(request)
        seat = str(body.get("seat") or "")
        present = body.get("present")
        stage = body.get("stage")
        if present is None and stage is None:
            raise HTTPException(400, "present 与 stage 至少给一个")
        if present is not None and not isinstance(present, bool):
            raise HTTPException(400, "present 应为布尔值 (true=有板, false=无板)")
        try:
            if present is not None:
                store.set_seat_presence(seat, present)
            if stage is not None:
                if not store.set_seat_stage(seat, str(stage)):
                    raise HTTPException(409, f"{seat} 座上无板, 无法设置工艺阶段")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.grid()

    @app.get(f"{prefix}/topology")
    async def get_material_topology(request: Request):
        """四类物料树 (每类的位置与传感器); 前端左侧导航与页面分区据此渲染, 不再硬编码."""
        return _store(request).topology_dto()

    @app.post(f"{prefix}/reconcile")
    async def post_material_reconcile(request: Request):
        """读 PLC 输入映像与账本做位置级在位对账 (只报不改).

        按拓扑一次性读齐需要的输入字节 (IX8/9/10/11/12), 逐位置按各自极性折算"有料"。
        传感器只知有/无, 知不了孔级余量, 且账本是建议式的 —— 故此端点只落快照与差异,
        处置由人在物料页盘点。上料两处无软件账, 只落现值不判定。
        """
        store = _store(request)
        plc = _plc(request)
        if plc is None:
            raise HTTPException(503, "PLC 控制器未就绪, 无法读取在位传感器")
        names = store.topology.byte_names()
        values: dict[str, int] = {}
        for name in names:
            try:
                value = await plc.read_host_var(name)
            except Exception as exc:
                # 未下装 / 符号未发布 / 断链: 明确告知, 不静默给个假快照
                raise HTTPException(
                    503, f"读取输入字节 {name} 失败 (未发布或 PLC 断链): {exc}") from exc
            if value is None:
                # 读到 None 不是"全空", 是读不到 —— 绝不能当 0 用 (会得到一张骗人的全空快照)
                raise HTTPException(
                    503, f"输入字节 {name} 读回空值; 节点存在但无值, "
                         f"通常是 PLC 未运行或输入映像未刷新")
            values[name] = int(value)
        result = store.reconcile_presence(values)
        # 原始字节随响应返回: 某组位全 0 时要能一眼分清"传感器真没触发"与"输入映像没读到";
        # IX12 高位是机器人工具检测, 有值即证明该字节所在 IO 模块是活的 (交叉验证锚点)
        raw = {name: {"value": value, "bits": format(value & 0xFF, "08b")}
               for name, value in values.items()}
        if "IX12" in values:
            raw["IX12"]["tool_detect_bits"] = [bool(values["IX12"] >> b & 1) for b in (4, 5, 6)]
        return {**result, "raw": raw, "grid": store.grid()}
