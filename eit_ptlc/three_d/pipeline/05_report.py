"""
功能: 资产性能预算门禁. 检查最终 GLB 是否满足前端可流畅加载与渲染的硬性指标.

为什么要有硬门禁: 三维页面的体验退化是渐进的 —— 每次多留一点几何细节都"看起来还行",
积累到某个点就会突然卡顿. 把预算固化成会失败的检查, 才能保证每次重跑管线都守住底线.

检查项:
    文件体积      <= budget.max_glb_mb        影响首屏加载时间
    绘制调用(图元) <= budget.max_draw_calls    影响帧率, 通常是最先突破的一项
    三角形数      <= budget.max_triangles     影响 GPU 光栅化与内存
    命名质量      提示性检查                   无语义名会让后续绑定层无法工作

用法:
    python 05_report.py                          # 检查 models/machine.glb
    python 05_report.py --input work/x.glb
    python 05_report.py --no-fail                # 只报告不失败(用于中间产物体检)

参数: 见 main() 中的 argparse 定义
返回值: 无; 未通过门禁时以退出码 1 结束
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter

import pygltflib

from common import human_size, load_config, log, write_report

NAUO_PATTERN = re.compile(r"^NAUO\d+$", re.IGNORECASE)
VENDOR_AUTO = re.compile(r"Open[_ ]CASCADE[_ ]STEP[_ ]translator", re.IGNORECASE)


def analyze(path: str) -> dict:
    """
    功能: 统计 GLB 的规模与命名质量指标.
    参数:
        path: GLB 路径
    返回值: dict, 指标字典
    """
    gltf = pygltflib.GLTF2().load(path)
    nodes = gltf.nodes or []
    meshes = gltf.meshes or []

    primitives = 0
    triangles = 0
    for mesh in meshes:
        for primitive in mesh.primitives:
            primitives += 1
            if primitive.indices is not None:
                triangles += gltf.accessors[primitive.indices].count // 3
            elif primitive.attributes.POSITION is not None:
                triangles += gltf.accessors[primitive.attributes.POSITION].count // 3

    def classify(name: str) -> str:
        """功能: 节点名归类. 参数: name 节点名. 返回值: str 类别"""
        if not name:
            return "empty"
        if NAUO_PATTERN.match(name):
            return "nauo"
        if VENDOR_AUTO.search(name):
            return "vendor_auto"
        return "semantic"

    naming = Counter(classify(node.name or "") for node in nodes)
    semantic_ratio = naming["semantic"] / max(len(nodes), 1)

    return {
        "path": path,
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "size_human": human_size(os.path.getsize(path)),
        "nodes": len(nodes),
        "meshes": len(meshes),
        "primitives": primitives,
        "triangles": triangles,
        "materials": len(gltf.materials or []),
        "textures": len(gltf.textures or []),
        "naming": dict(naming),
        "semantic_ratio": round(semantic_ratio, 4),
        "extensions_used": list(gltf.extensionsUsed or []),
    }


def evaluate(metrics: dict, budget: dict) -> list[dict]:
    """
    功能: 逐项比对指标与预算.
    参数:
        metrics: analyze() 的产出
        budget: pipeline.yaml 的 budget 段
    返回值: list[dict], 每项含 name/value/limit/passed/severity
    """
    checks = [
        {
            "name": "文件体积 (MB)",
            "value": metrics["size_mb"],
            "limit": budget.get("max_glb_mb", 25),
            "severity": "error",
        },
        {
            "name": "绘制调用 (图元数)",
            "value": metrics["primitives"],
            "limit": budget.get("max_draw_calls", 500),
            "severity": "error",
        },
        {
            "name": "三角形数",
            "value": metrics["triangles"],
            "limit": budget.get("max_triangles", 3_000_000),
            "severity": "error",
        },
    ]
    for check in checks:
        check["passed"] = check["value"] <= check["limit"]

    # 命名质量是提示项而非硬门禁: minimal 阶段按材质合并后节点名本来就会退化,
    # 但 full 阶段若语义名占比过低, 说明 STEP 名称传播出了问题, 必须警告.
    checks.append(
        {
            "name": "语义命名占比",
            "value": metrics["semantic_ratio"],
            "limit": 0.5,
            "passed": metrics["semantic_ratio"] >= 0.5,
            "severity": "warning",
            "note": "低于阈值说明零件名未能传播, device-manifest 将无法绑定节点",
        }
    )
    return checks


def missing_rig_nodes(glb_path: str, manifest_path: str) -> tuple[list[str], int] | None:
    """
    功能: 反查 manifest 声明的执行器节点(actuators/linkages 的叶名)是否都在 GLB 里.

    为什么是硬门禁: ACTUATOR_* 是无网格空节点, 04 的 prune/join 一旦把它剪掉,
    前端按 id 能查到机构却找不到几何 —— 症状是"夹爪/吸盘永远不动"且全程零报错.

    参数:
        glb_path: 被检查的 GLB
        manifest_path: device-manifest.json 路径
    返回值: (缺失叶名列表, 应有总数); manifest 不存在或未声明执行器时返回 None
    """
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    expected: set[str] = set()
    for item in manifest.get("actuators") or []:
        if item.get("node"):
            expected.add(str(item["node"]).split("/")[-1])
    for item in manifest.get("linkages") or []:
        for member in item.get("members") or []:
            if member.get("node"):
                expected.add(str(member["node"]).split("/")[-1])
    if not expected:
        return None
    gltf = pygltflib.GLTF2().load(glb_path)
    names = {node.name or "" for node in (gltf.nodes or [])}
    return sorted(expected - names), len(expected)


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    budget = config.get("budget", {})

    parser = argparse.ArgumentParser(description="GLB 性能预算门禁")
    parser.add_argument(
        "--input", default=os.path.join(config["paths"]["models"], "machine.glb")
    )
    parser.add_argument("--no-fail", action="store_true", help="不通过时也返回 0")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(f"错误: 文件不存在: {args.input}")

    metrics = analyze(args.input)
    checks = evaluate(metrics, budget)

    rig_probe = missing_rig_nodes(
        args.input, os.path.join(config["paths"]["models"], "device-manifest.json")
    )
    if rig_probe is not None:
        missing, expected_total = rig_probe
        checks.append(
            {
                "name": "执行器节点存活",
                "value": len(missing),
                "limit": 0,
                "passed": not missing,
                "severity": "error",
                "note": (
                    f"manifest 声明 {expected_total} 个执行器节点, 缺失: {missing}"
                    if missing
                    else f"manifest 声明的 {expected_total} 个执行器节点全部存活"
                ),
            }
        )
        if missing:
            log(f"执行器节点被优化链剪掉: {missing}(前端对应机构将静默不动)")

    log(f"资产: {metrics['path']} ({metrics['size_human']})")
    log(
        f"节点 {metrics['nodes']} / 网格 {metrics['meshes']} / 图元 {metrics['primitives']} / "
        f"三角形 {metrics['triangles']:,} / 材质 {metrics['materials']}"
    )
    if metrics["extensions_used"]:
        log(f"扩展: {', '.join(metrics['extensions_used'])}")

    print()
    print(f"{'检查项':<20}{'实测':>14}{'预算':>14}   结果")
    print("-" * 62)
    failures = []
    warnings = []
    for check in checks:
        mark = "通过" if check["passed"] else ("警告" if check["severity"] == "warning" else "不通过")
        value = check["value"]
        limit = check["limit"]
        value_text = f"{value:,.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
        limit_text = f"{limit:,.4f}".rstrip("0").rstrip(".") if isinstance(limit, float) else f"{limit:,}"
        print(f"{check['name']:<20}{value_text:>14}{limit_text:>14}   {mark}")
        if not check["passed"]:
            (warnings if check["severity"] == "warning" else failures).append(check)
    print("-" * 62)

    for check in warnings:
        log(f"警告: {check['name']} {check.get('note', '')}")

    report = {"metrics": metrics, "budget": budget, "checks": checks, "passed": not failures}
    write_report(
        os.path.join(config["paths"]["work"], "05_report.json"), report
    )

    if failures:
        names = ", ".join(c["name"] for c in failures)
        log(f"预算门禁未通过: {names}")
        log("建议: 加大 prune_list 删减范围 / 调高 04_optimize 的 --simplify 比例 / 提高 02 的 tol_linear")
        if not args.no_fail:
            raise SystemExit(1)
    else:
        log("预算门禁全部通过")


if __name__ == "__main__":
    main()
