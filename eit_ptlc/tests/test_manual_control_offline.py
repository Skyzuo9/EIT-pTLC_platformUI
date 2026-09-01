"""单点控制 (PC Manual Mode) 端到端离线测试 (HTTP)
====================================================
功能:
    在 sim (Mock PLC + 单点容器树 + PLC_PCManual FSM) 下经 HTTP 验证:
    会话门控与前置检查、气缸电平二态与到位反馈联动、轴点动的三层防卡死、
    与 L2 动作的双向互斥、看门狗清扫、一键回原点。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_manual_control_offline
"""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(f"{name} {detail}".strip())
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def _set_mode(client, mode: str) -> None:
    r = client.post("/api/mode", json={"control_mode": mode})
    assert r.status_code == 200, f"切换模式失败: HTTP {r.status_code} {r.text[:120]}"


def _state(client, station: str | None = None) -> dict:
    q = f"?station={station}" if station else ""
    return client.get(f"/api/manual/state{q}").json()


def _wait(fn, tries: int = 60, delay: float = 0.05):
    """轮询到 fn() 为真 (或用尽); 返回最后一次取值."""
    value = None
    for _ in range(tries):
        value = fn()
        if value:
            return value
        time.sleep(delay)
    return value


def _enter(client) -> dict:
    return client.post("/api/manual/session/enter")


def main() -> int:
    app = create_sim_app()
    with TestClient(app) as client:
        # ── 点表回显 (不限模式, 纯内存) ──
        points = client.get("/api/manual/points").json()
        total_c = sum(len(v["cylinders"]) for v in points["stations"].values())
        total_a = sum(len(v["axes"]) for v in points["stations"].values())
        check("点表-51缸11轴", total_c == 51 and total_a == 11, f"cyl={total_c} axes={total_a}")
        check("点表-8工位", len(points["all_stations"]) == 8, str(points["all_stations"]))

        # ── RUN 模式禁止进入 ──
        _set_mode(client, "RUN")
        r = _enter(client)
        check("RUN 模式拒绝进入", r.status_code == 403, f"HTTP {r.status_code}")

        # ── DEBUG 模式可进入, PLC 回 Active ──
        _set_mode(client, "DEBUG")
        r = _enter(client)
        check("DEBUG 模式进入", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        st = _state(client)
        check("PLC 回 Active", st.get("active") is True, f"reject={st.get('reject_text')}")

        # ── 气缸: 电平二态 + 到位反馈联动 ──
        r = client.post("/api/manual/cylinder/dev_t1_cyl1", json={"on": True})
        check("气缸开-下发", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        got = _wait(lambda: _state(client, "develop")["cylinders"]["dev_t1_cyl1"].get("fb_on"))
        check("气缸开-动点反馈", got is True, f"fb_on={got}")
        cyl = _state(client, "develop")["cylinders"]["dev_t1_cyl1"]
        # 电子手动档下只写手动位: 自动位是 L2 流程与泵管理的地盘, 碰了会打架 + HMI 显示乱
        check("气缸开-只写手动位不碰自动位",
              cyl.get("manual") is True and cyl.get("auto") is False, str(cyl))
        # 单点生效即切电子手动档 (A00 里 xAutoMode := 手自动 AND NOT PC_Manual_Active)
        check("单点生效即切手动档", _state(client)["globals"].get("manual_auto") is False,
              str(_state(client)["globals"].get("manual_auto")))

        client.post("/api/manual/cylinder/dev_t1_cyl1", json={"on": False})
        got = _wait(lambda: _state(client, "develop")["cylinders"]["dev_t1_cyl1"].get("fb_off"))
        check("气缸关-原点反馈", got is True, f"fb_off={got}")

        # ── 单点会话期间 PLC L2 动作被拒 (双向互斥之一) ──
        r = client.post("/api/actions/develop.fill/run", json={"params": {"tank": 1}, "mode": "DEBUG"})
        body = r.json() if r.status_code == 200 else {}
        check("会话中 L2 动作被拒",
              body.get("status") == "REJECTED" and body.get("reject_code") == "RESOURCE_CONFLICT",
              f"HTTP {r.status_code} status={body.get('status')} code={body.get('reject_code')}")

        # ── 机器人动作不受单点互斥影响 (只拦 PLC 类) ──
        r = client.post("/api/actions/robot.stop/run", json={"params": {}, "mode": "DEBUG"})
        body = r.json() if r.status_code == 200 else {}
        check("会话中机器人动作放行", body.get("reject_code") != "RESOURCE_CONFLICT",
              f"status={body.get('status')} code={body.get('reject_code')}")

        # ── 轴点动: 续订则持续, 不续订则后端看门狗松开 ──
        p0 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        r = client.post("/api/manual/axis/axis_8y/jog/start", json={"direction": "pos"})
        check("点动-下发", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        for _ in range(4):
            time.sleep(0.2)
            client.post("/api/manual/axis/axis_8y/jog/keep")
        p1 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        check("点动-续订期间位移", p1 > p0 + 0.5, f"{p0} -> {p1}")

        client.post("/api/manual/axis/axis_8y/jog/stop")
        time.sleep(0.3)
        p2 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        time.sleep(0.3)
        p3 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        check("点动-松开即停", abs(p3 - p2) < 1e-6, f"{p2} -> {p3}")

        # 不续订: 后端 jog deadline (0.8s) 到点强制松开
        client.post("/api/manual/axis/axis_8y/jog/start", json={"direction": "pos"})
        time.sleep(1.4)
        p4 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        time.sleep(0.4)
        p5 = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        check("点动-不续订自动松开", abs(p5 - p4) < 1e-6, f"{p4} -> {p5}")
        jog_bits = _state(client, "photoscrape")["axes"]["axis_8y"]
        check("点动-命令位已清", jog_bits.get("xJogPos") is False, str(jog_bits.get("xJogPos")))

        # ── 绝对定位: 到位后命令位自动收口 ──
        r = client.post("/api/manual/axis/axis_8y/move",
                        json={"mode": "abs", "target": 12.0, "vel": 40.0})
        check("定位-下发", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        got = _wait(lambda: abs(_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"] - 12.0) < 0.01,
                    tries=80, delay=0.1)
        check("定位-到达目标", bool(got),
              f'fActPos={_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]}')

        # 速度限幅: vel 超过点表 vel_max 时被夹到 vel_max (8Y 的 vel_max=50)
        r = client.post("/api/manual/axis/axis_8y/move",
                        json={"mode": "abs", "target": 12.0, "vel": 9999.0})
        check("定位-速度限幅", r.status_code == 200 and r.json().get("vel") == 50.0,
              f"vel={r.json().get('vel')}")

        # ── 单轴回零: 绝不预清 bHomed ──
        # bHomed 是 PLC `A00_设备状态显示及控制` 里 `伺服未回原点报警` 的唯一输入, 而那是
        # **置位锁存** (只有柜面 复位/bSysReset/bAutoHomeResetPulse 能清)。预清一次 = 每回
        # 一次零就在 HMI 留一条要人工复位的报警, 还把整机推进 FB_Mode 的故障态。
        # 终态判据靠 PLC 自清 xHome (`IF 回零完成nX THEN xHome := FALSE; bHomed := TRUE`)。
        # 先撤掉上一步的绝对定位: 命令位还挂着的话, 回零归零后会被它当场拉回目标位
        # (真 PLC 同理 —— 同一个 FB_SERVOAXIS 上两条运动命令抢一根轴, 见 home_all 的 docstring)
        client.post("/api/manual/axis/axis_8y/stop")
        time.sleep(0.5)  # axis_stop 的 xStop 脉冲宽 0.3s, 等它落下
        pos_before = _state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]
        check("单轴回零-起始不在零位", abs(pos_before) > 0.01, f"fActPos={pos_before}")

        svc = app.state.manual
        driver = svc._driver
        home_writes: list[str] = []
        orig_write_ext = driver.write_ext

        async def _spy_write_ext(path, value, var_type):
            home_writes.append(str(path[-1]))
            return await orig_write_ext(path, value, var_type)

        driver.write_ext = _spy_write_ext
        try:
            r = client.post("/api/manual/axis/axis_8y/home")
            check("单轴回零-下发", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        finally:
            driver.write_ext = orig_write_ext
        check("单轴回零-只写 xHome", home_writes == ["xHome"], str(home_writes))
        check("单轴回零-未预清 bHomed", "bHomed" not in home_writes, str(home_writes))
        got = _wait(lambda: abs(_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]) < 0.01,
                    tries=60, delay=0.1)
        check("单轴回零-轴归零", bool(got),
              f'fActPos={_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]}')
        check("单轴回零-bHomed 全程为真",
              _state(client, "photoscrape")["axes"]["axis_8y"].get("bHomed") is True)

        # ── 一键回原点: 须 confirm ──
        r = client.post("/api/manual/home_all", json={})
        check("一键回原点-缺 confirm 拒绝", r.status_code == 422, f"HTTP {r.status_code}")
        r = client.post("/api/manual/home_all", json={"confirm": True})
        check("一键回原点-下发", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        got = _wait(lambda: abs(_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]) < 0.01,
                    tries=60, delay=0.1)
        check("一键回原点-轴归零", bool(got),
              f'fActPos={_state(client, "photoscrape")["axes"]["axis_8y"]["fActPos"]}')

        # ── 退出: 清扫全部命令位, 且可重入 ──
        client.post("/api/manual/cylinder/dev_t1_cyl1", json={"on": True})
        time.sleep(0.2)
        r = client.post("/api/manual/session/exit")
        check("退出-成功", r.status_code == 200, f"HTTP {r.status_code}")
        # PC_Manual_Active 由 PLC 侧算出, 撤 Enable 后要等一个扫描周期才落下
        _wait(lambda: _state(client, "develop").get("active") is False)
        st = _state(client, "develop")
        check("退出-会话已关", st.get("active") is False and st.get("enabled") is False,
              f"active={st.get('active')} enabled={st.get('enabled')}")
        cyl = st["cylinders"]["dev_t1_cyl1"]
        check("退出-手动位已清扫", cyl.get("manual") is False, str(cyl))
        check("退出-档位交还自动", st["globals"].get("manual_auto") is True,
              str(st["globals"].get("manual_auto")))
        check("退出-幂等", client.post("/api/manual/session/exit").status_code == 200)

        # 退出后 L2 动作恢复放行 (互斥解除)
        r = client.post("/api/actions/develop.fill/run", json={"params": {"tank": 1}, "mode": "DEBUG"})
        body = r.json() if r.status_code == 200 else {}
        check("退出后 L2 动作放行", body.get("reject_code") != "RESOURCE_CONFLICT",
              f"status={body.get('status')} code={body.get('reject_code')}")

        # ── 会话未激活时写类端点被拒 ──
        r = client.post("/api/manual/cylinder/dev_t1_cyl1", json={"on": True})
        check("无会话时下发被拒", r.status_code == 409, f"HTTP {r.status_code}")

        # ── 未知 id → 404 ──
        check("重新进入", _enter(client).status_code == 200)
        r = client.post("/api/manual/cylinder/nope", json={"on": True})
        check("未知执行器 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = client.post("/api/manual/axis/nope/jog/start", json={"direction": "pos"})
        check("未知轴 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = client.post("/api/manual/axis/axis_8y/jog/start", json={"direction": "sideways"})
        check("非法方向 422", r.status_code == 422, f"HTTP {r.status_code}")
        client.post("/api/manual/session/exit")

        # ── 停发心跳 -> 会话自动退出 -> 电子档位交还 ──
        # 这是"用户从面板导航走了"的后端契约: 前端一旦不再续 TTL, 后端必须自己收口,
        # 否则 PC_Manual_Active 恒真 => 整机卡在电子手动档 => 产线再也启动不了。
        check("重新进入(心跳超时前)", _enter(client).status_code == 200)
        client.post("/api/manual/cylinder/dev_t1_cyl1", json={"on": True})
        time.sleep(5.0)   # 会话 TTL 3.5s; 期间不发 keepalive 也不拉 state (state 也会续期)
        st = _state(client, "develop")
        check("停发心跳-会话自动退出", st.get("enabled") is False and st.get("active") is False,
              f"enabled={st.get('enabled')} active={st.get('active')}")
        check("停发心跳-手动位已清", st["cylinders"]["dev_t1_cyl1"].get("manual") is False,
              str(st["cylinders"]["dev_t1_cyl1"]))
        check("停发心跳-档位交还自动", st["globals"].get("manual_auto") is True,
              str(st["globals"].get("manual_auto")))

        # ── 设备状态机启停 (脉冲 PLCStop/PLCStart, 与柜面按钮并联) ──
        # 单点模式要求 MODE_State<>运行; 这两个端点让操作工不必跑去柜子按停止/启动。
        client.post("/api/manual/session/exit")
        r = client.post("/api/manual/machine/resume", json={})
        check("恢复运行-缺 confirm 拒绝", r.status_code == 422, f"HTTP {r.status_code}")
        r = client.post("/api/manual/machine/resume", json={"confirm": True})
        check("恢复运行-进运行态", r.status_code == 200 and r.json().get("mode_state") == 1,
              f"HTTP {r.status_code} {r.text[:120]}")
        # 电子手动档的关键收益: 运行态下也能直接进单点, 不必先停机
        r = _enter(client)
        check("运行态也能进入单点", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        check("运行态进入后仍是手动档", _state(client)["globals"].get("manual_auto") is False,
              str(_state(client)["globals"].get("manual_auto")))
        client.post("/api/manual/session/exit")

        r = client.post("/api/manual/machine/stop", json={"confirm": True})
        check("停机-回停止态", r.status_code == 200 and r.json().get("mode_state") != 1,
              f"HTTP {r.status_code} {r.text[:120]}")
        check("停机后可进入单点", _enter(client).status_code == 200)
        r = client.post("/api/manual/machine/stop", json={"confirm": True})
        check("会话中拒绝再停机", r.status_code == 409, f"HTTP {r.status_code}")
        client.post("/api/manual/session/exit")
        r = client.post("/api/manual/machine/stop", json={"confirm": True})
        check("已停止时停机幂等", r.status_code == 200 and r.json().get("changed") is False,
              f"{r.text[:100]}")

        # ── 维护门 (PLC 全下载) 与单点会话互斥 ──
        gate = app.state.maintenance_gate
        lease = gate.try_acquire("离线测试: 模拟 PLC 全下载")
        check("维护门可抢占 (无活动会话)", lease is not None)
        r = _enter(client)
        check("维护态拒绝进入单点", r.status_code == 409, f"HTTP {r.status_code}")
        gate.release(lease)
        check("释放维护门后可进入", _enter(client).status_code == 200)
        # 反向: 会话激活时维护门抢不到 (部署会被挡住)
        check("会话激活时维护门抢占失败",
              gate.try_acquire("离线测试: 会话中不应放行") is None)
        client.post("/api/manual/session/exit")

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项:")
        for item in FAIL:
            print("  -", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
