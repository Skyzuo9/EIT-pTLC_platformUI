# CNC 原点对刀 (1 点 XY 触点) — 设计与分阶段计划

- 日期: 2026-07-09
- 分支: codex/ui-upper-next
- 状态: 设计定稿, 待真机 Phase 0 核对后进入实施
- 关联: [[photoscrape-vision-frame-consistency]] · [[cnc-collect-path-tail-return]] · [[photoscrape-cnc-camera-actions]]

## 1. 背景与动机

拍照刮板工位的 CNC 刮取路径把"板坐标(cm)"映射到"机床坐标(mm)"时,原点由 `app.yaml`
`gcode.plate_origin_x/y` 两个**手打常量**给定 (当前 291.02 / 122.13)。观察到刮头存在
**安装导致的偏差**, 手打两个数不可靠——用户提出希望像普通 CNC 那样加一个**可选的对刀**步骤,
把板的参考点对上, 参数存进上位机供后续刮取使用。

## 2. 关键结论 (第一性原理 / 奥卡姆)

### 2.1 冗余性裁决: 4 点仿射对刀是过度设计, 1 点原点对刀才是右尺寸

用户初始设想"采板四个角 → 拟合仿射"。经拷问, 两个物理事实否定了这个复杂度:

- **偏差形态 = 整体平移**: 刮取路径形状本身对, 只是整体偏了一个固定量。
  ⇒ 旋转 = 0、缩放正确、无剪切。
- **装夹方式 = 机加工夹具 / 定位销**: 板与 CNC 轴**由构造保证平行**, 且**每次坐得一致**。
  ⇒ 偏差不仅是纯平移, 还是**固定 + 可复现**, 标定一次长期用。

因此 4 点仿射会去拟合物理上**恒为零**的自由度 (旋转/缩放/剪切), 且用 4 个手动采点的噪声
反而可能造出假的剪切/缩放, 使路径更差。**真正未知的只有两个数 (原点 XY)**——正是 `app.yaml`
里那两个。故: 不改模型, 只改**测这两个数的方式**。

### 2.2 与既有机制无冗余

- **与视觉 deskew 无冗余**: `image_plate_rotation_deg` 修的是"相机↔板"错位 (hop A);
  对刀修的是"板↔CNC"错位 (hop B)。两者作用于不同物理错位, 可组合, 不重叠。
- **与 `plate_affine` 无冗余**: 那是复用 (本方案甚至不需要它)。

### 2.3 变换链 (定位偏差归属)

```
相机像素 ──(A: deskew)──> 板帧 cm ──(B: plate_origin + flip)──> 机床 mm
        视觉层已处理                  ← 对刀替换的就是这一跳的原点部分
```

hop B 现状是 `_to_machine`: `机床 = 原点 ± cm·10` (仅平移 + 轴翻转, 无旋转/缩放)。
既然偏差是纯平移, 只需把"原点"这两个数测准, hop B 就正确。

## 3. PLC 侧核实结果 (codesys MCP, 2026-07-09)

- 刮头是真实 EtherCAT 伺服轴: **刮板轴9X** (X) / **刮板轴10Z** (Z); 拍照刮板龙门 Y = **拍照轴8Y**。
- `servo` 结构体含 `fActPos` (实际位置, 可读) + `xJogPos/xJogNeg` (软件点动)。
- **物理手轮 `FB_HandWheel` 已能点动 8Y/9X/10Z** (AXIS_6/7/8)。
  ⇒ 对刀的"移动"用手轮即可, **上位机只需读, 不发运动指令** (比上样孔板标定还简单:
    后者需 `Sampling_Servo_FreeMove` 去使能手推; 这里手轮天然可动)。
- 上位机位置镜像: **`Photo_8Y_ActPos` 已存在** (Host_Computer 已声明并被上样标定使用);
  **刮板轴9X / 10Z 无镜像** (Host_Computer 只有 4X/3Y/6X/7Y/8Y/Rail/FeedLift)。
- 真机刮取路径**已跑通** (用户确认: 刷子真的按 g_sx/g_sy 描出路径)。故消费者存在;
  本工程快照里 `PLC_CNC` 实现体为空, 是旧快照现象 (真机跑的是实现好的版本), 不阻塞本功能。

### 3.1 待真机核对的前提 (Phase 0, 唯一未解风险)

**坐标帧一致性**: `plate_origin_x/y` 活在 cnc_path 产出的**机床路径帧**里, 经
`SMC_TRAFO_Gantry3` 才落到物理轴。需真机核对 "读 9X/8Y 的 `fActPos`" 是否等于
"路径帧机床坐标"。三种结果与对策:

- 一致 → 对刀按本设计直接成立。
- 差一个常数偏置 → 采点时补该常数 (仍简单, 但必须知道它)。
- 非线性 (变换含缩放/旋转) → 不能读原始轴位, 需 PLC 暴露插补器 tool 位; 本设计暂不覆盖, 届时另议。

**低成本自检**: 首次对刀采到的 XY, 与当前能用的 `plate_origin` (扣除已知安装漂移后)
应在合理范围内; 对得上即帧一致。可作为 Phase 0 的实操判据, 无需额外仪器。

## 4. 方案 (右尺寸: 1 点原点对刀, XY)

### 4.1 一句话

DEBUG 门控 + confirm 的只读采点动作: 手轮把刮头开到**板原点角** (匹配 `origin_corner` 的那个角) →
上位机读 `刮板轴9X` + `拍照轴8Y` 的 `fActPos` → 写回 `gcode.plate_origin_x/y`。其余一切不动。

### 4.2 明确不做 (相对早期草案砍掉的冗余)

- 不在 `_to_machine` 引入 2×3 仿射 seam。
- 不建 `scrape_calib.py` / 标定服务 / override 文件 / 优先级逻辑。
- 不做 4 角标注 / lstsq / 残差门。
- 不复用 `plate_affine`。
- `cnc_path.py` **零改动**。

### 4.3 "可选"如何免费获得

对刀产物就是 `app.yaml` 里已存在的两个值。不跑对刀 → 手打值继续生效。无需任何优先级/开关机制。

### 4.4 Z 暂不采

偏差含 Z 向固定量也成立, 但采 Z 需接触判定 (手感/目测/探针) 更麻烦。本轮**只采 XY**;
PLC 侧可顺带留 `Scrape_10Z_ActPos` 镜像口 (不启用), 为将来 Z 对刀备用。

## 5. 分阶段计划

前两阶段是"验证与解锁", 不写业务代码; 把最可能推翻整件事的核对放最前。

### Phase 0 — 真机坐标帧核对 (不写代码)
- 手轮把刮头开到已知机床路径坐标的位置 (或当前 `plate_origin` 声称的原点角);
  读 9X/8Y 的 `fActPos`, 与路径帧期望值比对。
- 判定: 一致 / 常数偏置 / 非线性 (见 3.1)。非一致情形先记录偏置或叫停。

### Phase 1 — PLC (极小)
- Host_Computer 加镜像变量 `Scrape_9X_ActPos: LREAL;` (可顺带 `Scrape_10Z_ActPos`, 不启用)。
- 扫描程序加一行: `Scrape_9X_ActPos := 刮板轴9XDATE.fActPos;` (10Z 同理)。
- `plc_nodes.yaml` 注册 `Scrape_9X_ActPos: {type: Double, comment: "刮板9X 实际位置(mm) 镜像 fActPos"}`。
- 下载到设备验证读数随手轮变化。

### Phase 2 — 上位机 (小)
- 只读采点: 读 `Scrape_9X_ActPos` (X) + `Photo_8Y_ActPos` (Y), 返回 {x_mm, y_mm}。
  若 Phase 0 判定常数偏置, 在此处补偏置。
- "存为板原点": 合并 `{plate_origin_x, plate_origin_y}` 经 `ConfigService.save_section("gcode", ...)`
  (ruamel round-trip, 保注释/格式)。DEBUG 门控 + `confirm` 二次确认 (覆盖活标定)。
- 端点建议挂 `/api/calibration/scrape_origin/*` (actpos / save), 与既有孔板标定路由同域, 保持结构整洁。

### Phase 3 — UI (小)
- 对刀面板, 复用既有 ActPos 实时显示模式: 引导操作员手轮走到原点角 → 显示实时 XY →
  "采为板原点" → 确认 → 保存 → 回读确认写入。
- 放置于既有标定/点位区, 与磁盘 config 组织一致 (见 [[ui-mirrors-config-layout]])。

## 6. 接口草图

```
GET  /api/calibration/scrape_origin/actpos
     → {x_mm: <Scrape_9X_ActPos(+offset?)>, y_mm: <Photo_8Y_ActPos>}
POST /api/calibration/scrape_origin/save   (DEBUG, body: {confirm: true})
     → 读当前 actpos → save_section("gcode", {plate_origin_x, plate_origin_y}) → 回读确认
```

## 7. 风险与验证

- **坐标帧偏置 (主风险)**: Phase 0 核对; 首次采点与现值自检兜底。
- **原点角标注错**: UI 明确指出要对哪个物理角 (匹配 `origin_corner`); 采到值与现值差异过大给告警。
- **误触覆盖活标定**: DEBUG 门控 + confirm; 保存前展示"旧值 → 新值"。
- **回归**: 不跑对刀则手打值不变; `cnc_path` 零改动 ⇒ 现有离线测试不受影响。

## 8. 未决 / 待用户确认

- Phase 0 核对结果 (帧是否一致 / 是否需常数偏置)。
- 是否本轮就把 `Scrape_10Z_ActPos` 一并加上 (为将来 Z 对刀留口)。
