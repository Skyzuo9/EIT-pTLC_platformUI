# 液面检测漂移补偿改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把液位干湿判据从"绝对差分+全局阈值"一刀切替换为"有符号差分(只认变暗)+干参考区漂移补偿+限宽跨洞前沿扫描",消除阴影带竖线漏检与低阈值全屏误检。

**Architecture:** 检测核心仍是 `waterlevel_detector.py` 纯函数;参考图从单张灰度升级为 `ReferenceBundle`(板 ROI 灰度 + 干参考区灰度);每帧用干参考区(板外金属面板,永不湿)的中位数差估计全局光照漂移并加法补偿;前沿扫描允许桥接 ≤`front_gap_frac` 宽度的低对比缺口。`dry_ref_frac` 作为每通道标定字段进 `ChannelCalibration`,穿过 store 持久化与 config tiers 的 Pose 位姿层(否则 `merge_tiers` 重建 calib 时会静默抹掉)。

**Tech Stack:** Python (conda env `platformupper`), numpy, OpenCV;测试为 check()/unittest 风格离线模块(非 pytest)。

**诊断依据(2026-07-14, ch3/ch8 实录逐帧量化):** 症状根因是未补偿的台阶式全局光照漂移(−2~−9 灰度)抵消阴影带 +8.5 的湿润变暗信号(噪声底仅 ±1);修复后 ch3 前沿从全程卡死变为 18200 帧 20% → 22200 帧 100% 平滑推进,干燥期误检 ≤1.9%;ch8(无漂移健康通道)无回退。详见 memory `ptlc-waterlevel-drift-compensation`。

## Global Constraints

- 一刀切:删除 abs 差分路径,不留 detect_mode 兼容开关(用户决策,回退靠 git revert)。
- 时序湿润锁存(wet latch)本轮不做(用户决策:暂缓)。
- 新默认值:`diff_threshold` 5.0→**2.0**(补偿后 no_signal 门限),`wet_pixel_threshold` 12.0→**5.0**,新增 `front_gap_frac`=**0.15**。
- Otsu 无参考回退路径逐字保留。
- 干参考区按流向预置默认:`right_to_left`(CH1-4, 面板在左)→ `(0.02, 0.10, 0.13, 0.80)`;`left_to_right`(CH5-8, 面板在右)→ `(0.78, 0.15, 0.10, 0.70)`;`bottom_to_top` → None。
- 测试解释器:`E:/Anaconda/envs/platformupper/python.exe`,模块方式运行(非 pytest)。
- `LevelResult`/`Pose` 新字段一律带默认值,保持现有关键字/位置构造点不炸。
- 提交信息风格:`feat(waterlevel): 中文描述`,遵循仓库现有格式。

---

### Task 1: 检测核心 — 有符号差分 + ReferenceBundle + 干区漂移补偿

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_detector.py`
- Test: `eit_ptlc/tests/test_waterlevel_detector_offline.py`

**Interfaces:**
- Consumes: 现有 `extract_roi_gray(frame_bgr, calib, params)`(不改)。
- Produces(后续所有 Task 依赖):
  - `ChannelCalibration` 新字段 `dry_ref_frac: Optional[tuple[float,float,float,float]] = None`(旋转后画布比例,同 `roi_frac` 语义)。
  - `@dataclass ReferenceBundle: plate_gray: np.ndarray; dry_gray: Optional[np.ndarray] = None`
  - `compute_reference(frame_bgr, calib, params=None) -> Optional[ReferenceBundle]`
  - `extract_dry_gray(frame_bgr, calib, params) -> Optional[np.ndarray]`
  - `separate_wet(gray, ref: ReferenceBundle, dry_now, params) -> tuple[np.ndarray, float, np.ndarray]`(wet_mask, drift, corrected)
  - `detect_level(frame_bgr, calib, ref: Optional[ReferenceBundle] = None, params=None) -> LevelResult`(参数名 `ref_gray`→`ref`)
  - `LevelResult` 新字段 `drift: float = 0.0`
  - `WaterLevelDetectParams` 默认值 `diff_threshold=2.0`, `wet_pixel_threshold=5.0`

- [ ] **Step 1: 写失败测试** — 在 `test_waterlevel_detector_offline.py` 中:

先全局替换旧 API 调用(`ref_gray=` → `ref=`),`compute_reference` 断言改为 bundle:

```python
    ref = compute_reference(_dry_frame(), calib, params)
    check("compute_reference", ref is not None and ref.plate_gray.shape == (_Y1 - _Y0, _W),
          f"shape={None if ref is None else ref.plate_gray.shape}")
```

在 `otsu_percent_50` 用例之后、归一化 ROI 用例之前插入新用例(干区框 `(0.85, 0.05, 0.10, 0.30)` 在 300×200 画布上 = x[255,285) y[10,70),完全在 ROI(50,50,200,100) 之外):

```python
    # ---- 有符号差分: 变亮不算湿 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + _W // 2] = 250          # ROI 左半变亮 30
    r = detect_level(f, calib, ref=ref, params=params)
    check("brighten_not_wet", r.valid and r.percent <= 5, f"percent={r.percent}")

    # ---- 干区漂移补偿: 全局 +5 变亮 + 微弱湿润变暗 8 (净差 3 < 阈值 5) ----
    _DRYFRAC = (0.85, 0.05, 0.10, 0.30)
    calib_dry = ChannelCalibration(rotation_angle_deg=0.0, roi_bbox=_ROI,
                                   flow_direction="left_to_right", dry_ref_frac=_DRYFRAC)
    ref_dry = compute_reference(_dry_frame(), calib_dry, params)
    check("ref_has_dry", ref_dry is not None and ref_dry.dry_gray is not None, "")
    f = _dry_frame().astype(np.int16) + 5                    # 全局变亮 +5 (含干区)
    f[_Y0:_Y1, _X0:_X0 + _W // 2] -= 8                       # 左半湿润变暗 8 → 净 |diff|=3
    f = np.clip(f, 0, 255).astype(np.uint8)
    r_no = detect_level(f, calib, ref=ref, params=params)            # 无干区: 净差 3 < 5 漏检
    check("drift_uncompensated_misses", r_no.valid is False or r_no.percent <= 5,
          f"valid={r_no.valid} percent={r_no.percent}")
    r_yes = detect_level(f, calib_dry, ref=ref_dry, params=params)   # 有干区: 3+5=8 > 5 检出
    check("drift_compensated_detects", r_yes.valid and 45 <= r_yes.percent <= 55,
          f"percent={r_yes.percent}")
    check("drift_reported", 4.0 <= r_yes.drift <= 6.0, f"drift={r_yes.drift}")
```

末尾 `total = 14` 改为 `total = 19`。

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_detector_offline
```
预期: FAIL/TypeError(`ChannelCalibration` 无 `dry_ref_frac`,`detect_level` 无 `ref` 参数)。

- [ ] **Step 3: 实现** — `waterlevel_detector.py`:

3a. `from dataclasses import dataclass, field, replace`(补 `replace`)。

3b. `ChannelCalibration` 在 `roi_frac` 字段后追加(docstring 同步补一行字段说明):

```python
    dry_ref_frac: Optional[tuple[float, float, float, float]] = None
```
> 字段语义写入 docstring: "(fx, fy, fw, fh) 旋转后画布比例; 板外永不湿的干参考区 (如金属面板), 用于每帧全局光照漂移补偿; None=不补偿。"

3c. `WaterLevelDetectParams`: `diff_threshold: float = 2.0`(docstring 改为"补偿后差分绝对均值下限; 低于此值视为画面无变化 → 无信号"),`wet_pixel_threshold: float = 5.0`(docstring 改为"补偿后有符号差分(变暗为正) > 此值判为已浸润")。

3d. `LevelResult` 在 `diff_mean` 后加字段 + docstring 一行:

```python
    drift: float = 0.0
```

3e. 新增(放在 `compute_reference` 前):

```python
@dataclass
class ReferenceBundle:
    """参考捕获产物: 干板 ROI 灰度 + 干参考区灰度 (漂移补偿基准; 无 dry_ref_frac 时 None)。"""
    plate_gray: np.ndarray
    dry_gray: Optional[np.ndarray] = None


def extract_dry_gray(frame_bgr, calib: ChannelCalibration,
                     params: WaterLevelDetectParams):
    """按 calib.dry_ref_frac 抽取干参考区灰度 (与板 ROI 同一套旋转/crop/模糊管线,
    保证参考帧与检测帧像素对齐)。未配置干区返回 None。"""
    if calib.dry_ref_frac is None:
        return None
    dry_calib = replace(calib, roi_frac=calib.dry_ref_frac, roi_bbox=None)
    return extract_roi_gray(frame_bgr, dry_calib, params)
```

3f. `compute_reference` 改为:

```python
def compute_reference(frame_bgr, calib: ChannelCalibration,
                      params: Optional[WaterLevelDetectParams] = None):
    """从一帧"干板"图抽取参考 (板 ROI 灰度 + 干参考区灰度); 板 ROI 失败返回 None。"""
    params = params or WaterLevelDetectParams()
    plate = extract_roi_gray(frame_bgr, calib, params)
    if plate is None:
        return None
    return ReferenceBundle(plate_gray=plate,
                           dry_gray=extract_dry_gray(frame_bgr, calib, params))
```

3g. 新增共用口径纯函数(整定台 Task 6 复用):

```python
def separate_wet(gray, ref: ReferenceBundle, dry_now,
                 params: WaterLevelDetectParams):
    """干/湿分离 (detect_level 与整定台共用口径)。

    有符号差分 (只认变暗) + 干参考区漂移补偿:
        drift     = median(干区当前 − 干区参考)   # 全局变亮为正
        corrected = (板参考 − 板当前) + drift      # 湿润变暗为正, 漂移被抵消
    返回 (wet_mask, drift, corrected)。干区缺失/shape 不符时 drift=0 (不补偿)。
    """
    diff = ref.plate_gray.astype(np.float32) - gray.astype(np.float32)
    drift = 0.0
    if (ref.dry_gray is not None and dry_now is not None
            and dry_now.shape == ref.dry_gray.shape):
        drift = float(np.median(dry_now.astype(np.float32)
                                - ref.dry_gray.astype(np.float32)))
    corrected = diff + drift
    return corrected > params.wet_pixel_threshold, drift, corrected
```

3h. `detect_level` 干/湿分离段一刀切替换(签名 `ref_gray=None` → `ref=None`,docstring 同步:Args 里 `ref: 参考 bundle (compute_reference 产出); None 则走 Otsu 回退`;模块头部第 14 行"干/湿分离优先用参考图差分"改为"干/湿分离 = 有符号差分(只认变暗) + 干参考区漂移补偿; 无参考图退化到 Otsu"):

```python
    # --- 干/湿分离: 有符号差分 + 漂移补偿 (无参考退化 Otsu) ---
    if ref is not None and ref.plate_gray.shape == gray.shape:
        dry_now = extract_dry_gray(frame_bgr, calib, params)
        wet_mask, drift, corrected = separate_wet(gray, ref, dry_now, params)
        diff_mean = float(np.abs(corrected).mean())
        # 补偿后差分过低 = 画面无变化 = 前沿尚未进入 / 无信号
        if diff_mean < params.diff_threshold:
            return LevelResult(valid=False, diff_mean=diff_mean, drift=drift,
                               roi_size=(roi_w, roi_h), reason="no_signal")
    else:
        # 无参考图: Otsu 双峰分割 (湿区通常更暗 → 取暗侧为湿)
        drift = 0.0
        diff_mean = 0.0
        _t, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        wet_mask = otsu > 0
```

末尾 `LevelResult(...)` 加 `drift=drift`。

- [ ] **Step 4: 跑测试确认通过**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_detector_offline
```
预期: `共 19 用例, 失败 0`。
> 注意 `dry_no_signal` 用例: 全干帧 corrected≈0 < 2.0 → 仍 no_signal,应保持 PASS。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_detector.py eit_ptlc/tests/test_waterlevel_detector_offline.py
git commit -m "feat(waterlevel): 干湿判据一刀切改有符号差分+干参考区漂移补偿 — ReferenceBundle/dry_ref_frac/separate_wet, 默认阈值 2.0/5.0 (诊断: 阴影带漏检根因=光照漂移抵消)"
```

---

### Task 2: 检测核心 — 限宽跨洞前沿扫描

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_detector.py:286-304`(`_front_position_percent`)及 `detect_level` 调用处、`WaterLevelDetectParams`
- Test: `eit_ptlc/tests/test_waterlevel_detector_offline.py`

**Interfaces:**
- Consumes: Task 1 的 `detect_level` / `ref=` API。
- Produces: `WaterLevelDetectParams.front_gap_frac: float = 0.15`;`_front_position_percent(profile, ratio_level, inflow_from_high, gap_frac=0.15)`。语义:从流入侧扫描,湿列(≥ratio_level)推进 `last`;连续干列超过 `G=max(1, round(n*gap_frac))` 则截停;front = `(last+1)/n*100`;流入侧首列即干 → None(与旧版一致)。

- [ ] **Step 1: 写失败测试** — 追加两个用例(放在 Task 1 新用例后):

```python
    # ---- 限宽跨洞: 10% 缺口 (≤15%) 桥接, 30% 缺口截停 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + int(_W * 0.45)] = _WET              # [0, 45%) 湿
    f[_Y0:_Y1, _X0 + int(_W * 0.55):_X0 + int(_W * 0.70)] = _WET  # [55%, 70%) 湿, 缺口 10%
    r = detect_level(f, calib, ref=ref, params=params)
    check("front_gap_bridged", r.front_percent is not None and 65 <= r.front_percent <= 75,
          f"front={r.front_percent} (10%缺口应桥接到70)")
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + int(_W * 0.30)] = _WET              # [0, 30%) 湿
    f[_Y0:_Y1, _X0 + int(_W * 0.60):_X0 + int(_W * 0.70)] = _WET  # 缺口 30% > 15%
    r = detect_level(f, calib, ref=ref, params=params)
    check("front_gap_truncates", r.front_percent is not None and 25 <= r.front_percent <= 35,
          f"front={r.front_percent} (30%缺口应截停在30)")
```

`total = 19` 改为 `total = 21`。

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_detector_offline
```
预期: `front_gap_bridged` FAIL(旧扫描在首个干列即停,front≈45)。

- [ ] **Step 3: 实现**

3a. `WaterLevelDetectParams` 在 `front_ratio_level` 后加字段 + docstring 一行("前沿扫描允许桥接的最大缺口宽度占 ROI 比例; 防边界伪迹用小值截停"):

```python
    front_gap_frac: float = 0.15
```

3b. `_front_position_percent` 整体替换:

```python
def _front_position_percent(profile, ratio_level: float,
                            inflow_from_high: bool,
                            gap_frac: float = 0.15) -> Optional[float]:
    """沿流动方向 (从流入侧) 找前沿位置, 归一为 0~100%。

    限宽跨洞: 低对比缺口 (阴影带) ≤ gap_frac*n 列时桥接继续, 超过则截停 —— 物理上
    湿区从流入侧连续推进, 中段掉线是光度问题非干燥; 但远端孤立伪迹 (如 ROI 边界列)
    不应把前沿骗到 100%, 故缺口限宽。流入侧首列即干 → 前沿未进入, 返回 None。
    """
    n = len(profile)
    if n == 0:
        return None
    seq = profile[::-1] if inflow_from_high else profile
    if seq[0] < ratio_level:
        return None
    G = max(1, int(round(n * gap_frac)))
    last = 0
    gap = 0
    for i in range(1, n):
        if seq[i] >= ratio_level:
            last = i
            gap = 0
        else:
            gap += 1
            if gap > G:
                break
    return round((last + 1) / n * 100.0, 2)
```

3c. `detect_level` 调用处改为:

```python
    front_percent = _front_position_percent(
        profile, params.front_ratio_level, inflow_from_high, params.front_gap_frac)
```

- [ ] **Step 4: 跑测试确认通过** — 同 Step 2 命令,预期 `共 21 用例, 失败 0`(注意 `half_front_50`/`r2l_front_50`/`full_percent_100` 语义不变:半湿 last=n/2-1 → 50,全湿 → 100)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_detector.py eit_ptlc/tests/test_waterlevel_detector_offline.py
git commit -m "feat(waterlevel): 前沿扫描限宽跨洞 front_gap_frac=0.15 — 阴影带缺口桥接, 边界伪迹截停"
```

---

### Task 3: Store — dry_ref_frac / front_gap_frac 持久化 + 按侧默认干区

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_store.py`
- Test: `eit_ptlc/tests/test_waterlevel_store_offline.py`(现 `total = 16`)

**Interfaces:**
- Consumes: Task 1 的 `ChannelCalibration.dry_ref_frac`、Task 2 的 `front_gap_frac`。
- Produces: JSON 往返保真两字段;模块级常量 `DRY_REF_DEFAULT_BY_FLOW: dict[str, Optional[tuple]]`(Task 6 整定台 seeding 复用);`default_configs()` 按流向预置干区。

- [ ] **Step 1: 写失败测试** — 在 `_run()` 内追加(仿现有 check 风格;save→load 用 `tmp` 目录已有模式,若无则用 `tempfile.TemporaryDirectory`):

```python
    # ---- dry_ref_frac / front_gap_frac 往返保真 ----
    import tempfile
    cfg_rt = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=1.0, roi_frac=(0.1, 0.0, 0.2, 1.0),
                                 flow_direction="right_to_left",
                                 dry_ref_frac=(0.02, 0.10, 0.13, 0.80)),
        params=WaterLevelDetectParams(front_gap_frac=0.22))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "rt.json"
        save_channel_configs(p, {3: cfg_rt})
        back = load_channel_configs(p)[3]
    check("dry_ref_frac_roundtrip", back.calib.dry_ref_frac == (0.02, 0.10, 0.13, 0.80),
          f"got={back.calib.dry_ref_frac}")
    check("front_gap_frac_roundtrip", abs(back.params.front_gap_frac - 0.22) < 1e-9,
          f"got={back.params.front_gap_frac}")

    # ---- 默认配置按侧预置干区 ----
    dc = default_configs()
    check("default_dry_left", dc[3].calib.dry_ref_frac == (0.02, 0.10, 0.13, 0.80),
          f"ch3={dc[3].calib.dry_ref_frac}")
    check("default_dry_right", dc[8].calib.dry_ref_frac == (0.78, 0.15, 0.10, 0.70),
          f"ch8={dc[8].calib.dry_ref_frac}")
```

`total = 16` 改为 `total = 20`。(文件顶部 import 需含 `Path`/`ChannelCalibration`/`WaterLevelDetectParams`,已有则不重复。)

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_store_offline
```
预期: FAIL(dry_ref_frac 丢失 / front_gap_frac 回默认 / default 无干区)。

- [ ] **Step 3: 实现** — `waterlevel_store.py`:

3a. 模块级常量(`NUM_CHANNELS` 下方):

```python
# 干参考区按流向的预置默认 (旋转后画布比例; 板外金属面板, 2026-07-14 逐通道首帧核实):
# right_to_left (CH1-4) 面板在左; left_to_right (CH5-8) 镜像在右; 垂直流无预置。
DRY_REF_DEFAULT_BY_FLOW: dict[str, Optional[tuple[float, float, float, float]]] = {
    "right_to_left": (0.02, 0.10, 0.13, 0.80),
    "left_to_right": (0.78, 0.15, 0.10, 0.70),
    "bottom_to_top": None,
}
```

3b. `_calib_to_dict` 在 roi_frac 写出块后追加:

```python
    if c.dry_ref_frac is not None:
        d["dry_ref_frac"] = [float(v) for v in c.dry_ref_frac]
```

3c. `_from_native_entry` 在 roi_frac 解析后追加,并把 `dry_ref_frac=dry_frac` 传入 `ChannelCalibration(...)`:

```python
    df = cd.get("dry_ref_frac")
    dry_frac = tuple(float(v) for v in df) if isinstance(df, (list, tuple)) and len(df) == 4 else None
```

3d. `_params_to_dict` 加 `"front_gap_frac": p.front_gap_frac,`;`_params_from_native` 加 `front_gap_frac=float(d.get("front_gap_frac", base.front_gap_frac)),`。

3e. `default_configs()` 中 calib 构造改为:

```python
        out[ch] = ChannelConfig(
            calib=ChannelCalibration(flow_direction=flow,
                                     dry_ref_frac=DRY_REF_DEFAULT_BY_FLOW.get(flow)),
            params=WaterLevelDetectParams(),
        )
```

(香橙派格式 `_from_orangepi_entry` 不加字段——旧格式无此概念,载入后为 None,属预期。)

- [ ] **Step 4: 跑测试确认通过** — 同 Step 2 命令,预期 `共 20 用例, 失败 0`。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_store.py eit_ptlc/tests/test_waterlevel_store_offline.py
git commit -m "feat(waterlevel): store 持久化 dry_ref_frac/front_gap_frac + 按流向预置干参考区默认"
```

---

### Task 4: Config tiers — Pose 携带 dry_frac + judgment 层收编 front_gap_frac

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_config_tiers.py`
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`(总数行自动计数,无需手改)

**Interfaces:**
- Consumes: Task 1 `dry_ref_frac`、Task 2 `front_gap_frac`。
- Produces: `Pose(rotation_deg, flow, xy_px, dry_frac=None)`(第 4 位新字段带默认,现有位置构造不炸);`split_tiers`/`merge_tiers` 往返保真 dry_frac;`GLOBAL_JUDGMENT_FIELDS` 含 `"front_gap_frac"`。
- **关键动机:** `merge_tiers` 从零重建 `ChannelCalibration`,不穿 Pose 的字段会在每次 `apply_commit` 被静默抹掉。

- [ ] **Step 1: 写失败测试** — 在测试文件 `_run()`(或对应结构)内追加:

```python
    # ---- dry_frac 穿 split/merge 往返 + apply_commit 不串台 ----
    cfg_d = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=0.0, roi_frac=(0.2, 0.0, 0.1, 0.5),
                                 flow_direction="right_to_left",
                                 dry_ref_frac=(0.02, 0.1, 0.13, 0.8)),
        params=WaterLevelDetectParams())
    tv_d = split_tiers(cfg_d)
    check("pose_carries_dry", tv_d.pose.dry_frac == (0.02, 0.1, 0.13, 0.8),
          f"got={tv_d.pose.dry_frac}")
    back_d = merge_tiers(tv_d.judgment, tv_d.size_px, tv_d.pose)
    check("merge_keeps_dry", back_d.calib.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
          f"got={back_d.calib.dry_ref_frac}")
    # 广播判据层不得覆盖他通道自己的 dry_frac
    other = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=0.0, roi_frac=(0.3, 0.0, 0.1, 0.5),
                                 flow_direction="left_to_right",
                                 dry_ref_frac=(0.78, 0.15, 0.10, 0.70)),
        params=WaterLevelDetectParams())
    merged_d = apply_commit({1: cfg_d, 2: other}, 1, cfg_d,
                            broadcast_global=True, with_pose=True)
    check("broadcast_keeps_other_dry",
          merged_d[2].calib.dry_ref_frac == (0.78, 0.15, 0.10, 0.70),
          f"got={merged_d[2].calib.dry_ref_frac}")
    check("judgment_has_front_gap", "front_gap_frac" in GLOBAL_JUDGMENT_FIELDS, "")
```

(import 处补 `GLOBAL_JUDGMENT_FIELDS`,其余符号该文件已有。)

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline
```
预期: FAIL(`Pose` 无 dry_frac 属性)。

- [ ] **Step 3: 实现** — `waterlevel_config_tiers.py`:

3a. `GLOBAL_JUDGMENT_FIELDS` 元组末尾加 `"front_gap_frac",`。

3b. `Pose` 加字段(docstring 补一行"dry_frac: 干参考区比例框, 逐通道位姿层, 随 with_pose 提交"):

```python
    dry_frac: Optional[tuple[float, float, float, float]] = None
```

3c. `split_tiers` 中 pose 构造改为:

```python
    pose = Pose(rotation_deg=calib.rotation_angle_deg, flow=calib.flow_direction,
                xy_px=pose_xy, dry_frac=calib.dry_ref_frac)
```

3d. `merge_tiers` 两个 `ChannelCalibration(...)` 构造(标定成立分支与未标定分支)各加一行 `dry_ref_frac=pose.dry_frac,`。

- [ ] **Step 4: 跑测试确认通过** — 同 Step 2 命令,预期失败 0(自动计数,总数比原来 +4)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): tiers Pose 携带 dry_frac 防 merge 抹除 + judgment 层收编 front_gap_frac"
```

---

### Task 5: Service — 快照暴露 drift, get_params 暴露 front_gap_frac

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_service.py:291-299`(`get_params`)、`:317-340`(`snapshot`)、`:397`(`_process` 参考捕获日志)
- Test: `eit_ptlc/tests/test_waterlevel_service_offline.py`(现 `total = 12`)

**Interfaces:**
- Consumes: Task 1 的 `ReferenceBundle`(`_process` 里 `compute_reference`/`detect_level` 调用形参不变,bundle 自动流转——`self._refs[ch]` 存 bundle,原样传回 `detect_level` 第 3 个位置参数;`LevelResult.drift`)。
- Produces: `snapshot()["channels"][ch]["drift"]`(float,四舍五入 2 位);`get_params(ch)["front_gap_frac"]`。auto-drain 消费的 percent/front_percent/valid 键不动(`waterlevel_observation.py` 零改动)。

- [ ] **Step 1: 写失败测试** — 在测试文件追加两个 check(仿现有 svc 构造模式;快照用例可直接向 `svc._results[1]` 塞 `LevelResult(valid=True, percent=50.0, drift=5.5, ...)` 后断言):

```python
    r_drift = LevelResult(valid=True, percent=50.0, wet_ratio=0.5,
                          diff_mean=8.0, drift=5.5, roi_size=(100, 50))
    svc._results[1] = r_drift
    snap_ch = svc.snapshot()["channels"][1]
    check("snapshot_exposes_drift", snap_ch.get("drift") == 5.5, f"got={snap_ch.get('drift')}")
    check("get_params_front_gap", "front_gap_frac" in svc.get_params(1),
          str(svc.get_params(1).keys()))
```

`total = 12` 改为 `total = 14`。(import 处补 `LevelResult`。)

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_service_offline
```
预期: 新增 2 例 FAIL,原 12 例 PASS(bundle 流转对 service 透明)。

- [ ] **Step 3: 实现** — `waterlevel_service.py`:

- `get_params` 返回 dict 中 `front_ratio_level` 行后加 `"front_gap_frac": p.front_gap_frac,`;
- `snapshot` 通道 dict 中 `"diff_mean"` 行后加 `"drift": round(r.drift, 2),`;
- `_process` 第 397 行日志 `ref.shape` 改为 `ref.plate_gray.shape`(`ReferenceBundle` 无 `.shape`,不改则参考捕获时 AttributeError):

```python
                log.info("[WL] CH%s 参考图已捕获 %s (干区 %s)", ch, ref.plate_gray.shape,
                         None if ref.dry_gray is None else ref.dry_gray.shape)
```

- [ ] **Step 4: 跑测试确认通过** — 同 Step 2 命令,预期 `共 14 用例, 失败 0`。再跑消费端回归:

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_observation_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
```
预期: 全 PASS(observation 只读 percent/front_percent/valid;LevelResult 新字段带默认)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_service.py eit_ptlc/tests/test_waterlevel_service_offline.py
git commit -m "feat(waterlevel): service 快照暴露 drift, get_params 暴露 front_gap_frac"
```

---

### Task 6: 整定台 — Ctrl+右键框干区 + 共用判据口径 + HUD drift + front_gap 滑块

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`
- Test: `eit_ptlc/tests/test_waterlevel_tune_offline.py`

**Interfaces:**
- Consumes: Task 1 `ReferenceBundle`/`separate_wet`/`extract_dry_gray`、Task 2 `front_gap_frac`、Task 3 `DRY_REF_DEFAULT_BY_FLOW`。
- Produces: 交互约定 — **Ctrl+右键拖 = 框干参考区**(普通右键拖 = 框 ROI 不变);`_UIState.dry_frac` 为干区当前值真源,`_read_state` 把它写进 `ChannelCalibration.dry_ref_frac`,随 'w'/'W' existing 路径持久化(Task 3/4 已打通)。

- [ ] **Step 1: 写失败测试** — `test_waterlevel_tune_offline.py` 针对纯函数部分追加(该文件测 `ParamSpec`/`parse_edit_command` 等纯函数;仿其风格):

```python
    # ---- front_gap 滑块规格: 自然值 <-> 轨位互逆 ----
    sp = SPECS["front_gap"]
    check("front_gap_spec_roundtrip", abs(sp.from_pos(sp.to_pos(0.15)) - 0.15) < 1e-9,
          f"got={sp.from_pos(sp.to_pos(0.15))}")
    check("front_gap_spec_clamp", sp.to_pos(9.9) == 40, f"got={sp.to_pos(9.9)}")
```

并把该文件已有的用例总数行相应 +2(若该文件为自动计数则不改)。

- [ ] **Step 2: 跑测试确认失败**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
```
预期: KeyError `front_gap`。

- [ ] **Step 3: 实现** — `wl_replay_tune.py`:

3a. import 区: `from eit_ptlc.controller.waterlevel_detector import (...)` 中补 `ReferenceBundle, compute_reference, separate_wet, extract_dry_gray`(保留现有项);`from eit_ptlc.controller.waterlevel_store import (...)` 补 `DRY_REF_DEFAULT_BY_FLOW`。

3b. `PARAM_SPECS` 在 `front_lvl` 条目后追加:

```python
    ParamSpec("front_gap", "front_gap(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
```

3c. `_UIState.__init__` 追加:

```python
        self.dry_frac = None                # 干参考区比例框 (Ctrl+右键拖设置; 漂移补偿)
        self.dry_drag0 = None               # 干区拖框起点
        self.dry_drag_cur = None            # 干区拖框当前点
```

`main()` 中 `ui = _UIState(...)` 后一行 seeding:

```python
    ui.dry_frac = calib0.dry_ref_frac or DRY_REF_DEFAULT_BY_FLOW.get(calib0.flow_direction)
```

同时 `_load_initial` 里 meta snapshot 解析处,`ChannelCalibration(...)` 构造补:

```python
            dry_ref_frac=tuple(float(v) for v in snap["dry_ref_frac"])
            if isinstance(snap.get("dry_ref_frac"), (list, tuple)) and len(snap["dry_ref_frac"]) == 4 else None,
```

3d. `_read_state` 的 `ChannelCalibration(...)` 构造加 `dry_ref_frac=ui.dry_frac,`;`WaterLevelDetectParams(...)` 加 `front_gap_frac=val("front_gap"),`;`_add_trackbars` 的 `init` dict 加 `"front_gap": params.front_gap_frac,`。

3e. 鼠标回调 `_make_mouse_cb`:右键分支前插入 Ctrl 判定(顺序在普通 RBUTTONDOWN 之前),MOUSEMOVE/RBUTTONUP 优先处理干区拖框:

```python
        elif event == cv2.EVENT_RBUTTONDOWN and inside_left and (flags & cv2.EVENT_FLAG_CTRLKEY):
            ui.dry_drag0 = (x, y); ui.dry_drag_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.dry_drag0 is not None:
            ui.dry_drag_cur = (x, y)
        elif event == cv2.EVENT_RBUTTONUP and ui.dry_drag0 is not None:
            x0, y0 = ui.dry_drag0
            rx, ry = min(x0, x), min(y0, y)
            rww, rhh = abs(x - x0), abs(y - y0)
            if rww >= 3 and rhh >= 3:
                ui.dry_frac = box_to_roi_frac(rx, ry, rww, rhh, rw, rh)
                print(f"[整定台] 框干参考区 → frac ({ui.dry_frac[0]:.3f},{ui.dry_frac[1]:.3f},"
                      f"{ui.dry_frac[2]:.3f},{ui.dry_frac[3]:.3f})")
            ui.dry_drag0 = ui.dry_drag_cur = None
```

(注意:此三条必须排在现有 `EVENT_RBUTTONDOWN`/`MOUSEMOVE(roi_drag0)`/`RBUTTONUP(roi_drag0)` 分支**之前**,elif 链天然互斥。)

3f. `_wet_mask` 一刀切替换(签名变,与 detect_level 共用 `separate_wet`):

```python
def _wet_mask(frame, gray: np.ndarray, ref: Optional[ReferenceBundle],
              calib: ChannelCalibration,
              params: WaterLevelDetectParams) -> tuple[np.ndarray, str, float]:
    """复算湿区掩膜供叠加 (仅显示用, 经 separate_wet 与 detect_level 严格同口径)。"""
    if ref is not None and ref.plate_gray.shape == gray.shape:
        dry_now = extract_dry_gray(frame, calib, params)
        mask, drift, _corr = separate_wet(gray, ref, dry_now, params)
        return mask, "diff", drift
    _t, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return otsu > 0, "otsu", 0.0
```

3g. `_render`:

- `ref_gray = extract_roi_gray(...)` 行改为 `ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None`;
- `detect_level(frame, calib, ref_gray=ref_gray, params=params)` → `detect_level(frame, calib, ref=ref, params=params)`;
- `mask, mode = _wet_mask(gray, ref_gray, params)` → `mask, mode, _drift_vis = _wet_mask(frame, gray, ref, calib, params)`;
- 左图画干区框(ROI 框绘制块之后):

```python
    if calib.dry_ref_frac is not None:
        dfx, dfy, dfw, dfh = calib.dry_ref_frac
        cv2.rectangle(left, (round(dfx * rw), round(dfy * rh)),
                      (round((dfx + dfw) * rw), round((dfy + dfh) * rh)), (255, 128, 0), 1)
    if ui is not None and ui.dry_drag0 is not None and ui.dry_drag_cur is not None:
        cv2.rectangle(left, ui.dry_drag0, ui.dry_drag_cur, (255, 128, 0), 1)
```

- HUD 第 3 行加 drift:

```python
        f"diff_mean={result.diff_mean:5.2f} (thr {params.diff_threshold:.1f})  "
        f"drift={result.drift:+5.2f}  roi={result.roi_size}",
```

- 主循环 `sig` 元组补 `ui.dry_frac, ui.dry_drag0, ui.dry_drag_cur`(否则框完干区不重绘)。

3h. `_plot_full_run`:`ref_gray = extract_roi_gray(...)` → `ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None`;`detect_level(frame, calib, ref_gray=ref_gray, ...)` → `ref=ref`;ax2 加 drift 曲线:

```python
    drifts.append(r.drift)   # 循环内收集 (初始化 drifts = [])
    ax2.plot(ts, drifts, ".-", ms=2, alpha=0.6, color="tab:blue", label="drift (干区漂移)")
```

3i. `HELP` 文本 与 `VIEW_WIN` 标题:右键说明后补 `Ctrl+右键拖=框干参考区(漂移补偿)`。模块 docstring 头部功能描述同步一句。

- [ ] **Step 4: 跑测试确认通过**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
```
预期: 失败 0。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_tune_offline.py
git commit -m "feat(waterlevel): 整定台 Ctrl+右键框干参考区 + separate_wet 共用口径 + HUD/曲线显示 drift + front_gap 滑块"
```

---

### Task 7: 真录像端到端验证 + 全量回归

**Files:**
- 无代码改动(验证任务);如发现缺陷回到对应 Task 修。

**Interfaces:**
- Consumes: Task 1-6 全部产物;`data/water_level_recordings/adhoc/ch3_20260708_211423.avi`(病态通道)与 `ch8_20260713_205434.avi`(健康通道)。

- [ ] **Step 1: ch3 病态通道复核** — 启动整定台,设参考帧 0,确认干区默认框落在左侧金属面板上(必要时 Ctrl+右键重框),`wet_thr` 敲 5.0、`diff_thr` 敲 2.0,按 `c` 跑整段曲线:

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/adhoc/ch3_20260708_211423.avi
```
预期(对照 2026-07-14 诊断基线): front(t) 不再卡死——约 18000 帧进入 ROI 后从 ~20% 平滑推进,约 22000-23000 帧到 100%;percent(t) 尾段稳定 ≥95%;drift 曲线呈台阶(+3/+6/+9);干燥期(前 15000 帧)percent≈0 且 front=None。

- [ ] **Step 2: ch8 健康通道无回退复核** — 同法跑:

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/adhoc/ch8_20260713_205434.avi
```
预期: 干燥期零误检;约 6500 帧 front 达 100% 并稳定保持;percent 尾段稳定 ~100%(旧算法为 93~99% 抖动)。

- [ ] **Step 3: 全量相关离线套件**

```bash
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_detector_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_store_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_service_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_observation_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_single_writer_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_write_offline
"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
```
预期: 全部 `失败 0`。

- [ ] **Step 4: Commit(如 Step 1-3 触发过修补)**

```bash
# 主树有他会话 WIP, 禁止 git add -A; 只加本项目触碰的文件
git add eit_ptlc/controller/waterlevel_detector.py eit_ptlc/controller/waterlevel_store.py \
        eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/controller/waterlevel_service.py \
        eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_detector_offline.py \
        eit_ptlc/tests/test_waterlevel_store_offline.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py \
        eit_ptlc/tests/test_waterlevel_service_offline.py eit_ptlc/tests/test_waterlevel_tune_offline.py
git commit -m "fix(waterlevel): 真录像端到端验证触发的修补 (ch3 解卡 + ch8 无回退 + 全量离线绿)"
```

---

## 上机与部署留后项(不在本 plan 内,执行后人工跟进)

1. **生产真源迁移**:`config/water_level_calib.json` 里 8 通道旧阈值(wet 12/7.6 等)语义已变,上机前用整定台对每通道执行一次 `W` 并入(判据层广播 wet_thr=5/diff_thr=2/front_gap=0.15;各通道 Ctrl+右键核框干区后随 with_pose 落盘)。后端必须停机(单写者约束)。
2. **真机活跃档(1280×720)复核**:dry_ref_frac 分辨率无关,但需目检干区框未压到板/导轨。
3. **auto-drain T2 复核**:修复后 percent 可达 ~99%,`trigger_percent_t2=90` 恢复可触发——按 memory `ptlc-waterlevel-auto-drain` 的上机清单一并验证。
4. 网页标定 UI(`WaterLevelCalibrate.vue`/`WaterLevelChannel.vue`)暂不加干区框选——CLI 整定台已覆盖;若后续要加,dry_frac 已在 Pose 位姿层,网页天然有提交权。
