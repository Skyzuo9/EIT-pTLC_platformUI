"""运行前入参 (inputs) 校验
==========================
功能:
    在起跑前校验一张入参 map 的取值域 —— 声明了 enum 的 in 变量, 传进来的值必须是
    其中之一。未跑先拒, 免得机器人 home 完、换完刀, 才在脚本末尾的
    `else: raise ROBOT_FLOW_SELECTOR` 处炸掉。

与 knobs.validate_overrides 的分工:
    两者校验的是**两条不同的提交通道**, 故分两个模块 (knobs.py 的模块契约明确自限于
    "旋钮 = 带 ui 的 in var 这一 opt-in 白名单", 把入参校验塞进去会糊掉那个心智模型):
        inputs    —— 用户在运行前设置面板逐项填的入口入参, 只注入入口帧
                     (thread._make_frame), 每次起跑都提交。
        overrides —— 旋钮覆盖, 线程级按名注入每一帧 (含深层子脚本), 只提交"动过的"。
    取值域本身是共用的: 两条通道都经 schema.var_enum 读同一个字段, 走 value_domain
    的同一个成员判定。

刻意不做"未知入参"检查:
    inputs 通道上除脚本 in 变量外还有别的合法载荷 —— SamplingMultiPanel 传 samples、
    调度器 _build_inputs 注入 ctx/batch 键。白名单会大面积误伤, 故只校"声明了取值域的
    那些项", 其余一律放行。
"""

from __future__ import annotations

from eit_ptlc.operation.vm.errors import VmError
from eit_ptlc.operation.vm.expr import coerce_value
from eit_ptlc.operation.vm.schema import var_enum
from eit_ptlc.value_domain import check_enum


def validate_inputs(doc: dict, inputs: dict) -> list[str]:
    """校验一张入口入参 map 的取值域; 返回错误消息列表 (空=通过).

    只校入口文档里 io=="in" 且声明了 enum 的变量 —— 深层子脚本的入参由
    run_script.inputs 的表达式给出 (静态可查), 不走这条运行期通道。

    参数:
        doc: 入口脚本文档
        inputs: 入参 map (名 -> 值)
    返回:
        错误消息列表
    """
    if not inputs:
        return []
    errors: list[str] = []
    for vd in (doc.get("vars") or []):
        if not isinstance(vd, dict) or vd.get("io") != "in":
            continue
        name = vd.get("name")
        if name not in inputs:
            continue
        opts = var_enum(vd)
        if not opts:
            continue                        # 无取值域声明的入参: 自由值, 放行
        vtype = vd.get("type")
        val = inputs[name]
        # 空值单独报: VM 建帧是"给了键就写值"(thread._make_frame), 空串会被原样写进变量
        # 而**不是**回退到 default —— 那必落 else 分支。"取默认"的正确做法是不提交这个键
        # (前端 collectInputs 正是这么做的), 故此处给出可操作的提示而非笼统的"不在可选值内"。
        if val is None or (isinstance(val, str) and val.strip() == ""):
            errors.append(f"入参 {name}: 留空; 该参数有可选值域, 需明确选一个 "
                          f"(要取脚本默认值请不要提交该键)")
            continue
        # 先报类型问题 (强转失败), 免得同一个错被成员判定再报一遍
        try:
            coerce_value(vtype, val)
        except VmError as exc:
            errors.append(f"入参 {name}: {exc}")
            continue
        err = check_enum(opts, val, coerce=lambda v: coerce_value(vtype, v))
        if err:
            errors.append(f"入参 {name}: {err}")
    return errors
