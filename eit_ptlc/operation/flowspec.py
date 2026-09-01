"""原子流程 (Atomic Flow) 规范化校验器 — 树级静态检查
=====================================================
概念分层 (并行实验系统的两级规范化单元):
    原子动作 = 执行最小单元 (action registry 条目), 不可拆分; 其"资源足迹"可推导 (下表)。
    原子流程 = 并行调度最小单元: 带 flow: 块且通过本校验器的 operation 脚本。调度器只派发
    原子流程; 段边界即样品停放点、即检查点。

本模块校验的树级约束 (单文件形状校验在 vm/schema.py::_validate_flow_block):
    R1 资源闭合律: 根 resources ⊇ 体内全部动作足迹(独占) ∪ 后代脚本根声明(独占),
       减去 with_resources 区间覆盖的部分。机械空间类资源 (staging-b, scrape-holder,
       collect-holder, collect-bottle, consumable-group) 无法从动作推导, 只存在于脚本根
       声明 —— 后代根声明并入 required 正是为兜住它们。
    R2 HITL 一致律: 树内含 human 节点 ⟺ flow.hitl == "confirm" (双向)。
    R3 防死锁律 W1/W2 树级复查: 跨 run_script 边界的区间嵌套关系, 每文件校验看不到,
       在此按运行期真实持有集 (根 + 沿途区间; 后代脚本根声明运行期不获取, 不算持有) 复查。

边界停放律 (进出时样品在停放位、机器人空手安全位) 无法静态证明 —— 由 R1-R4 + 配方位置
连续性 (recipe.py) + 各脚本自带的入出口硬门联合保证, 这是约定 + 运行期门, 非静态定理。
"""

from __future__ import annotations

from typing import Callable, Optional

from eit_ptlc.operation.resources import MODE_EXCLUSIVE
from eit_ptlc.operation.vm.schema import child_blocks

# 脚本递归展开深度上限 (与 vm/thread.MAX_CALL_DEPTH 同量级; 防环兜底)
_MAX_DEPTH = 64

# 原子动作资源足迹: action.station (小写) -> 独占资源名。None = 无独占工位映射。
# pump: 真空经 device:vacuum_pump 共享钩子 (禁止直调), 其余泵动作无独占工位。
STATION_RESOURCE: dict[str, Optional[str]] = {
    "sampling": "station:sampling",
    "develop": "station:develop",
    "collect": "station:collect",
    "photoscrape": "station:photo_scrape",   # 注意拼写差异: 动作 station 无下划线
    "feedlift": "station:feedlift",
    "rail": "station:rail",
    "staging_a": "staging-a",
    "pump": None,
}

# 按动作名的足迹特例表 (覆盖 kind/station 推导; 当前为空, 留扩展点)
FOOTPRINT_OVERRIDES: dict[str, frozenset[str]] = {}

# 机器人足迹并入地轨: 机器人运动期间地轨绝不可被他人移动 (机器人基座在轨上,
# 轨动 = 在飞轨迹整体平移, 必撞), 故 robot 类动作恒 = {robot, station:rail}。
_ROBOT_FOOTPRINT = frozenset({"robot", "station:rail"})


def action_footprint(adef) -> frozenset[str]:
    """推导一个原子动作触碰的独占资源集 (原子动作规范: 足迹可推导).

    参数:
        adef: ActionDef (registry 条目)
    返回:
        独占资源名集合 (可能为空; 不含共享资源 —— 共享经引用计数, 不参与闭合律)
    """
    override = FOOTPRINT_OVERRIDES.get(adef.name)
    if override is not None:
        return override
    kind = adef.kind
    if kind == "robot":
        return _ROBOT_FOOTPRINT
    if kind == "rail_ensure":
        return frozenset({"station:rail"})
    if kind == "plc_l2":
        station = (adef.station or "").strip().lower()
        if station not in STATION_RESOURCE:
            # 未知工位名宁可报出来: 静默 ∅ 会让闭合律漏检
            raise ValueError(f"动作 {adef.name} 的 station={adef.station!r} 未在"
                             f" flowspec.STATION_RESOURCE 登记, 无法推导资源足迹")
        res = STATION_RESOURCE[station]
        return frozenset({res}) if res else frozenset()
    # host / vision / camera / plc_write / servo_target / device: 无独占足迹
    # (plc_write/servo_target 为点级写, 保守依赖脚本根声明; 有例外走 FOOTPRINT_OVERRIDES)
    return frozenset()


def check_station_map(resource_modes: dict[str, str]) -> list[str]:
    """启动自检: STATION_RESOURCE 右侧的名字必须都在资源表登记 (防两侧漂移)."""
    errors = []
    for station, res in STATION_RESOURCE.items():
        if res is not None and res not in resource_modes:
            errors.append(f"flowspec.STATION_RESOURCE[{station}]={res} 未在 config/resources.yaml 登记")
    return errors


def validate_flow(doc: dict, *, resolve: Callable[[str], dict], registry,
                  resource_modes: dict[str, str]) -> list[str]:
    """树级校验一个原子流程; 返回错误列表 (空=合法).

    参数:
        doc: 脚本文档 (应带 flow: 块; 无块或 atomic 非真即错 —— 本函数只被配方段调用)
        resolve: 脚本名 -> doc (ScriptRepo.get 的闭包; 缺脚本抛 KeyError)
        registry: ActionRegistry (动作足迹推导)
        resource_modes: 资源名 -> 模式 (exclusive|shared)
    """
    errors: list[str] = []
    flow = doc.get("flow")
    name = doc.get("name", "?")
    if not isinstance(flow, dict) or flow.get("atomic") is not True:
        return [f"{name}: 不是原子流程 (缺 flow: 块或 atomic 非 true), 不可作为配方段"]

    root_declared = frozenset(n for n in (doc.get("resources") or []) if isinstance(n, str))
    root_exclusive = frozenset(n for n in root_declared
                               if resource_modes.get(n) == MODE_EXCLUSIVE)

    state = {"required": set(), "has_human": False}

    def exclusives_of(names) -> frozenset[str]:
        if not isinstance(names, list):
            return frozenset()
        return frozenset(n for n in names if isinstance(n, str)
                         and resource_modes.get(n) == MODE_EXCLUSIVE)

    def walk(nodes: list, *, covered: frozenset, held: frozenset,
             stack: tuple[str, ...], where: str) -> None:
        if len(stack) > _MAX_DEPTH:
            errors.append(f"{name}: 脚本嵌套深度超限 (>{_MAX_DEPTH}) @ {where}")
            return
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            op = node.get("op")
            if op == "call":
                action = node.get("action")
                try:
                    adef = registry.get(action)
                except KeyError:
                    errors.append(f"{name}: 未知动作 {action} @ {where}")
                    continue
                try:
                    fp = action_footprint(adef)
                except ValueError as exc:
                    errors.append(f"{name}: {exc}")
                    continue
                state["required"].update(fp - covered)
            elif op == "run_script":
                sub_name = node.get("script")
                if sub_name in stack:
                    errors.append(f"{name}: 脚本递归环 {' -> '.join(stack)} -> {sub_name}")
                    continue
                try:
                    sub = resolve(sub_name)
                except KeyError:
                    errors.append(f"{name}: 缺子脚本 {sub_name} @ {where}")
                    continue
                # 后代根声明并入 required: run_script 运行期不获取子脚本根资源,
                # 全靠本流程根声明覆盖 (机械空间类资源只在这里可见)
                sub_root_excl = exclusives_of(sub.get("resources"))
                state["required"].update(sub_root_excl - covered)
                walk(sub.get("body") or [], covered=covered, held=held,
                     stack=stack + (sub_name,), where=f"{where}/{sub_name}")
            elif op == "with_resources":
                names = node.get("resources") or []
                region_excl = exclusives_of(names)
                if region_excl:
                    overlap = region_excl & held
                    if overlap:
                        errors.append(
                            f"{name}: with_resources 重复获取已持有的独占资源"
                            f" {sorted(overlap)} @ {where} (W1 自死锁)")
                    elif held:
                        errors.append(
                            f"{name}: 已持有独占 {sorted(held)} 时体内区间又申请独占"
                            f" {sorted(region_excl)} @ {where} (W2 hold-and-wait)")
                walk(node.get("body") or [],
                     covered=covered | frozenset(n for n in names if isinstance(n, str)),
                     held=held | region_excl, stack=stack, where=f"{where}/with")
            elif op == "human":
                state["has_human"] = True
            else:
                for block_name, block in child_blocks(node):
                    walk(block, covered=covered, held=held, stack=stack,
                         where=f"{where}/{block_name}")

    walk(doc.get("body") or [], covered=frozenset(), held=root_exclusive,
         stack=(name,), where="b")

    # R1 资源闭合律
    missing = sorted(state["required"] - root_declared)
    if missing:
        errors.append(
            f"{name}: 违反资源闭合律 R1 — 体内触碰独占资源 {missing} 未在根 resources 声明"
            f" (根声明: {sorted(root_declared)})")
    # R2 HITL 一致律 (双向)
    hitl = flow.get("hitl", "none")
    if state["has_human"] and hitl != "confirm":
        errors.append(f"{name}: 违反 R2 — 树内含 human 节点但 flow.hitl={hitl!r} (应为 confirm)")
    if not state["has_human"] and hitl == "confirm":
        errors.append(f"{name}: 违反 R2 — flow.hitl=confirm 但树内无 human 节点")
    return errors
