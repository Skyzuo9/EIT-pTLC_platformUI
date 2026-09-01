"""薄层板位置的沙盒只读投影
============================
功能:
    把沙盒里**已经存在的现场事实**(板位人工账 seat_occupancy / 板仓张数 / 板堆物理模型)
    换成三维板层能消费的 L1 形状, 供 GET /api/sim/plate_positions。

    真实链上这份数据来自调度器 (GET /api/scheduler/snapshot -> experiments.db 的
    samples.position), 而沙盒**不装调度器**(隔离铁律)。于是仿真页的板层此前一直是死的:
    端点 404, PlateLedgerStore 恒 received=false, 一块 L1 板都不建, 搬运时只长出无主的
    L3 推断板 —— 三层仲裁里"L2 只允许在 L1 认可的相邻两态间插值"那道闸门等于不存在。

它不是第二套调度器 (逐条对照 FlowScheduler 是什么, 不靠自称):
    无队列与派发循环 · 无资源仲裁与缸池 · 无物料预留 · 无持久化 (连内存表都没有,
    只有一个 int revision) · **零写** · 不订阅事件总线 · 沙盒 VM 不读它所以不能影响
    任何执行。它与 mock/behavior/sensors.SensorModel 同一范畴 —— 把已有现场事实换个
    形状读出来; 区别是 SensorModel 还写 IX 字节, 本模块连写都没有。

它不是第二套板账本:
    seat_occupancy 表本来就在库里, material_topology.yaml 写明它存在的理由正是
    "调度器 samples.position 只在有批次跑着时才有内容 —— 于是'人手动把板拿走了'
    这件事无处同步"。本模块只是把这张已有的表读成 L1 形状, 真机侧一个字节不动。

诚实边界 (载荷里的 coverage 块把它讲给前端听, 不靠文档):
    * 能给**位置**, 给不出**身份** —— 沙盒没有 sample_id 的来源
      (VM 运行只报 origin=sim), 故合成 id 自报 synthetic 且**永不带 jobs[]**:
      编一个 run_id 会让 L2 迁移错误归属, 比不归属更坏。
    * 缸里有哪块板**完全给不出** —— 那在真机上是调度器缸池的状态, 不是现场账;
      Tank_State 只表达液相相位, 拿它当板位是纯编造。
    * 因此"缺"必须区别于"空": 直接少报一个落点, 前端的 _syncLedger 会把那里的板
      **回收**掉 —— 板消失且无任何线索, 比 404 更危险。coverage.slots 就是那道闸。
"""

from __future__ import annotations

#: 会产出 sample 行的落点 = 物料拓扑里的两个板位座 (material_topology.yaml 的 seats)
#: 词表与 web 的 PlateSlots.PLATE_SLOT 逐字一致, 那不是巧合: 拓扑注释写明 seat id
#: 刻意复用调度器的 _SINGLE_SLOTS 词表。
#: 2026-08-13 补 8 个展缸位: 拓扑给它们建了座 (material_topology 的 seats), 流程经
#: material_bindings 的 plate_seat / plate_stage 维护, 于是"缸里有哪块板"在沙盒里
#: 第一次说得清 —— 此前那是调度器缸池的状态, 沙盒不装调度器故只能报 uncovered。
SEAT_SLOTS = ("spot_seat", "scrape_table") + tuple(
    f"tank:{index}" for index in range(1, 9))

#: 座名 (账本) -> 落点名 (前端 PLATE_SLOT 词表)。缸位两边写法不同: 账本用 tank_3
#: (SQL 标识符友好), 前端与调度器用 tank:3。**只此一处换算**, 别处一律用落点名。
SEAT_TO_SLOT = {f"tank_{index}": f"tank:{index}" for index in range(1, 9)}

#: 本投影能 authoritative 地回答的**全部**落点。比 SEAT_SLOTS 多两个板仓:
#: 仓里有几张沙盒是知道的 (板堆模型), 只是不为它们建独立板实例 —— 前端
#: isMagazineSlot 会把仓态样品从 plates() 里滤掉, 仓由料仓堆叠画。
#: 两者必须分开: 混用会让"某个座恰好叫 feedlift"这类形状问题变成产假 sample。
COVERED_SLOTS = SEAT_SLOTS + ("feedlift", "waste")

#: 给不出的落点及其原因 —— 前端据此跳过回收, 并如实标注"L1 覆盖外"
UNCOVERED = (("carried",),)

_NOTES = {
    "carried": "板被吸盘带着走是三维派生的位置词, 后端词表里没有它; "
               "沙盒靠吸盘真空位 (rob_suction) 自行维持与释放。",
    "run_index": "沙盒 VM 运行不带 sample_id (sim_routes 只报 origin=sim), 故无 "
                 "run_id -> 样品 的索引; 本投影永不产出 jobs[]。",
    "seat": "点样座 / 刮板拍照台在真机上也没有在位传感器 (material_topology.yaml 已声明), "
            "只有人工账; 流程不自动更新它, 需要经 POST /api/sim/materials/seat 摆。",
    "magazine": "两个板仓不产 sample: 仓态由 material_state 的 magazines 推给料仓堆叠画, "
                "为它们造 sample 只会污染板层计数 (前端 onPlate=false 本就会滤掉)。",
}


def project_plate_positions(*, seats, magazines, feedlift_model, revision: int) -> dict:
    """把沙盒现场事实投影成 L1 板位快照 (纯函数, 零副作用).

    参数:
        seats: material_store.grid()["seats"] —— 板位人工账 [{seat, label, present, ...}]
        magazines: material_store.grid()["magazines"] —— 板仓账面 [{magazine, count, ...}]
        feedlift_model: FeedLiftModel —— 板堆物理真源 (张数/标定/触发位)
        revision: 单调递增的版本号 (内容变化才 +1; 沙盒销毁归 0)
    返回:
        Dict, 与 PlateLedgerStore.push 消费的字段逐字对齐, 另带 coverage / identity /
        magazines 三块自述信息

    刻意**不含** resources / tanks / reservations / wip_limit / occupancy / boot_report:
    给一个空的 tanks 等于宣称"八个缸都没人占", 那是假数据。
    (occupancy 另有一层: PlateLedgerStore.push 里的 occupancy 是它自己按 position 折算的
     函数内局部量, 根本不读快照里的同名字段。)
    """
    samples = []
    for index, row in enumerate(seats or []):
        if not row.get("present"):
            continue
        seat = str(row.get("seat") or "")
        slot = SEAT_TO_SLOT.get(seat, seat)
        if slot not in SEAT_SLOTS:
            continue
        samples.append({
            "sample_id": f"sim:seat:{seat}",
            "seq": index + 1,
            # 刻意用 ATTENTION_STATUSES 词表外的值: 写 RUNNING 会假装有作业在跑
            "status": "PRESENT",
            "tank": None,
            "position": slot,
            # 工艺阶段 (blank/spotted/developed/scraped): 账本 seat_occupancy.stage
            # 的直读。前端优先用它, 缺席才退回从调度器 jobs 推导 —— live 载荷没有
            # 这个字段, 于是那边逐字不变。
            "stage": str(row.get("stage") or "blank"),
            "message": f"{row.get('label') or seat}: 板位人工账 "
                       f"(POST /api/sim/materials/seat)",
            "origin": "seat_ledger",
            "synthetic": True,
            # 恒空: 沙盒没有 run_id -> 样品 的索引, 编一个会让 L2 迁移错误归属
            "jobs": [],
        })

    rows = []
    for row in (magazines or []):
        name = str(row.get("magazine") or "")
        calib = (feedlift_model.calib or {}).get(name)
        model_count = int((feedlift_model.counts or {}).get(name, 0))
        ledger_count = int(row.get("count") or 0)
        rows.append({
            "magazine": name,
            "label": row.get("label") or name,
            "capacity": int(row.get("capacity") or 0),
            "ledger_count": ledger_count,
            "model_count": model_count,
            # 两者相等是"账面已回灌进物理模型"的可视化; 不等即回灌链断了
            "diverged": ledger_count != model_count,
            "pitch_mm": float(getattr(calib, "pitch_mm", 0.0) or 0.0),
            "z_empty_mm": float(getattr(calib, "z_empty_mm", 0.0) or 0.0),
            "z_trigger_mm": (float(feedlift_model.z_trigger(name))
                             if calib is not None else None),
            "photo": None,
            "proximity": bool(feedlift_model.proximity(name)) if calib is not None else None,
            "homed": bool((feedlift_model.homed or {}).get(name, False)),
        })

    uncovered = [slot for group in UNCOVERED for slot in group]
    return {
        "revision": int(revision),
        "source": "sandbox-projection/v1",
        # 身份是位置合成的 —— 前端据此决定 L2 迁移能不能按落点归属
        "identity": "synthetic",
        "coverage": {
            "slots": list(COVERED_SLOTS),
            "uncovered": uncovered,
            "run_index": "unavailable",
            "notes": dict(_NOTES),
        },
        "batches": [{
            "batch_id": "sandbox",
            "name": "沙盒现场事实",
            "status": "RUNNING",
            "samples": samples,
        }],
        "magazines": rows,
    }
