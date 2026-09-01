(*
    Collect_Action_Decomposition.st
    Date: 2026-06-18

    用途
    ----
    本程序是 PLC 侧的 ST 参考程序，用于拆分收集工位动作，同时保留现有的
    collect_Enable 阶段协议。

    职责边界
    --------
    - 上位机写入工艺意图和阶段参数：collect_Enable、
      collect_forward_instructions、collect_count、collect_Consume_Slot、
      collect_Powder_Return_Slot 以及耗材架决策。
    - PLC 负责原始传感器、I/O 闭环、安全互锁、动作执行、可重试性判断、
      safe_state 和诊断信息。
    - 原始传感器可以开放给维护功能，但生产调度应使用动作的
      status/result/error_code/retryable/safe_state。
    - 对改变物理状态且非幂等的动作，上位机不得盲目重试。仅当 PLC 层报告
      retryable 时才允许重试。

    奥卡姆式实施方案
    ----------------
    1. 保留外部 collect_Enable 全流程，作为生产入口。
    2. 仅拆分当前 PLC 流程中已经存在的收集工位动作；不要把原始传感器逻辑
       移到上位机。
    3. 为所有动作增加一套共用的诊断字段：
       Collect_ActionId, Collect_ActionStep, Collect_ActionStatus,
       Collect_ActionErrorCode, Collect_ActionDiag, Collect_ActionRetryable,
       Collect_ActionSafeState.
    4. 尽可能复用现有 I/O 名称和机器人握手位。
    5. 将 pump-idle / pump-error 作为 PLC 侧预留接口，在现场验证期间接入。
       在接入前，可强制 Collect_PumpIdle := TRUE、Collect_PumpError := FALSE
       来仿真本程序。

    动作协议摘要
    ------------
    动作 1：Collect_Init
      进入条件：
        MODE_State=1、安全条件满足，并检测到 collect_Enable 上升沿，或阶段已进入 Step 5。
      完成条件：
        下压/夹持/升降/伸缩气缸均在原点；阀门关闭；内部步骤和旧完成标志已清除。
      失败条件：
        安全条件丢失、非自动模式或气缸回原点超时。
      依赖项：
        收集下压/夹持/升降/伸缩气缸、收集阀门/泵命令通道、工位允许位。
      物理状态变化：
        收集平台返回安全初始姿态。
      恢复方式：
        操作员确认没有物料卡滞后执行 Reset；若工位为空且
        safe_state=SAFE_IDLE，则允许自动重试。
      自动重试：
        可以，但仅限未持有收集瓶或收集器时。

    动作 2：Collect_LoadPowderCollector
      进入条件：
        收集工位已初始化；夹持和下压气缸位于原点；允许机器人/SCARA/轨道侧放置收集器。
      完成条件：
        粉末收集器已放到收集工位，夹持气缸到达动点，机器人已退出安全区域。
      失败条件：
        机器人放置超时、夹持超时、机器人退出超时或安全条件丢失。
      依赖项：
        机器人 110/130 类握手信号、收集夹持气缸、工位允许位，以及机器人程序内部的轨道/机器人互锁。
      物理状态变化：
        粉末收集器从刮取工位/临时交接位置移入收集工位并被夹紧。
      恢复方式：
        Reset 前人工检查收集器位置和夹持状态。
      自动重试：
        默认不允许；该动作会改变物料位置。

    动作 3：Collect_LoadBottle
      进入条件：
        粉末收集器已夹紧；伸缩气缸位于原点；瓶传感器确认当前位置无瓶；机器人可从暂存工位 B 放入收集瓶。
      完成条件：
        检测到收集瓶，伸缩气缸到达动点，升降和下压气缸到达洗脱姿态。
      失败条件：
        机器人放置超时、未检测到收集瓶，或伸缩/升降/下压动作超时。
      依赖项：
        机器人 120 类握手信号、瓶传感器、伸缩/升降/下压气缸和工位允许位。
      物理状态变化：
        空收集瓶从暂存工位 B 移入收集工位并进入洗脱姿态。
      恢复方式：
        人工检查收集瓶和平台姿态。
      自动重试：
        默认不允许；重复放置可能造成重复取放或与已有瓶发生碰撞。

    动作 4：Collect_Elute
      进入条件：
        粉末收集器和收集瓶均已装载，已到达洗脱姿态，
        collect_forward_instructions 非空且 collect_count > 0。
      完成条件：
        已完成 collect_count 个循环；进液阀、排液阀和正压排液阀均关闭。
      失败条件：
        命令无效、泵报错、等待泵空闲超时或洗脱计数超时。
      依赖项：
        收集泵、进液阀、排液阀、正压排液阀，以及可选的气泡/瓶状态诊断。
      物理状态变化：
        液体穿过粉末收集器并转移到收集瓶中。
      恢复方式：
        若命令在液体开始移动前失败，PLC 可标记为可重试；若液体可能已经移动，则需人工作出工艺判断。
      自动重试：
        仅当 PLC 报告 retryable 且 safe_state=SAFE_TO_RETRY 时允许。

    动作 5：Collect_UnloadBottle
      进入条件：
        洗脱已完成；升降和下压机构可安全返回；收集瓶存在。
      完成条件：
        下压/升降已释放，伸缩气缸回到原点，机器人已将收集瓶移回暂存工位 B 或下一个配置位置。
      失败条件：
        气缸返回超时或机器人卸瓶超时。
      依赖项：
        下压/升降/伸缩气缸和机器人 140 类握手信号。
      物理状态变化：
        已装液的收集瓶离开收集工位。
      恢复方式：
        人工检查收集瓶位置和耗材台账。
      自动重试：
        默认不允许；卸载动作非幂等。

    动作 6：Collect_UnloadPowderCollector
      进入条件：
        收集瓶已卸载或已确认清空；粉末收集器仍被夹持；
        collect_Powder_Return_Slot > 0。
      完成条件：
        夹持已释放，机器人将收集器送回暂存工位 A 的原槽位，collect_Done 锁存。
      失败条件：
        缺少返还槽位、夹持释放超时或机器人返还超时。
      依赖项：
        夹持气缸、机器人 130 类握手信号和粉末收集器返还槽位。
      物理状态变化：
        粉末收集器离开收集工位并返回暂存工位 A。
      恢复方式：
        人工检查收集器位置和暂存工位 A 台账。
      自动重试：
        默认不允许；返还槽位动作非幂等。

    建议的全流程顺序
    ----------------
    面向用户的六个动作命名为：
      Init, LoadPowderCollector, LoadBottle, Elute,
      UnloadBottle, UnloadPowderCollector.

    本文件按上述顺序执行。若现场验证表明旧有物理顺序必须保持“先放瓶、后放收集器”，
    只需在编排层交换 Step 10 和 Step 20；动作协议和诊断字段保持不变。
*)

VAR_GLOBAL
    (* 现有统一阶段变量。如果项目中已经声明这些变量，目标集成时应将这些声明
       移至 VAR_EXTERNAL。 *)
    collect_Enable : BOOL;
    collect_Step : INT;
    collect_Done : BOOL;
    collect_Error : BOOL;
    collect_Reset : BOOL;
    collect_Busy : BOOL;

    collect_forward_instructions : STRING(128);
    collect_count : INT;
    collect_OK : BOOL;
    collect_initialization : BOOL;
    collect_Initialization_OK : BOOL;
    collect_prepare : BOOL;
    collect_prepare_OK : BOOL;

    collect_Consume_Slot : INT;
    collect_Powder_Return_Slot : INT;

    (* 新增的动作诊断字段。 *)
    Collect_ActionId : INT;          (* 0 空闲，1 初始化，2 装载收集器，3 装载收集瓶，4 洗脱，5 卸载收集瓶，6 卸载收集器 *)
    Collect_ActionStep : INT;        (* 当前动作内部的子步骤 *)
    Collect_ActionStatus : INT;      (* 0 空闲，10 运行中，20 完成，90 错误 *)
    Collect_ActionErrorCode : DINT;  (* 参见程序主体中的错误码注释 *)
    Collect_ActionDiag : STRING(128);
    Collect_ActionRetryable : BOOL;
    Collect_ActionSafeState : INT;   (* 0 未知，1 安全空闲，2 持有收集器，3 持有收集瓶，4 洗脱位置，5 等待恢复，6 可安全重试 *)

    (* 用于验证的泵状态预留接口。具备真实的泵命令转换器完成/错误状态后，
       应替换为真实信号。 *)
    Collect_PumpIdle : BOOL := TRUE;
    Collect_PumpError : BOOL := FALSE;
END_VAR

PROGRAM Collect_Action_Decomposition
VAR_EXTERNAL
    MODE_State : INT;
    急停 : BOOL;

    收集下压气缸自动 : BOOL;
    收集夹持气缸自动 : BOOL;
    收集升降气缸自动 : BOOL;
    收集伸缩气缸自动 : BOOL;

    收集进液自动 : BOOL;
    收集排液自动 : BOOL;
    收集正压排液自动 : BOOL;
    转发转存 : STRING(128);
    收集计数 : INT;

    收集平台下压气缸原点 : BOOL;
    收集平台下压气缸动点 : BOOL;
    收集平台夹持气缸原点 : BOOL;
    收集平台夹持气缸动点 : BOOL;
    收集平台升降气缸原点 : BOOL;
    收集平台升降气缸动点 : BOOL;
    收集平台推出气缸原点 : BOOL;
    收集平台推出气缸动点 : BOOL;
    收集平台瓶子有无传感器 : BOOL;

    收集工位允许放收集瓶 : BOOL;
    收集工位放收集瓶完成 : BOOL;
    收集工位允许放收集器 : BOOL;
    收集工位放收集器到工位 : BOOL;
    收集工位允许机器人退出工位 : BOOL;
    收集工位机器人退出完成 : BOOL;
    收集工位允许机器人取收集瓶放暂存工位 : BOOL;
    收集工位机器人放收集瓶到暂存工位完成 : BOOL;
    收集工位允许取收集器 : BOOL;
    收集工位机器人到达收集器位置 : BOOL;
    收集工位机器人取收集器放回暂存工位 : BOOL;
    收集工位放收集器完成 : BOOL;
END_VAR

VAR
    rCollectEnable : R_TRIG;
    fCollectEnable : F_TRIG;
    tonAction : TON;
    tonEluteDwell : TON;
    lastStep : INT := -1;
    timerRun : BOOL;
    actionTimeout : TIME := T#30S;

    powderLoaded : BOOL;
    bottleLoaded : BOOL;
    eluteDone : BOOL;
END_VAR

(* 边沿检测 *)
rCollectEnable(CLK := collect_Enable);
fCollectEnable(CLK := collect_Enable);

(* 下降沿：Done 由 PLC 负责清除，上位机不得写入 Done=FALSE。 *)
IF fCollectEnable.Q THEN
    collect_Done := FALSE;
    collect_Busy := FALSE;
    IF collect_Step <> 90 THEN
        collect_Step := 0;
        Collect_ActionId := 0;
        Collect_ActionStep := 0;
        Collect_ActionStatus := 0;
        Collect_ActionErrorCode := 0;
        Collect_ActionDiag := 'idle';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 1;
    END_IF
END_IF

(* Reset 清除诊断信息和未锁存请求，但不会假定物料已自动回到原位；
   重新启动前，操作员必须确认实际物理状态。 *)
IF collect_Reset THEN
    collect_Error := FALSE;
    collect_Done := FALSE;
    collect_Busy := FALSE;
    collect_Step := 0;
    collect_OK := FALSE;
    collect_initialization := FALSE;
    collect_Initialization_OK := FALSE;
    collect_prepare := FALSE;
    collect_prepare_OK := FALSE;

    收集进液自动 := FALSE;
    收集排液自动 := FALSE;
    收集正压排液自动 := FALSE;
    转发转存 := '';

    收集工位允许放收集瓶 := FALSE;
    收集工位允许放收集器 := FALSE;
    收集工位允许机器人退出工位 := FALSE;
    收集工位允许机器人取收集瓶放暂存工位 := FALSE;
    收集工位允许取收集器 := FALSE;
    收集工位机器人取收集器放回暂存工位 := FALSE;

    Collect_ActionId := 0;
    Collect_ActionStep := 0;
    Collect_ActionStatus := 0;
    Collect_ActionErrorCode := 0;
    Collect_ActionDiag := 'reset';
    Collect_ActionRetryable := FALSE;
    Collect_ActionSafeState := 1;
    powderLoaded := FALSE;
    bottleLoaded := FALSE;
    eluteDone := FALSE;
END_IF

(* 全局安全/模式拒绝逻辑。按照当前 PLC 约定，NOT 急停 表示安全链断开。 *)
IF (NOT collect_Reset) AND collect_Enable AND (collect_Step <> 90) THEN
    IF MODE_State <> 1 THEN
        collect_Error := TRUE;
        collect_Busy := FALSE;
        collect_Step := 90;
        Collect_ActionStatus := 90;
        Collect_ActionErrorCode := 9002;
        Collect_ActionDiag := 'MODE_State is not AUTO';
        Collect_ActionRetryable := TRUE;
        Collect_ActionSafeState := 1;
    ELSIF NOT 急停 THEN
        收集进液自动 := FALSE;
        收集排液自动 := FALSE;
        收集正压排液自动 := FALSE;
        收集工位允许放收集瓶 := FALSE;
        收集工位允许放收集器 := FALSE;
        收集工位允许机器人退出工位 := FALSE;
        收集工位允许机器人取收集瓶放暂存工位 := FALSE;
        收集工位允许取收集器 := FALSE;
        收集工位机器人取收集器放回暂存工位 := FALSE;
        collect_Error := TRUE;
        collect_Busy := FALSE;
        collect_Step := 90;
        Collect_ActionStatus := 90;
        Collect_ActionErrorCode := 9001;
        Collect_ActionDiag := 'EStop or safety chain open';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 5;
    END_IF
END_IF

(* 启动完整收集流程。对外行为仍以 collect_Enable 为入口。 *)
IF rCollectEnable.Q AND (collect_Step = 0) AND (NOT collect_Error) THEN
    collect_Done := FALSE;
    collect_OK := FALSE;
    collect_Busy := TRUE;
    collect_Step := 5;
    Collect_ActionId := 1;
    Collect_ActionStep := 0;
    Collect_ActionStatus := 10;
    Collect_ActionErrorCode := 0;
    Collect_ActionDiag := 'Collect_Init';
    Collect_ActionRetryable := FALSE;
    Collect_ActionSafeState := 0;
    powderLoaded := FALSE;
    bottleLoaded := FALSE;
    eluteDone := FALSE;
END_IF

collect_Busy := collect_Enable AND (collect_Step > 0) AND (collect_Step < 90) AND (NOT collect_Done);

CASE collect_Step OF
    5:  actionTimeout := T#30S;   (* 初始化 *)
    10: actionTimeout := T#90S;   (* 装载粉末收集器 *)
    20: actionTimeout := T#90S;   (* 装载收集瓶 *)
    30: actionTimeout := T#180S;  (* 洗脱 *)
    40: actionTimeout := T#90S;   (* 卸载收集瓶 *)
    50: actionTimeout := T#90S;   (* 卸载粉末收集器 *)
ELSE
    actionTimeout := T#30S;
END_CASE

IF collect_Step <> lastStep THEN
    tonAction(IN := FALSE, PT := actionTimeout);
    lastStep := collect_Step;
END_IF

timerRun := collect_Busy AND (collect_Step > 0) AND (collect_Step < 90);
tonAction(IN := timerRun, PT := actionTimeout);

IF tonAction.Q AND (collect_Step <> 90) THEN
    收集进液自动 := FALSE;
    收集排液自动 := FALSE;
    收集正压排液自动 := FALSE;
    收集工位允许放收集瓶 := FALSE;
    收集工位允许放收集器 := FALSE;
    收集工位允许机器人退出工位 := FALSE;
    收集工位允许机器人取收集瓶放暂存工位 := FALSE;
    收集工位允许取收集器 := FALSE;
    收集工位机器人取收集器放回暂存工位 := FALSE;

    collect_Error := TRUE;
    collect_Busy := FALSE;
    collect_Step := 90;
    Collect_ActionStatus := 90;
    Collect_ActionRetryable := FALSE;
    Collect_ActionSafeState := 5;

    CASE Collect_ActionId OF
        1:
            Collect_ActionErrorCode := 1100;
            Collect_ActionDiag := 'Collect_Init timeout';
            IF (NOT powderLoaded) AND (NOT bottleLoaded) THEN
                Collect_ActionRetryable := TRUE;
                Collect_ActionSafeState := 1;
            END_IF
        2:
            Collect_ActionErrorCode := 2100;
            Collect_ActionDiag := 'LoadPowderCollector timeout';
        3:
            Collect_ActionErrorCode := 3100;
            Collect_ActionDiag := 'LoadBottle timeout';
        4:
            Collect_ActionErrorCode := 4200;
            Collect_ActionDiag := 'Collect_Elute timeout';
            IF 收集计数 = 0 THEN
                Collect_ActionRetryable := TRUE;
                Collect_ActionSafeState := 6;
            END_IF
        5:
            Collect_ActionErrorCode := 5100;
            Collect_ActionDiag := 'UnloadBottle timeout';
        6:
            Collect_ActionErrorCode := 6100;
            Collect_ActionDiag := 'UnloadPowderCollector timeout';
    ELSE
        Collect_ActionErrorCode := 1000;
        Collect_ActionDiag := 'Unknown collect action timeout';
    END_CASE
END_IF

CASE collect_Step OF
    0:
        collect_Busy := FALSE;
        IF NOT collect_Enable THEN
            Collect_ActionId := 0;
            Collect_ActionStep := 0;
            Collect_ActionStatus := 0;
            Collect_ActionSafeState := 1;
        END_IF

    5:
        (* 收集工位初始化（Collect_Init） *)
        Collect_ActionId := 1;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'Collect_Init running';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 0;
        collect_initialization := TRUE;
        collect_prepare := FALSE;
        collect_Initialization_OK := FALSE;
        collect_prepare_OK := FALSE;
        collect_OK := FALSE;
        Collect_ActionStep := 10;

        收集下压气缸自动 := FALSE;
        收集夹持气缸自动 := FALSE;
        收集升降气缸自动 := FALSE;
        收集伸缩气缸自动 := FALSE;
        收集进液自动 := FALSE;
        收集排液自动 := FALSE;
        收集正压排液自动 := FALSE;
        转发转存 := '';

        收集工位允许放收集瓶 := FALSE;
        收集工位允许放收集器 := FALSE;
        收集工位允许机器人退出工位 := FALSE;
        收集工位允许机器人取收集瓶放暂存工位 := FALSE;
        收集工位允许取收集器 := FALSE;
        收集工位机器人取收集器放回暂存工位 := FALSE;

        IF 收集平台下压气缸原点
           AND 收集平台夹持气缸原点
           AND 收集平台升降气缸原点
           AND 收集平台推出气缸原点 THEN
            collect_Initialization_OK := TRUE;
            collect_initialization := FALSE;
            Collect_ActionStatus := 20;
            Collect_ActionDiag := 'Collect_Init done';
            Collect_ActionSafeState := 1;
            collect_Step := 10;
            Collect_ActionStep := 0;
        END_IF

    10:
        (* 装载粉末收集器（Collect_LoadPowderCollector） *)
        Collect_ActionId := 2;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'LoadPowderCollector running';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 1;

        CASE Collect_ActionStep OF
            0:
                IF 收集平台夹持气缸原点 AND 收集平台下压气缸原点 THEN
                    收集工位允许放收集器 := TRUE;
                    Collect_ActionStep := 10;
                END_IF
            10:
                IF 收集工位放收集器到工位 THEN
                    收集工位允许放收集器 := FALSE;
                    收集夹持气缸自动 := TRUE;
                    Collect_ActionStep := 20;
                END_IF
            20:
                IF 收集平台夹持气缸动点 THEN
                    收集工位允许机器人退出工位 := TRUE;
                    Collect_ActionStep := 30;
                END_IF
            30:
                IF 收集工位机器人退出完成 THEN
                    收集工位允许机器人退出工位 := FALSE;
                    powderLoaded := TRUE;
                    Collect_ActionStatus := 20;
                    Collect_ActionDiag := 'LoadPowderCollector done';
                    Collect_ActionSafeState := 2;
                    Collect_ActionStep := 0;
                    collect_Step := 20;
                END_IF
        END_CASE

    20:
        (* 装载收集瓶（Collect_LoadBottle） *)
        Collect_ActionId := 3;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'LoadBottle running';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 2;

        CASE Collect_ActionStep OF
            0:
                IF (NOT powderLoaded) THEN
                    collect_Error := TRUE;
                    collect_Busy := FALSE;
                    collect_Step := 90;
                    Collect_ActionStatus := 90;
                    Collect_ActionErrorCode := 3001;
                    Collect_ActionDiag := 'Powder collector is not loaded';
                    Collect_ActionSafeState := 5;
                ELSIF 收集平台推出气缸原点 AND (NOT 收集平台瓶子有无传感器) THEN
                    收集工位允许放收集瓶 := TRUE;
                    Collect_ActionStep := 10;
                END_IF
            10:
                IF 收集工位放收集瓶完成 THEN
                    收集工位允许放收集瓶 := FALSE;
                    收集伸缩气缸自动 := TRUE;
                    Collect_ActionStep := 20;
                END_IF
            20:
                IF 收集平台推出气缸动点 AND 收集平台瓶子有无传感器 THEN
                    收集升降气缸自动 := TRUE;
                    收集下压气缸自动 := TRUE;
                    Collect_ActionStep := 30;
                ELSIF 收集平台推出气缸动点 AND (NOT 收集平台瓶子有无传感器) THEN
                    收集伸缩气缸自动 := FALSE;
                    collect_Error := TRUE;
                    collect_Busy := FALSE;
                    collect_Step := 90;
                    Collect_ActionStatus := 90;
                    Collect_ActionErrorCode := 3200;
                    Collect_ActionDiag := 'Bottle not detected after placement';
                    Collect_ActionRetryable := FALSE;
                    Collect_ActionSafeState := 5;
                END_IF
            30:
                IF 收集平台升降气缸动点 AND 收集平台下压气缸动点 THEN
                    bottleLoaded := TRUE;
                    collect_prepare_OK := TRUE;
                    Collect_ActionStatus := 20;
                    Collect_ActionDiag := 'LoadBottle done';
                    Collect_ActionSafeState := 4;
                    Collect_ActionStep := 0;
                    collect_Step := 30;
                END_IF
        END_CASE

    30:
        (* 收集洗脱（Collect_Elute） *)
        Collect_ActionId := 4;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'Collect_Elute running';
        Collect_ActionSafeState := 4;

        IF (collect_forward_instructions = '') OR (collect_count <= 0) THEN
            collect_Error := TRUE;
            collect_Busy := FALSE;
            collect_Step := 90;
            Collect_ActionStatus := 90;
            Collect_ActionErrorCode := 4100;
            Collect_ActionDiag := 'Invalid collect pump command or count';
            Collect_ActionRetryable := TRUE;
            Collect_ActionSafeState := 6;
        ELSIF Collect_PumpError THEN
            收集进液自动 := FALSE;
            收集排液自动 := FALSE;
            收集正压排液自动 := FALSE;
            collect_Error := TRUE;
            collect_Busy := FALSE;
            collect_Step := 90;
            Collect_ActionStatus := 90;
            Collect_ActionErrorCode := 4201;
            Collect_ActionDiag := 'Collect pump reports error';
            Collect_ActionRetryable := FALSE;
            Collect_ActionSafeState := 5;
        ELSE
            CASE Collect_ActionStep OF
                0:
                    收集进液自动 := TRUE;
                    收集排液自动 := TRUE;
                    收集正压排液自动 := FALSE;
                    tonEluteDwell(IN := FALSE, PT := T#5S);
                    Collect_ActionStep := 10;
                10:
                    转发转存 := collect_forward_instructions;
                    Collect_ActionStep := 20;
                20:
                    IF Collect_PumpIdle THEN
                        转发转存 := '';
                        收集进液自动 := FALSE;
                        收集正压排液自动 := TRUE;
                        tonEluteDwell(IN := FALSE, PT := T#5S);
                        Collect_ActionStep := 30;
                    END_IF
                30:
                    tonEluteDwell(IN := TRUE, PT := T#5S);
                    IF (收集计数 >= collect_count) AND tonEluteDwell.Q THEN
                        收集排液自动 := FALSE;
                        收集正压排液自动 := FALSE;
                        tonEluteDwell(IN := FALSE, PT := T#5S);
                        collect_OK := TRUE;
                        eluteDone := TRUE;
                        Collect_ActionStatus := 20;
                        Collect_ActionDiag := 'Collect_Elute done';
                        Collect_ActionSafeState := 4;
                        Collect_ActionStep := 0;
                        collect_Step := 40;
                    ELSIF Collect_PumpIdle AND tonEluteDwell.Q THEN
                        tonEluteDwell(IN := FALSE, PT := T#5S);
                        Collect_ActionStep := 10;
                    END_IF
            END_CASE
        END_IF

    40:
        (* 卸载收集瓶（Collect_UnloadBottle） *)
        Collect_ActionId := 5;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'UnloadBottle running';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 4;

        CASE Collect_ActionStep OF
            0:
                IF NOT eluteDone THEN
                    collect_Error := TRUE;
                    collect_Busy := FALSE;
                    collect_Step := 90;
                    Collect_ActionStatus := 90;
                    Collect_ActionErrorCode := 5001;
                    Collect_ActionDiag := 'Elute not completed before bottle unload';
                    Collect_ActionSafeState := 5;
                ELSE
                    收集下压气缸自动 := FALSE;
                    收集升降气缸自动 := FALSE;
                    Collect_ActionStep := 10;
                END_IF
            10:
                IF 收集平台升降气缸原点 AND 收集平台下压气缸原点 THEN
                    收集伸缩气缸自动 := FALSE;
                    Collect_ActionStep := 20;
                END_IF
            20:
                IF 收集平台推出气缸原点 THEN
                    收集工位允许机器人取收集瓶放暂存工位 := TRUE;
                    Collect_ActionStep := 30;
                END_IF
            30:
                IF 收集工位机器人放收集瓶到暂存工位完成 THEN
                    收集工位允许机器人取收集瓶放暂存工位 := FALSE;
                    bottleLoaded := FALSE;
                    Collect_ActionStatus := 20;
                    Collect_ActionDiag := 'UnloadBottle done';
                    Collect_ActionSafeState := 2;
                    Collect_ActionStep := 0;
                    collect_Step := 50;
                END_IF
        END_CASE

    50:
        (* 卸载粉末收集器（Collect_UnloadPowderCollector） *)
        Collect_ActionId := 6;
        Collect_ActionStatus := 10;
        Collect_ActionDiag := 'UnloadPowderCollector running';
        Collect_ActionRetryable := FALSE;
        Collect_ActionSafeState := 2;

        IF collect_Powder_Return_Slot <= 0 THEN
            collect_Error := TRUE;
            collect_Busy := FALSE;
            collect_Step := 90;
            Collect_ActionStatus := 90;
            Collect_ActionErrorCode := 6001;
            Collect_ActionDiag := 'Missing powder return slot';
            Collect_ActionRetryable := FALSE;
            Collect_ActionSafeState := 5;
        ELSE
            CASE Collect_ActionStep OF
                0:
                    收集工位允许取收集器 := TRUE;
                    Collect_ActionStep := 10;
                10:
                    IF 收集工位机器人到达收集器位置 THEN
                        收集夹持气缸自动 := FALSE;
                        收集工位允许取收集器 := FALSE;
                        Collect_ActionStep := 20;
                    END_IF
                20:
                    IF 收集平台夹持气缸原点 THEN
                        收集工位机器人取收集器放回暂存工位 := TRUE;
                        Collect_ActionStep := 30;
                    END_IF
                30:
                    IF 收集工位放收集器完成 THEN
                        收集工位机器人取收集器放回暂存工位 := FALSE;
                        powderLoaded := FALSE;
                        collect_Done := TRUE;
                        collect_Busy := FALSE;
                        collect_Step := 0;
                        Collect_ActionStatus := 20;
                        Collect_ActionDiag := 'Collect full flow done';
                        Collect_ActionSafeState := 1;
                        Collect_ActionId := 0;
                        Collect_ActionStep := 0;
                    END_IF
            END_CASE
        END_IF

    90:
        collect_Error := TRUE;
        collect_Busy := FALSE;
        Collect_ActionStatus := 90;
END_CASE
