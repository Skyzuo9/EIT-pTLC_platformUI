"""升降板仓「光电触发位 + Z 行程」板数换算 — 判定单点产地。

原理:
    平台托板运动到顶部板遮住(1Z 上料)或脱离(2Z 下料)光电时停轴, 停轴位置与仓内
    板数一一对应 —— 板越多, 平台停得越低:

        张数 = (z_empty_mm − z_trigger_mm) / pitch_mm

    pitch_mm 必须实测标定, 不能用玻璃名义厚度。TLC 硅胶板一面有硅胶涂层, 真实堆叠
    节距 = 玻璃厚 + 涂层厚 + 贴合间隙, 通常比名义 2.0mm 大 0.2~0.3mm。按名义值换算的
    误差 = 0.125 × 张数, 数到第 8 张即错满一张, 故未标定时本模块拒绝换算。

    误差预算依据 (1Z/2Z, 见 PLC 伺服调用 FB_SERVOAXIS_0/1): JOG 15mm/s + 减速
    1000mm/s² ⇒ 停车距离 0.11mm, 且为系统性偏移, 会被 z_empty_mm 标定一并吸收;
    残余随机项主要是光电触发重复性, 由 residual 暴露。

本模块不做 IO 之外的副作用: 换算与判定全为纯函数, 不读账本、不发事件、不抛控制流
异常 —— evaluate() 恒返回 dict, 由调用方 (runtime/bootstrap.py 的 _feedlift_probe)
按 ok 决定是否报错。文件读写仅 load_calib/save_calib 两个标定常量存取函数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 残差(张)上界: 换算值离最近整数超过此值即判读数不可信。
# 兼作 A11_feed_raise step 30 抖动重捕获的间接探测 —— FeedLift_1Z_RaiseRetryCount
# 未导出到 OPC UA, 上位机无法直接得知是否发生过重捕获, 但重捕获带来的位置偏移会在
# 残差上显形。
RESIDUAL_LIMIT = 0.4

# 实测节距与标定节距的偏离(mm)上界: 超过即提示重新标定 (只提示, 不自动改标定值)。
# 换批次板(涂层厚度不同)会造成系统性偏移, 此项使其不至于静默错下去。
PITCH_DRIFT_LIMIT = 0.15

# 标定文件里每个板仓的必填键 (samples 可缺, 缺即视为空列表 —— 旧版两步标定留下的文件没有它)
_CALIB_KEYS = ("z_empty_mm", "pitch_mm", "warn_threshold")
# 允许写入的键 = 必填键 + 采样记录
_WRITABLE_KEYS = _CALIB_KEYS + ("samples",)

# 各板仓的光电逼近动作: 标定采样与 cycle 内探测**必须用同一个动作**, 否则触发边沿不同,
# 标定基准与运行读数会差一个光电回差。
#   feed  → feed_raise    向上搜索 玻璃升降光电开关1 = TRUE
#   waste → unload_ready  向上搜索 玻璃升降光电开关2 = TRUE
SEARCH_ACTION = {"feed": "feedlift.feed_raise", "waste": "feedlift.unload_ready"}

# 各板仓的光电清零动作: 把光电退成 FALSE, 供随后的逼近动作"从 FALSE 侧走过来"。
#   feed  → feed_clear    向下搜索 玻璃升降光电开关1 = FALSE
#   waste → unload_bury   向下搜索 玻璃升降光电开关2 = FALSE
#
# ⚠ 一次板数测量 = 清零 + 逼近 + 读位, 三步缺一不可, **不存在只发逼近动作的测量**。
# 原因是逼近动作在光电已 TRUE 时是幂等直通 (A11_feed_raise step5: 原地停住确认 300ms 即 DONE,
# 轴一步不动), 连发只会反复读到上次停轴的陈旧位置 —— 2026-07-26 现场就是这么把"装了 5 张板"
# 测成了与空仓一模一样的 498.619。
# 清零同时也是正确的计量做法: 触发点永远从同一侧、同一方向逼近, 传感器回差与机械间隙才是
# 可重复的常量; 逼近位移只有回差那一小段, 正是希望它稳定的那一段。
CLEAR_ACTION = {"feed": "feedlift.feed_clear", "waste": "feedlift.unload_bury"}

# 逼近位移(mm)下界: 清零后逼近至少要走出这么多, 才算真搜索过。正常值就是光电回差
# (0.2~1mm 量级), 此处只用来抓"动作返回 DONE 了但轴一步没动"这一类失效, 故取得很小。
MIN_APPROACH_MM = 0.02

# 实测节距的合理区间(mm): 落在区间外说明装板数记错、板无涂层或堆叠有明显间隙/翘曲,
# 三种情况下绝对法都不可信, 故拒绝写入而不是存下一个坏常数。采样本身仍保留 —— 样本是
# 现场事实, 不该因为拟合不合理就被丢掉。
PITCH_MIN_MM = 1.5
PITCH_MAX_MM = 4.0

# ── FeedLift L2 前置门与错误码的释义 ──────────────────────────────────────────
# PLC 只回一个整数, 上位机不翻译的话现场看到的就是 "error=301" 这么一个字, 而这几个码
# 的差别恰恰决定了该去查什么: 301/302 是**前置条件没满足、轴根本没启动**, 304/305/307
# 才是真搜索到了边界。把它俩混为一谈会让人去查伺服和光电, 而真因在别处。
#
# ⚠ 门原文与错误码文本**不在本文件**: 它们的唯一真源是编排说明书
# mock/behavior/specs/feedlift.yaml (逐字提取自活工程 20260702.project, 带 POU 锚点与
# ST 哈希, 有离线与在线两层漂移看门狗)。翻译入口是 action/plc_error_hints.describe。
# 本文件曾手抄过一份门表与错误码表, 抄一份必漂, 已删。
#
# 下面两条 hint 留在这里, 因为它们的属主是**标定链**: preflight_gate 在自检不通过时
# 要用, 与错误码翻译各用各的。
#
# 各项的物理含义 (2026-07-27 现场目视 + PLC 注释确认):
#   玻璃升降接近开关1/2 = **仓底的有无板检测** (不是位置开关); 空仓必为 FALSE
#   Alarm.0 / Alarm.1   = PLC 注释原文「上料机构无物料」/「下料机构已满料」
# ⇒ 上料侧其实有**三重**有无料检查 (进料传感器 / 接近开关 / Alarm.0), 这是正当的物料互锁。

# 空仓时这些门必然不成立 —— 标定因此**不能采空仓那一组**。但也不需要:
# 空仓基准位 z_empty 是 fit_calib 的**截距**, 由任意 >=2 组不同的非零张数外推得出。
EMPTY_MAGAZINE_HINT = (
    "空仓时仓底接近开关为 FALSE、Alarm 置位, 这几个门必然不成立 —— 标定不要采空仓那一组。"
    "改用不同的已知非零张数各采一组 (如 10/20/30): 空仓基准位是拟合直线的截距, "
    "由这些组外推即可, 不需要真的把仓清空。")

# bHomed 也在门里, 但它不是常见成因, 故降级为"排除掉物料互锁之后再查"。
# PLC 开机自动回零只回 5Z/4X (tools/plc_startup_fix_20260721.mjs:576 "startup request homes
# only incremental 5Z then 4X"; 完成判据 bAutoHome45Done 只看这两个轴), 1Z/2Z 的回零只挂在
# HMI【一键回原点】上, 而那个按钮没有暴露成 OPC 节点, 上位机发不了。
# 注意**轴能手动点动并不代表已回零** (点动绕开 L2 派发器, 也不置 bHomed)。
HOMING_HINT = (
    "若仓内确实有板仍报此码, 再查回零: PLC 开机自动回零只回 5Z/4X, "
    "1Z/2Z 只能在 HMI 上按【一键回原点】。注意轴能手动点动 ≠ 已回零。")

# ── 发动作前的可见前置自检 ────────────────────────────────────────────────────
# 三项前置里只有接近开关是上位机看得见的: bHomed 与 Alarm 都没有暴露成 OPC 节点
# (plc_nodes.yaml 的 FeedLift 段只有 ActPos 与搜索边界)。所以自检**只能证伪不能证真**
# —— 能提前拦下"仓底没板"这一种, 拦不下"没回零", 通过了也不代表动作一定能跑。
# 这个限制必须如实写进返回体, 否则"自检通过"会被当成"动作会成功"。
#
# IX8 位映射见 plc_nodes.yaml:170 —— bit3/4 = 玻璃升降光电开关1/2,
# bit5/6 = 玻璃升降接近开关1/2。两者物理位置与职责不同 (2026-07-27 现场目视):
#   光电开关 (侧面) —— 检测**顶板是否升到取料位**, 这是测量用的那个
#   接近开关 (仓底) —— 检测**仓内有没有板**, 这是物料互锁用的那个
# 二者配合构成 feed_raise 的正当前置: 底部确认有板 + 侧面确认顶板到位。
#
# ⚠ 这里按**裸位=1 即满足**判定, 不做常开/常闭折算: PLC 的 ST 是
# `玻璃升降接近开关1 AT %IX8.5` 直接当 BOOL 用并要求它 TRUE, 我们镜像的是 PLC 自己的
# 判据。物料对账那边按有料/无料语义折算极性是另一回事, 别把这里也一起"修正"了 ——
# 一改就和 PLC 的门对不上。
_IX8_PHOTO_BIT = {"feed": 3, "waste": 4}
_IX8_PROX_BIT = {"feed": 5, "waste": 6}

# 各板仓对应的升降轴号; 多处 `1 if magazine == "feed" else 2` 的单一出处。
MAGAZINE_AXIS = {"feed": 1, "waste": 2}


def preflight_gate(magazine: str, ix8: int, plc_ready: bool | None = None) -> dict:
    """按 IX8 裸字节做发动作前的可见前置自检 (纯函数)。

    参数:
        magazine: 板仓标识 feed | waste
        ix8: PLC 输入字节 IX8 的当前值
        plc_ready: PLC_Ready 现值; None 表示没读到, 不参与判定

    返回:
        Dict {magazine, axis, ix8, ix8_bits, photoelectric, proximity, plc_ready,
              ok, blockers, unobservable, text}
        ok=False 表示**已经能确定**动作会超时; ok=True 只表示看得见的那部分没问题。
    """
    if magazine not in MAGAZINE_AXIS:
        raise ValueError(f"板仓应为 {tuple(MAGAZINE_AXIS)} 之一, 收到 {magazine!r}")
    axis = MAGAZINE_AXIS[magazine]
    raw = int(ix8) & 0xFF
    photo = bool(raw >> _IX8_PHOTO_BIT[magazine] & 1)
    prox = bool(raw >> _IX8_PROX_BIT[magazine] & 1)

    blockers: list[str] = []
    if not prox:
        # 接近开关是仓底的有无板检测, 所以 FALSE 就是"仓是空的" —— 直接这么说, 别让现场
        # 拿着一个位号去猜。同时给出做法: 空仓这一组本来就不该采 (见 EMPTY_MAGAZINE_HINT)。
        blockers.append(
            f"仓底检测不到板 (空仓): 玻璃升降接近开关{axis} = IX8."
            f"{_IX8_PROX_BIT[magazine]} = FALSE。PLC 的清零动作要求仓内有板, "
            f"现在发下去必然 10 秒超时。{EMPTY_MAGAZINE_HINT}")
    if plc_ready is False:
        blockers.append("PLC_Ready = FALSE, PLC 尚未就绪 (总线/使能/自动回零未完成)")

    # 看不见的两项如实点名: 自检通过不等于动作会成功
    alarm_meaning = "上料机构无物料" if magazine == "feed" else "下料机构已满料"
    unobservable = [f"{axis}Z 是否已回零 (bHomed)",
                    f"Alarm.{axis - 1} 是否为 FALSE ({alarm_meaning})"]

    if blockers:
        text = "; ".join(blockers)
    else:
        text = (f"可见前置通过 (仓底接近开关{axis}=有板, 侧面光电{axis}="
                f"{'到位' if photo else '未到位'})。但 {'、'.join(unobservable)} "
                f"上位机读不到 —— 若仍报 301/302, 依次查这两项。{HOMING_HINT}")

    return {
        "magazine": magazine,
        "axis": axis,
        "ix8": raw,
        "ix8_bits": format(raw, "08b"),
        "photoelectric": photo,
        "proximity": prox,
        "plc_ready": plc_ready,
        "ok": not blockers,
        "blockers": blockers,
        "unobservable": unobservable,
        "text": text,
    }


@dataclass(frozen=True)
class MagazineCalib:
    """单个板仓的行程-张数标定常数。

    字段:
        magazine: 板仓标识, feed=上料仓(1Z) | waste=下料仓(2Z)
        z_empty_mm: 空仓时光电触发的轴位置(mm); 由 fit_calib 拟合得出 (是截距, 不是某一次读数)
        pitch_mm: 实测堆叠节距(mm), 同由拟合得出; 0 表示尚未标定
        capacity: 仓容量(张), 取自物料拓扑 (material_topology.yaml), 不在标定文件里重复定义
        warn_threshold: 预警阈值(张); feed 为低料下限, waste 为快满上限
        samples: 标定采样 ((张数, 轴位置mm), ...), 即上面两个值的出处; 空元组表示
            该标定来自旧版两步标定或尚未采样 —— 不能反推出它是怎么来的
    """

    magazine: str
    z_empty_mm: float
    pitch_mm: float
    capacity: int
    warn_threshold: int
    samples: tuple = ()

    @property
    def calibrated(self) -> bool:
        """节距是否已标定 (pitch_mm > 0)."""
        return self.pitch_mm > 0.0


def count_from_pos(z_mm: float, calib: MagazineCalib) -> tuple[int, float]:
    """由光电触发停轴位置反算仓内板数。

    参数:
        z_mm: 光电触发停轴后的轴实际位置(mm)
        calib: 该板仓的标定常数, 须已标定

    返回:
        Tuple[int, float], (四舍五入后的张数, 残差张数)
        残差 = 原始换算值与最近整数之差的绝对值; 接近 0 表示落在整数张位置上,
        接近 0.5 表示测量或标定有问题。不做 [0, capacity] 截断 —— 越界本身是
        需要暴露的异常, 截断会把它藏起来。
    """
    raw = (calib.z_empty_mm - z_mm) / calib.pitch_mm
    count = round(raw)
    return count, abs(raw - count)


def fit_calib(samples) -> dict:
    """由多组 (仓内张数, 光电触发位) 样本最小二乘拟合空仓基准位与堆叠节距。

    模型 z = z_empty − N × pitch 是条直线, 对 k 组样本做一元线性回归:

        b = Σ((Nᵢ−N̄)(zᵢ−z̄)) / Σ((Nᵢ−N̄)²)      pitch = −b
        a = z̄ − b×N̄                              z_empty = a

    两点时退化为 pitch = (z₀ − z_N)/N, 即旧版两步标定的公式, 故单点用法不丢。
    多点的真正增量是**残差**: k≥3 时残差 RMS 就是光电触发重复性的直接实测, 换算成张数
    后即"这套方案在这台机器上到底多准"; 残差异常增大还能暴露堆叠非线性 (被压实/有间隙)。

    参数:
        samples: [(plates, z_mm), ...]; plates 为该次采样时仓内实际张数 (空仓即 0)

    返回:
        Dict {n, ok, z_empty_mm, pitch_mm, residual_rms_mm, residual_rms_plates,
              residuals, reason}
        ok=False 表示定不出直线 (样本 <2 组, 或全部张数相同使分母为 0), 此时前四项为 None。
        **k=2 时 ok=True 但 residual_rms_mm 为 None** —— 两点必然共线, 残差恒为 0, 那个 0
        不代表准, 只代表没有信息; 由 reason 如实说明, 绝不返回一个看着很好的 0。
        residuals 为每组样本的残差(mm), 供向导逐行显示 (k=2 时为全 0)。
    """
    pairs = [(float(n), float(z)) for n, z in samples]
    k = len(pairs)
    if k < 2:
        return _fit_fail(k, f"样本只有 {k} 组, 至少要 2 组 (建议 3 组以上) 才能定出直线")

    mean_n = sum(p[0] for p in pairs) / k
    mean_z = sum(p[1] for p in pairs) / k
    denom = sum((p[0] - mean_n) ** 2 for p in pairs)
    if denom == 0.0:
        return _fit_fail(k, "全部样本的张数相同, 定不出斜率 —— 请在不同装板张数下各采一组")

    b = sum((p[0] - mean_n) * (p[1] - mean_z) for p in pairs) / denom
    a = mean_z - b * mean_n
    # +0.0 归一化负零: 斜率恰为 0 时 -b 得到 -0.0, 直接显示成"节距 -0.0mm"很像是算错了
    residuals = [round(z - (a + b * n), 4) + 0.0 for n, z in pairs]
    pitch = -b + 0.0

    if k == 2:
        rms_mm = None
        rms_plates = None
        reason = "只有 2 组样本: 两点必然共线, 残差恒为 0 并不代表准, 只代表没有信息 —— 再加一组才知道准不准"
    else:
        # k−2 自由度: 拟合消耗了斜率与截距两个参数
        rms_mm = round((sum(r * r for r in residuals) / (k - 2)) ** 0.5, 4)
        rms_plates = round(rms_mm / abs(pitch), 4) if pitch != 0 else None
        reason = ""

    return {
        "n": k,
        "ok": True,
        "z_empty_mm": round(a, 3),
        "pitch_mm": round(pitch, 4),
        "residual_rms_mm": rms_mm,
        "residual_rms_plates": rms_plates,
        "residuals": residuals,
        "reason": reason,
    }


def record_sample(path, magazine: str, capacity: int, plates: int,
                  z_clear: float, z_trigger: float) -> dict:
    """记一组标定样本: 自校验逼近位移 → 追加样本 → 重新拟合 → 按合理性决定是否写常数。

    参数:
        path: 标定文件路径; magazine: 板仓标识; capacity: 仓容量(张)
        plates: 此刻仓内实际张数; z_clear/z_trigger: 同一次测量的清零位与触发位(mm)
    返回:
        Dict {magazine, plates, z_mm, approach_mm, n_samples, fit, reject_reason}
    异常:
        ValueError —— 张数越界, 或逼近位移不足 (读数陈旧, 见下)

    逼近位移必须 > MIN_APPROACH_MM: 逼近动作在光电已 TRUE 时是幂等直通 (原地确认 300ms
    即 DONE, 轴一步不动), 此时读回的是上次停轴的陈旧位置。2026-07-26 现场就是这么把装了
    5 张板测成了与空仓一模一样的 498.619。

    拟合不合理时**保留样本但不写常数**: 样本是现场事实, 坏常数才是要挡住的东西。
    """
    plates = int(plates)
    if plates < 0 or plates > capacity:
        raise ValueError(f"采样张数应在 0~{capacity} 之间, 收到 {plates}")

    approach = round(float(z_trigger) - float(z_clear), 3)
    if approach <= MIN_APPROACH_MM:
        raise ValueError(
            f"逼近动作返回 DONE 但轴几乎没动 (清零位 {float(z_clear):.3f}mm → 触发位 "
            f"{float(z_trigger):.3f}mm, 逼近仅 {approach:.3f}mm): 读数是陈旧值, 已拒绝采用。"
            f"多半是清零动作没把光电退成 FALSE, 请查该动作与光电接线")

    calib = load_calib(path, magazine, capacity)
    z_mm = round(float(z_trigger), 3)
    samples = calib.samples + ((plates, z_mm),)
    fit = fit_calib(samples)
    reject_reason = calib_reject_reason(fit)

    if reject_reason:
        save_calib(path, magazine, samples=samples_to_json(samples))
    else:
        save_calib(path, magazine, samples=samples_to_json(samples),
                   z_empty_mm=fit["z_empty_mm"], pitch_mm=fit["pitch_mm"])

    return {"magazine": magazine, "plates": plates, "z_mm": z_mm,
            "approach_mm": approach, "n_samples": len(samples),
            "fit": fit, "reject_reason": reject_reason}


def calib_reject_reason(fit: dict) -> str:
    """拟合结果是否该被拒绝写入标定常数; 返回中文原因, 空串表示可写入。

    参数:
        fit: fit_calib 的返回

    单一出处: feedlift.calib_record 用它决定落不落盘, 标定路由用它回显原因 —— 两处
    各写一份迟早会漂。被拒时**样本仍照记**, 只是不写常数: 样本是现场事实, 坏常数才是
    要挡住的东西。
    """
    if not fit["ok"]:
        return fit["reason"]
    if not (PITCH_MIN_MM <= fit["pitch_mm"] <= PITCH_MAX_MM):
        return (f"拟合节距 {fit['pitch_mm']}mm 落在合理区间 {PITCH_MIN_MM}~{PITCH_MAX_MM}mm "
                f"之外, 已保留本组采样但未写入标定 —— 请核对各组装板张数是否准确、"
                f"板间是否有明显间隙或翘曲")
    return ""


def _fit_fail(n: int, reason: str) -> dict:
    """构造拟合失败的返回 dict, 键集与成功时一致 (前端不必分支取值)."""
    return {
        "n": n, "ok": False, "z_empty_mm": None, "pitch_mm": None,
        "residual_rms_mm": None, "residual_rms_plates": None,
        "residuals": [], "reason": reason,
    }


def evaluate(z_mm: float, calib: MagazineCalib, *,
             z_prev: float | None = None,
             expect_taken: int | None = None) -> dict:
    """一次板仓探测的完整换算与判定 (纯函数; VM 零算术)。

    参数:
        z_mm: 本次光电触发停轴后的轴实际位置(mm)
        calib: 该板仓的标定常数
        z_prev: 前一次探测的轴位置(mm); 给了才做差分判定, 缺省只做绝对盘点
        expect_taken: 期望的取走张数; 与 z_prev 同时给出才生效

    返回:
        Dict, 键集与编排 YAML `{field: {var: pN}, name: ...}` 取值逐字对齐:
        {z_mm, count, residual, taken, delta_mm, measured_pitch_mm,
         pitch_drift, warn, ok, text}
        taken/delta_mm/measured_pitch_mm 在未做差分时为 None。
        ok=False 表示本次读数不可采信或实取张数不符, 由调用方据此报错停机。
    """
    z_mm = round(float(z_mm), 3)
    if not calib.calibrated:
        return _fail(z_mm, f"{calib.magazine} 板仓节距尚未标定 (pitch_mm=0), "
                           f"请先在物料页完成空仓与满仓两步标定")

    count, residual = count_from_pos(z_mm, calib)
    residual = round(residual, 3)

    taken: int | None = None
    delta_mm: float | None = None
    measured_pitch: float | None = None
    pitch_drift = False
    if z_prev is not None:
        delta_mm = round(z_mm - float(z_prev), 3)
        taken = round(delta_mm / calib.pitch_mm)
        if taken != 0:
            # 实测节距 = 本次行程差 / 实取张数, 用于监测换批次板导致的系统性偏移
            measured_pitch = round(abs(delta_mm / taken), 3)
            pitch_drift = abs(measured_pitch - calib.pitch_mm) > PITCH_DRIFT_LIMIT

    # ── 判定 1: 残差 —— 读数是否落在整数张位置上 ────────────────────────────
    if residual > RESIDUAL_LIMIT:
        return _fail(z_mm, f"{calib.magazine} 板仓读数不可信: 位置 {z_mm}mm 换算 "
                           f"{count} 张但残差达 {residual} 张 (上界 {RESIDUAL_LIMIT}), "
                           f"疑为光电抖动重捕获或标定失准",
                     count=count, residual=residual, taken=taken, delta_mm=delta_mm,
                     measured_pitch_mm=measured_pitch, pitch_drift=pitch_drift)

    # ── 判定 2: 绝对张数是否在物理量程内 ────────────────────────────────────
    if count < 0 or count > calib.capacity:
        return _fail(z_mm, f"{calib.magazine} 板仓换算张数 {count} 超出量程 "
                           f"0~{calib.capacity} 张, 疑为标定失准或机构异常",
                     count=count, residual=residual, taken=taken, delta_mm=delta_mm,
                     measured_pitch_mm=measured_pitch, pitch_drift=pitch_drift)

    # ── 判定 3: 差分 —— 本次实际取走张数是否符合预期 ────────────────────────
    if taken is not None and expect_taken is not None and taken != int(expect_taken):
        return _fail(z_mm, _taken_text(calib, taken, int(expect_taken), delta_mm, count),
                     count=count, residual=residual, taken=taken, delta_mm=delta_mm,
                     measured_pitch_mm=measured_pitch, pitch_drift=pitch_drift)

    warn = _is_warn(count, calib)
    return {
        "z_mm": z_mm,
        "count": count,
        "residual": residual,
        "taken": taken,
        "delta_mm": delta_mm,
        "measured_pitch_mm": measured_pitch,
        "pitch_drift": pitch_drift,
        "warn": warn,
        "ok": True,
        "text": _ok_text(calib, count, residual, taken, warn, pitch_drift, measured_pitch),
    }


def _is_warn(count: int, calib: MagazineCalib) -> bool:
    """余量是否触及预警线: 上料仓看低料下限, 下料仓看快满上限."""
    if calib.magazine == "waste":
        return count >= calib.warn_threshold
    return count <= calib.warn_threshold


def _taken_text(calib: MagazineCalib, taken: int, expect: int,
                delta_mm: float | None, count: int) -> str:
    """差分判定失败的中文诊断语, 按实取张数分三种典型故障措辞."""
    if taken >= 2 and expect == 1:
        cause = f"疑为吸盘一次吸走 {taken} 张 (双张)"
    elif taken == 0 and expect == 1:
        cause = "疑为吸盘空吸, 没有取到板"
    else:
        cause = "实取张数与编排预期不符"
    return (f"{calib.magazine} 板仓实取 {taken} 张, 预期 {expect} 张: {cause}。"
            f"行程差 {delta_mm}mm / 标定节距 {calib.pitch_mm}mm, 仓内余 {count} 张")


def _ok_text(calib: MagazineCalib, count: int, residual: float, taken: int | None,
             warn: bool, pitch_drift: bool, measured_pitch: float | None) -> str:
    """判定通过时的中文回显语, 供事件流与人工门直接引用."""
    parts = [f"{calib.magazine} 板仓余 {count} 张 (残差 {residual} 张)"]
    if taken is not None:
        parts.append(f"本次取走 {taken} 张")
    if warn and calib.magazine == "waste":
        parts.append(f"⚠ 已达快满预警线 {calib.warn_threshold} 张, 请及时清仓")
    elif warn:
        parts.append(f"⚠ 已低于备料预警线 {calib.warn_threshold} 张, 请及时补料")
    if pitch_drift:
        parts.append(f"⚠ 实测节距 {measured_pitch}mm 偏离标定值 {calib.pitch_mm}mm "
                     f"超过 {PITCH_DRIFT_LIMIT}mm, 疑为换批次板, 建议重新标定")
    return " | ".join(parts)


def _fail(z_mm: float, text: str, **extra) -> dict:
    """构造判定失败的返回 dict, 补齐调用方需要的全部键 (缺省 None/False)."""
    result = {
        "z_mm": z_mm, "count": None, "residual": None, "taken": None,
        "delta_mm": None, "measured_pitch_mm": None, "pitch_drift": False,
        "warn": False, "ok": False, "text": text,
    }
    result.update(extra)
    return result


# ──────────────────────────────────────────────────────────────────────────
# 标定常量存取 (唯一落盘家; 探测闭包与标定端点共用, 避免两份读法)
# ──────────────────────────────────────────────────────────────────────────

def load_calib(path: Path, magazine: str, capacity: int) -> MagazineCalib:
    """从标定文件读出某板仓的标定常数。

    参数:
        path: feedlift_calib.json 路径
        magazine: 板仓标识 feed | waste
        capacity: 仓容量(张), 由调用方从物料拓扑 (MaterialStore.magazines) 取, 不在标定文件里重复

    返回:
        MagazineCalib

    文件缺失、板仓缺项或键不全时抛 ValueError, 由调用方转为动作 ERROR。
    """
    raw = _read_all(path)
    section = raw.get(magazine)
    if not isinstance(section, dict):
        raise ValueError(f"标定文件 {path.name} 缺少板仓 {magazine!r} 的配置节")
    missing = [k for k in _CALIB_KEYS if k not in section]
    if missing:
        raise ValueError(f"标定文件 {path.name} 的板仓 {magazine!r} 缺少键: {missing}")
    return MagazineCalib(
        magazine=magazine,
        z_empty_mm=float(section["z_empty_mm"]),
        pitch_mm=float(section["pitch_mm"]),
        capacity=int(capacity),
        warn_threshold=int(section["warn_threshold"]),
        samples=_parse_samples(section.get("samples"), path, magazine),
    )


def _parse_samples(raw, path: Path, magazine: str) -> tuple:
    """把标定文件里的 samples 解析成 ((张数, 位置mm), ...); 缺省视为空。

    samples 缺失 = 旧版两步标定留下的文件, 不是错误; 但格式不对是错误 —— 静默丢弃采样
    会让"这个节距怎么来的"永远查不清, 故宁可抛错。
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"标定文件 {path.name} 的板仓 {magazine!r}: samples 应为数组")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "plates" not in item or "z_mm" not in item:
            raise ValueError(
                f"标定文件 {path.name} 的板仓 {magazine!r}: 第 {i + 1} 组采样应含 plates 与 z_mm")
        out.append((int(item["plates"]), float(item["z_mm"])))
    return tuple(out)


def samples_to_json(samples) -> list:
    """把 ((张数, 位置mm), ...) 转成标定文件里的数组形态 (供 save_calib 落盘)."""
    return [{"plates": int(n), "z_mm": round(float(z), 3)} for n, z in samples]


def save_calib(path: Path, magazine: str, **fields) -> dict:
    """就地更新某板仓的若干标定字段并落盘, 返回该板仓更新后的完整配置节。

    参数:
        path: feedlift_calib.json 路径
        magazine: 板仓标识 feed | waste
        fields: 要覆盖的键值 (z_empty_mm / pitch_mm / warn_threshold / samples)

    返回:
        Dict, 更新后该板仓的配置节

    只改传入的键, 其余保持原值 —— 采样与拟合结果分次写入, 后写的不能冲掉先写的。
    """
    unknown = set(fields) - set(_WRITABLE_KEYS)
    if unknown:
        raise ValueError(f"标定字段名非法: {sorted(unknown)}, 允许 {_WRITABLE_KEYS}")
    raw = _read_all(path)
    section = dict(raw.get(magazine) or {})
    section.update(fields)
    raw[magazine] = section
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return section


def _read_all(path: Path) -> dict:
    """读整个标定文件为 dict; 文件缺失或非法 JSON 抛 ValueError."""
    if not path.exists():
        raise ValueError(f"标定文件不存在: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"标定文件 {path.name} 不是合法 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"标定文件 {path.name} 顶层应为对象, 实际为 {type(raw).__name__}")
    return raw
