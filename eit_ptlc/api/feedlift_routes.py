"""升降板仓行程标定路由
========================
功能:
    注册玻璃板仓「光电触发位 ↔ 板数」的多点标定与实测端点到 FastAPI 应用。
    标定常量与采样记录落在 config/feedlift_calib.json, 由 feedlift.probe_stack 动作读取。

⚠ 本模块的 POST 端点会**驱动 1Z/2Z 升降轴运动** (经编排发对应光电搜索动作), 不是纯读。
    运动本身受 PLC 有界 jog 保护: 只在 SearchLow~SearchHigh 窗口内单向 jog, 前置不满足报
    301/302, 到上界报 304/305。调用前必须确认升降区无人无障碍。

⚠ 两个驱动运动的端点**都走 VM 编排** (config/operation/07_feedlift/feedlift_calib_sample
    与 feedlift_measure_count), 不再直调执行器: 直调不经 VM 就不发 vm_*/operation_* 事件,
    也就不进 RunStore —— 运行历史里一条记录都不留, 现场看不出这几个动作到底执行没执行、
    卡在哪一步。走编排后每一步都可见、可单步、可回放, 返回体里的 run_id 即历史入口。
    端点仍是同步的 (启动后等到终态才返回), 向导那套"点一下 → 出结果"的用法不变。

每次取位都是「自检 → 清零 → 逼近 → 读位」四步: 逼近动作在光电已 TRUE 时是幂等直通,
单发它只会读到上次停轴的陈旧位置。清零动作先把光电退成 FALSE, 逼近才真搜索。

标定流程 (向导逐步引导, 每步一次调用即完成"清零+逼近 → 读轴位 → 记样本 → 重新拟合"):
    1. 装入已知张数 -> POST calib/sample {plates: N}, 建议 3 组以上 (如 10/20/30)
    2. 样本 >=2 组即自动最小二乘拟合出节距与空仓位并落盘

⚠ **不采空仓那一组**: 仓底的玻璃升降接近开关是有无板检测, 空仓时清零动作 (feed_clear /
    unload_bury) 的物料互锁不成立, PLC 必然 10 秒超时报 301/302 —— 那是设计如此的物料
    互锁, 不是故障。也不需要采: 空仓基准位 z_empty 是拟合直线的**截距**, 由不同的非零
    张数外推得出 (见 controller/feedlift_count.py::fit_calib)。

为什么要多点: 两点必然共线, 残差恒为 0 而没有信息; 3 组起残差 RMS 才是光电触发重复性的
直接实测, 换算成张数即"这套方案在这台机器上到底多准", 也能暴露堆叠非线性。

为什么必须实测而不能用玻璃名义厚度: TLC 硅胶板一面有硅胶涂层, 真实堆叠节距 = 玻璃厚 +
涂层厚 + 贴合间隙, 通常比名义 2.0mm 大 0.2~0.3mm; 按名义值换算的误差 = 0.125 x 张数,
数到第 8 张即错满一张。

端点 (前缀 /api):
    GET    /feedlift/calib             读两个板仓的标定现状 + 采样 + 拟合结果
    POST   /feedlift/calib/sample      采一组样本 (发搜索动作 + 读轴位), 自动重拟合
    DELETE /feedlift/calib/samples     清空某仓采样并把标定归零 (重新标定)
    POST   /feedlift/measure           立即实测现在有几张 (发搜索动作 + probe_stack 校正账本)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.controller.feedlift_count import (
    CLEAR_ACTION, SEARCH_ACTION, calib_reject_reason, fit_calib, load_calib,
    samples_to_json, save_calib)
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError

log = logging.getLogger(__name__)

# 两条编排的脚本名 (config/operation/07_feedlift/)
_CALIB_SCRIPT = "feedlift_calib_sample"
_MEASURE_SCRIPT = "feedlift_measure_count"
_WORKSPACE = "default"

# 单次运行的等待上限(秒): 两条编排都是"自检 + 两个有界 jog + 几次读数", 正常十几秒内结束。
# 取 180 是给 PLC 那两个 10 秒前置等待 + 慢速搜索留足余量, 同时不至于让页面无限期挂着。
# 超时只是不再等, **不终止运行** —— 轴可能正在动。
_RUN_TIMEOUT_S = 180.0


def register_feedlift_routes(app: FastAPI) -> None:
    """把升降板仓标定路由注册到应用。"""

    def _calib_path(request: Request):
        path = getattr(request.app.state, "feedlift_calib_path", None)
        if path is None:
            raise HTTPException(503, "板仓标定路径未就绪")
        return path

    def _require_plc(request: Request) -> None:
        """PLC 控制器缺席时直接 503, 不起编排。

        没有 PLC 这条编排必然在第一个读位动作上失败, 起了只是往运行历史里塞一条注定
        失败的运行, 还把"设备没接上"这件事伪装成"流程跑挂了"。
        """
        if getattr(request.app.state, "plc", None) is None:
            raise HTTPException(503, "PLC 控制器未就绪")

    def _magazines(request: Request) -> dict:
        """板仓表 {仓号: (显示名, 容量)}; 真源是 material_topology.yaml, 不在此另立一份."""
        store = getattr(request.app.state, "material_store", None)
        if store is None:
            raise HTTPException(503, "物料账本未就绪")
        return store.magazines

    def _check_magazine(request: Request, magazine: str) -> None:
        mags = _magazines(request)
        if magazine not in mags:
            raise HTTPException(400, f"板仓应为 {tuple(mags)} 之一, 收到 {magazine!r}")

    def _vm(request: Request):
        vm = getattr(request.app.state, "vm", None)
        if vm is None:
            raise HTTPException(503, "VM 控制器未就绪")
        return vm

    def _script(request: Request, name: str) -> dict:
        repo = getattr(request.app.state, "script_repo", None)
        if repo is None:
            raise HTTPException(503, "脚本仓库未就绪")
        try:
            return repo.get(_WORKSPACE, name)
        except KeyError:
            raise HTTPException(503, f"编排脚本缺失: {name}") from None

    def _run_message(request: Request, run_id: str) -> str:
        """从运行历史取该次运行的终态消息 (VM 的 _state 不带 message)."""
        store = getattr(request.app.state, "run_store", None)
        if store is None:
            return ""
        run = store.get_run(run_id)
        return (run or {}).get("message") or ""

    async def _run_script(request: Request, name: str, inputs: dict) -> tuple[str, dict]:
        """跑一条编排到终态, 返回 (run_id, 变量快照 {名: 值}); 非 DONE 转 422。

        走 VM 而不是直调执行器, 是为了让这几步动作**留得下痕迹**: 只有经 VM 才会发
        vm_*/operation_* 事件、进 RunStore, 现场才看得出到底执行没执行、卡在第几步,
        事后也才能回放。错误码释义已在执行器并进动作 message (action/plc_error_hints.py),
        故此处照原样透出即可, 不需要再翻一遍。

        端点保持同步 (等到终态才返回), 向导那套"点一下 → 出结果"的用法不变。
        """
        vm = _vm(request)
        doc = _script(request, name)
        try:
            started = await vm.start(doc, inputs)
        except MaintenanceActiveError as exc:
            raise HTTPException(409, str(exc)) from exc
        run_id = started["run_id"]
        try:
            state = await vm.wait_final(run_id, timeout=_RUN_TIMEOUT_S)
        except asyncio.TimeoutError:
            # 不掐运行: 轴可能正在动, 掐掉只会留下一个说不清的中间态。交由前端按 run_id 跟。
            raise HTTPException(
                504, f"{name} 超过 {_RUN_TIMEOUT_S:.0f} 秒仍未结束 (run_id={run_id}); "
                     f"运行未被终止, 请在运行历史或实时监视器里跟进") from None
        if state["status"] != "DONE":
            detail = _run_message(request, run_id) or f"{name} 未完成"
            raise HTTPException(422, f"{detail} (run_id={run_id})")
        # 根帧全程不出栈, 故终态时局部变量仍在, assign 的动作结果可直接取用
        snapshot = vm.vars(run_id)["vars"]
        return run_id, {k: v["value"] for k, v in snapshot.items()}

    def _state(request: Request, magazine: str) -> dict:
        """某板仓的完整标定状态 (常量 + 采样 + 当前拟合), 供 GET 与两个写端点共用返回体."""
        label, capacity = _magazines(request)[magazine]
        try:
            calib = load_calib(_calib_path(request), magazine, capacity)
        except ValueError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {
            "magazine": magazine,
            "label": label,
            "z_empty_mm": calib.z_empty_mm,
            "pitch_mm": calib.pitch_mm,
            "capacity": calib.capacity,
            "warn_threshold": calib.warn_threshold,
            "calibrated": calib.calibrated,
            # 一次测量实际发的两个动作, 供向导的确认弹窗如实点名 (清零在前, 逼近在后)
            "clear_action": CLEAR_ACTION[magazine],
            "search_action": SEARCH_ACTION[magazine],
            "samples": samples_to_json(calib.samples),
            "fit": fit_calib(calib.samples),
        }

    @app.get("/api/feedlift/calib")
    async def get_feedlift_calib(request: Request):
        """读两个板仓的标定现状 (供物料页玻璃板子页的标定向导渲染)."""
        return {m: _state(request, m) for m in _magazines(request)}

    @app.post("/api/feedlift/calib/sample")
    async def post_feedlift_calib_sample(request: Request):
        """采一组标定样本: 跑 feedlift_calib_sample 编排 (自检→清零→逼近→记样本)。

        请求体: {magazine: "feed"|"waste", plates: N}  (N 为此刻仓内实际张数, 空仓填 0)
        前置: 仓内确为 N 张, 升降区无人无障碍 —— 本端点会驱动轴运动。

        采样、拟合与落盘全在编排的 feedlift.calib_record 动作里 (runtime/bootstrap.py),
        本端点只负责校参数、起编排、等终态、回读现状 —— 不复制一份拟合逻辑。
        拟合结果不过合理性检查时**保留样本但不写 pitch_mm**: 样本是现场事实, 坏常数才是
        要挡住的东西。返回体的 fit.reason / reject_reason 说明原因。
        """
        body = await request.json()
        magazine = str(body.get("magazine") or "")
        _check_magazine(request, magazine)
        _require_plc(request)
        _, capacity = _magazines(request)[magazine]
        try:
            plates = int(body.get("plates"))
        except (TypeError, ValueError):
            raise HTTPException(400, f"plates 应为整数, 收到 {body.get('plates')!r}") from None
        if plates < 0 or plates > capacity:
            raise HTTPException(400, f"采样张数应在 0~{capacity} 之间, 收到 {plates}")
        if plates == 0:
            # 空仓组必然失败, 不起编排 —— 起了只是往运行历史塞一条注定超时的运行 (同 _require_plc)。
            # 仓底接近开关是有无板检测, 空仓时清零动作的物料互锁不成立。而这一组本来就不必采。
            raise HTTPException(
                400,
                "空仓这一组采不了: 仓底接近开关检测不到板, PLC 的清零动作会因物料互锁 "
                "10 秒超时 (301/302)。也不需要采 —— 空仓基准位是拟合直线的截距, "
                "由不同的已知非零张数 (如 10/20/30) 外推得出")

        run_id, vars_ = await _run_script(request, _CALIB_SCRIPT,
                                          {"magazine": magazine, "plates": plates})
        # 标定现状回读落盘文件而不是从 VM 变量里捞: 文件才是 probe_stack 后续要读的那份
        state = _state(request, magazine)
        sample = vars_.get("sample") or {}
        return {**state, "run_id": run_id,
                "sampled": {"plates": sample.get("plates", plates),
                            "z_mm": sample.get("z_mm")},
                "reject_reason": sample.get("reject_reason")
                                 or calib_reject_reason(state["fit"])}

    @app.delete("/api/feedlift/calib/samples")
    async def delete_feedlift_calib_samples(request: Request, magazine: str):
        """清空某板仓的采样并把标定归零 (重新标定); 不驱动任何运动."""
        _check_magazine(request, magazine)
        save_calib(_calib_path(request), magazine, samples=[], z_empty_mm=0.0, pitch_mm=0.0)
        log.info("[升降板仓] %s 采样与标定已清空", _magazines(request)[magazine][0])
        return _state(request, magazine)

    @app.post("/api/feedlift/measure")
    async def post_feedlift_measure(request: Request):
        """立即实测某板仓现在有几张: 跑 feedlift_measure_count 编排 (自检→清零→逼近→盘点)。

        请求体: {magazine: "feed"|"waste"}
        前置: 该仓已完成标定; 升降区无人无障碍 —— 本端点会驱动轴运动。

        判定与落账**完全复用 probe_stack 动作**, 不在此复制 evaluate/对账逻辑 —— 走的是与
        两个 feedlift cycle 逐字相同的代码路径, 故按钮实测的数与跑流程时校正账本的数不会漂移。
        取位的清零+逼近由编排负责, probe_stack 只负责换算与对账, 不动轴。
        """
        body = await request.json()
        magazine = str(body.get("magazine") or "")
        _check_magazine(request, magazine)
        _require_plc(request)
        run_id, vars_ = await _run_script(request, _MEASURE_SCRIPT, {"magazine": magazine})
        # 返回体即 probe_stack 的 evaluate 结果 (count/residual/warn/text), 与改造前逐字
        # 同形 —— 前端读的是同一批键
        return {**(vars_.get("probe") or {}), "run_id": run_id}
