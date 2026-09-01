#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真空泵重构 + 系统健壮性: Now.xml 确定性文本变换 (读 stage1 -> 写 Now.xml).

功能:
    在已含 Pump_L2 通道/PLC_Pump_泵管理 聚合 POU 的快照 Now.xml.stage1 基础上, 施加剩余
    PLC 改动: 删上样原子内零散真空泵开关, 拆 A21_rinse 为 注液+抽吸 (新增 A26_rinse_suction),
    A20_pipeline 去 slot[10] (整动作由上位机括泵), 修 collect 双触发 + %MW300 typo,
    给 5 个派发器加 RUNNING 中 RESET, 给易挂死原子加传感器超时. 每步断言定位唯一, 可重复执行.

用法:
    python _refactor_pump.py        # 读 Now.xml.stage1 -> 写 Now.xml
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "Now.xml.stage1"
DST = HERE / "Now.xml"

text = SRC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 定位辅助: 按 <action name=...> / <pou name=...> 切出对象体块, 限定替换范围
# ---------------------------------------------------------------------------
def _slice(text: str, open_tag: str, name: str) -> tuple[int, int]:
    """返回名为 name 的 action/pou 元素 [start, end) 区间 (含开闭标签)."""
    marker = f'<{open_tag} name="{name}"'  # pou 带 pouType 属性, 故不含闭合 >
    i = text.index(marker)
    j = text.index(f"</{open_tag}>", i) + len(f"</{open_tag}>")
    return i, j


def edit_block(text: str, open_tag: str, name: str, fn) -> str:
    """对名为 name 的对象体块应用 fn(block)->block', 其余不动."""
    i, j = _slice(text, open_tag, name)
    block = text[i:j]
    new_block = fn(block)
    if new_block == block:
        raise AssertionError(f"{open_tag} {name}: 变换未产生改动 (可能已应用或匹配失败)")
    return text[:i] + new_block + text[j:]


def drop_lines(block: str, pattern: str, count: int) -> str:
    """删除块内匹配 pattern 的整行 (含行首空白与换行), 断言命中条数."""
    rx = re.compile(rf"[ \t]*{pattern}[^\n]*\n")
    hits = rx.findall(block)
    assert len(hits) == count, f"删除行 {pattern!r}: 期望 {count} 命中 {len(hits)}"
    return rx.sub("", block)


def replace_once(block: str, old: str, new: str) -> str:
    assert block.count(old) == 1, f"replace_once: {old!r} 命中 {block.count(old)} (需 1)"
    return block.replace(old, new)


# ---------------------------------------------------------------------------
# 1. 删上样原子内零散真空泵开关 (改由上位机 Pump_L2 括泵)
# ---------------------------------------------------------------------------
# A20_clean_清洗 (live): 删 slot[11]:=TRUE (清洗起) 与 step60 的 slot[11]:=FALSE
text = edit_block(text, "action", "A20_clean_清洗",
                  lambda b: drop_lines(b, r"大真空泵站位\[11\]:=", 2))
# A50_absorb_吸收液体 (live): 删 slot[11]:=FALSE (吸液收尾)
text = edit_block(text, "action", "A50_absorb_吸收液体",
                  lambda b: drop_lines(b, r"大真空泵站位\[11\]:=FALSE;", 1))

# ---------------------------------------------------------------------------
# 2. A20_pipeline_清洗管路: 真空与冲洗并发于整动作 -> 不拆, 仅去 slot[10], 由上位机括泵
# ---------------------------------------------------------------------------
text = edit_block(text, "action", "A20_pipeline_清洗管路",
                  lambda b: drop_lines(b, r"大真空泵站位\[10\]:=", 2))

# ---------------------------------------------------------------------------
# 3. A21_rinse_润洗展缸: 拆为 注液 (本动作, step0-20) + 抽吸 (新 A26_rinse_suction)
#    注液收尾改为直接完成; 删除原 step30/40 (抽吸段移入新动作, 不含 slot[9])
# ---------------------------------------------------------------------------
def _rinse_to_fill(b: str) -> str:
    # step20: 不再进 step30, 直接完成 (阀保持开, 由后续抽吸动作处理)
    b = replace_once(
        b,
        "\t\t\t转发转存:='';    \n\t\t\t%MW1300:=128;\n\t\t\t润洗展缸STEP:=30;\n",
        "\t\t\t转发转存:='';\n\t\t\t%MW1300:=128;\n\t\t\tExpand_Group_clean_OK:=TRUE; bActionDone:=TRUE;\n\t\t\t润洗展缸STEP:=0;\n",
    )
    # 删 step30..step40 (从 step30 标签到最外层 END_CASE 前; 贪婪到最后一个 END_CASE)
    b2 = re.sub(r"\n[ \t]*30:[ \t]*\n.*\nEND_CASE", "\nEND_CASE", b, flags=re.S)
    assert b2 != b and "大真空泵站位[9]" not in b2, "A21_rinse 抽吸段删除失败"
    return b2

text = edit_block(text, "action", "A21_rinse_润洗展缸", _rinse_to_fill)


# 生成抽吸动作 ST 体 (按 group1/2 x number1..4 展开, 与原 step30/40 一致, 去 slot[9])
def _gen_suction_body() -> str:
    def grp(n):  # 缸前缀
        return "展缸1" if n == 1 else "展缸2"
    # step0 (原30): 等沉淀 TON_2 + 废液传感器 TON[10] -> 关进液阀, 开吹气阀
    close_inlet = []
    for g in (1, 2):
        inner = []
        for num in (1, 2, 3, 4):
            inner.append(
                f"\t\t\t\t\t\t\t{num}:\n"
                f"\t\t\t\t\t\t\t\t{grp(g)}进液电池阀{num}自动:=FALSE;\n"
                f"\t\t\t\t\t\t\t\t{grp(g)}吹气电池阀{num}自动:=TRUE;\n"
                f"\t\t\t\t\t\t\t\t润洗展缸STEP:=10;\n"
            )
        close_inlet.append(f"\t\t\t\t\t{g}:\n\t\t\t\t\t\tCASE Expand_Number OF\n" + "".join(inner) + "\t\t\t\t\t\tEND_CASE\n")
    # step10 (原40): 等吹气 TON[4] -> 关排液阀, 关吹气阀, 完成
    close_all = []
    for g in (1, 2):
        inner = []
        for num in (1, 2, 3, 4):
            inner.append(
                f"\t\t\t\t\t{num}:\n"
                f"\t\t\t\t\t\t{grp(g)}排液电池阀{num}自动:=FALSE;\n"
                f"\t\t\t\t\t\t{grp(g)}吹气电池阀{num}自动:=FALSE;\n"
                f"\t\t\t\t\t\tExpand_Group_clean_OK:=TRUE; bActionDone:=TRUE;\n"
                f"\t\t\t\t\t\t润洗展缸STEP:=0;\n"
            )
        close_all.append(f"\t\t\t\t{g}:\n\t\t\t\t\tCASE Expand_Number OF\n" + "".join(inner) + "\t\t\t\t\tEND_CASE\n")
    body = (
        "(* 润洗展缸-抽吸: 真空由上位机 Pump_L2 提供 (本动作前置 vacuum_on).\n"
        "   等废液抽净 -&gt; 关进液阀/开吹气阀 -&gt; 吹气定时 -&gt; 关阀完成. 阀状态承接 A21_rinse 注液. *)\n"
        "TON[10](IN:=(Expand_Group=1 AND  展缸1溶剂废液检测传感器) OR (Expand_Group=2 AND  展缸2溶剂废液检测传感器),PT:=T#10S);\n"
        "TON_2(IN:=润洗展缸STEP=0, PT:=T#3S);\n"
        "TON[4](IN:=润洗展缸STEP=10,PT:=T#30S);\n"
        "TON[7](IN:=润洗展缸STEP=0, PT:=T#60S);   (* 抽吸超时看门狗 *)\n"
        "CASE 润洗展缸STEP OF\n"
        "\t0:\n"
        "\t\tIF TON_2.Q THEN\n"
        "\t\t\tIF TON[10].Q THEN\n"
        "\t\t\t\tCASE Expand_Group OF\n"
        + "".join(close_inlet) +
        "\t\t\t\tEND_CASE\n"
        "\t\t\tELSIF TON[7].Q THEN\n"
        "\t\t\t\tDevelop_L2_ErrorCode:=402;   (* 抽吸超时: 废液未抽净 *)\n"
        "\t\t\t\t润洗展缸STEP:=0;\n"
        "\t\t\t\tbActionError:=TRUE;\n"
        "\t\t\tEND_IF\n"
        "\t\tEND_IF\n"
        "\t10:\n"
        "\t\tIF TON[4].Q THEN\n"
        "\t\t\tCASE Expand_Group OF\n"
        + "".join(close_all) +
        "\t\t\tEND_CASE\n"
        "\t\tEND_IF\n"
        "END_CASE\n"
    )
    return body


SUCTION_GUID = "d3f177f9-10e0-57a1-ba1a-1d1f6f0fbe2d"
DEVELOP_POU_GUID = "bcb465f6-3d0b-539a-b025-144432e0939d"
APP_GUID = "60805218-a29d-437c-87e4-65307711d826"
PLCLOGIC_GUID = "d065fd5a-a37a-40a0-bdcf-fa3012d36936"
DEVICE_GUID = "ea0913c2-01c3-4246-ae88-1c6b39cb02f1"
FOLDER_50 = "f66a7361-893a-453f-8407-8f140228ebba"

A26_BLOCK = f"""    <data name="http://www.3s-software.com/plcopenxml/action" handleUnknown="implementation">
      <action name="A26_rinse_suction">
        <body>
          <ST>
            <xhtml xmlns="http://www.w3.org/1999/xhtml">{_gen_suction_body()}</xhtml>
          </ST>
        </body>
        <addData>
          <data name="http://www.3s-software.com/plcopenxml/pathstructure" handleUnknown="discard">
            <pathStructure isFolder="False" name="Device" namespace="1ee21fdd-5562-44a0-a3ce-665d74916d50" factoryName="Inovance.InoPro.InoDeviceObject.DeviceObjectFactory" factoryGuid="{{84d12aa5-3225-473b-9df6-18af40889bdf}}" objectGuid="{DEVICE_GUID}">
              <pathStructure isFolder="False" name="Plc Logic" namespace="00000000-0000-0000-0000-000000000000" factoryName="_3S.CoDeSys.PlcLogicObject.PlcLogicObjectFactory" factoryGuid="{{8ceeba4e-ac7a-4fbd-9415-bfb2d98668ab}}" objectGuid="{PLCLOGIC_GUID}">
                <pathStructure isFolder="False" name="Application" namespace="e5b60c93-5445-4e40-ada9-cd9c005549b4" factoryName="_3S.CoDeSys.ApplicationObject.ApplicationObjectFactory" factoryGuid="{{ECADC42E-716E-4ff3-A93C-0CD143F9743F}}" objectGuid="{APP_GUID}">
                  <pathStructure isFolder="True" name="50_action" namespace="00000000-0000-0000-0000-000000000000" factoryName="Inovance.InoPro.InoNavigators.FolderObjectFactory" factoryGuid="{{BA66A801-C738-4176-B072-DFE26ACE36D3}}" objectGuid="{FOLDER_50}">
                    <pathStructure isFolder="False" name="Develop_L2" namespace="e5b60c93-5445-4e40-ada9-cd9c005549b4" factoryName="Inovance.InoPro.InoPOUObject.POUObjectFactory" factoryGuid="{{39C4ED2B-903C-464c-9041-7DF4ECEE9609}}" objectGuid="{DEVELOP_POU_GUID}">
                      <pathStructure isFolder="False" name="A26_rinse_suction" namespace="e5b60c93-5445-4e40-ada9-cd9c005549b4" factoryName="Inovance.InoPro.InoPOUObject.ActionObjectFactory" factoryGuid="{{00393DE5-D8B3-4ff3-845F-37AAB59A22C5}}" objectGuid="{SUCTION_GUID}" />
                    </pathStructure>
                  </pathStructure>
                </pathStructure>
              </pathStructure>
            </pathStructure>
          </data>
          <data name="http://www.3s-software.com/plcopenxml/objectid" handleUnknown="discard">
            <ObjectId>{SUCTION_GUID}</ObjectId>
          </data>
        </addData>
      </action>
    </data>
"""

# 在 A21_rinse 动作块之后插入 A26_rinse_suction 动作块
anchor = '    <data name="http://www.3s-software.com/plcopenxml/action" handleUnknown="implementation">\n      <action name="A20_pipeline_清洗管路">'
assert text.count(anchor) == 1, "A20_pipeline 动作锚点不唯一"
text = text.replace(anchor, A26_BLOCK + anchor, 1)

def sub1(b: str, pattern: str, repl: str) -> str:
    """正则替换且断言恰好命中 1 次; repl 作字面量 (不解析反斜杠/组引用), 容忍制表/空白差异."""
    new, n = re.subn(pattern, lambda m: repl, b)
    assert n == 1, f"sub1 命中 {n} (需 1): {pattern!r}"
    return new


# Develop_L2 派发器: 动作码白名单 + CASE 加 26 (clean_line 不拆, 无 25)
def _develop_dispatch(b: str) -> str:
    b = sub1(b, r"10, 20, 21, 22, 31, 32:", "10, 20, 21, 22, 26, 31, 32:")
    b = sub1(b, r"21: A21_rinse_润洗展缸\(\);",
             "21: A21_rinse_润洗展缸();\n\t\t\t\t26: A26_rinse_suction();")
    return b

text = edit_block(text, "pou", "Develop_L2", _develop_dispatch)

# ---------------------------------------------------------------------------
# 4. collect: %MW300 typo + step30 双触发 (TON_0 沉淀与计数判定解耦)
# ---------------------------------------------------------------------------
def _collect_fix(b: str) -> str:
    b = sub1(b, r"%MW300:=128;", "%MW1300:=128;")
    b = sub1(
        b,
        r"IF ton\[2\]\.Q THEN\s+TON_0\(IN:=TRUE, PT:=T#5S\);\s+IF 收集计数&gt;=collect_count AND TON_0\.Q THEN",
        "TON_0(IN:=ton[2].Q, PT:=T#5S);   (* 排液计时后再沉淀, 沉淀完成才判定, 杜绝误回 step0 *)\n"
        "\t\tIF TON_0.Q THEN\n"
        "\t\t\tIF 收集计数&gt;=collect_count THEN",
    )
    return b

text = edit_block(text, "action", "A30_collect_收集", _collect_fix)

# ---------------------------------------------------------------------------
# 5. 5 个派发器: RUNNING(10) 中响应 RESET -> 中止回 IDLE (Pump_L2 已自带)
# ---------------------------------------------------------------------------
for prefix in ("Sampling", "Collect", "Develop", "PhotoScrape", "FeedLift"):
    def _reset_in_running(b: str, p=prefix) -> str:
        return sub1(
            b, r"10: \(\* RUNNING \*\)\n",
            f"10: (* RUNNING *)\n\t\tIF {p}_L2_Reset THEN {p}_L2_State := 0; RETURN; END_IF   (* RUNNING 中 RESET: 中止挂死动作 *)\n",
        )
    text = edit_block(text, "pou", f"{prefix}_L2", _reset_in_running)

# ---------------------------------------------------------------------------
# 6. 易挂死原子加传感器超时看门狗 (无料/无板时限时报错, 不再死等)
# ---------------------------------------------------------------------------
# A11_feed_raise: step0 等 升降接近开关1/进料传感器, 无则超时 301
def _feed_raise_to(b: str) -> str:
    b = sub1(b, r"CASE 上料step OF", "feedlift_TO(IN:=上料step=0, PT:=T#10S);\nCASE 上料step OF")
    b = sub1(b, r"上料step:=1;\n[ \t]*END_IF",
             "上料step:=1;\n\t\tELSIF feedlift_TO.Q THEN\n"
             "\t\t\tFeedLift_L2_ErrorCode:=301;   (* 上料无玻璃/传感器未就绪 *)\n"
             "\t\t\t上料step:=0;\n\t\t\tbActionError:=TRUE;\n\t\tEND_IF")
    return b

text = edit_block(text, "action", "A11_feed_raise", _feed_raise_to)

# A22_unload_bury: step0 等 升降光电2/接近2, 无则超时 302
def _unload_bury_to(b: str) -> str:
    b = sub1(b, r"CASE 下料step OF", "feedlift_TO(IN:=下料step=0, PT:=T#10S);\nCASE 下料step OF")
    b = sub1(b, r"下料step:=10;\n[ \t]*END_IF",
             "下料step:=10;\n\t\tELSIF feedlift_TO.Q THEN\n"
             "\t\t\tFeedLift_L2_ErrorCode:=302;   (* 下料无玻璃/传感器未就绪 *)\n"
             "\t\t\t下料step:=0;\n\t\t\tbActionError:=TRUE;\n\t\tEND_IF")
    return b

text = edit_block(text, "action", "A22_unload_bury", _unload_bury_to)

# FeedLift_L2 POU: 新增 feedlift_TO (TON) 局部变量供上述两原子使用
def _feedlift_add_ton(b: str) -> str:
    block = ('            <variable name="L2_StartTrig">\n'
             '              <type>\n'
             '                <derived name="R_TRIG" />\n'
             '              </type>\n'
             '            </variable>\n')
    add = ('            <variable name="feedlift_TO">\n'
           '              <type>\n'
           '                <derived name="TON" />\n'
           '              </type>\n'
           '            </variable>\n')
    assert b.count(block) == 1, f"L2_StartTrig 块命中 {b.count(block)}"
    return b.replace(block, block + add)

text = edit_block(text, "pou", "FeedLift_L2", _feedlift_add_ton)

DST.write_text(text, encoding="utf-8")
print(f"WROTE {DST} ({len(text)} chars)")

# 良构校验
import lxml.etree as ET
ET.parse(str(DST))
print("WELL-FORMED OK")
for tok in ["A26_rinse_suction", "26: A26_rinse_suction();", "feedlift_TO",
            "%MW300:=128", "大真空泵站位[9]", "大真空泵站位[10]"]:
    print(f"  {tok:28s} count={text.count(tok)}")
