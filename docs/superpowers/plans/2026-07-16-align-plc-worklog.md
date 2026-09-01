# PLC 核查 worklog — PhotoScrape_L2 对位检查(align) ActionCode 42/43/44

日期: 2026-07-16
任务: Task B1(只读调查,不改 PLC)
工程: `eit_ptlc/plc/20260702.project`(CODESYS 会话 state=ready)
相关 spec: `docs/superpowers/specs/2026-07-16-photoscrape-align-check-design.md` §4/§7
消费者: Task B11(按本 worklog 在 PhotoScrape_L2 加 42/43/44 + 6 个 GVL 节点)

本文所有 ST 片段均从 CODESYS `codesys_read_pou` 现场读取原文,POU 路径逐条标注。
**结论优先:** 42/43/44 在派发器 CASE 里确认空闲;三条动作有两处硬拦截(8Y/9X 的
`10Z.fActPos<6` Z 高门 + 8Y 的遮光上位门)会直接影响 spec §4 的"检查高度微调"设计,详见 Q2/Q5。

---

## 已核对象清单(全部只读)

| POU 路径 | 作用 |
|---|---|
| `Application/50_action/PhotoScrape_L2` | 工位 L2 动作派发器(CASE 主插入点) |
| `.../PhotoScrape_L2/A10_init_初始化` | 复位归位:Z→0, X→335, Y→0 |
| `.../PhotoScrape_L2/A31_cam_移轴335` | 9X 绝对定位样例(→335) |
| `.../PhotoScrape_L2/A32/A33_cam_定位/下压` | 气缸动作(与 align 无关) |
| `.../PhotoScrape_L2/A34_cam_相机位` | 8Y→Photo_8Y_Target |
| `.../PhotoScrape_L2/A35_cam_回零` | 8Y→0(cam_photohome) |
| `.../PhotoScrape_L2/A40_scrape_刮取` | scrape(40):触发 CNC,不走 MC_MoveAbsolute |
| `.../PhotoScrape_L2/A41/A51/A52` | 收尾/取料气缸 |
| `Application/30_Ethercat任务/PLC_Servo_伺服/伺服调用` | FB_SERVOAXIS 实例化 + **轴级互锁** |
| `Application/30_Ethercat任务/PLC_Servo_伺服/伺服一键回原点` | 全局一键回零状态机(Z 先/XY 后链) |
| `Application/25_FB_功能块/FB_SERVOAXIS` | 轴功能块(MC_MoveAbsolute/MC_Home 封装) |
| `Application/10_数据结构/servo` | 轴数据 struct(fAbsTarget/xMoveAbs/bAbMoveDone/fActPos...) |
| `Application/20_变量Date/servoaxisdate` | 11 轴 DATE 实例声明 |
| `Application/20_变量Date/Host_Computer` | Host↔PLC GVL(新节点挂载处) |
| `Application/20_变量Date/GVL` | CNC启动/完成、回零完成位、B1/B2 CNC 缓冲 |
| `Application/40_Man/PLC_MainPRG` | ActPos 每扫描镜像块(回显挂载处) |
| `Application/50_action/FeedLift_L2` + `A11_feed_raise` | 兄弟派发器 + 守卫报错样例 |

---

## Q1 — scrape(40) 用哪些轴 FB 实例;42/43/44 与之有无隐藏共享状态

### 轴数据实例(`servoaxisdate`,类型 `servo`,VAR_GLOBAL RETAIN PERSISTENT)

```
拍照轴8YDATE  AT %MB131512: servo;   // 8Y
刮板轴9XDATE  AT %MB131600: servo;   // 9X
刮板轴10ZDATE AT %MB131688: servo;   // 10Z
```

`servo` 是纯数据 struct(无软限位字段),被 `伺服调用` 里的 FB_SERVOAXIS 实例驱动:
- `FB_SERVOAXIS_5` ← `拍照轴8Y`(AXIS_REF),回写 `拍照轴8YDATE`
- `FB_SERVOAXIS_6` ← `刮板轴9X`,回写 `刮板轴9XDATE`
- `FB_SERVOAXIS_7` ← `刮板轴10Z`,回写 `刮板轴10ZDATE`

单轴点位动作(31/34/35/init 及将来的 42/43/44)通过 `轴.xMoveAbs`→FB 内 `MC_MoveAbsolute` 走。

### ⚠️ scrape(40) 不走 MC_MoveAbsolute,走 CNC 插补器

`.../A40_scrape_刮取` 原文:

```
(* 刮取单 pass: 上位机已写 g_pass_z 等 g_* 参数; 触发 PLC_CNC 跑一刀
   CNC启动/CNC完成 为 PLC 内部 SoftMotion 触发线 (保留); 多 pass 由上位机循环调用本动作 *)
CASE 刮板收集step OF
	0:
		刮板拍照真空自动:=TRUE;
		CNC启动:=TRUE;
		刮板收集step:=10;
	10:
		IF CNC完成 THEN
			CNC启动:=FALSE;
			刮板收集step:=0;
			bActionDone:=TRUE;
		END_IF
END_CASE
```

即:**同一组物理轴(9X/8Y/10Z)有两个运动主:code 40 经 SoftMotion CNC 组
(`PLC_CNC`,has_impl=false 不可读 ST;缓冲 `B1/B2: ARRAY[1..2000] OF SMC_GEOINFO`
在 GVL;参数 `g_sx/g_sy/g_cx/g_cy/g_pass_z`);其余 code 经 FB_SERVOAXIS 的 MC_MoveAbsolute。**

**隐藏共享状态 = CNC 组对 9X/8Y/10Z 的轴占用 + `CNC启动/CNC完成` 握手线。**
- 派发器单活(见 Q-派发器,CASE 每扫描只跑一个 ActiveCode),40 与 42/43/44 天然不同周期,不会并发。
- 上机需确认:`CNC完成` 后 `CNC启动:=FALSE`,CNC 组是否**当周期完全释放**轴回单轴 MC 组,
  使随后的 MC_MoveAbsolute 能拿到轴(SoftMotion CNC 用 SMC_ControlAxisByPos 期间独占轴)。B11 保证
  align 动作只在无 CNC pass 活动时派发(派发器已保证),但轴归还时序须上机验一次。

### 与 40 零共享(spec §4 承诺已核对)

align 只碰 9X/8Y/10Z(MC_MoveAbsolute)+ 读 ActPos;**不碰**
`刮板拍照真空自动/无刷电机/各气缸/g_sx.. 系列/收集器`。使能线全轴统一 `xEnable:=急停`
(全局使能,无工位级门),42/43/44 无需额外处理使能。

---

## Q2 — 8Y 同轴时序:cam_photohome(35) 终态 8Y 是否在零

**是,在零。** `.../A35_cam_回零` 原文:

```
(* 遮光上 + 拍照Y轴回零 (上位机已拍照完成) *)
CASE 拍照step OF
	0:  刮板拍照遮光气缸自动:=FALSE; 拍照step:=10;
	10: IF 刮板拍照遮光气缸上位 THEN
			拍照轴8YDATE.fAbsTarget:=0;
			拍照轴8YDATE.xMoveAbs:=TRUE;
			拍照step:=20;
		END_IF
	20: IF 拍照轴8YDATE.bAbMoveDone THEN
			拍照轴8YDATE.xMoveAbs:=FALSE;
			拍照step:=0; bActionDone:=TRUE;
		END_IF
END_CASE
```

对照 `.../A34_cam_相机位`:8Y 走到 `Photo_8Y_Target`(已替代硬编码 420),期间遮光气缸落下拍照。
35 之后 8Y=0 且遮光上位。**故 align 若在 cam 拍照流程后进入,8Y 起点=0。**

### ⚠️ 8Y 绝对运动的硬互锁(`伺服调用` FB_SERVOAXIS_5)

```
xMoveAbs:= 拍照轴8YDATE.xMoveAbs AND  刮板拍照遮光气缸上位 AND 刮板轴10ZDATE.fActPos<6 ,
```

**8Y 只有在「遮光气缸上位 AND 10Z.fActPos<6(Z 处于顶部 6mm 内=安全高)」时才允许绝对运动。**
align_move(42) 走 8Y 前必须:① 遮光气缸在上位(init 后 `遮光自动:=FALSE`,气缸复位上位,须上机确认);
② Z 在高位。否则 `xMoveAbs` 被 AND 成 FALSE,轴不动,`bAbMoveDone` 永不到,动作挂死到 Reset。

---

## Q3 — 回零复用哪个既有块;42/43 能否直接调用

### 既有 Z 先/XY 后回零链在 `伺服一键回原点`

```
//刮板拍照回原点流程(仅手动): 10Z 回零后 9X,8Y
CASE HOME_1STEP OF
	1 : IF 刮板轴10ZDATE.bHomed THEN
			刮板轴10ZDATE.xHome := FALSE;
			刮板轴9XDATE.xHome := TRUE;
			拍照轴8YDATE.xHome := TRUE;
			HOME_1STEP := 2;
		END_IF
	2 : IF 刮板轴9XDATE.bHomed THEN 刮板轴9XDATE.xHome := FALSE; END_IF
		IF 拍照轴8YDATE.bHomed THEN 拍照轴8YDATE.xHome := FALSE; END_IF
		IF 刮板轴10ZDATE.bHomed AND 刮板轴9XDATE.bHomed THEN HOME_1STEP := 0; END_IF
END_CASE
```

排序正是 43 要的"先 Z 到位再 XY"。**但不能直接调用:**
- 触发门为 `R_TRIG_HomeAll(CLK := 一键回原点 AND MODE_State<>1 AND NOT ManualAuto)` —— 手动模式一键按钮,
  且**同时回全 11 轴**(含上样组),不是工位级动作。
- 用的是 `MC_Home`(`xHome`)=**回零参考行程**(找限位/原点开关),不是简单 MoveAbsolute 到 0。

### 43 的两个可复用惯例

**(a) MC_Home 逐轴**:复制 HOME_1STEP 排序(10Z.bHomed→9X/8Y.xHome),但每次 align_home 都跑一次
回零参考行程(慢、触限位),偏重。

**(b) MoveAbsolute 归位(推荐,照 A10_init)**:

```
6 : 刮板轴10ZDATE.fAbsTarget:=0; 刮板轴10ZDATE.xMoveAbs:=TRUE;
    IF 刮板轴10ZDATE.bAbMoveDone THEN 刮板轴10ZDATE.xMoveAbs:=FALSE; 初始化step:=10; END_IF
10: 刮板轴9XDATE.fAbsTarget:=335; 刮板轴9XDATE.xMoveAbs:=TRUE;
    IF 刮板轴9XDATE.bAbMoveDone THEN 刮板轴9XDATE.xMoveAbs:=FALSE; 初始化step:=20; END_IF
20: IF 刮板拍照遮光气缸上位 THEN
        拍照轴8YDATE.fAbsTarget:=0; 拍照轴8YDATE.xMoveAbs:=TRUE;
        IF 拍照轴8YDATE.bAbMoveDone THEN ... END_IF
    END_IF
```

保持已建立的坐标系、无参考行程。顺序天然满足"先 Z→0(令 fActPos<6)再 XY"(否则 XY 被 Z 门拦,见 Q5)。

### ⚠️ 9X"回零"目标歧义

A10_init 把 9X 停在 **335**(放板/上料位),**不是 0**;9X=0 是 MC_Home 参考后的机床零,可能位于/接近硬限位。
B11 决策:43 归位 9X 建议停 **335**(已验证的工位停放位),除非明确要机床零。8Y 归 0(须遮光上位),Z 归 0。

---

## Q4 — scrape(40) 对起始 XY 有无"从零位出发"假设

**A40 本身无首点进近**:它只 `CNC启动:=TRUE` 交给 g-code,所有运动(含首点进近段)由上位机生成的
`g_sx/g_sy/g_cx/g_cy` 路径定义,首点坐标写在 g-code 里,不假设从零出发。

进入 scrape 前的停放位由 init(A10)决定:**Z=0, X=335, Y=0**。故 align_home 归到
init 停放位(X=335/Y=0/Z=0)与后续 scrape 进场兼容,无冲突。

---

## Q5 — 软限位/行程常量在哪;42 的板区窗数值从哪取

### ST 内无软限位常量

`servo` struct、`GVL`、`servoaxisdate` 均无 min/max 行程字段。SoftMotion 软限位
(AXIS_REF_SM3 的 SWLimit)在**轴设备配置**里,`read_pou` 读不到 ST(在设备树/`.Device.Application.xml`)。

**唯一嵌在 ST 里的行程安全魔数** = `伺服调用` 互锁中的 `刮板轴10ZDATE.fActPos<6`
(XY 动作的 Z 高门),硬编码字面量,非具名 GVL 常量:

```
// 9X:  xMoveAbs:= 刮板轴9XDATE.xMoveAbs AND  刮板轴10ZDATE.fActPos<6,
// 8Y:  xMoveAbs:= 拍照轴8YDATE.xMoveAbs AND  刮板拍照遮光气缸上位 AND 刮板轴10ZDATE.fActPos<6,
// 10Z: xMoveAbs:= 刮板轴10ZDATE.xMoveAbs                     (无额外互锁)
```

### ⚠️ 该 Z 门与 spec §4"检查高度微调"直接冲突

Z 正向向下,Z=0 上=安全;`fActPos<6` = Z 在顶部 6mm 内。检查高度 = `plate_surface_z_mm − align_clearance_mm`
= 20.5 − 2.5 = **18.0**(> 6)。**在检查高度时,9X/8Y 的 xMoveAbs 被 AND 成 FALSE,XY 完全动不了。**
spec §4/§6 的"10Z 在检查高度 → 放行 ≤2mm 微调"在现有互锁下**物理不成立**。
- 主流程(Z=0 走位)OK:Z≈0<6,互锁放行。
- 检查高度处的 XY 微调:被 Z 门挡。B11/上机决策:要么放弃"高位微调"(微调前先 align_z(0) 抬起→在 Z=0 微调→再降),
  要么改互锁(越界,风险,不建议)。**推荐:所有 XY 走位强制 Z=0;检查高度只做纯 Z 观察不做 XY。**

### 42 板区窗数值来源

板区窗是**上位机侧概念**,PLC 无现成常量 → B11 须新增 PLC 兜底常量(字面 mm)。
host `eit_ptlc/config/app.yaml` gcode 段(只读参考):

```
plate_origin_x: 91.24        # 图像左下角机床 X
plate_origin_y: -75.2        # 图像左下角机床 Y(点样线底边)
plate_surface_z_mm: 20.5
machine_y_min_mm: -73        # 机床 Y 软下限(防撞机)
```

⚠️ **坐标系警示:** host 的 `plate_origin_y=-75.2` 为负,而 8Y 轴 `fAbsTarget` 实测走 0..420(A34 相机位 Photo_8Y_Target,
init 335 等均为正),**两者疑似不同坐标系**。align_move 的 TargetX/Y(spec 称"机床 mm")最终写进 9X/8Y 的
`fAbsTarget`,必须落在**轴坐标系**。因此 PLC 兜底窗须用**轴坐标(9X/8Y ActPos)**表达,
建议 B11/上机:jog 到板四角读 `刮板轴9XDATE.fActPos`/`拍照轴8YDATE.fActPos` 得板区实测范围 ±5mm 余量为窗,
**不要直接照抄 host 的 plate_origin**(可能差一个 frame 偏置)。Z 窗:下限 0,上限须 < plate_surface(20.5),
两档 {0, 18.0}。

---

## Q6 — 既有 MC_MoveAbsolute 速度典型值

### FB 侧默认 vs 实际接线

`FB_SERVOAXIS` 声明默认 `fVelocity: LREAL := 100.0`。但 `伺服调用` 里三条刮板轴的接线是:

```
fVelocity:= 拍照轴8YDATE.fVelocity ,    // 8Y(FB_SERVOAXIS_5), fAcc:=500.0, fDec:=500.0, fJogVel:=50.0
fVelocity:= 刮板轴9XDATE.fVelocity ,    // 9X(FB_SERVOAXIS_6), fAcc:=500.0, fDec:=500.0, fJogVel:=50.0
fVelocity:= 刮板轴10ZDATE.fVelocity ,   // 10Z(FB_SERVOAXIS_7), fAcc:=500.0, fDec:=500.0, fJogVel:=50.0
```

`fVelocity` 取自 **RETAIN PERSISTENT 的 DATE struct**(HMI 示教写入的持久值),**不是 ST 里的硬编码常量**。
PhotoScrape 各动作(A31/A34/A35/init)**都没设 fVelocity**,靠持久值跑。

### ST 里能读到的速度字面量

- `fAcc = fDec = 500.0`(三轴,`伺服调用` 硬编码)—— 这是可靠的加/减速基准。
- 唯一显式速度字面量:`伺服一键回原点` 里退避 `fVelocity := 5.0`(上样 5Z/4X 退避)。

### ⚠️ 给 B11

ST 无可靠"典型 MoveAbsolute 速度"(在持久 DATE.fVelocity 里)。**42/44 必须在 xMoveAbs 前显式写
`轴.fVelocity`,不能靠持久值。** 建议保守字面量:XY 走位 ≈ 30–50 mm/s;Z 缓降 ≈ 5–10 mm/s
(对齐 5.0 退避先例);fAcc/fDec 沿用 500(Z 缓降可更低)。spec§4"取典型 1/2"因无典型值可取,改为直接给保守常量。

---

## Q7 — GVL 符号配置挂载点

### 挂载 GVL = `Host_Computer`

新 6 节点全部进 `Application/20_变量Date/Host_Computer`(已含全部 `PhotoScrape_L2_*` 握手变量、
`Photo_8Y_Target`、`FeedLift_1Z_ActPos`(LREAL,命名先例)、`PhotoScrape_CamLocate/CamPress_Target`)。

spec §4 拟加(命名对齐 `FeedLift_1Z_ActPos` 惯例):

```
PhotoScrape_Align_TargetX : REAL;    // 机床/轴 mm, host 写
PhotoScrape_Align_TargetY : REAL;
PhotoScrape_Align_TargetZ : REAL;
PhotoScrape_9X_ActPos     : LREAL;   // PLC 写回显
PhotoScrape_8Y_ActPos     : LREAL;   // (见下:8Y 已有 Photo_8Y_ActPos)
PhotoScrape_10Z_ActPos    : LREAL;
```

### ✅ 8Y ActPos 已存在(减工作量)

`PLC_MainPRG` 顶部**无条件每扫描镜像块**(任意模式恒跑)已有:

```
// ===== 连续伺服实际位置镜像 (B方案, PLC->PC, 每扫描无条件; 供实时显示+jog标定采点) =====
Sampling_4X_ActPos := 上样轴4X轴DATE.fActPos;
Sampling_3Y_ActPos := 打样瓶上料轴3YDATE.fActPos;
Spot_6X_ActPos     := 点样轴6XDATE.fActPos;
Spot_7Y_ActPos     := 点样轴7YDATE.fActPos;
Photo_8Y_ActPos    := 拍照轴8YDATE.fActPos;      // <-- 8Y 已镜像!
FeedLift_1Z_ActPos := 玻璃上料轴1ZDATE.fActPos;
FeedLift_2Z_ActPos := 玻璃上料轴2ZDATE.fActPos;
Rail_ActPos := 地轨轴11YDATE.fActPos;
Rail_Homed  := 地轨轴11YDATE.bHomed;
Rail_Sync();
```

**8Y 实读已由 `Photo_8Y_ActPos` 提供。** 故 spec §4"5 个节点"对上了:真正新增 5 个
= TargetX/TargetY/TargetZ + 9X_ActPos + 10Z_ActPos(8Y 复用 Photo_8Y_ActPos)。
B11 若为命名对称仍想加 `PhotoScrape_8Y_ActPos`,则为 6 个;否则 host 侧直接读 `Photo_8Y_ActPos`。

**回显挂载点** = 上述镜像块尾,B11 追加:

```
PhotoScrape_9X_ActPos  := 刮板轴9XDATE.fActPos;
PhotoScrape_10Z_ActPos := 刮板轴10ZDATE.fActPos;
// (可选) PhotoScrape_8Y_ActPos := 拍照轴8YDATE.fActPos;
```

### Symbol Configuration(OPC UA 导出)

`eit_ptlc/plc/20260702.Device.Application.xml` 的 Symbol Configuration 把 Host_Computer 每个成员列为
独立 Node(按字母序),例如:

```
<Node name="FeedLift_1Z_ActPos" type="T_LREAL" access="ReadWrite" />   (line 4355)
<Node name="Photo_8Y_ActPos"    type="T_LREAL" access="ReadWrite" />   (line 4395)
<Node name="PhotoScrape_L2_ActionCode" type="T_INT" access="ReadWrite" /> (line 4400)
```

新 6(或 5)节点加进 Host_Computer GVL 后,用 CODESYS **Symbol Configuration 编辑器勾选包含**即自动生成
`<Node .../>`(REAL→`T_REAL`,LREAL→`T_LREAL`,access `ReadWrite`)。**不要手改这个生成的 XML。**

---

## Step 3 — 给 B11 的最终 ST 集成点清单

### 1) 派发器 CASE 插入(`Application/50_action/PhotoScrape_L2`)

现状(原文):

```
CASE PhotoScrape_L2_ActionCode OF
    10, 31, 32, 33, 34, 35, 36, 40, 41, 51, 52:
        PhotoScrape_L2_SafeState := 0;
        PhotoScrape_L2_State     := 10;   (* RUNNING *)
ELSE
    PhotoScrape_L2_ErrorCode    := 101;  (* 未知动作码 *)
    ...
```

- **IDLE 受理行**:把 `42, 43, 44,` 加进接受码表 `10, 31, 32, 33, 34, 35, 36, 40, 41, 51, 52:`。
- **RUNNING 派发 CASE**(现有 `CASE PhotoScrape_L2_ActiveCode OF` 里 40/41/51/52 之后)追加:

```
42: A42_align_move();
43: A43_align_home();
44: A44_align_z();
```

- 在 `Application/50_action/PhotoScrape_L2/` 下新建 3 个 action POU(A42/A43/A44),复用现有 step 变量惯例
  (可新增 `alignstep: INT` 到 PhotoScrape_L2 声明,照 `初始化step/拍照step/刮板收集step`)。
- **42/43/44 确认空闲**:现 CASE 无 42/43/44,落 ELSE→ErrorCode 101。核对通过。

### 2) 兄弟守卫报错样例(`FeedLift_L2/A11_feed_raise` 原文)

```
IF FeedLift_1Z_SearchLowTarget >= FeedLift_1Z_SearchHighTarget THEN
    FeedLift_L2_ErrorCode := 303;
    上料step := 0;
    bActionError := TRUE;
END_IF
```

派发器把 `bActionError` 接成 State 40(ERROR)+ `Retryable:=TRUE`,`ErrorCode 由原子置`。
PhotoScrape 等价写法:`PhotoScrape_L2_ErrorCode := <码>; alignstep := 0; bActionError := TRUE;`。
(FeedLift 亦用 `FeedLift_L2_Step` 区分失败阶段,PhotoScrape 可同法用 `PhotoScrape_L2_Step`。)

### 3) 轴绝对运动样例(`A31_cam_移轴335` 原文,+ B11 须补的显式设速)

```
刮板轴9XDATE.fAbsTarget:=335;
刮板轴9XDATE.xMoveAbs:=TRUE;
IF 刮板轴9XDATE.bAbMoveDone THEN
    刮板轴9XDATE.xMoveAbs:=FALSE;
    bActionDone:=TRUE;
END_IF
```

B11 版(补 fVelocity,见 Q6;并注意 8Y/9X 的 Z 门 + 8Y 遮光门,见 Q2/Q5):

```
刮板轴9XDATE.fVelocity := 40.0;          // 显式保守速度, 别靠持久值
刮板轴9XDATE.fAbsTarget := <TargetX>;
刮板轴9XDATE.xMoveAbs := TRUE;
IF 刮板轴9XDATE.bAbMoveDone THEN 刮板轴9XDATE.xMoveAbs := FALSE; bActionDone := TRUE; END_IF
// 前置守卫: 目标在板区窗内 & (Z=0 或微调) & (走 8Y 时遮光上位)
```

### 4) 错误码段分配建议

- PhotoScrape_L2 现仅用 **101**(未知动作码)。ErrorCode 是**每工位独立变量**
  (`PhotoScrape_L2_ErrorCode`),跨工位不冲突,只需在 PhotoScrape 命名空间内避开 101。
- 建议 align 专段 **421–424**(与 42x 动作助记):
  - `421` = Z 门拒动(10Z 既非 0 档也非检查高度档 / 目标超 Z 门)
  - `422` = XY 目标超板区软限位窗
  - `423` = 检查高度处 XY 微调超 ≤2mm(若采纳"高位微调"路线;否则不需要)
  - `424` = 缓降(44)时 XY 不在板区窗内
  - (可留 `425` = 遮光气缸未上位致 8Y 无法移动的显式拒动,替代"挂死到 Reset")
- **host 侧须在错误码映射表登记 (station=photo_scrape, code=421..425) → 中文提示。**

### 5) 板区软限位窗数值 + 依据

- **PLC 无现成软限位常量;须 B11 新增字面 mm 兜底常量。**
- Z:两档 `{0.0, 18.0}`,`18.0 = plate_surface_z_mm(20.5) − align_clearance_mm(2.5)`;
  上限恒 `< 20.5`(永不触板面)。现有 XY-走位 Z 门阈值 = `刮板轴10ZDATE.fActPos < 6`。
- XY:**用轴坐标(9X/8Y ActPos)表达**,数值上机 jog 到板四角实测 ±5mm 余量;
  **勿直接照抄 host `plate_origin`**(host frame 与 8Y 轴 frame 疑似不同,见 Q5 坐标系警示)。
  上机前占位建议:X∈[板 X 实测下限−5, 上限+5],Y∈[板 Y 实测下限−5, 上限+5]。
  参考:host app.yaml `plate_origin_x=91.24 / plate_origin_y=-75.2 / machine_y_min_mm=-73`;
  init 停放 9X=335、8Y 相机位 Photo_8Y_Target(旧硬编码 420)。

---

## 未决项(B11 / 上机确认)

1. **CNC↔单轴 MC 组轴归还时序**(Q1):`CNC完成` 后同周期能否 MoveAbsolute。上机验一次。
2. **Z 门 vs 检查高度微调冲突**(Q5):`10Z.fActPos<6` 挡住检查高度处 XY。决策=强制 XY 走位在 Z=0
   (推荐),还是采纳高位微调(需改互锁,不建议)。
3. **9X 归位目标 0 vs 335**(Q3):建议 335(工位停放位);若要机床零改用 MC_Home 参考行程。
4. **8Y 遮光上位前置**(Q2):init 后气缸复位是否 = 遮光上位;align 走 8Y 前须置/确认遮光上位。
5. **保守速度定值**(Q6):XY 30–50 / Z 缓降 5–10 mm/s 待上机试定;ST 无典型值可照抄。
6. **板区 XY 窗轴坐标实测**(Q5):jog 读 9X/8Y ActPos 定板四角范围;host↔轴 frame 偏置核对。
7. **8Y_ActPos 复用还是新增别名**(Q7):`Photo_8Y_ActPos` 已可用;是否加 `PhotoScrape_8Y_ActPos`。
