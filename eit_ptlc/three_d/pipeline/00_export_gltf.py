"""
功能: 管线第 00 步 —— 用 SolidWorks 自带的 XR 导出器把整机装配体直出为 GLB.

为什么有这一步(以及它取代了什么):
    原先的入口是 01(STEP 名称修复) + 02(STEP→GLB, OCCT 转换约 11 分钟). 那条路的代价是
    STEP(AP203)会丢掉一大截信息, 于是 01 步不得不顺着 `NAUO→PRODUCT_DEFINITION→PRODUCT`
    的引用链把真实装配实例名回填回去, 材质还得再开一条 COM 通道逐零件读.

    SolidWorks 2025 自带 glTF 导出器, 直出的 GLB 原生就带:
        * 真实装配实例名(`电磁阀总装-2`, 带 -N 后缀区分多实例), 中文原样保留
        * 具名 PBR 材质(`polished steel` / `white medium gloss plastic`)
        * Solidworks_custom_properties 扩展(自定义属性)
        * Draco 压缩几何(Blender 可直接读, 已验证层级/材质/单位全对)

    所以走这一步就能跳过 01 与 02.

踩过的坑(都已固化进 sw_core.export_gltf):
    * 导出器插件默认不随 SolidWorks 启动, 需先 LoadAddIn
    * 插件自带的 GLTF_FileSave_Assembly/Part 是死的(各种参数写法都空返回不产出),
      真正入口是常规 Extension.SaveAs
    * **只支持 .glb**; .gltf 会返回成功却不产出任何文件
    * 文档必须处于激活状态

用法:
    python 00_export_gltf.py                       # 导整机
    python 00_export_gltf.py --input <装配体> --output <out.glb>
    python 00_export_gltf.py --inspect-only        # 只检查已有产物

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 GLB 到 exports/, 报告写入 work/)
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

from common import ensure_dir, human_size, load_config, log, write_report

SW_MCP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp_servers", "sw_mcp")
)


def glb_summary(path: str) -> dict:
    """
    功能: 只读 GLB 头部 JSON 块, 汇总它保住了多少信息.

    这是判断"这次导出到底成不成"的依据 —— 光看文件大小说明不了问题, 关键是
    节点有没有名字、材质是不是非空.

    参数:
        path: GLB 路径
    返回值: dict, 含节点/网格/材质统计与样例名
    """
    with open(path, "rb") as handle:
        magic, _version, _length = struct.unpack("<III", handle.read(12))
        if magic != 0x46546C67:  # 'glTF'
            raise RuntimeError(f"不是合法 GLB: {path}")
        chunk_len, chunk_type = struct.unpack("<II", handle.read(8))
        if chunk_type != 0x4E4F534A:  # 'JSON'
            raise RuntimeError(f"GLB 首块不是 JSON: {path}")
        document = json.loads(handle.read(chunk_len).decode("utf-8"))

    nodes = document.get("nodes", [])
    named = [n for n in nodes if n.get("name")]
    # 顶层 = 场景直接挂的节点
    scenes = document.get("scenes") or [{}]
    top = scenes[document.get("scene", 0)].get("nodes", []) if scenes else []
    materials = document.get("materials", [])

    # 空叶节点 = 无网格且无子节点的具名节点(排除导出器附带的 current 相机).
    # XR 导出器对"纯曲面零件/被隐藏或压缩的实例"会只留变换不给几何, 零件就这样
    # 无声消失在孪生里(2026-08-02 上样 EBF41 同步带轮一案), 必须显式盯住.
    empty_leaves = sorted(
        n["name"] for n in named
        if "mesh" not in n and not n.get("children") and n["name"] != "current"
    )

    return {
        "path": path,
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "generator": document.get("asset", {}).get("generator", ""),
        "nodes": len(nodes),
        "named_nodes": len(named),
        "top_level": len(top),
        "meshes": len(document.get("meshes", [])),
        "materials": len(materials),
        "extensions": document.get("extensionsUsed", []),
        "sample_nodes": [n["name"] for n in named[:15]],
        "sample_materials": [m.get("name", "(无名)") for m in materials[:15]],
        "empty_leaves": empty_leaves,
    }


def report_summary(info: dict) -> None:
    """功能: 打印 GLB 汇总. 参数: info. 返回值: None"""
    log(f"产物: {info['path']} ({info['size_mb']} MB)")
    log(f"  生成器: {info['generator']}")
    log(f"  顶层组件 {info['top_level']} / 节点 {info['nodes']}(有名字 {info['named_nodes']}) "
        f"/ 网格 {info['meshes']} / 材质 {info['materials']}")
    log(f"  扩展: {', '.join(info['extensions']) or '无'}")
    log(f"  节点名样例: {info['sample_nodes'][:8]}")
    log(f"  材质名样例: {info['sample_materials'][:8]}")
    log(f"  空叶节点: {len(info['empty_leaves'])} 个")


def check_empty_leaves(summary: dict, config: dict) -> list[str]:
    """
    功能: 空叶节点门禁 —— 与 pipeline.yaml 白名单做差集.

    白名单按**实例名整串**匹配(如 `外罩-1`); 同一名字在装配树多处出现时一并放行,
    粒度到不了"同名不同父", 放行前须确认该名字全部实例都属有意隐藏.

    参数:
        summary: glb_summary 的返回值
        config: pipeline.yaml 配置
    返回值: list[str], 白名单之外的空叶节点名(应为空)
    """
    allowed = set((config.get("export_gate") or {}).get("expected_empty_nodes") or [])
    return [name for name in summary["empty_leaves"] if name not in allowed]


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    work_dir = config["paths"]["work"]

    parser = argparse.ArgumentParser(description="SolidWorks 原生 glTF 导出(管线第 00 步)")
    parser.add_argument("--input", default=config["sources"]["full_assembly"])
    parser.add_argument("--output", default=config["sources"]["native_glb"])
    parser.add_argument("--keep-open", action="store_true", help="导完保持文档打开")
    parser.add_argument("--inspect-only", action="store_true", help="只检查已有产物, 不导出")
    parser.add_argument("--no-gate", action="store_true",
                        help="跳过空叶节点门禁(仅排查/过渡期用)")
    args = parser.parse_args()

    output = os.path.abspath(args.output)

    if args.inspect_only:
        if not os.path.isfile(output):
            raise SystemExit(f"错误: 产物不存在: {output}")
        summary = glb_summary(output)
        report_summary(summary)
        unexpected = check_empty_leaves(summary, config)
        if unexpected:
            log(f"警告: 白名单外空叶节点 {len(unexpected)} 个: {unexpected[:10]} …")
        return

    if not os.path.isfile(args.input):
        raise SystemExit(f"错误: 装配体不存在: {args.input}")

    # sw_core 只在这一步用到; 放到函数里导入, 免得没装 pywin32 的机器连管线都跑不起来
    sys.path.insert(0, SW_MCP_DIR)
    from sw_core import SolidWorksSession

    ensure_dir(output)
    log(f"输入: {args.input} ({human_size(os.path.getsize(args.input))})")
    log("经 SolidWorks XR 导出器直出 GLB(整机规模可能要几十分钟)…")

    session = SolidWorksSession()
    started = time.time()
    try:
        info = session.connect()
        log(f"SolidWorks {info['revision']} 早期绑定={info['early_binding']}")
        result = session.export_gltf(args.input, output, keep_open=args.keep_open)
    finally:
        session.release()

    log(f"完成: {result['size_mb']} MB, 耗时 {round(time.time() - started, 1)}s")

    summary = glb_summary(output)
    report_summary(summary)

    if summary["named_nodes"] == 0:
        raise SystemExit("错误: 产物里没有任何带名字的节点 —— 下游全部规则都会失效")
    if summary["materials"] == 0:
        log("警告: 产物没有材质, 后续只能靠 materials.yaml 的名称规则赋材")

    unexpected = check_empty_leaves(summary, config)

    # 先落报告再门禁: 报错时用户手里要有完整名单可查
    write_report(
        os.path.join(work_dir, "00_export_gltf.report.json"),
        {"export": result, "summary": summary, "unexpected_empty_leaves": unexpected},
    )

    if unexpected and not args.no_gate:
        for name in unexpected[:20]:
            log(f"  空叶节点(白名单外): {name}")
        raise SystemExit(
            f"错误: {len(unexpected)} 个零件导出无几何(白名单外空叶节点) —— "
            "多为纯曲面零件或被隐藏/压缩的实例, 会在孪生里无声消失. "
            "修零件或确认有意后把名字加进 pipeline.yaml export_gate.expected_empty_nodes; "
            "临时放行用 --no-gate"
        )


if __name__ == "__main__":
    main()
