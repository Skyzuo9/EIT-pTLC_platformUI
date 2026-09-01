"""地轨第 7 维派生 (单真源)
========================
功能:
    分支感知走图 + 原子·分支 rail 求值。把"该走哪个地轨槽"从人肉字面量变为可从点位 (point.rail)
    推导的值, 供三处复用同一套逻辑, 杜绝两份走图分叉:
      1. 契约测试 test_rail_point_consistency_offline (字面量 vs 点 rail 一致性校验)。
      2. B1 注入脚本 tools/insert_rail_ensure (求每个空手接缝原子·分支应注入的 rail.ensure(N))。
      3. B1 注入正确性断言测试。

设计:
    走 operation body, 线程 current_rail (随 rail_move_safe(N) / 直接 rail.move(N) 变), 每遇
    robot.move_to_point 回调 on_move(ref, current_rail, certain)。分支 guard 用注入 env 求值:
    能定值的分支才 certain=True (消多态歧义); 未知 guard 过近似走所有分支并标 certain=False。
    rail=None 的点 (过渡/枢纽/未收编) 豁免, 不参与判定。
"""

from __future__ import annotations

_UNKNOWN = object()
_HOME_POINT_ID = "robot-main.home"      # P1 的 point_id; require_anchor 可用 P1 或此别名指 home


def _num(x):
    """尽力把 x 转 float; 非数返回 None (供类型宽容比较)。"""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cmp(op, a, b):
    """类型宽容比较 (VM 变量可能是字符串 '1' 与整型字面量 1)。返回 bool 或 _UNKNOWN。"""
    if op in ("==", "!="):
        eq = a == b or str(a) == str(b) or (
            _num(a) is not None and _num(a) == _num(b))
        return eq if op == "==" else not eq
    na, nb = _num(a), _num(b)
    if na is None or nb is None:
        na, nb = str(a), str(b)
    if op == "<":
        return na < nb
    if op == ">":
        return na > nb
    if op == "<=":
        return na <= nb
    if op == ">=":
        return na >= nb
    return _UNKNOWN


def ev(expr, env):
    """求值一个 VM value/cond 表达式 (lit/var/binop) -> 具体值或 _UNKNOWN。"""
    if not isinstance(expr, dict):
        return expr
    if "lit" in expr:
        return expr["lit"]
    if "var" in expr:
        return env.get(expr["var"], _UNKNOWN)
    if "binop" in expr:
        op = expr["binop"]
        left = ev(expr.get("left"), env)
        right = ev(expr.get("right"), env)
        if op in ("and", "or"):
            lb = None if left is _UNKNOWN else bool(left)
            rb = None if right is _UNKNOWN else bool(right)
            if op == "and":
                if lb is False or rb is False:
                    return False
                return True if (lb and rb) else _UNKNOWN
            if lb or rb:
                return True
            return False if (lb is False and rb is False) else _UNKNOWN
        if left is _UNKNOWN or right is _UNKNOWN:
            return _UNKNOWN
        return _cmp(op, left, right)
    return _UNKNOWN


def rail_of(reg, ref):
    """查点 ref 的 rail 槽 (派生点从 base 继承); 未知点返回 None。"""
    try:
        return reg.get(str(ref)).rail
    except KeyError:
        return None


def walk(nodes, rail, env, stack, certain, on_move, docs):
    """按序走一段 body, 线程 current_rail; 每个 move_to_point 调 on_move(ref, rail, certain)。

    参数:
        nodes: body 节点列表; rail: 进入本段时的 current_rail; env: 分支 guard/表达式求值环境;
        stack: 防 run_script 递归环; certain: 当前路径是否被 guard 确定选中;
        on_move: 回调 (ref:str, rail:int|None, certain:bool); docs: {operation name -> doc} (供子脚本展开)。
    返回:
        走完本段后的 current_rail。
    """
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        op = node.get("op")
        if op == "call":
            action = node.get("action")
            if action == "robot.move_to_point":
                ref = ev((node.get("args") or {}).get("point_id_or_robot_name"), env)
                if ref not in (None, _UNKNOWN):
                    on_move(str(ref), rail, certain)
            elif action in ("rail.move", "rail.ensure"):
                # 设槽机制: rail.move=直接移轨 (全流程/demo); rail.ensure=原子 enter 幂等确认/补移
                # (Win B, 删 rail_move_safe 后的运行期设槽). 二者均把 current_rail 推进到目标槽。
                tv = ev((node.get("args") or {}).get("Rail_Target_Position"), env)
                if isinstance(tv, int):
                    rail = tv
            continue
        if op == "run_script":
            script = node.get("script", "")
            inputs = node.get("inputs") or {}
            if script == "rail_move_safe":
                tgt = ev(inputs.get("target"), env)
                if isinstance(tgt, int):
                    rail = tgt
            elif script in docs and script not in stack:
                child = {}
                for k, vexpr in inputs.items():
                    val = ev(vexpr, env)
                    if val is not _UNKNOWN:
                        child[k] = val
                rail = walk(docs[script].get("body"), rail, child,
                            stack + [script], certain, on_move, docs)
            continue
        if op == "if":
            cond = ev(node.get("cond"), env)
            if cond is True:
                walk(node.get("then"), rail, env, stack, certain, on_move, docs)
            elif cond is False:
                body = node.get("else")
                for eb in node.get("elifs") or []:
                    if ev(eb.get("cond"), env) is True:
                        body = eb.get("body")
                        break
                walk(body, rail, env, stack, certain, on_move, docs)
            else:  # 未知 guard -> 近似走所有分支并标 certain=False
                walk(node.get("then"), rail, env, stack, False, on_move, docs)
                for eb in node.get("elifs") or []:
                    walk(eb.get("body"), rail, env, stack, False, on_move, docs)
                walk(node.get("else"), rail, env, stack, False, on_move, docs)
            continue
        for key in ("body", "then", "else", "finally"):
            if node.get(key):
                walk(node.get(key), rail, env, stack, certain, on_move, docs)
        for br in node.get("branches") or []:
            walk(br.get("body") if isinstance(br, dict) else br,
                 rail, env, stack, certain, on_move, docs)
        for h in node.get("catch") or []:
            walk(h.get("body"), rail, env, stack, certain, on_move, docs)
    return rail


def branch_rail(branch_body, reg, *, docs=None, env=None):
    """一段原子分支 body 走图, 返回其到达的 work 点唯一 rail 槽 (决策 #6: 每分支 rail 恒定)。

    参数:
        branch_body: 分支节点列表; reg: PointRegistry; docs: 子脚本展开表 (机器人原子分支通常无);
        env: 分支已定的选择变量 (rack_id/slot_id 等)。
    返回:
        int (该分支唯一非空 rail) 或 None (分支无带 rail 的 work 点)。
    异常:
        ValueError: 分支内出现 >1 种 rail (混轨, 违背决策 #6)。
    """
    rails: set = set()

    def on_move(ref, _rail, _certain):
        pr = rail_of(reg, ref)
        if pr is not None:
            rails.add(pr)

    walk(branch_body, None, dict(env or {}), [], True, on_move, docs or {})
    if len(rails) > 1:
        raise ValueError(f"原子分支混轨 (决策 #6 违背): {sorted(rails)}")
    return next(iter(rails), None)


def entry_anchor(branch_body):
    """分支首节点若为 robot.require_anchor, 返回其 point_id 字面量 (未定值时为 _UNKNOWN); 否则 None。

    空手接缝原子的 entry 锚点为 home (P1); 据此判定"臂在 P1 时可安全注入移轨"。
    """
    for node in branch_body or []:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "call" and node.get("action") == "robot.require_anchor":
            return ev((node.get("args") or {}).get("point_id"), {})
        return None                          # 首个有效节点非 require_anchor -> 无 entry 锚
    return None


def is_home_anchor(anchor, reg):
    """anchor 是否解析到 home 点 (P1 / robot-main.home): 空手接缝的判据。

    require_anchor 的 point_id 可写 P1 或别名 robot-main.home (同一点); 变量/未定值 (_UNKNOWN)
    因无法静态确定不算 home (安全侧: 宁跳过不误注)。
    """
    if anchor in ("P1", _HOME_POINT_ID):
        return True
    if not isinstance(anchor, str):
        return False
    try:
        p = reg.get(anchor)
    except KeyError:
        return False
    return getattr(p, "point_id", None) == _HOME_POINT_ID or getattr(p, "robot_name", None) == "P1"


def branch_bodies(doc):
    """把一个机器人原子文档拆成其"分支体"列表 (可原位编辑的节点列表)。

    顶层 if 的 then / 每 elif.body / else 各为一条分支; 无顶层 if 则整个 body 视为一条分支。
    与注入脚本、注入正确性断言测试共用同一拆分, 避免结构走图分叉。
    """
    body = doc.get("body")
    if not body:
        return []
    result = []
    for node in body:
        if isinstance(node, dict) and node.get("op") == "if":
            if node.get("then") is not None:
                result.append(node["then"])
            for eb in node.get("elifs") or []:
                if eb.get("body") is not None:
                    result.append(eb["body"])
            if node.get("else") is not None:
                result.append(node["else"])
    return result or [body]
