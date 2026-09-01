"""
功能: 把(已完成名称修复的)STEP 文件网格化并转换为 GLB, 作为三维前端可加载的原始资产.

引擎:
    cascadio —— 主引擎. trimesh 作者维护的 OCCT 7.x wheel, 纯 pip 安装、无需图形界面,
                能保留装配层级与产品名, 支持 AP214 颜色(include_materials).
    freecad  —— 兜底引擎. 当 cascadio 在超大文件上崩溃/丢层级时改用,
                通过 FreeCADCmd 无界面执行 Import.insert + glTF 导出.

用法:
    python 02_convert_step.py                                  # 用 work/ 下 01 的产物
    python 02_convert_step.py --input X.STEP --output Y.glb
    python 02_convert_step.py --engine freecad
    python 02_convert_step.py --tol-linear 1.0                 # 更粗的网格, 更小的文件

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 GLB + 报告 JSON)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

from common import ensure_dir, human_size, load_config, log, timed, write_report


def convert_with_cascadio(
    input_path: str,
    output_path: str,
    tol_linear: float,
    tol_angular: float,
    tol_relative: bool,
    merge_primitives: bool,
    use_parallel: bool,
    include_materials: bool,
) -> dict:
    """
    功能: 使用 cascadio(OCCT)把 STEP 转换为 GLB.
    参数:
        input_path: 源 STEP 路径
        output_path: 目标 GLB 路径
        tol_linear: 线性网格化公差(与 STEP 单位一致, 本项目为 mm)
        tol_angular: 角度网格化公差(弧度)
        tol_relative: tol_linear 是否为相对值
        merge_primitives: 每个零件是否合并为一个网格图元
        use_parallel: 是否并行网格化
        include_materials: 是否带出材质/颜色(需源文件为 AP214)
    返回值: dict, 转换结果统计
    """
    import cascadio

    ensure_dir(output_path)
    log(
        f"cascadio 参数: tol_linear={tol_linear} tol_angular={tol_angular} "
        f"relative={tol_relative} materials={include_materials}"
    )
    cascadio.step_to_glb(
        input_path,
        output_path,
        tol_linear=tol_linear,
        tol_angular=tol_angular,
        tol_relative=tol_relative,
        merge_primitives=merge_primitives,
        use_parallel=use_parallel,
        include_materials=include_materials,
    )
    return {"engine": "cascadio"}


def _find_freecad() -> str:
    """
    功能: 定位 FreeCADCmd 可执行文件.
    参数: 无
    返回值: str, 可执行文件绝对路径
    异常: FileNotFoundError, 未安装时抛出
    """
    candidates = [
        os.environ.get("FREECAD_CMD", ""),
        *glob.glob(r"C:\Program Files\FreeCAD*\bin\FreeCADCmd.exe"),
        *glob.glob(r"C:\Program Files (x86)\FreeCAD*\bin\FreeCADCmd.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        "未找到 FreeCADCmd.exe; 请安装 FreeCAD 1.0 或设置环境变量 FREECAD_CMD"
    )


def convert_with_freecad(input_path: str, output_path: str) -> dict:
    """
    功能: 使用 FreeCAD 无界面模式把 STEP 转换为 glTF/GLB(兜底路径).
    参数:
        input_path: 源 STEP 路径
        output_path: 目标 GLB 路径
    返回值: dict, 转换结果统计
    异常: RuntimeError, FreeCAD 返回非零退出码时抛出
    """
    freecad = _find_freecad()
    ensure_dir(output_path)

    # FreeCAD 内部脚本: 导入 STEP -> 全选 -> 导出 glTF
    script = (
        "import FreeCAD, Import, ImportGui, Mesh\n"
        f"doc = FreeCAD.newDocument('conv')\n"
        f"ImportGui.insert(r'{input_path}', doc.Name)\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        "import ImportGui\n"
        f"ImportGui.export(objs, r'{output_path}')\n"
        "FreeCAD.closeDocument(doc.Name)\n"
    )
    script_path = os.path.join(os.path.dirname(output_path), "_freecad_convert.py")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(script)

    log(f"调用 FreeCAD: {freecad}")
    completed = subprocess.run(
        [freecad, script_path], capture_output=True, text=True, timeout=7200
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"FreeCAD 转换失败 (code={completed.returncode}):\n{completed.stderr[-2000:]}"
        )
    return {"engine": "freecad", "stdout_tail": completed.stdout[-500:]}


def inspect_glb(path: str) -> dict:
    """
    功能: 读取 GLB 的结构统计(节点/网格/图元/三角形/材质), 用于预算评估与命名核对.
    参数:
        path: GLB 文件路径
    返回值: dict, 结构统计; 若 pygltflib 不可用则返回基本信息
    """
    stats: dict = {
        "path": path,
        "size": human_size(os.path.getsize(path)),
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
    }
    try:
        import pygltflib
    except ImportError:
        stats["note"] = "未安装 pygltflib, 跳过结构统计"
        return stats

    gltf = pygltflib.GLTF2().load(path)
    primitives = sum(len(mesh.primitives) for mesh in (gltf.meshes or []))

    triangles = 0
    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives:
            if primitive.indices is None:
                continue
            accessor = gltf.accessors[primitive.indices]
            triangles += accessor.count // 3

    node_names = [node.name for node in (gltf.nodes or []) if node.name]
    stats.update(
        {
            "nodes": len(gltf.nodes or []),
            "meshes": len(gltf.meshes or []),
            "primitives": primitives,
            "triangles": triangles,
            "materials": len(gltf.materials or []),
            "named_nodes": len(node_names),
            "sample_node_names": node_names[:40],
        }
    )
    return stats


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    convert_cfg = config.get("convert", {})
    work_dir = config["paths"]["work"]

    # 与 01 保持一致: 中间产物使用纯 ASCII 名(OCCT 在 Windows 上无法打开含中文的路径)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from importlib import import_module

    slugify = import_module("01_fix_step_names").slugify
    default_input = os.path.join(
        work_dir,
        slugify(os.path.splitext(os.path.basename(config["sources"]["legacy_full_step"]))[0])
        + "_named.STEP",
    )

    parser = argparse.ArgumentParser(description="STEP -> GLB 转换")
    parser.add_argument("--input", default=default_input)
    parser.add_argument("--output", default=None, help="默认写入 work/<原名>.raw.glb")
    parser.add_argument("--engine", default=convert_cfg.get("engine", "cascadio"),
                        choices=["cascadio", "freecad"])
    parser.add_argument("--tol-linear", type=float, default=convert_cfg.get("tol_linear", 0.4))
    parser.add_argument("--tol-angular", type=float, default=convert_cfg.get("tol_angular", 0.5))
    parser.add_argument("--tol-relative", action="store_true",
                        default=bool(convert_cfg.get("tol_relative", False)))
    parser.add_argument("--no-merge-primitives", action="store_true")
    parser.add_argument("--no-parallel", action="store_true")
    parser.add_argument("--no-materials", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(
            f"错误: 输入文件不存在: {args.input}\n请先运行 01_fix_step_names.py"
        )

    stem = os.path.splitext(os.path.basename(args.input))[0]
    output = args.output or os.path.join(work_dir, f"{stem}.raw.glb")

    log(f"引擎: {args.engine}")
    log(f"源文件: {args.input} ({human_size(os.path.getsize(args.input))})")

    with timed(f"STEP -> GLB ({args.engine})"):
        if args.engine == "cascadio":
            result = convert_with_cascadio(
                args.input,
                output,
                tol_linear=args.tol_linear,
                tol_angular=args.tol_angular,
                tol_relative=args.tol_relative,
                merge_primitives=not args.no_merge_primitives,
                use_parallel=not args.no_parallel,
                include_materials=not args.no_materials
                and bool(convert_cfg.get("include_materials", True)),
            )
        else:
            result = convert_with_freecad(args.input, output)

    if not os.path.isfile(output):
        raise SystemExit(f"错误: 转换未产出文件: {output}")

    with timed("GLB 结构统计"):
        stats = inspect_glb(output)

    report = {"input": args.input, "output": output, **result, "glb": stats}
    write_report(os.path.join(work_dir, "02_convert_step.report.json"), report)

    log(
        f"完成: {output} ({stats['size']}); "
        f"节点 {stats.get('nodes', '?')} / 网格 {stats.get('meshes', '?')} / "
        f"图元 {stats.get('primitives', '?')} / 三角形 {stats.get('triangles', '?'):,}"
        if isinstance(stats.get("triangles"), int)
        else f"完成: {output} ({stats['size']})"
    )


if __name__ == "__main__":
    main()
