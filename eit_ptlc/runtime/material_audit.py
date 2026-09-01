"""物料一键审查的核对纯函数层
==============================
功能:
    把"账 (materials.db) 与实 (传感器/机器人/调度器) 的核对"全部做成纯函数:
    输入是已经读好的快照 (在位对账行 / IX 字节 / 缸态数组 / 调度器样品位置 / 账本 grid),
    输出是统一行结构的核对结果。取数与组装在 api/material_audit_routes.py, 本模块
    不碰 app、不做 IO —— 与 controller/feedlift_count.preflight_gate 同一先例,
    可以离线直测。

    统一行结构:
        {id, label, severity, expected, actual, note, fix, goto}
        severity: mismatch     账实矛盾且判定可信
                  warn         矛盾但存在合法解释 / 判据是推定值
                  unverifiable 有账可比但传感器极性未实证 (只显读数不判定)
                  ok           核对一致
                  skip         该项依赖不可达 (robot 忙 / 调度器未装 / 读失败)
        fix:  {action, payload, label, confirm} 或 None —— action 是**闭集动作名**
              (magazine/bottle/staging/rack/seat/payload_seat/reservation_release),
              前端用映射表转成既有写端点调用, 不执行后端下发的任意 URL;
              修复永远是人显式点按钮, 审查本身只报不改。
        goto: {cat} 或 None —— 指向物料页某子页 (无一键修复时给人工处置入口)。

主要函数:
    presence_rows / magazine_bottom_rows / collect_bottle_row / tool_state_row /
    tank_rows / ledger_rows / capacity_drift_rows / manual_rows / count_rows
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from eit_ptlc.controller.feedlift_count import preflight_gate

log = logging.getLogger(__name__)

# severity 闭集 (前端样式映射与 count_rows 都以此为准)
SEV_MISMATCH = "mismatch"
SEV_WARN = "warn"
SEV_UNVERIFIABLE = "unverifiable"
SEV_OK = "ok"
SEV_SKIP = "skip"
SEVERITIES = (SEV_MISMATCH, SEV_WARN, SEV_UNVERIFIABLE, SEV_OK, SEV_SKIP)

# 样品的终止态: 位置账/预留对这些样品不再有意义
_SAMPLE_TERMINAL = ("DONE", "ABORTED", "SKIPPED")

# Tank_State 相位含义 (与 mock/plc_server.run_tank_drain_fsm 及 PLC ST 同一词表)
_TANK_STATE_TEXT = {0: "空闲", 10: "备液中", 50: "排液中", 55: "吹扫中", 56: "干燥中",
                    90: "错误", 98: "已排空待复用", 99: "已排空待复用"}
# 无主时仍带残留状态的相位 (需要人工排液/释放)
_TANK_RESIDUAL_STATES = (10, 50, 55, 56, 98, 99)


def _row(row_id: str, label: str, severity: str, *, expected: str = "", actual: str = "",
         note: str = "", fix: Optional[dict] = None, goto: Optional[dict] = None,
         **extra: Any) -> dict:
    """拼一行统一结构 (extra 允许带 presence 原字段供前端悬停提示)."""
    out = {"id": row_id, "label": label, "severity": severity, "expected": expected,
           "actual": actual, "note": note, "fix": fix, "goto": goto}
    out.update(extra)
    return out


def skip_row(row_id: str, label: str, reason: str) -> dict:
    """拼一行 skip (依赖不可达); 组装层在某取数源失败时用它替代该源的全部行."""
    return _row(row_id, label, SEV_SKIP, note=reason)


# ----------------------------------------------------------------------
# ① 传感器在位核对 (复用 reconcile_presence 的行, 换算成统一结构)
# ----------------------------------------------------------------------

def presence_rows(recon_rows: list[dict]) -> list[dict]:
    """把 reconcile_presence 的行映射成审查行.

    功能:
        expected 为 None 的行 (上料两处与件位传感器: 无软件账或另有专项核对) 不进本组;
        verified=False 且有账可比 -> unverifiable (读数与账面并排显示, 不判定);
        其余按 ok 判 mismatch/ok。中转位"传感器报空但账记板 N"给一键置空修复;
        反方向 (报有料但账空) 板号无从知道, 只给跳转。
    参数:
        recon_rows: MaterialStore.reconcile_presence(values)["rows"]
    返回:
        list[dict], 统一行结构 (附带 sensor/byte/bit/raw/present/verified 原字段)
    """
    out: list[dict] = []
    for row in recon_rows:
        if row.get("expected") is None:
            continue
        raw_extra = {key: row.get(key) for key in
                     ("location_id", "sensor", "byte", "bit", "polarity", "verified",
                      "raw", "present", "kind", "plate")}
        present = bool(row.get("present"))
        expected = bool(row.get("expected"))
        expected_text = "传感器应报有料" if expected else "传感器应报无料"
        actual_text = f"传感器={'有料' if present else '无料'} · 账面期望{'有' if expected else '无'}"
        row_id = f"presence.{row.get('location_id')}"
        if not row.get("verified"):
            out.append(_row(row_id, str(row.get("label") or ""), SEV_UNVERIFIABLE,
                            expected=expected_text, actual=actual_text,
                            note="极性未实证, 只显读数不判定", **raw_extra))
            continue
        if row.get("ok") is True:
            out.append(_row(row_id, str(row.get("label") or ""), SEV_OK,
                            expected=expected_text, actual=actual_text, **raw_extra))
            continue
        # 判定不一致: 中转位报空而账记板号 -> 一键以实为准置空; 其余方向只给跳转
        fix = None
        goto = {"cat": "tray"}
        location_id = str(row.get("location_id") or "")
        if location_id.startswith("staging-") and not present and expected:
            fix = {"action": "staging", "payload": {"area": location_id, "plate": None},
                   "label": "以实为准: 置空",
                   "confirm": f"传感器报 {row.get('label')} 无料, 将把该中转位账面置空 "
                              f"(原记录的板号会被清掉), 无撤销。"}
        out.append(_row(row_id, str(row.get("label") or ""), SEV_MISMATCH,
                        expected=expected_text, actual=actual_text,
                        note=str(row.get("note") or ""), fix=fix, goto=goto, **raw_extra))
    return out


# ----------------------------------------------------------------------
# ② 派生核对 (传感器 + 账本的跨域推导)
# ----------------------------------------------------------------------

def magazine_bottom_rows(ix8: int, magazines: list[dict]) -> list[dict]:
    """板仓账面张数 vs 仓底接近开关 (IX8.5/8.6).

    功能:
        接近开关只能判"仓内有板/空仓", 判不了张数, 但足以抓两类矛盾:
        账面 >0 而仓底说空 -> mismatch + 一键置 0 (以实为准);
        账面 =0 而仓底说有 -> mismatch, 真实张数未知, 指向标定向导实测 (会动轴,
        刻意不给一键修复, 审查绝不触发动轴操作)。
        判据可信依据: PLC 的清零/上升动作 ST 直接拿这两个位当前置门 (裸位语义),
        与 controller/feedlift_count.preflight_gate 同一出处。
    参数:
        ix8: IX8 字节现值; magazines: grid()["magazines"] 行
    返回:
        list[dict]
    """
    out: list[dict] = []
    for item in magazines:
        magazine = str(item.get("magazine") or "")
        if magazine not in ("feed", "waste"):
            continue
        gate = preflight_gate(magazine, ix8)
        prox = bool(gate["proximity"])
        count = int(item.get("count") or 0)
        label = str(item.get("label") or magazine)
        actual = f"账面 {count} 张 · 仓底接近开关={'有板' if prox else '空'}"
        row_id = f"derived.magazine.{magazine}"
        if count > 0 and not prox:
            out.append(_row(
                row_id, label, SEV_MISMATCH,
                expected="账面 >0 时仓底应检测到板", actual=actual,
                note="接近开关是 PLC 自己的物料互锁判据 (裸位=1 即有板), 可信",
                fix={"action": "magazine", "payload": {"magazine": magazine, "count": 0},
                     "label": "以实为准: 置 0",
                     "confirm": f"仓底接近开关报空仓, 将把 {label} 账面板数改写为 0, 无撤销。"},
                goto={"cat": "glass"}))
        elif count == 0 and prox:
            out.append(_row(
                row_id, label, SEV_MISMATCH,
                expected="账面 =0 时仓底应检测不到板", actual=actual,
                note="仓内有板但账面为 0; 真实张数未知, 请到玻璃板页用标定向导实测盘点 "
                     "(会动轴, 不在本审查内)",
                goto={"cat": "glass"}))
        else:
            out.append(_row(row_id, label, SEV_OK,
                            expected="仓底开关与账面有无一致", actual=actual))
    return out


def collect_bottle_row(presence_row: Optional[dict],
                       payload_seats: list[dict]) -> Optional[dict]:
    """收集工位瓶位: IX8.1 传感器 vs payload_seat['collect-bottle'] 座位账.

    功能:
        拓扑未声明该位置传感器时返回 None (整行不出现);
        verified=False 期间恒 unverifiable (双方数值照显, 不判定);
        翻 verified=True 后自动开始判定: 传感器空而账面有件 -> 一键清座位账;
        传感器有而账面空 -> 瓶身份未知, 指向件位子页人工放件。
        座位行陈旧不降可信度 (瓶子停在工位上, 后端重启它不会自己跑掉)。
    参数:
        presence_row: reconcile_presence 里 location_id='collect-bottle' 的行, 无则 None;
        payload_seats: grid()["payload_seats"] (只列被占的座)
    返回:
        dict 或 None
    """
    if presence_row is None:
        return None
    seat_row = next((row for row in payload_seats
                     if row.get("seat") == "collect-bottle"), None)
    present = bool(presence_row.get("present"))
    has_account = seat_row is not None
    if has_account:
        account_text = (f"账面: {seat_row.get('kind')} 板{seat_row.get('plate')} "
                        f"孔{seat_row.get('hole')}")
    else:
        account_text = "账面: 空"
    actual = f"传感器={'有瓶' if present else '无瓶'} · {account_text}"
    row_id = "derived.collect_bottle"
    label = "收集工位瓶位"
    if not presence_row.get("verified"):
        return _row(row_id, label, SEV_UNVERIFIABLE, actual=actual,
                    note="传感器极性未实证 (同族推定 NO), 只显读数不判定; "
                         "现场放瓶/取瓶各读一次核实后在拓扑翻 verified 即自动激活判定")
    if present == has_account:
        return _row(row_id, label, SEV_OK, expected="传感器与座位账一致", actual=actual)
    if has_account and not present:
        return _row(
            row_id, label, SEV_MISMATCH,
            expected="账面有瓶时传感器应报有瓶", actual=actual,
            note="瓶已不在工位但座位账还挂着",
            fix={"action": "payload_seat", "payload": {"seat": "collect-bottle"},
                 "label": "以实为准: 清座位账",
                 "confirm": "传感器报收集工位无瓶, 将清掉该座位账 (瓶的孔位状态请随后在"
                            "盘位页自行更正), 无撤销。"},
            goto={"cat": "holder"})
    return _row(row_id, label, SEV_MISMATCH,
                expected="账面空时传感器应报无瓶", actual=actual,
                note="工位上有瓶但账面没记; 瓶的身份 (板/孔) 未知, 请到件位页人工放件",
                goto={"cat": "holder"})


def tool_state_row(ix12: Optional[int], mounted_tool: Optional[int],
                   skip_reason: str = "") -> dict:
    """机器人工具检测位 (IX12.4-6) vs 上位机权威工具态 (mounted_tool).

    功能:
        skip_reason 非空 (robot 不可达/运动中) -> skip;
        位语义按"位 N=1 即 N 号工具在刀架"推定 (依据: 三位曾同时读到 [1,1,0],
        若是腕侧挂载检测不可能两位同时为 1)。期望 = 挂在腕上的那把不在刀架。
        该族极性未现场实证, 不符只给 warn 不给 mismatch。工具态修正走机器人侧,
        不在物料写端点集内, 故无 fix。
    参数:
        ix12: IX12 字节现值 (None 表示没读到); mounted_tool: 0=裸腕, 1/2/3=工具号
        skip_reason: 不可核对的原因
    返回:
        dict
    """
    row_id = "derived.robot_tool"
    label = "机器人工具刀架"
    if skip_reason:
        return skip_row(row_id, label, skip_reason)
    if ix12 is None:
        return skip_row(row_id, label, "IX12 未读到")
    bits = [bool(int(ix12) >> b & 1) for b in (4, 5, 6)]
    mounted = int(mounted_tool or 0)
    expected_bits = [tool != mounted for tool in (1, 2, 3)]
    actual = (f"刀架检测位={[int(b) for b in bits]} · 腕上工具="
              f"{mounted if mounted else '无 (裸腕)'}")
    if bits == expected_bits:
        return _row(row_id, label, SEV_OK,
                    expected=f"期望检测位={[int(b) for b in expected_bits]}", actual=actual)
    return _row(row_id, label, SEV_WARN,
                expected=f"期望检测位={[int(b) for b in expected_bits]}", actual=actual,
                note="按'位=1 即工具在刀架'推定判不符; 该族极性未现场实证, 仅提示。"
                     "工具态修正走机器人页, 不在物料账内")


def tank_rows(tank_states: list[int], owners: dict) -> list[dict]:
    """展缸 Tank_State vs 调度器缸占用账.

    功能:
        只判两条鲁棒规则 (释放缸会驱动硬件, 违反只报不改, 故一律无 fix):
        state=90 -> warn 错误态; 无主但 state 有残留 (10/50/55/56/98/99) -> warn
        "有残留状态无人认领"。有主而 state=0 是派发-开跑之间的正常瞬态, 记 ok。
    参数:
        tank_states: read_all_tank_states() 的 8 元素数组 (下标 0 = 1 号缸);
        owners: 调度器 snapshot()["tanks"] ({缸号字符串: 占用者}), 无主的缸不在其中
    返回:
        list[dict]
    """
    out: list[dict] = []
    for index, state in enumerate(tank_states):
        tank = index + 1
        owner = owners.get(str(tank))
        state = int(state)
        state_text = _TANK_STATE_TEXT.get(state, f"state={state}")
        actual = f"Tank_State={state} ({state_text}) · 调度占用={owner or '无'}"
        row_id = f"derived.tank.{tank}"
        label = f"{tank} 号展缸"
        if state == 90:
            out.append(_row(row_id, label, SEV_WARN,
                            expected="缸不应处于错误态", actual=actual,
                            note="缸处于错误态 (90), 需人工排查后释放"))
        elif not owner and state in _TANK_RESIDUAL_STATES:
            out.append(_row(row_id, label, SEV_WARN,
                            expected="无人认领的缸应为空闲 (0)", actual=actual,
                            note="缸有残留状态但调度器无人认领, 需人工排液/释放 "
                                 "(释放会驱动硬件, 不提供一键修复)"))
        else:
            out.append(_row(row_id, label, SEV_OK, actual=actual))
    return out


# ----------------------------------------------------------------------
# ③ 软件双账核对 (纯账本/调度器, 不依赖 PLC)
# ----------------------------------------------------------------------

def capacity_drift_rows(grid: dict) -> list[dict]:
    """库内容量/名称 vs 拓扑声明 (种子漂移检测).

    功能:
        板仓容量与溶剂瓶容量/名称只在建库时 INSERT OR IGNORE 播种一次
        (material_store._seed), 改拓扑 yaml 对已存在的库无效 —— 本函数把这种
        "声明与库内不一致"揪出来。处置是一次性迁移 (停机手工 UPDATE 或删行重启
        重播), 频率不足以养一个修正端点, 故只给指引无 fix。
    参数:
        grid: MaterialStore.grid()
    返回:
        list[dict]
    """
    out: list[dict] = []
    topo_mag: dict[str, float] = {}
    topo_bottle: dict[str, tuple] = {}
    for cat in (grid.get("topology") or {}).get("categories", []):
        for item in cat.get("magazines", []):
            topo_mag[str(item.get("id"))] = float(item.get("capacity") or 0)
        for item in cat.get("bottles", []):
            topo_bottle[str(item.get("id"))] = (str(item.get("label") or ""),
                                                float(item.get("capacity_ml") or 0.0))
    note = ("容量/名称只在建库时播种 (INSERT OR IGNORE), 改拓扑 yaml 对老库无效; "
            "处置: 停机后手工 UPDATE 库或删行重启重播")
    for item in grid.get("magazines", []):
        magazine = str(item.get("magazine"))
        declared = topo_mag.get(magazine)
        if declared is None:
            continue
        actual_cap = float(item.get("capacity") or 0)
        if actual_cap != declared:
            out.append(_row(
                f"ledger.capacity.magazine.{magazine}",
                f"{item.get('label') or magazine} 容量", SEV_WARN,
                expected=f"拓扑声明 {declared:g} 张", actual=f"库内 {actual_cap:g} 张",
                note=note, goto={"cat": "glass"}))
    for item in grid.get("bottles", []):
        bottle = str(item.get("bottle"))
        declared = topo_bottle.get(bottle)
        if declared is None:
            continue
        declared_label, declared_cap = declared
        actual_cap = float(item.get("capacity_ml") or 0.0)
        if actual_cap != declared_cap or str(item.get("label") or "") != declared_label:
            out.append(_row(
                f"ledger.capacity.bottle.{bottle}",
                f"{item.get('label') or bottle} 容量/名称", SEV_WARN,
                expected=f"拓扑声明 {declared_label} / {declared_cap:g} mL",
                actual=f"库内 {item.get('label')} / {actual_cap:g} mL",
                note=note, goto={"cat": "solvent"}))
    return out


def ledger_rows(grid: dict, samples: Optional[list[dict]], reserved: dict,
                sched_error: str = "") -> list[dict]:
    """软件双账核对: 座位账 vs 调度器位置 / 陈旧在途 / 孤儿预留 / 越界.

    功能:
        seat_occupancy (人工板位账) vs 调度器 samples.position —— 不一致是 warn
        (两种合法解释: 人拿走了板没同步, 或调度账没收尾), 一键修复 = 以调度为准;
        payload_transit 里 stale=True 的行 -> warn (上一进程遗留, 爪上有没有东西
        没人能确认; 去向必须人选, 无一键修复); 座位账的 stale 行**刻意不列**
        (语义为仍可信, 列出来是制造假告警);
        预留的 sample_id 不在任何批次或已终止 -> 孤儿预留, 一键释放;
        越界 (板仓张数>容量 / 瓶余量>瓶容量 / 孔位液量>名义容量) -> mismatch,
        真值未知不许猜, 只给跳转。
    参数:
        grid: MaterialStore.grid(); samples: 调度器全部样品行 (含 status/position),
        None 表示调度器不可达; reserved: MaterialStore.reserved_summary();
        sched_error: 调度器不可达时的原因 (samples 为 None 时必填)
    返回:
        list[dict]
    """
    out: list[dict] = []

    # -- seat_occupancy vs samples.position ------------------------------
    if samples is None:
        out.append(skip_row("ledger.seat", "板位 vs 调度器位置",
                            sched_error or "调度器未就绪"))
    else:
        active = [s for s in samples if s.get("status") not in _SAMPLE_TERMINAL]
        for seat_row in grid.get("seats", []):
            seat = str(seat_row.get("seat"))
            label = str(seat_row.get("label") or seat)
            holders = [s.get("sample_id") for s in active if s.get("position") == seat]
            sched_has = bool(holders)
            manual_has = bool(seat_row.get("present"))
            actual = (f"人工账={'有板' if manual_has else '无板'} · "
                      f"调度器={'样品 ' + ', '.join(map(str, holders)) if sched_has else '无'}")
            row_id = f"ledger.seat.{seat}"
            if manual_has == sched_has:
                out.append(_row(row_id, label, SEV_OK, actual=actual))
            else:
                note = ("人工记有板但调度器没有样品在此: 可能是人手动放的板, 或调度账已收尾"
                        if manual_has else
                        "调度器记样品在此但人工账无板: 可能是人拿走了板没同步账")
                out.append(_row(
                    row_id, label, SEV_WARN, actual=actual, note=note,
                    fix={"action": "seat",
                         "payload": {"seat": seat, "present": sched_has},
                         "label": f"以调度为准: 记{'有' if sched_has else '无'}板",
                         "confirm": f"将把 {label} 人工账改为"
                                    f"{'有板' if sched_has else '无板'} (以调度器为准), "
                                    f"无撤销。"},
                    goto={"cat": "seat"}))

    # -- 陈旧在途 ---------------------------------------------------------
    for carrier, row in (grid.get("transit") or {}).items():
        if not row.get("stale"):
            continue
        target = (f"板{row.get('plate')}" if row.get("payload") == "tray"
                  else f"板{row.get('plate')} 孔{row.get('hole')}")
        out.append(_row(
            f"ledger.transit.{carrier}", f"在途载荷 ({carrier})", SEV_WARN,
            actual=f"账面: {row.get('kind')} {target} 在爪上 (上一进程记录)",
            note="陈旧在途 = 上一进程遗留, 爪上是否真有东西没人能确认; "
                 "去向 (记回货架/记入中转/只清行) 必须人选, 请到盘位页顶部在途条处置",
            goto={"cat": "tray"}))

    # -- 孤儿预留 ---------------------------------------------------------
    if samples is None:
        if reserved:
            out.append(skip_row("ledger.reservations", "物料预留",
                                sched_error or "调度器未就绪, 无法判定预留归属"))
    else:
        known = {str(s.get("sample_id")): str(s.get("status") or "") for s in samples}
        for kind, entry in (reserved or {}).items():
            holders = list(entry.get("count_level") or [])
            holders += [hole.get("sample_id") for hole in (entry.get("holes") or [])]
            for sample_id in dict.fromkeys(map(str, holders)):
                status = known.get(sample_id)
                if status is not None and status not in _SAMPLE_TERMINAL:
                    continue
                reason = ("样品不在任何批次中" if status is None
                          else f"样品已终止 ({status})")
                out.append(_row(
                    f"ledger.reservation.{kind}.{sample_id}",
                    f"预留 ({kind})", SEV_WARN,
                    actual=f"样品 {sample_id} 仍占着 {kind} 预留",
                    note=f"{reason}, 预留不会再被消耗, 会白白挡住其它样品取料",
                    fix={"action": "reservation_release",
                         "payload": {"sample_id": sample_id, "kind": kind},
                         "label": "释放预留",
                         "confirm": f"将释放样品 {sample_id} 的 {kind} 预留 "
                                    f"(若该样品其实还要跑, 它开工时会重新预留), 无撤销。"}))

    # -- 越界 -------------------------------------------------------------
    for item in grid.get("magazines", []):
        count = int(item.get("count") or 0)
        capacity = int(item.get("capacity") or 0)
        if capacity > 0 and count > capacity:
            out.append(_row(
                f"ledger.range.magazine.{item.get('magazine')}",
                f"{item.get('label') or item.get('magazine')} 张数", SEV_MISMATCH,
                expected=f"0..{capacity} 张", actual=f"账面 {count} 张",
                note="超出物理容量, 账面必错; 真实张数未知, 请实测或按现场改写",
                goto={"cat": "glass"}))
    for item in grid.get("bottles", []):
        volume = float(item.get("volume_ml") or 0.0)
        capacity = float(item.get("capacity_ml") or 0.0)
        if capacity > 0 and volume > capacity:
            out.append(_row(
                f"ledger.range.bottle.{item.get('bottle')}",
                f"{item.get('label') or item.get('bottle')} 余量", SEV_MISMATCH,
                expected=f"0..{capacity:g} mL", actual=f"账面 {volume:g} mL",
                note="余量超过瓶容量, 账面必错", goto={"cat": "solvent"}))
    liquid_cap = 0.0
    for cat in (grid.get("topology") or {}).get("categories", []):
        for content in cat.get("contents", []):
            if content.get("kind") == "bottle":
                liquid_cap = float(content.get("capacity") or 0.0)
    if liquid_cap > 0:
        for cell in grid.get("cells", []):
            liquid = float(cell.get("liquid_ml") or 0.0)
            if liquid > liquid_cap:
                out.append(_row(
                    f"ledger.range.cell.{cell.get('kind')}.{cell.get('plate')}"
                    f".{cell.get('hole')}",
                    f"样品瓶 板{cell.get('plate')} 孔{cell.get('hole')} 液量",
                    SEV_MISMATCH,
                    expected=f"0..{liquid_cap:g} mL", actual=f"账面 {liquid:g} mL",
                    note="液量超过瓶腔名义容量 (记账为估算值, 超限即估错), 请人工覆盖",
                    goto={"cat": "tray"}))
    return out


# ----------------------------------------------------------------------
# ④ 人工核对项 (机器无法核验的账, 如实列出防误报)
# ----------------------------------------------------------------------

def manual_rows(topology: dict) -> list[dict]:
    """不可感知清单: 每行指向对应编辑子页.

    功能:
        照 feedlift_count.preflight_gate 的 unobservable 字段的诚实度 —— 审查只能
        证伪不能证真, 机器看不见的账必须如实点名, 否则"全绿"会被误读成"全对"。
        清单是静态的 (由硬件现实决定, 不随账面变化)。
    参数:
        topology: grid()["topology"] (取分类存在性, 拓扑删类后行自动消失)
    返回:
        list[dict], severity 一律 unverifiable
    """
    cats = {cat.get("key") for cat in (topology or {}).get("categories", [])}
    catalog = [
        ("tray", "72 格耗材新旧与内容物",
         "孔位 FRESH/USED、粉量、液量、已淋洗均无测量硬件 (粉按视觉轮廓估, 液按动作参数算), "
         "只能人工盘点"),
        ("tray", "货架 12 库位在架",
         "12 路光电传感器未供电 (2026-07-26 实测与物理零耦合), 板级在架只能人工记账"),
        ("solvent", "溶剂瓶余量",
         "硬件无任何体积测量, 余量按动作参数推算, 请定期人工盘点"),
        ("seat", "点样座/刮板台有无板",
         "两处无任何在位传感器, 纯人工账"),
        ("glass", "板仓精确张数",
         "精确盘点需清零+逼近实测 (会动 1Z/2Z 轴), 请到玻璃板页标定向导执行; "
         "本审查只做仓底有无板的零成本矛盾检测"),
        ("holder", "刮板夹具/收集工位夹具上的件",
         "两个收集器件位无传感器, 座位账由流程事件维护, 异常时人工清账/放件"),
    ]
    out: list[dict] = []
    for index, (cat, label, note) in enumerate(catalog):
        if cat not in cats:
            continue
        out.append(_row(f"manual.{index}", label, SEV_UNVERIFIABLE, note=note,
                        goto={"cat": cat}))
    return out


# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------

def count_rows(groups: list[dict]) -> dict:
    """按 severity 汇总全部组的行数 (组级 error 不计入行数, 由前端单独渲染横幅)."""
    counts = {"mismatch": 0, "warn": 0, "unverifiable": 0, "ok": 0, "skipped": 0}
    key_of = {SEV_MISMATCH: "mismatch", SEV_WARN: "warn",
              SEV_UNVERIFIABLE: "unverifiable", SEV_OK: "ok", SEV_SKIP: "skipped"}
    for group in groups:
        for row in group.get("rows", []):
            key = key_of.get(str(row.get("severity")))
            if key is not None:
                counts[key] += 1
    return counts
