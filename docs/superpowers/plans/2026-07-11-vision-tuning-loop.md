# 视觉调参闭环 (rotation 全链 + 载入生产 case + 共用参数组件) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `image_plate_rotation_deg` 纳入调参面全链、支持一键载入生产 case 复盘调参、视觉栏与重识别门共用一套识别参数组件并显示生产基线实际值,使"生产不满意→调试台复盘→应用到生产→门内重新识别"闭环真正可用。

**Architecture:** spec 切片 3。后端顺流而下四小步(reanalyze 透传 → 调试台参数集 → 应用到生产 → cases 列表/载入,全 TDD);前端一个共用组件 `RecognitionParams.vue`(value/override 双模式)接入两处。关键利好:`VisionService.with_overrides` 与 `analyze_action` **均已支持** rotation(`vision_controller.py:170,188,512,546`),后端只differ在参数集与透传元组。

**Tech Stack:** FastAPI + pydantic(路由)、pytest 离线测试(TestClient + Fake 桩,镜像现有套路)、Vue 3 `<script setup>`。

**Spec:** `docs/superpowers/specs/2026-07-11-vision-ui-tuning-loop-design.md`(切片 3)

**前置:** Plan 1(`2026-07-11-vision-ui-display-layer.md`)已落地 — Task 6/7 与其改同两个前端文件;若行号有偏移,以锚文本定位。

## Global Constraints

- 只改 `eit_ptlc/` 活跃树;`View/pTLC_Viewing/tlc_analyze.py` 本次**只读**(方案 A 不动算法内部)。
- 参数空值语义:前端 `''` = 不覆盖/用基线;`0` 与 `0.0` 是合法值必须透传(沿用 `p.x !== '' && p.x != null` 判式,防 None-sentinel 零值坑)。
- `image_plate_rotation_deg` 语义:`null` = 每帧自动估计;写回 config 时允许 null(`VisionCfg` 字段本为 Optional)。
- 不破坏 run-vs-edit 解耦不变量(浏览/调参不得终止运行中的 run)。
- 后端改动须有离线 pytest 覆盖,现有全量离线套件保持全绿;前端无测试设施,`npm run build` 必须通过。
- UI 文案中文,风格沿用现有自研组件(无 UI 组件库)。
- 新文件服务端点必须有目录穿越防护与后缀白名单(沿用 `vision_routes.py` / `vision_debug_routes.py` 现有模式)。

pytest 一律在仓库根 `E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next` 下执行;`npm` 在 `eit_ptlc/web/` 下执行。

---

### Task 1: reanalyze 路由透传 rotation + action 旋钮声明

**Files:**
- Modify: `eit_ptlc/api/photoscrape_routes.py:154-155`(透传元组)
- Modify: `eit_ptlc/config/actions/04_photoscrape/vision.yaml:20`(加参数行)
- Test: `eit_ptlc/tests/test_photoscrape_reanalyze_offline.py`(追加 2 测)

**Interfaces:**
- Consumes: `analyze_action` 已有的 `image_plate_rotation_deg: Optional[float]` 关键字(`vision_controller.py:512`)。
- Produces: `POST /api/photoscrape/reanalyze` 接受可选 `image_plate_rotation_deg`(float, [-180,180],经 executor 契约校验);action `photoscrape.analyze` 新增同名可选旋钮(VM 运行前旋钮面板自动出现)。

- [ ] **Step 1: 写失败测试** — `test_photoscrape_reanalyze_offline.py` 文件末追加:

```python
def test_reanalyze_forwards_rotation_deg_including_zero(tmp_path):
    # rotation=0.0 是合法覆盖值(整数零), 必须透传, 不得被判空丢弃 (None-sentinel 零值坑)。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_rotation_deg": 0.0},
    )
    assert r.status_code == 200, r.text
    assert captured["overrides"] == {"image_plate_rotation_deg": 0.0}


def test_reanalyze_rejects_out_of_range_rotation(tmp_path):
    # 超出 [-180,180] 经 executor 契约校验被拒 → 422, 不触及 analyze。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_rotation_deg": 200.0},
    )
    assert r.status_code == 422, r.text
    assert not captured
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest eit_ptlc/tests/test_photoscrape_reanalyze_offline.py -q`
Expected: 第一测必 FAIL(路由未透传该键,`captured["overrides"]` 为 `{}`);第二测可能已 PASS(executor 对未声明参数本就拒 422)— 以第一测红为准。

- [ ] **Step 3: 最小实现**

`eit_ptlc/api/photoscrape_routes.py:154-155` 把:

```python
        for key in ("image_plate_orientation", "auto_rectify_tilt",
                    "rectify_min_angle_deg", "min_row_score"):
```

改为:

```python
        for key in ("image_plate_orientation", "auto_rectify_tilt",
                    "rectify_min_angle_deg", "min_row_score",
                    "image_plate_rotation_deg"):
```

`eit_ptlc/config/actions/04_photoscrape/vision.yaml` 在 `min_row_score` 行(:20)后追加:

```yaml
    - {name: image_plate_rotation_deg,  type: float,  required: false, min: -180, max: 180, label: 相机滚转角覆盖 (deg)}
```

- [ ] **Step 4: 跑测确认通过**

Run: `python -m pytest eit_ptlc/tests/test_photoscrape_reanalyze_offline.py -q`
Expected: 全绿(原 7 测 + 新 2 测)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/api/photoscrape_routes.py eit_ptlc/config/actions/04_photoscrape/vision.yaml eit_ptlc/tests/test_photoscrape_reanalyze_offline.py
git commit -m "feat(reanalyze): 门内重识别透传 image_plate_rotation_deg (含 0.0), action 声明同名旋钮"
```

---

### Task 2: 调试台服务/请求模型/bootstrap 纳入 rotation

**Files:**
- Modify: `eit_ptlc/controller/vision_debug_service.py:23-28`(`_RECOGNITION_KEYS`)、`:58-63`(`_initial_state` recognition)
- Modify: `eit_ptlc/api/vision_debug_routes.py:31-35`(`AnalyzeRequest`)
- Modify: `eit_ptlc/runtime/bootstrap.py:273-278`(recognition_defaults 播种)
- Test: `eit_ptlc/tests/test_vision_debug.py`(追加 1 测)

**Interfaces:**
- Consumes: `VisionService.with_overrides` 的 `allowed` 集已含 `image_plate_rotation_deg`(`vision_controller.py:170,188`)— 服务把整个 recognition dict 传给它,键入集即贯通。
- Produces: 调试台 state `recognition_params` 含第 5 键 `image_plate_rotation_deg`(float|None,None=每帧自动估);`POST /api/vision/debug/analyze` 接受该可选字段。Task 3(应用到生产)与 Task 6(前端)依赖这一键名。

- [ ] **Step 1: 写失败测试** — `test_vision_debug.py` 文件末追加(复用文件内既有 `FakeCameraController` / `FakeVisionService` / `_image_bytes`):

```python
def test_analyze_forwards_rotation_deg_and_persists_in_state(tmp_path):
    # rotation 入 _RECOGNITION_KEYS 后: analyze 参数经 with_overrides 透传给 VisionService,
    # 并持久化进 state.recognition_params (与其余 4 识别参数同轨)。
    fake_vision = FakeVisionService()
    service = VisionDebugService(
        tmp_path,
        FakeCameraController(),
        fake_vision,
        recognition_defaults={"image_plate_rotation_deg": None},
    )
    (tmp_path / "before.jpg").write_bytes(_image_bytes())
    (tmp_path / "after.jpg").write_bytes(_image_bytes())
    state = asyncio.run(service.analyze({
        "image_plate_orientation": "rot0",
        "auto_rectify_tilt": False,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
        "image_plate_rotation_deg": -2.43,
    }))
    assert fake_vision.last_overrides["image_plate_rotation_deg"] == -2.43
    assert state["recognition_params"]["image_plate_rotation_deg"] == -2.43
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest eit_ptlc/tests/test_vision_debug.py::test_analyze_forwards_rotation_deg_and_persists_in_state -q`
Expected: FAIL — `KeyError: 'image_plate_rotation_deg'`(不在 `_RECOGNITION_KEYS`,analyze 不收、state 不存)。

- [ ] **Step 3: 最小实现**

`vision_debug_service.py:23-28` 把:

```python
_RECOGNITION_KEYS = (
    "image_plate_orientation",
    "auto_rectify_tilt",
    "rectify_min_angle_deg",
    "min_row_score",
)
```

改为:

```python
_RECOGNITION_KEYS = (
    "image_plate_orientation",
    "auto_rectify_tilt",
    "rectify_min_angle_deg",
    "min_row_score",
    "image_plate_rotation_deg",
)
```

`_initial_state`(`:58-63`)的 recognition dict 加一行(None = 每帧自动估):

```python
    recognition = {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
        "image_plate_rotation_deg": None,
    }
```

`vision_debug_routes.py:31-35` 的 `AnalyzeRequest` 加字段:

```python
class AnalyzeRequest(_StrictRequest):
    image_plate_orientation: Literal["rot0", "rot90cw", "rot180", "rot270cw"]
    auto_rectify_tilt: bool
    rectify_min_angle_deg: float = Field(ge=0, le=45)
    min_row_score: float = Field(ge=0)
    image_plate_rotation_deg: float | None = Field(default=None, ge=-180, le=180)
```

`bootstrap.py:273-278` 的 recognition_defaults 加一行:

```python
        recognition_defaults={
            "image_plate_orientation": config.vision.image_plate_orientation,
            "auto_rectify_tilt": config.vision.auto_rectify_tilt,
            "rectify_min_angle_deg": config.vision.rectify_min_angle_deg,
            "min_row_score": config.vision.min_row_score,
            "image_plate_rotation_deg": config.vision.image_plate_rotation_deg,
        },
```

- [ ] **Step 4: 跑测确认通过(含该文件全量回归)**

Run: `python -m pytest eit_ptlc/tests/test_vision_debug.py -q`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/vision_debug_service.py eit_ptlc/api/vision_debug_routes.py eit_ptlc/runtime/bootstrap.py eit_ptlc/tests/test_vision_debug.py
git commit -m "feat(vision-debug): image_plate_rotation_deg 入调试台参数集 (state/analyze/播种), null=每帧自动估"
```

---

### Task 3: 应用到生产纳入 rotation

**Files:**
- Modify: `eit_ptlc/api/vision_debug_routes.py:93-121`(apply_to_production 键元组 + docstring)
- Test: `eit_ptlc/tests/test_vision_apply_to_production_offline.py`(追加 2 测)

**Interfaces:**
- Consumes: Task 2 的 state 键 `image_plate_rotation_deg`。
- Produces: `POST /api/vision/debug/apply_to_production` 把 5 键(含 rotation,None 合法)写回 `config.vision`;生产 `_analyze_live` 基线本就读该键(`bootstrap.py:300`),写回即生效。

- [ ] **Step 1: 写失败测试** — `test_vision_apply_to_production_offline.py` 文件末追加:

```python
def test_apply_includes_rotation_deg_value(tmp_path):
    tuned = {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 1.0,
        "min_row_score": 3.5,
        "image_plate_rotation_deg": -2.0,
    }
    client, cfg_svc = _client(tmp_path, tuned)
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 200
    assert resp.json()["applied"] == tuned
    assert cfg_svc.read_section("vision")["image_plate_rotation_deg"] == -2.0


def test_apply_rotation_deg_null_roundtrip(tmp_path):
    # null = 每帧自动估计, 是合法可应用值 (VisionCfg 字段 Optional), 写回后读回仍为 None。
    tuned = {"min_row_score": 4.0, "image_plate_rotation_deg": None}
    client, cfg_svc = _client(tmp_path, tuned)
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 200
    after = cfg_svc.read_section("vision")
    assert after["min_row_score"] == 4.0
    assert after["image_plate_rotation_deg"] is None
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest eit_ptlc/tests/test_vision_apply_to_production_offline.py -q`
Expected: 新增 2 测 FAIL(`applied` 缺 rotation 键)。

- [ ] **Step 3: 最小实现** — `vision_debug_routes.py` apply_to_production 中把:

```python
        values = {
            key: recog[key]
            for key in (
                "image_plate_orientation",
                "auto_rectify_tilt",
                "rectify_min_angle_deg",
                "min_row_score",
            )
            if key in recog
        }
```

改为:

```python
        values = {
            key: recog[key]
            for key in (
                "image_plate_orientation",
                "auto_rectify_tilt",
                "rectify_min_angle_deg",
                "min_row_score",
                "image_plate_rotation_deg",
            )
            if key in recog
        }
```

并把 docstring 中"只写 4 个识别参数"改为"只写 5 个识别参数(含 image_plate_rotation_deg, None=每帧自动估)"。

- [ ] **Step 4: 跑测确认通过**

Run: `python -m pytest eit_ptlc/tests/test_vision_apply_to_production_offline.py -q`
Expected: 全绿(原 3 测 + 新 2 测)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/api/vision_debug_routes.py eit_ptlc/tests/test_vision_apply_to_production_offline.py
git commit -m "feat(vision-debug): 应用到生产写回 5 参数 (含 rotation, null 合法) — 调参面不再有只能改 yaml 的死角"
```

---

### Task 4: cases 列表 + 载入生产 case

**Files:**
- Modify: `eit_ptlc/controller/vision_debug_service.py:243-248`(upload 加 source 关键字)、`:273-279`(state[role] 用 source)
- Modify: `eit_ptlc/api/vision_debug_routes.py`(顶部 import + `LoadCaseRequest` + 2 端点)
- Test: Create `eit_ptlc/tests/test_vision_debug_load_case_offline.py`

**Interfaces:**
- Consumes: `VisionDebugService.upload(role, file_bytes, filename)`(现有归一化路径:PIL 校验 → workspace/{role}.jpg + 质量叠加)。
- Produces:
  - `VisionDebugService.upload(role, file_bytes, filename, *, source: str = "upload")` — state[role].source 可标注来源。
  - `GET /api/vision/debug/cases` → `{"cases": [{"id": str, "summary_dir": str, "mtime_iso": str}], "truncated": bool}`(mtime 倒序,截 50)。
  - `POST /api/vision/debug/load_case` body `{"summary_dir": str}` → 调试台完整 state(与 upload 端点同形)。
  Task 6 前端按这两个契约调用。

- [ ] **Step 1: 写失败测试** — 创建 `eit_ptlc/tests/test_vision_debug_load_case_offline.py`:

```python
"""调试台"载入生产 case"(cases 列表 + load_case)离线测试。

契约: GET /api/vision/debug/cases 扫 config.vision.output_dir 单根, case = 含 inputs.json
的子目录, mtime 倒序截 50 (truncated 标志); POST /api/vision/debug/load_case {summary_dir}
把该 case 的 before/after 经上传同一归一化路径拷入工作区, state[role].source = "case:<id>"。
防穿越: summary_dir 解析后必须在 output_dir 根内; inputs.json/图片缺失 → 404 明确文案。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from eit_ptlc.api.vision_debug_routes import register_vision_debug_routes
from eit_ptlc.controller.config_service import ConfigService
from eit_ptlc.controller.vision_debug_service import VisionDebugService


def _jpg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 40), (40, 220, 80)).save(buffer, "JPEG")
    return buffer.getvalue()


def _make_case(root: Path, name: str, *, with_images: bool = True) -> Path:
    case_dir = root / name
    case_dir.mkdir(parents=True)
    before = case_dir / "before_src.jpg"
    after = case_dir / "after_src.jpg"
    if with_images:
        before.write_bytes(_jpg_bytes())
        after.write_bytes(_jpg_bytes())
    (case_dir / "inputs.json").write_text(
        json.dumps({"sample_id": name, "before_path": str(before), "after_path": str(after)}),
        encoding="utf-8",
    )
    return case_dir


def _client(tmp_path: Path) -> TestClient:
    output_root = tmp_path / "vision_output"
    output_root.mkdir()
    cfg_path = tmp_path / "app.yaml"
    cfg_path.write_text(
        f"vision:\n  mock: true\n  output_dir: {json.dumps(str(output_root))}\n",
        encoding="utf-8",
    )
    app = FastAPI()
    app.state.config_svc = ConfigService(cfg_path)
    # camera/vision 服务在 upload/load_case 路径上不被触达 → None 桩即可
    app.state.vision_debug = VisionDebugService(tmp_path / "workspace", None, None)
    app.state.control_mode = "DEBUG"
    register_vision_debug_routes(app)
    return TestClient(app)


def test_list_and_load_case(tmp_path):
    client = _client(tmp_path)
    output_root = tmp_path / "vision_output"
    _make_case(output_root, "S1")
    (output_root / "not_a_case").mkdir()  # 无 inputs.json → 不列出

    r = client.get("/api/vision/debug/cases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["id"] for c in body["cases"]] == ["S1"]
    assert body["truncated"] is False

    r2 = client.post(
        "/api/vision/debug/load_case",
        json={"summary_dir": body["cases"][0]["summary_dir"]},
    )
    assert r2.status_code == 200, r2.text
    state = r2.json()
    assert state["before"]["source"] == "case:S1"
    assert state["after"]["source"] == "case:S1"
    assert (tmp_path / "workspace" / "before.jpg").is_file()
    assert (tmp_path / "workspace" / "after.jpg").is_file()


def test_load_case_404_when_images_cleaned(tmp_path):
    client = _client(tmp_path)
    case_dir = _make_case(tmp_path / "vision_output", "S2", with_images=False)
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(case_dir)})
    assert r.status_code == 404
    assert "已被清理" in r.json()["detail"]


def test_load_case_404_when_inputs_missing(tmp_path):
    client = _client(tmp_path)
    case_dir = tmp_path / "vision_output" / "S3"
    case_dir.mkdir(parents=True)
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(case_dir)})
    assert r.status_code == 404
    assert "inputs.json" in r.json()["detail"]


def test_load_case_rejects_outside_root(tmp_path):
    # 防穿越: 不在 output_dir 根内的目录一律拒 (即使真实存在且含 inputs.json)。
    client = _client(tmp_path)
    outside = _make_case(tmp_path / "elsewhere", "EVIL")
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(outside)})
    assert r.status_code == 404
    assert "不在视觉输出目录" in r.json()["detail"]
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest eit_ptlc/tests/test_vision_debug_load_case_offline.py -q`
Expected: 4 测全 FAIL(404 Not Found — 端点不存在)。

- [ ] **Step 3: 实现服务端 source 标注** — `vision_debug_service.py` upload 签名(`:243-248`)改为:

```python
    async def upload(
        self,
        role: str,
        file_bytes: bytes,
        filename: str,
        *,
        source: str = "upload",
    ) -> dict[str, Any]:
```

state 写入处(`:273-279`)把 `"source": "upload",` 改为 `"source": source,`:

```python
            state[role] = {
                "source": source,
                "url": f"/api/vision/debug/file/{role}.jpg",
                "quality_url": "",
                "filename": filename,
            }
```

- [ ] **Step 4: 实现两个端点** — `vision_debug_routes.py` 顶部 import 区加:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
```

`AnalyzeRequest` 类后加请求模型:

```python
class LoadCaseRequest(_StrictRequest):
    summary_dir: str
```

`register_vision_debug_routes` 内(`apply_to_production` 端点之后)加:

```python
    def _vision_output_root(request: Request) -> Path:
        cfg_svc = getattr(request.app.state, "config_svc", None)
        if cfg_svc is None:
            raise HTTPException(503, "配置服务未就绪")
        section = cfg_svc.read_section("vision") or {}
        return Path(section.get("output_dir", "vision_output"))

    @app.get("/api/vision/debug/cases")
    async def list_cases(request: Request):
        """列出可载入调试台复盘的生产分析 case (config.vision.output_dir 下含 inputs.json 的子目录)。"""
        root = _vision_output_root(request)
        cases = []
        if root.is_dir():
            for entry in root.iterdir():
                if not entry.is_dir() or not (entry / "inputs.json").is_file():
                    continue
                cases.append({
                    "id": entry.name,
                    "summary_dir": str(entry),
                    "mtime_iso": datetime.fromtimestamp(
                        entry.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
        cases.sort(key=lambda c: c["mtime_iso"], reverse=True)
        return {"cases": cases[:50], "truncated": len(cases) > 50}

    @app.post("/api/vision/debug/load_case")
    async def load_case(request: Request, body: LoadCaseRequest):
        """把生产 case 的 before/after 载入调试台工作区复盘调参 (走与上传同一归一化路径)。"""
        root = _vision_output_root(request)
        case_dir = Path(body.summary_dir)
        try:
            case_dir.resolve().relative_to(root.resolve())
        except ValueError:
            raise HTTPException(404, "case 不在视觉输出目录下")
        inputs_file = case_dir / "inputs.json"
        if not inputs_file.is_file():
            raise HTTPException(404, "该 case 缺少 inputs.json, 无法载入")
        try:
            inputs = json.loads(inputs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"读取 inputs.json 失败: {exc}") from exc
        service = _service(request)
        state = None
        for role, key in (("before", "before_path"), ("after", "after_path")):
            image_path = Path(str(inputs.get(key) or ""))
            if not image_path.is_file():
                raise HTTPException(404, f"该 case 的 {role} 原始图片已被清理: {image_path}")
            try:
                state = await service.upload(
                    role,
                    image_path.read_bytes(),
                    image_path.name,
                    source=f"case:{case_dir.name}",
                )
            except VisionDebugError as exc:
                _raise_debug_error(exc)
        return state
```

- [ ] **Step 5: 跑测确认通过(含相邻套件回归)**

Run: `python -m pytest eit_ptlc/tests/test_vision_debug_load_case_offline.py eit_ptlc/tests/test_vision_debug.py eit_ptlc/tests/test_vision_apply_to_production_offline.py -q`
Expected: 全绿(upload 加了带默认值的关键字参数,旧调用不受影响)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/controller/vision_debug_service.py eit_ptlc/api/vision_debug_routes.py eit_ptlc/tests/test_vision_debug_load_case_offline.py
git commit -m "feat(vision-debug): 一键载入生产 case (cases 列表 + load_case, 复用上传归一化路径, 防穿越)"
```

---

### Task 5: RecognitionParams 共用组件

**Files:**
- Create: `eit_ptlc/web/src/components/RecognitionParams.vue`

**Interfaces:**
- Consumes: 无。
- Produces: `RecognitionParams.vue` — props `{ modelValue: Object, mode: 'value'|'override', baseline: Object|null }`,事件 `update:modelValue`(整对象替换)与 `change`(参数键名)。`value` 模式绑定有类型值(rotation 空输入 → `null`);`override` 模式全部控件以 `''` 表示"用基线",占位显示 `基线 <实际值>`(rotation 基线 null 显示 `基线 自动`)。Task 6/7 按此接入。

- [ ] **Step 1: 创建组件**

```vue
<script setup>
// 识别参数控件组 (视觉调试台 & HITL 重识别门共用, 5 参数一处维护)。
// mode='value'    : 绑定有类型的当前值 (调试台 state.recognition_params); rotation 空输入 → null (每帧自动估)。
// mode='override' : 全部控件以 '' 表示"用基线"; baseline 提供占位显示的基线实际值。
// 0 是合法覆盖值 — 判空只用 '', 不用 falsy (None-sentinel 零值坑)。
const props = defineProps({
  modelValue: { type: Object, required: true },
  mode: { type: String, default: 'value' },        // 'value' | 'override'
  baseline: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'change'])

function set(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
  emit('change', key)
}
function numOrNull(raw) {
  if (raw === '' || raw === null) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}
function ph(key, fallback = '') {
  if (props.mode !== 'override') return fallback
  const v = props.baseline?.[key]
  if (v === undefined) return '基线'
  if (v === null) return '基线 自动'
  return `基线 ${v}`
}
</script>

<template>
  <div class="rp">
    <label class="rp-field">
      <span>板朝向</span>
      <select
        :value="modelValue.image_plate_orientation"
        @change="set('image_plate_orientation', $event.target.value)"
      >
        <option v-if="mode === 'override'" value="">{{ ph('image_plate_orientation') }}</option>
        <option value="rot0">rot0</option>
        <option value="rot90cw">rot90cw</option>
        <option value="rot180">rot180</option>
        <option value="rot270cw">rot270cw</option>
      </select>
    </label>
    <label v-if="mode === 'value'" class="rp-check">
      <input
        type="checkbox"
        :checked="!!modelValue.auto_rectify_tilt"
        @change="set('auto_rectify_tilt', $event.target.checked)"
      />
      <span>自动倾斜矫正</span>
    </label>
    <label v-else class="rp-field">
      <span>倾斜矫正</span>
      <select
        :value="modelValue.auto_rectify_tilt"
        @change="set('auto_rectify_tilt', $event.target.value)"
      >
        <option value="">{{ ph('auto_rectify_tilt') }}</option>
        <option value="true">开</option>
        <option value="false">关</option>
      </select>
    </label>
    <label class="rp-field">
      <span>最小矫正角 deg</span>
      <input
        type="number" min="0" step="0.1"
        :value="modelValue.rectify_min_angle_deg"
        :placeholder="ph('rectify_min_angle_deg')"
        @input="set('rectify_min_angle_deg', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
    <label class="rp-field">
      <span>min_row_score</span>
      <input
        type="number" min="0" step="0.1"
        :value="modelValue.min_row_score"
        :placeholder="ph('min_row_score')"
        @input="set('min_row_score', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
    <label class="rp-field">
      <span>相机滚转角 deg</span>
      <input
        type="number" step="0.01"
        :value="modelValue.image_plate_rotation_deg"
        :placeholder="ph('image_plate_rotation_deg', '空 = 每帧自动估')"
        @input="set('image_plate_rotation_deg', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
  </div>
</template>

<style scoped>
.rp { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 6px 0; }
.rp-field { display: grid; grid-template-columns: 110px minmax(0, 1fr); align-items: center; gap: 6px;
  font-size: 12px; color: var(--subtle); font-weight: 650; }
.rp-field input, .rp-field select { min-width: 0; min-height: 26px; padding: 3px 6px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--field-bg); color: var(--text); font-size: 13px; }
.rp-check { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--subtle); font-weight: 650; }
</style>
```

- [ ] **Step 2: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error(组件暂未被引用,仅语法/编译验证)。

- [ ] **Step 3: Commit**

```bash
git add eit_ptlc/web/src/components/RecognitionParams.vue
git commit -m "feat(vision-ui): RecognitionParams 共用参数组件 (value/override 双模式, 5 参数, 基线占位)"
```

---

### Task 6: 视觉栏接入(rotation + case 工具条 + 组件替换)

**Files:**
- Modify: `eit_ptlc/web/src/api.js:194-199`(analyze 加 rotation)+ 该区块后加 2 个函数
- Modify: `eit_ptlc/web/src/views/VisionDebugView.vue`(默认参数、fieldset 替换、case 工具条、script 函数)

**Interfaces:**
- Consumes: Task 4 的 `GET /api/vision/debug/cases` / `POST /api/vision/debug/load_case` 契约;Task 5 的 `RecognitionParams.vue`;Task 2 的 analyze 字段 `image_plate_rotation_deg`。
- Produces: 无下游依赖(Task 7 独立接入门侧)。

- [ ] **Step 1: api.js**

`analyzeVisionDebug`(`:194-199`)改为:

```js
  analyzeVisionDebug: (params) => http.post('/api/vision/debug/analyze', {
    image_plate_orientation: params?.image_plate_orientation,
    auto_rectify_tilt: params?.auto_rectify_tilt,
    rectify_min_angle_deg: params?.rectify_min_angle_deg,
    min_row_score: params?.min_row_score,
    image_plate_rotation_deg: params?.image_plate_rotation_deg ?? null,
  }).then((r) => r.data),
```

`applyVisionToProduction`(`:201-202`)之后加:

```js
  // 载入生产 case 复盘调参: 列 vision_output 下含 inputs.json 的 case / 把其 before+after 拷入调试台
  listVisionDebugCases: () => http.get('/api/vision/debug/cases').then((r) => r.data),
  loadVisionDebugCase: (summaryDir) =>
    http.post('/api/vision/debug/load_case', { summary_dir: summaryDir }).then((r) => r.data),
```

- [ ] **Step 2: VisionDebugView script**

`DEFAULT_RECOGNITION_PARAMS`(`:12-17`)与 `RECOGNITION_PARAM_KEYS`(`:20-25`)各加 rotation:

```js
const DEFAULT_RECOGNITION_PARAMS = {
  image_plate_orientation: 'rot180',
  auto_rectify_tilt: true,
  rectify_min_angle_deg: 0.5,
  min_row_score: 5.0,
  image_plate_rotation_deg: null,
}

const RECOGNITION_PARAM_KEYS = [
  'image_plate_orientation',
  'auto_rectify_tilt',
  'rectify_min_angle_deg',
  'min_row_score',
  'image_plate_rotation_deg',
]
```

import 区加:

```js
import RecognitionParams from '../components/RecognitionParams.vue'
```

`loading` reactive(`:40-46`)加 `loadCase: false,`。状态区(`applyMsg` 附近)加:

```js
const cases = ref([])
const casesTruncated = ref(false)
const selectedCase = ref('')
```

`applyToProduction` 函数后加:

```js
async function refreshCases() {
  try {
    const res = await api.listVisionDebugCases()
    cases.value = res?.cases || []
    casesTruncated.value = !!res?.truncated
  } catch (e) {
    localError.value = errText(e)
  }
}

async function loadCase() {
  if (!selectedCase.value || busy.value) return
  loading.loadCase = true
  localError.value = ''
  try {
    const next = await api.loadVisionDebugCase(selectedCase.value)
    normalizeState(next)
  } catch (e) {
    localError.value = errText(e)
  } finally {
    loading.loadCase = false
  }
}
```

`onMounted`(`:370-375`)里 `refreshAll()` 后加一行 `refreshCases()`(只拉一次,不进 2s 轮询)。

- [ ] **Step 3: VisionDebugView template**

"识别参数" fieldset(`:446-485`)内部整体替换为组件:

```html
      <fieldset class="vd-param-group">
        <legend>识别参数</legend>
        <RecognitionParams
          v-model="state.recognition_params"
          mode="value"
          @change="markRecognitionDirty"
        />
      </fieldset>
```

`vd-images` section 前加 case 工具条:

```html
    <section class="vd-cases">
      <label class="vd-field case-field">
        <span>生产 case</span>
        <select v-model="selectedCase">
          <option value="">选择要复盘的生产分析…</option>
          <option v-for="c in cases" :key="c.summary_dir" :value="c.summary_dir">
            {{ c.id }} · {{ (c.mtime_iso || '').slice(0, 19).replace('T', ' ') }}
          </option>
        </select>
      </label>
      <button class="btn" :disabled="busy || loading.loadCase || !selectedCase" @click="loadCase">
        {{ loading.loadCase ? '载入中...' : '载入' }}
      </button>
      <button class="btn ghost" @click="refreshCases">刷新列表</button>
      <span v-if="casesTruncated" class="muted">仅显示最近 50 个 case</span>
    </section>
```

scoped CSS 加:

```css
.vd-cases { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.vd-cases .case-field { margin-bottom: 0; flex: 1 1 320px; }
```

- [ ] **Step 4: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error;确认无未使用变量 warning(旧 fieldset 的控件已移除,`markRecognitionDirty` 仍被组件 `@change` 使用)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/web/src/api.js eit_ptlc/web/src/views/VisionDebugView.vue
git commit -m "feat(vision-ui): 视觉栏 5 参数组件化 + 生产 case 一键载入复盘"
```

---

### Task 7: 重识别门接入(rotation + 组件 + 基线占位)

**Files:**
- Modify: `eit_ptlc/web/src/components/HitlModal.vue`(reParams/reOverrides/watch、`.re-params` 模板与 CSS 替换、baseline 拉取)

**Interfaces:**
- Consumes: Task 5 的 `RecognitionParams.vue`(override 模式);Task 1 的 reanalyze rotation 透传;现有 `api.getConfigSection('vision')`(`api.js:149`)。
- Produces: 无下游依赖。

- [ ] **Step 1: script 改动**

`reParams` 初始化(`:30`)与 watch 复位(`:49`)都改为含 rotation 的 5 键:

```js
const reParams = ref({ min_row_score: '', image_plate_orientation: '', auto_rectify_tilt: '', rectify_min_angle_deg: '', image_plate_rotation_deg: '' })
```

(watch 内 `:49` 同样替换为上式右值。)

`reNonce`(`:35`)后加基线状态:

```js
const reBaseline = ref(null)  // 门打开时读一次 config.vision, 供 override 占位显示基线实际值
```

watch 中分两处改:复位区 `reNonce.value = 0`(`:54`)后加一行:

```js
  reBaseline.value = null
```

原有 `if (!h) return`(`:55`)**之后**、`if (h.fields)` 之前加:

```js
  if (h.kind === 'reanalyze') {
    api.getConfigSection('vision')
      .then((v) => { reBaseline.value = v })
      .catch(() => { reBaseline.value = null })
  }
```

`reOverrides()`(`:211-219`)加 rotation(判空只用 `''`,0 合法):

```js
function reOverrides() {
  const p = reParams.value
  const o = {}
  if (p.min_row_score !== '' && p.min_row_score != null) o.min_row_score = Number(p.min_row_score)
  if (p.rectify_min_angle_deg !== '' && p.rectify_min_angle_deg != null) o.rectify_min_angle_deg = Number(p.rectify_min_angle_deg)
  if (p.image_plate_rotation_deg !== '' && p.image_plate_rotation_deg != null) o.image_plate_rotation_deg = Number(p.image_plate_rotation_deg)
  if (p.image_plate_orientation) o.image_plate_orientation = p.image_plate_orientation
  if (p.auto_rectify_tilt !== '') o.auto_rectify_tilt = p.auto_rectify_tilt === 'true'
  return o
}
```

import 区加:

```js
import RecognitionParams from './RecognitionParams.vue'
```

- [ ] **Step 2: template + CSS**

`.re-params` div(`:296-315`)整体替换为:

```html
          <RecognitionParams v-model="reParams" mode="override" :baseline="reBaseline" />
```

scoped style 中删除 `.re-params` 三条规则(`:370-372`),保留 `.re-bands`。

- [ ] **Step 3: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/components/HitlModal.vue
git commit -m "feat(hitl): 重识别门参数区组件化 — 5 参数 + 基线实际值占位 (看清起点再调)"
```

---

### Task 8: 收尾验证与闭环目验

**Files:**
- 无新改动(验证任务)。

**Interfaces:**
- Consumes: Task 1-7 全部产物。
- Produces: 目验记录(留言即可,不入库)。

- [ ] **Step 1: 全量离线套件 + 构建**

Run: `python -m pytest eit_ptlc/tests -q && cd eit_ptlc/web && npm run build`
Expected: pytest 全绿(比改动前 +9:reanalyze 2 + debug 1 + apply 2 + load_case 4);build `✓`。

- [ ] **Step 2: 浏览器闭环目验(需后端运行)**

1. 视觉栏:识别参数区 5 参数齐全,滚转角空显示"空 = 每帧自动估";case 下拉列出 vision_output 的 case,「载入」后 before/after 双图 + 质量叠加刷新,`source` 显示 case 来源。
2. 调参→「分析当前双图」→「应用到生产」→ 提示写入 config.vision;检查 `eit_ptlc/config/app.yaml` vision 段 5 参数已更新且注释保留。
3. 触发 reanalyze 门(或 sim):参数区为共用组件,占位符显示"基线 <实际值>"(含刚应用的新值);全部留空按「重新识别」→ 用新基线出结果;敲 `0` 进滚转角再按 → 覆盖为 0(非当作空)。
4. 「用此结果」选带下发,VM 恢复运行,run 不被调参操作打断(run-vs-edit 不变量)。

- [ ] **Step 3: 完成声明**

真机 HITL 实弹与真实生产 case 复盘验证单列入下次上机 checklist,在完成留言中注明。
