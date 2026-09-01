# -*- coding: utf-8 -*-
"""
功能:
    把 plc_split/All.xml.bak (原始 PLCopen 导出) 变换为解耦后的 All.xml:
    新增 50_action 文件夹 + 各工位 L2 派发器 POU + 纯设备原子动作 + L2 通道 GVL 节点.
    (本阶段先做 Collection 工位的"新增"部分, 后续工位/删除/改写在同一脚本内追加.)
协议:
    确定性变换 —— 始终从 All.xml.bak 读入, 写出 All.xml, 可反复运行结果一致.
    新对象 GUID 用 uuid5(固定命名空间, 逻辑名) 确定性生成, 保证 pathStructure /
    ObjectId / ProjectStructure 三处一致且重跑稳定.
"""
import uuid
import sys
from lxml import etree

NS = "http://www.plcopen.org/xml/tc6_0200"
XHTML = "http://www.w3.org/1999/xhtml"
Q = lambda t: f"{{{NS}}}{t}"

SRC = "plc_split/All.xml.bak"
DST = "plc_split/All.xml"

# 确定性 GUID 命名空间 (固定随意常量)
_GUID_NS = uuid.UUID("6f1d2c34-5a6b-47c8-9d0e-1f2a3b4c5d6e")
def guid(logical_name: str) -> str:
    return str(uuid.uuid5(_GUID_NS, "ptlc50:" + logical_name))

# 工程树路径常量 (忠实原文件)
DEVICE = dict(name="Device", ns="1ee21fdd-5562-44a0-a3ce-665d74916d50",
              fn="Inovance.InoPro.InoDeviceObject.DeviceObjectFactory",
              fg="{84d12aa5-3225-473b-9df6-18af40889bdf}", og="ea0913c2-01c3-4246-ae88-1c6b39cb02f1")
PLCLOGIC = dict(name="Plc Logic", ns="00000000-0000-0000-0000-000000000000",
                fn="_3S.CoDeSys.PlcLogicObject.PlcLogicObjectFactory",
                fg="{8ceeba4e-ac7a-4fbd-9415-bfb2d98668ab}", og="d065fd5a-a37a-40a0-bdcf-fa3012d36936")
APP = dict(name="Application", ns="e5b60c93-5445-4e40-ada9-cd9c005549b4",
           fn="_3S.CoDeSys.ApplicationObject.ApplicationObjectFactory",
           fg="{ECADC42E-716E-4ff3-A93C-0CD143F9743F}", og="60805218-a29d-437c-87e4-65307711d826")
FOLDER_FN = "Inovance.InoPro.InoNavigators.FolderObjectFactory"
FOLDER_FG = "{BA66A801-C738-4176-B072-DFE26ACE36D3}"
POU_FN = "Inovance.InoPro.InoPOUObject.POUObjectFactory"
POU_FG = "{39C4ED2B-903C-464c-9041-7DF4ECEE9609}"
ACT_FN = "Inovance.InoPro.InoPOUObject.ActionObjectFactory"
ACT_FG = "{00393DE5-D8B3-4ff3-845F-37AAB59A22C5}"
APPNS = APP["ns"]

FOLDER50_GUID = guid("folder:50_action")


def _ps(parent, isFolder, name, ns, fn, fg, og):
    e = etree.SubElement(parent, Q("pathStructure"))
    e.set("isFolder", "True" if isFolder else "False")
    e.set("name", name); e.set("namespace", ns)
    e.set("factoryName", fn); e.set("factoryGuid", fg); e.set("objectGuid", og)
    return e


def make_pathstructure_data(leaf_kind, pou_name, pou_guid, action_name=None, action_guid=None):
    """构造 addData/pathStructure 链: Device>PlcLogic>Application>50_action>POU[>action]."""
    data = etree.Element(Q("data"))
    data.set("name", "http://www.3s-software.com/plcopenxml/pathstructure")
    data.set("handleUnknown", "discard")
    d = _ps(data, False, DEVICE["name"], DEVICE["ns"], DEVICE["fn"], DEVICE["fg"], DEVICE["og"])
    p = _ps(d, False, PLCLOGIC["name"], PLCLOGIC["ns"], PLCLOGIC["fn"], PLCLOGIC["fg"], PLCLOGIC["og"])
    a = _ps(p, False, APP["name"], APP["ns"], APP["fn"], APP["fg"], APP["og"])
    f = _ps(a, True, "50_action", "00000000-0000-0000-0000-000000000000", FOLDER_FN, FOLDER_FG, FOLDER50_GUID)
    pou = _ps(f, False, pou_name, APPNS, POU_FN, POU_FG, pou_guid)
    if action_name is not None:
        _ps(pou, False, action_name, APPNS, ACT_FN, ACT_FG, action_guid)
    return data


def make_objectid_data(obj_guid):
    data = etree.Element(Q("data"))
    data.set("name", "http://www.3s-software.com/plcopenxml/objectid")
    data.set("handleUnknown", "discard")
    etree.SubElement(data, Q("ObjectId")).text = obj_guid
    return data


def add_var(localvars_or_globalvars, name, type_spec):
    """type_spec: ('simple','INT') | ('derived','TON') | ('array',1,5,'derived','R_TRIG') | ('array',1,5,'simple','INT')."""
    v = etree.SubElement(localvars_or_globalvars, Q("variable")); v.set("name", name)
    t = etree.SubElement(v, Q("type"))
    kind = type_spec[0]
    if kind == "simple":
        etree.SubElement(t, Q(type_spec[1]))
    elif kind == "derived":
        etree.SubElement(t, Q("derived")).set("name", type_spec[1])
    elif kind == "array":
        _, lo, hi, basekind, basename = type_spec
        arr = etree.SubElement(t, Q("array"))
        dim = etree.SubElement(arr, Q("dimension")); dim.set("lower", str(lo)); dim.set("upper", str(hi))
        bt = etree.SubElement(arr, Q("baseType"))
        if basekind == "simple":
            etree.SubElement(bt, Q(basename))
        else:
            etree.SubElement(bt, Q("derived")).set("name", basename)
    return v


def make_body(code_text):
    body = etree.Element(Q("body"))
    st = etree.SubElement(body, Q("ST"))
    xhtml = etree.SubElement(st, f"{{{XHTML}}}xhtml", nsmap={None: XHTML})
    xhtml.text = code_text
    return body


def make_pou(pou_name, localvars, body_text):
    """构造 program POU 元素 (interface + body + addData)."""
    pou = etree.Element(Q("pou")); pou.set("name", pou_name); pou.set("pouType", "program")
    itf = etree.SubElement(pou, Q("interface"))
    lv = etree.SubElement(itf, Q("localVars"))
    for nm, ts in localvars:
        add_var(lv, nm, ts)
    pou.append(make_body(body_text))
    ad = etree.SubElement(pou, Q("addData"))
    ad.append(make_pathstructure_data("pou", pou_name, guid("pou:" + pou_name)))
    ad.append(make_objectid_data(guid("pou:" + pou_name)))
    return pou


def make_action_data(pou_name, action_name, body_text):
    """构造一个 <data name=...action> 块 (项目级 addData 下)."""
    data = etree.Element(Q("data"))
    data.set("name", "http://www.3s-software.com/plcopenxml/action")
    data.set("handleUnknown", "implementation")
    act = etree.SubElement(data, Q("action")); act.set("name", action_name)
    act.append(make_body(body_text))
    ad = etree.SubElement(act, Q("addData"))
    aguid = guid("action:" + pou_name + "/" + action_name)
    ad.append(make_pathstructure_data("action", pou_name, guid("pou:" + pou_name),
                                      action_name=action_name, action_guid=aguid))
    ad.append(make_objectid_data(aguid))
    return data


# ─────────────────────────────────────────────────────────────────────────
# 原动作体派生 (从 All.xml.bak 取原 ST, 做最小手术: 删行 / 插 bActionDone)
# ─────────────────────────────────────────────────────────────────────────
_BAK_ROOT = etree.parse(SRC).getroot()

def orig_body(pou_name, action_name):
    """取 bak 中归属 pou_name 的 action_name 的 ST 正文 (real <>& 已反转义, 含原制表符)."""
    for d in _BAK_ROOT.find(Q("addData")).findall(Q("data")):
        if d.get("name") != "http://www.3s-software.com/plcopenxml/action":
            continue
        a = d.find(Q("action"))
        if a.get("name") != action_name:
            continue
        leaf = None
        for ps in d.iter(Q("pathStructure")):
            if (ps.get("factoryName") or "").endswith("POUObjectFactory"):
                leaf = ps.get("name")
        if leaf == pou_name:
            return a.find(f".//{{{XHTML}}}xhtml").text
    raise KeyError(f"{pou_name}/{action_name}")


def strip_lines(body, substrs):
    """删除任何包含 substrs 之一的整行 (用于剔除机器人/相机/CNC 握手行)."""
    return "\n".join(ln for ln in body.split("\n")
                     if not any(s in ln for s in substrs))


def expand_cyl_case(setval, sensor):
    """生成展缸 Group(1..2)/Number(1..4) 气缸寻址 CASE; 到位传感器满足则置 bActionDone."""
    out = ["CASE Expand_Group OF"]
    for g in (1, 2):
        out.append(f"\t{g}:")
        out.append("\t\tCASE Expand_Number OF")
        for n in (1, 2, 3, 4):
            cyl = f"展缸{g}气缸{n}"
            out.append(f"\t\t\t{n}:")
            out.append(f"\t\t\t\t{cyl}自动:={setval};")
            out.append(f"\t\t\t\tIF {cyl}{sensor} THEN bActionDone:=TRUE; END_IF")
        out.append("\t\tEND_CASE")
    out.append("END_CASE")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────
# L2 通道 GVL 节点 (每工位 12 字段; 贴进 Host_Computer)
# ─────────────────────────────────────────────────────────────────────────
def l2_nodes(prefix):
    INT = ("simple", "INT"); DINT = ("simple", "DINT"); BOOL = ("simple", "BOOL")
    return [
        (f"{prefix}_L2_ActionCode", INT), (f"{prefix}_L2_RequestSeq", DINT),
        (f"{prefix}_L2_Start", BOOL), (f"{prefix}_L2_Reset", BOOL),
        (f"{prefix}_L2_State", INT), (f"{prefix}_L2_ActiveCode", INT),
        (f"{prefix}_L2_AcceptedSeq", DINT), (f"{prefix}_L2_CompletedSeq", DINT),
        (f"{prefix}_L2_Step", INT), (f"{prefix}_L2_ErrorCode", INT),
        (f"{prefix}_L2_SafeState", INT), (f"{prefix}_L2_Retryable", BOOL),
    ]


def make_dispatch(prefix, codes, resets, accept_extra=""):
    """生成工位 L2 派发器 ST. codes=[(code,action_name),...]; resets=[step 变量名,...].
    accept_extra: 接受请求时(置 ActiveCode 后)注入的额外 ST (如 Develop 由 Target_Tank 推导 Group/Number).
    协议: Start 上升沿接受 -> RUNNING 调原子 -> bActionDone->DONE / bActionError->ERROR(报错交上位机)."""
    code_list = ", ".join(str(c) for c, _ in codes)
    reset_lines = "\n".join(f"\t\t\t{r} := 0;" for r in resets)
    if accept_extra:
        reset_lines = reset_lines + "\n" + "\n".join("\t\t\t" + ln for ln in accept_extra.split("\n"))
    run_lines = "\n".join(f"\t\t\t{c}: {n}();" for c, n in codes)
    return f"""(* {prefix} 工位 L2 统一动作派发器
   按 {prefix}_L2_ActionCode 派发到纯设备原子动作 (不含机器人/相机/CNC 握手).
   Start 上升沿接受请求 -> RUNNING 每周期调用对应原子 -> bActionDone=DONE / bActionError=ERROR. *)
L2_StartTrig(CLK := {prefix}_L2_Start);

CASE {prefix}_L2_State OF
\t0:  (* IDLE *)
\t\t{prefix}_L2_Step := 0;
\t\tIF L2_StartTrig.Q THEN
\t\t\t{prefix}_L2_AcceptedSeq := {prefix}_L2_RequestSeq;
\t\t\t{prefix}_L2_ActiveCode  := {prefix}_L2_ActionCode;
\t\t\t{prefix}_L2_ErrorCode   := 0;
\t\t\t{prefix}_L2_Retryable   := FALSE;
\t\t\tbActionDone  := FALSE;
\t\t\tbActionError := FALSE;
{reset_lines}
\t\t\tCASE {prefix}_L2_ActionCode OF
\t\t\t\t{code_list}:
\t\t\t\t\t{prefix}_L2_SafeState := 0;
\t\t\t\t\t{prefix}_L2_State     := 10;   (* RUNNING *)
\t\t\tELSE
\t\t\t\t{prefix}_L2_ErrorCode    := 101;  (* 未知动作码 *)
\t\t\t\t{prefix}_L2_Retryable    := TRUE;
\t\t\t\t{prefix}_L2_CompletedSeq := {prefix}_L2_AcceptedSeq;
\t\t\t\t{prefix}_L2_State        := 30;   (* REJECTED *)
\t\t\tEND_CASE
\t\tEND_IF

\t10: (* RUNNING *)
\t\tCASE {prefix}_L2_ActiveCode OF
{run_lines}
\t\tEND_CASE
\t\tIF bActionDone THEN
\t\t\tbActionDone              := FALSE;
\t\t\t{prefix}_L2_CompletedSeq := {prefix}_L2_AcceptedSeq;
\t\t\t{prefix}_L2_State        := 20;   (* DONE *)
\t\tELSIF bActionError THEN              (* 设备预条件未满足 -> 报错交上位机 *)
\t\t\tbActionError             := FALSE;
\t\t\t{prefix}_L2_Retryable    := TRUE;
\t\t\t{prefix}_L2_CompletedSeq := {prefix}_L2_AcceptedSeq;
\t\t\t{prefix}_L2_State        := 40;   (* ERROR; ErrorCode 由原子置 *)
\t\tEND_IF

\t20, 30, 40, 50:  (* 终态: 等 Start 落沿或 Reset 回 IDLE *)
\t\tIF (NOT {prefix}_L2_Start) OR {prefix}_L2_Reset THEN
\t\t\t{prefix}_L2_State := 0;
\t\tEND_IF
END_CASE
"""


# ═════════════════════════════════════════════════════════════════════════
# Collection 工位内容 (派发器 POU + 8 原子动作)
# ═════════════════════════════════════════════════════════════════════════
COLLECT_LOCALS = [
    ("初始化STEP", ("simple", "INT")), ("准备step", ("simple", "INT")),
    ("收集step", ("simple", "INT")), ("搬运step", ("simple", "INT")),
    ("泵初始化完成", ("simple", "BOOL")), ("bActionDone", ("simple", "BOOL")),
    ("bActionError", ("simple", "BOOL")),
    ("L2_StartTrig", ("derived", "R_TRIG")),
    ("R_TRIG", ("array", 1, 5, "derived", "R_TRIG")),
    ("ton", ("array", 1, 10, "derived", "TON")),
    ("TON_0", ("derived", "TON")),
]

COLLECT_DISPATCH = """(* 收集工位 L2 统一动作派发器
   功能:
       按 Collect_L2_ActionCode 把上位机请求派发到设备原子动作 (纯设备, 不含机器人握手).
   协议:
       Collect_L2_Start 上升沿接受请求 -> RUNNING 每周期调用对应原子 -> 原子置 bActionDone -> DONE.
   动作码:
       10 init 初始化 / 21 夹持夹紧 / 22 伸缩伸出 / 23 缩回升降下压
       30 collect 收集 / 41 复位伸出 / 42 伸缩缩回 / 43 松夹持
   参数:
       无, 经 Collect_L2_* 反馈. *)
L2_StartTrig(CLK := Collect_L2_Start);

CASE Collect_L2_State OF
\t0:  (* IDLE *)
\t\tCollect_L2_Step := 0;
\t\tIF L2_StartTrig.Q THEN
\t\t\tCollect_L2_AcceptedSeq := Collect_L2_RequestSeq;
\t\t\tCollect_L2_ActiveCode  := Collect_L2_ActionCode;
\t\t\tCollect_L2_ErrorCode   := 0;
\t\t\tCollect_L2_Retryable   := FALSE;
\t\t\tbActionDone            := FALSE;
\t\t\tbActionError           := FALSE;
\t\t\t初始化STEP := 0;
\t\t\t准备step   := 0;
\t\t\t收集step   := 0;
\t\t\t搬运step   := 0;
\t\t\tCASE Collect_L2_ActionCode OF
\t\t\t\t10, 21, 22, 23, 30, 41, 42, 43:
\t\t\t\t\tCollect_L2_SafeState := 0;
\t\t\t\t\tCollect_L2_State     := 10;   (* RUNNING *)
\t\t\tELSE
\t\t\t\tCollect_L2_ErrorCode    := 101;  (* 未知动作码 *)
\t\t\t\tCollect_L2_Retryable    := TRUE;
\t\t\t\tCollect_L2_CompletedSeq := Collect_L2_AcceptedSeq;
\t\t\t\tCollect_L2_State        := 30;   (* REJECTED *)
\t\t\tEND_CASE
\t\tEND_IF

\t10: (* RUNNING *)
\t\tCASE Collect_L2_ActiveCode OF
\t\t\t10: A10_init_初始化();
\t\t\t21: A21_夹持夹紧();
\t\t\t22: A22_伸缩伸出();
\t\t\t23: A23_缩回升降下压();
\t\t\t30: A30_collect_收集();
\t\t\t41: A41_复位伸出();
\t\t\t42: A42_伸缩缩回();
\t\t\t43: A43_松夹持();
\t\tEND_CASE
\t\tIF bActionDone THEN
\t\t\tbActionDone             := FALSE;
\t\t\tCollect_L2_CompletedSeq := Collect_L2_AcceptedSeq;
\t\t\tCollect_L2_State        := 20;   (* DONE *)
\t\tELSIF bActionError THEN              (* 设备预条件未满足 -> 报错交上位机 *)
\t\t\tbActionError            := FALSE;
\t\t\tCollect_L2_Retryable    := TRUE;
\t\t\tCollect_L2_CompletedSeq := Collect_L2_AcceptedSeq;
\t\t\tCollect_L2_State        := 40;   (* ERROR; ErrorCode 由原子置 *)
\t\tEND_IF

\t20, 30, 40, 50:  (* 终态: 等 Start 落沿或 Reset 回 IDLE *)
\t\tIF (NOT Collect_L2_Start) OR Collect_L2_Reset THEN
\t\t\tCollect_L2_State := 0;
\t\tEND_IF
END_CASE
"""

COLLECT_ACTIONS = [
    ("A10_init_初始化", """(* 初始化: 复位气缸/电磁阀 + 注射泵初始化 (已删机器人握手位复位)
   完成条件: 四气缸回原点 AND 泵初始化完成 *)
R_TRIG[1](CLK := %MX2005.5);   (* 泵空闲上升沿 *)
CASE 初始化STEP OF
\t0:
\t\t收集下压气缸手动:=FALSE; 收集下压气缸自动:=FALSE;
\t\t收集夹持气缸手动:=FALSE; 收集夹持气缸自动:=FALSE;
\t\t收集升降气缸手动:=FALSE; 收集升降气缸自动:=FALSE;
\t\t收集伸缩气缸手动:=FALSE; 收集伸缩气缸自动:=FALSE;
\t\t收集进液手动:=FALSE; 收集进液自动:=FALSE;
\t\t收集排液手动:=FALSE; 收集排液自动:=FALSE;
\t\t收集正压排液手动:=FALSE; 收集正压排液自动:=FALSE;
\t\t溶液收集瓶定位手动:=FALSE;
\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:='/3Z0,2,2R$R';             (* 泵初始化指令 *)
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t初始化STEP:=10;
\t\tEND_IF
\t10:
\t\tIF %MW1300=0 THEN
\t\t\t转发转存:='/3Q$R';                   (* 查询泵状态 *)
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[1].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\t泵初始化完成:=TRUE;
\t\t\t初始化STEP:=20;
\t\tEND_IF
\t20:
\t\tIF 收集平台下压气缸原点 AND 收集平台夹持气缸原点
\t\t   AND 收集平台升降气缸原点 AND 收集平台推出气缸原点
\t\t   AND 泵初始化完成 THEN
\t\t\t泵初始化完成:=FALSE;
\t\t\t初始化STEP:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A21_夹持夹紧", """(* 夹持气缸夹紧 (上位机已先驱动机器人放收集器) *)
CASE 准备step OF
\t0:
\t\t收集夹持气缸自动:=TRUE;
\t\t准备step:=10;
\t10:
\t\tIF 收集平台夹持气缸动点 THEN
\t\t\t准备step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A22_伸缩伸出", """(* 伸缩气缸伸出到放瓶位 *)
CASE 准备step OF
\t0:
\t\tIF 收集平台推出气缸原点 AND NOT 收集平台瓶子有无传感器 THEN
\t\t\t收集伸缩气缸自动:=TRUE;
\t\t\t准备step:=10;
\t\tEND_IF
\t10:
\t\tIF 收集平台推出气缸动点 THEN
\t\t\t准备step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A23_缩回升降下压", """(* 缩回 -> 升降上升 -> 下压 (上位机已先驱动机器人放收集瓶)
   缺瓶处理: 原 A10 "缺瓶重试" 改为报错交上位机 (ErrorCode 201), 由上位机重放瓶后重调 *)
CASE 准备step OF
\t0:
\t\t收集伸缩气缸自动:=FALSE;
\t\t准备step:=10;
\t10:
\t\tIF 收集平台推出气缸原点 AND 收集平台瓶子有无传感器 THEN
\t\t\t收集升降气缸自动:=TRUE;
\t\t\t准备step:=20;
\t\tELSIF 收集平台推出气缸原点 AND NOT 收集平台瓶子有无传感器 THEN
\t\t	准备step:=0;
\t\t	Collect_L2_ErrorCode:=201;   (* 缺瓶: 上位机放瓶后传感器未检到 *)
\t\t	bActionError:=TRUE;
\t\tEND_IF
\t20:
\t\tIF 收集平台升降气缸动点 THEN
\t\t\t收集下压气缸自动:=TRUE;
\t\t\t准备step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A30_collect_收集", """(* 收集: 进液 -> 注射泵转发 -> 排液/正压循环 collect_count 次 (纯设备, 不变) *)
ton[1](IN:=收集step=10, PT:=T#0.5S);
ton[2](IN:=收集step=30, PT:=T#10S);
R_TRIG[5](CLK := %MX2005.5);
CASE 收集step OF
\t0:
\t\tIF collect_forward_instructions<>'' THEN
\t\t\t收集进液自动:=TRUE;
\t\tEND_IF
\t\tIF %MW1300=0 AND 泵站位符=FALSE THEN
\t\t\t转发转存:=collect_forward_instructions;
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t泵站位符:=TRUE;
\t\t\t收集step:=10;
\t\tEND_IF
\t10:
\t\tIF %MW1300=0 AND ton[1].Q THEN
\t\t\t转发转存:='/3Q$R';
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[5].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\t收集step:=20;
\t\tEND_IF
\t20:
\t\t转发转存:='';
\t\t%MW300:=128;
\t\t收集进液自动:=FALSE;
\t\t收集排液自动:=TRUE;
\t\t收集正压排液自动:=TRUE;
\t\t收集计数:=收集计数+1;
\t\t收集step:=30;
\t30:
\t\tIF ton[2].Q THEN
\t\t\tTON_0(IN:=TRUE, PT:=T#5S);
\t\t\tIF 收集计数>=collect_count AND TON_0.Q THEN
\t\t\t\t收集计数:=0;
\t\t\t\t收集step:=40;
\t\t\tELSE
\t\t\t\t收集排液自动:=FALSE;
\t\t\t\t收集正压排液自动:=FALSE;
\t\t\t\t收集step:=0;
\t\t\tEND_IF
\t\tEND_IF
\t40:
\t\t收集排液自动:=FALSE;
\t\t收集正压排液自动:=FALSE;
\t\t收集step:=0;
\t\tbActionDone:=TRUE;
END_CASE
"""),
    ("A41_复位伸出", """(* 搬运段1: 复位下压/升降 -> 伸缩伸出到取瓶位 *)
CASE 搬运step OF
\t0:
\t\t收集下压气缸自动:=FALSE;
\t\t搬运step:=5;
\t5:
\t\tIF 收集平台下压气缸原点 THEN
\t\t\t收集升降气缸自动:=FALSE;
\t\t\t搬运step:=10;
\t\tEND_IF
\t10:
\t\tIF 收集平台升降气缸原点 THEN
\t\t\t收集伸缩气缸自动:=TRUE;
\t\t\t搬运step:=20;
\t\tEND_IF
\t20:
\t\tIF 收集平台推出气缸动点 THEN
\t\t\t搬运step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A42_伸缩缩回", """(* 搬运段2: 伸缩缩回 (上位机已先驱动机器人取瓶到暂存) *)
CASE 搬运step OF
\t0:
\t\t收集伸缩气缸自动:=FALSE;
\t\t搬运step:=10;
\t10:
\t\tIF 收集平台推出气缸原点 THEN
\t\t\t搬运step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A43_松夹持", """(* 搬运段3: 松夹持 (上位机已先驱动机器人到收集器位) *)
CASE 搬运step OF
\t0:
\t\t收集夹持气缸自动:=FALSE;
\t\t搬运step:=10;
\t10:
\t\tIF 收集平台夹持气缸原点 THEN
\t\t\t搬运step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
]

# ═════════════════════════════════════════════════════════════════════════
# Sampling 工位内容 (上样点样; 派发器 + 7 原子)  10 init/20 clean/31 放板移轴/32 放板定位/40 prep/50 absorb/60 spray
# ═════════════════════════════════════════════════════════════════════════
SAMPLING_LOCALS = [
    ("初始化step", ("simple", "INT")), ("清洗step", ("simple", "INT")),
    ("清洗计数", ("simple", "INT")), ("放硅胶板STEP", ("simple", "INT")),
    ("上样准备step", ("simple", "INT")), ("吸收液体step", ("simple", "INT")),
    ("点样step", ("simple", "INT")), ("N", ("simple", "INT")), ("A", ("simple", "INT")),
    ("打样伺服移动step", ("simple", "INT")),
    ("bActionDone", ("simple", "BOOL")), ("bActionError", ("simple", "BOOL")),
    ("TON_0", ("derived", "TON")), ("TON_1", ("derived", "TON")),
    ("L2_StartTrig", ("derived", "R_TRIG")),
    ("R_TRIG", ("array", 1, 12, "derived", "R_TRIG")),
    ("TON", ("array", 1, 11, "derived", "TON")),
]

SAMPLING_ACTIONS = [
    ("A10_init_初始化", """(* 初始化: 复位阀/伺服回零 + 注射泵初始化 (已删机器人握手位复位) *)
CASE 初始化step OF
\t0 :
\t\t上样定位手动:=FALSE;
\t\t上样定位自动:=FALSE;
\t\t上样点样三通电池阀手动:=FALSE;
\t\t上样点样三通电池阀自动:=FALSE;
\t\t上样吹气手动:=FALSE;
\t\t上样吹气自动:=FALSE;
\t\t打样瓶上料轴3YDATE.fAbsTarget:=0;
\t\t点样轴6XDATE.fAbsTarget:=0;
\t\t点样轴7YDATE.fAbsTarget:=0;
\t\t上样轴4X轴DATE.fAbsTarget:=0;
\t\t上样轴5Z轴DATE.fAbsTarget:=0;
\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t上样轴4X轴DATE.xMoveAbs:=FALSE;
\t\t打样瓶上料轴3YDATE.xMoveAbs:=FALSE;
\t\tSampling_Spray_sample_OK:=FALSE;
\t\tSampling_liquid_absorption:=FALSE;
\t\tSampling_preparation_OK:=FALSE;
\t\t大真空泵站位[11]:=FALSE;
\t\t清洗计数:=0;
\t\t清洗step:=0;
\t\t放硅胶板STEP:=0;
\t\t上样准备step:=0;
\t\t吸收液体step:=0;
\t\t点样step:=0;
\t\t初始化step:=5;
\t5:
\t\t上样轴5Z轴DATE.fAbsTarget:=0;
\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\tIF 上样轴5Z轴DATE.bAbMoveDone THEN
\t\t\t点样轴7YDATE.fAbsTarget:=0  ;
\t\t\t点样轴6XDATE.fAbsTarget:=0  ;
\t\t\t上样轴4X轴DATE.fAbsTarget:=0;
\t\t\t上样轴4X轴DATE.xMoveAbs:=TRUE;
\t\t\t点样轴7YDATE.xMoveAbs:=TRUE;
\t\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t\t初始化step:=6;
\t\tEND_IF
\t6:
\t\tIF 上样轴4X轴DATE.bAbMoveDone AND 上样轴5Z轴DATE.bAbMoveDone AND 点样轴6XDATE.bAbMoveDone AND 点样轴7YDATE.bAbMoveDone THEN
\t\t\t初始化step:=10;
\t\t\t上样轴4X轴DATE.xMoveAbs:=FALSE;
\t\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\tEND_IF
\t10:
\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:='/4Z0,1,1R$R';
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t初始化STEP:=20;
\t\tEND_IF
\t20:
\t\tIF %MW1300=0 THEN
\t\t\t转发转存:='/4Q$R';
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tR_TRIG[1](CLK:=%MX2005.5);
\t\tIF R_TRIG[1].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\t初始化STEP:=30;
\t\tEND_IF
\t30:
\t\tSampling_initialization_OK:=TRUE;
\t\t初始化step:=0;
\t\tbActionDone:=TRUE;
END_CASE
"""),
    ("A20_clean_清洗", """(* 清洗: 伺服到清洗位 -> 注射泵清洗循环 Sampling_clean_count 次 (纯设备) *)
TON[1](IN:=清洗step=20,PT:=T#0.5S);
TON[6](IN:=清洗step=40,PT:=T#0.5S);
TON[8](IN:=清洗step=26,PT:=T#0.5S);
R_TRIG[2](CLK:=%MX2005.5);
R_TRIG[11](CLK:=%MX2005.5);
R_TRIG[12](CLK:=%MX2005.5);
CASE 清洗step OF
\t0 :
\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t上样轴4X轴DATE.xMoveAbs:=FALSE;
\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t清洗step:=5;
\t5:
\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[1];
\t\t上样轴4X轴DATE.fAbsTarget:=HMI_上样轴4X轴.position[9];
\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t上样轴4X轴DATE.xMoveAbs:=TRUE;
\t\t清洗计数:=0;
\t\t清洗step:=6;
\t6:
\t\tIF 上样轴4X轴DATE.bAbMoveDone THEN
\t\t\t上样轴4X轴DATE.xMoveAbs:=FALSE;
\t\t\t上样轴5Z轴DATE.fAbsTarget:=HMI_上样轴5Z轴.position[1];
\t\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\t\t清洗step:=7;
\t\tEND_IF
\t7:
\t\tIF  上样轴5Z轴DATE.bAbMoveDone AND 点样轴6XDATE.bAbMoveDone THEN
\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t\tIF Sampling_clean_count>0 THEN
\t\t\t\t清洗step:=10;
\t\t\tELSE
\t\t\t\t清洗step:=60;
\t\t\tEND_IF
\t\tEND_IF
\t10:
\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:=Sampling_clean_instructions[1];
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t大真空泵站位[11]:=TRUE;
\t\t\t上样点样三通电池阀自动:=TRUE;
\t\t\t清洗step:=20;
\t\tEND_IF
\t20:
\t\tIF %MW1300=0 AND TON[1].Q THEN
\t\t转发转存:='/4Q$R';
\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[2].Q THEN
\t\t\t上样点样三通电池阀自动:=FALSE;
\t\t\t泵站位符:=FALSE;
\t\t\t清洗step:=24;
\t\tEND_IF
\t24:
\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:=Sampling_clean_instructions[1];
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t清洗step:=26;
\t\tEND_IF
\t26:
\t\tIF %MW1300=0 AND TON[8].Q THEN
\t\t转发转存:='/4Q$R';
\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[11].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\t清洗step:=30;
\t\tEND_IF
\t30:
\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:=Sampling_clean_instructions[2];
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t清洗step:=40;
\t\tEND_IF
\t40:
\t\tIF %MW1300=0 AND TON[6].Q THEN
\t\t转发转存:='/4Q$R';
\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[12].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\t清洗step:=50;
\t\tEND_IF
\t50:
\t\t清洗计数:=清洗计数+1;
\t\tIF  Sampling_clean_count> 清洗计数 THEN
\t\t\t转发转存:='';
\t\t\t%MW1300:=128;
\t\t\t清洗step:=10;
\t\tELSIF  Sampling_clean_count<= 清洗计数 THEN
\t\t\t转发转存:='';
\t\t\t%MW1300:=128;
\t\t\t清洗计数:=0;
\t\t\tSampling_Cleaning_OK:=TRUE;
\t\t\t清洗step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
\t\t上样点样三通电池阀自动:=FALSE;
\t60:
\t\t大真空泵站位[11]:=FALSE;
\t\tSampling_Cleaning_OK:=TRUE;
\t\t清洗step:=0;
\t\tbActionDone:=TRUE;
END_CASE
"""),
    ("A31_放板移轴", """(* 放板移轴: 点样7Y轴到放板位 (上位机随后驱动机器人放板) *)
CASE 放硅胶板STEP OF
\t0:
\t\t点样轴7YDATE.fAbsTarget:=HMI_点样轴7Y.position[1];
\t\t点样轴7YDATE.xMoveAbs:=TRUE;
\t\t放硅胶板STEP:=10;
\t10:
\t\tIF 点样轴7YDATE.bAbMoveDone THEN
\t\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t\t放硅胶板STEP:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A32_放板定位", """(* 放板定位: 上位机放板后定位夹紧 *)
上样定位自动:=TRUE;
Sampling_Place_materials_OK:=TRUE;
bActionDone:=TRUE;
"""),
    ("A40_prep_上样准备", """(* 上样准备: Z回零 + 注射泵准备指令循环 (纯设备) *)
TON[2](IN:=上样准备step=2,PT:=T#0.5S);
R_TRIG[3](CLK:=%MX2005.5);
CASE 上样准备step OF
\t0:
\t\t上样轴5Z轴DATE.fAbsTarget:=0;
\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\tIF 上样轴5Z轴DATE.bAbMoveDone THEN
\t\t\tN:=1;
\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE ;
\t\t\t上样准备step:=1;
\t\tEND_IF
\t1:
\t\tCASE N OF
\t\t\t1,2:
\t\t\t\tIF %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t\t\t泵站位符:=TRUE;
\t\t\t\t\t转发转存:=Sampling_prep_instructions[N];
\t\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\t\t上样准备step:=2;
\t\t\t\tEND_IF
\t\tEND_CASE
\t2:
\t\tIF %MW1300=0 AND TON[2].Q THEN
\t\t转发转存:='/4Q$R';
\t\t%MW1300:=LEN(STR:= 转发转存);
\t\tEND_IF
\t\tIF R_TRIG[3].Q THEN
\t\t\t泵站位符:=FALSE;
\t\t\tN:=N+1;
\t\t\tIF N>2 THEN
\t\t\t\tSampling_preparation_OK:=TRUE;
\t\t\t\tN:=0;
\t\t\t\t上样准备step:=0;
\t\t\t\tbActionDone:=TRUE;
\t\t\tELSE
\t\t\t\t上样准备step:=1;
\t\t\tEND_IF
\t\tEND_IF
END_CASE
"""),
    ("A50_absorb_吸收液体", """(* 吸收液体: Z回零->XY到坐标->Z下探->泵吸液循环->Z回零 (纯设备) *)
TON_0(IN:=吸收液体step=30, PT:=T#0.5S);
TON_1(IN:=NOT 点样气泡传感器, PT:=T#5S);
R_TRIG[10](CLK:=%MX2005.5);
IF Sampling_X_coordinate>0 AND  Sampling_Y_coordinate>0  THEN
\tCASE 吸收液体step OF
\t\t0:
\t\t\t上样轴5Z轴DATE.fAbsTarget:=0;
\t\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\t\tIF 上样轴5Z轴DATE.bAbMoveDone THEN
\t\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t\t\t上样轴4X轴DATE.fAbsTarget:=HMI_上样轴4X轴.position[Sampling_X_coordinate];
\t\t\t\t打样瓶上料轴3YDATE.fAbsTarget:=HMI_打样瓶上料轴3Y.position[Sampling_Y_coordinate];
\t\t\t\t上样轴4X轴DATE.xMoveAbs:=TRUE;
\t\t\t\t打样瓶上料轴3YDATE.xMoveAbs:=TRUE;
\t\t\t\t吸收液体step:=10;
\t\t\tEND_IF
\t\t10:
\t\t\tIF 上样轴4X轴DATE.bAbMoveDone AND 打样瓶上料轴3YDATE.bAbMoveDone THEN
\t\t\t\t上样轴4X轴DATE.xMoveAbs:=FALSE;
\t\t\t\t打样瓶上料轴3YDATE.xMoveAbs:=FALSE;
\t\t\t\t上样轴5Z轴DATE.fAbsTarget:=HMI_上样轴5Z轴.position[2];
\t\t\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\t\t\t吸收液体step:=20;
\t\t\tEND_IF
\t\t20:
\t\t\tIF 上样轴5Z轴DATE.bAbMoveDone THEN
\t\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t\t\tA:=1;
\t\t\t\t吸收液体step:=25;
\t\t\tEND_IF
\t\t25:
\t\t\tCASE A OF
\t\t\t\t1,2:
\t\t\t\t\tIF  %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t\t\t\t转发转存:=Sampling_sample_instructions[A];
\t\t\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\t\t\t泵站位符:=TRUE;
\t\t\t\t\t\t吸收液体step:=30;
\t\t\t\t\tEND_IF
\t\t\tEND_CASE
\t\t30:
\t\t\tIF  %MW1300=0 AND TON_0.Q THEN
\t\t\t\t转发转存:='/4Q$R';
\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\tIF R_TRIG[10].Q THEN
\t\t\t\t\t泵站位符:=FALSE;
\t\t\t\t\tA:=A+1;
\t\t\t\t\tIF A>2 THEN
\t\t\t\t\t\tA:=0;
\t\t\t\t\t\t大真空泵站位[11]:=FALSE;
\t\t\t\t\t\t吸收液体step:=40;
\t\t\t\t\tELSE
\t\t\t\t\t\t吸收液体step:=25;
\t\t\t\t\tEND_IF
\t\t\t\tEND_IF
\t\t\tEND_IF
\t\t40:
\t\t\t上样轴5Z轴DATE.fAbsTarget:=0;
\t\t\t上样轴5Z轴DATE.xMoveAbs:=TRUE;
\t\t\tIF 上样轴5Z轴DATE.bAbMoveDone THEN
\t\t\t\t上样轴5Z轴DATE.xMoveAbs:=FALSE;
\t\t\t\tSampling_liquid_absorption:=TRUE;
\t\t\t\t吸收液体step:=0;
\t\t\t\tbActionDone:=TRUE;
\t\t\tEND_IF
\tEND_CASE
END_IF
"""),
    ("A60_spray_点样", """(* 点样: 伺服点样序列 + 注射泵点样 (已删尾部 允许取硅胶板 机器人握手) *)
TON[4](IN:=点样step=20,PT:=T#0.5S);
TON[5](IN:=点样气泡传感器,PT:=T#5S);
TON[7](IN:=点样step=10,PT:=T#0.5S);
R_TRIG[10](CLK:=%MX2005.5);
CASE 点样step OF
\t0:
\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t点样step:=1;
\t1:
\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[2];
\t\t点样轴7YDATE.fAbsTarget:=HMI_点样轴7Y.position[2];
\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t点样轴7YDATE.xMoveAbs:=TRUE;
\t\t点样step:=5;
\t5:
\t\tIF 点样轴6XDATE.bAbMoveDone AND 点样轴7YDATE.bAbMoveDone THEN
\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t\tIF  %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t\t泵站位符:=TRUE;
\t\t\t\t转发转存:=Sampling_dispense_instructions[1];
\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\t上样点样三通电池阀自动:=TRUE;
\t\t\t\t点样step:=10;
\t\t\tEND_IF
\t\tEND_IF
\t10:
\t\tIF  %MW1300=0 AND TON[7].Q THEN
\t\t\t\t转发转存:='/4Q$R';
\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\tIF R_TRIG[10].Q THEN
\t\t\t\t\t泵站位符:=FALSE;
\t\t\t\t\t点样step:=15;
\t\t\t\tEND_IF
\t\tEND_IF
\t15:
\t\tIF  %MW1300=0 AND NOT 泵站位符 THEN
\t\t\t上样吹气自动:=TRUE;
\t\t\t泵站位符:=TRUE;
\t\t\t转发转存:=Sampling_dispense_instructions[2];
\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[3];
\t\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t\t点样step:=20;
\t\tEND_IF
\t20:
\t\tIF  %MW1300=0 AND TON[4].Q THEN
\t\t\t\t转发转存:='/4Q$R';
\t\t\t\t%MW1300:=LEN(STR:= 转发转存);
\t\t\t\tIF R_TRIG[10].Q THEN
\t\t\t\t\t泵站位符:=FALSE;
\t\t\t\t\t上样点样三通电池阀自动:=FALSE;
\t\t\t\t\t上样吹气自动:=FALSE;
\t\t\t\tEND_IF
\t\tEND_IF
\t\tCASE 打样伺服移动step OF
\t\t\t0:
\t\t\t\tIF 点样轴6XDATE.bAbMoveDone THEN
\t\t\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t\t\t\tIF 泵站位符 THEN
\t\t\t\t\t\t打样伺服移动step:=10;
\t\t\t\t\tELSE
\t\t\t\t\t\t点样step:=30;
\t\t\t\t\tEND_IF
\t\t\t\tEND_IF
\t\t\t10:
\t\t\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[2];
\t\t\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t\t\t打样伺服移动step:=20;
\t\t\t20:
\t\t\t\tIF 点样轴6XDATE.bAbMoveDone THEN
\t\t\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t\t\t\t打样伺服移动step:=30;
\t\t\t\tEND_IF
\t\t\t30:
\t\t\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[3];
\t\t\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\t\t\t打样伺服移动step:=0;
\t\tEND_CASE
\t30:
\t\t点样轴6XDATE.fAbsTarget:=HMI_点样轴6X.position[1];
\t\t点样轴6XDATE.xMoveAbs:=TRUE;
\t\tIF 点样轴6XDATE.bAbMoveDone THEN
\t\t\t点样轴7YDATE.fAbsTarget:=HMI_点样轴7Y.position[1];
\t\t\t点样轴7YDATE.xMoveAbs:=TRUE;
\t\t\t点样step:=40;
\t\tEND_IF
\t40:
\t\tIF 点样轴7YDATE.bAbMoveDone  THEN
\t\t\t点样轴6XDATE.xMoveAbs:=FALSE;
\t\t\t点样轴7YDATE.xMoveAbs:=FALSE;
\t\t\t上样定位自动:=FALSE;
\t\t\tSampling_Spray_sample_OK:=TRUE;
\t\t\t点样step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
]

SAMPLING_CODES = [(10, "A10_init_初始化"), (20, "A20_clean_清洗"), (31, "A31_放板移轴"),
                  (32, "A32_放板定位"), (40, "A40_prep_上样准备"), (50, "A50_absorb_吸收液体"),
                  (60, "A60_spray_点样")]
SAMPLING_RESETS = ["初始化step", "清洗step", "放硅胶板STEP", "上样准备step", "吸收液体step", "点样step"]


# ═════════════════════════════════════════════════════════════════════════
# Develop 工位内容 (展开; 前缀 Develop, 缸寻址 Expand_Group/Number 由 Target_Tank 推导)
#   10 init/20 pipeline/21 rinse/22 up_liquid/31 放板缸回原点/32 放板缸到动点; 排液走 Tank_Drain 数组(剔除阶段处理)
# ═════════════════════════════════════════════════════════════════════════
EXPAND_LOCALS = [
    ("初始化step", ("simple", "INT")), ("清洗STEP", ("simple", "INT")),
    ("润洗展缸STEP", ("simple", "INT")), ("上液step", ("simple", "INT")),
    ("放硅胶板step", ("simple", "INT")), ("润洗计数", ("simple", "INT")),
    ("上液计数", ("simple", "INT")), ("泵初始化完成", ("simple", "BOOL")),
    ("bActionDone", ("simple", "BOOL")), ("bActionError", ("simple", "BOOL")),
    ("TON_0", ("derived", "TON")), ("TON_1", ("derived", "TON")), ("TON_2", ("derived", "TON")),
    ("L2_StartTrig", ("derived", "R_TRIG")),
    ("R_TRIG", ("array", 1, 10, "derived", "R_TRIG")),
    ("TON", ("array", 1, 10, "derived", "TON")),
]

_EXP = "Expand_process_展开流程"
_EX_INIT = strip_lines(
    orig_body(_EXP, "A00_initialization_初始化"),
    ["展开工位允许放硅胶板", "展开工位允许取硅胶板", "展开工位机器人到达准备点",
     "展开工位机器人放硅胶板完成", "展开工位取硅胶板完成"]
).replace("初始化STEP:=0;", "初始化STEP:=0; bActionDone:=TRUE;")
_EX_PIPE = orig_body(_EXP, "A10_pipeline_cleaning_清洗管路").replace(
    "Expand_Group_clean_OK:=TRUE;", "Expand_Group_clean_OK:=TRUE; bActionDone:=TRUE;")
_EX_RINSE = orig_body(_EXP, "A20_clean_expand_润洗展缸").replace(
    "Expand_Group_clean_OK:=TRUE;", "Expand_Group_clean_OK:=TRUE; bActionDone:=TRUE;")
_EX_UPLIQ = orig_body(_EXP, "A40_up_liquid_上液").replace(
    "Expand_up_liquid_OK:=TRUE;", "Expand_up_liquid_OK:=TRUE; bActionDone:=TRUE;")
_EX_RETRACT = "(* 放板-缸回原点 (上位机随后驱动机器人放板); 删原机器人到位/允许握手 *)\n" + expand_cyl_case("FALSE", "原点") + "\n"
_EX_EXTEND = "(* 放板-缸到动点 (上位机已驱动机器人放完板) *)\n" + expand_cyl_case("TRUE", "动点") + "\n"

EXPAND_ACTIONS = [
    ("A10_init_初始化", _EX_INIT),
    ("A20_pipeline_清洗管路", _EX_PIPE),
    ("A21_rinse_润洗展缸", _EX_RINSE),
    ("A22_up_liquid_上液", _EX_UPLIQ),
    ("A31_放板缸回原点", _EX_RETRACT),
    ("A32_放板缸到动点", _EX_EXTEND),
]
EXPAND_CODES = [(10, "A10_init_初始化"), (20, "A20_pipeline_清洗管路"), (21, "A21_rinse_润洗展缸"),
                (22, "A22_up_liquid_上液"), (31, "A31_放板缸回原点"), (32, "A32_放板缸到动点")]
EXPAND_RESETS = ["初始化step", "清洗STEP", "润洗展缸STEP", "上液step", "放硅胶板step"]
EXPAND_ACCEPT = ("Expand_Group  := (Expand_Target_Tank - 1) / 4 + 1;\n"
                 "Expand_Number := (Expand_Target_Tank - 1) MOD 4 + 1;")


# ═════════════════════════════════════════════════════════════════════════
# PhotoScrape 工位内容 (拍照刮板; 相机/CNC/机器人握手全删, 编排归上位机)
#   10 init / 31..35 相机设备原子 / 40 刮取单pass / 41 刮取收尾 / 51 取料松压 / 52 取料停旋转
#   注: CNC启动/CNC完成 属 PLC 内部 SoftMotion 线(在 GVL, 非 OPCUA 暴露), 保留; 多 pass 循环由上位机驱动.
# ═════════════════════════════════════════════════════════════════════════
PHOTO_LOCALS = [
    ("初始化step", ("simple", "INT")), ("拍照step", ("simple", "INT")),
    ("刮板收集step", ("simple", "INT")),
    ("bActionDone", ("simple", "BOOL")), ("bActionError", ("simple", "BOOL")),
    ("L2_StartTrig", ("derived", "R_TRIG")),
]

_PS = "Photo_scraper_拍照刮板"
_PH_INIT = strip_lines(
    orig_body(_PS, "A00_initialization_初始化"),
    ["拍照工位允许", "拍照工位机器人", "拍照工位放硅胶板完成", "scrape_WaitConfirm", "scrape_IsLast"]
).replace("Camera_scraper_initialization_OK:=TRUE;", "Camera_scraper_initialization_OK:=TRUE; bActionDone:=TRUE;")

PHOTO_ACTIONS = [
    ("A10_init_初始化", _PH_INIT),
    ("A31_cam_移轴335", """(* 刮板X轴到放板/上料位 335 *)
刮板轴9XDATE.fAbsTarget:=335;
刮板轴9XDATE.xMoveAbs:=TRUE;
IF 刮板轴9XDATE.bAbMoveDone THEN
\t刮板轴9XDATE.xMoveAbs:=FALSE;
\tbActionDone:=TRUE;
END_IF
"""),
    ("A32_cam_定位", """(* 拍照定位气缸夹紧 (上位机已驱动机器人放板) *)
刮板拍照定位气缸自动:=TRUE;
bActionDone:=TRUE;
"""),
    ("A33_cam_下压", """(* 下压气缸压下 (上位机已驱动机器人放收集器) *)
刮板拍照下压气缸自动:=TRUE;
bActionDone:=TRUE;
"""),
    ("A34_cam_相机位", """(* 移到相机位 + 遮光下 (随后由上位机视觉控制器拍照) *)
CASE 拍照step OF
\t0:
\t\tIF 刮板拍照遮光气缸上位 THEN
\t\t\t拍照轴8YDATE.fAbsTarget:=420;
\t\t\t拍照轴8YDATE.xMoveAbs:=TRUE;
\t\t\t拍照step:=10;
\t\tEND_IF
\t10:
\t\tIF 拍照轴8YDATE.bAbMoveDone THEN
\t\t\t拍照轴8YDATE.xMoveAbs:=FALSE;
\t\t\t刮板拍照遮光气缸自动:=TRUE;
\t\t\t拍照step:=20;
\t\tEND_IF
\t20:
\t\tIF 刮板拍照遮光气缸下位 THEN
\t\t\t拍照step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A35_cam_回零", """(* 遮光上 + 拍照Y轴回零 (上位机已拍照完成) *)
CASE 拍照step OF
\t0:
\t\t刮板拍照遮光气缸自动:=FALSE;
\t\t拍照step:=10;
\t10:
\t\tIF 刮板拍照遮光气缸上位 THEN
\t\t\t拍照轴8YDATE.fAbsTarget:=0;
\t\t\t拍照轴8YDATE.xMoveAbs:=TRUE;
\t\t\t拍照step:=20;
\t\tEND_IF
\t20:
\t\tIF 拍照轴8YDATE.bAbMoveDone THEN
\t\t\t拍照轴8YDATE.xMoveAbs:=FALSE;
\t\t\t拍照step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A40_scrape_刮取", """(* 刮取单 pass: 上位机已写 g_pass_z 等 g_* 参数; 触发 PLC_CNC 跑一刀
   CNC启动/CNC完成 为 PLC 内部 SoftMotion 触发线 (保留); 多 pass 由上位机循环调用本动作 *)
CASE 刮板收集step OF
\t0:
\t\t刮板拍照真空自动:=TRUE;
\t\tCNC启动:=TRUE;
\t\t刮板收集step:=10;
\t10:
\t\tIF CNC完成 THEN
\t\t\tCNC启动:=FALSE;
\t\t\t刮板收集step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A41_scrape_收尾", """(* 刮取收尾: 关定位/真空/电机, 旋转气缸翻转倒料 *)
刮板拍照定位气缸自动:=FALSE;
刮板拍照真空自动:=FALSE;
刮板拍照无刷电机自动:=FALSE;
刮板拍照旋转气缸自动:=TRUE;
bActionDone:=TRUE;
"""),
    ("A51_取料松压", """(* 取料: 松下压气缸 (上位机已驱动机器人到收集器夹持位) *)
刮板拍照下压气缸自动:=FALSE;
IF 刮板拍照下压气缸上位 THEN
\tbActionDone:=TRUE;
END_IF
"""),
    ("A52_取料停旋转", """(* 取料收尾: 停旋转气缸 (上位机已驱动机器人退出取走收集器) *)
刮板拍照旋转气缸自动:=FALSE;
bActionDone:=TRUE;
"""),
]
PHOTO_CODES = [(10, "A10_init_初始化"), (31, "A31_cam_移轴335"), (32, "A32_cam_定位"),
               (33, "A33_cam_下压"), (34, "A34_cam_相机位"), (35, "A35_cam_回零"),
               (40, "A40_scrape_刮取"), (41, "A41_scrape_收尾"),
               (51, "A51_取料松压"), (52, "A52_取料停旋转")]
PHOTO_RESETS = ["初始化step", "拍照step", "刮板收集step"]


# ═════════════════════════════════════════════════════════════════════════
# FeedLift 工位内容 (玻璃上下料伺服; 第5通道; 由 A10_上下料伺服流程 解构)
#   11 上料升轴取料位 / 12 上料降轴让位 / 21 下料到放废料位 / 22 下料埋料
#   注: jog/光电/报警逻辑忠实自原伺服流程, 删机器人握手; 实机需谨慎复核 (玻璃误动作风险)
# ═════════════════════════════════════════════════════════════════════════
FEEDLIFT_LOCALS = [
    ("上料step", ("simple", "INT")), ("下料step", ("simple", "INT")),
    ("bActionDone", ("simple", "BOOL")), ("bActionError", ("simple", "BOOL")),
    ("L2_StartTrig", ("derived", "R_TRIG")),
]
FEEDLIFT_ACTIONS = [
    ("A11_feed_raise", """(* 上料: jog 上料Z1 升至取料光电 (上位机随后驱动机器人吸料); 无玻璃则报错交上位机 *)
CASE 上料step OF
\t0:
\t\tIF 玻璃上料轴1ZDATE.bHomed AND 玻璃升降接近开关1 AND 上料进料传感器 AND NOT Alarm.0 THEN
\t\t\t上料step:=1;
\t\tEND_IF
\t1:
\t\tIF 玻璃上料轴1ZDATE.fActPos>=510.0 AND 玻璃升降光电开关1 AND NOT 玻璃升降接近开关1 THEN
\t\t\tZ1JOG_pos:=FALSE;
\t\t\tAlarm.0:=TRUE;                       (* 上料机构无玻璃 *)
\t\t\t上料step:=0;
\t\t\tFeedLift_L2_ErrorCode:=301;
\t\t\tbActionError:=TRUE;
\t\tELSIF NOT 玻璃升降光电开关1 AND 玻璃上料轴1ZDATE.fActPos<514 THEN
\t\t\tZ1JOG_pos:=TRUE;
\t\tELSE
\t\t\tZ1JOG_pos:=FALSE;
\t\t\t上料step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A12_feed_lower", """(* 上料: 机器人吸住玻璃后, Z1 相对下降 5mm 让位 *)
CASE 上料step OF
\t0:
\t\t玻璃上料轴1ZDATE.fRelTarget:=-5.0;
\t\t玻璃上料轴1ZDATE.xMoveRel:=TRUE;
\t\t上料step:=10;
\t10:
\t\tIF 玻璃上料轴1ZDATE.bReMoveDone THEN
\t\t\t玻璃上料轴1ZDATE.xMoveRel:=FALSE;
\t\t\t上料step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A21_unload_ready", """(* 下料: jog 下料Z2 到放废料位 (上位机随后驱动机器人放废料) *)
CASE 下料step OF
\t0:
\t\tIF 玻璃上料轴2ZDATE.bHomed AND 下料出料传感器 AND NOT Alarm.1 THEN
\t\t\t下料step:=1;
\t\tEND_IF
\t1:
\t\tIF NOT 玻璃升降光电开关2 AND 玻璃上料轴2ZDATE.fActPos<510 THEN
\t\t\tZ2JOG_POS:=TRUE;
\t\tELSE
\t\t\tZ2JOG_POS:=FALSE;
\t\t\t下料step:=10;
\t\tEND_IF
\t10:
\t\tIF 玻璃升降光电开关2 THEN
\t\t\tZ2JOG_NEG:=TRUE;
\t\t\t下料step:=15;
\t\tEND_IF
\t15:
\t\tIF NOT 玻璃升降光电开关2 THEN
\t\t\tZ2JOG_NEG:=FALSE;
\t\t\t下料step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
    ("A22_unload_bury", """(* 下料: 机器人放废料后, jog Z2 下埋至光电消失 *)
CASE 下料step OF
\t0:
\t\tIF 玻璃升降光电开关2 AND 玻璃升降接近开关2 THEN
\t\t\tZ2JOG_NEG:=TRUE;
\t\t\t下料step:=10;
\t\tEND_IF
\t10:
\t\tIF NOT 玻璃升降光电开关2 THEN
\t\t\tZ2JOG_NEG:=FALSE;
\t\t\t下料step:=0;
\t\t\tbActionDone:=TRUE;
\t\tEND_IF
END_CASE
"""),
]
FEEDLIFT_CODES = [(11, "A11_feed_raise"), (12, "A12_feed_lower"),
                  (21, "A21_unload_ready"), (22, "A22_unload_bury")]
FEEDLIFT_RESETS = ["上料step", "下料step"]


# 工位规格表 (全 5 通道)
STATIONS = [
    dict(prefix="Collect", pou="Collect_L2", locals=COLLECT_LOCALS,
         dispatch=COLLECT_DISPATCH, actions=COLLECT_ACTIONS),
    dict(prefix="Sampling", pou="Sampling_L2", locals=SAMPLING_LOCALS,
         dispatch=make_dispatch("Sampling", SAMPLING_CODES, SAMPLING_RESETS),
         actions=SAMPLING_ACTIONS),
    dict(prefix="Develop", pou="Develop_L2", locals=EXPAND_LOCALS,
         dispatch=make_dispatch("Develop", EXPAND_CODES, EXPAND_RESETS, accept_extra=EXPAND_ACCEPT),
         actions=EXPAND_ACTIONS),
    dict(prefix="PhotoScrape", pou="PhotoScrape_L2", locals=PHOTO_LOCALS,
         dispatch=make_dispatch("PhotoScrape", PHOTO_CODES, PHOTO_RESETS),
         actions=PHOTO_ACTIONS),
    dict(prefix="FeedLift", pou="FeedLift_L2", locals=FEEDLIFT_LOCALS,
         dispatch=make_dispatch("FeedLift", FEEDLIFT_CODES, FEEDLIFT_RESETS),
         actions=FEEDLIFT_ACTIONS),
]

# ═════════════════════════════════════════════════════════════════════════
# 剔除阶段: 删 POU/action + 改 body + 引用驱动删 GVL 变量 + manifest 收尾
# ═════════════════════════════════════════════════════════════════════════

# 待删 POU (连同其全部归属 action + manifest 条目)
DELETE_POUS = [
    "Robotic_Process_机器人流程", "FB_RB_Control",
    "Collection_process_收集流程", "Sample_point_sampling_上样点样",
    "Expand_process_展开流程", "Photo_scraper_拍照刮板",
]
# 待删独立 action (归属保留的 PLC_MainPRG)
DELETE_ACTIONS = [
    ("PLC_MainPRG", "A20_机器人"),
    ("PLC_MainPRG", "A10_上下料伺服流程"),
]
# PLC_MainPRG 正文调用改写 (旧 -> 新)
MAINPRG_REPLACERS = [
    ("A20_机器人();", ""),
    ("Robotic_Process_机器人流程();", ""),
    ("A10_上下料伺服流程 ();", "FeedLift_L2();"),
    ("Sample_point_sampling_上样点样();", "Sampling_L2();"),
    ("Collection_process_收集流程();", "Collect_L2();"),
    ("Expand_process_展开流程();", "Develop_L2();"),
    ("Photo_scraper_拍照刮板();", "PhotoScrape_L2();"),
]
# 急停 / 上下料 / 排液 中要剔除的跨执行体握手 substring (整行删除)
HANDSHAKE_SUBSTRS = [
    "收集工位允许", "收集工位机器人", "收集工位放收集", "收集工位放收集器到工位",
    "展开工位允许", "展开工位机器人", "展开工位取硅胶板完成",
    "拍照工位允许", "拍照工位机器人", "拍照工位放硅胶板完成",
    "上样点样允许", "上样点样放硅胶板完成",
    "升降上料", "升降下料",
    "Execute:=", "FunctionID:=", "ParameterList",
    "scrape_WaitConfirm", "机器人流程", "bParameterList1",
]
# 引用驱动删除候选 (仅当全工程 ST 体零引用才删)
GVL_DELETE_CANDIDATES = {
    "RB_Date": None,   # None = 全部变量
    "HMI_Date": ["机器人流程"],
    "Host_Computer": ["scrape_WaitConfirm", "scrape_Confirm"],
    "GVL": [
        "取工具完成", "取升降硅胶板step", "取升降硅胶板完成", "放点样硅胶板step", "放点样硅胶板完成",
        "取点样硅胶板step", "取点样硅胶板完成", "放展缸硅胶板完成", "放展缸硅胶板step",
        "取展缸硅胶板step", "取展缸硅胶板完成", "放拍照硅胶板完成", "放拍照硅胶板step",
        "取收集器组放暂存工位step", "取收集瓶组放暂存工位完成", "取暂存收集器放刮板位完成",
        "取暂存收集器放刮板位step", "取刮板收集器放到收集工位完成", "取刮板收集器放到收集工位step",
        "取暂存收集瓶放收集工位step", "取暂存收集瓶放收集工位完成", "取收集器放暂存工位完成",
        "取收集器放暂存工位step", "取刮板硅胶板放废料区step", "取刮板硅胶板放废料区完成",
        "取暂存收集器组放仓库完成", "取暂存收集器组放仓库step", "取收集器组放暂存工位完成",
        "取收集瓶组放暂存工位step", "取暂存收集瓶组放仓库完成", "取暂存收集瓶组放仓库step",
        "取收集瓶放暂存工位step", "取收集瓶放暂存工位完成", "取工具setp",
        "取拍照硅胶完step", "取拍照硅胶板完成",
        "收集瓶组站位符", "收集器组站位符", "刮板拍照工位站位符",
        "展开工位允许放硅胶板1", "bParameterList1",
    ],
}


def parent_pou_of_action(data_el):
    for ps in data_el.iter(Q("pathStructure")):
        if (ps.get("factoryName") or "").endswith("POUObjectFactory"):
            return ps.get("name")
    return None


def delete_pou(root, pou_name):
    pous = root.find(Q("types")).find(Q("pous"))
    ad = root.find(Q("addData"))
    # 1. <pou>
    for p in list(pous.findall(Q("pou"))):
        if p.get("name") == pou_name:
            pous.remove(p)
    # 2. 归属 action <data>
    for d in list(ad.findall(Q("data"))):
        if d.get("name") == "http://www.3s-software.com/plcopenxml/action" \
           and parent_pou_of_action(d) == pou_name:
            ad.remove(d)
    # 3. manifest <Object Name=pou_name> (含其 action 子节点)
    for o in list(root.iter(Q("Object"))):
        if o.get("Name") == pou_name:
            o.getparent().remove(o)


def delete_action(root, pou_name, action_name):
    ad = root.find(Q("addData"))
    for d in list(ad.findall(Q("data"))):
        if d.get("name") == "http://www.3s-software.com/plcopenxml/action":
            a = d.find(Q("action"))
            if a is not None and a.get("name") == action_name and parent_pou_of_action(d) == pou_name:
                ad.remove(d)
    # manifest: <Object Name=action_name> under <Object Name=pou_name>
    for po in root.iter(Q("Object")):
        if po.get("Name") == pou_name:
            for c in list(po):
                if c.get("Name") == action_name:
                    po.remove(c)


def get_xhtml(el):
    return el.find(f".//{{{XHTML}}}xhtml")


def edit_body(root, pou_name, action_name, transform):
    """对某 action 的 ST 正文施加 transform(text)->text. action_name=None 表示 POU 正文."""
    if action_name is None:
        for p in root.find(Q("types")).find(Q("pous")).findall(Q("pou")):
            if p.get("name") == pou_name:
                x = get_xhtml(p.find(Q("body"))); x.text = transform(x.text); return
    else:
        ad = root.find(Q("addData"))
        for d in ad.findall(Q("data")):
            if d.get("name") == "http://www.3s-software.com/plcopenxml/action":
                a = d.find(Q("action"))
                if a is not None and a.get("name") == action_name and parent_pou_of_action(d) == pou_name:
                    x = get_xhtml(a); x.text = transform(x.text); return
    raise KeyError(f"{pou_name}/{action_name}")


def remove_local_var(root, pou_name, var_name):
    for p in root.find(Q("types")).find(Q("pous")).findall(Q("pou")):
        if p.get("name") == pou_name:
            lv = p.find(Q("interface")).find(Q("localVars"))
            for v in list(lv.findall(Q("variable"))):
                if v.get("name") == var_name:
                    lv.remove(v)


def all_st_text(root):
    """汇总当前工程全部 POU 正文 + action 正文 (用于引用扫描)."""
    chunks = []
    for x in root.iter(f"{{{XHTML}}}xhtml"):
        if x.text:
            chunks.append(x.text)
    return "\n".join(chunks)


def _isid(c):
    return c != "" and (c.isalnum() or c == "_")   # isalnum 对中文亦为真


def is_referenced(var, text):
    """var 是否作为完整标识符出现 (前后均不接标识符字符, 避免命中更长名如 collect_Reset / ...板1)."""
    start = 0
    while True:
        i = text.find(var, start)
        if i < 0:
            return False
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(var)] if i + len(var) < len(text) else ""
        if (not _isid(before)) and (not _isid(after)):
            return True
        start = i + 1


def edit_a50(text):
    """A50 排液: 60->Done+99, 删机器人取板(65)段与末尾 bParameterList1 块."""
    for i in range(1, 9):
        text = text.replace(f"Tank_State[{i}] := 65;",
                            f"Tank_Drain_Done[{i}] := TRUE; Tank_State[{i}] := 99;")
    cut = text.find("//场景 6")
    if cut < 0:
        cut = text.find("ELSIF Tank_State[i] = 65")
    head = text[:cut].rstrip()
    return head + "\n\tEND_IF\nEND_FOR\n"



def delete_orphan_gvl_vars(root, candidates_map):
    """引用驱动删除: 仅当某 GVL 变量在全工程 ST 体零引用时才删除其声明.
    candidates_map: {gvl_name: [var,...] | None}. 返回 (deleted, kept)."""
    text = all_st_text(root)
    ad = root.find(Q("addData"))
    gvls = {}
    for d in ad.findall(Q("data")):
        if d.get("name") == "http://www.3s-software.com/plcopenxml/globalvars":
            gv = d.find(Q("globalVars"))
            gvls[gv.get("name")] = gv
    deleted, kept = [], []
    for gvlname, varlist in candidates_map.items():
        gv = gvls.get(gvlname)
        if gv is None:
            continue
        if varlist is None:
            varlist = [v.get("name") for v in gv.findall(Q("variable"))]
        for vn in varlist:
            if is_referenced(vn, text):
                kept.append(gvlname + "." + vn)
                continue
            for v in list(gv.findall(Q("variable"))):
                if v.get("name") == vn:
                    gv.remove(v); deleted.append(gvlname + "." + vn)
    return deleted, kept


def main():
    tree = etree.parse(SRC)
    root = tree.getroot()
    pous = root.find(Q("types")).find(Q("pous"))
    ad = root.find(Q("addData"))
    host_gv = None
    for d in ad.findall(Q("data")):
        if d.get("name") == "http://www.3s-software.com/plcopenxml/globalvars":
            gv = d.find(Q("globalVars"))
            if gv is not None and gv.get("name") == "Host_Computer":
                host_gv = gv
    assert host_gv is not None, "Host_Computer GVL not found"
    ps_data = None
    for d in ad.findall(Q("data")):
        if d.get("name") == "http://www.3s-software.com/plcopenxml/projectstructure":
            ps_data = d
    app_obj = None
    for o in ps_data.iter(Q("Object")):
        if o.get("Name") == "Application" and o.get("ObjectId") == APP["og"]:
            app_obj = o; break
    assert app_obj is not None, "Application manifest object not found"

    # 1. additive: 50_action folder + 5 dispatchers + atomics + L2 nodes
    folder50 = etree.SubElement(app_obj, Q("Folder")); folder50.set("Name", "50_action")
    existing_vars = {v.get("name") for v in host_gv.findall(Q("variable"))}
    added_vars = []
    for st in STATIONS:
        for nm, ts in l2_nodes(st["prefix"]):
            if nm in existing_vars:
                continue
            add_var(host_gv, nm, ts); existing_vars.add(nm); added_vars.append(nm)
        pous.append(make_pou(st["pou"], st["locals"], st["dispatch"]))
        pou_obj = etree.SubElement(folder50, Q("Object"))
        pou_obj.set("Name", st["pou"]); pou_obj.set("ObjectId", guid("pou:" + st["pou"]))
        for aname, abody in st["actions"]:
            ad.append(make_action_data(st["pou"], aname, abody))
            ao = etree.SubElement(pou_obj, Q("Object"))
            ao.set("Name", aname); ao.set("ObjectId", guid("action:" + st["pou"] + "/" + aname))

    # 2. body edits (before deletion so handshake refs are removed)
    edit_body(root, "PLC_MainPRG", "A30_急停", lambda t: strip_lines(t, HANDSHAKE_SUBSTRS + GVL_DELETE_CANDIDATES["GVL"]))
    edit_body(root, "Develop_TankDrain", "A50_Expand_liquid_discharge_排液", edit_a50)
    def fix_mainprg(t):
        for old, new in MAINPRG_REPLACERS:
            t = t.replace(old, new)
        return t
    edit_body(root, "PLC_MainPRG", None, fix_mainprg)
    remove_local_var(root, "PLC_MainPRG", "RB_Control_0")

    # 3. delete robot/camera/old-station POUs + standalone actions
    for pou, act in DELETE_ACTIONS:
        delete_action(root, pou, act)
    for pou in DELETE_POUS:
        delete_pou(root, pou)

    # 4. reference-driven GVL var deletion
    deleted, kept = delete_orphan_gvl_vars(root, GVL_DELETE_CANDIDATES)

    tree.write(DST, xml_declaration=True, encoding="utf-8")
    print("written", DST)
    print("L2 nodes added: %d | GVL vars deleted: %d | candidates kept(still-ref): %d" % (len(added_vars), len(deleted), len(kept)))
    if kept:
        print("  KEPT(still referenced):", kept)

    # 5. verify
    r2 = etree.parse(DST).getroot()
    pous2 = list(r2.iter(Q("pou")))
    acts2 = [d for d in r2.find(Q("addData")).findall(Q("data"))
             if d.get("name") == "http://www.3s-software.com/plcopenxml/action"]
    oids = [e.text for e in r2.iter(Q("ObjectId"))]
    mids = [o.get("ObjectId") for o in r2.iter(Q("Object"))]
    print("POUs: %d | actions: %d" % (len(pous2), len(acts2)))
    print("ObjectId: %d | manifest Object: %d | bijection: %s" % (len(oids), len(mids), sorted(oids) == sorted(mids)))
    txt = all_st_text(r2)
    dangling_vars = [d.split(".", 1)[1] for d in deleted if is_referenced(d.split(".", 1)[1], txt)]
    print("dangling deleted-var refs (count %d):" % len(dangling_vars), dangling_vars[:12])
    callnames = DELETE_POUS + [a for _, a in DELETE_ACTIONS]
    dangling_calls = [nm for nm in callnames if (nm + "()") in txt or (nm + " ()") in txt]
    print("dangling deleted POU/action calls:", dangling_calls)


if __name__ == "__main__":
    main()
