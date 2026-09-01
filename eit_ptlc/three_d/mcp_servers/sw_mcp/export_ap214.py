"""
功能: 把装配体导出为带外观(颜色)的 STEP AP214, 供三维管线取得真实的材质区分.

为什么走导出而不是逐个组件查材质:
    IComponent2 的材质/外观查询虽然能调通, 但对每个组件都会迫使 SolidWorks 从磁盘完整
    解析该零件 —— 1500 多个组件实测跑二十分钟仍未过半, 成本失控.
    而导出是**一次调用**: SolidWorks 内部批量遍历, 顺带把每个面的颜色写进 STEP 的
    STYLED_ITEM / COLOUR_RGB 实体. 这些颜色正是设计者在 CAD 里做出的材质区分,
    cascadio 的 include_materials 会把它们带进 GLB.

前提: AP203 不携带任何外观信息(现有那份整机 STEP 就是 AP203, 所以转出来是一片灰).
必须用 AP214 或 AP242, 且勾上"导出外观".

用法:
    python export_ap214.py                                  # 导出整机
    python export_ap214.py --input <装配体> --name <输出名>
    python export_ap214.py --check-only                     # 只检查已有文件的颜色实体

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 STEP 到 three_d/exports/)
"""

from __future__ import annotations

import argparse
import os
import time

from sw_core import SolidWorksSession

DEFAULT_ASM = r"E:\eit_lab\eit_lab_hardware\eit_ptlc_station\TLC设备总装.SLDASM"
# 与 server.py 的 DEFAULT_EXPORT_DIR 保持一致: three_d/exports(往上两级, 不是一级)
EXPORT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "exports")
)

# 判断 STEP 里到底有没有外观信息的标志实体
COLOR_TOKENS = (
    "COLOUR_RGB",           # 颜色定义本身
    "STYLED_ITEM",          # 把颜色绑到几何上
    "PRESENTATION_STYLE_ASSIGNMENT",
    "FILL_AREA_STYLE_COLOUR",
)


def flush(message: str) -> None:
    """
    功能: 立即打印(后台运行时不至于看不到进度).
    参数:
        message: 内容
    返回值: None
    """
    print(message, flush=True)


def inspect_step_colors(path: str, sample: int = 12) -> dict:
    """
    功能: 检查一个 STEP 文件里的外观信息量, 并抽样列出用到的颜色.

    这是验证"导出到底带没带颜色"的唯一可靠手段 —— 光看文件大小或导出成功与否
    完全说明不了问题.

    参数:
        path: STEP 路径
        sample: 抽样列出多少种颜色
    返回值: dict, 含各标志实体计数、协议名与颜色样本
    """
    counts = {token: 0 for token in COLOR_TOKENS}
    colors: dict[tuple, int] = {}
    protocol = "未知"

    with open(path, "rb") as handle:
        for raw in handle:
            line = raw.decode("latin-1")
            if "FILE_SCHEMA" in line or "FILE_DESCRIPTION" in line:
                for name in ("AP214", "AP203", "AP242", "AUTOMOTIVE_DESIGN", "CONFIG_CONTROL_DESIGN"):
                    if name in line:
                        protocol = name
            for token in COLOR_TOKENS:
                if token in line:
                    counts[token] += 1
            # COLOUR_RGB ( '', 0.7, 0.7, 0.7 )
            if "COLOUR_RGB" in line and "(" in line:
                try:
                    body = line[line.index("(", line.index("COLOUR_RGB")) + 1: line.rindex(")")]
                    parts = [p.strip() for p in body.split(",")]
                    rgb = tuple(round(float(p), 3) for p in parts[-3:])
                    colors[rgb] = colors.get(rgb, 0) + 1
                except (ValueError, IndexError):
                    pass

    top = sorted(colors.items(), key=lambda kv: -kv[1])[:sample]
    return {
        "path": path,
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "protocol": protocol,
        "counts": counts,
        "distinct_colors": len(colors),
        "top_colors": [
            {
                "rgb": list(rgb),
                "hex": "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c * 255)))) for c in rgb),
                "count": count,
            }
            for rgb, count in top
        ],
    }


def report(info: dict) -> None:
    """
    功能: 打印外观检查结果.
    参数:
        info: inspect_step_colors 的产出
    返回值: None
    """
    flush(f"\n=== {os.path.basename(info['path'])} ({info['size_mb']} MB) ===")
    flush(f"协议: {info['protocol']}")
    for token, count in info["counts"].items():
        flush(f"  {token:<32} {count}")
    flush(f"不同颜色: {info['distinct_colors']} 种")
    if info["top_colors"]:
        flush("用得最多的颜色:")
        for item in info["top_colors"]:
            flush(f"  {item['count']:>6}  {item['hex']}  rgb{tuple(item['rgb'])}")
    else:
        flush("⚠ 没有任何颜色实体 —— 该文件不含外观信息, 转出来会是一片灰")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="导出带外观的 STEP AP214")
    parser.add_argument("--input", default=DEFAULT_ASM)
    parser.add_argument("--name", default="TLC_full_AP214.STEP", help="输出文件名(纯 ASCII)")
    parser.add_argument("--ap", type=int, default=214, choices=[214, 242])
    parser.add_argument("--check-only", action="store_true", help="只检查已有文件, 不导出")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    output = os.path.join(EXPORT_DIR, args.name)

    if args.check_only:
        if not os.path.isfile(output):
            raise SystemExit(f"文件不存在: {output}")
        report(inspect_step_colors(output))
        return

    session = SolidWorksSession()
    try:
        info = session.connect()
        flush(f"SolidWorks {info['revision']}  早期绑定={info['early_binding']}")

        flush(f"设置导出选项: AP{args.ap} + 导出外观")
        options = session.set_step_options(ap=args.ap, appearances=True)
        if options["mismatch"]:
            raise SystemExit(f"选项设置未生效: {options['mismatch']}")
        flush(f"  已确认: AP{options['ap']}, 外观={options['appearances']}")

        flush(f"导出(整机一次调用, 预计数分钟): {args.input}")
        started = time.time()
        result = session.export_step(
            args.input, output, ap=args.ap, appearances=True, keep_open=args.keep_open
        )
        flush(f"  完成: {result['size_mb']} MB, 耗时 {round(time.time() - started, 1)}s")
    finally:
        if not args.keep_open:
            session.close_all_opened()
        session.release()

    report(inspect_step_colors(output))


if __name__ == "__main__":
    main()
