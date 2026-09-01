# 液位整定台 — 终端精确敲值 + 两级存盘 (草稿 / 并入真源)

日期: 2026-07-10
范围: `eit_ptlc/tools/wl_replay_tune.py` 单文件 + 一份纯函数单元测试
状态: 设计已定, 待写实施计划

## 背景与动机

整定台 (`wl_replay_tune.py`) 现役靠 OpenCV trackbar 拖滑块调参。两个痛点:

1. **滑块调不出确切值** —— 想把 `diff_threshold` 定到 `7.5`,拖滑块只能靠手感逼近。
   OpenCV HighGUI 的 trackbar 是纯整数、无文本框,天生给不了"输入框"。
2. **"存盘"语义模糊** —— 现在只有 `w` 一档,写到旁挂 `<stem>.tuned.json`(store 原生
   格式,只含当前一路)。要让上位机**生产**真正用上,还得手动把这一路并入真源
   `config/water_level_calib.json`。而这一步有坑:sidecar 只含一路、`save_channel_configs`
   是**覆盖写**,直接 copy 覆盖真源会**静默抹掉其余 7 路**。

本设计:用**终端敲值 REPL**补上精确输入;把存盘拆成清晰两级 —— `w` 存草稿(不变)、
`W` 显式并入真源(load-merge-save 单通道 + 确认,堵死抹通道的脚枪)。

### 设计约束 (逐字沿用文件既有哲学)

- **零新算法 / 零新依赖**: 复用现役 `detect_level` / store 的 `load_channel_configs`
  `save_channel_configs` / 既有 trackbar 层。本次只加交互外壳与一层薄标度抽象。
- **滑块层保持可用**: 敲值即时生效仍走"回填滑块 → 主循环 `_read_state` 每帧读"这条既有
  数据流,不新开一条并行状态。改值看效果**不需要任何 commit**,是实时的。
- **写生产真源是较重的 outward-facing 动作**: 必须显式热键 + 一次确认,不可误触。

### 与"旋转/ROI 耦合"的关系 (评估结论, 作为本设计的语境)

`roi_frac` 存在**旋转后画布**坐标里,故与 `rotation_angle_deg` 几何耦合:改旋转 → 同一
`roi_frac` 的物理落点漂移 ≈ `r·Δθ`(r=展缸盖边到画面中心距离)。但影响很小:720p、
r≈300px、Δθ=1° → 漂 ≈5px,被 `roi_crop` 缩进缓冲吃掉;且生产走参考图差分,静止盖边在
ref/检测帧中抵消。**rotation 与 roi_frac 在 `ChannelCalibration` 里是原子单元**,web UI 与
整定台都一起存,不会悄悄脱耦(除非手改 JSON 单字段)。

由此得一个**顺带增益**:终端敲值 REPL 把 `rotation_deg` 也纳入可敲项 —— 需要按耦合结论做
"改旋转顺手核 ROI"时,可直接敲一个确切角度(取代只能画线定角),两者仍一起 `W` 落盘。

## 组件与接口

全部改动落在 `wl_replay_tune.py`,新增测试落在 `eit_ptlc/tools/tests/`(或既有测试目录)。

### 1. 标度单一真源 `PARAM_SPECS`(纯函数, 去重现有散落的 x10/1000 换算)

现状:滑块 int ↔ 自然值 的标度(`diff_thr(x10)`、`roi_fx(/1000)`、`blur=2v+1` …)在
`_add_trackbars`(建轨)与 `_read_state`(读轨)各写一遍。本次抽成一张**纯数据表**,三处
(建轨 / 读轨 / 敲值 REPL)共用,消除重复、且**纯函数可无 GUI 单测**。

```python
@dataclass(frozen=True)
class ParamSpec:
    key: str                     # 菜单/命令短名, 如 "diff_thr"
    trackbar: str                # 对应滑块名
    lo: float; hi: float         # 自然值合法区间 (用户敲的单位)
    track_hi: int                # 滑块 int 上限
    to_pos:  Callable[[float], int]    # 自然值 -> 滑块 int
    from_pos: Callable[[int], float]   # 滑块 int -> 自然值
    is_int: bool                 # flow/blur 之类整数项 (敲值按 int 解析)
    hint: str                    # 菜单里的单位/取值提示
```

覆盖项(菜单顺序):`flow`(enum 0/1/2)、`roi_fx/fy/fw/fh`(/1000)、`crop_x/crop_y`(%,
自然值 0~0.40)、`blur_ksize`(2v+1,敲奇数核 1~31)、`diff_thr`(x10)、`wet_thr`(x10)、
`front_lvl`(%,自然值 0~1)。

- **Consumes**: 无(纯声明)。
- **Produces**: 供下述三处消费的规格表 + 纯 `to_pos/from_pos`。
- **契约**: 对每个 spec,`from_pos(to_pos(v)) ≈ v`(在标度分辨率内)。这条由单测钉死。

`rotation_deg` **不入 `PARAM_SPECS`**(它不是滑块,存在 `ui.angle_deg`),作为 REPL 的一个
特殊菜单项单列:敲值 → `clamp(-45, 45)` → 写 `ui.angle_deg`。

`_add_trackbars` / `_read_state` 重构为遍历 `PARAM_SPECS` 建轨/读轨(`frame`/`ref_frame`
两个导航轨保持直接创建,不属参数)。行为等价,仅去重。

### 2. 终端敲值 REPL(热键 `e`)

```
def run_edit_repl(ui) -> None:   # 阻塞式模态编辑; 返回后主循环照常重渲
```

行为:
1. 按 `e` → `playing = False`(编辑时不推帧)→ 调 `run_edit_repl(ui)`。
2. 打印带编号的可编辑项清单 + **当前自然值** + 区间提示。编号 0 = `rotation_deg`,
   其后为 `PARAM_SPECS` 各项。
3. 循环读一行 `编辑> `:
   - 解析 `<编号|短名> <值>`(纯函数 `parse_edit_command(line, specs)` → `(target, value)`
     或错误串)。
   - 应用:滑块项 → `pos = clamp(to_pos(clamp(value, lo, hi)), 0, track_hi)`,
     `cv2.setTrackbarPos(...)`;rotation → 写 `ui.angle_deg`。
   - 回读并打印新值(确认生效)。非法/越界 → 打印提示,REPL 不退出。
   - 空行 / `q` → 退出 REPL,回到预览(主循环下一帧用新滑块值重渲)。

- **Consumes**: `ui`(读写 `ui.angle_deg`)、`PARAM_SPECS`、`CTRL_WIN` 上的 trackbar。
- **Produces**: 副作用 = 更新 trackbar 位置 / `ui.angle_deg`;无返回值。
- **已知取舍**: `input()` 阻塞期间 OpenCV 预览窗不刷新(可能短暂"未响应")。开发工具可接受,
  文档标注即可。

### 3. `w` 存草稿 —— 不变

`_save_params` 原样保留:写 `<stem>.tuned.json`(store 原生, 单通道)。

### 4. `W` 并入生产真源(load-merge-save + 确认)

```
def commit_to_source(calib_json_path: Path, ch: int,
                     calib, params, confirm: Callable[[], bool]) -> bool:
```

行为(注入 `path` 与 `confirm` 以便无 GUI 单测):
1. **前置守卫**: `calib.calibrated` 为假 → 拒绝(不把无 ROI 配置写进生产),返回 False。
2. **确认**: `confirm()` 返回假 → 中止(热键侧 `confirm` = 终端 `input()` 读 `y/N`)。
   确认前打印该通道 **旧→新** 的 `rotation` 与 `roi_frac` 摘要,让用户看清改动。
3. **load-merge-save**: `cfgs = load_channel_configs(path)`(缺失→空 dict)→
   `cfgs[ch] = ChannelConfig(calib, params)` → `save_channel_configs(path, cfgs)`。
   `save_channel_configs` 自带 tmp+replace 原子写。**其余通道原样保留**。
4. 打印 `CH{ch} 已并入 {path},保留其余 {n-1} 通道`,返回 True。

热键 `W` 处理:解析出通道 —— `ch = meta.get("channel")`;为 `None` 则打印"meta 无 channel,
无法定位真源槽位"并中止(不猜)。真源路径 = `parents[1]/config/water_level_calib.json`
(与 `_load_initial` 回退读取同一路径)。`confirm` = 终端 `input("确认并入 CHx? [y/N] ")`。

- **Consumes**: `meta['channel']`、当前 `calib`/`params`、真源 JSON。
- **Produces**: 覆盖写后的 `config/water_level_calib.json`(仅该通道被替换)。
- **假设**: `meta['channel']` 与真源的 **1-based** 通道键一致(recorder 与检测服务同约定)。
  若不一致会写错槽位 —— 摘要打印(第 2 步旧→新)可让用户当场发现。

### 5. 热键 / HELP / 窗口标题

- 新增 `e`(敲值)、`W`(并入真源);`w`/`r`/`c`/导航键不变。键码无冲突
  (`e`=101, `W`=87, `w`=119, 现役 `key = keyfull & 0xFF` 可区分大小写 w)。
- `HELP` 与 `VIEW_WIN` 标题补 `e敲值 w存草稿 W并入真源`。

## 数据流

```
敲值(e) ──setTrackbarPos/ui.angle_deg──▶ trackbar/ui
                                            │ 主循环每帧
                                            ▼
                              _read_state ─▶ calib/params ─▶ _render/detect_level(实时)
                                            │
                       w ──▶ <stem>.tuned.json (草稿, 单通道)
                       W ──▶ load config/water_level_calib.json
                             └▶ 换掉 CHx ─▶ save (原子, 其余通道保留)
```

## 错误处理

| 场景 | 处理 |
|---|---|
| 敲值非数字 / 越界 | REPL 打印提示, 值 clamp 到区间, 不退出 |
| `e` 时正在播放 | 进 REPL 前 `playing=False`, 退出后不自动续播 |
| `W` 时 `meta['channel']` 缺失 | 打印提示并中止, 不写真源 |
| `W` 时当前无 ROI (`not calibrated`) | `commit_to_source` 守卫拒绝, 不写 |
| `W` 用户答非 `y` | `confirm()` 返回假, 中止 |
| 真源文件不存在 | `load_channel_configs` 返回空 → 新建只含该通道 (打印告知) |
| `input()` 阻塞致预览不刷新 | 文档标注为模态编辑的已知取舍 |

## 测试 (纯函数, 无需 GUI 窗口)

1. **`PARAM_SPECS` 标度往返**: 对每个 spec 取代表值,断言 `from_pos(to_pos(v)) ≈ v`,
   且关键换算命中(`diff_thr` 7.5→pos 75→7.5;`blur_ksize` 5→v2→5;`crop` 0.12→12→0.12;
   `roi_fx` 0.30→300→0.30)。钉死"三处共用一张表"不漂移。
2. **`parse_edit_command`**: `"8 7.5"`(按编号)、`"diff_thr 7.5"`(按短名)、
   `"front_lvl 0.5"`、非法 `"foo bar"`、越界 `"crop_x 0.9"`(→clamp 提示)。
3. **`commit_to_source` load-merge-save**: 临时文件预置 CH1/CH2,
   commit CH5 → 文件含 CH1/CH2/CH5;再 commit CH1(新值)→ CH1 被替换、CH2 原样;
   `confirm=lambda: False` → 文件不变、返回 False;`calib` 未标定 → 拒绝、返回 False。

## 非目标 (YAGNI)

- 不引入 Tkinter/PySide 图形输入框(集成风险高于收益;终端敲值已满足精确输入)。
- 不做"敲值即自动落 sidecar"(会刷出大量中间 `.tuned.json`)。
- 不做 ROI 跟随盖边自动检测(额外失败模式;旋转是极少动的物理量,收益不抵)。
- 不动检测算法 / store 格式 / web 标定 UI。
