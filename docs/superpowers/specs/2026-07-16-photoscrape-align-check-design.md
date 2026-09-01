# 拍照刮板对位检查(align)+ 矫正帧原点标注 — 设计 spec

日期: 2026-07-16
状态: grilling 定案待 plan
分支: codex/ui-upper-next
相关 spec: 2026-07-15-photoscrape-scrape-closedloop-design.md(包2/包3 已实施)
相关 memory: ptlc-photoscrape-bias-closedloop / ptlc-cnc-gcode / ptlc-l2-stations

---

## 1. 背景与目的

真机观察到刮取 band 相对手绘 band 存在 y 向恒定偏移, 难点是无法区分偏差来自
**相机侧**(标角/识别把照片像素换算成板上 cm 的那一步)还是**机床侧**(对刀,
即 `plate_origin_x/y` 标定)加**刀尖装配偏置**。

已有部件与本 spec 的分工:

- 矫正帧收编(包3, 已实施): 手点四角后画布当场换成"程序认为的板", 用户在矫正图上画路径, 可一键重标。
- 刮后对账照片(包2, 已实施): 刮完补拍 + 叠同一 preview payload, 三链总偏差的唯一影像凭据。
- **缺口 A**: 画路径之前, 矫正图上没有原点/坐标系标注(标注层只在 cnc_path 之后的门预览图出现)。
- **缺口 B**: 刮前没有任何机床侧探针 —— 预览叠加是自洽闭环, 对刀偏差在图像域正逆抵消永远"完美"。

本 spec 补这两个缺口: A=HitlModal 原点标注(相机侧核对); B=刀头对位检查动作(机床侧核对, 刮前唯一探针)。

## 2. 决策记录(grilling 2026-07-16, 用户逐条拍板)

| # | 决策 |
|---|---|
| Q1 | 图上原点标注 = **相机侧(标角)核对专用**; 对刀核对交给刀头走位。图例明示"验证标角, 不验证对刀" |
| Q2 | 走位目标: **原点角 + 路径起点两点都支持**, 顺序可选。原点角=纯机床侧(参照物=物理板角); 起点=全链(参照物=板上的带)。两点组合可当场分解偏差来源 |
| Q3 | 机构 = **PhotoScrape_L2 新专用 ActionCode**(否决: 退化路径 trick 无回显停不住; 补全 T_HMI_Servo 影响面过大)。专动作专用, 收窄影响面 |
| Q4 | 交互 = **MVP 先行**: 复用现有 choose/input human 门做内环, 写经 VM(单写者不破), 回显走只读轮询+prompt 文本; 专用 align 前端面板留作后续升级(轮询端点先建, 升级零返工) |
| Q5 | **Z 正方向向下, Z=0 在上=安全位**。大行程 XY 移动锁 Z=0; 可选缓降检查高度 = `plate_surface_z_mm − align_clearance_mm`(新配置, 默认 2.5), **锚定既有刀长真源**, 换刀只改 plate_surface_z_mm 检查高度自动跟随。当前刀: 板面 z≈20.5, 检查高度≈18 |
| Q6 | Δ 修正 = **只显示不回写**: 门内给出带符号建议新值(按 origin_corner flip 算好方向), 人去配置页改, 复跑对位 Δ≈0 即验收。plate_origin_x/y 仍是唯一修正家, 不加新偏置旋钮, run 上下文无权改标定 |
| Q7 | 对刀系列 action **进一步编排成独立 operation**(对刀业务, 换刀后专跑), 与 photoscrape_process 门环共用同一个对位内环子 operation(`op: run_script` 复用, VM 原生支持, 已核 schema.py) |

## 3. A 部分 — HitlModal 原点标注(相机侧核对)

- 触发: `/sketch_rectify` 成功接管矫正帧后(以及视觉成功分支 plateBbox 有效时), canvas 叠画:
  原点 cm(0,0) 双圈 + ±x/±y 短箭头 + 四角 cm 语义标签(与包2 §5.3 标注层同语义同口诀: **cm 原点角应贴点样边**)。
- 数据(2026-07-16 plan 阶段修正): 标注几何**不需要 origin_corner** —— `plate_coords` 仿射约定把
  cm(0,0) 永远钉在 plateBbox 图像左下角(Y 翻转), origin_corner/flip 只活在机床↔cm 变换。
  后端用 `plate_coords.cm_to_px_affine` 算好标注 px 点集(`plate_axes`)随 `/sketch_rectify`
  与 `/sketch_context` 响应返回, 前端只画不算 — flip/映射逻辑零 JS 拷贝(C-4 单一真源)。
- 能抓: 角点没点准物理板角(板边不贴帧边)/ origin 角认错(点样边认错)。**抓不了对刀偏差** —— 图例文案写明。
- 既有「重标四角」循环不变, 标注随重标即时刷新。

## 4. B 部分 — PLC 侧(PhotoScrape_L2 POU + 符号表)

新增 3 个动作码(42/43/44 空闲, 已核 plc_photoscrape.yaml 码表)+ 5 个节点:

**ActionCode 42 `align_move`(对位移动)**
- 入参节点(新): `PhotoScrape_Align_TargetX` / `PhotoScrape_Align_TargetY`(REAL, **与 g_sx/g_sy 同帧的机床 mm** —
  B1 核查 C2: host plate_origin(-75.2) 与 8Y 轴坐标(0..420)疑似不同帧, 若单轴 MC 需帧变换**在 PLC 内完成**, 上机首项核查)。
- 守卫(全部动作内强制, 不靠调用方):
  1. **Z 门(2026-07-16 B1 核查修正)**: **一切 XY 移动只在 10Z 零位发生**, 否则拒动 ErrorCode。
     原设计"检查高度下放行 ≤2mm 微调"已废除 — 与既有 8Y 绝对运动互锁 `刮板轴10ZDATE.fActPos<6` 冲突,
     绕开既有安全互锁违背收窄影响面; jog 改为 升Z→步进→人工再缓降复查 的循环(见 §6 D1)。
  2. 目标在软限位窗内(板区+余量; **数值上机以 9X/8Y ActPos 轴坐标实测**, 勿照抄 config — B1 C2), 超窗拒动。
  3. 8Y 运动前须满足既有互锁"刮板拍照遮光气缸上位"(B1 发现的既有前置)。
- 行为: 9X/8Y 直线到目标, 速度=PLC 内**显式**保守常量(B1 C4: ST 无既有速度典型值, 靠持久值, 42/44 须显式设 fVelocity);
  终态锁存 Done(同 8 站 IF(NOT Start) 惯例), **刀头停在原地不回零**。
- 明确不碰: `g_sx/g_sy/g_cx/g_cy`、收集器轴、气缸/真空/翻料 —— 与 scrape(40) 零共享状态。

**ActionCode 43 `align_home`(对位结束)**: 若 Z 不在 0 先升 Z 到 0, 再 9X/8Y 回零, Done。

**ActionCode 44 `align_z`(检查高度缓降/回升)**
- 入参节点(新): `PhotoScrape_Align_TargetZ`(REAL); host 只发两档 {0, 检查高度}。
- 守卫: 降(target>0)仅当 XY 在板区窗内; 慢速; PLC 侧兜底上限常量(行程保护, 防撞责任在 host 的 plate_surface−clearance 换算 + 门内二次确认)。

**只读回显节点(新)**: `PhotoScrape_9X_ActPos` / `PhotoScrape_8Y_ActPos` / `PhotoScrape_10Z_ActPos`(LREAL, 命名对齐 FeedLift_1Z_ActPos 惯例)。

## 5. C 部分 — Host 动作层

- `photoscrape.align_move` / `align_home` / `align_z`(kind: plc_l2, params/channel 写法照 locate_cylinder)。
- `plc_controller.read_scrape_axes()`(照 read_rail_pose 先例)+ **只读** API 端点(UI 轮询; 读不算写者)。
- 目标换算(host, 经 plate_coords/gcode cfg 单一真源):
  - 原点角 = `(plate_origin_x, plate_origin_y)` 直接下发(不需要路径存在);
  - 路径起点 = `(g_sx[1], g_sy[1])`(取自本次 cnc 结果, 仅 cand_valid 时可选)。
- 新配置: `align_clearance_mm`(app.yaml gcode 段, 默认 2.5; 维护参数非 run 旋钮)。
- Δ 显示(2026-07-16 plan 阶段修正): 回显/Δ/建议全部下沉到单一 host 动作 `photoscrape.align_readout`
  (闭包 live-read gcode + 读 ActPos, 返回预格式化中文 text, VM 零算术 — VM 表达式无减法/下标的既证支持)。
  **建议 plate_origin 新值 = jog 对准原点角后当前实读直接照抄**(plate_origin 定义即该角机床坐标,
  flip 不进公式, 不会错向), 人工誊抄到配置页。路径起点标量由 cnc_path 结果新增
  `start_x_mm/start_y_mm`(=g_sx[0]/g_sy[0])提供, 规避 VM 数组下标。

## 6. D 部分 — 编排(三层: 内环子 operation / 独立对刀业务 / 门环选项)

### D1 对位内环子 operation `photoscrape_align_loop`(可复用单元)

纯对位, **不碰气缸**(气缸状态由调用方负责; 门环调用时板已压紧且刮取还要继续, 不得释放):

- in vars: `start_x_mm` / `start_y_mm`(路径起点目标, 可空; 空则内门"走路径起点"选项无效)。
- body = 内环(while): choose(走原点角 / 走路径起点 / 缓降检查高度 / 升回安全高 / 微调 / 结束)
  + 微调(2026-07-16 B1 修正) = input Δx/Δy(mm) → **align_z(0) 先升安全位** → align_move(当前实读+Δ)
  → 回内门; 低位观察→升Z→盲步进→再缓降复查, 迭代收敛(一切 XY 移动只在 Z=0, 与 PLC 42 守卫一致)。
  → 回门 prompt 带 ActPos 回显 + Δ=实读−指令原点 + 建议 plate_origin 新值。
- 内环整体 try/catch: **任何失败/中止路径先 align_z(0) 再 align_home**, 刀头绝不悬在板上方退出。
- 结束 = align_z(0) + align_home 后正常返回。

### D2 独立对刀业务 operation `photoscrape_tool_align`(换刀后维护流程)

resources: [station:photo_scrape](与生产 run 天然互斥), ui 归 03_photoscrape 维护类:

1. 首门(human confirm): 提醒并确认 **"已按当前刀更新 plate_surface_z_mm"** —— 换新刀更长而配置未更新时,
   缓降检查高度会撞板, 此门是唯一防线, 必设;确认已人工放入一块板(任意板, 板角位置由定位夹具保证)。
2. locate_cylinder(true) + press_cylinder(true)(对刀状态=工作状态, 压平防板翘)。
3. `op: run_script` → D1(不传 start_x/y, 维护场景无路径; 微调+绝对目标输入已覆盖自由走位)。
4. 收尾(含 catch 兜底): press_cylinder(false) + locate_cylinder(false) 放板。

### D3 photoscrape_process 门环选项

- 外门 options 增 `{value: align, label: 对位检查}` → `op: run_script` → D1(传 start_x=g_sx[1], start_y=g_sy[1],
  仅 cand_valid 时传; 气缸保持压紧不动)→ 返回后回外门, 门环结构不变。

## 7. 验证项(实施前 CODESYS 必核)

1. PhotoScrape POU: scrape(40) 与新 42/43/44 轴资源无隐藏共享; 8Y 相机/刮头同轴时序(cam_photohome 后 8Y 在零)。
2. 回零复用哪个既有块; 软限位/行程数值从哪取; Z 轴单位与方向在 POU 内再证一遍(正向向下, mm)。
3. scrape(40) 对起始 XY 是否有"从零位出发"假设(对位结束必回零, 但确认 40 自身有首点进近)。
4. 物理干涉(上机核): press_cylinder 压下状态, 刮头在板区任意 XY + 检查高度是否碰压头/收集器。

## 8. 测试与上机

- 离线: 门环扩展测试(align 分支进出/失败必回 home/cand_valid=false 时起点选项无效); D1 子 operation 单测(run_script 输入映射/try-catch 必回 home); D2 全流程(首门确认/气缸配对释放/catch 兜底释放); 目标换算黄金值; 微调 clamp 边界; 只读端点。
- 上机: ① 原点角走位 + 回显对读; ② 缓降 + jog 对准物理板角 → Δ 读数与包1 卡尺法**交叉验证一次**; ③ 路径起点走位 vs 手绘带目测; ④ 修 plate_origin 后复跑 Δ≈0; ⑤ 故意超窗/低位大步长, 验证两级拒动。

## 9. 与包1/包2 的关系

- jog 对刀**取代包1 的"XY 原点定量"部分**(不再必须牺牲板); 包1 保留的独有价值: 受力刮削下真实刮痕位置(静态对准测不出受力偏转)+ 刮宽 vs cutter compensation R 校验。
- 建议顺序: 先 jog 对刀修 plate_origin → 包1 一次交叉验证 → 对账照片(包2)作长期哨兵。三者互补, 互不取代。
