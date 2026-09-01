"""
功能: 为 pipeline.yaml 的 restore_geometry 规则生成/刷新单件 GLB 素材.

为什么要有它: SolidWorks XR 导出器在**装配**上下文对个别零件只写出带变换的空节点、
不给网格(2026-08-02 上样 EBF41 同步带轮丢失一案), 但**单件导出**完全正常.
03 步用这些单件素材把几何补回空节点位置 —— 素材必须可复现, 不能是手工拷来的孤儿文件.

用法:
    python export_part_assets.py --list                # 只看清单与素材是否已存在
    python export_part_assets.py                       # 补齐缺失素材
    python export_part_assets.py --force               # 全部重导(CAD 更新后用)
    python export_part_assets.py --part <SLDPRT> --out <glb>   # 单独导一个

参数: 见 main() argparse
返回值: 无(素材写入 exports/parts/, 报告写入 work/)
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

from common import ensure_dir, load_config, log, write_report

SW_MCP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp_servers", "sw_mcp")
)


def glb_mesh_count(path: str) -> dict:
    """功能: 只读 GLB 头部 JSON 块统计网格. 参数: GLB 路径. 返回值: dict"""
    with open(path, "rb") as handle:
        handle.read(12)
        chunk_len, _ = struct.unpack("<II", handle.read(8))
        doc = json.loads(handle.read(chunk_len).decode("utf-8"))
    nodes = doc.get("nodes", [])
    return {
        "meshes": len(doc.get("meshes", [])),
        "nodes_with_mesh": sum(1 for n in nodes if "mesh" in n),
        "size_kb": round(os.path.getsize(path) / 1024, 1),
    }


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    root = config["paths"]["root"]
    work_dir = config["paths"]["work"]

    parser = argparse.ArgumentParser(description="生成补几何用的单件 GLB 素材")
    parser.add_argument("--list", action="store_true", help="只列清单, 不导出")
    parser.add_argument("--force", action="store_true", help="已存在也重导")
    parser.add_argument("--part", help="单独导出这个零件(绕过配置清单)")
    parser.add_argument("--out", help="配合 --part 使用的输出 GLB")
    args = parser.parse_args()

    if args.part:
        if not args.out:
            raise SystemExit("--part 必须配 --out")
        jobs = [(os.path.abspath(args.out), args.part)]
    else:
        jobs = []
        for rule in config.get("restore_geometry") or []:
            asset = rule.get("part_glb") or ""
            if not asset:
                continue
            abs_asset = asset if os.path.isabs(asset) else os.path.join(root, asset)
            source = rule.get("source_part")
            if not source:
                raise SystemExit(
                    f"规则 {rule.get('node_prefix')} 缺 source_part —— "
                    "素材必须能从源零件复现, 不能是手工拷来的孤儿文件"
                )
            jobs.append((os.path.abspath(abs_asset), source))

    if not jobs:
        log("restore_geometry 配置为空, 无事可做")
        return

    for asset, source in jobs:
        exists = os.path.isfile(asset)
        log(f"{'[已存在]' if exists else '[缺失]  '} {os.path.basename(asset)} <- {source}")
    if args.list:
        return

    todo = [(a, s) for a, s in jobs if args.force or not os.path.isfile(a)]
    if not todo:
        log("素材齐全, 无需导出(要强制重导加 --force)")
        return

    sys.path.insert(0, SW_MCP_DIR)
    from sw_core import SolidWorksSession

    results = []
    session = SolidWorksSession()
    try:
        info = session.connect()
        log(f"SolidWorks {info['revision']}")
        for asset, source in todo:
            if not os.path.isfile(source):
                raise SystemExit(f"源零件不存在: {source}")
            # 输出路径含非 ASCII 时 SaveAs 会**静默失败**: 返回 ok=True、errors=0,
            # 却根本不写文件(2026-08-02 实测, 24 个素材里 20 个栽在这上面, 一度
            # 误判成"这些零件本身没有几何"). 素材名一律用 ASCII, 中文走拼音 slug.
            if not asset.isascii():
                raise SystemExit(
                    f"素材路径含非 ASCII 字符, SolidWorks 的 SaveAs 会静默不产出文件: {asset}\n"
                    "把 part_glb 改成纯 ASCII 名(中文零件名转拼音), node_prefix 不受影响"
                )
            ensure_dir(asset)
            log(f"导出 {os.path.basename(source)} …")
            started = time.time()
            session.export_gltf(source, asset, keep_open=False)
            stat = glb_mesh_count(asset)
            if stat["nodes_with_mesh"] < 1:
                raise SystemExit(
                    f"素材没有网格, 补几何会白做: {asset}"
                    "(单件导出也拿不到几何, 说明该零件另有问题)"
                )
            log(f"  -> {asset} {stat} 耗时 {round(time.time() - started, 1)}s")
            results.append({"asset": asset, "source": source, **stat})
    finally:
        session.release()

    write_report(os.path.join(work_dir, "export_part_assets.report.json"), {"assets": results})


if __name__ == "__main__":
    main()
