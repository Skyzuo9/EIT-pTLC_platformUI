# 液位标定业务上位机化 + 整定台修缮 —— 设计稿

- 日期: 2026-07-08
- 状态: 设计已评审 (待写实施计划)
- 范围: 上位机侧 (`eit_ptlc/`) 液位标定/整定链路; 不动 OrangePi 载荷、不动检测算法核心

---

## 1. 背景与问题

液位检测已从香橙派搬到上位机 (纯函数 `waterlevel_detector.detect_level`, 输出 percent 面积占比)。
`wl_replay_tune.py` 已能用录制回放整定参数, 效果可用。本轮解决三件事:

1. **整定台的"旋转画面"不好用** —— 相机未正对硅胶板, 画面里硅胶板的**竖直参考边是斜的**,
   需要旋转把它摆正。现整定台用旋转**滑块**靠肉眼估, 与用户既有工作流 (手绘贴边取角) 不符;
   ROI 只能拖 4 个滑块, 没把"旋转后的画面"真正利用起来。
2. **网页"液位"栏缺标定业务** —— 现有单路视图只有数值 ROI + 参数滑块 + 采参考图, 无旋转、
   无可视框选; 香橙派侧标注/调试流在 `--no-detect` 架构下已无叠加 (见 §3), 覆盖不了标定交互。
3. **整定台 `←/→` 上/下一帧卡死** —— 方向键无反应 + 整体卡顿。

### 附带澄清: 旋转后 px→mm 还准不准 (用户顾虑)

`rotation_matrix` 用 `cv2.getRotationMatrix2D(center, angle, scale=1.0)` —— **刚体旋转 (等距变换)**,
保长度、保角度, 只转朝向。二维码在图中的像素边长旋转前后不变 ⇒ **mm/px 比例一字节不变**,
px-mm 标定保持有效, 且旋转后图像 x/y 轴对齐硅胶板真实横/纵向 ⇒ **更好用**。唯一纪律: 标定与
测量须在同一 (旋转后) 坐标系一致进行。且当前液位链路走 percent 面积占比 (无量纲), 根本不用 mm。
结论: **摆正画面的做法成立**, 可正式做成标定业务。(mm 绝对标定本轮不落地, 见 §9。)

---

## 2. 领域模型订正 (关键)

- 硅胶板**参考边在画面里是竖直的** (展开组 1、2 皆然)。
- **水平展缸**: 溶剂前沿沿画面**水平**推进; 组 1 与组 2 的差别**只在前进方向** (`left_to_right` /
  `right_to_left`), 已由 `flow_direction` 完整表达。
- 三者正交: **旋转** 只负责把竖直参考边摆到真正竖直; **ROI** 框监测区; **flow_direction** 决定
  前沿从哪侧进。(早前"对齐水平参考线"的说法作废。)

---

## 3. 已核实事实: 香橙派标注/调试流在当前架构下已死 (UI 侧)

`water_level_8ch_compress_mqtt.py:3231` 在 `--no-detect` 下 `rendered = frame` (原始, 无叠加)。
`mjpeg_streamer._stream_channel`: annotated=`get_rendered()`、debug=`get_debug()`、raw=原始帧。
故 `--no-detect` (检测已搬上位机) 下:

| UI 模式 | 来源 | `--no-detect` 下实际 |
|---|---|---|
| 标注 annotated | `get_rendered()` | 原始帧 (无叠加) |
| 调试面板 debug | `get_debug()` | 空/陈旧 |
| 原始 raw | 原始帧 | 原始帧 |

⇒ UI 的 **标注 / 调试面板 两模式已死**, 安全删除 (仅 UI 侧)。**边界**: OrangePi 载荷保留
`--no-detect`/检测开关作可回退兜底 (非本轮范围, 删它是另一件更大且有风险的事)。

---

## 4. 架构决策

### 4.1 旋转渲染 = 前端 canvas (方案 A)
前端拉一次原始帧到 canvas, 把 `rotation_matrix` 那几行几何**移植成 JS** 本地旋转; `roi_frac` 由
纯数学 (相对旋转后画布尺寸) 算出。后端检测用同一 `rotation_matrix` 复现 ⇒ 像素级一致。
取舍: 滑块/交互丝滑零往返, ROI frac 精确; 代价是几何有第二份 (JS) 实现 —— 用注释锚定 Python 源 +
`/verify` 人工核对兜住 (见 §8)。否决: 后端逐角度渲染 (往返卡)、CSS transform (不扩画布 ⇒ frac 错配)。

### 4.2 摆正 = 画边线定角 (非滑块)
- 状态: `angle` (总旋转角, 度)。显示 = 原始帧按 `angle` 旋转。
- 用户在**当前显示 (已旋转) 画面**上沿竖直参考边点 2 点 → 线的朝向 `θ_line = atan2(dy,dx)` →
  求"把该线转竖直"所需 `delta` → `angle += delta` → 从原始帧按新 `angle` 重渲。
- 不满意就在旋转后画面**再画一次** (delta 迭代收敛)。**无滑块、无微调钮** (再画即微调)。
- 符号约定对齐 `cv2.getRotationMatrix2D` (正角=逆时针), 实现时以一个离线/人工用例定符号。

### 4.3 ROI = 拖框 + 数值双向同步, 数值用 `roi_frac`
- 拖框实时回填数值; 改数值实时更新框。
- 数值统一 `roi_frac` (分辨率无关比例) —— 正是**跨通道该保持相同**的量, 可把某通道值抄到其它
  通道, 为将来"统一液位阈值触发排液"打一致性地基 (**触发逻辑本轮不做**, YAGNI)。

---

## 5. 工作流

### WS1 — 修 `wl_replay_tune` 卡顿 + 方向键 (需求 3)
- `cv2.waitKey()&0xFF` → `cv2.waitKeyEx()` 收方向键真码; 另补 `a`/`d` 单帧键 (跨平台兜底, 恒可用)。
- **仅状态变化时重渲染**: 帧号/参考帧/角/ROI 任一变化才 `warpAffine`+`detect_level`; 空闲不重算 →
  卡顿消失。播放态照常推进。

### WS1.5 — 整定台对齐新机制 (需求 1 收尾)
- 旋转: 换成**鼠标画边线定角** (§4.2), 替掉旋转滑块。
- ROI: 旋转后画面**鼠标拖框** → `roi_frac`; **保留 4 个 ROI 数值控件** (OpenCV trackbar 呈现 frac 值),
  与拖框**双向同步** —— 拖框回填 trackbar, 调 trackbar 也更新框; 存盘 `.tuned.json` 含精确 `roi_frac`
  供跨通道复制。
- 初值种子 fallback 链: 录制 `meta.calibration_snapshot` → 缺失读 `config/water_level_calib.json[通道]`
  → 再默认。解决 "CH5–8 在真源里没有、看着像没标定"。

### WS2 — 后端标定写入补 `roi_frac` (需求 2 使能项)
- `WaterLevelDetectService.update_calibration` 增 `roi_frac` 入参: 设 `calib.roi_frac`, **清 `roi_bbox`**
  (避免陈旧像素框优先); 沿用"改标定 → 参考图失效"逻辑。
- 路由 `_dispatch_upper_cmd` 的 `set_calibration` 透传 `roi_frac` (与 `rotation_angle_deg`/
  `flow_direction` 一并)。
- 不动检测算法。~15 行 + 离线用例。

### WS3 — 网页标定模式 + 清理死模式 (需求 2 主菜)
- 单路视图页签栏改为 **`原始`(实时流) + `标定`(冻结帧 canvas)**; **删除 `标注`/`调试面板`** 及
  `wlStreamUrl` 里 annotated/debug 分支 (只留 raw)。
- 新组件 `WaterLevelCalibrate.vue` (canvas 交互), 选「标定」时替换左侧视图区:
  1. `GET /api/water_level/frame/chN` 拉一次**冻结原始帧** → canvas; 「重新取帧」换新帧。
  2. **画竖直参考边线**定角摆正 (§4.2); 叠一条竖直参考线做视觉校验。
  3. 旋转后画面**拖框 ROI** + `roi_frac` 数值输入框, 双向同步 (§4.3)。
  4. **流向**下拉 (`left_to_right`/`right_to_left`/`bottom_to_top`)。
  5. 「保存标定」→ `set_calibration{rotation_angle_deg, roi_frac, flow_direction, save:true}`;
     「采集参考图」→ `capture_reference` (改标定已使旧参考失效, 重采)。

---

## 6. 数据流 (网页标定)

```
[香橙派 /frame/chN 原始帧]
        │ (拉一次, 冻结)
        ▼
[前端 canvas: JS rotation_matrix(angle) 旋转显示]
   ├─ 画边线 → delta → angle += delta → 重渲
   └─ 拖框 → roi_frac(相对旋转后画布) ⇄ 数值输入框
        │ 保存
        ▼
POST /api/water_level/cmd/set_calibration {rotation_angle_deg, roi_frac, flow_direction, save:true}
        ▼
WaterLevelDetectService.update_calibration → 内存真源 + 持久化 water_level_calib.json
        ▼
下一轮拉帧检测用同一 rotation_matrix + roi_frac → percent (口径一致)
```

---

## 7. 涉及文件 (预估)

- `eit_ptlc/tools/wl_replay_tune.py` — WS1 (waitKeyEx + 按需重渲) + WS1.5 (画线定角 + 拖框 ROI +
  种子 fallback)
- `eit_ptlc/controller/waterlevel_service.py` — WS2 (`update_calibration` 增 `roi_frac`)
- `eit_ptlc/api/water_level_routes.py` — WS2 (`set_calibration` 透传 `roi_frac`)
- `eit_ptlc/web/src/components/WaterLevelChannel.vue` — WS3 (页签改 `原始`+`标定`, 删死模式)
- `eit_ptlc/web/src/components/WaterLevelCalibrate.vue` — WS3 新增 (canvas 标定交互)
- `eit_ptlc/web/src/api.js` — WS3 (简化 `wlStreamUrl`, 只留 raw)
- `eit_ptlc/tests/test_waterlevel_calib_roi_frac_offline.py` — WS2 新增离线用例

---

## 8. 测试

- **WS2 离线**: `update_calibration(roi_frac=...)` → `calib.roi_frac` 生效且 `roi_bbox` 清空; 持久化
  往返读回一致; `set_calibration` 路由透传 `roi_frac` (可复用现有 `test_waterlevel_calib_write_offline`
  风格)。
- **WS1/WS1.5**: 整定台是交互 GUI, 主体不进离线; 但**几何纯函数可测** —— 断言 "给定旋转后画布尺寸,
  由拖框像素反推的 `roi_frac`, 经 `roi_pixels` 还原回同一像素框" (round-trip), 锚定 JS/Python 同式。
- **WS3 前端**: 无自动化; 靠 `/verify` 人工核对 —— 画框保存后, 检测 percent 与叠加框吻合;
  画边线后竖直参考边确实竖直。
- **回归**: 现有 `eit_ptlc/tests/` 全绿 (尤其液位相关离线集)。

**验证难点**: JS 版 `rotation_matrix` 与 Python 分歧风险 → JS 端注释锚定 Python 源 + round-trip 测试 +
`/verify` 人工核对三重兜底。

---

## 9. 不做 (YAGNI / 范围外)

- 网页里回放 `.avi` 标定 (用户未选; 实机冻结帧已够)。
- **mm 绝对标定 / 二维码 px-mm 重建** (液位走 percent 无量纲, 不需要)。
- **统一液位阈值触发排液的触发逻辑** (本轮只保证 ROI 可跨通道一致输入, 触发另立)。
- 时序滤波 / 前沿状态机 (WAITING/TRACKING/GONE) —— 属上层检测服务职责, 不污染纯函数。
- 改检测算法核心。
- 动 OrangePi 载荷 (保留 `--no-detect`/检测开关作兜底)。

---

## 10. 风险与开放点

- **符号约定**: 画线定角的 `delta` 正负须与 `cv2.getRotationMatrix2D` 一致 —— 实现时以用例钉死。
- **冻结帧分辨率**: `/frame` 为压缩帧 (质量 70, 采集档尺寸); 检测同源同端点 ⇒ 分辨率一致;
  即便日后换档, `roi_frac` 比例无关仍成立。
- **JS 几何第二实现**: 见 §8 兜底; 若未来嫌重, 可退化为后端一次性返回"旋转后帧" (方案 B) 但牺牲
  滑动手感 —— 本轮不做。
