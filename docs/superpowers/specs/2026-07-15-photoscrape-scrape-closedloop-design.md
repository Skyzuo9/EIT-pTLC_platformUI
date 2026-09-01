# 拍照刮板 HITL 标定闭环 — 刮后对账照片 + 矫正帧收编 设计 spec

日期: 2026-07-15
状态: 设计定稿待评审
分支: codex/ui-upper-next
相关 memory: ptlc-photoscrape-path-source / vision-tab-single-track / ptlc-cutter-compensation

---

## 1. 背景与问题

真机观察: 实际刮取的 band 相对手绘的 band 存在 **y 向恒定偏移**(方向、大小在多次
run 间稳定; 已在手绘 band 上确认, 手绘不经视觉识别 → 识别链排除)。难点在于现有链路
无法区分偏差来自标定(相机链)还是机床链。

**结构性根源: 预览叠加是自洽闭环, 对标定 bias 是盲的。**
`preview_from_polygon` / `preview_payload_from_arrays` 把机床 mm 用**同一组参数**
(同一 px↔cm 映射、同一 `plate_origin`/`origin_corner`)逆变换回像素叠图。因此:

- 4 角点/plate_bbox 点偏(相机链 A 偏差) → 正逆变换精确抵消, 叠加图看起来完美;
- `plate_origin_y` 标定偏(机床链 B 偏差) → 同一常数正逆抵消, 叠加图同样完美;
- 刮刀刀尖 y 向装配偏置(物理链 C 偏差) → 根本不进坐标链。

三类偏差只在真机刮痕上现形, 而刮痕目前**没有任何影像记录**(相机只在刮取前拍照)。

已核事实(2026-07-15 代码核查):

- 拍照与刮取同工位, 段首 `press_cylinder(true)` 至收尾板零位移; 相机拍照位
  `photo_8y` 可复位 → 刮前/刮后照片像素级对齐, 无需配准。
- `fixed_summary_path` 固定路径实验机制已存在(YAML 3b 块 + `tools/fixed_scrape_path.py`
  + 离线测试), "指令刮已知 cm 位置"零新代码。
- 视觉成功路径已在归一化帧(`after_normalized.jpg` + `plate_bbox_px`)上作业;
  4 角人工标板 fallback 的背景**也已归一化**(`prepare_manual_backdrop` 找板失败仍先归一化),
  但其后的手绘/预览/提交仍走原始帧上的透视单应链。
- cm→px 仿射公式当前存在 **3 份拷贝**(`vision_controller` 内部闭包 int 版 /
  `sketch_path.cm_to_px_affine` / `cnc_preview.cm_to_px_affine`); machine→cm 逆变换
  2 份(`sketch_path` / `cnc_preview`, 后者自带一份 `_CORNER_FLIP` 表拷贝)。
  靠注释约定 + 测试对齐, 属真实漂移风险类。
- 归一化的 `auto_rectify_tilt` 角度**从当张图现测且只打 stdout 不落盘**;
  刮后板的绿色掩膜已改变, 对刮后照片重测会得到不同角度 → 直接叠加会错帧。

## 2. 目标 / 非目标

**目标**

1. 每次刮取产出一张"说好的 vs 刮到的"对账照片(`scraped_annotated.png`),
   使 A+B+C 总偏差在图像上可见、可量化(包2)。
2. 对账照片自身不引入测量误差: 帧回放契约(禁重新检测) + 坐标映射单一真源(包2)。
3. 4 角人工标板后, 用户看到并工作在**变换后的矫正图**上, 角点错误即时自检;
   手绘 fallback 分支收编进已验证的 `plate_bbox_px` 仿射主路径(包3)。
4. 在叠加图上标注程序认定的板坐标系(角点语义 X 标记 + cm 原点 + ±轴箭头),
   同时出现在下发门 preview 与刮后对账图(包2, 用户 Q1)。

**非目标**

- 不在本次实施定位实验本身(包1, 纯程序, 上机阶段执行, 见 §8)。
- 不改 `cnc_path` 路径生成算法、不加新偏置旋钮(`plate_origin_y` 即修正量的家;
  `bottle_y_offset_mm` 只作用收集器路径, 不动)。
- 不做镜头畸变校正(现有单应/仿射假设不变, 无回退)。
- 不新增前端页面; 对账图经 case 目录由 vision debug case 浏览器可见即可。

## 3. 总体结构与依赖 DAG

```
共享基建(包2a: plate_coords 收编 + normalize_applied 持久化/回放)
        │
        ├──> 包2b: 刮后补拍 + 对账叠加 + 坐标系标注层
        └──> 包3 : 矫正帧收编(/sketch_rectify) + 角点语义/点序自检
                          (包3 复用包2a 的持久化契约)
包1(定位分解实验): 零代码, 依赖包2b 的对账图读出相机链残差, 上机执行
```

包2、包3 各自跑一次 writing-plans 出独立 plan; 包2a 作为包2 plan 的先行任务组,
包3 plan 声明依赖包2a 落地。

## 4. 共享契约(两包逐字遵守)

### C-1 归一化参数持久化: summary.json 新字段 `normalize_applied`

所有 summary 生产者(`process_pair` / `prepare_manual_backdrop` / reanalyze 复用
`process_pair` / `write_manual_summary` 继承源 summary)统一写入:

```json
"normalize_applied": {
  "orientation": "rot0",            // 实际应用的 rot0/rot90/rot180/rot270
  "tilt_deg": 1.23,                 // 实际应用的 deskew 角; 0.0 = 未矫
  "rotation_center": "image_center",// 固定约定: cv2.getRotationMatrix2D(center=图像中心)
  "frame_size": [W, H]              // 归一化帧尺寸(px), 回放后校验
}
```

- `tilt_deg` 记**实际应用值**: fixed 分支记 fixed 值; auto 分支记现测值; 未矫记 0.0。
- `_normalize_plate_image` 改为返回 `(before, after, applied: dict)`。

### C-2 手动矫正参数持久化: `manual_rectify`(包3 产, 包2 回放消费)

```json
"manual_rectify": {
  "plate_corners_px": [[x,y],[x,y],[x,y],[x,y]],  // 归一化帧上的 [左上,右上,右下,左下]
  "px_per_cm": 40,
  "frame_size": [800, 800]                          // = plate_size_cm * px_per_cm
}
```

写入手绘 manual summary(`write_manual_summary` 扩展), 同时**复制**源 summary 的
`normalize_applied`(两级回放: raw → 归一化帧 → 手动矫正帧)。

### C-3 帧回放函数(与归一化实现同居 `tlc_analyze.py`, 同源 by construction)

```python
def replay_normalization(raw_image_path: Path, summary_path: Path, out_path: Path) -> Path
```

- 读 `normalize_applied`(+ 可选 `manual_rectify`), **确定性回放**同一变换链, 落 `out_path`。
- **禁止任何重新检测**(不跑 `green_plate_mask`/`detect_plate`/`minAreaRect`)。
- 参数缺失(旧 summary)或回放后尺寸与 `frame_size` 不符 → raise; 调用方 fail-safe:
  只存原始 `scraped.jpg`, 不渲染叠加, log 提示。宁可无图, 不可错帧。

### C-4 坐标映射单一真源: 新模块 `eit_ptlc/controller/plate_coords.py`

从 `sketch_path.py` 迁入(sketch_path 保留同名薄委托, 公共 API 不破):

```python
plate_bbox_xywh(plate_bbox_px) -> (x, y, w, h)
cm_to_px_affine(pts, plate_bbox_px, plate_size_cm) / px_to_cm_affine(...)
cm_to_px_corners(pts, plate_corners_px, plate_size_cm) / px_to_cm_corners(...)
machine_mm_to_cm(pts_mm, gcode_cfg) / machine_mm_to_px(...)
```

- flip 查表唯一来源 `cnc_path._flip_from_corner`; **删除** `cnc_preview._CORNER_FLIP` 拷贝。
- `cnc_preview` 的映射函数改为 import plate_coords; `vision_controller` 两处内部闭包
  改调 plate_coords(绘图处调用侧再取整)。
- 测试: px→cm→px 与 machine→cm→machine 往返恒等(4 种 `origin_corner` × 随机点)
  + 迁移前后黄金值不变。

### C-5 preview payload 持久化(对账图与门 preview 逐字节同源)

`cnc_path` 动作渲染 preview_url 时, 把 `preview_payload_from_arrays` 的返回**原样落盘**
`case_dir/preview_payload.json`(payload 增补 `plate_bbox_px`、`plate_size_cm` 两字段,
供标注层与复核, 纯增量)。刮后叠加**只读此文件**, 不重新计算数组、不重新生成路径
(维持 cnc_preview "never regenerates" 契约)。

payload 与 summary 必须**同代**(同一次 cnc_path 产物): cnc_path 每次执行先失效(删除)前任
preview_payload.json 再生成, 本次失败不留陈旧坐标 — 对账宁可无图, 不可用旧 payload 配新 summary 错帧。

## 5. 包2 — 刮后对账照片(closed-loop)

### 5.1 流程编排(photoscrape_process.yaml)

pass 循环之后、`scrape_finish` 之前, 新增块(与段首拍照同一组动作, 文件名换
`scraped.jpg`); 仅在 `reconcile_photo == true 且 skip_scrape == false` 时进入;
整块 try, 失败不 fault:

```yaml
# vars 新增(平台 knob 惯例, 运行前可覆盖):
#   {name: reconcile_photo, scope: local, type: BOOL, io: in, default: true,
#    comment: "刮后对账照片开关(漂移哨兵/标定验收); 生产嫌节拍可关"}
- op: if
  cond: {binop: and, left: {var: reconcile_photo},
         right: {unop: not, operand: {var: skip_scrape}}}
  then:
    - op: try
      body:
        - {op: comment, text: "(7) 刮后对账照片: 板仍压紧, 相机回拍照位补拍(与 after.jpg 像素对齐)"}
        - {op: call, action: photoscrape.cam_photopos, mode: RUN, args: {ref_8y: {lit: photo_8y}}}
        - {op: call, action: photoscrape.capture, mode: RUN,
           args: {sample_id: {var: sample_id}, save_dir: {var: save_dir},
                  filename: {lit: scraped.jpg}, profile: {lit: photoscrape}},
           assign: {var: scraped_shot}}
        - {op: call, action: photoscrape.cam_photohome, mode: RUN}
        - {op: call, action: photoscrape.scraped_overlay, mode: RUN,
           args: {summary_path: {var: cand_summary_path},
                  scraped_path: {field: {var: scraped_shot}, name: image_path}}}
      catch:
        - error: "*"
          body:
            - {op: comment, text: "对账照片/叠加失败不阻断收尾; best-effort 收相机"}
            - {op: call, action: photoscrape.cam_photohome, mode: RUN}
```

- 新 var: `scraped_shot` (DICT)。catch 内 `cam_photohome` 再失败由外层 fault 兜底
  (此时相机确实需要人工介入, 不再吞)。
- `fixed_summary_path` 实验 run 照常补拍(包1 依赖); fixed summary 无
  `plate_bbox_px`/`normalize_applied` → 叠加 fail-safe 跳过, `scraped.jpg` 仍留档。

### 5.2 新 host 动作 `photoscrape.scraped_overlay`

职责(全部复用既有部件, 无新算法):

1. `replay_normalization(scraped.jpg, summary_path, case_dir/scraped_normalized.jpg)` (C-3);
2. 读 `case_dir/preview_payload.json` (C-5);
3. `render_cnc_overlay(scraped_normalized.jpg, payload, case_dir/scraped_annotated.png)`;
4. 返回 `{ok, scraped_url, annotated_url}`; 任一步失败 → `ok=false` + 原图留档 + log,
   不抛(动作级 fail-safe, 与 YAML try 双保险)。

### 5.3 板坐标系标注层(用户 Q1)

`render_cnc_overlay` 增加标注层(preview 门图与对账图共用):

- `plate_bbox` 四角: 黄色 X + cm 语义标签 `cm(0,0)` / `cm(S,0)` / `cm(0,S)` / `cm(S,S)`;
- cm 原点 (0,0): 双圈醒目标记;
- 自原点两支短箭头 `+x`/`+y`(把 cm 点 `(0,0)→(3,0)`、`(0,0)→(0,3)` 过**同一个**
  cm→px 映射画出 — 标注即同源探针, 映射错则箭头立错);
- 操作员核对口诀(写入 OverlayLegend 图例文案): **cm 原点角应贴点样边**。

### 5.4 测量方法(使用说明, 进 docs)

对账图上: 青色线(指令路径) vs 白色刮槽(物理真值) 的 y 向错位, 除以
`plate_bbox` 每 cm 像素数 = A+B+C 总偏差(cm)。配合包1 得到的机床链分量即可分解。

## 6. 包3 — 矫正帧收编(4 角标板 → 变换后图像确认并作业)

### 6.1 后端: 新端点 `POST /api/photoscrape/sketch_rectify`(与 preview_path/sketch_commit 同路由家族)

入参 `{summary_path(=门 context), corners_px(归一化帧上4点, 序 左上/右上/右下/左下), plate_size_cm}`:

1. 服务端校验: 恰 4 点、按序构成凸四边形、方位一致(左上点须在右上点左侧等), 不符 → 400 带中文原因;
2. 底图取现有解析逻辑同款(`after_normalized.jpg` 优先);
3. `cv2.warpPerspective` 到 `S = plate_size_cm × px_per_cm(默认40)` 正方形,
   落 `case_dir/manual_normalized.jpg`;
4. 返回 `{image_url, plate_bbox_px: {x:0,y:0,w:S,h:S}, px_per_cm}`;
5. cv2 缺失/警告性失败 → 4xx/5xx, 前端回落旧 4 角单应老路(老路**不删**, 行为兜底)。

### 6.2 提交链: 手绘 summary 携带回放参数

`commit_sketch` / `write_manual_summary` 扩展: 经矫正帧提交时写入 `manual_rectify`(C-2)
并复制源 summary 的 `normalize_applied`; `backdrop_ref` 用 `manual_normalized.jpg`。
polygon px 在矫正帧内, 走**现有** `plate_bbox_px` 仿射分支 — preview/commit **主路径**
不再进透视单应代码(单应仅存活于 §6.3 端点失败的兜底路径与测试兼容)。

### 6.3 前端(HitlModal.vue)

- 点四角时数字 1-4 旁加语义标签 左上/右上/右下/左下(`redraw()` 内 3 行);
- 第 4 点落下: 先本地凸性/方位自检(~15 行, 错序即时中文报错), 过 → 调 `/sketch_rectify`
  → 画布底图换矫正图、`plateBbox` 置全幅、`hasPlateRef=true`, 后续与视觉成功分支同流;
- 保留原图与原角点状态, 「重标四角」一键回退重来;
- 端点失败 → 提示后回落现行 corners 流(`_plateRefPayload` 原样)。

### 6.4 用户确认体验

矫正图本身即确认界面: 角点点错 → 板边歪斜/切边/画幅不满, 一眼可见; 无需单独"确认"步。

## 7. 测试策略(全部离线可跑)

- **C-4**: 往返恒等 × 4 origin_corner × 随机点; 迁移黄金值回归(现 `sketch_path` 测试值不变)。
- **C-1/C-3**: 合成图 + 已知参数 → 归一化落 `normalize_applied` → `replay_normalization`
  逐像素一致; 缺字段/尺寸不符 → raise; 两级回放(含 `manual_rectify`)一致性。
- **C-5**: cnc_path 动作后 `preview_payload.json` 存在且与返回 payload 相等。
- **包2 YAML**: 扩展现有 photoscrape 门流离线测试 — `skip_scrape` 或 `reconcile_photo=false` 跳过补拍块;
  capture 抛错 → run 不 fault 且 `cam_photohome` 被调; `scraped_overlay` 缺
  `normalize_applied` → `ok=false` 不抛。
- **包3**: 端点校验矩阵(点数/凸性/错序/cv2 缺失); warp 后已知 cm 点 → px 黄金值;
  manual summary 含 `manual_rectify`+`normalize_applied`; 前端逻辑抽纯函数
  (凸性/方位自检)单测。
- **渲染 fail-safe**: cv2 缺失 → `render_cnc_overlay`/`replay_normalization` 路径整体
  fail-safe, 主流程绿。

## 8. 包1 — 定位分解实验(零代码, 上机程序, 另立手册进 docs)

1. `tools/fixed_scrape_path.py` 生成**不对称**已知 band: x∈[2,18], y∈[4.5,5.5] cm
   (中心 y=5.0; 不对称同时检出 `origin_corner` 镜像错误 — y=10 对称位置是镜像不变的);
2. 空白牺牲板, run 输入 `fixed_summary_path` 直发;
3. 卡尺量刮痕中心到板 y=0 边(点样边)距离: `Δ_machine = 实测 − 5.0 cm` = 机床链(B+C);
   顺手量刮痕宽度 vs 指令 1.0 cm 校验 cutter compensation 的 R;
4. 修正: `Δ_machine` 折进 `plate_origin_y`(手册给带符号算例, 按 `origin_corner` flip 定向);
5. 相机链残差 A = 对账图总偏差(包2 读出) − `Δ_machine`; A 显著则修角点指引/找板边界,
   不做数值补偿。

## 9. 风险与回退

| 风险 | 处置 |
|---|---|
| 补拍增加节拍(~相机往返一次) | `reconcile_photo` in-var knob(默认 true)本期做; 生产可一键关; bias 修完且连续多 run 残差归零前建议常开(标定验收的唯一凭据) |
| 旧 case/旧 summary 无新字段 | 全链 fail-safe: 跳过叠加只留原图; 老路兜底不删 |
| `auto_rectify_tilt` 与 fixed 角并存语义 | `normalize_applied.tilt_deg` 只记实际应用值, 回放与检测彻底解耦 |
| plate_coords 迁移引入行为差 | 薄委托保 API + 黄金值回归; vision int 取整只留在绘图调用侧 |
| 矫正 warp 分辨率损失 | px_per_cm=40(20cm 板 800px)≥ 原 bbox 典型分辨率; 仅供描点, 无识别消费 |

## 10. 上机 pending(合并后)

1. 真机跑一次 manual 手绘全流程, 确认 `scraped_annotated.png` 落盘且帧对齐(目测板边);
2. 包1 定位实验全程(§8), 拿到 `Δ_machine` 修 `plate_origin_y`;
3. 修正后复跑一次, 对账图残差应归零(≤1 刀宽内目测);
4. 4 角矫正流程真机走一遍(故意点错序验证自检报错)。
