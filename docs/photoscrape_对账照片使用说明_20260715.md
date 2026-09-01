# 刮后对账照片 — 读图与测量方法

每次刮取(reconcile_photo=true, 默认)后新增:
- `scraped.jpg`: 刮后原始帧, 由 capture 落在 save_dir(与 after.jpg 同处)
- case 目录里另有 `scraped_normalized.jpg`(原始帧回放到归一化帧)与
  `scraped_annotated.png`(归一化刮后照片 + 下发时的指令路径叠加)

## 读图
- 青色线 = 指令路径(与写入 PLC 的 g_sx/g_sy 同源, 经 preview_payload.json 落盘复用)
- 照片中白色刮槽 = 机床实际刮到的位置(物理真值)
- 黄色标注 = 程序认定的板坐标系: 四角 X + cm 标签, 原点 cm(0,0) 双圈, ±轴箭头。
  核对口诀: **原点角应贴点样边**。

## 测量总 bias
y 向错位(px) ÷ (plate_bbox 高度 px / plate_size_cm) = 相机链+机床链+刀具链总偏差(cm)。
配合包1 定位实验(fixed_summary_path 刮已知位置直线 + 卡尺量 Δ_machine)即可分解:
相机链残差 A = 对账图总偏差 − Δ_machine。修正入 config gcode.plate_origin_y(不加新旋钮)。

## 注意
- 旧 case / fixed 实验 summary 无 normalize_applied 或 preview_payload.json 时,
  对账叠加自动跳过(宁可无图不可错帧), scraped.jpg 仍留档可人工量。
- auto_rectify_tilt 每帧现测角度不落盘的历史坑已由 normalize_applied 回放契约根治;
  老录像/老 case 回放须先重跑 analyze 落新字段。
