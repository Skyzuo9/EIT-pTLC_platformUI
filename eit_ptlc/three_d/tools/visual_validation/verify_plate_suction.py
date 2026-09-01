"""
功能: 薄层板持板与料仓下扎的自动化验收 —— 用户 2026-08-05 报的两个穿模现象。

核心断言链(把"看起来穿模"翻译成机器可验证的表述):
  1. 吸气后板必须挂在 ACTUATOR_FLIP_SUCTION 之下(纯换父, 翻转由构造跟随);
  2. **板心 = 唇口 + 半板厚 − 当帧压缩量** —— 这是"吸盘扎穿板面"的判据。
     容差 0.1mm。⚠ 2026-08-05 起判的是这条**一致性**而不是"板心恒在唇口外 1.5mm":
     吸盘是波纹的会压缩, 按刚性判会在任何 >1mm 的压缩上假红;
  2b. 板心**横向**偏移必须等于前端自报的面内修正(plates().seatHold.offsetMm)。
     ⚠ 2026-08-06 起不再断言"横向恒为 0": 面内是软轴, 板还坐在落点里时位置归落点,
     见 PlateStage._seatHold。判一致性而不是判零, 与第 2 条同一理由;
  3. 压缩量必须落在 [0, strokeM] 内 —— 超出的部分该露成缝, 不该被悄悄吸收;
  4. 料仓下扎: 把 1Z/2Z 拖到 range_mm 下限, 板底不得低于实测地板
     (前端按 manifest 的 axes[].geometryMinMm 夹, 见 MachineStateDriver.setAxisMm)。
另截关键姿态图供目检。

用法: python verify_plate_suction.py [--headless]
返回值: 退出码 0/1(结果写 work/verify_plate_suction.json, 截图写 work/previews/review/)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from scipy.spatial.transform import Rotation as R

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))
MODELS_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "models"))
SHOT_DIR = os.path.join(WORK_DIR, "previews", "review")

#: 片段里那块板的 id(编译器固定用 plate, 见 clip_compiler.PLATE_CLIP_ID)
PLATE_ID = "plate"
SUCTION_NODE = "ACTUATOR_FLIP_SUCTION"
CUPS = ("SAB22-KQ2E06-1", "SAB22-KQ2E06-2")

#: 板心与"唇口 + 压缩量"的允许偏差(mm)。
#:
#: ⚠ 2026-08-05 改判据: 此前这里断言 `|板心沿轴 − 半板厚| ≤ 1mm`, 那是按**刚性**唇口写的。
#: 吸盘是波纹的, 顶到硬表面时会压缩(见 plateContact.js), 板心自然会比唇口多出一个压缩量,
#: 于是任何 >1mm 的压缩都会把这条门禁打红 —— 画面对了门禁却挂, 是最坏的一种假红。
#: 现在判的是**一致性**: 板心偏移必须正好等于半板厚 + 当帧压缩量。0.1mm 远严于原来的 1mm。
CONTACT_TOL_MM = 0.1


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="薄层板持板/料仓下扎验收")
    # 演示页按流程名自动装载(单片段那条路要点 UI 选动作, 不适合无人值守)。
    # sampling_load = 料仓取板 → 点样座, 正好走一遍"吸盘吸板"。
    # ⚠ 开发钩子 window.__anim 只存在于 **dev 构建**, 所以默认打 15173 而不是 18080。
    # develop_load = 把板放进展缸, 是唯一会真发生柔性接触的流程(实测板坐在
    # PTLC-02-013 填充块上压 0.84mm)。sampling_load 全程悬空, 验不到柔性那条路径。
    parser.add_argument("--url", default="http://localhost:15173/3d/demo/develop_load")
    parser.add_argument("--expect-compression", action="store_true",
                        help="要求本流程里出现过非零压缩。⚠ 2026-08-05 补上持板压缩标定后, "
                             "板本来就该干净落座、穿透≈0, 于是 develop_load 上再加这个开关"
                             "等于在要求一个缺陷; 柔性通路的回归护栏已移交前端单测"
                             "(tests/three-d/plateContact.test.js 的持板压缩三例)")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    manifest = json.loads(
        open(os.path.join(MODELS_DIR, "device-manifest.official-cr5.json"),
             encoding="utf-8").read())
    grip = next(a for a in manifest["actuators"] if a["id"] == "rob_flip_suction")["plateGrip"]
    axes = {a["id"]: a for a in manifest["axes"]}

    result: dict = {"url": args.url, "console_errors": [], "grip": grip}
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console",
                lambda m: result["console_errors"].append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(str(e)))

        log(f"打开 {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        # 就绪信号取开发钩子本身 + 片段真装上了 —— 各页的加载遮罩类名不一样, 靠它不通用
        page.wait_for_function("() => !!window.__anim", timeout=240_000)
        page.wait_for_function(
            "() => (window.__anim.state()?.duration || 0) > 0", timeout=240_000)
        page.wait_for_timeout(2000)

        def ev(expression: str, arg=None):
            page.wait_for_function("() => !!window.__anim", timeout=60_000)
            return page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)

        state = ev("window.__anim.state()")
        result["initial"] = state
        log(f"装载片段: {state}")

        def seek(t: float) -> None:
            ev(f"window.__anim.seek({t})")
            page.wait_for_timeout(300)

        def plate_local(plate_id: str):
            # 板是运行期造的, 不在节点索引里 —— 只能走板层自己的钩子
            return ev("id => window.__anim.plateLocal(id)", plate_id)

        # -- 1: 吸气后板挂在翻转节点下 -------------------------------------
        # 扫出"板在手上"的那一刻: 流程长度各不相同, 写死时刻改片段就漂。
        # **优先取有压缩的那一刻** —— 零压缩的帧验不到柔性接触这条新路径, 而柔性一旦
        # 悄悄失效, 表现就是放板时板重新扎进展缸(正是 2026-08-05 用户报的那个现象)。
        duration = float(state.get("duration") or 0)
        carried_at = None
        best_compression = -1.0
        step = max(duration / 120.0, 0.1)
        t = 0.0
        while t <= duration:
            seek(t)
            status = ev("window.__anim.plates()") or {}
            if any(row.get("slot") == "carried" for row in status.get("rows") or []):
                compression = float((status.get("contact") or {}).get("compressionM") or 0)
                if carried_at is None or compression > best_compression:
                    carried_at, best_compression = t, compression
                if compression > 0:
                    break
            t += step
        if carried_at is not None:
            seek(carried_at)
        result["maxCompressionM"] = max(best_compression, 0.0)
        result["carriedAt"] = carried_at
        if carried_at is None:
            failures.append("整段流程里没有出现'板在手上'的时刻 —— 吸附事件没生效")
            log("未找到持板时刻")
        else:
            log(f"持板时刻 t={carried_at:.2f}s / 全长 {duration:.2f}s")
        page.screenshot(path=os.path.join(SHOT_DIR, "plate_carried.png"))

        local = plate_local(PLATE_ID)
        result["plateLocal"] = local
        if local is None:
            failures.append(f"持板时刻取不到板 {PLATE_ID} 的局部位姿 —— 板没被画出来")
        elif local.get("parent") != SUCTION_NODE:
            failures.append(
                f"板的父节点是 {local.get('parent')!r}, 不是 {SUCTION_NODE} —— 吸附没生效"
            )

        # -- 2/3: 贴合面是否正落在吸盘唇口上 --------------------------------
        # 在**翻转节点局部系**里判: 那里 plateGrip 是刀具常量, 与机械臂姿态无关。
        # 板的局部位姿应当就是 suctionMountLocal 算出来的那个 —— 一次把"用没用刀具常量"
        # 与"算得对不对"一起验了。
        if local and local.get("parent") == SUCTION_NODE:
            import math
            axis = grip["axisLocal"]
            contact = grip["contactLocalM"]
            position = local["position"]
            strokeMm = float(grip.get("strokeM") or 0) * 1000.0
            state = (ev("window.__anim.plates()") or {}).get("contact") or {}
            penetration = float(state.get("penetrationM") or 0) * 1000.0
            compression = float(state.get("compressionM") or 0) * 1000.0
            overshoot = float(state.get("overshootM") or 0) * 1000.0

            # 板心 = **工作唇口** + 半板厚 − **整个穿透量**。
            # ⚠ 减的是穿透而不是压缩: 板永远停在硬表面上(这是"不许扎进展缸"的全部意义),
            # 而吸盘只让到行程上限为止 —— 两者的差(overshoot)正是那道该露出来的缝。
            # 写成"减压缩"会在超行程时差一个 overshoot(2026-08-05 本判据首版就是这么假红的)。
            #
            # ⚠ 工作唇口 = contactLocalM − carryCompressionM · axis, **不是** contactLocalM。
            #   CAD 里杯子是自由态, 真机抽真空后波纹已压瘪, 板骑的是压缩后的唇口
            #   (见 plateGeometry.suctionMountLocal 与 rig_map 的 carry_compression_mm)。
            #   照自由唇口判会读出 −16.32 这种数并假红 —— 本判据 2026-08-05 就这么红过一次。
            carry = float(grip.get("carryCompressionM") or 0) * 1000.0
            contact = [contact[i] - axis[i] * carry / 1000.0 for i in range(3)]
            along = sum((position[i] - contact[i]) * axis[i] for i in range(3)) * 1000.0
            expected = 1.5 - penetration
            lateral = math.dist(
                [position[i] - axis[i] * along / 1000.0 for i in range(3)], contact) * 1000.0
            result["plateVsContact"] = {
                "alongAxisMm": round(along, 3), "expectedMm": round(expected, 3),
                "lateralMm": round(lateral, 3), "compressionMm": round(compression, 3),
                "overshootMm": round(overshoot, 3), "hit": state.get("hit", ""),
            }
            log(f"板心相对吸盘接触面: 沿轴 {along:+.3f}mm(应为 {expected:+.3f}) / 横向 "
                f"{lateral:.3f}mm / 穿透 {penetration:.3f} = 压缩 {compression:.3f} + 露缝 "
                f"{overshoot:.3f}mm" + (f" / 顶在 {state.get('hit')}" if state.get("hit") else ""))
            if abs(along - expected) > CONTACT_TOL_MM:
                failures.append(
                    f"板心沿吸盘轴 {along:.2f}mm, 与'半板厚 1.5 − 穿透 {penetration:.2f}'"
                    f"对不上 —— 板没有停在硬表面上(刚性时的表现是吸盘扎穿板面, "
                    "现在的表现则是板扎进展缸/座面)"
                )
            # 横向(面内)判据 2026-08-06 改口径: 板**并不**总是正对吸盘对中心。
            #
            # 光板上两只杯落在哪由示教决定, 面内没有任何几何特征定位它, 实测各站偏 4~21mm。
            # 前端 PlateStage._seatHold 因此在"板还坐在落点里"时把面内位置交还给落点
            # (否则吸气那一帧板会横着跳 15mm 扎进料仓 —— 用户 2026-08-06 报的就是它)。
            # 于是这里判的是**一致性**: 横向偏移必须正好等于前端自报的那笔面内修正,
            # 没有落点咬着时才回到"必须正对"(seat_hold 为空 => expected_lateral = 0)。
            #
            # ⚠ 别改回"横向恒 ≤0.1mm": 那条会在每一次取放板的最后一小段假红,
            #   而它假红的恰恰是**修好之后**的画面。
            seat_hold = (ev("window.__anim.plates()") or {}).get("seatHold") or {}
            expected_lateral = float(seat_hold.get("offsetMm") or 0.0)
            result["plateVsContact"]["expectedLateralMm"] = round(expected_lateral, 3)
            result["plateVsContact"]["seatHold"] = seat_hold or None
            if abs(lateral - expected_lateral) > CONTACT_TOL_MM:
                where = (f"落点 {seat_hold.get('slot')} 权重 {seat_hold.get('weight'):.3f}"
                         if seat_hold else "当前没有落点咬着板")
                failures.append(
                    f"板心横向 {lateral:.2f}mm, 与前端自报的面内修正 {expected_lateral:.2f}mm "
                    f"对不上({where}) —— 要么 _seatHold 没生效, 要么板真的没正对吸盘"
                )
            if compression < -1e-6 or compression > strokeMm + 1e-6:
                failures.append(
                    f"压缩量 {compression:.2f}mm 越出行程 [0, {strokeMm:.1f}]mm —— 压缩封顶失效"
                )
            if abs(penetration - compression - overshoot) > 1e-3:
                failures.append(
                    f"穿透 {penetration:.3f} ≠ 压缩 {compression:.3f} + 露缝 {overshoot:.3f} —— "
                    "三者本该恒等, 对不上说明有一段被谁悄悄吸收了"
                )

        result["cupWorld"] = {name: ev("n => window.__anim.nodeWorld(n)", name) for name in CUPS}

        # -- 3b: 杯唇画在哪(2026-08-06 补上的盲区) --------------------------
        #
        # 为什么必须单列一条: 上面那节只验**板**贴不贴接触面, 从不看**杯子**画在哪。
        # 2026-08-05 shipped manifest 里 mountOffsetParent 符号写反(+28.571mm, 应为
        # −17.5mm), 两只吸盘杯从板面里穿出 33mm —— 而本脚本当时全绿。
        #
        # 它还是唯一能发现"算法修好了但 manifest 没重生成"的判据:
        #   管线自检看的是**现役代码**, 前端单测看的是**夹具**, 只有这里读的是
        #   **上线那份 manifest + 真实渲染**。那次正是陈旧型, 前两道都拦不住。
        #
        # 量法(不依赖 mountOffsetParent 本身, 否则等于拿错值验错值):
        #   先扫一帧"手上没板"的(杯必为自由长)拿到 baseScale, 再在持板帧按
        #   s = scale/baseScale 推唇口 = 原点 + 自由长/2 × s, 与"接触面 − 总压缩"对比。
        # 自由长基准取全程**最大**缩放, 而不是"随便找一帧手上没板的就读"。
        # 理由: 板落座后板层未必每帧都再跑一次接触求解, 杯子可能仍停在上一次的压缩态 ——
        # 实测同一时刻两次运行读到 0.0175 与 0.00859 两种值。压缩只会让杯子变短,
        # 所以全程最大值必是自由长, 与"哪一帧被求解过"无关。
        rubbers = grip.get("rubbers") or []
        base_scale = {}
        saw_free_frame = False
        t = 0.0
        while t <= duration:
            seek(t)
            status = ev("window.__anim.plates()") or {}
            if not any(row.get("slot") == "carried" for row in status.get("rows") or []):
                saw_free_frame = True
            for spec in rubbers:
                node = ev("n => window.__anim.nodeLocal(n)", spec["node"])
                if not node:
                    continue
                value = float(node["scale"][int(spec.get("scaleAxis") or 0)])
                base_scale[spec["node"]] = max(base_scale.get(spec["node"], 0.0), value)
            t += max(duration / 40.0, 0.25)

        if carried_at is not None and saw_free_frame and base_scale:
            seek(carried_at)
            state = (ev("window.__anim.plates()") or {}).get("contact") or {}
            total_mm = (float(grip.get("carryCompressionM") or 0)
                        + float(state.get("compressionM") or 0)) * 1000.0
            flip = ev("n => window.__anim.nodeWorldPose(n)", SUCTION_NODE)
            axis = np.asarray(grip["axisLocal"], dtype=float)
            contact_along = float(np.dot(np.asarray(grip["contactLocalM"], dtype=float), axis)) * 1000.0
            rotation = R.from_quat(flip["quaternion"]).as_matrix()
            origin = np.asarray(flip["position"], dtype=float)
            lips = {}
            for spec in rubbers:
                node = ev("n => window.__anim.nodeLocal(n)", spec["node"])
                pose = ev("n => window.__anim.nodeWorldPose(n)", spec["node"])
                base = base_scale.get(spec["node"])
                if not node or not pose or not base:
                    continue
                ratio = float(node["scale"][int(spec.get("scaleAxis") or 0)]) / base
                local = rotation.T @ (np.asarray(pose["position"], dtype=float) - origin)
                lip = float(np.dot(local, axis)) * 1000.0 + (spec["freeLenM"] * 1000.0 / 2.0) * ratio
                lips[spec["node"].rsplit("/", 1)[-1][:28]] = round(lip, 3)
                expect_lip = contact_along - total_mm
                log(f"杯唇 {spec['node'].split('/')[-2]:18} 沿轴 {lip:+8.3f}mm"
                    f"(应为接触面 {contact_along:+.2f} − 总压缩 {total_mm:.2f} = {expect_lip:+.3f})")
                if abs(lip - expect_lip) > CONTACT_TOL_MM:
                    failures.append(
                        f"杯唇沿吸盘轴 {lip:.2f}mm, 应为 {expect_lip:.2f}mm —— 杯子没画在压缩后的"
                        f"位置上(差 {lip - expect_lip:+.2f}mm)。正号=杯子往外跑, 会从板面里穿出来; "
                        "先查 manifest 的 plateGrip.rubbers[].mountOffsetParent 是不是陈旧值"
                    )
            result["cupLipMm"] = lips
            result["cupLipExpectMm"] = round(contact_along - total_mm, 3)
        else:
            log("跳过杯唇判据: 本流程没有同时出现'持板'与'手上没板'两种帧, 取不到自由长基准")
        if args.expect_compression and best_compression <= 0:
            failures.append(
                "整段流程里压缩量始终为 0 —— 柔性接触没生效(开关关了? 碰撞集空了? "
                "manifest 缺 plateGrip.rubbers?)。⚠ 但先排除另一种可能: 2026-08-05 补上 "
                "carry_compression_mm 标定之后, 板本来就干净落座(各站沿轴残差 ≤2.9mm), "
                "穿透≈0 故压缩≈0 —— 那是**修好了**而不是坏了。真要验柔性通路请看前端单测 "
                "tests/three-d/plateContact.test.js 的持板压缩三例"
            )

        # -- 4: 料仓下扎 ---------------------------------------------------
        floors = {}
        for axis_id in ("axis_1z", "axis_2z"):
            spec = axes.get(axis_id) or {}
            low = float((spec.get("rangeMm") or [0, 0])[0])
            ev(f"window.__anim.setAxis('{axis_id}', {low})")
            page.wait_for_timeout(120)
            applied = ev(f"window.__anim.axisValue('{axis_id}')")
            floors[axis_id] = {
                "requestedMm": low,
                "appliedMm": applied,
                "geometryMinMm": spec.get("geometryMinMm"),
            }
            expected = spec.get("geometryMinMm")
            if expected is not None and abs(float(applied) - float(expected)) > 0.01:
                failures.append(
                    f"{axis_id} 请求 {low}mm, 实际停在 {applied}mm, "
                    f"应被几何下界 {expected}mm 夹住 —— 板会扎穿仓底"
                )
        result["magazineFloor"] = floors
        page.screenshot(path=os.path.join(SHOT_DIR, "magazine_bottom.png"))

        browser.close()

    result["failures"] = failures
    with open(os.path.join(WORK_DIR, "verify_plate_suction.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    print()
    for line in failures:
        print(f"    {line}")
    if failures:
        print(f"[!] 薄层板持板/下扎验收未通过({len(failures)} 项)")
        return 1
    print("[ok] 板贴在吸盘上, 且料仓轴被几何下界夹住")
    return 0


if __name__ == "__main__":
    sys.exit(main())
