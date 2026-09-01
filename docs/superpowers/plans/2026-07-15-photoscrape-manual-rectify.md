# 包3: 4角标板矫正帧收编 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4 角人工标板后立即生成透视矫正图(用户看到"程序认为的板"并在其上作业),手绘 fallback 分支收编进已验证的 `plate_bbox_px` 仿射主路径;角点语义标签 + 点序凸性自检。

**Architecture:** 第 4 个角点落下 → 前端本地点序自检 → `POST /api/photoscrape/sketch_rectify` → 后端 `warpPerspective` 出正方形矫正帧 `manual_normalized.jpg` + 全幅 `plate_bbox_px` → 前端换底图、走现有 bbox 分支画区域/预览/提交;`manual_rectify` 记录随 manual summary 落盘供刮后回放二级链(契约 C-2)。端点失败回落现行 4 角单应老路(老路不删)。

**Tech Stack:** FastAPI 路由 + sketch_path 纯函数(cv2) + Vue3 HitlModal。

**Spec:** `docs/superpowers/specs/2026-07-15-photoscrape-scrape-closedloop-design.md` §6(契约 C-2)。

**依赖:** 包2 Task 3 已落地(`write_manual_summary(..., normalize_applied=...)` 与 `commit_sketch(..., source_summary_path=...)` 签名已存在)。执行本 plan 前确认 `git log` 含 "normalize_applied 实际应用参数持久化" 提交。

## Global Constraints

- **老路不删**:4 角透视单应链(`plate_corners_px` 经 preview/commit)保留为端点失败兜底与测试兼容;矫正帧只是**主路径**。
- **宁可无图,不可错帧**(全局契约,本包产出的 `manual_rectify` 是刮后回放二级链输入,字段形状逐字遵守 C-2):`{"plate_corners_px": [[x,y]×4], "px_per_cm": int, "frame_size": [W, H]}`,角点为**归一化帧**上的 [左上,右上,右下,左下]。
- **后端为准绳双重校验**:前端点序自检只是即时提示,后端 `validate_manual_corners` 必须独立校验(422 带中文原因)。
- `px_per_cm` 默认 40(20cm 板 → 800×800,仅供描点,无识别消费)。
- 不加新偏置旋钮;不改 cnc_path。
- 本机解释器 `E:/Anaconda/python.exe`;后端测试离线可跑;前端以 `npm run build` 编译零错为门槛(仓库无 JS 测试基建)。
- 注释与文案:中文为主体,技术术语保留英文。

---

### Task 1: `sketch_path` 纯函数 — 点序校验 + 矫正帧生成

**Files:**
- Modify: `eit_ptlc/controller/sketch_path.py`(`read_plate_bbox` 之后新增两函数)
- Test: `eit_ptlc/tests/test_sketch_rectify_offline.py`

**Interfaces:**
- Consumes: 无新依赖(cv2 函数内局部 import,与 `render_sketch_overlay` 同模式)。
- Produces(Task 2 路由消费):
  - `validate_manual_corners(corners_px: Any) -> list[tuple[float, float]]`——不符抛 `ValueError`(中文原因)。
  - `rectify_manual_frame(backdrop_path, corners_px, plate_size_cm, case_dir, *, px_per_cm: int = 40) -> dict`,返回 `{"image_path": str, "plate_bbox_px": {"x":0,"y":0,"w":S,"h":S}, "px_per_cm": int, "manual_rectify": {...C-2 形状}}`;cv2 缺失抛 `RuntimeError`(路由映射 503),底图不可读抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_sketch_rectify_offline.py`:

```python
"""4 角标板矫正帧 — 点序校验矩阵 + warp 黄金值 (spec §6.1, 契约 C-2)。"""

from __future__ import annotations

import numpy as np
import pytest

from eit_ptlc.controller import sketch_path as sp

_GOOD = [[30, 20], [170, 25], [165, 140], [28, 135]]  # 左上,右上,右下,左下


def test_validate_accepts_good_corners():
    pts = sp.validate_manual_corners(_GOOD)
    assert len(pts) == 4 and pts[0] == (30.0, 20.0)


@pytest.mark.parametrize("corners,frag", [
    ([[0, 0], [1, 1], [2, 2]], "4 个角点"),                       # 数量
    ([[0, 0], [10], [2, 2], [3, 3]], "数对"),                     # 形状
    ([[170, 20], [30, 25], [165, 140], [28, 135]], "左右颠倒"),    # 左右换
    ([[30, 140], [170, 135], [165, 20], [28, 25]], "上下颠倒"),    # 上下换
    ([[30, 20], [170, 25], [165, 140], [100, 80]], "凸四边形"),    # BL 内凹(方位检查可通过, 凸性不行)
    ([[10, 10], [50, 20], [90, 30], [50, 20]], "共线"),            # 同一斜线上退化(方位检查可通过)
])
def test_validate_rejects_bad_corners(corners, frag):
    with pytest.raises(ValueError, match=frag):
        sp.validate_manual_corners(corners)


def test_rectify_manual_frame_warps_to_square(tmp_path):
    cv2 = pytest.importorskip("cv2")
    img = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.fillPoly(img, [np.array(_GOOD, dtype=np.int32)], (255, 255, 255))  # 板内白
    backdrop = tmp_path / "after_normalized.jpg"
    cv2.imwrite(str(backdrop), img)
    res = sp.rectify_manual_frame(backdrop, _GOOD, 20.0, tmp_path, px_per_cm=10)
    out = cv2.imread(res["image_path"])
    assert [out.shape[1], out.shape[0]] == [200, 200]              # 20cm × 10px/cm
    assert float(out.mean()) > 180                                 # 板区充满画幅(近全白)
    assert res["plate_bbox_px"] == {"x": 0, "y": 0, "w": 200, "h": 200}
    assert res["manual_rectify"] == {
        "plate_corners_px": [[30.0, 20.0], [170.0, 25.0], [165.0, 140.0], [28.0, 135.0]],
        "px_per_cm": 10, "frame_size": [200, 200],
    }


def test_rectify_unreadable_backdrop_raises(tmp_path):
    pytest.importorskip("cv2")
    with pytest.raises(ValueError, match="底图"):
        sp.rectify_manual_frame(tmp_path / "nope.jpg", _GOOD, 20.0, tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_sketch_rectify_offline.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'validate_manual_corners'`

- [ ] **Step 3: 实现两函数**

在 `sketch_path.py` 的 `read_plate_bbox` 之后新增:

```python
# ---------------------------------------------------------------------------
# 4 角标板矫正帧 (spec §6, 契约 C-2): 点序校验 + warpPerspective 出正方形主路径帧。
# 端点失败时前端回落上面的 4 角单应老路 — 老路不删。
# ---------------------------------------------------------------------------

def validate_manual_corners(corners_px: Any) -> list[Point]:
    """校验 4 角点序 [左上,右上,右下,左下]: 数量/数对/方位/凸性; 不符 ValueError(中文原因)。

    后端准绳: 前端有同规则即时提示, 但以这里为最终校验(双重校验, 不信任客户端)。
    """
    if not isinstance(corners_px, (list, tuple)) or len(corners_px) != 4:
        raise ValueError("需恰好 4 个角点 [左上,右上,右下,左下]")
    pts: list[Point] = []
    for p in corners_px:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError(f"角点须为 [x,y] 数对, 得到 {p!r}")
        pts.append((float(p[0]), float(p[1])))
    (tlx, tly), (trx, tr_y), (brx, bry), (blx, bly) = pts
    if not (tlx < trx and blx < brx):
        raise ValueError("左右颠倒: 请按 左上→右上→右下→左下 顺序点四角")
    if not (tly < bly and tr_y < bry):
        raise ValueError("上下颠倒: 请按 左上→右上→右下→左下 顺序点四角")
    sign = 0.0
    for i in range(4):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 4]
        cx, cy = pts[(i + 2) % 4]
        z = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if z == 0:
            raise ValueError("角点共线/重合, 无法构成板框")
        if sign == 0.0:
            sign = z
        elif (z > 0) != (sign > 0):
            raise ValueError("四点不构成凸四边形, 请检查点位或顺序")
    return pts


def rectify_manual_frame(
    backdrop_path: Path | str,
    corners_px: Any,
    plate_size_cm: float,
    case_dir: Path | str,
    *,
    px_per_cm: int = 40,
) -> dict[str, Any]:
    """4 角单应 → 正方形矫正帧 manual_normalized.jpg(用户看到"程序认为的板")。

    返回含 C-2 形状的 manual_rectify 记录 — 提交时随 manual summary 落盘,
    供刮后 replay_normalization 二级回放。cv2 缺失 → RuntimeError(路由 503, 前端回落老路)。
    """
    try:
        import cv2  # type: ignore
        import numpy as _np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(f"cv2 缺失, 无法生成矫正帧: {exc}") from exc
    pts = validate_manual_corners(corners_px)
    img = cv2.imread(str(backdrop_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"底图不可读: {backdrop_path}")
    side = int(round(float(plate_size_cm) * px_per_cm))
    if side <= 0:
        raise ValueError(f"plate_size_cm/px_per_cm 无效: {plate_size_cm}/{px_per_cm}")
    src = _np.float32(pts)
    dst = _np.float32([[0, 0], [side, 0], [side, side], [0, side]])
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (side, side))
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    out = case_dir / "manual_normalized.jpg"
    cv2.imwrite(str(out), warped)
    return {
        "image_path": str(out),
        "plate_bbox_px": {"x": 0, "y": 0, "w": side, "h": side},
        "px_per_cm": px_per_cm,
        "manual_rectify": {
            "plate_corners_px": [[x, y] for x, y in pts],
            "px_per_cm": px_per_cm,
            "frame_size": [side, side],
        },
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_sketch_rectify_offline.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/sketch_path.py eit_ptlc/tests/test_sketch_rectify_offline.py
git commit -m "feat(sketch): 4角点序校验+矫正帧生成纯函数 — 凸性/方位矩阵校验, warp出正方形主路径帧 (契约C-2)"
```

---

### Task 2: `/sketch_rectify` 端点 + commit 链携带 `manual_rectify`

**Files:**
- Modify: `eit_ptlc/api/photoscrape_routes.py`(新端点;sketch_commit 透传)
- Modify: `eit_ptlc/controller/sketch_path.py`(`write_manual_summary` / `commit_sketch` 加 `manual_rectify` 参数)
- Test: `eit_ptlc/tests/test_sketch_rectify_offline.py`(追加路由/commit 用例)

**Interfaces:**
- Consumes: Task 1 两函数;既有 `_vision_output_dir`(vision_routes.py:27,仅需 `app.state.config_svc` 可存根);包2 的 `write_manual_summary(..., normalize_applied=...)`。
- Produces:
  - `POST /api/photoscrape/sketch_rectify` 请求 `{summary_path, corners_px, plate_size_cm?}` → 200 `{image_url, image_path, plate_bbox_px, px_per_cm, manual_rectify}`;422 校验失败 / 404 底图缺失 / 503 cv2 缺失。
  - `write_manual_summary(..., manual_rectify: dict | None = None)`、`commit_sketch(..., manual_rectify: dict | None = None)`;manual summary 顶层含 `manual_rectify`(给了才写)。

- [ ] **Step 1: 追加失败测试**

在 `test_sketch_rectify_offline.py` 追加:

```python
def _client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from eit_ptlc.api.photoscrape_routes import register_photoscrape_routes

    class _CfgStub:
        def read_section(self, name):
            return {"output_dir": str(tmp_path)}

    app = FastAPI()
    app.state.config_svc = _CfgStub()
    register_photoscrape_routes(app)
    return TestClient(app)


def _case_dir(tmp_path):
    cv2 = pytest.importorskip("cv2")
    case = tmp_path / "T1"
    case.mkdir()
    img = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.fillPoly(img, [np.array(_GOOD, dtype=np.int32)], (255, 255, 255))
    cv2.imwrite(str(case / "after_normalized.jpg"), img)
    (case / "summary.json").write_text('{"ok": false, "plate_size_cm": 20.0}', encoding="utf-8")
    return case


def test_rectify_endpoint_happy_path(tmp_path):
    client = _client(tmp_path)
    case = _case_dir(tmp_path)
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": _GOOD, "plate_size_cm": 20.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image_url"].startswith("/api/vision/image/")
    assert body["plate_bbox_px"]["w"] == body["plate_bbox_px"]["h"] == 800   # 默认 40px/cm
    assert body["manual_rectify"]["frame_size"] == [800, 800]
    assert (case / "manual_normalized.jpg").is_file()


def test_rectify_endpoint_rejects_bad_order(tmp_path):
    client = _client(tmp_path)
    case = _case_dir(tmp_path)
    bad = [_GOOD[1], _GOOD[0], _GOOD[2], _GOOD[3]]                           # 左右颠倒
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": bad,
    })
    assert r.status_code == 422 and "左右颠倒" in r.json()["detail"]


def test_rectify_endpoint_404_when_no_backdrop(tmp_path):
    client = _client(tmp_path)
    case = tmp_path / "T2"
    case.mkdir()
    (case / "summary.json").write_text("{}", encoding="utf-8")
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": _GOOD,
    })
    assert r.status_code == 404


def test_commit_sketch_persists_manual_rectify(tmp_path):
    import json as _json
    from eit_ptlc.config.models import GCodeCfg
    manual = {"plate_corners_px": [[30.0, 20.0], [170.0, 25.0], [165.0, 140.0], [28.0, 135.0]],
              "px_per_cm": 40, "frame_size": [800, 800]}
    res = sp.commit_sketch(
        [(100, 700), (700, 700), (700, 600)], GCodeCfg(), tmp_path,
        plate_size_cm=20.0, plate_bbox_px={"x": 0, "y": 0, "w": 800, "h": 800},
        sample_id="T", manual_rectify=manual,
    )
    doc = _json.loads((tmp_path / "T_manual" / "summary.json").read_text(encoding="utf-8"))
    assert doc["manual_rectify"] == manual
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_sketch_rectify_offline.py -q`
Expected: 新 4 例 FAIL(404 路由不存在 / `TypeError: unexpected keyword 'manual_rectify'`)

- [ ] **Step 3: 实现端点**

`photoscrape_routes.py` 在 `sketch_context` 端点之后加:

```python
    @app.post("/api/photoscrape/sketch_rectify")
    async def sketch_rectify(request: Request):
        """4 角标板 → 透视矫正帧(主路径): 落 case_dir/manual_normalized.jpg, 返回全幅
        plate_bbox_px + manual_rectify(C-2, 提交时随 manual summary 落盘供刮后回放)。
        失败语义: 422 点序/参数 | 404 底图缺失 | 503 cv2 缺失 → 前端回落 4 角单应老路。"""
        body = await request.json()
        summary_path = body.get("summary_path")
        if not summary_path:
            raise HTTPException(422, "缺少 summary_path")
        plate_size_cm = float(body.get("plate_size_cm") or sp.read_plate_bbox(summary_path)[1] or 20.0)
        case_dir = Path(summary_path).parent
        backdrop = None
        for name in ("after_normalized.jpg", "after.jpg"):   # 干净底图, 不用带叠加的门图
            cand = case_dir / name
            if cand.is_file():
                backdrop = cand
                break
        if backdrop is None:
            raise HTTPException(404, "case 目录缺少 after_normalized.jpg/after.jpg, 无法生成矫正帧")
        try:
            res = sp.rectify_manual_frame(backdrop, body.get("corners_px"), plate_size_cm, case_dir)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        output_dir = _vision_output_dir(request)
        try:
            rel = Path(res["image_path"]).resolve().relative_to(output_dir.resolve()).as_posix()
        except ValueError as exc:
            raise HTTPException(500, "矫正图不在视觉服务目录内, 无法提供 URL") from exc
        res["image_url"] = f"/api/vision/image/{rel}"
        return res
```

- [ ] **Step 4: commit 链透传**

4a. `sketch_path.write_manual_summary` 签名加 `manual_rectify: dict | None = None`(排在 `normalize_applied` 后),写盘前:

```python
    if manual_rectify is not None:
        summary_doc["manual_rectify"] = manual_rectify
```

4b. `sketch_path.commit_sketch` 签名加 `manual_rectify: dict | None = None`,`write_manual_summary` 调用加 `manual_rectify=manual_rectify`。

4c. `photoscrape_routes.py` sketch_commit 的 `sp.commit_sketch(...)` 实参加 `manual_rectify=body.get("manual_rectify"),`。

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_sketch_rectify_offline.py eit_ptlc/tests/test_normalize_replay_offline.py -q`
Expected: 全 passed(回放套件确认 manual_rectify 二级链字段兼容)

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/api/photoscrape_routes.py eit_ptlc/controller/sketch_path.py eit_ptlc/tests/test_sketch_rectify_offline.py
git commit -m "feat(sketch): /sketch_rectify 端点 + manual_rectify 随 commit 落盘 — 矫正帧主路径, 422/404/503 分级失败语义 (spec§6.1-6.2)"
```

---

### Task 3: 前端 — 角点语义标签 + 自检 + 矫正帧接管

**Files:**
- Modify: `eit_ptlc/web/src/api.js:214` 附近(加 `rectifySketch`)
- Modify: `eit_ptlc/web/src/components/HitlModal.vue`(script + template)

**Interfaces:**
- Consumes: Task 2 端点响应 `{image_url, plate_bbox_px, manual_rectify}`。
- Produces: 提交/预览 payload 变化 — 矫正帧生效时 `plate_bbox_px` 走全幅 bbox、commit 额外带 `manual_rectify` 与 `backdrop_ref`=矫正图 URL。

- [ ] **Step 1: api.js 加方法**

在 `commitSketch` 行(:214)后加:

```js
  rectifySketch: (payload) => http.post('/api/photoscrape/sketch_rectify', payload).then((r) => r.data),
```

- [ ] **Step 2: HitlModal 状态与复位**

script 顶部状态区(`hasPlateRef` 附近)加:

```js
const manualRectify = ref(null)  // 矫正帧记录: 提交时随 commit 落 manual summary (契约C-2)
const rectifiedUrl = ref('')     // 矫正图 URL: 生效时作 commit 的 backdrop_ref
let originalImage = null         // 矫正前底图 (重标四角回退用)
```

`watch(() => debug.hitl, ...)` 复位块(:47-66)加:

```js
  manualRectify.value = null
  rectifiedUrl.value = ''
  originalImage = null
```

- [ ] **Step 3: 角点语义标签 + 第 4 点触发自检与矫正**

3a. `redraw()` 四角绘制循环(:177-180)改为:

```js
  const CORNER_LABELS = ['左上', '右上', '右下', '左下']
  corners.value.forEach(([x, y], i) => {
    ctx.fillStyle = 'yellow'; ctx.beginPath(); ctx.arc(x, y, lw * 2.2, 0, 7); ctx.fill()
    ctx.fillStyle = 'black'; ctx.font = `${lw * 6}px sans-serif`
    ctx.fillText(`${i + 1} ${CORNER_LABELS[i]}`, x + lw * 3, y)
  })
```

3b. script 加纯函数(与后端 `validate_manual_corners` 同规则,后端为准绳):

```js
// 点序自检 (即时提示; 后端 /sketch_rectify 有同规则最终校验): 返回空串=通过
function cornerOrderError(cs) {
  if (cs.length !== 4) return '需恰好 4 个角点'
  const [tl, tr, br, bl] = cs
  if (!(tl[0] < tr[0] && bl[0] < br[0])) return '左右颠倒: 请按 左上→右上→右下→左下 顺序点'
  if (!(tl[1] < bl[1] && tr[1] < br[1])) return '上下颠倒: 请按 左上→右上→右下→左下 顺序点'
  let sign = 0
  for (let i = 0; i < 4; i++) {
    const a = cs[i], b = cs[(i + 1) % 4], c = cs[(i + 2) % 4]
    const z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    if (z === 0) return '角点共线, 请重新点'
    if (!sign) sign = Math.sign(z)
    else if (Math.sign(z) !== sign) return '四点不构成凸四边形, 请检查点位/顺序'
  }
  return ''
}
```

3c. `onCanvasClick`(:110-121)corners 分支改为:

```js
  if (pickMode.value === 'corners') {
    if (corners.value.length < 4) corners.value.push(p)
    if (corners.value.length === 4) {
      const err = cornerOrderError(corners.value)
      if (err) { errMsg.value = err; corners.value.pop(); redraw(); return }
      errMsg.value = ''
      rectifyFromCorners()          // 成功→矫正帧接管; 失败→老路(单应)兜底
    }
  } else {
```

3d. script 加矫正流程函数:

```js
// 4 角就绪 → 后端出矫正帧: 用户看到"程序认为的板"(角点错→图歪斜/切边一眼可见),
// 且后续画区域/预览/提交走与视觉成功分支相同的 plate_bbox_px 仿射主路径。
async function rectifyFromCorners() {
  busy.value = true
  try {
    const res = await api.rectifySketch({
      summary_path: debug.hitl.context, corners_px: corners.value, plate_size_cm: plateSize.value,
    })
    const img = new Image()
    img.onload = () => {
      originalImage = bgImage
      bgImage = img
      plateBbox.value = res.plate_bbox_px
      manualRectify.value = res.manual_rectify
      rectifiedUrl.value = res.image_url
      hasPlateRef.value = true
      polygon.value = []; preview.value = null
      pickMode.value = 'region'
      redraw()
    }
    img.onerror = () => { errMsg.value = '矫正图加载失败 — 回落原图 4 角标定(老路)'; pickMode.value = 'region' }
    img.src = res.image_url
  } catch (e) {
    errMsg.value = errText(e) + ' — 回落原图 4 角标定(老路)'
    pickMode.value = 'region'       // 老路: corners 已点满, 单应链照旧可预览/提交
  } finally {
    busy.value = false
  }
}
```

3e. `repickCorners()`(:137-142)改为(矫正帧回退):

```js
function repickCorners() {
  if (originalImage) { bgImage = originalImage; originalImage = null }
  manualRectify.value = null
  rectifiedUrl.value = ''
  hasPlateRef.value = false
  plateBbox.value = null
  corners.value = []
  polygon.value = []
  pickMode.value = 'corners'
  preview.value = null
  redraw()
}
```

- [ ] **Step 4: 提交/预览 payload 与模板**

4a. `submitSketch` 的 `api.commitSketch({...})` 实参改(带矫正记录与矫正图底图):

```js
    const res = await api.commitSketch({
      polygon_px: polygon.value, plate_size_cm: plateSize.value,
      summary_path: debug.hitl.context,
      backdrop_ref: rectifiedUrl.value || debug.hitl.image,
      manual_rectify: manualRectify.value || undefined,
      ..._plateRefPayload(),
    })
```

(`_plateRefPayload` 无需改:矫正生效时 `hasPlateRef=true` 自然走 `plate_bbox_px` 分支。)

4b. 模板「重标四角」按钮(:306)条件改为矫正态也可见:

```html
            <button v-if="!hasPlateRef || manualRectify" class="run ghost" @click="repickCorners">重标四角</button>
```

4c. 4 角提示文案(:289-292)改为:

```html
          <p v-if="!hasPlateRef" class="hitl-hint">
            视觉未框到板 — 请按 <b>左上→右上→右下→左下</b> 点四角标板 ({{ corners.length }}/4);
            点满后自动生成<b>矫正图</b>供确认(板应充满画幅、边缘横平竖直), 再画要刮取的闭合区域。
          </p>
          <p v-else-if="manualRectify" class="hitl-hint">
            已按 4 角矫正 — 当前即"程序认为的板"。若板歪斜/切边说明角点有误, 点「重标四角」重来;
            确认无误后画要刮取的<b>闭合区域</b>。
          </p>
```

- [ ] **Step 5: 编译验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: 编译零错(exit 0)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/web/src/api.js eit_ptlc/web/src/components/HitlModal.vue
git commit -m "feat(hitl): 4角语义标签+点序自检+矫正帧接管 — 点满即见'程序认为的板', 端点失败回落单应老路 (spec§6.3-6.4)"
```

---

### Task 4: 全量回归收尾

- [ ] **Step 1: 全量离线回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q`
Expected: 包2 后基线 + 本包新增(约 +13)全部 passed,0 failed。

- [ ] **Step 2: 前端再编译确认**

Run: `cd eit_ptlc/web && npm run build`
Expected: exit 0。

- [ ] **Step 3: Commit(如有回归修复)**

```bash
git add -A
git commit -m "test(sketch-rectify): 包3 回归收尾"
```

(无改动则跳过。)

---

## 上机验收(合并后, 非本 plan 范围)

1. 真机制造一次视觉找板失败(或用无板照片),走 4 角标板 → 确认矫正图弹出、板充满画幅;故意点错序 → 即时中文报错。
2. 矫正帧上画区域 → 预览 → 提交 → 实刮;刮后对账图(包2)确认二级回放帧对齐。
3. 断网/停后端复现端点失败 → 确认回落老路仍可提交。
