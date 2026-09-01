# 单点控制 (PC Manual Mode)

把 HMI 触摸屏"手动档"下的每模块单点操作搬到上位机，**不需要拧柜面的手/自动旋钮**。

## 1. 电子手动档

HMI 手动屏的按钮之所以"切到手动档才可用"，是因为每个执行器的 `FB_cylinder` 里：

```
IF xManualAuto THEN  bEnableCmd1 := xAutoExtend;    // 自动档: 只看 <设备>自动
ELSE                 bEnableCmd1 := xManualExtend;  // 手动档: 只看 <设备>手动
```

而 `xManualAuto` 接的就是柜面旋钮镜像 `GVL.ManualAuto`。所以上位机在自动档下直接写
`<设备>手动` 位是**无效**的 —— 这是本功能必须动 PLC 的根本原因。

做法是给上位机一个**电子手动档**：新增 PROGRAM `Application/40_Man/PLC_PCManual` 算出
`PC_Manual_Active`（含心跳看门狗与下降沿清扫），在 `PLC_MainPRG` 里于
`PLC_Cyinder_气缸动作()` 之前调用；再把它接进 `A00_设备状态显示及控制` 的 `FB_Mode`：

```
xAutoMode := 手自动 AND NOT PLC_PCManual.PC_Manual_Active,
```

上位机一进单点，整机就切到手动档 —— **等效于有人把柜面旋钮拧到手动**，机器不会进入
任何它没被设计过的状态。于是上位机**只写 `<设备>手动` 位**（与 HMI 手动屏同一批位），
`<设备>自动` 一根手指都不碰。

> 早期版本走的是"自动档下同时写手动位和自动位"，为的是不改那 51 处气缸调用。
> 代价是与 HMI／流程抢 `<设备>自动`：HMI 上的自动位显示会乱亮、`Pump_Vacuum_On`
> 镜像被写脏、运行态下还会被 `PLC_Pump_泵管理` 每扫描覆盖。电子手动档一次性消掉这些。

白捡的两个结构性好处：

- `FB_Mode` 的 `ELSIF (bAuto AND xStart)` 决定**手动档下「启动」不被接受** ——
  单点会话激活期间机器根本无法被启动进运行态，不必在软件里另设防线。
- 手轮读的是**原始物理输入**（`bHandWheelAllowed := … AND NOT 手自动`），
  电子手动档不会把手轮放出来，这是有意为之。

伺服轴**不需要任何 PLC 改造**：`FB_SERVOAXIS` 的 `bNormalMotionAllowed` 只要求
通信正常 + 已使能 + `PLC_Ready` + 不在下载窗口，与档位无关。

`伺服一键回原点` 的 `NOT ManualAuto` 条件在电子手动档下自然成立；那里另加的
`OR PLC_PCManual.PC_Manual_Active` 现在是冗余的，留作双保险。

## 2. 生效的必要条件

`PC_Manual_Active` 为真才允许下发，任一条失守立即落下并清扫：

| 条件 | 拒绝码 | 说明 |
|---|---|---|
| 上位机心跳 3s 内有跳变 | 1 | 断网 / 后端崩溃 / 前端卡死自动收口 |
| 8 个工位 L2 全部非 RUNNING | 2 | 与上位机自身的动作 / 流程互斥 |
| `PLC_Ready` | 3 | |
| `PLC_Deploy_State ∈ {0,30}` | 4 | 与 PLC 全下载维护窗口互斥 |

**不要求设备处于停止态**。既然不写自动位，L2 派发器和 `PLC_Pump_泵管理` 写什么都被
`FB_cylinder` 忽略，两个写者的问题根本不存在；而手动档下机器又启动不起来。所以运行态
也能直接进单点，不必先把设备停下来。

设备停机/开机另有一对独立按钮（与单点模式无关，纯粹省一趟腿）：`A00_设备状态显示及控制`
里 FB_Mode 的接线是

```
xStart := 启动 OR PLCStart      // 柜面按钮 或 上位机
xStop  := NOT 停止 OR PLCStop
```

`PLCStart` / `PLCStop` 是 `Host_Computer` 里的 PC 可写位，即上位机与柜面按钮并联。
两个位都是**脉冲用法**——一直压着 `PLCStop` 会把机器焊死在停止态，所以服务层在
`finally` 里必定撤位。停机前会跑与进入单点同一套空闲检查，免得把在跑的流程冻在半路；
恢复运行要求先退出单点会话且在自动档（刚退出时电子档位要一个扫描周期才交还，故会轮询等待）。

## 3. 三层防卡死

OPC UA 写进去的是**电平**不是脉冲 —— 上位机若在阀通电、轴点动时崩溃，PLC 侧不会自己松开。

1. **前端**：`pointerup / pointercancel / lostpointercapture` + `visibilitychange / blur / pagehide` 立刻发 `jog/stop`
2. **后端**：jog 续订窗口 0.8s（前端按住期间每 300ms 续一次）；会话 TTL 3.5s（任一面板交互都算续期）
3. **PLC**：`PLC_PCManual` 的 3s 心跳看门狗；`PC_Manual_Active` 下降沿一次性清扫
   51 个执行器的**手动位**与 11 根轴的 `xJogPos/xJogNeg/xMoveAbs/xMoveRel/xHome`
   （不清 `xStop`/`XReset` —— 安全与清错方向）

> **退出是无缝的**：只清手动位，自动位从头到尾没被碰过。档位一交还回自动，
> 各执行器立刻接着听流程的自动位，不会出现"退出后全机断电"。

> ⚠️ 反过来，**进入**单点的那一刻等价于拧旋钮到手动：此前由自动位保持通电的执行器
> 会立即断电（因为对应的手动位默认是 FALSE）。这与实体旋钮的行为一致。

## 4. 互斥关系

- 单点会话激活 → `ActionExecutor` 拒绝 `plc_l2 / plc_write / servo_target / rail_ensure` 类动作
  （`robot / camera / vision` 照常放行）
- 单点会话激活 → 持有 `MaintenanceGate` 活动租约 → PLC 全下载抢不到门
- PLC 处于维护态 / 有 L2 在 RUNNING / VM 有流程在跑 → 拒绝进入单点会话

## 5. 使用

设备页 `/nodes/plc.<工位>`（如 `/nodes/plc.develop`）→「进入单点模式」。
需要 **DEBUG** 控制模式（顶部态势条切换）。设备若在运行态，会先弹窗问你要不要停机
（见 §2），确认后自动停；调试完点「恢复运行」把机器交还给流程。

孔板标定页 `/points/calibration` 也内嵌了一份**只含上样三轴**（5Z/4X/3Y）的点动条：
「开始标定」即进同一个单点会话（store 单例，与设备页共享），点动/步进对准锚孔后
就地「采点」，「结束标定」退出。它替掉了 2026-07 之前那套「去使能手推」——
那条路在 PLC 侧是个自毁循环，见 §10。

面板顶栏实时显示档位（`ManualAuto`）、设备状态（`MODE_State`）、气缸报警字，
以及未生效时 PLC 给出的具体原因。

- **执行器**：开 / 关两个按钮（单控阀，电平二态），旁边是原点/动点到位灯。
  36 个电池阀类 PLC 未接到位传感器，只显示命令态。
- **伺服轴**：按住点动（速度是 PLC 硬编码常量，**不可调** —— `<轴>DATE.fJogVel`
  在 `伺服调用` 里未接线，写了无效）；回零 / 停止 / 清错；绝对与相对定位（速度按点表 `vel_max` 限幅）。
- **一键回原点**：触发 PLC 内既定次序的全轴回零，下发前会先撤掉本会话的所有点动/定位命令位。

## 6. 实机 OPC UA 寻址的两个坑

2026-07-28 首次连真机（192.168.0.50）时踩到的，**都无法从符号配置 XML 或 sim 推断**，
以后新增中文点位时会再遇到：

**① PROGRAM 实例挂在 `Programs` 下，不和 GVL 同层**

符号表里 GVL 和 PROGRAM 实例都平铺成 `Application/<容器>/<变量>`，但 browse 树不是：

```
Application/
├── Programs/     ← PROGRAM 实例 (PLC_PCManual)
├── Tasks/
└── GlobalVars/   ← GVL (cyinder_date / GVL / HMI_Date / Host_Computer / IO / servoaxisdate)
```

`manual_points.yaml` 的 `containers.search` 因此给的是候选前缀列表
`[[GlobalVars], [Programs], []]`，驱动按序探测并缓存命中项。

**② 含中文的 BrowseName 是 GBK 字节被按 UTF-8 解码**

汇川/CODESYS 的 OPC UA 服务器用 PLC 本地代码页（GBK）编码标识符，asyncua 按
UTF-8 + surrogateescape 解码，中文就碎成一串孤立代理字符。实测 `大真空泵手动` 取回来是
`\udcb4\udcf3\udcd5\udce6\udcbfձ\udcc3\udccaֶ\udcaf`（`\udcb4\udcf3` = 字节 B4 F3 = GBK 的"大"）。

**纯 ASCII 名字不受影响**——这就是既有系统一直没暴露该问题的原因：`plc_nodes.yaml` 锁定的
`Host_Computer` 里全是 ASCII 名。修复在 `driver/opcua_driver.py` 的 `_recover_browse_name()`
（`encode('utf-8','surrogateescape').decode('gbk')`），名字匹配处同时接受原始名与还原名，
所以 mock 的正规 UTF-8 名和真机的 GBK 名走同一套代码。mock 模拟不了这一层，
回归测试在 `tests/test_manual_points_config_offline.py`（用真机抓到的原始串做断言）。

## 7. 关键文件

| 位置 | 作用 |
|---|---|
| `Application/40_Man/PLC_PCManual` | PLC 侧握手 / 判定 / 看门狗 / 清扫 |
| `eit_ptlc/config/manual_points.yaml` | 点表（51 执行器 + 11 轴，名字逐字来自 PLC 声明） |
| `eit_ptlc/controller/manual_service.py` | 会话、下发、状态批量回显、审计事件 |
| `eit_ptlc/api/manual_routes.py` | `/api/manual/*` |
| `eit_ptlc/driver/opcua_driver.py` | `resolve_ext_node / read_ext / write_ext / read_ext_batch` |
| `eit_ptlc/mock/manual_plc.py` | sim 模式的容器树 + PLC 行为仿真 |
| `eit_ptlc/web/src/components/StationManualPanel.vue` | 工位面板 |
| `eit_ptlc/web/src/components/CalibratePanel.vue` | 孔板标定页内嵌的上样三轴点动 |
| `eit_ptlc/web/src/composables/useAxisJog.js` | 按住点动（代次令牌 + pointer capture + 窗口安全停），两个面板共用 |

## 8. 真机灰度顺序

1. **只读回显**：部署 PLC 改动 + 符号导出后，先只看面板状态，核对 51 个执行器的到位反馈
   与 11 根轴的 `fActPos` 与 HMI 显示一致。不写任何位。
2. **单气缸**：选无互锁、动程可见的（如 `上样定位气缸`），旋钮留在自动档，进入单点 → 开/关各一次。
   分别验证 **正常退出 / 拔网线 / 杀后端** 三条路径都能清扫（用 InoProShop 在线监视 `cyinder_date` 确认）。
   同时确认 `PC_Manual_Active=FALSE` 时自动流程行为无变化。
3. **轴点动**：选行程长、无碰撞风险的（如 `拍照轴8Y`），验证三层停。再验回零 / 停止 / 定位。
4. 按工位分批放开；最后验一键回原点。
5. 跑一遍完整流程，确认单点未激活时零行为变化。

> ⚠️ 点动在 PLC 侧**没有互锁**（定位有：8Y 需遮光气缸在上位且 10Z<6；9X 需 10Z<6；
> 4X 需 5Z<3）。点动前请自行确认运动区域安全。

## 9. 设计偏离说明

`docs/pTLC下一阶段_生产调度与设备节点_完整落地计划.md` 约定"设备节点页不增加第二套
直接驱动按钮，必须走统一 Action API"。本功能是**经用户明确要求的例外**：HMI 手动位是
电平、点动是按住持续，与"一发一终态"的原子动作模型不适配。补偿措施是
审计事件进事件总线（监视器可见）+ 三重互斥 + DEBUG 门控 + 三层防卡死。

## 10. 为什么孔板标定不用"去使能手推"（2026-07-28 废弃）

标定页原先有一对「进入/退出手动校准（去使能）」按钮，只写一个位
`Sampling_Servo_FreeMove`。**它从来没真正生效过**，有三条独立原因：

**① 自毁循环（主因）**。`伺服调用` 里 4X/3Y 的使能是

```
xEnable := 急停 AND NOT (Sampling_Servo_FreeMove AND (上样轴5Z轴DATE.fActPos < 3))
```

而 `PLC_Servo_伺服` 状态机 60 又有 `PLC_Ready := bAllAxesEnabled AND ...`，
`bAllAxesEnabled` 是 11 根轴 `bEnabled` 的与、**含 4X 和 3Y**；同一 POU 末尾的排空块还有
`IF (NOT PLC_Ready) OR ... THEN ... Sampling_Servo_FreeMove := FALSE; END_IF`。于是：

```
写 FreeMove=TRUE → 4X/3Y 掉使能 → bAllAxesEnabled=FALSE → PLC_Ready=FALSE
  → 排空块把 FreeMove 抹成 FALSE → 下一扫描轴重新上电 → PLC_Ready=TRUE → 循环
```

后端只在 enter 时写一次、不重申，请求位在几十毫秒内被 PLC 自己清掉，两根轴闪一下就回电。
期间 `PLC_Ready` 抖动还会连带压掉 11 个轴报警出口、让 8 个 L2 派发器对新 Start 回 190、
手轮失效、`一键回原点` 被排空块清掉。

**② 5Z 抬起是硬前置**。`fActPos < 3` 不成立时整个 AND 恒假，按钮完全无效。

**③ 5Z 自己永不释放**。它的 `xEnable` 只有 `急停`，三根轴里最关键的那根从设计上就推不动。

（与抱闸无关：全 PLC 工程没有任何抱闸控制位，抱闸由驱动器参数自理。）

要修 ① 得改 `PLC_Ready` 让它排除"被 FreeMove 合法去使能"的两轴、并收窄排空块的清位条件；
修完 ③ 还要给垂直轴确认机械抱闸，否则掉电即坠。权衡后直接改走单点模式的电动点动：
三轴全覆盖、`axis_move(mode='rel')` 可做 0.01 mm 微调、有现成的三层防卡死。
`Sampling_Servo_FreeMove` 节点本身保留（`bootstrap._deploy_idle_guard` 仍防御性读它），
但上位机不再有任何写者。
