"""mini-VM 解释线程
==================
功能:
    VmThread 是一台递归 async 解释器: 遍历脚本节点树逐节点执行, 借 Python 调用栈承载脚本调用栈
    与异常传播. 叶子设备调用复用 ActionExecutor; 控制流 (if/for/while/repeat/try/parallel/
    with_resources)、类型化作用域变量、HITL 挂起、单步调试门 (STEP/RUN/PAUSE/断点) 均在此实现.

设计要点:
    - 指令指针 current_aid 由树位置推导 (见 schema.aid_of), 仅在当前帧脚本内寻址.
    - 叶子执行前过 _checkpoint 调试门; 控制流节点透明穿过.
    - call 返回非 DONE -> 抛 VmActionError (fail-fast 与 try/catch 的挂钩).
    - 全部运行状态在进程内存; 事件经 emit 回调外发 (vm_* 与 operation_*).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Optional

from eit_ptlc.operation.vm.errors import VmActionError, VmError, VmRaise
from eit_ptlc.operation.vm.expr import coerce_value, default_value, eval_expr
from eit_ptlc.operation.vm.schema import LEAF_OPS, aid_of, is_knob_var
from eit_ptlc.operation.vm.state import Frame, GlobalEnv, Scope, Variable, VmStatus

log = logging.getLogger(__name__)

MAX_CALL_DEPTH = 64          # run_script 递归深度上限
DEFAULT_MAX_ITER = 100000    # while/repeat 默认最大迭代


class VmThread:
    """单脚本执行线程 (一个 async 协程驱动的 mini-VM)."""

    def __init__(
        self,
        doc: dict,
        *,
        executor,
        res_gate,
        resolve_script: Optional[Callable[[str], dict]] = None,
        emit: Optional[Callable[[dict], None]] = None,
        run_id: Optional[str] = None,
        mode_provider: Optional[Callable[[], Optional[str]]] = None,
        time_fn: Callable[[], float] = None,
        overrides: Optional[dict] = None,
        execution_generation: int = 1,
        meta: Optional[dict] = None,
        preset_vars: Optional[dict] = None,
    ) -> None:
        import time as _time
        self._root = doc
        self._executor = executor
        self._res_gate = res_gate
        self._resolve_script = resolve_script or (lambda name: (_ for _ in ()).throw(VmError(f"无脚本解析器, 无法调用子脚本 {name}")))
        self._emit = emit or (lambda e: None)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        # reset 会复用 run_id；execution_generation 用于区分同一 run 的新旧 VmThread，
        # 防止断线重连时旧线程快照覆盖复位后的新执行。
        self.execution_generation = int(execution_generation)
        self._mode_provider = mode_provider
        self._time = time_fn or _time.time
        # 运行前旋钮覆盖 (名 -> 值): 每次建帧时按名叠加到带 ui 的 in var 上, 见 _make_frame。
        # 线程级 (非仅根帧): 故能命中深层子脚本 in var, 消逐层 inputs 透传。
        self._overrides = dict(overrides or {})
        # 运行元信息 (origin/sample_id/batch_id 等): 由调度器/调用方自报, 非空时随
        # operation_start 事件外发, 供前端通道标注与实验库按 run 归属 (不参与执行语义)。
        self._meta = dict(meta or {})
        # 断点续跑变量回注 (根帧级): start_aid 快进会跳过 call/run_script 叶子, 其
        # assign/outputs 不会执行 —— 已产出的中间变量 (如 collector_hole) 必须由调用方
        # 从失败时的 vars 快照回注, 否则续跑段拿到的是默认值。只写已声明的非 const 变量。
        self._preset_vars = dict(preset_vars or {})

        self.status = VmStatus.NEW
        self.stack: list[Frame] = []
        self._global = GlobalEnv()
        self.current_aid: Optional[str] = None
        self.last_result = None
        # 当前仍在执行的 call/run_script 节点。一个脚本帧内的 AID 不是全局唯一，
        # 因此活动节点必须始终携带所属脚本名；列表保留重复项以支持递归/并行实例。
        self._active_nodes: list[dict[str, Any]] = []
        self._active_revision = 0

        # 调试控制
        self._step_mode = False
        # 单步地板: 仅在栈深 <= 此值的叶子停驻; None 表示任意层级都停 (步入 / 首叶子)
        self._step_floor: Optional[int] = None
        self._resume_evt = asyncio.Event()
        self.breakpoints: set[str] = set()
        # 终止中: 置位后, 在飞叶子动作一返回即把本次运行干净收尾为 KILLED (而非按动作失败 FAILED)
        self._terminating = False
        # HITL
        self._human_reply: Optional[asyncio.Future] = None
        self._pending_human: Optional[str] = None
        # 挂起的人工请求 payload (字段与 vm_human_request 事件一致, 去 type/run_id/ts);
        # 供 GET /api/debug/active 重建前端弹窗 (刷新/断线找回), 回复后清空
        self._pending_human_payload: Optional[dict] = None
        # 复位到节点: 结构化快进时跳过设备/人工叶子直至命中此 AID
        self._skip_to: Optional[str] = None

        self._handlers: dict[str, Callable] = {
            "call": self._op_call, "run_script": self._op_run_script, "assign": self._op_assign,
            "if": self._op_if, "for": self._op_for, "while": self._op_while, "repeat": self._op_repeat,
            "raise": self._op_raise, "try": self._op_try, "parallel": self._op_parallel,
            "with_resources": self._op_with_resources,
            "human": self._op_human, "comment": self._op_comment,
        }

    # ------------------------------------------------------------------
    # 顶层执行
    # ------------------------------------------------------------------

    async def run(self, inputs: Optional[dict] = None) -> VmStatus:
        """执行根脚本至终态; 返回终态 status.

        参数:
            inputs: 根脚本 in 变量入参 (名 -> 值)
        """
        frame = self._make_frame(self._root, inputs or {})
        # 断点续跑回注: 覆盖根帧已声明的非 const 变量 (含 io:var 的中间产物)
        for name, value in self._preset_vars.items():
            var = frame.locals.vars.get(name)
            if var is not None and var.io != "const":
                try:
                    var.value = coerce_value(var.type, value)
                except Exception:
                    log.warning("[VM %s] 续跑回注变量 %s 失败 (类型不符), 保留默认值",
                                self.run_id, name)
        self.stack.append(frame)
        self.status = VmStatus.RUNNING
        # inputs 随事件携带 = 本次运行的参数快照: 根脚本没有 run_script 节点包裹, 若不带则
        # 面板直跑 transfer_* 时 slot_id 在事件流里无处可寻 (物料账本据此记账)。
        self._emit({"type": "operation_start", "operation": self._root.get("name", ""),
                    "run_id": self.run_id, "label": self._root.get("label", self._root.get("name", "")),
                    "inputs": dict(inputs or {}),
                    "execution_generation": self.execution_generation,
                    **({"meta": dict(self._meta)} if self._meta else {}),
                    "ts": self._time()})
        self._emit_state()
        try:
            async with self._res_gate.acquire(list(self._root.get("resources") or []),
                                              holder=self.run_id):
                await self._exec_block(self._root.get("body", []), frame, (), "b")
            self.status = VmStatus.DONE
            self._finish("DONE", "")
        except VmRaise as exc:
            self.status = VmStatus.ERROR
            self._finish("FAILED", f"{exc.error}: {exc.message}")
        except VmActionError as exc:
            self.status = VmStatus.ERROR
            self._finish("FAILED", exc.result.message)
        except VmError as exc:
            self.status = VmStatus.ERROR
            self._finish("FAILED", str(exc))
        except asyncio.CancelledError:
            self.status = VmStatus.KILLED
            self._finish("CANCELLED", "已停止")
            raise
        except Exception as exc:
            # 驱动/集成层违反“不抛异常”契约时仍须终态化，否则线程会永久卡 RUNNING，
            # /debug/active 与前端高光也无法收口。
            log.exception("[VM %s] 未处理异常", self.run_id)
            self.status = VmStatus.ERROR
            self._finish("FAILED", f"内部异常: {exc}")
        return self.status

    def _finish(self, status_str: str, message: str) -> None:
        """发出终态事件 (operation_done|operation_failed)."""
        # 异常/取消可能绕过某些 vm_node_done；终态统一收口，避免活动高光残留。
        if self._active_nodes:
            self._active_nodes.clear()
            self._active_revision += 1
        ev = "operation_done" if status_str == "DONE" else "operation_failed"
        self._emit({"type": ev, "operation": self._root.get("name", ""), "run_id": self.run_id,
                    "status": status_str, "message": message,
                    "active_nodes": self.active_nodes(), "active_revision": self._active_revision,
                    "execution_generation": self.execution_generation,
                    "ts": self._time()})
        self._emit_state()

    # ------------------------------------------------------------------
    # 块 / 节点遍历
    # ------------------------------------------------------------------

    async def _exec_block(self, nodes: list, frame: Frame, base_path: tuple, block: str) -> None:
        for k, node in enumerate(nodes):
            await self._exec_node(node, frame, base_path + ((block, k),))

    async def _exec_node(self, node: dict, frame: Frame, path: tuple) -> None:
        op = node["op"]
        self.current_aid = aid_of(path)
        # 快进 (复位到节点 / 从选中行起跑): 命中目标前跳过设备/人工叶子 (assign 与控制流照常执行以
        # 推进变量/分支, 期间不经调试门停驻); 命中目标即清快进标记, 之后停/跑交由控制器预置的 _step_mode 决定
        if self._skip_to is not None and self.current_aid != self._skip_to:
            if op in ("call", "run_script", "human"):
                return
            await self._handlers[op](node, frame, path)
            return
        self._skip_to = None
        if op in LEAF_OPS:
            await self._checkpoint(path)
        await self._handlers[op](node, frame, path)

    # ------------------------------------------------------------------
    # 调试门 (STEP / RUN / PAUSE / 断点)
    # ------------------------------------------------------------------

    async def _checkpoint(self, path: tuple) -> None:
        """叶子执行前的停驻判定: 暂停 / 单步 / 断点 命中则进入等待.

        单步分步入 / 步过: _step_floor 为 None 表示任意层级都停 (步入 / 首叶子); 为整数 D
        表示仅在栈深 <= D 的叶子停, 借此让 step_over 跑完更深的子脚本叶子而不停驻.
        """
        aid = aid_of(path)
        step_hit = self._step_mode and (self._step_floor is None or len(self.stack) <= self._step_floor)
        if self.status == VmStatus.PAUSED or step_hit or aid in self.breakpoints:
            if self.status != VmStatus.PAUSED:
                self.status = VmStatus.STOPPED
            self.current_aid = aid
            self._emit_state()
            self._emit_vars()
            self._resume_evt.clear()
            await self._resume_evt.wait()
            self.status = VmStatus.RUNNING
            self._emit_state()

    # ------- 供 VmController 调用的调试动词 -------

    def step(self) -> None:
        """单步步入: 放行一个叶子后在下一个叶子 (任意层级, 含子脚本内部) 停驻."""
        self._step_mode = True
        self._step_floor = None
        self.status = VmStatus.RUNNING
        self._resume_evt.set()

    def step_over(self) -> None:
        """单步步过: 放行一个叶子; 若它下钻子脚本 (run_script), 更深层叶子照常执行但不停驻,
        直至回到当前栈深的下一叶子 (经典 step-over)."""
        self._step_mode = True
        self._step_floor = len(self.stack)
        self.status = VmStatus.RUNNING
        self._resume_evt.set()

    def cont(self) -> None:
        """自由运行 / 恢复 (置 RUNNING, 避免后续 checkpoint 误入暂停分支并清掉放行信号)."""
        self._step_mode = False
        self.status = VmStatus.RUNNING
        self._resume_evt.set()

    def pause(self) -> None:
        """请求暂停 (下一个叶子停驻)."""
        if self.status == VmStatus.RUNNING:
            self.status = VmStatus.PAUSED

    def mark_terminating(self) -> None:
        """标记本次运行为'终止中': 在飞叶子动作返回后干净收尾为 KILLED 而非 FAILED.

        配合 VmController.terminate/estop: 机器人软停/急停使在飞 move 以中止返回 CANCELLED,
        此标志让 _op_call 改抛 CancelledError 走 KILLED 路径, 避免被当成动作失败上报 ERROR.
        """
        self._terminating = True

    def set_breakpoints(self, aids) -> None:
        self.breakpoints = set(aids or [])

    def human_reply(self, req_id: str, payload: dict) -> bool:
        """回复一个 HITL 请求, 唤醒挂起的 human 节点.

        参数:
            req_id: 请求标识; payload: {choice?, values?}
        返回:
            是否成功 (req_id 匹配且未完成)
        """
        if self._pending_human != req_id or self._human_reply is None:
            return False
        if not self._human_reply.done():
            self._human_reply.set_result(dict(payload or {}))
        return True

    # ------------------------------------------------------------------
    # 变量
    # ------------------------------------------------------------------

    def _make_frame(self, doc: dict, inputs: dict) -> Frame:
        """按脚本变量定义构建一帧; global 变量进全局环境, 其余进局部; in 变量用入参覆盖默认."""
        local_vars: dict[str, Variable] = {}
        for vd in doc.get("vars", []) or []:
            scope = vd.get("scope", "local")
            # 无 default 的旋钮 = 可选覆盖参数 (如点样几何 spot_x_start/…): 未覆盖即保持 None (≡ 未提供),
            # 交动作层按"未给"走点表示教基准 (base-by-read, 见 executor._validate 的 None 跳过)。
            # 非旋钮 / 有 default 的变量仍取零值或声明默认 (coerce_value(None) 落零值)。覆盖注入在下方叠加。
            raw_default = vd.get("default")
            init_value = None if (is_knob_var(vd) and raw_default is None) else coerce_value(vd["type"], raw_default)
            var = Variable(name=vd["name"], scope=scope, type=vd["type"], io=vd.get("io", "var"),
                           value=init_value, comment=vd.get("comment", ""))
            if scope == "global":
                self._global.vars.setdefault(var.name, var)
            else:
                local_vars[var.name] = var
        for key, val in inputs.items():
            if key in local_vars:
                local_vars[key].value = coerce_value(local_vars[key].type, val)
        # 运行前旋钮覆盖: 在 inputs 之后叠加 (override 胜)。仅命中带 ui 的 in var (白名单=旋钮),
        # 天然跳过 const/scratch/out 与未暴露的 in var; 值仅做类型 coerce, 范围/枚举由运行前
        # 提交校验 (api) + 动作层 _validate 双重把关, 不在此热路径重复。此处即"零逐层透传"的注入点。
        if self._overrides:
            for vd in doc.get("vars", []) or []:
                if is_knob_var(vd) and vd["name"] in self._overrides:
                    var = local_vars.get(vd["name"]) or self._global.vars.get(vd["name"])
                    if var is not None:
                        var.value = coerce_value(var.type, self._overrides[vd["name"]])
        return Frame(script_name=doc.get("name", ""), locals=Scope(local_vars))

    def _lookup(self, frame: Frame, name: str) -> Optional[Variable]:
        if name in frame.locals.vars:
            return frame.locals.vars[name]
        return self._global.vars.get(name)

    def _read(self, frame: Frame, name: str) -> Any:
        var = self._lookup(frame, name)
        if var is None:
            raise VmError(f"读取未声明变量: {name}")
        return var.value

    def _write(self, frame: Frame, name: str, value: Any) -> None:
        var = self._lookup(frame, name)
        if var is None:
            raise VmError(f"写入未声明变量: {name}")
        if var.io == "const":
            raise VmError(f"不可写常量: {name}")
        var.value = coerce_value(var.type, value)

    def _reader(self, frame: Frame) -> Callable[[str], Any]:
        return lambda name: self._read(frame, name)

    # ------------------------------------------------------------------
    # 节点处理器
    # ------------------------------------------------------------------

    async def _op_call(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        args = {k: eval_expr(v, read) for k, v in (node.get("args") or {}).items()}
        self._emit_node_enter(node, path, args=args, script=frame.script_name)
        mode = node.get("mode") or (self._mode_provider() if self._mode_provider else None)
        res_names = node.get("resources")
        if res_names:
            async with self._res_gate.acquire(list(res_names), holder=self.run_id):
                res = await self._executor.execute(node["action"], args, current_mode=mode)
        else:
            res = await self._executor.execute(node["action"], args, current_mode=mode)
        # 终止中: 在飞动作 (含被软停/急停打断的 move) 一返回即干净收尾, 不再处理结果或推进
        if self._terminating:
            raise asyncio.CancelledError
        self.last_result = res
        # 不变量: 失败动作 (res.ok=False) 不得写它的 assign 目标 —— 被拒动作 res.result 默认 {},
        # 否则失败的重试 (如手绘/重识别 cnc_path) 会把上一有效结果冲空、而守卫标志仍 true,
        # 下发喂空 dict → KeyError 逃逸未捕获 → run 静默死亡、板卡压头下 (审阅 #1)。
        if node.get("assign") and res.ok:
            self._write(frame, node["assign"]["var"], res.result)
        self._emit_node_done(node, path, res.status.value, res.message, res.result,
                             script=frame.script_name)
        if not res.ok:
            raise VmActionError(res)

    async def _op_run_script(self, node: dict, frame: Frame, path: tuple) -> None:
        if len(self.stack) >= MAX_CALL_DEPTH:
            raise VmError(f"脚本调用深度超限 (>{MAX_CALL_DEPTH})")
        sub_doc = self._resolve_script(node["script"])
        read = self._reader(frame)
        inputs = {callee_in: eval_expr(expr, read) for callee_in, expr in (node.get("inputs") or {}).items()}
        self._emit_node_enter(node, path, args=inputs, script=frame.script_name)
        child = self._make_frame(sub_doc, inputs)
        try:
            self.stack.append(child)
            self._emit_state()
            try:
                await self._exec_block(sub_doc.get("body", []), child, (), "b")
                out_vals = {target["var"]: self._read(child, callee_out)
                            for callee_out, target in (node.get("outputs") or {}).items()}
            finally:
                self.stack.pop()
                self._emit_state()
            for caller_var, val in out_vals.items():
                self._write(frame, caller_var, val)
        except asyncio.CancelledError:
            self._emit_node_done(node, path, "CANCELLED", "已停止", {}, script=frame.script_name)
            raise
        except Exception as exc:
            if isinstance(exc, VmActionError):
                failed = exc.result
                self._emit_node_done(node, path, failed.status.value, failed.message,
                                     failed.result, script=frame.script_name)
            else:
                self._emit_node_done(node, path, "ERROR", str(exc), {}, script=frame.script_name)
            raise
        else:
            self._emit_node_done(node, path, "DONE", "", {}, script=frame.script_name)

    async def _op_assign(self, node: dict, frame: Frame, path: tuple) -> None:
        val = eval_expr(node["value"], self._reader(frame))
        self._write(frame, node["target"]["var"], val)

    async def _op_if(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        if eval_expr(node["cond"], read):
            await self._exec_block(node.get("then", []), frame, path, "then")
            return
        for i, br in enumerate(node.get("elifs", [])):
            if eval_expr(br["cond"], read):
                await self._exec_block(br.get("body", []), frame, path, f"elif{i}")
                return
        await self._exec_block(node.get("else", []), frame, path, "else")

    async def _op_for(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        var = node["var"]
        if "in" in node:
            for item in list(eval_expr(node["in"], read)):
                self._write(frame, var, item)
                await self._exec_block(node.get("body", []), frame, path, "body")
        else:
            start = int(eval_expr(node["start"], read))
            stop = int(eval_expr(node["stop"], read))
            step = int(eval_expr(node.get("step", {"lit": 1}), read))
            if step == 0:
                raise VmError("for 步长不能为 0")
            i = start
            while (step > 0 and i < stop) or (step < 0 and i > stop):
                self._write(frame, var, i)
                await self._exec_block(node.get("body", []), frame, path, "body")
                i += step

    async def _op_while(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        max_iter = int(node.get("max_iter", DEFAULT_MAX_ITER))
        count = 0
        while eval_expr(node["cond"], read):
            await self._exec_block(node.get("body", []), frame, path, "body")
            count += 1
            if count >= max_iter:
                raise VmError(f"while 超过最大迭代 {max_iter}")

    async def _op_repeat(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        max_iter = int(node.get("max_iter", DEFAULT_MAX_ITER))
        count = 0
        while True:
            await self._exec_block(node.get("body", []), frame, path, "body")
            count += 1
            if eval_expr(node["until"], read):
                break
            if count >= max_iter:
                raise VmError(f"repeat 超过最大迭代 {max_iter}")

    async def _op_raise(self, node: dict, frame: Frame, path: tuple) -> None:
        msg = eval_expr(node["message"], self._reader(frame)) if node.get("message") is not None else ""
        raise VmRaise(node["error"], str(msg))

    async def _op_try(self, node: dict, frame: Frame, path: tuple) -> None:
        try:
            await self._exec_block(node.get("body", []), frame, path, "body")
        except (VmRaise, VmActionError) as exc:
            err_name = exc.error
            handlers = node.get("catch", [])
            matched = next((i for i, h in enumerate(handlers)
                            if h.get("error") == err_name or h.get("error") == "*"), None)
            if matched is None:
                raise
            await self._exec_block(handlers[matched].get("body", []), frame, path, f"catch{matched}")
        finally:
            if node.get("finally"):
                await self._exec_block(node["finally"], frame, path, "finally")

    async def _op_parallel(self, node: dict, frame: Frame, path: tuple) -> None:
        branches = node.get("branches", [])
        join = node.get("join", "all")
        res_names = node.get("resources")

        async def run_branch(i: int, nodes: list) -> None:
            await self._exec_block(nodes, frame, path, f"br{i}")

        async def drive() -> None:
            tasks = [asyncio.create_task(run_branch(i, br)) for i, br in enumerate(branches)]
            try:
                if join == "any":
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for t in done:
                        if t.exception():
                            raise t.exception()
                else:
                    await asyncio.gather(*tasks)
            except BaseException:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        if res_names:
            async with self._res_gate.acquire(list(res_names), holder=self.run_id):
                await drive()
        else:
            await drive()

    async def _op_with_resources(self, node: dict, frame: Frame, path: tuple) -> None:
        """区间持有共享资源: 进入取得, 退出 (含异常/取消) 释放.

        资源门按引用计数合成物理开关, 因此嵌套或并发声明同一资源只在首个持有者进入时开启,
        最后一个持有者退出时关闭 —— 短流程收尾不会掐掉长流程仍在使用的设备.

        独占资源区间 (W1/W2 约束下由 schema 放行, 如展开等待段短取 station:develop 排液):
        进入时与其他运行按锁互斥排队, 退出即还 —— 等待期不持有任何其他独占, 无死锁风险.
        """
        async with self._res_gate.acquire(list(node.get("resources") or []),
                                          holder=self.run_id):
            await self._exec_block(node.get("body", []), frame, path, "body")

    async def _op_human(self, node: dict, frame: Frame, path: tuple) -> None:
        read = self._reader(frame)
        req_id = uuid.uuid4().hex[:12]
        self._pending_human = req_id
        self._human_reply = asyncio.get_running_loop().create_future()
        self.status = VmStatus.WAITING_HUMAN
        prompt = eval_expr(node["prompt"], read) if node.get("prompt") is not None else ""
        image = eval_expr(node["image"], read) if node.get("image") is not None else None
        # context: 传给前端的运行期数据(如手绘门的源 summary_path, 供画布取板参照); 与 image 同为表达式求值
        context = eval_expr(node["context"], read) if node.get("context") is not None else None
        # options: 多选门(kind=choose/sketch)的按钮项 [{value,label}]; 前端渲染为按钮, 回 choice
        payload = {"req_id": req_id, "kind": node.get("kind"), "prompt": prompt,
                   "fields": node.get("fields", []), "image": image,
                   "options": node.get("options", []), "context": context, "aid": aid_of(path)}
        self._pending_human_payload = payload
        self._emit({"type": "vm_human_request", "run_id": self.run_id, **payload,
                    "execution_generation": self.execution_generation, "ts": self._time()})
        self._emit_state()
        try:
            reply = await self._human_reply
        finally:
            self._pending_human = None
            self._human_reply = None
            self._pending_human_payload = None
        self.status = VmStatus.RUNNING
        self._emit({"type": "vm_human_reply", "run_id": self.run_id, "req_id": req_id,
                    "execution_generation": self.execution_generation, "ts": self._time()})
        # 出门也广播状态 (与进门的 _emit_state 对称): 否则答完门后 status 悄悄回 RUNNING 却无任何事件,
        # 前端徽标会一直冻在 WAITING_HUMAN, 直到下一条稀疏 vm_state (子脚本弹栈 / 下一道门 / 终态)。
        # 门后若立刻进长 plc_l2 动作 (如 scrape stall_timeout=300s), 期间徽标就像"卡死在等待人工"。
        self._emit_state()
        if node.get("assign_choice"):
            self._write(frame, node["assign_choice"]["var"], reply.get("choice"))
        for f in node.get("fields", []) or []:
            if f.get("var") in reply.get("values", {}):
                self._write(frame, f["var"], reply["values"][f["var"]])
        if (node.get("kind") == "confirm" and reply.get("choice") == "cancel"
                and node.get("on_cancel", "raise") == "raise"):
            raise VmRaise("HUMAN_CANCELLED", "用户取消")

    async def _op_comment(self, node: dict, frame: Frame, path: tuple) -> None:
        return None

    # ------------------------------------------------------------------
    # 事件发出
    # ------------------------------------------------------------------

    def snapshot_vars(self) -> dict:
        """公开变量快照 (供 VmController/API)."""
        return self._snapshot_vars()

    def active_nodes(self) -> list[dict[str, Any]]:
        """公开活动 call/run_script 节点快照 (供状态 API 与前端重连恢复)."""
        return [dict(item) for item in self._active_nodes]

    @property
    def active_revision(self) -> int:
        """活动节点快照的单调版本号。"""
        return self._active_revision

    def current_script(self) -> str:
        """公开当前帧脚本名 (供 VmController/API)."""
        return self._cur_script()

    @property
    def pending_human_request(self) -> Optional[dict]:
        """挂起的人工请求 payload (无门挂起时 None); 字段与 vm_human_request 事件一致 (供 API 重建弹窗)."""
        return dict(self._pending_human_payload) if self._pending_human_payload else None

    def _cur_script(self) -> str:
        return self.stack[-1].script_name if self.stack else self._root.get("name", "")

    def _snapshot_vars(self) -> dict:
        """合并全局 + 栈顶帧局部为 {名: {value, type, scope}}."""
        out: dict[str, dict] = {}
        for var in self._global.vars.values():
            out[var.name] = {"value": var.value, "type": var.type, "scope": var.scope}
        if self.stack:
            for var in self.stack[-1].locals.vars.values():
                out[var.name] = {"value": var.value, "type": var.type, "scope": var.scope}
        return out

    def _emit_state(self) -> None:
        self._emit({"type": "vm_state", "run_id": self.run_id, "status": self.status.value,
                    "current_aid": self.current_aid, "script": self._cur_script(),
                    "stack_depth": len(self.stack), "active_nodes": self.active_nodes(),
                    "active_revision": self._active_revision,
                    "execution_generation": self.execution_generation,
                    "ts": self._time()})

    def _emit_vars(self) -> None:
        self._emit({"type": "vm_vars", "run_id": self.run_id, "script": self._cur_script(),
                    "execution_generation": self.execution_generation,
                    "vars": self._snapshot_vars(), "ts": self._time()})

    def _node_ref(self, node: dict, path: tuple, *, script: str | None = None) -> dict[str, Any]:
        return {"script": script or self._cur_script(), "aid": aid_of(path),
                "op": node["op"], "action": node.get("action") or node.get("script")}

    def _emit_node_enter(self, node: dict, path: tuple, *, args: dict | None = None,
                         script: str | None = None) -> None:
        ref = self._node_ref(node, path, script=script)
        self._active_nodes.append(ref)
        self._active_revision += 1
        self._emit({"type": "vm_node_enter", "run_id": self.run_id, **ref,
                    "args": dict(args or {}), "active_nodes": self.active_nodes(),
                    "active_revision": self._active_revision,
                    "execution_generation": self.execution_generation, "ts": self._time()})

    def _emit_node_done(self, node: dict, path: tuple, status: str, message: str, result: dict,
                        *, script: str | None = None) -> None:
        # action 与 vm_node_enter 对称携带 (call=动作名, run_script=子脚本名): 前端步骤树完成时据此
        # 保留动作名, 否则只剩 op 会退化成 "call"/"run_script" (审阅: 完成行丢名)。
        ref = self._node_ref(node, path, script=script)
        # 从后向前移除同一实例键：递归/并行出现相同 script+aid 时一次 done 只减一个。
        for i in range(len(self._active_nodes) - 1, -1, -1):
            if self._active_nodes[i] == ref:
                self._active_nodes.pop(i)
                self._active_revision += 1
                break
        self._emit({"type": "vm_node_done", "run_id": self.run_id, **ref,
                    "status": status, "message": message, "result": result,
                    "active_nodes": self.active_nodes(),
                    "active_revision": self._active_revision,
                    "execution_generation": self.execution_generation, "ts": self._time()})
