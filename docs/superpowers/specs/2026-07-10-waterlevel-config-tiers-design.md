# 液位配置一致性层 (参数分层 + 所有权网关 + CLI 看板)

日期: 2026-07-10
状态: 设计已确认, 待实施
分支: codex/ui-upper-next

---

## 1. 问题

调参时(`eit_ptlc.tools.wl_replay_tune`)无法在**已标定配置**基础上做"统一"操作:
统一 ROI 尺寸、统一判据阈值(如前沿 50% 触发口径)。今天想统一就得手改 8 处,必然漂。
且没有任何入口能**一眼看出 8 路参数是否一致**。

更深的一层: `water_level_calib.json` 已经有两个潜在写者(网页标定 UI、CLI 工具),
但**字段所有权未定义**。这会导致两种病:

- 互相覆盖(网页存完位姿 → CLI 广播全局层时盖掉);
- "改完还得跑回 CLI 补一刀"(网页拖 ROI 时连 `w,h` 一起写了, 破坏全局尺寸统一)。

极端情况下所有权全落到 CLI, 网页 UI 被架空。

---

## 2. 第一性原理: 参数分三层, 层即所有权

参数按**"定它需要什么信息"**天然分三层。层一旦定死, 所有权(谁能写)随之确定:

| 层 | 字段 | 定它需要 | 归谁写 | 频率 |
|---|---|---|---|---|
| **全局·判据** | `WaterLevelDetectParams` 全部: `roi_crop_x/y`, `blur_ksize`, `diff_threshold`, `wet_pixel_threshold`, `front_ratio_level` | 一整段**时序录制**(灌/排事件曲线) | **CLI 回放整定** | 极少, 近乎常量 |
| **全局·尺寸** | ROI 像素 `w, h`(参考分辨率下) | 同上 | **CLI 回放整定** | 极少 |
| **逐通道·位姿** | `rotation_angle_deg`, `flow_direction`, ROI 位置 `x, y` | **实时画面**(相机被碰/重装) | **网页标定 UI** | 常改, 运维日常 |

这个划分**不重叠**, 于是两个担心同时消解:

- 网页**不会被架空** —— 它独占运维天天碰的位姿; CLI 碰不到。
- **不存在"改完跑回 CLI"** —— 网页写的字段 CLI 不拥有。
- CLI 只在重新决定全厂标准时用一次(类比 `D_f`: 定了就是常量)。

即 **HMI(操作) vs 工程师站(定标准)** 的经典分工。

### 2.1 关键约束: 像素尺寸只在声明的参考分辨率下有意义

运行时检测的真源是 **`roi_frac`(比例, 分辨率无关)**, 不是 `roi_bbox`
(见 `waterlevel_detector.ChannelCalibration.roi_pixels`: `roi_frac` 优先, `roi_bbox` 仅为遗留回退)。
`roi_frac` 分辨率无关是刻意设计(监控档/活跃档共用一份标定)。

而 `roi_frac = 像素 / 旋转后画布尺寸`, 且旋转后画布尺寸依赖 `rotation_angle_deg`(逐通道不同)。
因此**"像素统一"与"frac 统一"数学上不能同时精确成立**。

**化解**:

- **像素 `w,h` 是人看的权威统一值**, 定义在一个**明确声明的参考分辨率**下;
- **`roi_frac` 是派生值**, 写回时按每通道自己的 `rotation` 换算 → materialize 进真源;
- **运行时检测代码零改**(照旧读 `roi_frac`)。

各通道 frac 的微小差异是**有意的**(补偿各自 rotation), 不是漂移。

**参考分辨率 = 1280×720**(由现有真源反推得到, 非 800×600):
以 CH1 为例, `rotation=0.8666°` 时旋转后画布 `1290×739`, `133/1290 = 0.1031 = roi_frac.fw` ✓。
(旧香橙派文件 `water_level_config.json` 的 `capture 800×600` 属于上一代算法, 与本设计无关。)

参考分辨率作为网关的显式参数(默认 1280×720), 不硬编码在散落各处。

### 2.2 现状已有真实漂移(设计的即时验证)

在参考分辨率 1280×720 下, 从现有 `water_level_calib.json` 反推 ROI 像素尺寸:

- `w = 133`, 8 路**完全一致** ✓
- `h = 397 / 384 / 396 / 387 / 392 / 392 / 392 / 392` —— 跨度 **13px (~3%)** ✗ **漂了**

看板一上线即可抓到此项, 且这是当前肉眼不可见的不一致。

---

## 3. 架构: 一个网关模块, 两个薄面

不让两个面各自懂规则, 而是收敛到唯一网关:

```
        网页 UI (位姿)          CLI 看板/整定 (全局层)
              \                        /
               \                      /
        ┌─────────────────────────────────────┐
        │  waterlevel_config_tiers  (网关)    │  ← 唯一懂:
        │   · 层定义                          │     谁属哪层
        │   · 写入按层过滤 (越权即拒)         │     frac 如何由 px 派生
        │   · frac 派生                       │     什么算"漂"
        │   · 一致性判据 (audit)              │
        └─────────────────────────────────────┘
                          │
              water_level_calib.json (真源, 格式不变)
```

**要点:**

- **写入按层过滤**: 每个面只能提交自己拥有的层, 网关拒绝越权字段。
  所有权从"文档约定"升格为"代码强制"。
- **frac 派生 / 漂移判据只有一份实现**, 读(看板)与写(广播)共用。
  顺带止住 `JS↔Python 几何双实现` 的技术债继续生长。
- **真源文件格式不动** —— 不掀 `waterlevel_store` / `service` / `bootstrap` / 香橙派兼容迁移这堵承重墙。
  "结构性防漂"通过**约束写者**达成, 而非重构存储格式。

### 3.1 为什么不重构成 `{shared:{...}, channels:{...}}`

评估过。收益是结构性防漂, 代价是改动 `waterlevel_store` / `waterlevel_service` /
`bootstrap` / `config/models` + 全套测试 + 香橙派兼容迁移。
约束写者已能拿到同等防漂效果, blast radius 近乎为零。**奥卡姆取后者。**

---

## 4. 组件

### 4.1 `eit_ptlc/controller/waterlevel_config_tiers.py` (新增, 网关)

纯函数为主, 无 I/O 副作用(I/O 仍走 `waterlevel_store`)。

```python
REFERENCE_CAPTURE = (1280, 720)          # 像素尺寸的声明参考分辨率

GLOBAL_JUDGMENT_FIELDS = (...)           # WaterLevelDetectParams 全字段
# 全局·尺寸: roi size px (w, h)
# 逐通道·位姿: rotation_angle_deg, flow_direction, roi pos px (x, y)

@dataclass(frozen=True)
class Pose:            rotation_deg: float; flow: str; xy_px: tuple[int, int]

@dataclass(frozen=True)
class TierView:        judgment: WaterLevelDetectParams
                       size_px: Optional[tuple[int, int]]
                       pose: Optional[Pose]

def split_tiers(cfg: ChannelConfig, capture=REFERENCE_CAPTURE) -> TierView
def derive_roi_frac(rotation_deg, xy_px, size_px, capture) -> tuple[float,float,float,float]
def merge_tiers(judgment, size_px, pose, capture) -> ChannelConfig   # 含 frac 派生
def audit(configs: dict[int, ChannelConfig], capture) -> AuditReport
def apply_commit(configs, ch, tuned: ChannelConfig, *,
                 broadcast_global: bool, with_pose: bool) -> dict[int, ChannelConfig]
```

- `derive_roi_frac` 复用现有 `rotation_matrix` + `box_to_roi_frac`, 不新写几何。
- **正反向换算都按该通道自己的 `rotation` 求旋转后画布尺寸**:
  `split_tiers` 的 `frac → px` 与 `derive_roi_frac` 的 `px → frac` 是严格互逆的一对(圆整误差 ≤1px)。
- `apply_commit` 是**唯一**的写入按层过滤点: `with_pose=False` 时丢弃 `tuned` 的位姿字段。
- `audit` 返回结构化报告(每个全局层字段: 是否一致 / 期望值 / 偏离通道列表; 未标定通道列表)。
  **期望值取严格多数(> 半数)**; 若无严格多数(如 4:4 平票)→ 报 **`无共识`**, 列出所有取值及其通道, **不猜、不自动选**。

**读/写两条路径彻底解耦, 不共用"取值"逻辑:**

| | 只读 `audit` | 写入 `--broadcast` |
|---|---|---|
| 值从哪来 | 8 路现值的**严格多数**(仅用于提示"谁偏离了大伙") | **`tuned.json` 那一路的实测值** |
| 无共识时 | 报 `无共识`, 列出所有取值 | **无影响** —— 广播源是确定的, 不投票 |

即: 多数值是**展示概念**, 广播是**确定性动作**。二者不耦合。

### 4.2 `eit_ptlc/tools/wl_config_board.py` (新增, CLI 看板)

与 `wl_replay_tune.py` 同级同类。

**只读模式(默认)** — `python -m eit_ptlc.tools.wl_config_board`

读真源 → 打印 `8 通道 × 各参数` 对齐表格:

- **全局层**某参数 8 路不一致 → 标红 + 给出期望值(多数值)与偏离通道号;
- **未标定通道**(`roi_frac`/`roi_bbox` 皆空)单列告警;
- **位姿层**灰显(信息, 不判漂)。

零真源改动。

**提交模式** — `... --commit <stem>.tuned.json [--broadcast] [--with-pose]`

**这是唯一改真源的入口**(不可逆动作集中一处, 可审计):

1. 读某通道调好的 `<stem>.tuned.json`;
2. **打印逐字段 diff**(真源现值 → 新值);
3. 交互确认(展示: 全局层落该通道还是 `--broadcast` 到 8 路; 位姿是否随 `--with-pose` 写入);
4. **先备份** `water_level_calib.json` → `water_level_calib.<ts>.bak.json`;
5. 写真源。广播尺寸时, 对每路用**它自己的 `rotation` + `x,y`** 重算 `roi_frac`, 同时 materialize `roi_bbox`;
6. 写完**自动重跑只读看板**, 当场证明"绿了"。

`--dry-run` 走 1-3 步后停, 不备份不写。

### 4.3 `eit_ptlc/tools/wl_replay_tune.py` (改动: 最小)

**基本不动。** `w` 键继续产出 `<stem>.tuned.json`(它天生就是"提交前的暂存")。
**不**让它直接写真源 —— 其风险面一点没变大。

唯一调整: `w` 存盘后提示下一步命令(`wl_config_board --commit <path>`), 把 workflow 串起来。

---

## 5. 数据流

**调参闭环(工程师站):**

```
录制 .avi ──► wl_replay_tune (读真源当初值, 调时序阈值/尺寸)
                    │ 按 w
                    ▼
             <stem>.tuned.json  (暂存, 单通道)
                    │ wl_config_board --commit [--broadcast]
                    ▼
        网关: 按层过滤 → frac 派生 → diff → 备份 → 写
                    ▼
          water_level_calib.json (真源)
                    │
                    ▼
             运行时 detect_level (读 roi_frac, 代码零改)
```

**位姿闭环(运维/网页, 本期不动):** 网页 → (下期: 走网关) → 真源。
本期由看板负责把网页造成的尺寸漂**标红报出来**。

---

## 6. 所有权规则 (拍板结论)

- **CLI commit 默认只落全局层**; 回放时画的角/拖的框只算"为了看清楚的本地草稿"。
- 确需写位姿时加 **`--with-pose`** 显式越权(逃生口: 网页不可用 / 只有录制段在手)。
- **网页永远只写位姿**(下期通过网关强制)。

---

## 7. 错误处理

- 真源不存在 / 解析失败 → 明确报错退出, 不静默造默认值。
- `--commit` 的 `tuned.json` 通道号缺失或越界 → 拒绝, 不猜。
- 备份写失败 → **中止, 不写真源**(备份是写入前置条件)。
- `merge_tiers` 派生出退化 ROI(`w<=0`/`h<=0`/越界)→ 抛错, 不写。
- 未标定通道参与 `--broadcast` 时: 只广播判据层, 尺寸层跳过(无位置可锚), 并在报告中列出。

---

## 8. 分期

- **本期**: 网关模块 + CLI 看板(读)+ CLI commit/广播(写, 全局层)。网页不动。
- **下期(独立 spec)**: 网页 ROI 尺寸吸附到全局值(只取 `x,y`)+ 网页提交走网关 → 标红变成不可能发生。

---

## 9. 测试 (全离线, 无真机)

- `split_tiers` / `merge_tiers` 往返一致性(round-trip)。
- `derive_roi_frac`: 给定 rotation + px → frac, 与现有真源实测值吻合(用 CH1/CH5 真实数据当金标准)。
- `audit`: 构造漂移样本 → 断言标出正确的字段与通道; **用当前真源断言 `h` 漂移被抓到**。
- `apply_commit`: `with_pose=False` 时位姿字段**未被写入**(越权过滤生效); `broadcast=True` 时 8 路判据/尺寸一致且各自 frac 按自身 rotation 正确派生。
- 备份失败 → 真源未被修改(前置条件)。
- 未标定通道参与广播的降级路径。

新增 `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`。

---

## 10. 非目标 (YAGNI)

- **"液位达阈值 → 发信号"的运行时接线** —— 今天代码里完全不存在(`percent` 只被算出, 无消费点)。
  本期只统一**参数**口径, 不造行为。需要时另开 spec。
- **把回放整定搬进网页上位机** —— 独立且更大的项目(浏览器对录制 MJPG 的帧精确 seek 是硬骨头,
  而这恰是 CLI/OpenCV 免费给的)。记为将来 spec, 不夹带。
- **重构真源为 `shared/channels` 格式** —— 见 §3.1, 已评估否决。
- **旧香橙派 `water_level_config.json`** —— 上一代算法资产, 不触碰。
