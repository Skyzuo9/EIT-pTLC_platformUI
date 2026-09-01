"""单点控制点表加载器离线测试
==============================
功能:
    校验 load_manual_points 对真实 manual_points.yaml 的解析结果 (工位归组/反馈配对/
    互锁备注), 以及各类畸形配置能被明确拒绝而不是带病上线。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_manual_points_config_offline
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

from eit_ptlc.config.loader import load_manual_points

_REPO = Path(__file__).resolve().parents[2]
_REAL = _REPO / "eit_ptlc" / "config" / "manual_points.yaml"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(f"{name} {detail}".strip())
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def _load_variant(mutate) -> tuple[bool, str]:
    """把真实点表读出来改一处再加载; 返回 (是否抛错, 错误信息)."""
    raw = yaml.safe_load(_REAL.read_text(encoding="utf-8"))
    mutate(raw)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manual_points.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        try:
            load_manual_points(path)
        except (ValueError, KeyError) as exc:
            return True, str(exc)
    return False, ""


def main() -> int:
    m = load_manual_points(_REAL)

    check("真实点表-51缸11轴", len(m.cylinders) == 51 and len(m.axes) == 11,
          f"cyl={len(m.cylinders)} axes={len(m.axes)}")
    check("真实点表-8工位", len(m.stations) == 8, str(m.stations))

    # 防漂移: 工位键必须等于设备节点 id 去 plc. 前缀 (node_registry 用 station.lower()),
    # 否则 /nodes/plc.<station> 取不到点表, 面板会静默不显示 —— 这是最难查的一类错。
    from eit_ptlc.runtime.bootstrap import _ALL_L2_STATIONS
    expected = {s.lower() for s in _ALL_L2_STATIONS}
    check("工位键与设备节点 id 对齐", set(m.stations) == expected,
          f"点表={sorted(set(m.stations))} 节点={sorted(expected)}")
    check("容器齐全", set(m.containers) >= {"cylinder", "servo", "gvl", "io", "hmi", "pcmanual"},
          str(sorted(m.containers)))
    check("握手三件套", all(m.host.get(k) for k in ("enable", "keepalive", "active")), str(m.host))

    # 工位归组: 展开 32 (8 缸 + 24 阀), 上样 5 根轴
    check("develop 32 个执行器", len(m.station_cylinders("develop")) == 32,
          str(len(m.station_cylinders("develop"))))
    check("sampling 5 根轴", len(m.station_axes("sampling")) == 5,
          str([a.id for a in m.station_axes("sampling")]))

    # 有到位传感器的执行器: 8 展缸缸 + 收集 4 + 刮板 3 = 15 (电池阀类 PLC 未接)
    with_fb = [c.id for c in m.cylinders.values() if c.fb_on or c.fb_off]
    check("15 个执行器有到位反馈", len(with_fb) == 15, f"{len(with_fb)}")

    # 报警位: PLC 只给 15 个执行器接了 bAlarm, 位号须两两不同且在 0..14
    bits = [c.alarm_bit for c in m.cylinders.values() if c.alarm_bit >= 0]
    check("报警位唯一且在 0..14", len(bits) == len(set(bits)) and max(bits) <= 14,
          f"n={len(bits)} max={max(bits)}")

    # 互锁备注必须留在点表里 (面板要原样展示给操作工)
    check("旋转气缸互锁备注", "9X" in m.cylinders["ps_rotate"].note,
          m.cylinders["ps_rotate"].note[:40])

    # 轴: jog 速度是 PLC 硬编码值 (只读显示), 定位限速必须为正
    check("轴限速均为正", all(a.vel_max > 0 for a in m.axes.values()))
    check("4X 点动速度 5.0", m.axes["axis_4x"].jog_vel_fixed == 5.0,
          str(m.axes["axis_4x"].jog_vel_fixed))

    # ── 畸形配置必须被拒 ──
    def dup_id(raw):
        raw["stations"]["collect"]["cylinders"][0]["id"] = "dev_t1_cyl1"
    raised, msg = _load_variant(dup_id)
    check("拒绝-id 重复", raised, msg[:60])

    def bad_station(raw):
        raw["stations"]["nonexistent_station"] = {"cylinders": []}
    raised, msg = _load_variant(bad_station)
    check("拒绝-未知工位", raised, msg[:60])

    def bad_container(raw):
        raw["stations"]["develop"]["cylinders"][0]["manual"]["container"] = "nope"
    raised, msg = _load_variant(bad_container)
    check("拒绝-未声明容器", raised, msg[:60])

    def bad_type(raw):
        raw["stations"]["develop"]["cylinders"][0]["manual"]["type"] = "Bool"
    raised, msg = _load_variant(bad_type)
    check("拒绝-非法类型名", raised, msg[:60])

    def no_manual(raw):
        raw["stations"]["develop"]["cylinders"][0].pop("manual")
    raised, msg = _load_variant(no_manual)
    check("拒绝-缺手动位", raised, msg[:60])

    def bad_vel(raw):
        raw["stations"]["rail"]["axes"][0]["vel_max"] = 0
    raised, msg = _load_variant(bad_vel)
    check("拒绝-限速非正", raised, msg[:60])

    def bad_host(raw):
        raw["host"]["container"] = "nope"
    raised, msg = _load_variant(bad_host)
    check("拒绝-握手容器未声明", raised, msg[:60])

    # ── GBK BrowseName 还原 (真机 OPC UA 的中文标识符) ──
    # 汇川/CODESYS 服务器按 PLC 本地代码页(GBK)编码标识符, asyncua 按 UTF-8+surrogateescape
    # 解码 -> 中文碎成孤立代理字符。下面的输入是 2026-07-28 连真机 192.168.0.50 实测抓到的
    # 原样字符串, 不是构造的。mock 发的是正规 UTF-8, 覆盖不到这条路径, 故在此单测。
    from eit_ptlc.driver.opcua_driver import _recover_browse_name

    real = "\udcb4\udcf3\udcd5\udce6\udcbfձ\udcc3\udccaֶ\udcaf"
    check("GBK 还原-真机实测串", _recover_browse_name(real) == "大真空泵手动",
          repr(_recover_browse_name(real)))
    # 逐字用 GBK 编码合成的其余点表名字也应还原 (覆盖反馈位/轴结构体这类名字)
    for want in ("展缸1气缸1手动", "刮板拍照遮光气缸上位", "拍照轴8YDATE", "一键回原点"):
        broken = want.encode("gbk").decode("utf-8", "surrogateescape")
        ok = _recover_browse_name(broken) == want
        check(f"GBK 还原-{want}", ok, repr(_recover_browse_name(broken)) if not ok else "")
    # 不该被误伤: 纯 ASCII 与服务器本就发正规 UTF-8 的中文
    check("GBK 还原-ASCII 原样", _recover_browse_name("cyinderAlarm") == "cyinderAlarm")
    check("GBK 还原-正规UTF8中文原样", _recover_browse_name("展缸1气缸1手动") == "展缸1气缸1手动")

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项:")
        for item in FAIL:
            print("  -", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
