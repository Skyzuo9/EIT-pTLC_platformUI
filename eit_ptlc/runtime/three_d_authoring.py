"""三维工程 authoring 服务.

功能:
    为上位机生产后端提供受管文件读写, 动画片段管理, 模型资产定位与固定管线重建.
    浏览器只能选择白名单目标和预定义步骤, 不能提交任意磁盘路径或命令.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional


log = logging.getLogger(__name__)

PYTHON_EXECUTABLE = Path("C:/ProgramData/miniforge3/python.exe")
CLIP_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
#: 流程名与入参名的白名单 —— 它们要拼进子进程 argv, 在这里收口。
#: create_subprocess_exec 不过 shell 所以没有注入面, 但一个拼错的名字会一路走到
#: flow_discovery 才 SystemExit, 报错信息夹在几百行编译日志里没人看得见。
OPERATION_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: --inputs 的 JSON 长度上限。Windows 命令行约 32K, 留足余量; 正常一条也就几十字节。
FLOW_INPUTS_MAX_CHARS = 2048


def _flow_argv(python: str, flow: Optional[dict]) -> tuple[str, ...]:
    """flows 步的 argv —— 全量编译 vs 定向编一条.

    参数:
        python: 解释器路径; flow: None=全量; 否则 {"operation": 名, "inputs": {入参: 值}}
    返回:
        argv 元组
    Raises:
        ValueError: 流程名/入参名不合白名单, 或 inputs 过长。**在这里拦而不是让它一路走到
            flow_discovery**: 那边的 SystemExit 会夹在几百行编译日志里, 前端只看得到
            "flows 步失败"。
    """
    if not flow:
        return (python, "sync_ptlc_robot.py", "--plates", "--flows", "--output", "..")

    operation = str(flow.get("operation") or "")
    if not OPERATION_NAME_RE.match(operation):
        raise ValueError(f"流程名不合法: {operation!r}")
    inputs = flow.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("定向编译必须给非空的 inputs")
    for key, value in inputs.items():
        if not IDENTIFIER_RE.match(str(key)):
            raise ValueError(f"入参名不合法: {key!r}")
        if not isinstance(value, (int, float, str, bool)):
            raise ValueError(f"入参 {key} 的取值类型不受支持: {type(value).__name__}")
    payload = json.dumps({operation: inputs}, ensure_ascii=False)
    if len(payload) > FLOW_INPUTS_MAX_CHARS:
        raise ValueError(f"inputs 过长({len(payload)} > {FLOW_INPUTS_MAX_CHARS} 字符)")
    # 片段名形如 flow.<operation>[.<变体>], 用 glob 把该流程的全部变体都纳入 —— 只写
    # flow.<op> 会漏掉带后缀的那条(而带后缀的正是本次要编的那条)。
    return (python, "sync_ptlc_robot.py", "--flows",
            "--only", f"flow.{operation}*", "--inputs", payload, "--output", "..")


class ThreeDWorkspaceUnavailable(RuntimeError):
    """三维工程目录不可用."""


class ThreeDRebuildBusy(RuntimeError):
    """三维重建任务已在运行."""


@dataclass(frozen=True)
class RebuildStep:
    """
    功能:
        描述一条固定重建步骤.

    参数:
        step_id: 稳定步骤标识.
        label: 中文显示名.
        argv: 子进程参数列表, None 表示执行内部部署函数.
        cwd: 子进程工作目录.
        optional: 是否只在被点名时才跑(不进"全链"默认集).

    返回:
        不返回, 仅承载不可变配置.
    """

    step_id: str
    label: str
    argv: Optional[tuple[str, ...]]
    cwd: Optional[Path]
    optional: bool = False


Runner = Callable[[tuple[str, ...], Path], Awaitable[dict]]


class ThreeDAuthoringService:
    """
    功能:
        管理三维工程白名单文件和单任务模型重建流程.

    参数:
        workspace_root: 上位机仓库内的三维模块根目录.
        hardware_root: 仓库外的 TLC 自动化设备原始文件目录.
        runner: 可选命令执行器, 测试可注入无副作用实现.

    返回:
        ThreeDAuthoringService 服务实例.
    """

    def __init__(
        self,
        workspace_root: Path,
        hardware_root: Optional[Path] = None,
        runner: Optional[Runner] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.hardware_root = Path(hardware_root).resolve() if hardware_root is not None else None
        self.pipeline_dir = self.workspace_root / "pipeline"
        self.work_dir = self.workspace_root / "work"
        self.models_dir = self.workspace_root / "models"
        self.clips_dir = self.workspace_root / "clips"
        self.generated_dir = self.workspace_root / "generated"
        self.control_root = Path(__file__).resolve().parent.parent
        self._runner = runner or self._run_command
        self._task: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._start_lock = asyncio.Lock()
        self._state = {
            "running": False,
            "startedAt": 0,
            "steps": [],
            "error": "",
        }

    def workspace_status(self) -> dict:
        """
        功能:
            检查模型资产和重建管线是否具备运行条件.

        参数:
            无.

        返回:
            包含 available, workspace_root 与 reason 的状态字典.
        """
        missing = []
        for required in (self.workspace_root, self.models_dir, self.pipeline_dir):
            if required.exists() is False:
                missing.append(str(required))
        rebuild_missing = list(missing)
        if PYTHON_EXECUTABLE.is_file() is False:
            rebuild_missing.append(str(PYTHON_EXECUTABLE))
        return {
            "available": len(missing) == 0,
            "rebuild_available": len(rebuild_missing) == 0,
            "workspace_root": str(self.workspace_root),
            "hardware_root": str(self.hardware_root) if self.hardware_root is not None else "",
            "hardware_available": (
                self.hardware_root.is_dir() if self.hardware_root is not None else False
            ),
            "reason": "" if len(missing) == 0 else "缺少三维工程依赖: " + ", ".join(missing),
            "rebuild_reason": (
                "" if len(rebuild_missing) == 0
                else "缺少三维重建依赖: " + ", ".join(rebuild_missing)
            ),
        }

    def status(self) -> dict:
        """
        功能:
            返回当前重建状态的独立快照.

        参数:
            无.

        返回:
            包含 running, steps 与 error 的字典.
        """
        return copy.deepcopy(self._state)

    def resolve_asset(self, asset_path: str) -> Path:
        """
        功能:
            将 URL 资产路径限定到三维模块的公开资源目录.

        参数:
            asset_path: 相对三维模块根目录的资源路径.

        返回:
            已解析且存在的文件路径.
        """
        self._require_assets()
        normalized = Path(str(asset_path).replace("\\", "/"))
        if len(normalized.parts) == 0:
            raise ValueError("三维资产路径不能为空")
        target = (self.workspace_root / normalized).resolve()
        if target.is_relative_to(self.workspace_root) is False:
            raise ValueError("三维资产路径越界")
        allowed_roots = {"models", "clips", "generated"}
        if normalized.as_posix() != "props.yaml" and normalized.parts[0] not in allowed_roots:
            raise ValueError(f"未知的三维资产目录: {normalized.parts[0]}")
        if target.is_file() is False:
            raise FileNotFoundError(f"三维资产不存在: {asset_path}")
        return target

    def read_file(self, key: Optional[str] = None, clip: Optional[str] = None) -> dict:
        """
        功能:
            读取一个白名单工程文件或动画片段.

        参数:
            key: 受管文件键.
            clip: 动画片段名, 不含扩展名.

        返回:
            包含相对路径和 UTF-8 文本内容的字典.
        """
        target = self._resolve_managed_target(key=key, clip=clip, writable=False)
        if target.is_file() is False:
            raise FileNotFoundError(f"文件不存在: {target.name}")
        return {
            "ok": True,
            "path": target.relative_to(self.workspace_root).as_posix(),
            "content": target.read_text(encoding="utf-8"),
        }

    def write_file(self, content: str, key: Optional[str] = None, clip: Optional[str] = None) -> dict:
        """
        功能:
            写入一个白名单工程文件或动画片段, 写前保留 .bak.

        参数:
            content: 完整 UTF-8 文本.
            key: 受管文件键.
            clip: 动画片段名, 不含扩展名.

        返回:
            包含写入路径的结果字典.
        """
        if isinstance(content, str) is False:
            raise ValueError("请求体缺少 content 字符串")
        target = self._resolve_managed_target(key=key, clip=clip, writable=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = target.with_name(target.name + ".bak")
        if target.is_file() is True:
            shutil.copy2(target, backup)
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        log.info("[3D] 已写入受管文件: %s", target)
        return {
            "ok": True,
            "path": target.relative_to(self.workspace_root).as_posix(),
            "backup": backup.relative_to(self.workspace_root).as_posix() if backup.is_file() else "",
        }

    def list_clips(self) -> list[str]:
        """
        功能:
            列出三维模块 clips 目录中的动画片段.

        参数:
            无.

        返回:
            按名称排序且不含扩展名的片段列表.
        """
        self._require_assets()
        if self.clips_dir.is_dir() is False:
            return []
        return sorted(path.stem for path in self.clips_dir.glob("*.yaml") if path.is_file() is True)

    async def start_rebuild(self, only: Optional[list[str]] = None,
                            flow: Optional[dict] = None) -> dict:
        """
        功能:
            启动一次固定步骤的后台重建任务.

        参数:
            only: 只运行指定步骤, 空列表表示全链.
            flow: 定向编译一条流程 {"operation": 名, "inputs": {入参: 值}}。
                演示页"按这组入参编这一条"走它, 约 20 秒。

        返回:
            已受理的重建状态快照.
        """
        self._require_rebuild()
        requested = list(only or [])
        if flow and requested != ["flows"]:
            # flow 只有 flows 步认得。允许它和别的步混跑 = 允许一个静默无效的请求:
            # 用户等完一整轮重建, 而那条流程根本没按新入参编过。
            raise ValueError('定向编译流程时 only 必须恰好是 ["flows"]')
        steps = self._rebuild_steps(flow)
        known = {step.step_id for step in steps}
        unknown = [step_id for step_id in requested if step_id not in known]
        if len(unknown) > 0:
            raise ValueError("未知的重建步骤: " + ", ".join(unknown))

        async with self._start_lock:
            if self._task is not None and self._task.done() is False:
                raise ThreeDRebuildBusy("已有三维重建任务在执行")
            # 空 only = 全链, 但不含 optional 步骤: 那些是按需的重活(如逐条编译上百个
            # 流程动画), 混进"改完 rig_map 顺手全链重跑"里只会把一分钟拖成好几分钟.
            selected = [
                step for step in steps
                if (step.step_id in requested) or (len(requested) == 0 and step.optional is False)
            ]
            self._state = {
                "running": True,
                "startedAt": int(time.time() * 1000),
                "steps": [
                    {
                        "id": step.step_id,
                        "label": step.label,
                        "status": "pending",
                        "elapsed_s": 0,
                        "tail": "",
                    }
                    for step in selected
                ],
                "error": "",
            }
            self._task = asyncio.create_task(self._run_rebuild(selected), name="three-d-rebuild")
        return self.status()

    async def close(self) -> None:
        """
        功能:
            关闭服务并终止仍在执行的重建子进程.

        参数:
            无.

        返回:
            无.
        """
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
        task = self._task
        if task is not None and task.done() is False:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._state["running"] = False

    def _require_workspace(self) -> None:
        status = self.workspace_status()
        if status["available"] is False:
            raise ThreeDWorkspaceUnavailable(status["reason"])

    def _require_assets(self) -> None:
        if self.models_dir.is_dir() is False:
            raise ThreeDWorkspaceUnavailable(f"三维资产目录不可用: {self.models_dir}")

    def _require_rebuild(self) -> None:
        status = self.workspace_status()
        if status["rebuild_available"] is False:
            raise ThreeDWorkspaceUnavailable(status["rebuild_reason"])

    def _writable_files(self) -> dict[str, Path]:
        return {
            "prune_list": self.pipeline_dir / "prune_list.yaml",
            "rig_map": self.pipeline_dir / "rig_map.yaml",
            "materials": self.pipeline_dir / "materials.yaml",
            "material_semantics": self.pipeline_dir / "material_semantics.yaml",
            "props": self.workspace_root / "props.yaml",
            "review": self.workspace_root / "docs" / "animation-review.md",
            # 实时页「显示 → 模块视角设定」写 stations[].camera. 该字段在
            # gen_twin_manifest.PRESERVE_FIELDS 里被列为"人工微调字段, 重跑不覆盖"
            # (merge_preserving 认 camera 内的 manual: true 标记); 前端做的是定点文本
            # 替换, 不整体重排。两份 manifest 各自成键 —— 前端必须写"页面正在用的那份":
            # /3d/live 与演示页用 official-cr5 变体, 装配台默认页用基础版。
            "device_manifest": self.models_dir / "device-manifest.json",
            "device_manifest_cr5": self.models_dir / "device-manifest.official-cr5.json",
        }

    def _readable_files(self) -> dict[str, Path]:
        return {
            **self._writable_files(),
            "names_csv": self.work_dir / "TLC_she_bei_zong_zhuang_names.csv",
            "structure": self.work_dir / "structure.json",
            "hierarchy": self.work_dir / "hierarchy_top.json",
            "report": self.work_dir / "05_report.json",
            "clean_report": self.work_dir / "03_clean_model.report.json",
            # 装配台标红基线: 由 03 的 raw 阶段裁决产出, 与真实删减同一份实现
            "prune_preview": self.work_dir / "prune_preview.json",
        }

    def _resolve_managed_target(
        self,
        *,
        key: Optional[str],
        clip: Optional[str],
        writable: bool,
    ) -> Path:
        self._require_workspace()
        if clip is not None:
            clip_name = str(clip).strip()
            if CLIP_NAME_RE.fullmatch(clip_name) is None:
                raise ValueError("动画片段名不合法")
            if Path(clip_name).name != clip_name:
                raise ValueError("动画片段路径越界")
            return self.clips_dir / f"{clip_name}.yaml"
        mapping = self._writable_files() if writable is True else self._readable_files()
        if key not in mapping:
            action = "写入" if writable is True else "读取"
            raise ValueError(f"未知的{action}目标: {key}")
        return mapping[str(key)]

    def _rebuild_steps(self, flow: Optional[dict] = None) -> list[RebuildStep]:
        """固定的重建步骤表.

        参数:
            flow: 定向编译一条流程时的 {"operation": 名, "inputs": {入参: 值}}。
                非空时 flows 步换成"只编这一条 + 这组入参"的 argv(见下面那条注释),
                约 20 秒而不是 10~20 分钟。
        """
        python = str(PYTHON_EXECUTABLE)
        return [
            RebuildStep("materials", "生成材质映射", (python, "build_materials.py"), self.pipeline_dir),
            RebuildStep(
                "clean",
                "Blender 清理与装配",
                (python, "03_clean_model.py", "--stage", "full", "--output", "../work/machine.full.glb"),
                self.pipeline_dir,
            ),
            # 必须紧跟 clean、排在其余一切读 machine.full.glb 的步骤之前:
            # 它就地改写 machine.full.glb(把过粗的圆柱件换成单独重导的高镶嵌网格),
            # 放在后面会让 manifest / 几何验收看到的是被换掉的那份旧几何。
            # 整机 glTF 是按**装配体文档**的图像品质镶嵌的, 圆柱面普遍只有 30~40 段,
            # 近景下每个刻面约 32 屏幕像素, 读起来就是"圆柱上一圈没来由的竖向明暗带"。
            # 详见 pipeline/hires_overrides.json 的说明与 06_hires_swap.mjs 头注释。
            RebuildStep(
                "hires-swap",
                "高精零件替换",
                ("node", "06_hires_swap.mjs"),
                self.pipeline_dir,
            ),
            RebuildStep(
                "verify-geometry",
                "机器人几何验收",
                (python, "verify_robot_geometry.py", "../work/machine.full.glb"),
                self.pipeline_dir,
            ),
            # 必须排在两条 manifest 之前: 它产出的 work/plate_clearance.json 是
            # magazines[].floorOffsetM 的来源(前端拿它夹住板底, 不让板扎穿仓底)。
            RebuildStep(
                "plate-clearance",
                "料仓板净空验收",
                (python, "verify_plate_clearance.py"),
                self.pipeline_dir,
            ),
            # 上样孔板验收: 只读 03 的报告做算术(不起 Blender, 秒级)。排在 manifest 之前是为了
            # "几何不自洽就别往下游发契约"; 它对控制侧 calibration.yaml 的核对只告警不判红。
            RebuildStep(
                "sample-plates",
                "上样孔板验收",
                (python, "verify_sample_plates.py"),
                self.pipeline_dir,
            ),
            # 载荷几何参考帧 + 单件在手锚点: 都必须排在 manifest 之前 ——
            # gen_twin_manifest 把 grips 烘进 attachments[].payload.mountLocal;
            # payload-poses 是 flows 步 _align_to_cad 的输入(缺了它站座落位不做 CAD 校正,
            # 收集工位的实例交换会肉眼跳变)。此前这两个脚本不在链里, 全靠有人记得手跑,
            # 陈旧了没有任何指标会报。
            RebuildStep(
                "payload-poses",
                "导出载荷几何参考帧",
                (python, "export_payload_poses.py"),
                self.pipeline_dir,
            ),
            # 只读上一轮 manifest 的**结构段**(linkages/tools/attachments 清单)解四销笼,
            # 结构跨轮稳定; 全新环境第一次跑请先单独执行一次 gen_twin_manifest。
            RebuildStep(
                "item-grips",
                "解算单件在手锚点",
                (python, "fit_item_grips.py"),
                self.pipeline_dir,
            ),
            RebuildStep("manifest", "生成绑定契约", (python, "gen_twin_manifest.py"), self.pipeline_dir),
            RebuildStep(
                "manifest-cr5",
                "生成绑定契约(official-cr5)",
                (python, "gen_twin_manifest.py", "--output", "../models/device-manifest.official-cr5.json"),
                self.pipeline_dir,
            ),
            RebuildStep(
                "optimize",
                "压缩优化",
                ("node", "04_optimize.mjs", "--input", "../work/machine.full.glb", "--output", "../models/machine.glb"),
                self.pipeline_dir,
            ),
            RebuildStep(
                "optimize-cr5",
                "压缩优化(official-cr5)",
                (
                    "node",
                    "04_optimize.mjs",
                    "--input",
                    "../work/machine.full.glb",
                    "--output",
                    "../models/machine.official-cr5.glb",
                    "--no-join",
                ),
                self.pipeline_dir,
            ),
            RebuildStep("report", "性能预算门禁", (python, "05_report.py", "--no-fail"), self.pipeline_dir),
            RebuildStep(
                "flows",
                "编译流程动画(单条)" if flow else "编译流程动画",
                # --output 必须显式给: 缺省值曾指向已废弃的 app/public, 生成一路绿灯
                # 而页面读到的还是旧片段(见 sync_ptlc_robot.DEFAULT_OUTPUT 的警告)。
                #
                # --plates 必须与 --flows 一起跑: 演示栏 83 条里有 12 条(sampling_load、
                # develop_load…)是 flow_discovery.covered_clips() 里的"硬编码路线", 由
                # --plates 生成而不是 --flows。只跑 --flows 的话, 改了 rig_map 的轴标定或
                # 点表的工位轴值, 那 12 条的 home.axis_mm 仍是旧的 —— 页面照播、不报任何错。
                # 2026-08-05 实测踩到: 点样座 7Y 改成实读 56.0 后, 十一条流程都跟着变了,
                # 唯独 sampling_load 还停在 -40.85, 因为它属于这一批。
                #
                # ⚠ 但定向编一条 flow 时 --plates 纯属浪费: 那 12 条硬编码路线与被点名的
                #   那条流程毫无关系, 白编 43 个 plate.* 片段。去掉之后单次开销 ≈
                #   python 启动 + 点表标定 + 14.9MB GLB 加载 + 1 条编译 ≈ 20 秒,
                #   而带 --plates 是 10~20 分钟 —— 那个差别决定了"改个参数看一眼"这件事
                #   到底做不做得成。
                _flow_argv(python, flow),
                self.pipeline_dir,
                optional=True,
            ),
            RebuildStep(
                "raw-swap",
                "工作台原始模型换官方臂",
                (python, "03_clean_model.py", "--stage", "raw", "--output", "../work/machine.raw.glb"),
                self.pipeline_dir,
            ),
            # raw 链同样要吃高精替换: 装配台看的就是 raw, 少这步的话 hires_overrides 里
            # "装配导出缺实体"类条目(如 镜头-1 的滚花壳)只在孪生页修好、装配台照旧残缺。
            RebuildStep(
                "hires-swap-raw",
                "高精零件替换(工作台原始模型)",
                ("node", "06_hires_swap.mjs", "--input", "../work/machine.raw.glb", "--output", "../work/machine.raw.glb"),
                self.pipeline_dir,
            ),
            RebuildStep(
                "raw",
                "刷新工作台原始模型",
                (
                    "node",
                    "04_optimize.mjs",
                    "--input",
                    "../work/machine.raw.glb",
                    "--output",
                    "../models/raw.glb",
                    "--passthrough",
                ),
                self.pipeline_dir,
            ),
            RebuildStep("deploy", "部署到应用", None, None),
        ]

    async def _run_rebuild(self, steps: list[RebuildStep]) -> None:
        try:
            for index, step in enumerate(steps):
                entry = self._state["steps"][index]
                entry["status"] = "running"
                started = time.monotonic()
                log.info("[3D] 开始重建步骤: %s", step.label)
                if step.argv is None:
                    result = await asyncio.to_thread(self._deploy_assets)
                else:
                    result = await self._runner(step.argv, step.cwd)
                entry["elapsed_s"] = round(time.monotonic() - started, 1)
                output = (str(result.get("stdout", "")) + str(result.get("stderr", ""))).strip()
                lines = output.splitlines()
                keep = 12 if result.get("ok") is True else 40
                entry["tail"] = "\n".join(lines[-keep:])
                if result.get("ok") is True:
                    entry["status"] = "done"
                    log.info("[3D] 重建步骤完成: %s", step.label)
                else:
                    entry["status"] = "failed"
                    self._state["error"] = f"步骤「{step.label}」失败"
                    log.error("[3D] %s: %s", self._state["error"], entry["tail"])
                    break
        except asyncio.CancelledError:
            self._state["error"] = "三维重建已随服务关闭而终止"
            raise
        except Exception as exc:
            self._state["error"] = f"三维重建异常: {exc}"
            log.exception("[3D] 三维重建异常")
        finally:
            self._state["running"] = False
            self._process = None

    async def _run_command(self, argv: tuple[str, ...], cwd: Path) -> dict:
        if cwd.is_dir() is False:
            return {"ok": False, "code": -1, "stdout": "", "stderr": f"工作目录不存在: {cwd}"}
        environment = dict(os.environ)
        environment["PTLC_CONTROL_ROOT"] = str(self.control_root)
        environment["PTLC_THREE_D_ROOT"] = str(self.workspace_root)
        if self.hardware_root is not None:
            environment["PTLC_HARDWARE_ROOT"] = str(self.hardware_root)
        environment["PYTHONIOENCODING"] = "utf-8"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        stdout_raw, stderr_raw = await self._process.communicate()
        code = int(self._process.returncode or 0)
        return {
            "ok": code == 0,
            "code": code,
            "stdout": stdout_raw.decode("utf-8", errors="replace"),
            "stderr": stderr_raw.decode("utf-8", errors="replace"),
        }

    def _deploy_assets(self) -> dict:
        required = (
            self.models_dir / "machine.glb",
            self.models_dir / "device-manifest.json",
            self.models_dir / "machine.official-cr5.glb",
            self.models_dir / "device-manifest.official-cr5.json",
            self.models_dir / "merge-members.json",
            self.models_dir / "raw.glb",
        )
        missing = [path.name for path in required if path.is_file() is False]
        if len(missing) > 0:
            return {"ok": False, "stdout": "", "stderr": "缺少应用资产: " + ", ".join(missing)}
        return {
            "ok": True,
            "stdout": "三维应用资产已就位: " + ", ".join(path.name for path in required),
            "stderr": "",
        }
