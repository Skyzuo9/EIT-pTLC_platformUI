"""
功能: 把 labware_geom 的参数化深孔板单独导出成可审阅的数模资产 GLB.

产物落在 `exports/parts/`(与 restore_geometry 用的单件 GLB 同一目录约定):
    exports/parts/deepwell_24_10ml.glb
    exports/parts/deepwell_24_15ml.glb
这两份是"数模"本体 —— 可以用 blender_inspect 量尺寸、blender_render 出图目检,
**不必先跑二十多分钟的整机重建就能定稿外观**. 整机里的板由
`blender_clean.build_sample_plates()` 用同一份 labware_geom 现场生成, 不读这两个文件
(避免"改了代数忘了重出资产"这类双真源问题).

本文件是**双模的**: 直接用系统 Python 跑 = 启动器(从 pipeline.yaml 取 blender 路径,
再把自己作为脚本喂给无界面 Blender); 在 Blender 里被执行时 = 执行器. 之所以没像 03 步
那样拆成两个文件, 是因为这里不需要 PyYAML 参与几何(labware_geom 是纯 stdlib), 拆开
只会多一个文件而不多一分清晰.

用法:
    python gen_labware.py                     # 出全部规格
    python gen_labware.py --spec deepwell_24_15ml
    python gen_labware.py --report            # 只打自检报告, 不跑 Blender
"""

from __future__ import annotations

import argparse
import json
import os
import sys

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import labware_geom as LG  # noqa: E402  (须在 sys.path 补好之后)

try:
    import bpy
except ImportError:                       # 系统 Python: 启动器模式
    bpy = None


# ---------------------------------------------------------------------------
# 执行器(Blender 内)
# ---------------------------------------------------------------------------

def _plate_material(spec: dict):
    """
    功能: 造聚丙烯本色材质(Principled BSDF).

    实验室耗材的观感线索是"哑光、微透、偏冷白"的塑料, 与整机上那些金属/钣金件必须
    一眼分得开 —— 所以粗糙度给到 0.42、金属度 0, 基色取本色 PP 的微暖白.
    暂按**不透明**处理: 24 个孔腔叠上 alpha 混合会带来排序伪影, 而整机尺度下
    半透带来的信息量远不抵这个代价. 若用户要半透, 改这里的 alpha 与 blend_method 即可.

    参数: spec 规格字典
    返回值: bpy.types.Material
    """
    mat = bpy.data.materials.new(f"MAT_LABWARE_PP_{spec['key']}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.88, 0.89, 0.87, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.42
        bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def build_object(spec: dict, scale: float = 0.001):
    """
    功能: 在当前 Blender 场景里造一块深孔板对象.

    labware_geom 出的是毫米, 而 glTF/整机场景一律米制 —— 所以在**顶点上**乘 scale 而不是
    设 object.scale: 带非单位 scale 的对象在后续父子变换/包围盒实测里全是坑
    (见 CLAUDE.md 第 6/11 条那两次量化包围盒膨胀事故).

    参数: spec 规格字典; scale 毫米→场景单位的系数(默认 0.001 = 米)
    返回值: bpy.types.Object
    """
    acc = LG.build_plate(spec)
    mesh = bpy.data.meshes.new(spec["key"])
    mesh.from_pydata([(x * scale, y * scale, z * scale) for x, y, z in acc.verts], [], acc.faces)
    mesh.update()
    for poly, flag in zip(mesh.polygons, acc.smooth):
        poly.use_smooth = flag
    obj = bpy.data.objects.new(spec["key"], mesh)
    obj.data.materials.append(_plate_material(spec))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def run_in_blender() -> None:
    """
    功能: Blender 内的主流程 —— 逐规格清场、建板、导出 GLB.
    参数: 无(读 "--" 之后的命令行)
    返回值: None
    """
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--spec", default="")
    args = parser.parse_args(argv)

    keys = [args.spec] if args.spec else list(LG.PLATE_SPECS)
    os.makedirs(args.out_dir, exist_ok=True)
    reports = []
    for key in keys:
        spec = LG.PLATE_SPECS[key]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        obj = build_object(spec)
        path = os.path.join(args.out_dir, f"{key}.glb")
        bpy.ops.export_scene.gltf(
            filepath=path, export_format="GLB", export_apply=True,
            export_materials="EXPORT", export_yup=True,
            export_cameras=False, export_lights=False, export_animations=False,
        )
        report = LG.plate_report(spec)
        report["glb"] = path
        report["glb_bytes"] = os.path.getsize(path)
        # 落地实测: 从对象自身逐顶点量, 证明"代数说的"与"网格里的"是一回事
        pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
        report["measured_mm"] = [
            round((max(p[i] for p in pts) - min(p[i] for p in pts)) * 1000, 3) for i in range(3)
        ]
        reports.append(report)
        print(f"[labware] 导出 {path}", flush=True)
    print("@@LABWARE_REPORT@@" + json.dumps(reports, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------------------
# 启动器(系统 Python)
# ---------------------------------------------------------------------------

def run_launcher() -> None:
    """
    功能: 解析参数, 找到 blender.exe, 以无界面方式把本文件喂回去执行.
    参数: 无(读 sys.argv)
    返回值: None
    """
    import subprocess

    from common import load_config, log

    parser = argparse.ArgumentParser(description="导出 24 孔深孔板数模 GLB")
    parser.add_argument("--spec", default="", choices=[""] + list(LG.PLATE_SPECS))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--report", action="store_true", help="只打自检报告, 不跑 Blender")
    parser.add_argument("--blender", default="")
    args = parser.parse_args()

    if args.report:
        keys = [args.spec] if args.spec else list(LG.PLATE_SPECS)
        print(json.dumps([LG.plate_report(LG.PLATE_SPECS[k]) for k in keys],
                         ensure_ascii=False, indent=2))
        return

    config = load_config()
    blender = args.blender or config["paths"]["blender"]
    if not os.path.isfile(blender):
        raise SystemExit(f"未找到 Blender: {blender}; 检查 pipeline.yaml 的 paths.blender")
    out_dir = args.out_dir or os.path.join(config["paths"]["exports"], "parts")

    cmd = [blender, "--background", "--factory-startup", "--python", os.path.abspath(__file__),
           "--", "--out-dir", out_dir]
    if args.spec:
        cmd += ["--spec", args.spec]
    log(f"调用 Blender 生成数模: {' '.join(cmd[:4])} ...")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)
    marker = "@@LABWARE_REPORT@@"
    payload = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith(marker):
            payload = json.loads(line[len(marker):])
    if proc.returncode != 0 or payload is None:
        sys.stderr.write((proc.stdout or "")[-4000:] + "\n" + (proc.stderr or "")[-2000:] + "\n")
        raise SystemExit(f"Blender 生成失败 (returncode={proc.returncode})")

    for report in payload:
        want = [report["footprint_mm"][0], report["footprint_mm"][1], report["height_mm"]]
        got = report["measured_mm"]
        # 网格实测必须与规格逐项吻合 —— 差了就是代数与建模走岔了, 硬失败而不是打个警告继续
        for axis, (w, g) in enumerate(zip(want, got)):
            if abs(w - g) > 0.02:
                raise SystemExit(
                    f"{report['key']} 第 {axis} 轴实测 {g} ≠ 规格 {w} —— 生成器与规格表不一致")
        log(f"{report['label']}: {got[0]}×{got[1]}×{got[2]}mm, {report['wells']} 孔, "
            f"孔距 {report['pitch_x_mm']}, 单孔 {report['well_volume_ml']}mL "
            f"(标称 {report['nominal_ml']}), {report['tris']} 三角, "
            f"{report['glb_bytes'] / 1024:.1f} KB")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if bpy is not None:
        run_in_blender()
    else:
        run_launcher()
