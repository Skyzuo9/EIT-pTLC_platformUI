"""离线核对完整下载握手、启动诊断和轴门控的 CODESYS 符号产物。"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


_XML = (
    Path(__file__).resolve().parent.parent
    / "plc"
    / "20260702.Device.Application.xml"
)
_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "tools"
    / "plc_startup_fix_20260721.mjs"
)


def _nodes(root: ET.Element) -> dict[str, ET.Element]:
    return {
        node.attrib["name"]: node
        for node in root.findall(".//{*}Node")
        if "name" in node.attrib
    }


def _user_type(root: ET.Element, name: str) -> dict[str, ET.Element]:
    element = root.find(f".//{{*}}TypeUserDef[@name='{name}']")
    assert element is not None, name
    return {
        child.attrib["iecname"]: child
        for child in element.findall("./{*}UserDefElement")
    }


def test_deploy_startup_symbol_types_and_access() -> None:
    root = ET.parse(_XML).getroot()
    nodes = _nodes(root)

    pc_owned = {
        "PLC_Deploy_RequestSeq": "T_DINT",
        "PLC_Deploy_CommitSeq": "T_DINT",
        "PLC_Deploy_Start": "T_BOOL",
        "PLC_Deploy_Reset": "T_BOOL",
    }
    plc_owned = {
        "PLC_Deploy_State": "T_INT",
        "PLC_Deploy_AcceptedSeq": "T_DINT",
        "PLC_Deploy_ErrorCode": "T_INT",
        "PLC_Startup_State": "T_INT",
        "PLC_Startup_ErrorCode": "T_INT",
        "PLC_Ready": "T_BOOL",
        "PLC_Startup_AlarmInhibit": "T_BOOL",
        "PLC_HandWheel_Active": "T_BOOL",
        "PLC_Axis_CommOperational": "T_ARRAY__1__11__OF_BOOL",
        "PLC_Axis_FaultSource": "T_ARRAY__1__11__OF_INT",
        "PLC_Axis_FaultCode": "T_ARRAY__1__11__OF_DINT",
    }

    for name, type_name in pc_owned.items():
        assert nodes[name].attrib == {
            "name": name,
            "type": type_name,
            "access": "ReadWrite",
        }
    for name, type_name in plc_owned.items():
        assert nodes[name].attrib == {
            "name": name,
            "type": type_name,
            "access": "Read",
        }


def test_axis_arrays_are_exactly_one_through_eleven() -> None:
    root = ET.parse(_XML).getroot()
    expected = {
        "T_ARRAY__1__11__OF_BOOL": ("11", "T_BOOL"),
        "T_ARRAY__1__11__OF_INT": ("22", "T_INT"),
        "T_ARRAY__1__11__OF_DINT": ("44", "T_DINT"),
    }
    for name, (size, base_type) in expected.items():
        array_type = root.find(f".//{{*}}TypeArray[@name='{name}']")
        assert array_type is not None
        assert array_type.attrib["size"] == size
        assert array_type.attrib["basetype"] == base_type
        dimension = array_type.find("./{*}ArrayDim")
        assert dimension is not None
        assert dimension.attrib == {"minrange": "1", "maxrange": "11"}


def test_servo_and_handwheel_function_blocks_export_safety_gates() -> None:
    root = ET.parse(_XML).getroot()
    servo = _user_type(root, "T_FB_SERVOAXIS")
    assert servo["xStartupMotionAllowed"].attrib["vartype"] == "VAR_INPUT"
    assert servo["bCommOperational"].attrib["vartype"] == "VAR_OUTPUT"
    assert servo["ClearFaultEdge"].attrib["type"] == "T_R_TRIG"
    assert servo["bNormalMotionAllowed"].attrib["vartype"] == "VAR"
    assert servo["bStartupMotionAllowed"].attrib["vartype"] == "VAR"

    handwheel = _user_type(root, "T_FB_HandWheel")
    assert handwheel["Enable"].attrib["vartype"] == "VAR_INPUT"
    assert handwheel["Active"].attrib["vartype"] == "VAR_OUTPUT"


def test_plc_migration_covers_non_l2_auxiliary_activity() -> None:
    """The binary project is compiled separately; keep its migration guards reviewable offline."""

    source = _MIGRATION.read_text(encoding="utf-8")

    assert "bAnyDeployCommandRequested" in source
    assert "bDeployCommandsArmed" in source
    assert "bPumpCommandsArmed" in source
    assert "PLC_Ready AND ${deployStateAllowsAux}" in source
    assert "((NOT PLC_Ready) OR ${maintenanceActive})" in source
    assert "...cylinderCommandSymbols" in source
    assert "大真空泵站位[${index}]" in source
    assert "bAnyPumpCommandRequested" in source
    assert "Tank_Drain_Enable[${index}]" in source
    assert "Tank_State[${index}]=50" in source
    assert "Tank_State[${index}]=55" in source
    assert "Tank_State[${index}]=56" in source

    # State 30 is a busy rejection, so the action that caused it must continue.
    assert "((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))" in source

    # SAFE_TO_DOWNLOAD may only be exposed once drive power is gone and every
    # axis is confirmed stationary; State 20 remains a maintained invariant.
    assert "ELSIF NOT bAnyAxisEnabled AND NOT bAnyAxisBusy THEN" in source
    assert "ELSIF bAnyAxisEnabled OR bAnyAxisBusy OR PLC_HandWheel_Active" in source

    # A maintenance-time request is frozen and cannot be replayed after unlock
    # until the underlying request bits have all returned FALSE.
    assert "const tankDrainAction = await read('A50_Expand_liquid_discharge_排液')" in source
    assert "IF bAnyDrainDeployRequest THEN" in source
    assert "ELSIF bDeployCommandsArmed AND ((Tank_State[i] = 0) OR (Tank_State[i] = 40)) THEN" in source

    # Pump/tank guards keep scanning outside RUN. L2 dispatchers do so only in
    # IDLE, allowing a fresh Start to be rejected without advancing an existing
    # RUNNING FSM when Ready is lost in STOP mode.
    assert "const alwaysSafetyCalls = [" in source
    assert "const idleOnlyL2SafetyCalls = [" in source
    assert "const cyclicSafetyCalls = [" in source
    assert "'PLC_Pump_泵管理();'" in source
    assert "'Develop_TankDrain();'" in source
    for l2_name in (
        "Pump_L2", "StagingA_L2", "Rail_L2", "FeedLift_L2",
        "Sampling_L2", "Collect_L2", "Develop_L2", "PhotoScrape_L2",
    ):
        assert f"'{l2_name}();'" in source
    assert (
        "IF (MODE_State=EN_功能块状态.运行) OR NOT PLC_Ready "
        "OR ${maintenanceActive} THEN"
    ) in source
    assert "AND (${state}=0)) THEN" in source
    assert "['StagingA_L2();', 'Host_Computer.StagingA_L2_State']" in source


def test_retained_hmi_teach_requests_cannot_replay_after_startup() -> None:
    """Persistent HMI command arrays must be drained at boot and while motion is gated."""

    source = _MIGRATION.read_text(encoding="utf-8")
    teach_sources = (
        "HMI_打样瓶上料轴3Y",
        "HMI_点样轴6X",
        "HMI_点样轴7Y",
        "HMI_地轨轴11Y",
        "HMI_上样轴4X轴",
        "HMI_上样轴5Z轴",
    )
    for name in teach_sources:
        assert f"'{name}'" in source

    assert "const clearTeachCommands = hmiTeachSources.map" in source
    assert "${source}.execute[n] := FALSE" in source
    assert "${source}.write[n] := FALSE" in source
    assert "FOR n:=1 TO 10 DO" in source
    assert "${clearTeachCommands}" in source

    assert "nTeachClear : INT;" in source
    assert "FOR nTeachClear:=1 TO 10 DO" in source
    assert "${source}.execute[nTeachClear] := FALSE" in source
    assert "${source}.write[nTeachClear] := FALSE" in source
    assert "${initClearTeachCommands}" in source

    # The retained all-axis home bit is another motion source. It is cleared at
    # boot and during every blocked scan, and the manual edge/branch are gated.
    assert source.count("一键回原点 := FALSE;") >= 2
    assert "const manualHomeAllowed = 'PLC_Ready AND" in source
    assert "R_TRIG_HomeAll(CLK := 一键回原点 AND ${manualHomeAllowed}" in source
    assert "IF (一键回原点 AND ${manualHomeAllowed}) OR bAutoHomeReq THEN" in source

    # These four globals bypass ServoAxisDate and feed MC_Jog directly for 1Z/2Z.
    for name in ("Z1JOG_pos", "Z1JOG_neg", "Z2JOG_POS", "Z2JOG_NEG"):
        assert f"'{name}'" in source
    assert "const clearDirectJogCommands = directJogSources.map" in source
    assert "${clearDirectJogCommands}" in source
    assert source.count("Sampling_Servo_FreeMove := FALSE;") >= 2

    assert "IF PLC_Ready\n\\tAND ((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))" in source
    assert "\\tAND (MODE_State<>1) AND NOT 点样测试 THEN" in source
    assert "\\t位置示教();" in source
