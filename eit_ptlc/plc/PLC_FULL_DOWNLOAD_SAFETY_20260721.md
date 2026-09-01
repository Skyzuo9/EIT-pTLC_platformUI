# PLC 完整下载与启动安全说明

适用工程：`20260702.project`。

## 正常完整下载

上位机入口会依次执行：编译、工程快照、获取全局维护锁、设备空闲检查、PLC 安全准备、完整下载、OPC UA 重连、5Z 回零、4X 回零和 READY 核对。

从编译开始直到 READY/失败结果确定，部署持有同一个工程级互斥锁。期间 POU 保存（包括
`save=false` 的 InoProShop 内存编辑）、符号导出修改和历史版本还原均返回 HTTP 409，不能在
安全握手等待窗口插入并改变实际下载内容；部署进度也只有真正取得该锁的请求才能初始化。

该互斥不仅是 FastAPI 进程内锁。`deploy.guard.json` 是 Python 客户端、Node MCP 和 worker
共同执行的持久事务守卫；创建守卫时与 `write.lock` 原子互斥，锁带随机 owner token，活 PID
不会仅因超时被夺锁，释放前必须再次核对 token。守卫期间禁止 write/save/compile/
generate-code/restore/takeover/shutdown 和第二次 deploy；若 Host 崩溃，守卫不会按 PID 自动失效。

真正下载还必须通过一次性授权：授权绑定 worker 实例 ID、60 秒有效期、PLC 提交序号、目标
PLC IP、下载前工程 SHA-256、协议 v3 和 `worker_body.py` 内容 SHA-256。Host 启动后若 worker
源码发生变化，会在创建守卫和签发授权前失败关闭，必须同时重启后端与 worker。worker 先把
deploy 请求原子改名为 `claimed`，再把授权票据从
`pending` 原子改名为 `consumed`；任何一步失败都不能进入 `oa.login`。worker 重启发现遗留
`claimed` 请求时只返回“结果不明确、禁止重放”，绝不再次执行。上位机在授权前完成编译、保存
与快照；worker 不再二次保存（InoProShop 每次保存都会改写易变容器元数据），而是在 login 前
重新校验受守卫保护的磁盘 SHA。进入共享 `deploy.physical.lock` 临界区后再次按配置 IP 设置通信路径、创建在线
句柄并回读目标，随后重新核验守卫、票据、有效期和工程哈希，才允许调用 `oa.login`。空 IP、
路径/回读失败、票据过期或 SHA 改变均明确返回 `downloaded=false`。物理锁释放失败会保留
`downloaded=true/false` 的真实结果，但强制 `ready=false、retryable=false` 并保持维护门，
下载台账只允许标记 worker 返回并与授权一致的精确 SHA。

部署守卫采用两阶段释放：先把 `active` 原子改为 `releasing`（此时 worker 已不能再登录），
再确认自身 `deploy.physical.lock` 已删除，最后才删除守卫。进程在任一边界崩溃都会留下可识别、
默认拒绝继续下载的状态。人工对账可恢复 `releasing` 守卫；若只剩物理锁，则仅在 owner token
完整且 owner PID 已确认死亡时清理。完成审计只在锁和守卫均确认删除后落盘。

PLC 仅在以下条件全部成立时进入 `PLC_Deploy_State=20`：

- 所有 L2 工位空闲；
- `Sampling_Servo_FreeMove=FALSE`（2026-07-28 起上位机已无写者，见下文，但守卫保留）；
- 手轮全部脱开，11 轴静止；
- 所有气缸/电磁阀输出和原始手自动命令均为 FALSE；
- `Develop_TankDrain` 无 Enable、无 50/55/56 在途状态，`大真空泵站位[0..11]` 全部撤票；
- 泵串口无在途占位或待发送数据；
- EtherCAT 为 OP，13 个从站在线，11 轴通信正常；
- 11 轴 `MC_Power.Status=FALSE`。

`PLC_Deploy_Start=TRUE` 是请求方对“可下载”状态的所有权锁。上位机在调用 CODESYS worker 前还会写入匹配的 `PLC_Deploy_CommitSeq`，PLC 随即进入不可由普通 HMI 取消的 `State=25`。取消普通准备时必须先写 `Start=FALSE`，再给 `Reset` 一个脉冲。完整下载后由新应用重新初始化该通道。

`State=30` 只表示“设备忙，拒绝本次准备”：PLC 会阻止新的下载/L2 请求，但继续保留既有
轴使能、运动、手轮、排液和真空控制，绝不因误点“准备下载”中止正在执行的动作。`10/20/25/40`
才属于去使能/闭锁状态；状态 30 也必须按正常取消顺序回到 0 后才能再次准备。

进入维护态后以及下载后 `PLC_Ready=FALSE` 的整个启动/自动回零窗口内，气缸/电磁阀命令、
真空泵、泵探针和自主排液 FSM 均被 PLC 侧闭锁。期间写入的气缸手自动位、12 个真空泵站位
或 `Tank_Drain_Enable` 不会在 Ready/解锁时补执行：对应请求必须先全部回到 FALSE，控制路径
才重新装载。错误码 `3` 表示准备请求时仍有辅助执行器活动；`42` 表示准备阶段的
辅助安全条件被破坏；`41` 表示可下载/已提交状态的轴或辅助安全不变量被破坏。后三者都不
允许继续下载。

泵管理和排液 FSM 在 `PLC_Ready=FALSE` 或真实维护态（10/20/25/40）期间继续每扫描运行，
用于撤防旧请求。8 个 L2 调度器则只在本站 `L2_State=0` 时进入一次安全门，拒绝新的 Start；
已经处于非空闲状态的 L2 在“停止模式 + Ready 丢失”时不会继续推进物理 FSM。这样既不会
在取消准备或切回运行模式后把旧 TRUE 当成新命令执行，也不会让被停止的在途动作意外前进。
State 30 仍排除在维护扫描条件之外。

完整下载初始化和整个启动/维护窗口还会持续清除 6 组 `HMI_Servo.execute/write`、
`一键回原点`、1Z/2Z 的 4 个直连 Jog 输入以及 `Sampling_Servo_FreeMove`。这些变量包含
RETAIN/PERSISTENT 或绕过 `ServoAxisDate` 的运动源，仅清派生的 `xMoveAbs/xJog` 不足以防止
Ready 后补执行。

孔板标定期间的下载互斥由**上位机单点会话**承担：`ManualService.enter()` 取
`gate.try_enter_activity("PC 单点控制会话")`，`exit()` 才释放，会话另有 3.5 s TTL 与 PLC 侧
3 s 心跳看门狗兜底进程崩溃。它比原先那条"去使能手推 ActivityLease"更严——除挡住下载外
还让 `ActionExecutor` 拒收 `plc_l2/plc_write/servo_target/rail_ensure`。

> 2026-07-28 变更：`POST /api/calibration/manual/enter|exit`（写 `Sampling_Servo_FreeMove`
> 去使能 4X/3Y 供手推）已删除——那条路在 PLC 侧是自毁循环（去使能两轴 ⇒ `bAllAxesEnabled`
> 假 ⇒ `PLC_Ready` 假 ⇒ 排空块把 `Sampling_Servo_FreeMove` 抹掉 ⇒ 轴立刻回电），从未真正
> 生效。分析见 `docs/单点控制_PC_Manual_Mode.md` §10。节点与 `_deploy_idle_guard` 里的
> `sampling_free_move_active()` 守卫保留，但上位机已无写者。

## 物理 HMI（本机不启用下载按钮）

本机没有可维护的物理 HMI 工程，且现场决定不增加“准备 PLC 下载/取消准备”按钮；这不影响
上位机自动安全下载路径。首次安装新握手固件完成后，后续完整下载必须统一从上位机
“下载到设备”入口发起，禁止直接在 InoProShop 中绕过握手全下载。

如果未来重新增加物理 HMI 下载入口，才需要按以下方式绑定：

HMI“准备 PLC 下载”按钮：

1. 先写 `PLC_Deploy_Start=FALSE`；
2. 递增并写入 `PLC_Deploy_RequestSeq`；
3. 写 `PLC_Deploy_Start=TRUE`；
4. 仅当 `PLC_Deploy_State=20` 且 `PLC_Deploy_AcceptedSeq=RequestSeq` 时显示“可下载”。

HMI“取消准备”按钮：先写 `Start=FALSE`，再脉冲 `Reset`，等待 `State=0`。状态 30/40 的错误码必须显示，禁止继续下载。

`State=25` 表示上位机已经提交非幂等下载，普通“取消准备”必须禁用。只有已人工确认 worker 尚未登录/下载时，维修人员才可执行“清 `CommitSeq=0` → `Start=FALSE` → 脉冲 `Reset`”的强制解锁顺序。

PLC 已在启动抑制期屏蔽 11 个公开 `*DATE.bError/iErrorCode` 出口，并屏蔽现有汇总
EtherCAT/伺服/未回原点报警。HMI 若直接使用 `NOT *DATE.bHomed` 等自定义条件，仍必须增加：

`原报警条件 AND NOT PLC_Startup_AlarmInhibit`

现有物理 HMI 的报警历史仍需在首次现场验收时确认。如果它直接使用
`NOT *DATE.bHomed` 等原始条件而不是 PLC 已抑制的公开报警位，仍须取得 HMI 工程并补上
`PLC_Startup_AlarmInhibit` 条件，之后才能宣称“启动成功时报警历史零新增”。

## 手动回零不再产生报警（2026-07-28）

`伺服未回原点报警` 原先是**置位锁存**：任一轴 `NOT bHomed` 即置 TRUE，而只有柜面 `复位`、
`bSysReset` 或开机自动回零的 `bAutoHomeResetPulse` 能清。偏偏回零的第一件事就是清 `bHomed`
（`伺服一键回原点` 给 11 根轴逐个 `bHomed:=FALSE`），于是**每按一次手动回零必然点亮它，
回零完成也不自灭**，`xFault` 一直挂着把整机焊在 `FB_Mode` 的故障态，必须有人跑去按柜面复位。

`A00_设备状态显示及控制` 现在这样收口（判据全取自全局量，无需跨 POU 取 `PLC_Servo_伺服`
的内部步号）：

- `bHomingActive := 一键回原点 OR 任一 <轴>DATE.xHome`。`一键回原点` 要等 11 轴齐 `bHomed`
  才自清，因此连 5Z/4X「退让 10 mm 期间没有任何 `xHome` 置位」的间隙也被盖住。
- `bHomingAlarmInhibit` 是它经 `TOF PT:=T#1S` 的关断延时——本 POU 在主任务，`xHome`/`bHomed`
  由 EtherCAT 任务的 `伺服调用` 在同一扫描翻转，两者不同步。延时只推迟“重新武装”该报警。
- 置位改为互补结构：**全轴已回零 ⇒ 无条件清**；否则仅当 `NOT (bHomingAlarmInhibit OR 一键回原点)`
  才置位。
- 手动回零完成后发 1.5 s 的 `bHomeResetPulse` 喂 `FB_Mode.xReset`（照抄 `bAutoHomeResetPulse`
  的写法，带 `PLC_Ready` 门避开开机窗口），让设备能自己退出故障态。它**不**并进末尾那个
  “清所有报警”的块，以免顺手抹掉真实的气缸/料架报警。

上位机侧同步去掉了 `ManualService.axis_home()` 里的 `bHomed:=FALSE` 预清，终态判据改用
PLC 自清 `xHome`（`IF 回零完成nX THEN xHome:=FALSE; bHomed:=TRUE`）+ `bError` 兜底。

⚠️ 同上一节：若物理 HMI 的报警条目直接读 `NOT *DATE.bHomed` 而不是 `伺服未回原点报警`
汇总位，本节改动对 HMI 报警历史无效（三色灯/蜂鸣器/`MODE_State` 仍会修好）。现场验收时
一并确认。

## 首次安装新握手固件

旧固件没有 `PLC_Deploy_*` 节点，因此首次安装不能走自动部署入口。必须：

1. 现场人员清空 5Z/4X 的至少 10 mm 退让和完整回零路径并守在急停旁；
2. 停止全部工艺、手轮、点动、机器人和 L2 动作；
3. 人工确认全部泵、排液、气缸和电磁阀已处于允许掉电的安全位置，再确认所有轴静止并撤销伺服使能；
4. 在 InoProShop 中编译 0 错误、核对工程快照后执行一次完整下载；
5. 观察 5Z 先以 5 mm/s 正向退让 10 mm 并回零，再观察 4X 同序动作；
6. 任何方向、限位极性或空间不符合预期时立即急停，不从中间步骤续跑。

当前工程按汇川 CiA402 映射读取 `0x60FD`：bit0=负限位、bit1=正限位、bit2=原点；
正限位已动作或正向软件限位不足 10 mm 时，PLC 会在发运动命令前以 5Z=`515`、4X=`514`
终止启动。该映射不能代替现场接线、有效电平和平台坐标方向验证，因此仍保留现场既有的
“正向 10 mm 退让”机械约定；完成首次低速确认并记录实际极性前不得无人值守下载。

## 失败处理

- 下载前失败：确认 `downloaded=false` 后可排障再试。
- 下载结果不明，或已下载但 `PLC_Ready=false`：禁止自动重发；人工核对在线版本、EtherCAT、驱动器面板码和启动错误码。
- CODESYS 请求超时会尽力删除尚未认领的请求并撤销尚未消费的一次性票据；若请求或票据已经被 worker 认领，则按“结果不明”处理，持久维护锁和部署守卫都不得自动释放。
- worker 登录前上位机会把维护锁原子持久化到 `var/plc-deploy-maintenance.json`；进程重启后继续锁住动作与再次下载。下载前退出准备态时也只有重新确认 `Startup=60`、`PLC_Ready=TRUE`、`Deploy=0` 才释放；复位/通信确认失败则保持锁。
- 对账入口为 `POST /api/plc/deploy/reconcile`。现有工具无法读取控制器应用哈希，所以操作员必须先在 InoProShop 人工核对在线版本，再明确确认；接口随后只读核对上述三个状态，先审计并清除跨进程部署守卫，再释放维护锁，不写 PLC、不下载、不发运动。`State=90` 绝不能直接解锁。
- 启动回零期间急停：状态进入 90；排除风险并复位后，从等待总线重新开始，不从中间步骤继续。

每次更新 `worker_body.py`、目标工程路径、PLC IP 或 IPC 协议后，旧的常驻 worker 都不再可用。
必须在无请求、无活动部署守卫、无人工接管且无物理下载在途时受控关闭，再由新客户端启动；
只有 `worker.status` 中 project、plc_ip、protocol_version、worker_body_sha256 和 instance_id
全部匹配才允许自动部署。
