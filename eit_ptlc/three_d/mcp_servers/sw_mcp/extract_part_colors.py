"""
功能: 读取整机每个零件的 SolidWorks 材质名与外观颜色, 产出 work/part_colors.json.

三条路都试过, 只有第三条可用:

  1. 组件级 MaterialPropertyValues —— 只返回"组件级覆盖". 整机 1544 个组件里仅 3 个
     做了覆盖(都是透明件), 其余返回 null. 颜色实际存在零件文件自身, 拿不到.

  2. 逐零件 OpenDoc6 + CloseDoc —— 能拿到真数据(材质名/颜色都有), 但冷开一个零件要
     34.9 秒, 749 个唯一零件要跑 7.3 小时, 成本失控.

  3. 本脚本: 装配体一次性完整打开后, 所有零件文档已在内存中. 通过
     IComponent2::GetModelDoc2() 取到的是**内存里那份**, 无磁盘 IO. 再按零件文件路径
     去重, 每个唯一文件只读一次.

另外记录一条踩坑: Extension.SaveAs(ExportData=None) 这条静默 STEP 导出路径恒定写出
AP203(FILE_SCHEMA = CONFIG_CONTROL_DESIGN), 无论 swStepAP / swStepExportPreference
设成什么都不变, 所以走 STEP 拿 STYLED_ITEM/COLOUR_RGB 这条路是死的.

用法:
    python extract_part_colors.py --limit 120     # 先小样本量成本
    python extract_part_colors.py                 # 全量

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 work/part_colors.json)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import sw_constants as swc
from sw_core import SolidWorksSession, _prop, _wrap

DEFAULT_ASM = r"E:\eit_lab\eit_lab_hardware\eit_ptlc_station\TLC设备总装.SLDASM"
WORK_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "work")
)
OUTPUT_JSON = os.path.join(WORK_DIR, "part_colors.json")
# "正在读哪个零件"的旁路日志; SolidWorks 卡死只能强杀时, 靠它定位元凶
TRACE_LOG = os.path.join(WORK_DIR, "part_colors.trace.log")

# MaterialPropertyValues 返回 9 个 double, 含义按 SolidWorks API 文档固定
_MPV_FIELDS = (
    "r", "g", "b", "ambient", "diffuse", "specular", "shininess", "transparency", "emission"
)


def flush(message: str) -> None:
    """功能: 立即打印. 参数: message. 返回值: None"""
    print(message, flush=True)


def _trace(path: str) -> None:
    """
    功能: 把"正在读哪个零件"追加进旁路日志并立刻刷盘.

    SolidWorks 在某些组件上会自旋不返回, 那时只能强杀进程、拿不到任何栈信息.
    有了这份日志, 最后一行就是卡住的那个零件, 之后用 --skip 绕开即可.

    参数:
        path: 零件绝对路径
    返回值: None
    """
    try:
        with open(TRACE_LOG, "a", encoding="utf-8") as handle:
            handle.write(path + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def read_appearance(model) -> dict | None:
    """
    功能: 读一个已打开文档的外观(9 个材质属性值).
    参数:
        model: IModelDoc2
    返回值: dict | None, 无外观时返回 None
    """
    try:
        values = _prop(model, "MaterialPropertyValues")
    except Exception:  # noqa: BLE001 - COM 侧异常一律当作读不到
        return None
    if not values:
        return None
    values = list(values)
    if len(values) < 9:
        return None
    record = {name: round(float(values[index]), 4) for index, name in enumerate(_MPV_FIELDS)}
    record["hex"] = "#%02X%02X%02X" % tuple(
        max(0, min(255, int(round(record[channel] * 255)))) for channel in ("r", "g", "b")
    )
    return record


def read_material_name(model) -> tuple[str, str]:
    """
    功能: 读零件的材质名与材质库名.
    参数:
        model: IModelDoc2(应为零件文档)
    返回值: (材质名, 材质库名); 读不到时返回 ("", "")
    """
    for method in ("GetMaterialPropertyName2", "GetMaterialPropertyName"):
        try:
            result = getattr(model, method)("", "")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(result, (tuple, list)):
            name = str(result[0] or "")
            database = str(result[1] or "") if len(result) > 1 else ""
            return name, database
        if result:
            return str(result), ""
    try:
        return str(_prop(model, "MaterialIdName") or ""), ""
    except Exception:  # noqa: BLE001
        return "", ""


def load_previous() -> dict[str, dict]:
    """
    功能: 读回上一轮已经取到的零件, 用于断点续跑.
    参数: 无
    返回值: dict, {零件路径: 记录}; 没有历史时返回空字典
    """
    if not os.path.isfile(OUTPUT_JSON):
        return {}
    try:
        with open(OUTPUT_JSON, encoding="utf-8") as handle:
            return {item["path"]: item for item in json.load(handle).get("parts", [])}
    except (OSError, ValueError, KeyError):
        return {}


def collect(
    session: SolidWorksSession,
    asm_path: str,
    limit: int = 0,
    resume: bool = True,
    skip: tuple[str, ...] = (),
) -> dict:
    """
    功能: 遍历已打开装配体的全部组件, 按零件文件去重后读材质与外观.

    这台装配上 SolidWorks 会在某个组件上自旋不返回(CPU 满核、内存不涨、无磁盘读),
    所以做了三重保护: 每 50 个零件增量落盘、把"正在读哪个"写进旁路日志(卡住时最后一行
    就是元凶)、以及按路径续跑与跳过.

    参数:
        session: 已连接的会话
        asm_path: 装配体绝对路径
        limit: 只处理前 N 个组件, 0 表示全部
        resume: 是否复用 part_colors.json 里已取到的零件
        skip: 要跳过的零件路径片段(命中即不读, 用于绕开会卡死的组件)
    返回值: dict, 含 parts / failures / elapsed_s
    """
    stage = time.time()
    flush("打开装配体…")
    session.open_document(asm_path, read_only=True)
    model = session._find_open_model(asm_path)
    if model is None:
        raise RuntimeError(f"打开后仍未找到装配体: {asm_path}")
    flush(f"  打开完成 {round(time.time() - stage, 1)}s")

    # model 已是 IModelDoc2 包装, 必须 force 才能换到 IAssemblyDoc 接口
    assembly = _wrap(model, "IAssemblyDoc", force=True)

    # 1544 个组件的大装配, SolidWorks 默认按"自动轻量化"载入; 轻量化组件的
    # GetModelDoc2() 会**逐个**触发从磁盘解析(实测冷开一个零件 34.9s, 749 个要 7.3 小时).
    # ResolveAllLightWeightComponents 是一次性批量解析, 之后每个 GetModelDoc2 都命中内存.
    stage = time.time()
    flush("批量解析轻量化组件(一次性, 大装配可能要几分钟)…")
    try:
        _prop(assembly, "ResolveAllLightWeightComponents", False)
        flush(f"  解析完成 {round(time.time() - stage, 1)}s")
    except Exception as exc:  # noqa: BLE001 - 解析失败仍可继续, 只是会慢
        flush(f"  解析调用失败({str(exc)[:120]}), 继续尝试直接读取")

    # 千万别用 IAssemblyDoc::GetComponents(False) 来"一次拿全部组件".
    # 实测在这台 1544 组件的装配上, 该调用会让 SolidWorks 满核自旋一小时以上不返回
    # (内存不涨、无模态框、杀掉客户端后 CPU 立刻归零 —— 是它自己在打转).
    # 走"配置 -> 根组件 -> GetChildren"递归才是可用的路子.
    stage = time.time()
    flush("递归遍历组件树…")
    config = _wrap(_prop(model, "GetActiveConfiguration"), "IConfiguration")
    root = _wrap(_prop(config, "GetRootComponent3", True), "IComponent2")

    parts: dict[str, dict] = load_previous() if resume else {}
    if parts:
        flush(f"  续跑: 已有 {len(parts)} 个零件, 本轮跳过它们")
    failures: list[dict] = []
    seen_subassembly: set[str] = set()
    counters = {"visited": 0, "read": 0}
    started = time.time()

    def snapshot() -> None:
        """功能: 增量落盘, 卡死时已取到的部分不会白跑. 参数: 无. 返回值: None"""
        save(
            {
                "assembly": asm_path,
                "elapsed_s": round(time.time() - started, 1),
                "components_scanned": counters["visited"],
                "complete": False,
                "failures": failures,
                "parts": sorted(parts.values(), key=lambda item: item["file"]),
            }
        )

    def visit(component, depth: int) -> None:
        """功能: 递归访问组件, 按零件文件去重后读材质. 参数: component/depth. 返回值: None"""
        children = _prop(component, "GetChildren")
        if not children:
            return
        for raw in children:
            if limit and counters["visited"] >= limit:
                return
            child = _wrap(raw, "IComponent2")
            try:
                path = str(_prop(child, "GetPathName") or "")
            except Exception as exc:  # noqa: BLE001
                failures.append({"depth": depth, "error": str(exc)[:160]})
                continue
            if not path:
                continue

            counters["visited"] += 1
            if counters["visited"] % 200 == 0:
                flush(
                    f"  已访问 {counters['visited']} 个组件  唯一零件 {len(parts)}  "
                    f"累计 {round(time.time() - started, 1)}s  失败 {len(failures)}"
                )

            is_assembly = path.lower().endswith(".sldasm")
            # 只有零件才有自己的材质; 同一零件文件被引用多次时只读一次
            if not is_assembly and path not in parts:
                if any(fragment and fragment in path for fragment in skip):
                    failures.append({"path": path, "error": "按 --skip 跳过"})
                    continue
                # 读之前先记下"正在读谁": SolidWorks 卡死时进程只能强杀, 拿不到栈,
                # 这个旁路日志的最后一行就是元凶
                _trace(path)
                try:
                    doc = _prop(child, "GetModelDoc2")
                    if doc is None:
                        failures.append({"path": path, "error": "GetModelDoc2 返回 None(未解析)"})
                    else:
                        doc = _wrap(doc, "IModelDoc2")
                        material, database = read_material_name(doc)
                        parts[path] = {
                            "file": os.path.basename(path),
                            "path": path,
                            "material": material,
                            "material_db": database,
                            "appearance": read_appearance(doc),
                        }
                        counters["read"] += 1
                        if counters["read"] % 50 == 0:
                            snapshot()
                except Exception as exc:  # noqa: BLE001 - 单个零件失败不该中断整轮
                    failures.append({"path": path, "error": str(exc)[:160]})

            # 同一个子装配被引用多次时只递归一次, 否则大装配会指数级膨胀
            if is_assembly and path not in seen_subassembly:
                seen_subassembly.add(path)
                visit(child, depth + 1)

    visit(root, 1)
    flush(f"  遍历完成 {round(time.time() - stage, 1)}s, 访问 {counters['visited']} 个组件")

    return {
        "assembly": asm_path,
        "elapsed_s": round(time.time() - started, 1),
        "complete": True,
        "components_scanned": counters["visited"],
        "failures": failures,
        "parts": sorted(parts.values(), key=lambda item: item["file"]),
    }


def save(result: dict) -> str:
    """
    功能: 把提取结果落盘.
    参数:
        result: collect 的产出
    返回值: str, 写出的文件路径
    """
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return OUTPUT_JSON


def summary_of(result: dict) -> dict:
    """
    功能: 把提取结果压成一份分布摘要 —— 这就是"CAD 里有哪些材质区别"的答案.
    参数:
        result: collect 的产出
    返回值: dict, 含材质分布/颜色分布/透明件清单/材质→颜色交叉表
    """
    parts = result["parts"]
    materials = Counter(part["material"] for part in parts if part["material"])
    colors = Counter(part["appearance"]["hex"] for part in parts if part["appearance"])
    transparent = [
        part for part in parts
        if part["appearance"] and part["appearance"]["transparency"] > 0.01
    ]

    # 材质 -> 颜色 的交叉表, 用于判断"同材质是否同色"
    cross: dict[str, Counter] = {}
    for part in parts:
        key = part["material"] or "(未指定材质)"
        hex_value = part["appearance"]["hex"] if part["appearance"] else "(无外观)"
        cross.setdefault(key, Counter())[hex_value] += 1

    return {
        "output": OUTPUT_JSON,
        "parts": len(parts),
        "components_scanned": result.get("components_scanned", 0),
        "failures": len(result["failures"]),
        "elapsed_s": result.get("elapsed_s", 0),
        "without_material": sum(1 for part in parts if not part["material"]),
        "materials": [{"name": n, "count": c} for n, c in materials.most_common()],
        "colors": [{"hex": h, "count": c} for h, c in colors.most_common()],
        "transparent": [
            {
                "file": part["file"],
                "transparency": part["appearance"]["transparency"],
                "hex": part["appearance"]["hex"],
            }
            for part in transparent
        ],
        "material_to_colors": {
            key: [{"hex": h, "count": c} for h, c in counter.most_common(6)]
            for key, counter in sorted(cross.items(), key=lambda kv: -sum(kv[1].values()))
        },
    }


def summarize(result: dict) -> None:
    """功能: 把摘要打印成人看的形式. 参数: result. 返回值: None"""
    info = summary_of(result)

    flush(f"\n唯一零件 {info['parts']} 个, 失败 {info['failures']} 个, 耗时 {info['elapsed_s']}s")
    flush(f"\n=== 材质名 {len(info['materials'])} 种 ===")
    for item in info["materials"][:60]:
        flush(f"  {item['count']:>4}  {item['name']}")
    flush(f"  {info['without_material']:>4}  (未指定材质)")

    flush(f"\n=== 外观颜色 {len(info['colors'])} 种 ===")
    for item in info["colors"][:60]:
        flush(f"  {item['count']:>4}  {item['hex']}")

    flush(f"\n=== 透明件 {len(info['transparent'])} 个 ===")
    for item in info["transparent"][:30]:
        flush(f"  α={item['transparency']:<6} {item['hex']}  {item['file']}")

    flush("\n=== 材质 → 颜色 ===")
    for key, entries in list(info["material_to_colors"].items())[:20]:
        detail = "  ".join(f"{e['hex']}×{e['count']}" for e in entries)
        flush(f"  {key}\n      {detail}")

    if result["failures"]:
        flush("\n失败样例:")
        for failure in result["failures"][:5]:
            flush(f"  {failure}")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="读取整机每个零件的材质名与外观颜色")
    parser.add_argument("--input", default=DEFAULT_ASM)
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个组件, 0 表示全量")
    parser.add_argument("--fresh", action="store_true", help="不续跑, 从零重新读全部零件")
    parser.add_argument(
        "--skip",
        default="",
        help="要跳过的零件路径片段, 逗号分隔; 用于绕开会让 SolidWorks 卡死的组件",
    )
    args = parser.parse_args()

    skip = tuple(s.strip() for s in args.skip.split(",") if s.strip())
    if skip:
        flush(f"将跳过含以下片段的零件: {skip}")

    session = SolidWorksSession()
    try:
        info = session.connect()
        flush(f"SolidWorks {info['revision']} 早期绑定={info['early_binding']}")
        result = collect(
            session, args.input, limit=args.limit, resume=not args.fresh, skip=skip
        )
    finally:
        session.release()   # 保持装配体打开, 后续还要用

    flush(f"\n已写出: {save(result)}")
    summarize(result)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
