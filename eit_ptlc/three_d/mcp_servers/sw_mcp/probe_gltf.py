"""
功能: 探明 SolidWorks 自带 XR 导出器能否静默导出 glTF, 并验证产物是否保住了名字与材质.

这是"改走原生 glTF 入口"这条路的判定关口. 关心三件事, 缺一不可:
    1. 拿不拿得到插件对象(GetAddInObject)
    2. 导出的 GLB 里节点**有没有可读的名字** —— 这是整条管线的命门.
       走 STEP 时名字全变 NAUO1234, 要靠 01 步回填才救回来; 原生导出理应不用.
    3. materials 段**是不是非空** —— STEP(AP203)一个颜色都不带, 逼得我们另开 COM 通道逐零件读.

用法:
    python probe_gltf.py --part                # 只导单零件(最快)
    python probe_gltf.py --sub                 # 再导一个子装配
    python probe_gltf.py --input <路径> --name <输出名>

参数: 见 main() 中的 argparse 定义
返回值: 无(打印判定结论, 产物写到 exports/)
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

from sw_core import XR_EXPORTER_CLSID, SolidWorksSession

# 探路用的两个样本: 先零件后子装配, 由小到大
SAMPLE_PART = r"E:\eit_lab\eit_lab_hardware\eit_ptlc_station\PTLC-08-011 三色灯立柱.SLDPRT"
# 这个子装配正是网页模型里缺掉的那个, 顺带验证它能不能回来
SAMPLE_SUB = r"E:\eit_lab\eit_lab_hardware\eit_ptlc_station\平面展缸\展缸注射泵总装.SLDASM"

# 与 server.py 的 DEFAULT_EXPORT_DIR 保持一致: three_d/exports(往上两级, 不是一级)
EXPORT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "exports")
)


def flush(message: str) -> None:
    """功能: 立即打印. 参数: message. 返回值: None"""
    print(message, flush=True)


def read_glb_json(path: str) -> dict:
    """
    功能: 只读 GLB 头部的 JSON 块, 不碰后面的二进制数据.

    参数:
        path: GLB 路径
    返回值: dict, glTF 的 JSON 文档
    异常: ValueError, 不是合法 GLB 时抛出
    """
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            raise ValueError("文件太短, 不是 GLB")
        magic, _version, _length = struct.unpack("<III", header)
        if magic != 0x46546C67:  # 'glTF'
            raise ValueError(f"魔数不对({magic:#x}), 可能导出的是 .gltf 而非 .glb")
        chunk_len, chunk_type = struct.unpack("<II", handle.read(8))
        if chunk_type != 0x4E4F534A:  # 'JSON'
            raise ValueError("首块不是 JSON 块")
        return json.loads(handle.read(chunk_len).decode("utf-8"))


def judge(path: str) -> dict:
    """
    功能: 对导出的 GLB 做判定 —— 名字保住了吗, 材质带出来了吗.

    参数:
        path: GLB 路径
    返回值: dict, 含各项统计与两个布尔判定
    """
    doc = read_glb_json(path)
    nodes = doc.get("nodes", [])
    materials = doc.get("materials", [])
    named = [n for n in nodes if n.get("name")]
    # NAUO1234 / node_12 这类是"没保住名字"的典型形态
    meaningless = [
        n for n in named
        if n["name"].startswith("NAUO") or n["name"].lower().startswith(("node", "mesh", "object_"))
    ]

    colors = set()
    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {})
        base = pbr.get("baseColorFactor")
        if base:
            colors.add(tuple(round(c, 3) for c in base[:3]))

    return {
        "nodes": len(nodes),
        "named_nodes": len(named),
        "meaningless_names": len(meaningless),
        "meshes": len(doc.get("meshes", [])),
        "materials": len(materials),
        "distinct_base_colors": len(colors),
        "extensions": doc.get("extensionsUsed", []),
        "generator": doc.get("asset", {}).get("generator", ""),
        "sample_names": [n["name"] for n in named[:12]],
        "sample_materials": [m.get("name", "(无名)") for m in materials[:12]],
        "names_ok": len(named) > 0 and len(meaningless) < max(1, len(named) * 0.5),
        "materials_ok": len(materials) > 0,
    }


def report(title: str, info: dict) -> None:
    """功能: 打印判定结果. 参数: title/info. 返回值: None"""
    flush(f"\n===== {title} =====")
    flush(f"  生成器      : {info['generator']}")
    flush(f"  节点        : {info['nodes']}  (有名字 {info['named_nodes']}, "
          f"其中无意义名 {info['meaningless_names']})")
    flush(f"  网格        : {info['meshes']}")
    flush(f"  材质        : {info['materials']}  (不同基色 {info['distinct_base_colors']} 种)")
    flush(f"  扩展        : {info['extensions'] or '无'}")
    flush(f"  节点名样例  : {info['sample_names']}")
    flush(f"  材质名样例  : {info['sample_materials']}")
    flush(f"  → 名字保住了吗: {'是' if info['names_ok'] else '否'}")
    flush(f"  → 材质带出来了吗: {'是' if info['materials_ok'] else '否'}")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="探路: SolidWorks 原生 glTF 导出")
    parser.add_argument("--input", default="", help="源文件; 留空则按 --part/--sub 选样本")
    parser.add_argument("--name", default="", help="输出文件名(纯 ASCII, 含 .glb)")
    parser.add_argument("--part", action="store_true", help="导单零件样本")
    parser.add_argument("--sub", action="store_true", help="导子装配样本")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    targets: list[tuple[str, str]] = []
    if args.input:
        targets.append((args.input, args.name or "_probe.glb"))
    else:
        if args.part or not args.sub:
            targets.append((SAMPLE_PART, "_probe_part.glb"))
        if args.sub:
            targets.append((SAMPLE_SUB, "_probe_sub.glb"))

    session = SolidWorksSession()
    try:
        started = time.time()
        flush("连接 SolidWorks(未运行则会拉起, 首次可能要一两分钟)…")
        info = session.connect()
        flush(f"  {info['revision']}  早期绑定={info['early_binding']}  "
              f"{round(time.time() - started, 1)}s")

        flush(f"\n取 XR 导出器插件 {XR_EXPORTER_CLSID} …")
        exporter = session.get_addin(XR_EXPORTER_CLSID, "ISWXRExporter")
        if exporter is None:
            flush("  ✗ 拿不到插件对象")
            flush("    多半是它没随 SolidWorks 启动 —— 需在 工具→插件 里勾上")
            flush("    'SOLIDWORKS XR Exporter', 或用注册表让它开机加载")
            raise SystemExit(2)
        flush(f"  ✓ 拿到了: {type(exporter).__name__}")
        # 插件的作用只是把 .glb 注册成 SaveAs 目标格式; 它自带的 GLTF_FileSave_* 实测
        # 是 0.2 秒空返回不产出(EnablePMP() 返 0, 缺 UI 上下文), 所以我们走常规 SaveAs.
        # 绝不调 ShowPMP —— 那会弹出属性页把 COM 堵死.

        for source, out_name in targets:
            flush(f"\n导出: {os.path.basename(source)}")
            result = session.export_gltf(
                source, os.path.join(EXPORT_DIR, out_name), keep_open=args.keep_open
            )
            flush(f"  {result['size_mb']} MB  {result['elapsed_s']}s  "
                  f"errors={result['errors']} warnings={result['warnings']}")
            report(out_name, judge(result["output"]))
    finally:
        if not args.keep_open:
            session.close_all_opened()
        session.release()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
