# 液位标记板标注 + 物理刻度标定 (整定台方案 B) · 设计

日期: 2026-07-17
状态: 设计定稿 (brainstorm 0716-0717, 用户已批准方向)
关联: docs/液位自动排液_P0实验手册_20260713.md (本设计落地时一并修订) /
      docs 前沿触发计划 (front-trigger, "px-mm 标定先行" 的 P0 由本设计顺带完成)

## 1. 背景与动机

P0 手册实验 A 用被整定的检测器自己读前沿推进量, 是自指闭环 (与 photoscrape
y-bias 的"预览自洽闭环盲区"同一模式); 实验 B (色素滴注) 为破环而设, 但一板只出
一个数据点且要人守着掐时机。

用户现有**标记板**: 距板顶 5/4/3/2/1 cm 处画横标线。用它录制展开后, 每段录像
自带最多 5 个可反复离线读取的真值事件 (前沿越线帧)。一段录像同时产出:

1. **front_percent ↔ 距板顶 cm 物理映射** —— 本设计的主产出。用户定位: 触发
   排液对精度不敏感, 这个映射的主用途是**后续读"液位在板子上的物理位置"**;
   计划把标定板放到各通道各跑一次展开, 得到每通道一份映射。
2. 检测精度 (每标线残差 → bias/σ)。
3. 触发区前沿速度 (相邻标线 Δt → cm/min)。
4. 触发→断液净推进 (含砂芯残液段), 拿标线当尺直读, 不依赖检测曲线。

硬需求: **缺标线必须支持** —— 1cm 线因视角/盖板遮挡可能不可见, 永远不标它时
一切计算自动适配。

## 2. 范围

**做** (全部在离线整定工具侧, 生产链路零改动):

- `eit_ptlc/tools/wl_replay_tune.py`: 标注热键 + HUD + 曲线叠标线 + 报告出口。
- 新纯函数模块 `eit_ptlc/tools/wl_marks.py` (stdlib+numpy, 不 import cv2):
  marks 文件读写 + 拟合/残差/速度/建议 全部计算, 离线可测。
- **`c` 键卡死根治** (见 §6) —— 报告出口依赖 `c`, 不修则本设计不可用。
- P0 实验手册修订 (见 §8)。
- 离线测试 (见 §9)。

**不做**:

- CV 自动识别标线 (人眼拖帧已足够准, YAGNI)。
- %↔cm 拟合写回 `config/water_level_calib.json` (方案 C)。等各通道数据稳定后
  另起; 本设计的数据格式已按"C 可直接消费"预留 (见 §4)。
- 检测服务 / develop.wait_level / 触发链路的任何改动。

## 3. 交互设计 (热键复用现有 preview 窗口)

- **数字键 `1`–`5` = 距板顶 cm 数**: 拖 `frame` 滑块到前沿越线那一帧, 按对应
  数字打标 ("按 `5`" = 记 "5cm 线 crossing = 当前帧")。语义:
  - 重按同一数字 → 覆盖到新的当前帧;
  - 在已标帧上按同数字 → 取消该标 (toggle);
  - 看不清的线永远不按, 无需任何"跳过"操作。
- HUD 增加一行: `marks: 5cm@f210 4cm@f388 3cm@f560 2cm@f731 (1cm 缺)`。
- 每次标注变更**即时原子写盘** (tmp + `os.replace`, 与 observation 落盘同款),
  无单独保存键; 重开工具自动载入已有 marks。
- CLI 可选参数 `--marks 5,4,3,2,1` 覆盖标线高度表 (默认即 5..1, 适配以后别的
  标定板)。**键位规则统一为: 数字键 = 距板顶 cm 整数值本身** (默认与覆盖同一
  语义), 故标线高度限 1–9 的整数 cm。
- `c` 整段曲线: percent(t)/front(t) 图上叠画各标线 crossing 的竖直虚线 (标注
  "5cm" 等), 并打印 §5 报告 + 落 `<stem>.marks_report.json`。

## 4. 数据契约 (Consumes / Produces)

**Consumes** (录制产物三件套, 既有格式不动):

- `<stem>.avi` — MJPG 逐帧;
- `<stem>.jsonl` — 逐帧墙钟时间戳 `{"i": idx, "t": epoch_seconds}` (可能缺行);
- `<stem>.meta.json` — `channel` / `calibration_snapshot` 等。

**Produces**:

`<stem>.marks.json` (schema `ptlc.wl-marks/v1`) — **只存纯真值**, 不存任何检测值:

```json
{
  "schema": "ptlc.wl-marks/v1",
  "channel": 3,
  "recording": "ch3_20260717_101500.avi",
  "marks_cm": [5.0, 4.0, 3.0, 2.0, 1.0],
  "events": [
    {"cm": 5.0, "frame_idx": 210, "ts": 1768623456.7},
    {"cm": 4.0, "frame_idx": 388, "ts": 1768623523.9}
  ],
  "updated_at": "2026-07-17T02:31:00+00:00"
}
```

设计决策: front_percent **在出报告时用当前滑块参数对标注帧现算** —— 与整定台
"ref_frame_idx 每次现算参考图"同一哲学: 改参数后标定自动跟新, 真值永不过期。
`frame_idx` 恒为原始帧序 (与 `c_speed` 抽帧无关); `ts` 按帧序取自 jsonl, 缺行
记 `null`。

`<stem>.marks_report.json` — 派生留档 (每次 `c` 覆盖):

- `fit`: `{slope_pct_per_cm, intercept_pct, r2, n}` (front% = a·d_cm + b);
- `marks`: 每条 `{cm, frame_idx, ts, front_percent, residual}`;
- `velocities`: 相邻已标线对 `{from_cm, to_cm, dt_s, cm_per_min}`;
- `suggestion`: 速度换算 %/s 及 `t1_offset` 建议算式 (参考信息, 不强求采纳);
- `params_snapshot` / `calib_snapshot` (现算所用参数, 报告可复现);
- `generated_at`。

`<stem>.curve.png` — 曲线图落盘 (§6 根治后的曲线出口之一)。

## 5. 报告计算 (`wl_marks.py` 纯函数; 缺省规则内建)

- **拟合**: 已标事件 ≥2 条 → 最小二乘 `front_percent = a·d + b` (d = 距板顶
  cm); <2 条 → 不拟合, 只列原始数据。报告同时打印反向映射公式
  `d(front%) = (front% − b) / a` —— 即"液位距板顶多少 cm"读数器。
- **残差/线性度**: ≥3 条时列每线残差与 R²; R² 低 (阈值实施时定, 初值 0.98)
  → 打印警告 "透视/ROI 不正, 物理映射慎用"。
- **区间速度**: 相邻已标线对按**实际 Δcm**/Δt 算 cm/min (缺 1cm 时最后一段
  自动是 3→2cm; 跳档如只标 5/3/2 → 段为 5→3, 3→2)。某端 ts 为 null → 该段
  跳过并注明。
- **建议行** (参考信息): 最靠上可用区间速度 × |a| → %/s, 附
  `t1_offset ≈ 就位时间(s) × 前沿速度(%/s)` 算式与代入值。
- **边界**: 未设参考帧 (`r`) 时无法现算 front_percent → 报告只列真值事件并提示
  "先按 r 设参考帧"; 某标注帧检测 invalid → 该线 front_percent 记 null, 不入拟合。

## 6. `c` 键卡死根治

现状诊断 (代码走读 `_plot_full_run`, 实施第一步先真机复现确认):

1. **层1 — 整段循环不泵事件**: 数千帧 decode + `detect_level` 同步跑在 cv2
   键循环线程里, 期间不调 `cv2.waitKey` → Windows 下窗口直接"未响应"。
2. **层2 — `plt.show()` mainloop 嵌套**: 跑完后 matplotlib GUI 后端 (TkAgg)
   的 mainloop 阻塞在 OpenCV 键循环内, 两套 GUI 事件循环互卡; 即使不死锁,
   用户不知道要关图窗才能继续, 同样表现为卡死。

方案 (单一 GUI 工具链原则):

- matplotlib 强制 `Agg` (纯渲染后端, 无 GUI): fig 渲染到 RGB buffer →
  `cv2.imshow` 独立窗口显示 + `<stem>.curve.png` 落盘 → 全程只有 HighGUI
  一套事件循环, 无 mainloop 嵌套。
- 整段循环每 N 帧 (~30) 调一次 `cv2.waitKey(1)` 泵事件 + 控制台进度
  (`x/总帧`); 期间按 Esc 中断本次整段跑, 回到交互态。
- 曲线窗口是普通 cv2 窗口 (X 关闭; 每次 c 刷新)。

## 7. 边界与前提 (写进报告头/手册)

- 标记与板同框进干板参考 → 差分中抵消, 不打扰检测; **参考窗口之后标记不可再
  改动**。
- 时间戳全部取录制 jsonl 真实墙钟, 与回放速度/抽帧无关。
- 既有注意事项不变: 老录像回放须显式带 tuned 标定。

## 8. P0 实验手册修订 (docs/液位自动排液_P0实验手册_20260713.md)

- 实验 A 读数改为**以标线为主尺** (整定台打标 + 报告), 检测曲线降为辅助交叉;
- 实验 B (色素滴注) 降级为抽查项;
- 新增"标定板全通道战役"一节: 标定板在各通道各跑一次展开 + 打标 → 每通道一份
  %↔cm 映射留档 (`marks_report.json`), 为方案 C (写回 config) 备数据。

## 9. 测试策略

- 新 `eit_ptlc/tests/test_wl_marks_offline.py` (纯函数, 不 import cv2):
  - 拟合: 5 线全标 / 只 2 线 (无 R²) / 只 1 线 (不拟合) / 反向映射数值;
  - 缺省: 缺 1cm、跳档 (5/3/2) 的区间速度分段正确;
  - ts 缺行 → 对应速度段跳过; invalid front → 该线不入拟合;
  - marks.json 读写往返 + 原子写 + 重载。
- GUI 侧 (热键交互 / `c` 根治 / 曲线窗口) 属人工验证, 清单进实施 plan:
  真录像开台走通 打标→报告→PNG→Esc 中断 全流程。

## 10. 实施顺序建议 (供 writing-plans)

1. `wl_marks.py` 纯函数 + 离线测试 (TDD);
2. `c` 根治 (Agg + cv2 显示 + 进度泵/中断) —— 独立可验证;
3. 热键/HUD/报告接线;
4. P0 手册修订。
