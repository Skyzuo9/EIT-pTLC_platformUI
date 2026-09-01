# PLC交付 - StagingA_L2 可复制粘贴

日期: 2026-07-03

目标: 只在一个 `StagingA_L2` POU 内，实现暂存 A / 暂存 B 两个定位气缸的原点、动点控制。

## 0. 最小契约

物理对象只有两个:

| 对象 | PLC 现有输出变量 | TRUE | FALSE |
|---|---|---|---|
| 暂存 A 定位气缸 | `cyinder_date.粉末收集器定位自动` | 动点 | 原点 |
| 暂存 B 定位气缸 | `cyinder_date.溶液收集瓶定位自动` | 动点 | 原点 |

L2 也只有一套:

| action_code | 含义 | PC 写入目标 |
|---:|---|---|
| 24 | 暂存 A 定位气缸到目标位 | `Host_Computer.StagingA_LocatorA_Target` |
| 25 | 暂存 B 定位气缸到目标位 | `Host_Computer.StagingA_LocatorB_Target` |

说明:

- `TRUE=动点，FALSE=原点`。
- 这里只做目标态写入: PLC 收到动作后写对应气缸自动变量，然后返回 `DONE`。
- 当前不新增 `StagingB_L2`，也不把暂存 B 拆成独立 L2 POU。
- 如果工程里访问气缸变量时不需要 `cyinder_date.` 前缀，粘贴时按实际工程作用域删掉前缀即可。

## 1. Host_Computer 增加变量

在 GVL `Host_Computer` 中，和现有各工位 `*_L2_*` 变量放在同一层级，新增:

```iecst
StagingA_L2_ActionCode     : INT;
StagingA_L2_RequestSeq     : DINT;
StagingA_L2_Start          : BOOL;
StagingA_L2_Reset          : BOOL;
StagingA_L2_State          : INT;   // 0=IDLE,10=RUNNING,20=DONE,30=REJECTED,40=ERROR,50=INTERRUPTED
StagingA_L2_ActiveCode     : INT;
StagingA_L2_AcceptedSeq    : DINT;
StagingA_L2_CompletedSeq   : DINT;
StagingA_L2_Step           : INT;
StagingA_L2_ErrorCode      : INT;
StagingA_L2_SafeState      : INT;
StagingA_L2_Retryable      : BOOL;

StagingA_LocatorA_Target   : BOOL;  // TRUE=暂存 A 到动点, FALSE=暂存 A 回原点
StagingA_LocatorB_Target   : BOOL;  // TRUE=暂存 B 到动点, FALSE=暂存 B 回原点
```

符号配置 / 标签通讯中确认这些 BrowseName 可见:

```text
Host_Computer.StagingA_L2_ActionCode
Host_Computer.StagingA_L2_RequestSeq
Host_Computer.StagingA_L2_Start
Host_Computer.StagingA_L2_Reset
Host_Computer.StagingA_L2_State
Host_Computer.StagingA_L2_ActiveCode
Host_Computer.StagingA_L2_AcceptedSeq
Host_Computer.StagingA_L2_CompletedSeq
Host_Computer.StagingA_L2_Step
Host_Computer.StagingA_L2_ErrorCode
Host_Computer.StagingA_L2_SafeState
Host_Computer.StagingA_L2_Retryable
Host_Computer.StagingA_LocatorA_Target
Host_Computer.StagingA_LocatorB_Target
```

## 2. StagingA_L2 声明区

如果 `StagingA_L2` POU 已经有 `L2_StartTrig`，不要重复声明。

```iecst
VAR
    L2_StartTrig : R_TRIG;
END_VAR
```

## 3. StagingA_L2 实现区

```iecst
// StagingA_L2
// 功能:
//   ActionCode=24: 暂存 A 定位气缸到 Host_Computer.StagingA_LocatorA_Target
//   ActionCode=25: 暂存 B 定位气缸到 Host_Computer.StagingA_LocatorB_Target
//
// L2 State:
//   0=IDLE, 10=RUNNING, 20=DONE, 30=REJECTED, 40=ERROR, 50=INTERRUPTED
// ErrorCode:
//   0=OK, 101=BUSY, 102=DUPLICATE_SEQ, 103=UNKNOWN_ACTION, 402=RESET_INTERRUPTED

L2_StartTrig(CLK := Host_Computer.StagingA_L2_Start);

// Reset: 上位机/人工复位。运行中复位给 INTERRUPTED; 非运行态复位回 IDLE。
IF Host_Computer.StagingA_L2_Reset THEN
    IF Host_Computer.StagingA_L2_State = 10 THEN
        Host_Computer.StagingA_L2_ErrorCode := 402;
        Host_Computer.StagingA_L2_Retryable := FALSE;
        Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_AcceptedSeq;
        Host_Computer.StagingA_L2_State := 50;
    ELSE
        Host_Computer.StagingA_L2_State := 0;
        Host_Computer.StagingA_L2_ActiveCode := 0;
        Host_Computer.StagingA_L2_Step := 0;
        Host_Computer.StagingA_L2_ErrorCode := 0;
        Host_Computer.StagingA_L2_SafeState := 0;
        Host_Computer.StagingA_L2_Retryable := FALSE;
    END_IF
    RETURN;
END_IF

// Start 上升沿: 接受/拒绝一个请求。
IF L2_StartTrig.Q THEN
    IF Host_Computer.StagingA_L2_State <> 0 THEN
        // BUSY
        Host_Computer.StagingA_L2_ErrorCode := 101;
        Host_Computer.StagingA_L2_Retryable := TRUE;
        Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_RequestSeq;
        Host_Computer.StagingA_L2_State := 30;

    ELSIF Host_Computer.StagingA_L2_RequestSeq <= Host_Computer.StagingA_L2_AcceptedSeq
       OR Host_Computer.StagingA_L2_RequestSeq <= Host_Computer.StagingA_L2_CompletedSeq THEN
        // DUPLICATE_SEQ
        Host_Computer.StagingA_L2_ErrorCode := 102;
        Host_Computer.StagingA_L2_Retryable := FALSE;
        Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_RequestSeq;
        Host_Computer.StagingA_L2_State := 30;

    ELSE
        CASE Host_Computer.StagingA_L2_ActionCode OF
            24, 25:
                Host_Computer.StagingA_L2_ActiveCode := Host_Computer.StagingA_L2_ActionCode;
                Host_Computer.StagingA_L2_AcceptedSeq := Host_Computer.StagingA_L2_RequestSeq;
                Host_Computer.StagingA_L2_ErrorCode := 0;
                Host_Computer.StagingA_L2_SafeState := 0;
                Host_Computer.StagingA_L2_Retryable := FALSE;
                Host_Computer.StagingA_L2_Step := 1;
                Host_Computer.StagingA_L2_State := 10;

            ELSE
                // UNKNOWN_ACTION
                Host_Computer.StagingA_L2_ErrorCode := 103;
                Host_Computer.StagingA_L2_Retryable := FALSE;
                Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_RequestSeq;
                Host_Computer.StagingA_L2_State := 30;
        END_CASE
    END_IF
END_IF

// RUNNING: 目标态动作，写对应气缸输出后立即 DONE。
IF Host_Computer.StagingA_L2_State = 10 THEN
    CASE Host_Computer.StagingA_L2_ActiveCode OF
        24:
            Host_Computer.StagingA_L2_Step := 24;
            cyinder_date.粉末收集器定位自动 := Host_Computer.StagingA_LocatorA_Target;

            Host_Computer.StagingA_L2_ErrorCode := 0;
            Host_Computer.StagingA_L2_Retryable := FALSE;
            Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_AcceptedSeq;
            Host_Computer.StagingA_L2_Step := 99;
            Host_Computer.StagingA_L2_State := 20;

        25:
            Host_Computer.StagingA_L2_Step := 25;
            cyinder_date.溶液收集瓶定位自动 := Host_Computer.StagingA_LocatorB_Target;

            Host_Computer.StagingA_L2_ErrorCode := 0;
            Host_Computer.StagingA_L2_Retryable := FALSE;
            Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_AcceptedSeq;
            Host_Computer.StagingA_L2_Step := 99;
            Host_Computer.StagingA_L2_State := 20;

        ELSE
            Host_Computer.StagingA_L2_ErrorCode := 103;
            Host_Computer.StagingA_L2_Retryable := FALSE;
            Host_Computer.StagingA_L2_CompletedSeq := Host_Computer.StagingA_L2_AcceptedSeq;
            Host_Computer.StagingA_L2_State := 40;
    END_CASE
END_IF

// 上位机看到终态后会清 Start=FALSE，并等待 State 回 IDLE。
// 保留 CompletedSeq，不清它，否则上位机会丢失已完成序号。
IF NOT Host_Computer.StagingA_L2_Start THEN
    IF (Host_Computer.StagingA_L2_State = 20)
    OR (Host_Computer.StagingA_L2_State = 30)
    OR (Host_Computer.StagingA_L2_State = 40)
    OR (Host_Computer.StagingA_L2_State = 50) THEN
        Host_Computer.StagingA_L2_State := 0;
        Host_Computer.StagingA_L2_ActiveCode := 0;
        Host_Computer.StagingA_L2_Step := 0;
        Host_Computer.StagingA_L2_ErrorCode := 0;
        Host_Computer.StagingA_L2_SafeState := 0;
        Host_Computer.StagingA_L2_Retryable := FALSE;
    END_IF
END_IF
```

## 4. PLC_MainPRG 调用

在 `PLC_MainPRG` 的运行态 L2 调度区，把 `StagingA_L2()` 和其它 L2 POU 放在同一层调用。

示意:

```iecst
Sampling_L2();
Develop_L2();
PhotoScrape_L2();
Collect_L2();
FeedLift_L2();
Pump_L2();
Rail_L2();
StagingA_L2();
```

只新增这一行即可:

```iecst
StagingA_L2();
```

## 5. 上位机后续配置口径

后续上位机配置应只使用一个 station/prefix:

```yaml
staging_a.locator_a:
  station: staging_a
  action_code: 24
  channel: StagingA_LocatorA_Target

staging_a.locator_b:
  station: staging_a
  action_code: 25
  channel: StagingA_LocatorB_Target
```

对应 `PlcController.STATION_PREFIX`:

```python
"staging_a": "StagingA"
```

不需要:

```text
StagingB_L2
staging_b station
StagingB_* OPC 节点
```

## 6. 最小验收

先只做单动作，不跑整条 demo:

1. 编译 PLC 工程，要求 0 errors。
2. OPC browse 确认 `Host_Computer.StagingA_L2_*`、`Host_Computer.StagingA_LocatorA_Target`、`Host_Computer.StagingA_LocatorB_Target` 都可见。
3. 上位机执行 `staging_a.locator_a(target=true)`，观察:
   - `StagingA_L2_State`: `0 -> 10 -> 20 -> 0`
   - `AcceptedSeq == CompletedSeq`
   - 暂存 A 气缸到动点。
4. 上位机执行 `staging_a.locator_a(target=false)`，确认暂存 A 气缸回原点。
5. 上位机执行 `staging_a.locator_b(target=true)`，确认暂存 B 气缸到动点。
6. 上位机执行 `staging_a.locator_b(target=false)`，确认暂存 B 气缸回原点。

如果动作方向相反，先核对对应 `cyinder_date.*定位自动` 的 TRUE/FALSE 物理语义，再决定是否在 POU 内取反。
