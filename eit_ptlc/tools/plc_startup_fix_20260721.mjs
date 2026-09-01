/*
 * One-shot, assertion-heavy migration for the active 20260702.project.
 *
 * The script talks only to the existing PlcProgramService HTTP API.  It does
 * not parse or rewrite the binary .project file directly.  Every replacement
 * checks the current source shape first so a future project cannot be patched
 * accidentally.
 */

const API = process.env.PTLC_API || 'http://127.0.0.1:18080/api/plc'

async function json(url, init) {
  const response = await fetch(url, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${JSON.stringify(body)}`)
  }
  return body
}

const catalog = await json(`${API}/pous`)

function pathFor(name) {
  const matches = catalog.pous.filter((item) => item.name === name)
  if (matches.length !== 1) {
    throw new Error(`expected one POU named ${name}, found ${matches.length}`)
  }
  return matches[0].path
}

async function read(name) {
  const path = pathFor(name)
  return json(`${API}/pou?path=${encodeURIComponent(path)}`)
}

async function save(current, { declaration = current.declaration, implementation = current.implementation }) {
  return json(`${API}/pou`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path: current.path, declaration, implementation, save: true }),
  })
}

function appendBeforeEndVar(declaration, marker, block) {
  if (declaration.includes(marker)) return declaration
  const at = declaration.lastIndexOf('END_VAR')
  if (at < 0) throw new Error(`END_VAR not found while adding ${marker}`)
  return `${declaration.slice(0, at)}${block}\n${declaration.slice(at)}`
}

const host = await read('Host_Computer')
const hostBlock = `
\t// ===== PLC full-download maintenance handshake =====
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_RequestSeq : DINT;       // PC/HMI request sequence
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_CommitSeq : DINT;        // Host-only commit; matching seq moves safe state 20 to locked state 25
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_Start : BOOL;            // rising edge requests safe download state
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_Reset : BOOL;            // cancel/release prepared state
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_State : INT;             // 0 idle,10 preparing,20 safe,25 host committed,30 busy,40 error
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_AcceptedSeq : DINT;
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_ErrorCode : INT;         // 1=L2 busy,2=axis moving,3=aux output/pending command,5=comm,40=power timeout,41/42=safe invariant

\t// ===== deterministic PLC/EtherCAT/servo startup =====
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Startup_State : INT;            // 0 boot,10 bus,20 reset,30 power,40/41 5Z,50/51 4X,60 ready,90 error
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Startup_ErrorCode : INT;
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Ready : BOOL;
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Axis_CommOperational : ARRAY[1..11] OF BOOL;
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Axis_FaultSource : ARRAY[1..11] OF INT;
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Axis_FaultCode : ARRAY[1..11] OF DINT;
`
let hostDeclaration = appendBeforeEndVar(host.declaration, 'PLC_Deploy_RequestSeq', hostBlock)
hostDeclaration = hostDeclaration.replace(
  /PLC_Deploy_ErrorCode\s*:\s*INT;[^\r\n]*/,
  'PLC_Deploy_ErrorCode : INT;         // 1=L2 busy,2=axis moving,3=aux output/pending command,5=comm,40=power timeout,41/42=safe invariant',
)
hostDeclaration = appendBeforeEndVar(hostDeclaration, 'PLC_Deploy_CommitSeq', `
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Deploy_CommitSeq : DINT;
`)
hostDeclaration = appendBeforeEndVar(hostDeclaration, 'PLC_Startup_AlarmInhibit', `
\t{attribute 'symbol' := 'readwrite'}
\tPLC_Startup_AlarmInhibit : BOOL;   // TRUE while transient startup alarms must not enter HMI history
\t{attribute 'symbol' := 'readwrite'}
\tPLC_HandWheel_Active : BOOL;       // any slave remains geared/in transition
`)
const plcOwnedSymbols = [
  'PLC_Deploy_State', 'PLC_Deploy_AcceptedSeq', 'PLC_Deploy_ErrorCode',
  'PLC_Startup_State', 'PLC_Startup_ErrorCode', 'PLC_Ready',
  'PLC_Startup_AlarmInhibit', 'PLC_HandWheel_Active',
  'PLC_Axis_CommOperational', 'PLC_Axis_FaultSource', 'PLC_Axis_FaultCode',
]
for (const symbolName of plcOwnedSymbols) {
  const symbolPattern = new RegExp(
    "\\{attribute 'symbol' := '(?:read|readwrite)'\\}(\\r?\\n\\s*" + symbolName + "\\s*:)",
  )
  if (!symbolPattern.test(hostDeclaration)) {
    throw new Error(`Host_Computer symbol declaration not found: ${symbolName}`)
  }
  hostDeclaration = hostDeclaration.replace(
    symbolPattern,
    "{attribute 'symbol' := 'read'}$1",
  )
}
await save(host, { declaration: hostDeclaration })

const axisFb = await read('FB_SERVOAXIS')
const axisDeclaration = `FUNCTION_BLOCK FB_SERVOAXIS
VAR_IN_OUT
\tAXIS: AXIS_REF_SM3;
END_VAR
VAR_INPUT
\txEnable    : BOOL;
\txStartupMotionAllowed : BOOL;       // TRUE only for the one axis owned by the startup homing FSM
\txHome      : BOOL;
\txJogPos    : BOOL;
\txJogNeg    : BOOL;
\txStop      : BOOL;
\txMoveAbs   : BOOL;
\txMoveRel   : BOOL;
\tXReset     : BOOL;
\tfAbsTarget : LREAL := 0.0;
\tfRelTarget : LREAL := 0.0;
\tfVelocity  : LREAL := 100.0;
\tfAcc       : LREAL := 1000.0;
\tfDec       : LREAL := 1000.0;
\tfJogVel    : LREAL := 50.0;
END_VAR
VAR_OUTPUT
\tbEnabled    : BOOL;
\tbHomed      : BOOL;
\tbBusy       : BOOL;
\tbError      : BOOL;
\tiErrorCode  : DINT;
\tiFaultSource : INT;                 // 0 none,1 axis,2 power,3 home,4 abs,5 rel,6 halt,7 jog,8 reset,9 comm
\tbCommOperational : BOOL;
\tfActPos     : LREAL;
\tfActVel     : LREAL;
\tbAbMoveDone : BOOL;
\tbReMoveDone : BOOL;
END_VAR
VAR
\tMC_Power : MC_Power;
\tMC_Home : MC_Home;
\tMC_Halt : MC_Halt;
\tMC_MoveAbsolute : MC_MoveAbsolute;
\tMC_MoveRelative : MC_MoveRelative;
\tMC_Jog : MC_Jog;
\tMC_Reset : MC_Reset;
\tCheckCommunication : SMC_CheckAxisCommunication;
\tResetAxisEdge : R_TRIG;
\tClearFaultEdge : R_TRIG;
\tbPowerAllowed : BOOL;
\tbNormalMotionAllowed : BOOL;
\tbStartupMotionAllowed : BOOL;
\tbFaultLatched : BOOL;
\tiLatchedSource : INT;
\tdiLatchedCode : DINT;
END_VAR`

const axisImplementation = `// Always execute the communication diagnostic and all PLCopen FB instances cyclically.
CheckCommunication(Axis := AXIS, bEnable := TRUE);
bCommOperational := CheckCommunication.bValid AND CheckCommunication.bOperational;

// Power is allowed only after the startup FSM reached POWER and never while a download is prepared.
bPowerAllowed := bCommOperational
\tAND (PLC_Startup_State >= 30) AND (PLC_Startup_State <> 90)
\tAND ((PLC_Deploy_State = 0) OR (PLC_Deploy_State = 30));
bNormalMotionAllowed := bCommOperational AND bEnabled AND PLC_Ready
\tAND ((PLC_Deploy_State = 0) OR (PLC_Deploy_State = 30));
bStartupMotionAllowed := bCommOperational AND bEnabled AND xStartupMotionAllowed
\tAND (PLC_Startup_State >= 40) AND (PLC_Startup_State <= 51)
\tAND ((PLC_Deploy_State = 0) OR (PLC_Deploy_State = 30));

MC_Power(
\tAxis := AXIS,
\tEnable := bPowerAllowed,
\tbRegulatorOn := xEnable AND bPowerAllowed,
\tbDriveStart := xEnable AND bPowerAllowed,
\tStatus => bEnabled);

MC_Home(
\tAxis := AXIS,
\tExecute := xHome AND (bNormalMotionAllowed OR bStartupMotionAllowed),
\tDone => bHomed);

// MC_Reset is edge-triggered and is issued only for a communicating ErrorStop axis.
ResetAxisEdge(CLK := XReset AND bCommOperational AND (AXIS.nAxisState = 1));
ClearFaultEdge(CLK := XReset AND bCommOperational AND (AXIS.nAxisState <> 1));
MC_Reset(Axis := AXIS, Execute := ResetAxisEdge.Q);

MC_Jog(
\tAxis := AXIS,
\tJogForward := xJogPos AND bNormalMotionAllowed,
\tJogBackward := xJogNeg AND bNormalMotionAllowed,
\tVelocity := fJogVel,
\tAcceleration := fAcc,
\tDeceleration := fDec);

// Halt remains available whenever axis communication is valid.
MC_Halt(
\tAxis := AXIS,
\tExecute := xStop AND bCommOperational,
\tDeceleration := fDec);

MC_MoveAbsolute(
\tAxis := AXIS,
\tExecute := xMoveAbs AND bNormalMotionAllowed,
\tPosition := fAbsTarget,
\tVelocity := fVelocity,
\tAcceleration := fAcc,
\tDeceleration := fDec,
\tDone => bAbMoveDone);

MC_MoveRelative(
\tAxis := AXIS,
\tExecute := xMoveRel AND (bNormalMotionAllowed OR bStartupMotionAllowed),
\tDistance := fRelTarget,
\tVelocity := fVelocity,
\tAcceleration := fAcc,
\tDeceleration := fDec,
\tDone => bReMoveDone);

fActPos := AXIS.fActPosition;
fActVel := AXIS.fActVelocity;
bBusy := MC_Power.Busy OR MC_Home.Busy OR MC_Halt.Busy OR MC_MoveAbsolute.Busy
\tOR MC_MoveRelative.Busy OR MC_Jog.Busy OR MC_Reset.Busy;

// Preserve the first real motion/drive fault. Communication loss is reported separately and never
// fanned out as eleven servo faults. Axis state 2 is Stopping and is deliberately not an error.
IF (MC_Reset.Done AND (AXIS.nAxisState <> 1)) OR ClearFaultEdge.Q THEN
\tbFaultLatched := FALSE;
\tiLatchedSource := 0;
\tdiLatchedCode := 0;
ELSIF NOT bFaultLatched AND bCommOperational THEN
\tIF MC_Power.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 2; diLatchedCode := MC_Power.ErrorID;
\tELSIF MC_Home.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 3; diLatchedCode := MC_Home.ErrorID;
\tELSIF MC_MoveAbsolute.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 4; diLatchedCode := MC_MoveAbsolute.ErrorID;
\tELSIF MC_MoveRelative.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 5; diLatchedCode := MC_MoveRelative.ErrorID;
\tELSIF MC_Halt.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 6; diLatchedCode := MC_Halt.ErrorID;
\tELSIF MC_Jog.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 7; diLatchedCode := MC_Jog.ErrorID;
\tELSIF MC_Reset.Error THEN
\t\tbFaultLatched := TRUE; iLatchedSource := 8; diLatchedCode := MC_Reset.ErrorID;
\tELSIF AXIS.nAxisState = 1 THEN
\t\tbFaultLatched := TRUE;
\t\tiLatchedSource := 1;
\t\t// Prefer the drive's original diagnostic value; keep 1 only as an explicit unknown fallback.
\t\tdiLatchedCode := AXIS.diDriverErrorCode;
\t\tIF diLatchedCode = 0 THEN diLatchedCode := 1; END_IF
\tEND_IF
END_IF

bError := bFaultLatched;
IF NOT bCommOperational THEN
\tiFaultSource := 9;
\tiErrorCode := WORD_TO_DINT(CheckCommunication.wComState);
ELSE
\tiFaultSource := iLatchedSource;
\tiErrorCode := diLatchedCode;
END_IF`
await save(axisFb, { declaration: axisDeclaration, implementation: axisImplementation })

const handwheelFb = await read('FB_HandWheel')
const handwheelDeclaration = `FUNCTION_BLOCK FB_HandWheel
VAR_IN_OUT
\tAxis_Spindle: AXIS_REF_SM3;
\tAXIS_1: AXIS_REF_SM3;
\tAXIS_2: AXIS_REF_SM3;
\tAXIS_3: AXIS_REF_SM3;
\tAXIS_4: AXIS_REF_SM3;
\tAXIS_5: AXIS_REF_SM3;
\tAXIS_6: AXIS_REF_SM3;
\tAXIS_7: AXIS_REF_SM3;
\tAXIS_8: AXIS_REF_SM3;
\tAXIS_9: AXIS_REF_SM3;
END_VAR
VAR_INPUT
\tEnable: BOOL;
\tSpeed_X1: BOOL;
\tSpeed_X10: BOOL;
\tSpeed_X100: BOOL;
\tReset: BOOL;
\tHandWheel_3Y: BOOL;
\tHandWheel_4X: BOOL;
\tHandWheel_5Z: BOOL;
\tHandWheel_6X: BOOL;
\tHandWheel_7Y: BOOL;
\tHandWheel_8Y: BOOL;
\tHandWheel_9X: BOOL;
\tHandWheel_10Z: BOOL;
\tHandWheel_11Y: BOOL;
END_VAR
VAR_OUTPUT
\txStop_1: BOOL;
\txStop_2: BOOL;
\txStop_3: BOOL;
\txStop_4: BOOL;
\txStop_5: BOOL;
\txStop_6: BOOL;
\txStop_7: BOOL;
\txStop_8: BOOL;
\txStop_9: BOOL;
\tActive: BOOL;
\tError: BOOL;
\tErrorID: WORD;
END_VAR
VAR
\tMC_GearIn_1: MC_GearIn;
\tMC_GearIn_2: MC_GearIn;
\tMC_GearIn_3: MC_GearIn;
\tMC_GearIn_4: MC_GearIn;
\tMC_GearIn_5: MC_GearIn;
\tMC_GearIn_6: MC_GearIn;
\tMC_GearIn_7: MC_GearIn;
\tMC_GearIn_8: MC_GearIn;
\tMC_GearIn_9: MC_GearIn;
\tMC_GearOut_1: MC_GearOut;
\tMC_GearOut_2: MC_GearOut;
\tMC_GearOut_3: MC_GearOut;
\tMC_GearOut_4: MC_GearOut;
\tMC_GearOut_5: MC_GearOut;
\tMC_GearOut_6: MC_GearOut;
\tMC_GearOut_7: MC_GearOut;
\tMC_GearOut_8: MC_GearOut;
\tMC_GearOut_9: MC_GearOut;
\tR_TRIG_1: R_TRIG;
\tR_TRIG_2: R_TRIG;
\tR_TRIG_3: R_TRIG;
\tR_TRIG_5: R_TRIG;
\tR_TRIG_6: R_TRIG;
\tR_TRIG_7: R_TRIG;
\tR_TRIG_8: R_TRIG;
\tR_TRIG_9: R_TRIG;
\tR_TRIG_10: R_TRIG;
\tR_TRIG_11: R_TRIG;
\tR_TRIG_12: R_TRIG;
\tR_TRIG_13: R_TRIG;
\tF_TRIG_1: F_TRIG;
\tF_TRIG_2: F_TRIG;
\tF_TRIG_3: F_TRIG;
\tF_TRIG_4: F_TRIG;
\tF_TRIG_5: F_TRIG;
\tF_TRIG_6: F_TRIG;
\tF_TRIG_7: F_TRIG;
\tF_TRIG_8: F_TRIG;
\tF_TRIG_9: F_TRIG;
\tiDenominator: UDINT := 100;
\tiMolecule: INT := 1;
END_VAR`

const handwheelSelectors = [
  'HandWheel_3Y', 'HandWheel_4X', 'HandWheel_5Z', 'HandWheel_6X', 'HandWheel_7Y',
  'HandWheel_8Y', 'HandWheel_9X', 'HandWheel_10Z', 'HandWheel_11Y',
]
const handwheelBlocks = handwheelSelectors.map((selector, index) => {
  const n = index + 1
  const trigger = index + 5
  return `
R_TRIG_${trigger}(CLK := Enable AND ${selector});
F_TRIG_${n}(CLK := Enable AND ${selector});
MC_GearIn_${n}(
\tMaster := Axis_Spindle,
\tSlave := AXIS_${n},
\tExecute := Enable AND (R_TRIG_${trigger}.Q
\t\tOR ((R_TRIG_1.Q OR R_TRIG_2.Q OR R_TRIG_3.Q) AND ${selector})),
\tRatioNumerator := iMolecule,
\tRatioDenominator := iDenominator,
\tAcceleration := 500,
\tDeceleration := 800);
MC_GearOut_${n}(
\tSlave := AXIS_${n},
\tExecute := (F_TRIG_${n}.Q OR NOT Enable) AND MC_GearIn_${n}.InGear,
\tDone => xStop_${n});
`
}).join('')
const handwheelErrors = handwheelSelectors.map((_selector, index) => {
  const n = index + 1
  return `MC_GearIn_${n}.Error OR MC_GearOut_${n}.Error`
}).join(' OR ')
const handwheelActive = handwheelSelectors.map((_selector, index) => {
  const n = index + 1
  return `MC_GearIn_${n}.InGear OR MC_GearIn_${n}.Busy OR MC_GearOut_${n}.Busy`
}).join(' OR ')
const handwheelErrorPriority = handwheelSelectors.map((_selector, index) => {
  const n = index + 1
  const keyword = index === 0 ? 'IF' : 'ELSIF'
  return `${keyword} MC_GearIn_${n}.Error THEN ErrorID := MC_GearIn_${n}.ErrorID;
ELSIF MC_GearOut_${n}.Error THEN ErrorID := MC_GearOut_${n}.ErrorID;`
}).join('\n')
const handwheelImplementation = `// Every PLCopen gearing FB is called cyclically. Dropping Enable forces GearOut.
IF Speed_X1 THEN
\tiDenominator := 100;
ELSIF Speed_X10 THEN
\tiDenominator := 10;
ELSIF Speed_X100 THEN
\tiDenominator := 1;
END_IF
R_TRIG_1(CLK := Enable AND Speed_X1);
R_TRIG_2(CLK := Enable AND Speed_X10);
R_TRIG_3(CLK := Enable AND Speed_X100);
${handwheelBlocks}
Active := ${handwheelActive};
Error := ${handwheelErrors};
ErrorID := 0;
${handwheelErrorPriority}
END_IF`
await save(handwheelFb, { declaration: handwheelDeclaration, implementation: handwheelImplementation })

const handwheelProgram = await read('PLC_HandWheel_手轮')
const handwheelProgramDeclaration = `PROGRAM PLC_HandWheel_手轮
VAR
\tFB_HandWheel_0: FB_HandWheel;
\tHC_Counter_0: HC_Counter;
\tbHandWheelAllowed: BOOL;
END_VAR`
const handwheelProgramImplementation = `SMC_FreeEncoder.fActPosition := Encoder.fActPosition;

bHandWheelAllowed := 急停 AND (MODE_State<>1) AND NOT 手自动 AND PLC_Ready
\tAND ((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))
\tAND PLC_Axis_CommOperational[3] AND PLC_Axis_CommOperational[4]
\tAND PLC_Axis_CommOperational[5] AND PLC_Axis_CommOperational[6]
\tAND PLC_Axis_CommOperational[7] AND PLC_Axis_CommOperational[8]
\tAND PLC_Axis_CommOperational[9] AND PLC_Axis_CommOperational[10]
\tAND PLC_Axis_CommOperational[11];

IF NOT bHandWheelAllowed THEN
\tHMI_HandWheel_3Y := FALSE; HMI_HandWheel_4X := FALSE; HMI_HandWheel_5Z := FALSE;
\tHMI_HandWheel_6X := FALSE; HMI_HandWheel_7Y := FALSE; HMI_HandWheel_8Y := FALSE;
\tHMI_HandWheel_9X := FALSE; HMI_HandWheel_10Z := FALSE; HMI_HandWheel_11Y := FALSE;
END_IF

HC_Counter_0(Axis := Encoder, Enable := bHandWheelAllowed);
FB_HandWheel_0(
\tAxis_Spindle := SMC_FreeEncoder,
\tAXIS_1 := 打样瓶上料轴3Y,
\tAXIS_2 := 上样轴4X轴,
\tAXIS_3 := 上样轴5Z轴,
\tAXIS_4 := 点样轴6X,
\tAXIS_5 := 点样轴7Y,
\tAXIS_6 := 拍照轴8Y,
\tAXIS_7 := 刮板轴9X,
\tAXIS_8 := 刮板轴10Z,
\tAXIS_9 := 地轨轴11Y,
\tEnable := bHandWheelAllowed,
\tSpeed_X1 := 倍率X1,
\tSpeed_X10 := 倍率X10,
\tSpeed_X100 := 倍率X100,
\tReset := 复位,
\tHandWheel_3Y := HMI_HandWheel_3Y,
\tHandWheel_4X := HMI_HandWheel_4X,
\tHandWheel_5Z := HMI_HandWheel_5Z,
\tHandWheel_6X := HMI_HandWheel_6X,
\tHandWheel_7Y := HMI_HandWheel_7Y,
\tHandWheel_8Y := HMI_HandWheel_8Y,
\tHandWheel_9X := HMI_HandWheel_9X,
\tHandWheel_10Z := HMI_HandWheel_10Z,
\tHandWheel_11Y := HMI_HandWheel_11Y,
\txStop_1 => 打样瓶上料轴3YDATE.xStop,
\txStop_2 => 上样轴4X轴DATE.xStop,
\txStop_3 => 上样轴5Z轴DATE.xStop,
\txStop_4 => 点样轴6XDATE.xStop,
\txStop_5 => 点样轴7YDATE.xStop,
\txStop_6 => 拍照轴8YDATE.xStop,
\txStop_7 => 刮板轴9XDATE.xStop,
\txStop_8 => 刮板轴10ZDATE.xStop,
\txStop_9 => 地轨轴11YDATE.xStop);
PLC_HandWheel_Active := FB_HandWheel_0.Active;`
await save(handwheelProgram, {
  declaration: handwheelProgramDeclaration,
  implementation: handwheelProgramImplementation,
})

const calls = await read('伺服调用')
let homedFixes = 0
const homedPattern = /([\u3400-\u9fffA-Za-z0-9_]+DATE)\.bHomed\s+S=\s*([^;\r\n]+);\s*\r?\nIF\s+\1\.xHome\s+THEN\s*\r?\n\s*\1\.bHomed\s*:=\s*FALSE;\s*\r?\nEND_IF/g
let callsImplementation = calls.implementation.replace(homedPattern, (_all, date, done) => {
  homedFixes += 1
  return `IF ${done.trim()} THEN\n\t${date}.xHome := FALSE;\n\t${date}.bHomed := TRUE;\nEND_IF`
})
// 4X/5Z additionally clear their reference when the safety chain drops.  Keep that behavior,
// but do not clear Homed merely because the home command is still high.
const samplingHomePattern = /([\u3400-\u9fffA-Za-z0-9_]+DATE)\.bHomed\s+S=\s*([^;\r\n]+);\s*\r?\n(\s*%QB\d+\s*:=\s*27;[^\r\n]*\r?\n)IF\s+NOT\s+\u6025\u505c\s+OR\s+\1\.xHome\s+THEN\s*\r?\n\s*\1\.bHomed\s*:=\s*FALSE;\s*\r?\nEND_IF/g
callsImplementation = callsImplementation.replace(samplingHomePattern, (_all, date, done, modeLine) => {
  homedFixes += 1
  return `IF ${done.trim()} THEN\n\t${date}.xHome := FALSE;\n\t${date}.bHomed := TRUE;\nEND_IF\n${modeLine}IF NOT \u6025\u505c THEN\n\t${date}.bHomed := FALSE;\nEND_IF`
})
if (homedFixes === 0 && !calls.implementation.includes('.bHomed S=')) {
  // Already migrated by an earlier, successful run.
  homedFixes = 11
}
if (homedFixes !== 11) {
  throw new Error(`expected to fix 11 homing latches, fixed ${homedFixes}`)
}

// Startup motion is intentionally granted to one incremental axis at a time.
// Normal Jog/MoveAbsolute inputs remain blocked until PLC_Ready inside FB_SERVOAXIS.
for (let axisIndex = 0; axisIndex < 11; axisIndex += 1) {
  const allowExpression = axisIndex === 9
    ? '((PLC_Startup_State=50) OR (PLC_Startup_State=51))'
    : axisIndex === 10
      ? '((PLC_Startup_State=40) OR (PLC_Startup_State=41))'
      : 'FALSE'
  const blockPattern = new RegExp(
    `FB_SERVOAXIS_${axisIndex}\\([\\s\\S]*?(?=\\nFB_SERVOAXIS_|$)`,
  )
  const match = callsImplementation.match(blockPattern)
  if (!match) throw new Error(`FB_SERVOAXIS_${axisIndex} invocation not found`)
  let block = match[0]
  if (/\n\s*xStartupMotionAllowed\s*:=/.test(block)) {
    block = block.replace(
      /\n\s*xStartupMotionAllowed\s*:=[^,\r\n]*,/,
      `\n\txStartupMotionAllowed:= ${allowExpression},`,
    )
  } else {
    const withInput = block.replace(
      /(\n\s*xEnable\s*:=[^\r\n]*\r?\n)/,
      `$1\txStartupMotionAllowed:= ${allowExpression}, // startup axis ownership\n`,
    )
    if (withInput === block) throw new Error(`FB_SERVOAXIS_${axisIndex} xEnable input not found`)
    block = withInput
  }

  // The legacy HMI binds several per-axis DATE.bError fields directly.  Keep
  // the FB instance as the unmasked source for the startup FSM/diagnostics,
  // while suppressing only the public HMI-facing fields during a normal boot.
  // This guarantees a silent successful startup even when the HMI project is
  // unavailable and cannot be changed alongside this PLC project.
  const publicFaultMarker = `// startup alarm visibility axis ${axisIndex}`
  if (!block.includes(publicFaultMarker)) {
    const errorMatch = block.match(/\n\s*bError\s*=>\s*([^,\r\n]+?)\.bError\s*,[^\r\n]*/)
    const codeMatch = block.match(/\n\s*iErrorCode\s*=>\s*([^,\r\n]+?)\.iErrorCode\s*,[^\r\n]*/)
    if (!errorMatch || !codeMatch || errorMatch[1].trim() !== codeMatch[1].trim()) {
      throw new Error(`FB_SERVOAXIS_${axisIndex} public fault mappings not found or mismatched`)
    }
    const axisDate = errorMatch[1].trim()
    block = block.replace(errorMatch[0], '').replace(codeMatch[0], '')
    const visibility = `${publicFaultMarker}
${axisDate}.bError := FB_SERVOAXIS_${axisIndex}.bError AND NOT PLC_Startup_AlarmInhibit;
IF PLC_Startup_AlarmInhibit THEN
\t${axisDate}.iErrorCode := 0;
ELSE
\t${axisDate}.iErrorCode := FB_SERVOAXIS_${axisIndex}.iErrorCode;
END_IF
`
    const withVisibility = block.replace(/(\);[^\r\n]*(?:\r?\n|$))/, `$1${visibility}`)
    if (withVisibility === block) {
      throw new Error(`FB_SERVOAXIS_${axisIndex} call terminator not found`)
    }
    block = withVisibility
  }
  callsImplementation = callsImplementation.replace(blockPattern, block)
}
if ((callsImplementation.match(/xStartupMotionAllowed\s*:=/g) || []).length !== 11) {
  throw new Error('expected exactly 11 startup-motion input bindings')
}
await save(calls, { implementation: callsImplementation })

const manualHomeAllowed = 'PLC_Ready AND ((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))'
const homeAction = await read('伺服一键回原点')
const homeImplementation = `// Manual request homes all axes; startup request homes only incremental 5Z then 4X.
R_TRIG_HomeAll(CLK := 一键回原点 AND ${manualHomeAllowed} AND MODE_State<>1 AND NOT ManualAuto);
R_TRIG_Home45(CLK := bAutoHomeReq);

IF R_TRIG_HomeAll.Q THEN
\t玻璃上料轴1ZDATE.bHomed := FALSE; 玻璃上料轴1ZDATE.xHome := TRUE;
\t玻璃上料轴2ZDATE.bHomed := FALSE; 玻璃上料轴2ZDATE.xHome := TRUE;
\t刮板轴10ZDATE.bHomed := FALSE; 刮板轴10ZDATE.xHome := TRUE;
\t点样轴6XDATE.bHomed := FALSE; 点样轴6XDATE.xHome := TRUE;
\t点样轴7YDATE.bHomed := FALSE; 点样轴7YDATE.xHome := TRUE;
\t地轨轴11YDATE.bHomed := FALSE; 地轨轴11YDATE.xHome := TRUE;
\tHOME_1STEP := 1;
\tHOME_2STEP := 1;
\tbAutoHomeOnly45 := FALSE;
END_IF

IF R_TRIG_Home45.Q THEN
\t上样轴5Z轴DATE.bHomed := FALSE;
\t上样轴4X轴DATE.bHomed := FALSE;
\tHOME_2STEP := 1;
\tbAutoHomeOnly45 := TRUE;
END_IF

IF (一键回原点 AND ${manualHomeAllowed}) OR bAutoHomeReq THEN
\t// Scraper/photo sequence is manual-only: 10Z, then 9X and 8Y.
\tCASE HOME_1STEP OF
\t\t1:
\t\t\tIF 刮板轴10ZDATE.bHomed THEN
\t\t\t\t刮板轴9XDATE.bHomed := FALSE; 刮板轴9XDATE.xHome := TRUE;
\t\t\t\t拍照轴8YDATE.bHomed := FALSE; 拍照轴8YDATE.xHome := TRUE;
\t\t\t\tHOME_1STEP := 2;
\t\t\tEND_IF
\t\t2:
\t\t\tIF 刮板轴10ZDATE.bHomed AND 刮板轴9XDATE.bHomed AND 拍照轴8YDATE.bHomed THEN
\t\t\t\tHOME_1STEP := 0;
\t\t\tEND_IF
\tEND_CASE

\t// Sampling sequence: 5Z retreat -> 5Z home -> 4X retreat -> 4X home.
\tCASE HOME_2STEP OF
\t\t1:
\t\t\t上样轴5Z轴DATE.xHome := FALSE;
\t\t\t上样轴4X轴DATE.xHome := FALSE;
\t\t\t上样轴5Z轴DATE.xMoveRel := FALSE;
\t\t\t上样轴4X轴DATE.xMoveRel := FALSE;
\t\t\t// Positive retreat is the established mechanical direction.  Do not
\t\t\t// arm it when the positive hardware/software limit says that direction
\t\t\t// is unavailable; the startup FSM reports the specific step failure.
\t\t\tIF NOT b5ZRetreatUnsafe THEN
\t\t\t\tHOME_2STEP := 2;
\t\t\tEND_IF
\t\t2:
\t\t\t上样轴5Z轴DATE.fRelTarget := 10.0;
\t\t\t上样轴5Z轴DATE.fVelocity := 5.0;
\t\t\t上样轴5Z轴DATE.xMoveRel := TRUE;
\t\t\tHOME_2STEP := 3;
\t\t3:
\t\t\t上样轴5Z轴DATE.fRelTarget := 10.0;
\t\t\t上样轴5Z轴DATE.fVelocity := 5.0;
\t\t\t上样轴5Z轴DATE.xMoveRel := TRUE;
\t\t\tIF 上样轴5Z轴DATE.bReMoveDone THEN
\t\t\t\t上样轴5Z轴DATE.xMoveRel := FALSE;
\t\t\t\t上样轴5Z轴DATE.bHomed := FALSE;
\t\t\t\t上样轴5Z轴DATE.xHome := TRUE;
\t\t\t\tHOME_2STEP := 4;
\t\t\tEND_IF
\t\t4:
\t\t\t上样轴5Z轴DATE.xHome := TRUE;
\t\t\tIF 上样轴5Z轴DATE.bHomed THEN
\t\t\t\t上样轴5Z轴DATE.xHome := FALSE;
\t\t\t\tIF NOT bAutoHomeOnly45 THEN
\t\t\t\t\t打样瓶上料轴3YDATE.bHomed := FALSE;
\t\t\t\t\t打样瓶上料轴3YDATE.xHome := TRUE;
\t\t\t\tEND_IF
\t\t\t\tIF (上样轴5Z轴DATE.fActPos < 3) AND NOT b4XRetreatUnsafe THEN
\t\t\t\t\t上样轴4X轴DATE.fRelTarget := 10.0;
\t\t\t\t\t上样轴4X轴DATE.fVelocity := 5.0;
\t\t\t\t\t上样轴4X轴DATE.xMoveRel := TRUE;
\t\t\t\t\tHOME_2STEP := 5;
\t\t\t\tEND_IF
\t\t\tEND_IF
\t\t5:
\t\t\t上样轴4X轴DATE.fRelTarget := 10.0;
\t\t\t上样轴4X轴DATE.fVelocity := 5.0;
\t\t\t上样轴4X轴DATE.xMoveRel := TRUE;
\t\t\tIF 上样轴4X轴DATE.bReMoveDone THEN
\t\t\t\t上样轴4X轴DATE.xMoveRel := FALSE;
\t\t\t\t上样轴4X轴DATE.bHomed := FALSE;
\t\t\t\t上样轴4X轴DATE.xHome := TRUE;
\t\t\t\tHOME_2STEP := 6;
\t\t\tEND_IF
\t\t6:
\t\t\t上样轴4X轴DATE.xHome := TRUE;
\t\t\tIF (bAutoHomeOnly45 OR 打样瓶上料轴3YDATE.bHomed) AND 上样轴4X轴DATE.bHomed THEN
\t\t\t\t上样轴4X轴DATE.xHome := FALSE;
\t\t\t\tHOME_2STEP := 0;
\t\t\tEND_IF
\tEND_CASE
END_IF

IF 玻璃上料轴1ZDATE.bHomed AND 玻璃上料轴2ZDATE.bHomed AND 点样轴6XDATE.bHomed
\tAND 点样轴7YDATE.bHomed AND 地轨轴11YDATE.bHomed AND 刮板轴10ZDATE.bHomed
\tAND 刮板轴9XDATE.bHomed AND 上样轴5Z轴DATE.bHomed AND 上样轴4X轴DATE.bHomed
\tAND 拍照轴8YDATE.bHomed AND 打样瓶上料轴3YDATE.bHomed THEN
\t一键回原点 := FALSE;
END_IF`
await save(homeAction, { implementation: homeImplementation })

// Legacy HMI/manual actuator paths bypass the L2 dispatchers.  Keep every
// cylinder FB cyclic, but gate both manual and automatic commands once a real
// download preparation has been accepted.  State 30 is only a busy rejection
// and must not interrupt the action that caused the rejection.
const deployStateAllowsAux = '((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))'
const auxAllowed = `PLC_Ready AND ${deployStateAllowsAux}`
const maintenanceActive = '((PLC_Deploy_State<>0) AND (PLC_Deploy_State<>30))'
const auxRearmBlocked = `((NOT PLC_Ready) OR ${maintenanceActive})`
const cylinderProgram = await read('PLC_Cyinder_气缸动作')
let cylinderImplementation = cylinderProgram.implementation
// Remove an earlier migration prelude before rebuilding it from the live POU.
cylinderImplementation = cylinderImplementation.replace(
  /^\/\/ PLC deploy auxiliary-actuator gate BEGIN\r?\n[\s\S]*?^\/\/ PLC deploy auxiliary-actuator gate END\r?\n/m,
  '',
)
cylinderImplementation = cylinderImplementation.replace(
  /^\/\/ PLC deploy auxiliary-actuator gate\r?\n/,
  '',
)

function unwrapCylinderGate(expression) {
  let value = expression.trim()
  const knownPrefixes = [
    `${auxAllowed} AND bDeployCommandsArmed AND (`,
    `${deployStateAllowsAux} AND bDeployCommandsArmed AND (`,
    `${deployStateAllowsAux} AND (`,
  ]
  for (const prefix of knownPrefixes) {
    if (value.startsWith(prefix) && value.endsWith(')')) {
      value = value.slice(prefix.length, -1).trim()
      break
    }
  }
  return value
}

let manualGateCount = 0
let autoGateCount = 0
const rawCylinderCommands = []
cylinderImplementation = cylinderImplementation.replace(
  /(x(?:Manual|Auto)Extend\s*:=\s*)([^,\r\n]+)(,)/g,
  (_all, prefix, expression, suffix) => {
    const raw = unwrapCylinderGate(expression)
    if (!raw) throw new Error(`empty cylinder command at ${prefix}`)
    if (prefix.startsWith('xManual')) manualGateCount += 1
    else autoGateCount += 1
    rawCylinderCommands.push(raw)
    return `${prefix}${auxAllowed} AND bDeployCommandsArmed AND (${raw})${suffix}`
  },
)
if (manualGateCount < 40 || manualGateCount !== autoGateCount) {
  throw new Error(`unexpected cylinder command count manual=${manualGateCount} auto=${autoGateCount}`)
}
const cylinderCommandSymbols = [...new Set(
  rawCylinderCommands.flatMap((expression) =>
    [...expression.matchAll(/[\p{L}\p{N}_]+(?:手动|自动)/gu)].map((match) => match[0])),
)]
if (cylinderCommandSymbols.length < 40) {
  throw new Error(`expected at least 40 raw cylinder commands, found ${cylinderCommandSymbols.length}`)
}
const anyCylinderCommand = cylinderCommandSymbols.join('\n\tOR ')
const cylinderGatePrelude = `// PLC deploy auxiliary-actuator gate BEGIN
bAnyDeployCommandRequested := ${anyCylinderCommand};
IF ${auxRearmBlocked} THEN
\tbDeployCommandsArmed := FALSE;
ELSIF NOT bAnyDeployCommandRequested THEN
\t// A command written while maintenance was active must first return FALSE;
\t// it is never replayed automatically when the maintenance lock is released.
\tbDeployCommandsArmed := TRUE;
END_IF
// PLC deploy auxiliary-actuator gate END
`
cylinderImplementation = `${cylinderGatePrelude}${cylinderImplementation}`
let cylinderDeclaration = appendBeforeEndVar(
  cylinderProgram.declaration,
  'bDeployCommandsArmed',
  `\tbDeployCommandsArmed: BOOL;\n\tbAnyDeployCommandRequested: BOOL;\n`,
)
const cylinderOutputs = [...new Set(
  [...cylinderImplementation.matchAll(/yValve1\s*=>\s*([^,\r\n]*)\s*,/g)]
    .map((match) => match[1].trim())
    .filter(Boolean),
)]
if (cylinderOutputs.length < 40) {
  throw new Error(`expected at least 40 auxiliary outputs, found ${cylinderOutputs.length}`)
}
await save(cylinderProgram, {
  declaration: cylinderDeclaration,
  implementation: cylinderImplementation,
})

// Develop_TankDrain is an autonomous non-L2 FSM.  It must not start or advance
// while a download is prepared, and a request written during maintenance must
// be cleared before the FSM can be armed again.
const tankDrain = await read('Develop_TankDrain')
const tankDrainDeclaration = appendBeforeEndVar(
  tankDrain.declaration,
  'bDeployCommandsArmed',
  `\tbDeployCommandsArmed: BOOL;\n\tbAnyDrainDeployRequest: BOOL;\n`,
)
await save(tankDrain, { declaration: tankDrainDeclaration })

const tankDrainAction = await read('A50_Expand_liquid_discharge_排液')
let tankDrainImplementation = tankDrainAction.implementation.replace(
  /^\/\/ PLC deploy tank-drain gate BEGIN\r?\n[\s\S]*?^\/\/ PLC deploy tank-drain gate END\r?\n/m,
  '',
)
const tankDrainGate = `// PLC deploy tank-drain gate BEGIN
bAnyDrainDeployRequest := Tank_Drain_Enable[1] OR Tank_Drain_Enable[2]
\tOR Tank_Drain_Enable[3] OR Tank_Drain_Enable[4]
\tOR Tank_Drain_Enable[5] OR Tank_Drain_Enable[6]
\tOR Tank_Drain_Enable[7] OR Tank_Drain_Enable[8];
IF ${auxRearmBlocked} THEN
\tbDeployCommandsArmed := FALSE;
\tFOR i := 1 TO 8 DO
\t\tDrainTimer[i](IN := FALSE, PT := T#0S);
\t\tCapTimer[i](IN := FALSE, PT := T#0S);
\t\tBlowTimer[i](IN := FALSE, PT := T#0S);
\t\tDryTimer[i](IN := FALSE, PT := T#0S);
\tEND_FOR
\tRETURN;
ELSIF NOT bDeployCommandsArmed THEN
\tIF bAnyDrainDeployRequest THEN
\t\t// Do not replay a request that appeared while maintenance was active.
\t\tFOR i := 1 TO 8 DO
\t\t\tDrainTimer[i](IN := FALSE, PT := T#0S);
\t\t\tCapTimer[i](IN := FALSE, PT := T#0S);
\t\t\tBlowTimer[i](IN := FALSE, PT := T#0S);
\t\t\tDryTimer[i](IN := FALSE, PT := T#0S);
\t\tEND_FOR
\t\tRETURN;
\tELSE
\t\tbDeployCommandsArmed := TRUE;
\tEND_IF
END_IF
// PLC deploy tank-drain gate END
`
const tankLoopMarker = '// ══ 主循环: 逐缸并行 FSM ══'
if (!tankDrainImplementation.includes(tankLoopMarker)) {
  throw new Error('Develop_TankDrain main-loop marker not found')
}
tankDrainImplementation = tankDrainImplementation.replace(
  tankLoopMarker,
  `${tankDrainGate}\n${tankLoopMarker}`,
)
if (!tankDrainImplementation.includes('ELSIF bDeployCommandsArmed AND ((Tank_State[i] = 0) OR (Tank_State[i] = 40)) THEN')) {
  const replaced = tankDrainImplementation.replace(
    'ELSIF (Tank_State[i] = 0) OR (Tank_State[i] = 40) THEN',
    'ELSIF bDeployCommandsArmed AND ((Tank_State[i] = 0) OR (Tank_State[i] = 40)) THEN',
  )
  if (replaced === tankDrainImplementation) {
    throw new Error('Develop_TankDrain start transition not found')
  }
  tankDrainImplementation = replaced
}
await save(tankDrainAction, { implementation: tankDrainImplementation })

const pumpManager = await read('PLC_Pump_泵管理')
const anyPumpCommand = Array.from(
  { length: 12 }, (_unused, index) => `大真空泵站位[${index}]`,
).join('\n\tOR ')
const pumpManagerDeclaration = appendBeforeEndVar(
  pumpManager.declaration,
  'bPumpCommandsArmed',
  `\tbPumpCommandsArmed: BOOL;\n\tbAnyPumpCommandRequested: BOOL;\n`,
)
const pumpManagerImplementation = `// PLC deploy vacuum gate
(* 真空泵集中管理: 大真空泵站位[] 引用计数总线 -> 大真空泵自动
   -> FB_cylinder cylinder_8 -> 大真空泵 %QX2.4。State30 是忙拒绝，已有真空继续；
   启动/维护期间写入的站位必须全部回 FALSE 后才重新装载，禁止解锁时补执行。 *)
bAnyPumpCommandRequested := ${anyPumpCommand};
IF ${auxRearmBlocked} THEN
\tbPumpCommandsArmed := FALSE;
ELSIF NOT bAnyPumpCommandRequested THEN
\tbPumpCommandsArmed := TRUE;
END_IF
大真空泵自动 := ${auxAllowed} AND bPumpCommandsArmed AND bAnyPumpCommandRequested;
`
await save(pumpManager, {
  declaration: pumpManagerDeclaration,
  implementation: pumpManagerImplementation,
})

const mainProgram = await read('PLC_MainPRG')
let mainImplementation = mainProgram.implementation
const mainDrainPrelude = `// PLC deploy legacy-command drain: prevent retained HMI tests/probes from resuming after reset.
IF ${auxRearmBlocked} THEN
\tpump_probe_trig := FALSE;
\tpump_probe_armed := FALSE;
\t点样测试 := FALSE;
\t打样伺服移动step := 0;
END_IF

`
if (mainImplementation.includes('// PLC deploy legacy-command drain')) {
  mainImplementation = mainImplementation.replace(
    /^\/\/ PLC deploy legacy-command drain:[\s\S]*?(?=\(\* ===== TEMP 泵响应探针)/,
    mainDrainPrelude,
  )
} else {
  mainImplementation = `${mainDrainPrelude}${mainImplementation}`
}
mainImplementation = mainImplementation.replace(
  /IF pump_probe_trig AND (?:PLC_Ready AND )?\(\(PLC_Deploy_State=0\) OR \(PLC_Deploy_State=30\)\) AND/,
  `IF pump_probe_trig AND ${auxAllowed} AND`,
)
mainImplementation = mainImplementation.replace(
  'IF pump_probe_trig AND %MW1300 = 0 AND NOT 泵站位符 THEN',
  `IF pump_probe_trig AND ${auxAllowed} AND %MW1300 = 0 AND NOT 泵站位符 THEN`,
)
mainImplementation = mainImplementation.replace(
  /IF 点样测试 AND (?:PLC_Ready AND )?\(\(PLC_Deploy_State=0\) OR \(PLC_Deploy_State=30\)\) THEN/,
  `IF 点样测试 AND ${auxAllowed} THEN`,
)
mainImplementation = mainImplementation.replace(
  'IF 点样测试 THEN',
  `IF 点样测试 AND ${auxAllowed} THEN`,
)
if (!mainImplementation.includes(`pump_probe_trig AND ${auxAllowed}`)
    || !mainImplementation.includes(`点样测试 AND ${auxAllowed}`)) {
  throw new Error('PLC_MainPRG legacy command gates not installed')
}

// Pump/tank guards must keep scanning throughout startup/maintenance so they can
// drain retained requests. L2 dispatchers may scan outside RUN only while IDLE:
// this lets their global gate reject a fresh Start without advancing a RUNNING
// state machine if Ready is lost while the machine is stopped.
const alwaysSafetyCalls = [
  'PLC_Pump_泵管理();',
  'Develop_TankDrain();',
]
const idleOnlyL2SafetyCalls = [
  ['Pump_L2();', 'Pump_L2_State'],
  ['StagingA_L2();', 'Host_Computer.StagingA_L2_State'],
  ['Rail_L2();', 'Rail_L2_State'],
  ['FeedLift_L2();', 'FeedLift_L2_State'],
  ['Sampling_L2();', 'Sampling_L2_State'],
  ['Collect_L2();', 'Collect_L2_State'],
  ['Develop_L2();', 'Develop_L2_State'],
  ['PhotoScrape_L2();', 'PhotoScrape_L2_State'],
]
const cyclicSafetyCalls = [
  ...alwaysSafetyCalls,
  ...idleOnlyL2SafetyCalls.map(([call]) => call),
]
mainImplementation = mainImplementation.replace(
  /^\/\/ PLC deploy\/startup cyclic safety sweep BEGIN\r?\n[\s\S]*?^\/\/ PLC deploy\/startup cyclic safety sweep END\r?\n/m,
  '',
)
const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
for (const call of cyclicSafetyCalls) {
  mainImplementation = mainImplementation.replace(
    new RegExp(`^[\\t ]*${escapeRegex(call)}[\\t ]*\\r?\\n`, 'gm'),
    '',
  )
}
const mainModeCase = 'CASE MODE_State OF'
if (!mainImplementation.includes(mainModeCase)) {
  throw new Error('PLC_MainPRG MODE_State CASE marker not found')
}
const cyclicSafetySweep = `// PLC deploy/startup cyclic safety sweep BEGIN
IF (MODE_State=EN_功能块状态.运行) OR NOT PLC_Ready OR ${maintenanceActive} THEN
\t${alwaysSafetyCalls.join('\n\t')}
END_IF
${idleOnlyL2SafetyCalls.map(([call, state]) => `IF (MODE_State=EN_功能块状态.运行)
\tOR (((NOT PLC_Ready) OR ${maintenanceActive}) AND (${state}=0)) THEN
\t${call}
END_IF`).join('\n')}
// PLC deploy/startup cyclic safety sweep END
`
mainImplementation = mainImplementation.replace(
  mainModeCase,
  `${cyclicSafetySweep}\n${mainModeCase}`,
)
for (const call of cyclicSafetyCalls) {
  const count = [...mainImplementation.matchAll(
    new RegExp(`^[\\t ]*${escapeRegex(call)}[\\t ]*$`, 'gm'),
  )].length
  if (count !== 1) throw new Error(`PLC_MainPRG expected one cyclic call ${call}, found ${count}`)
}
await save(mainProgram, { implementation: mainImplementation })

const pumpActivity = Array.from({ length: 12 }, (_unused, index) => `大真空泵站位[${index}]`)
const tankDrainActivity = Array.from({ length: 8 }, (_unused, offset) => {
  const index = offset + 1
  return [
    `Tank_Drain_Enable[${index}]`,
    `((Tank_State[${index}]=50) OR (Tank_State[${index}]=55) OR (Tank_State[${index}]=56))`,
  ]
}).flat()
const auxOutputExpression = [
  ...cylinderOutputs,
  ...cylinderCommandSymbols,
  ...pumpActivity,
  ...tankDrainActivity,
  '泵站位符',
  '(%MW1300<>0)',
].join('\n\tOR ')

const servo = await read('PLC_Servo_伺服')
let servoDeclaration = appendBeforeEndVar(servo.declaration, 'TON_BusStable', `
\tTON_BusStable: TON;
\tTON_BusTimeout: TON;
\tTON_ResetTimeout: TON;
\tTON_EnableTimeout: TON;
\tTON_RetreatTimeout: TON;
\tTON_HomeTimeout: TON;
\tTON_DeployPrepareTimeout: TON;
\tR_TRIG_DeployStart: R_TRIG;
\tbAllAxesComm: BOOL;
\tbAllAxesEnabled: BOOL;
\tbAnyAxisEnabled: BOOL;
\tbAnyAxisBusy: BOOL;
\tbAnyAxisErrorStop: BOOL;
\tbAnyAxisFault: BOOL;
\tbAnyL2Busy: BOOL;
\tbStartupResetIssued: BOOL;
\tbAutoHome45Done: BOOL;
`)
servoDeclaration = appendBeforeEndVar(
  servoDeclaration,
  'bAnyAxisFault',
  `\tbAnyAxisFault: BOOL;\n`,
)
servoDeclaration = appendBeforeEndVar(servoDeclaration, 'b5ZNegativeLimit', `
\t// CiA-402 0x60FD standard bits: 0 negative limit, 1 positive limit, 2 home switch.
\tb5ZNegativeLimit: BOOL;
\tb5ZPositiveLimit: BOOL;
\tb5ZHomeSwitch: BOOL;
\tb4XNegativeLimit: BOOL;
\tb4XPositiveLimit: BOOL;
\tb4XHomeSwitch: BOOL;
\tb5ZRetreatUnsafe: BOOL;
\tb4XRetreatUnsafe: BOOL;
\tbAnyAuxOutputActive: BOOL;
`)
// Keep this declaration independently idempotent.  On a project that was
// migrated by an earlier script revision the b5Z marker already exists, so
// the block above is intentionally skipped even though the auxiliary flag is
// still missing.
servoDeclaration = appendBeforeEndVar(
  servoDeclaration,
  'bAnyAuxOutputActive',
  `\tbAnyAuxOutputActive: BOOL;\n`,
)

const hmiTailAt = servo.implementation.indexOf('IF MODE_State=1 THEN')
if (hmiTailAt < 0) throw new Error('PLC_Servo HMI cleanup tail marker not found')
const hmiTail = servo.implementation.slice(hmiTailAt)

const axisCommandDates = [
  '玻璃上料轴1ZDATE', '玻璃上料轴2ZDATE', '打样瓶上料轴3YDATE',
  '点样轴6XDATE', '点样轴7YDATE', '拍照轴8YDATE', '刮板轴9XDATE',
  '刮板轴10ZDATE', '地轨轴11YDATE', '上样轴4X轴DATE', '上样轴5Z轴DATE',
]
const hmiTeachSources = [
  'HMI_打样瓶上料轴3Y',
  'HMI_点样轴6X',
  'HMI_点样轴7Y',
  'HMI_地轨轴11Y',
  'HMI_上样轴4X轴',
  'HMI_上样轴5Z轴',
]
const directJogSources = [
  'Z1JOG_pos',
  'Z1JOG_neg',
  'Z2JOG_POS',
  'Z2JOG_NEG',
]
const clearDirectJogCommands = directJogSources.map((source) =>
  `\t${source} := FALSE;`
).join('\n')
const clearTeachCommands = hmiTeachSources.map((source) =>
  `\t\t${source}.execute[n] := FALSE;\n\t\t${source}.write[n] := FALSE;`
).join('\n')
const initClearTeachCommands = hmiTeachSources.map((source) =>
  `\t${source}.execute[nTeachClear] := FALSE;\n\t${source}.write[nTeachClear] := FALSE;`
).join('\n')
const clearAxisCommands = axisCommandDates.map((date) =>
  `\t\t${date}.xHome := FALSE; ${date}.xJogPos := FALSE; ${date}.xJogNeg := FALSE;\n` +
  `\t\t${date}.xMoveAbs := FALSE; ${date}.xMoveRel := FALSE; ${date}.xStop := FALSE; ${date}.XReset := FALSE;`
).join('\n')
const clearAxisMotionCommands = axisCommandDates.map((date) =>
  `\t${date}.xHome := FALSE; ${date}.xJogPos := FALSE; ${date}.xJogNeg := FALSE;\n` +
  `\t${date}.xMoveAbs := FALSE; ${date}.xMoveRel := FALSE; ${date}.XReset := FALSE;`
).join('\n')
const stopAllAxes = axisCommandDates.map((date) => `\t\t${date}.xStop := TRUE;`).join('\n')

const servoImplementation = `// Compute alarm visibility before any axis/HMI-facing output.  Do not depend on
// initialization task ordering: the very first application scan must already be silent.
PLC_Startup_AlarmInhibit := ((NOT PLC_Ready) AND (PLC_Startup_State<>90))
\tOR ((PLC_Deploy_State<>0) AND (PLC_Deploy_State<>30));

// Execute axis FBs first; command inputs are internally gated by communication/startup/maintenance state.
伺服调用();

PLC_Axis_CommOperational[1] := FB_SERVOAXIS_0.bCommOperational;
PLC_Axis_CommOperational[2] := FB_SERVOAXIS_1.bCommOperational;
PLC_Axis_CommOperational[3] := FB_SERVOAXIS_2.bCommOperational;
PLC_Axis_CommOperational[4] := FB_SERVOAXIS_3.bCommOperational;
PLC_Axis_CommOperational[5] := FB_SERVOAXIS_4.bCommOperational;
PLC_Axis_CommOperational[6] := FB_SERVOAXIS_5.bCommOperational;
PLC_Axis_CommOperational[7] := FB_SERVOAXIS_6.bCommOperational;
PLC_Axis_CommOperational[8] := FB_SERVOAXIS_7.bCommOperational;
PLC_Axis_CommOperational[9] := FB_SERVOAXIS_8.bCommOperational;
PLC_Axis_CommOperational[10] := FB_SERVOAXIS_9.bCommOperational;
PLC_Axis_CommOperational[11] := FB_SERVOAXIS_10.bCommOperational;
PLC_Axis_FaultSource[1] := FB_SERVOAXIS_0.iFaultSource; PLC_Axis_FaultCode[1] := FB_SERVOAXIS_0.iErrorCode;
PLC_Axis_FaultSource[2] := FB_SERVOAXIS_1.iFaultSource; PLC_Axis_FaultCode[2] := FB_SERVOAXIS_1.iErrorCode;
PLC_Axis_FaultSource[3] := FB_SERVOAXIS_2.iFaultSource; PLC_Axis_FaultCode[3] := FB_SERVOAXIS_2.iErrorCode;
PLC_Axis_FaultSource[4] := FB_SERVOAXIS_3.iFaultSource; PLC_Axis_FaultCode[4] := FB_SERVOAXIS_3.iErrorCode;
PLC_Axis_FaultSource[5] := FB_SERVOAXIS_4.iFaultSource; PLC_Axis_FaultCode[5] := FB_SERVOAXIS_4.iErrorCode;
PLC_Axis_FaultSource[6] := FB_SERVOAXIS_5.iFaultSource; PLC_Axis_FaultCode[6] := FB_SERVOAXIS_5.iErrorCode;
PLC_Axis_FaultSource[7] := FB_SERVOAXIS_6.iFaultSource; PLC_Axis_FaultCode[7] := FB_SERVOAXIS_6.iErrorCode;
PLC_Axis_FaultSource[8] := FB_SERVOAXIS_7.iFaultSource; PLC_Axis_FaultCode[8] := FB_SERVOAXIS_7.iErrorCode;
PLC_Axis_FaultSource[9] := FB_SERVOAXIS_8.iFaultSource; PLC_Axis_FaultCode[9] := FB_SERVOAXIS_8.iErrorCode;
PLC_Axis_FaultSource[10] := FB_SERVOAXIS_9.iFaultSource; PLC_Axis_FaultCode[10] := FB_SERVOAXIS_9.iErrorCode;
PLC_Axis_FaultSource[11] := FB_SERVOAXIS_10.iFaultSource; PLC_Axis_FaultCode[11] := FB_SERVOAXIS_10.iErrorCode;

bAllAxesComm := PLC_Axis_CommOperational[1] AND PLC_Axis_CommOperational[2]
\tAND PLC_Axis_CommOperational[3] AND PLC_Axis_CommOperational[4]
\tAND PLC_Axis_CommOperational[5] AND PLC_Axis_CommOperational[6]
\tAND PLC_Axis_CommOperational[7] AND PLC_Axis_CommOperational[8]
\tAND PLC_Axis_CommOperational[9] AND PLC_Axis_CommOperational[10]
\tAND PLC_Axis_CommOperational[11];
bAllAxesEnabled := 玻璃上料轴1ZDATE.bEnabled AND 玻璃上料轴2ZDATE.bEnabled
\tAND 打样瓶上料轴3YDATE.bEnabled AND 点样轴6XDATE.bEnabled AND 点样轴7YDATE.bEnabled
\tAND 拍照轴8YDATE.bEnabled AND 刮板轴9XDATE.bEnabled AND 刮板轴10ZDATE.bEnabled
\tAND 地轨轴11YDATE.bEnabled AND 上样轴4X轴DATE.bEnabled AND 上样轴5Z轴DATE.bEnabled;
bAnyAxisEnabled := 玻璃上料轴1ZDATE.bEnabled OR 玻璃上料轴2ZDATE.bEnabled
\tOR 打样瓶上料轴3YDATE.bEnabled OR 点样轴6XDATE.bEnabled OR 点样轴7YDATE.bEnabled
\tOR 拍照轴8YDATE.bEnabled OR 刮板轴9XDATE.bEnabled OR 刮板轴10ZDATE.bEnabled
\tOR 地轨轴11YDATE.bEnabled OR 上样轴4X轴DATE.bEnabled OR 上样轴5Z轴DATE.bEnabled;
bAnyAxisBusy := 玻璃上料轴1ZDATE.bBusy OR 玻璃上料轴2ZDATE.bBusy
\tOR 打样瓶上料轴3YDATE.bBusy OR 点样轴6XDATE.bBusy OR 点样轴7YDATE.bBusy
\tOR 拍照轴8YDATE.bBusy OR 刮板轴9XDATE.bBusy OR 刮板轴10ZDATE.bBusy
\tOR 地轨轴11YDATE.bBusy OR 上样轴4X轴DATE.bBusy OR 上样轴5Z轴DATE.bBusy
\tOR (ABS(玻璃上料轴1ZDATE.fActVel)>0.01) OR (ABS(玻璃上料轴2ZDATE.fActVel)>0.01)
\tOR (ABS(打样瓶上料轴3YDATE.fActVel)>0.01) OR (ABS(点样轴6XDATE.fActVel)>0.01)
\tOR (ABS(点样轴7YDATE.fActVel)>0.01) OR (ABS(拍照轴8YDATE.fActVel)>0.01)
\tOR (ABS(刮板轴9XDATE.fActVel)>0.01) OR (ABS(刮板轴10ZDATE.fActVel)>0.01)
\tOR (ABS(地轨轴11YDATE.fActVel)>0.01) OR (ABS(上样轴4X轴DATE.fActVel)>0.01)
\tOR (ABS(上样轴5Z轴DATE.fActVel)>0.01) OR PLC_HandWheel_Active;
bAnyAxisErrorStop := (玻璃上料轴1Z.nAxisState=1) OR (玻璃上料轴2Z.nAxisState=1)
\tOR (打样瓶上料轴3Y.nAxisState=1) OR (点样轴6X.nAxisState=1) OR (点样轴7Y.nAxisState=1)
\tOR (拍照轴8Y.nAxisState=1) OR (刮板轴9X.nAxisState=1) OR (刮板轴10Z.nAxisState=1)
\tOR (地轨轴11Y.nAxisState=1) OR (上样轴4X轴.nAxisState=1) OR (上样轴5Z轴.nAxisState=1);
bAnyAxisFault := FB_SERVOAXIS_0.bError OR FB_SERVOAXIS_1.bError OR FB_SERVOAXIS_2.bError
\tOR FB_SERVOAXIS_3.bError OR FB_SERVOAXIS_4.bError OR FB_SERVOAXIS_5.bError
\tOR FB_SERVOAXIS_6.bError OR FB_SERVOAXIS_7.bError OR FB_SERVOAXIS_8.bError
\tOR FB_SERVOAXIS_9.bError OR FB_SERVOAXIS_10.bError;
b5ZNegativeLimit := (上样轴5Z轴.in.dwDigitalInputs AND DWORD#16#00000001) <> DWORD#0;
b5ZPositiveLimit := (上样轴5Z轴.in.dwDigitalInputs AND DWORD#16#00000002) <> DWORD#0;
b5ZHomeSwitch := (上样轴5Z轴.in.dwDigitalInputs AND DWORD#16#00000004) <> DWORD#0;
b4XNegativeLimit := (上样轴4X轴.in.dwDigitalInputs AND DWORD#16#00000001) <> DWORD#0;
b4XPositiveLimit := (上样轴4X轴.in.dwDigitalInputs AND DWORD#16#00000002) <> DWORD#0;
b4XHomeSwitch := (上样轴4X轴.in.dwDigitalInputs AND DWORD#16#00000004) <> DWORD#0;
b5ZRetreatUnsafe := b5ZPositiveLimit
\tOR (上样轴5Z轴.bSWLimitEnable
\t\tAND ((上样轴5Z轴DATE.fActPos + 10.0) > 上样轴5Z轴.fSWLimitPositive));
b4XRetreatUnsafe := b4XPositiveLimit
\tOR (上样轴4X轴.bSWLimitEnable
\t\tAND ((上样轴4X轴DATE.fActPos + 10.0) > 上样轴4X轴.fSWLimitPositive));
bAnyAuxOutputActive := ${auxOutputExpression};
bAnyL2Busy := (Collect_L2_State=10) OR (Sampling_L2_State=10) OR (Develop_L2_State=10)
\tOR (PhotoScrape_L2_State=10) OR (FeedLift_L2_State=10) OR (Pump_L2_State=10)
\tOR (Rail_L2_State=10) OR (StagingA_L2_State=10);

// Download prepare handshake. A busy machine is rejected; running actions are never interrupted.
R_TRIG_DeployStart(CLK := PLC_Deploy_Start);
TON_DeployPrepareTimeout(IN := PLC_Deploy_State=10, PT := T#10S);
IF PLC_Deploy_Reset AND NOT PLC_Deploy_Start
\tAND ((PLC_Deploy_State<>25) OR (PLC_Deploy_CommitSeq=0)) THEN
\tPLC_Deploy_State := 0;
\tPLC_Deploy_ErrorCode := 0;
ELSIF R_TRIG_DeployStart.Q AND PLC_Deploy_State=0 THEN
\tPLC_Deploy_AcceptedSeq := PLC_Deploy_RequestSeq;
\tIF bAnyL2Busy THEN
\t\tPLC_Deploy_State := 30; PLC_Deploy_ErrorCode := 1;
\tELSIF bAnyAxisBusy THEN
\t\tPLC_Deploy_State := 30; PLC_Deploy_ErrorCode := 2;
\tELSIF bAnyAuxOutputActive THEN
\t\tPLC_Deploy_State := 30; PLC_Deploy_ErrorCode := 3;
\tELSIF NOT PLC_Ready OR NOT bAllAxesComm THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 5;
\tELSE
${clearAxisCommands}
\t\tPLC_Deploy_ErrorCode := 0;
\t\tPLC_Deploy_State := 10;
\tEND_IF
ELSIF PLC_Deploy_State=10 THEN
\tIF (ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8) OR NOT bAllAxesComm THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 5;
\tELSIF bAnyAuxOutputActive THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 42;
\tELSIF NOT bAnyAxisEnabled AND NOT bAnyAxisBusy THEN
\t\tPLC_Deploy_State := 20;
\tELSIF TON_DeployPrepareTimeout.Q THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 40;
\tEND_IF
ELSIF PLC_Deploy_State=20 THEN
\t// READY_TO_DOWNLOAD is a maintained invariant, not a one-scan acknowledgement.
\tIF (ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8) OR NOT bAllAxesComm THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 5;
\tELSIF bAnyAxisEnabled OR bAnyAxisBusy OR PLC_HandWheel_Active OR bAnyAuxOutputActive THEN
\t\tPLC_Deploy_State := 40; PLC_Deploy_ErrorCode := 41;
\tELSIF PLC_Deploy_Start AND (PLC_Deploy_CommitSeq=PLC_Deploy_AcceptedSeq)
\t\tAND (PLC_Deploy_CommitSeq<>0) THEN
\t\tPLC_Deploy_State := 25;
\tEND_IF
ELSIF PLC_Deploy_State=25 THEN
\t// Host committed: normal HMI Start/Reset cancellation is ignored until a confirmed
\t// pre-download abort explicitly clears CommitSeq. Full download reinitialises the application.
\tIF (ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8) OR NOT bAllAxesComm THEN
\t\tPLC_Deploy_ErrorCode := 5;
\tELSIF bAnyAxisEnabled OR bAnyAxisBusy OR PLC_HandWheel_Active OR bAnyAuxOutputActive THEN
\t\tPLC_Deploy_ErrorCode := 41;
\tEND_IF
END_IF

// Startup timers. Safety-chain wait itself is intentionally untimed; no motion begins until it is healthy.
TON_BusStable(IN := PLC_Startup_State=10 AND ethercat1.m_master.m_uiactualnoslaves=13
\tAND (ethercat1.m_master._masterState=8) AND bAllAxesComm, PT := T#2S);
TON_BusTimeout(IN := PLC_Startup_State=10, PT := T#30S);
TON_ResetTimeout(IN := PLC_Startup_State=20 AND 急停 AND bStartupResetIssued
\tAND (bAnyAxisErrorStop OR bAnyAxisFault), PT := T#5S);
TON_EnableTimeout(IN := PLC_Startup_State=30 AND 急停 AND NOT bAllAxesEnabled, PT := T#10S);
TON_RetreatTimeout(IN := (PLC_Startup_State=40) OR (PLC_Startup_State=50), PT := T#15S);
TON_HomeTimeout(IN := (PLC_Startup_State=41) OR (PLC_Startup_State=51), PT := T#60S);

bSysReset := FALSE;
IF 复位 AND PLC_Startup_State=90 THEN
\tPLC_Startup_State := 0;
END_IF

// Once EtherCAT startup has succeeded, a later bus/axis-communication loss is always the root cause.
// It outranks reset, enable and homing timeouts and is never treated as eleven independent servo faults.
IF (PLC_Startup_State>=20) AND (PLC_Startup_State<=60)
\tAND ((ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8) OR NOT bAllAxesComm) THEN
\tPLC_Ready := FALSE;
\tPLC_Startup_ErrorCode := 100;
\tPLC_Startup_State := 90;
END_IF

CASE PLC_Startup_State OF
\t0:
\t\tPLC_Ready := FALSE;
\t\tPLC_Startup_ErrorCode := 0;
\t\tbStartupResetIssued := FALSE;
\t\tbAutoHomeReq := FALSE;
\t\tHOME_2STEP := 0;
\t\tPLC_HandWheel_Active := FALSE;
${clearAxisCommands}
\t\t上样轴5Z轴DATE.bHomed := FALSE;
\t\t上样轴4X轴DATE.bHomed := FALSE;
\t\tPLC_Startup_State := 10;
\t10:
\t\tPLC_Ready := FALSE;
\t\tIF TON_BusStable.Q THEN
\t\t\tbStartupResetIssued := FALSE;
\t\t\tPLC_Startup_State := 20;
\t\tELSIF TON_BusTimeout.Q THEN
\t\t\tIF (ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8) THEN
\t\t\t\tPLC_Startup_ErrorCode := 100;
\t\t\tELSE
\t\t\t\tPLC_Startup_ErrorCode := 200;
\t\t\tEND_IF
\t\t\tPLC_Startup_State := 90;
\t\tEND_IF
\t20:
\t\tIF 急停 THEN
\t\t\tIF NOT bStartupResetIssued THEN
\t\t\t\tbSysReset := TRUE;
\t\t\t\tbStartupResetIssued := TRUE;
\t\t\tELSIF NOT bAnyAxisErrorStop AND NOT bAnyAxisFault THEN
\t\t\t\tPLC_Startup_State := 30;
\t\t\tELSIF TON_ResetTimeout.Q THEN
\t\t\t\tPLC_Startup_ErrorCode := 300;
\t\t\t\tPLC_Startup_State := 90;
\t\t\tEND_IF
\t\tEND_IF
\t30:
\t\tIF 急停 THEN
\t\t\tIF bAnyAxisFault THEN
\t\t\t\tPLC_Startup_ErrorCode := 301;
\t\t\t\tPLC_Startup_State := 90;
\t\t\tELSIF bAllAxesEnabled THEN
\t\t\t\tbAutoHomeReq := TRUE;
\t\t\t\tPLC_Startup_State := 40;
\t\t\tELSIF TON_EnableTimeout.Q THEN
\t\t\t\tPLC_Startup_ErrorCode := 400;
\t\t\t\tPLC_Startup_State := 90;
\t\t\tEND_IF
\t\tEND_IF
\t40:
\t\tIF NOT 急停 THEN
\t\t\tPLC_Startup_ErrorCode := 900; PLC_Startup_State := 90;
\t\tELSIF b5ZRetreatUnsafe THEN
\t\t\tPLC_Startup_ErrorCode := 515; PLC_Startup_State := 90;
\t\tELSIF FB_SERVOAXIS_10.bError THEN
\t\t\tPLC_Startup_ErrorCode := 705; PLC_Startup_State := 90;
\t\tELSIF bAnyAxisFault THEN
\t\t\tPLC_Startup_ErrorCode := 301; PLC_Startup_State := 90;
\t\tELSIF HOME_2STEP=4 THEN
\t\t\tPLC_Startup_State := 41;
\t\tELSIF TON_RetreatTimeout.Q THEN
\t\t\tPLC_Startup_ErrorCode := 505; PLC_Startup_State := 90;
\t\tEND_IF
\t41:
\t\tIF NOT 急停 THEN
\t\t\tPLC_Startup_ErrorCode := 900; PLC_Startup_State := 90;
\t\tELSIF (HOME_2STEP=4) AND 上样轴5Z轴DATE.bHomed AND b4XRetreatUnsafe THEN
\t\t\tPLC_Startup_ErrorCode := 514; PLC_Startup_State := 90;
\t\tELSIF FB_SERVOAXIS_10.bError THEN
\t\t\tPLC_Startup_ErrorCode := 705; PLC_Startup_State := 90;
\t\tELSIF bAnyAxisFault THEN
\t\t\tPLC_Startup_ErrorCode := 301; PLC_Startup_State := 90;
\t\tELSIF HOME_2STEP=5 THEN
\t\t\tPLC_Startup_State := 50;
\t\tELSIF TON_HomeTimeout.Q THEN
\t\t\tPLC_Startup_ErrorCode := 605; PLC_Startup_State := 90;
\t\tEND_IF
\t50:
\t\tIF NOT 急停 THEN
\t\t\tPLC_Startup_ErrorCode := 900; PLC_Startup_State := 90;
\t\tELSIF b4XRetreatUnsafe THEN
\t\t\tPLC_Startup_ErrorCode := 514; PLC_Startup_State := 90;
\t\tELSIF FB_SERVOAXIS_9.bError THEN
\t\t\tPLC_Startup_ErrorCode := 704; PLC_Startup_State := 90;
\t\tELSIF bAnyAxisFault THEN
\t\t\tPLC_Startup_ErrorCode := 301; PLC_Startup_State := 90;
\t\tELSIF HOME_2STEP=6 THEN
\t\t\tPLC_Startup_State := 51;
\t\tELSIF TON_RetreatTimeout.Q THEN
\t\t\tPLC_Startup_ErrorCode := 504; PLC_Startup_State := 90;
\t\tEND_IF
\t51:
\t\tIF NOT 急停 THEN
\t\t\tPLC_Startup_ErrorCode := 900; PLC_Startup_State := 90;
\t\tELSIF FB_SERVOAXIS_9.bError THEN
\t\t\tPLC_Startup_ErrorCode := 704; PLC_Startup_State := 90;
\t\tELSIF bAnyAxisFault THEN
\t\t\tPLC_Startup_ErrorCode := 301; PLC_Startup_State := 90;
\t\tELSIF (HOME_2STEP=0) AND 上样轴5Z轴DATE.bHomed AND 上样轴4X轴DATE.bHomed THEN
\t\t\tPLC_Startup_State := 60;
\t\tELSIF TON_HomeTimeout.Q THEN
\t\t\tPLC_Startup_ErrorCode := 604; PLC_Startup_State := 90;
\t\tEND_IF
\t60:
\t\tIF NOT 急停 THEN
\t\t\tPLC_Ready := FALSE;
\t\t\tPLC_Startup_ErrorCode := 900;
\t\t\tPLC_Startup_State := 90;
\t\tELSIF bAnyAxisFault THEN
\t\t\tPLC_Ready := FALSE;
\t\t\tPLC_Startup_ErrorCode := 301;
\t\t\tPLC_Startup_State := 90;
\t\tELSE
\t\t\tPLC_Ready := bAllAxesEnabled
\t\t\t\tAND ((PLC_Deploy_State=0) OR (PLC_Deploy_State=30));
\t\tEND_IF
\t90:
\t\tPLC_Ready := FALSE;
\t\tbAutoHomeReq := FALSE;
\t\tHOME_2STEP := 0;
${stopAllAxes}
\t\t上样轴5Z轴DATE.xHome := FALSE;
\t\t上样轴5Z轴DATE.xMoveRel := FALSE;
\t\t上样轴4X轴DATE.xHome := FALSE;
\t\t上样轴4X轴DATE.xMoveRel := FALSE;
END_CASE

bSysResetDone := PLC_Startup_State>=30 AND PLC_Startup_State<>90;
bAutoHome45Done := 上样轴5Z轴DATE.bHomed AND 上样轴4X轴DATE.bHomed;
IF bAutoHomeReq AND bAutoHome45Done THEN
\tTON_AutoHomeReset(IN := TRUE, PT := T#1500MS);
\tbAutoHomeResetPulse := TRUE;
\tIF TON_AutoHomeReset.Q THEN
\t\tbAutoHomeReq := FALSE;
\t\tbAutoHomeResetPulse := FALSE;
\tEND_IF
ELSE
\tTON_AutoHomeReset(IN := FALSE, PT := T#1500MS);
\tbAutoHomeResetPulse := FALSE;
END_IF

// Keep the existing cylinder startup suppression window.
TON_CyInhibit(IN := ethercat1.m_master.m_uiactualnoslaves=13 AND NOT bCyInhibitDone, PT := T#15S);
bCyInhibit := (ethercat1.m_master.m_uiactualnoslaves=13) AND NOT bCyInhibitDone;
IF TON_CyInhibit.Q THEN bCyInhibitDone := TRUE; END_IF

// Refresh alarm visibility before every alarm outlet.  The same expression is also evaluated at
// the very top of this POU before the axis calls, so a fresh download cannot leak a first-scan pulse.
PLC_Startup_AlarmInhibit := ((NOT PLC_Ready) AND (PLC_Startup_State<>90))
\tOR ((PLC_Deploy_State<>0) AND (PLC_Deploy_State<>30));

// Successful initialization is silent. Only a terminal startup failure or a post-ready loss is alarmed.
IF PLC_Startup_AlarmInhibit THEN
\tECAT掉站报警 := FALSE;
ELSIF (PLC_Startup_State=90) AND (PLC_Startup_ErrorCode>=100) AND (PLC_Startup_ErrorCode<=200) THEN
\tECAT掉站报警 := TRUE;
ELSE
\tECAT掉站报警 := (ethercat1.m_master.m_uiactualnoslaves<>13) OR (ethercat1.m_master._masterState<>8);
END_IF

// Retained/HMI motion requests are continuously drained while startup or maintenance owns motion.
// The automatic homing POU below reasserts only the currently authorised 5Z/4X command.
IF (NOT PLC_Ready) OR ((PLC_Deploy_State<>0) AND (PLC_Deploy_State<>30)) THEN
${clearAxisMotionCommands}
${clearDirectJogCommands}
	Sampling_Servo_FreeMove := FALSE;
END_IF

// The six teaching arrays are RETAIN PERSISTENT command sources. Clearing only the
// derived axis command is insufficient because 位置示教 can recreate it later. Drain
// both execute/write sources every scan while startup or maintenance owns motion.
IF (NOT PLC_Ready) OR ((PLC_Deploy_State<>0) AND (PLC_Deploy_State<>30)) THEN
\tFOR n:=1 TO 10 DO
${clearTeachCommands}
\tEND_FOR
\t一键回原点 := FALSE;
END_IF

IF ((MODE_State<>1) AND PLC_Ready)
\tOR ((PLC_Startup_State>=40) AND (PLC_Startup_State<=51)) THEN
\t伺服一键回原点();
END_IF
IF PLC_Ready
\tAND ((PLC_Deploy_State=0) OR (PLC_Deploy_State=30))
\tAND (MODE_State<>1) AND NOT 点样测试 THEN
\t位置示教();
END_IF

${hmiTail}`
await save(servo, { declaration: servoDeclaration, implementation: servoImplementation })

const init = await read('initialization')
const initDeclaration = appendBeforeEndVar(
  init.declaration,
  'nTeachClear',
  `\tnTeachClear : INT;\n`,
)
const initAxisState = axisCommandDates.map((date) =>
  `${date}.xHome := FALSE; ${date}.xJogPos := FALSE; ${date}.xJogNeg := FALSE;
${date}.xMoveAbs := FALSE; ${date}.xMoveRel := FALSE; ${date}.xStop := FALSE; ${date}.XReset := FALSE;
${date}.bBusy := FALSE; ${date}.bError := FALSE; ${date}.iErrorCode := 0;
${date}.bAbMoveDone := FALSE; ${date}.bReMoveDone := FALSE;`
).join('\n')
const initImplementation = `${initAxisState}
${clearDirectJogCommands}
// Full download must invalidate retained teaching requests before normal motion can re-arm.
FOR nTeachClear:=1 TO 10 DO
${initClearTeachCommands}
END_FOR
一键回原点 := FALSE;
上样轴4X轴DATE.bHomed := FALSE;
上样轴5Z轴DATE.bHomed := FALSE;
HMI_HandWheel_3Y := FALSE; HMI_HandWheel_4X := FALSE; HMI_HandWheel_5Z := FALSE;
HMI_HandWheel_6X := FALSE; HMI_HandWheel_7Y := FALSE; HMI_HandWheel_8Y := FALSE;
HMI_HandWheel_9X := FALSE; HMI_HandWheel_10Z := FALSE; HMI_HandWheel_11Y := FALSE;
Sampling_Servo_FreeMove := FALSE;
PLC_Ready := FALSE;
PLC_Startup_AlarmInhibit := TRUE;
PLC_HandWheel_Active := FALSE;
PLC_Startup_State := 0;
PLC_Startup_ErrorCode := 0;
PLC_Deploy_CommitSeq := 0;
PLC_Deploy_Start := FALSE;
PLC_Deploy_Reset := FALSE;
PLC_Deploy_State := 0;
PLC_Deploy_ErrorCode := 0;
ECAT掉站报警 := FALSE;
伺服报警 := FALSE;
伺服未回原点报警 := FALSE;`
await save(init, { declaration: initDeclaration, implementation: initImplementation })

const alarm = await read('A00_设备状态显示及控制')
const alarmImplementation = `// PLC mode and stack-light control.
PLC_Mode_0(
\tbWarning_alarm := cyinderAlarm<>0 OR Alarm<>0 OR 上样料架报警 OR ModbusTcpError.byDiagData>0,
\txStart := 启动 OR PLCStart,
\txStop := NOT 停止 OR PLCStop,
\txReset := 复位 OR bAutoHomeResetPulse,
\txAutoMode := 手自动,
\txFault := 伺服报警 OR ECAT掉站报警 OR 伺服未回原点报警,
\txEmergency := 急停,
\tbRed => 三色灯红,
\tbYellow => 三色灯黄,
\tbGreen => 三色灯绿,
\tbBuzzer => 蜂鸣器,
\tiState => MODE_STATE,
\tbAuto => ManualAuto);

// Do not create HMI history records during a successful PLC/EtherCAT startup.
IF (NOT PLC_Ready) AND (PLC_Startup_State<>90) THEN
\t伺服报警 := FALSE;
\t伺服未回原点报警 := FALSE;
ELSIF (PLC_Startup_State=90) AND (PLC_Startup_ErrorCode>=100) AND (PLC_Startup_ErrorCode<=200) THEN
\t// EtherCAT/axis-communication root cause: suppress the eleven derived servo alarms.
\t伺服报警 := FALSE;
\t伺服未回原点报警 := FALSE;
ELSE
\tIF 玻璃上料轴1ZDATE.bError OR 玻璃上料轴2ZDATE.bError OR 打样瓶上料轴3YDATE.bError
\t\tOR 点样轴6XDATE.bError OR 点样轴7YDATE.bError OR 拍照轴8YDATE.bError
\t\tOR 刮板轴9XDATE.bError OR 刮板轴10ZDATE.bError OR 地轨轴11YDATE.bError
\t\tOR 上样轴4X轴DATE.bError OR 上样轴5Z轴DATE.bError THEN
\t\t伺服报警 := TRUE;
\tEND_IF
\tIF NOT 玻璃上料轴1ZDATE.bHomed OR NOT 玻璃上料轴2ZDATE.bHomed
\t\tOR NOT 打样瓶上料轴3YDATE.bHomed OR NOT 点样轴6XDATE.bHomed
\t\tOR NOT 点样轴7YDATE.bHomed OR NOT 拍照轴8YDATE.bHomed
\t\tOR NOT 刮板轴9XDATE.bHomed OR NOT 刮板轴10ZDATE.bHomed
\t\tOR NOT 地轨轴11YDATE.bHomed OR NOT 上样轴4X轴DATE.bHomed
\t\tOR NOT 上样轴5Z轴DATE.bHomed THEN
\t\t伺服未回原点报警 := TRUE;
\tEND_IF
END_IF

IF 复位 OR bSysReset OR bAutoHomeResetPulse THEN
\t伺服报警 := FALSE;
\t伺服未回原点报警 := FALSE;
\tAlarm := 0;
\tcyinderAlarm := 0;
\t上样料架报警 := FALSE;
END_IF`
await save(alarm, { implementation: alarmImplementation })

// Close the PLC-side race as well as the host-side idle guard: once startup is incomplete or
// download preparation is accepted, every L2 dispatcher rejects a fresh Start before executing
// any axis, pump, or cylinder action.  Existing RUNNING actions prevent preparation upstream.
const l2Programs = [
  ['Collect_L2', 'Collect_L2'],
  ['FeedLift_L2', 'FeedLift_L2'],
  ['Sampling_L2', 'Sampling_L2'],
  ['PhotoScrape_L2', 'PhotoScrape_L2'],
  ['Develop_L2', 'Develop_L2'],
  ['Pump_L2', 'Pump_L2'],
  ['Rail_L2', 'Rail_L2'],
  ['StagingA_L2', 'Host_Computer.StagingA_L2'],
]
const gatedL2Paths = []
for (const [name, prefix] of l2Programs) {
  const pou = await read(name)
  const gateCondition = `IF L2_StartTrig.Q AND (${prefix}_State=0)
\tAND ((NOT PLC_Ready) OR (PLC_Deploy_State<>0)) THEN`
  if (pou.implementation.includes('Global deployment/startup gate')) {
    const implementation = pou.implementation.replace(
      /(\(\* Global deployment\/startup gate:[^\r\n]*\*\)\r?\n)IF L2_StartTrig\.Q[\s\S]*? THEN/,
      `$1${gateCondition}`,
    )
    if (implementation === pou.implementation && !pou.implementation.includes(gateCondition)) {
      throw new Error(`${name}: existing global gate condition not recognised`)
    }
    if (implementation !== pou.implementation) {
      await save(pou, { implementation })
    }
    gatedL2Paths.push(pou.path)
    continue
  }
  const startCall = name === 'StagingA_L2'
    ? 'L2_StartTrig(CLK := Host_Computer.StagingA_L2_Start);'
    : `L2_StartTrig(CLK := ${name}_Start);`
  const at = pou.implementation.indexOf(startCall)
  if (at < 0) throw new Error(`${name}: Start trigger call not found`)
  const insertAt = at + startCall.length
  const gate = `

(* Global deployment/startup gate: reject before any physical action is dispatched. *)
${gateCondition}
\t${prefix}_AcceptedSeq := ${prefix}_RequestSeq;
\t${prefix}_ActiveCode := ${prefix}_ActionCode;
\t${prefix}_ErrorCode := 190;
\t${prefix}_Retryable := TRUE;
\t${prefix}_CompletedSeq := ${prefix}_RequestSeq;
\t${prefix}_State := 30;
\tRETURN;
END_IF`
  const implementation = `${pou.implementation.slice(0, insertAt)}${gate}${pou.implementation.slice(insertAt)}`
  await save(pou, { implementation })
  gatedL2Paths.push(pou.path)
}

console.log(JSON.stringify({
  updated: [
    host.path, axisFb.path, handwheelFb.path, handwheelProgram.path, calls.path,
    homeAction.path, cylinderProgram.path, tankDrain.path, tankDrainAction.path,
    pumpManager.path, mainProgram.path, servo.path, init.path, alarm.path,
    ...gatedL2Paths,
  ],
  homing_latches_fixed: homedFixes,
}, null, 2))
