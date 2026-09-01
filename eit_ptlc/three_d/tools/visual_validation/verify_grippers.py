# 功能: 夹爪三态的前端运行时端到端验收(方向/行程/持料/短柱随动全部以浏览器内真值断言).
# 用法: C:\ProgramData\miniforge3\python.exe grip_e2e.py
# 前提: PTLC 上位机在 http://localhost:18080, 部署的 device-manifest.json 已是新值.
#
# ⚠ 本验收打的是**实时链的载荷无关兜底层**(spec.holdValue): vial 的 hold 期望 44.97mm
#   对应 holdValue 0.101。精编译片段的取件闭合 2026-08-07 起已逐件化(瓶颈 0.2543 /
#   粉桶摇篮同心 0.817, 见 clip_compiler._close_value_for), 不经本档路径 —— 期望值
#   保持不变是有意的, 别按逐件值来"修"这里。
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:18080/3d/live"
OUT = r"E:\eit_lab\pTLC_platformUI\eit_ptlc\three_d\work\previews"

# 组间距期望(mm): 由导出 GLB 父空间平移与行程推导
EXPECT = {
    "vial": {"pair": ("ACTUATOR_GRIP_VIAL_L", "ACTUATOR_GRIP_VIAL_R"),
             "open": 47.50, "closed": 22.50, "hold": 44.97},
    "plate": {"pair": ("ACTUATOR_GRIP_PLATE96_L", "ACTUATOR_GRIP_PLATE96_R"),
              "open": 59.30, "closed": 48.90, "hold": 56.31},
}
TOL = 0.6  # mm

JS_MEASURE = """
() => {
  const scene = window.__ptlcTwin.manager.scene
  const wanted = ['ACTUATOR_GRIP_VIAL_L', 'ACTUATOR_GRIP_VIAL_R',
                  'ACTUATOR_GRIP_PLATE96_L', 'ACTUATOR_GRIP_PLATE96_R']
  const pos = {}
  const pins = {}
  scene.traverse((obj) => {
    if (wanted.includes(obj.name)) {
      obj.updateWorldMatrix(true, false)
      const e = obj.matrixWorld.elements
      pos[obj.name] = [e[12], e[13], e[14]]
    }
    if (obj.name && obj.name.includes('短柱')) {
      obj.updateWorldMatrix(true, false)
      const e = obj.matrixWorld.elements
      pins[obj.name] = { x: e[12] * 1000, group: obj.parent?.name || '?' }
    }
  })
  const states = window.__ptlcTwin.feed.sampleMechanismStates()
  return { pos, pins, holding: {
    plate: states.rob_grip_plate96?.holding ?? null,
    vial: states.rob_grip_vial?.holding ?? null,
  } }
}
"""

seq = 300


def evaluate(page, js, arg=None):
    return page.evaluate(js, arg) if arg is not None else page.evaluate(js)


def inject_mech(page, commanded):
    global seq
    seq += 1
    page.evaluate(
        """([commanded, seq]) => {
      window.__ptlcTwin.feed.handleEvent({ type: 'mechanism_state', ts: Date.now() / 1000, seq,
        states: { rob_grip_vial: { commanded }, rob_grip_plate96: { commanded } } })
    }""",
        [commanded, seq],
    )


def tool_and_close(page, tool, script):
    page.evaluate(
        """([tool, script]) => {
      const feed = window.__ptlcTwin.feed
      feed.handleEvent({ type: 'telemetry', node: 'robot', health: 'ok',
        data: { tool_state: { mounted_tool: tool } } })
      feed.handleEvent({ type: 'vm_node_done', op: 'call', action: 'robot.tool_action',
        status: 'DONE', script, args: { action: 'gripper-close' } })
    }""",
        [tool, script],
    )


def tool_and_open(page, tool):
    page.evaluate(
        """(tool) => {
      const feed = window.__ptlcTwin.feed
      feed.handleEvent({ type: 'telemetry', node: 'robot', health: 'ok',
        data: { tool_state: { mounted_tool: tool } } })
      feed.handleEvent({ type: 'vm_node_done', op: 'call', action: 'robot.tool_action',
        status: 'DONE', script: 'robot_group_staging_put', args: { action: 'gripper-open' } })
    }""",
        tool,
    )


def measure(page):
    m = evaluate(page, JS_MEASURE)
    out = {"holding": m["holding"], "pins": m["pins"]}
    for key, spec in EXPECT.items():
        a, b = spec["pair"]
        pa, pb = m["pos"].get(a), m["pos"].get(b)
        if pa and pb:
            out[key] = round(sum((pa[i] - pb[i]) ** 2 for i in range(3)) ** 0.5 * 1000, 2)
    return out


def check(tag, got, expect_key, results):
    ok_all = True
    for key, spec in EXPECT.items():
        want = spec[expect_key]
        actual = got.get(key)
        ok = actual is not None and abs(actual - want) <= TOL
        ok_all = ok_all and ok
        results.append(f"{'PASS' if ok else 'FAIL'} {tag}/{key}: {actual}mm (期望 {want}±{TOL})")
    return ok_all


def main():
    results = []
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        # 隔离真实事件流: 注入的状态不能被后端快照覆盖
        page.route("**/api/**", lambda route: route.abort())
        page.goto(BASE, timeout=60000)
        page.wait_for_function(
            "() => window.__ptlcTwin && window.__ptlcTwin.manager && window.__ptlcTwin.manager.scene",
            timeout=150000,
        )
        page.wait_for_timeout(3000)

        # -- 张开(信号 0) --------------------------------------------------
        inject_mech(page, False)
        page.wait_for_timeout(2000)
        m_open = measure(page)
        ok &= check("张开", m_open, "open", results)
        pins_open = {k: v["x"] for k, v in m_open["pins"].items()}

        # -- 空爪紧闭(信号 1, 无持料) --------------------------------------
        inject_mech(page, True)
        page.wait_for_timeout(2000)
        m_closed = measure(page)
        ok &= check("空爪紧闭", m_closed, "closed", results)

        # 短柱随动: 每根销钉按其所属组 ±12.5mm(用户报的 bug: 臂动销不动)
        expected_pin = {"ACTUATOR_GRIP_VIAL_L": 12.5, "ACTUATOR_GRIP_VIAL_R": -12.5}
        for name, info in sorted(m_closed["pins"].items()):
            want = expected_pin.get(info["group"])
            if want is None:
                results.append(f"FAIL 短柱 {name} 不在运动组内(父={info['group']})")
                ok = False
                continue
            moved = info["x"] - pins_open.get(name, float("nan"))
            pin_ok = abs(moved - want) <= 0.5
            ok &= pin_ok
            results.append(
                f"{'PASS' if pin_ok else 'FAIL'} 短柱随动 {name}@{info['group']}: {moved:+.2f}mm (期望 {want:+.1f})")

        # -- 持料闭合(pick 包络) -------------------------------------------
        tool_and_close(page, 2, "robot_group_rack_pick")
        tool_and_close(page, 3, "robot_individual_pick")
        page.wait_for_timeout(300)
        flags = evaluate(page, JS_MEASURE)["holding"]
        if flags != {"plate": True, "vial": True}:
            results.append(f"FAIL 持料标志未置位: {flags}")
            ok = False
        page.wait_for_timeout(2000)
        m_hold = measure(page)
        ok &= check("持料闭合", m_hold, "hold", results)

        # -- 松开包络后回满闭合 --------------------------------------------
        tool_and_open(page, 3)
        tool_and_open(page, 2)
        page.wait_for_timeout(2000)
        m_rel = measure(page)
        ok &= check("释放后紧闭", m_rel, "closed", results)

        try:
            page.screenshot(path=f"{OUT}\\e2e_grip_final.png", timeout=20000)
        except Exception:
            pass
        browser.close()

    print("\n".join(results))
    slim = {k: {kk: vv for kk, vv in v.items() if kk != "pins"} if isinstance(v, dict) else v
            for k, v in {"open": m_open, "closed": m_closed, "hold": m_hold, "released": m_rel}.items()}
    print(json.dumps(slim, ensure_ascii=False))
    sys.exit(0 if ok else 1)


main()
