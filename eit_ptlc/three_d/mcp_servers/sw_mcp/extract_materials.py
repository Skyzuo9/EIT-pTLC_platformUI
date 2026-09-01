"""
功能: 从 SolidWorks 装配体里提取每个零件的**真实材质与外观**, 导出成映射表,
      供三维管线用真实材质替代按名称猜测的规则.

为什么值得做: 现在管线里的材质是靠零件名正则猜的("名字里带 bo_li 就当玻璃"),
猜错的地方只能靠肉眼发现. 而 SolidWorks 里每个零件本来就带着设计者指定的
材质名(6061 铝合金 / 304 不锈钢 / 亚克力…)与外观颜色 —— 那才是权威来源.

提取两类信息, 用途不同:
  材质名 (GetMaterialPropertyName2) —— 语义, 决定该用哪种 PBR 参数(金属?玻璃?塑料?)
  外观色 (GetMaterialPropertyValues2) —— 设计者的配色意图, 含 RGB 与透明度

产出 materials_from_cad.json: 零件名 -> {material, rgb, transparency, count},
再由 build_materials_yaml.py 转成管线用的 materials.yaml.

用法:
    python extract_materials.py --input <装配体.SLDASM>
    python extract_materials.py --input <...> --depth 3    # 递归更深
    python extract_materials.py --dry-run                  # 只连不读, 验证环境

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 JSON)
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

import pythoncom

from sw_core import SolidWorksSession, _prop, _wrap

# GetMaterialPropertyValues2 返回 9 个 double, 含义见 SolidWorks API 文档
IDX_R, IDX_G, IDX_B = 0, 1, 2
IDX_AMBIENT, IDX_DIFFUSE, IDX_SPECULAR = 3, 4, 5
IDX_SHININESS, IDX_TRANSPARENCY, IDX_EMISSION = 6, 7, 8

# swInConfigurationOpts_e.swThisConfiguration
CONFIG_THIS = 1

# 读取失败计数. "读失败"与"零件确实没指定材质"在结果里长得一模一样,
# 不单独记的话会得出"CAD 里根本没有材质"这种错误结论 —— 那正是第一次跑时踩的坑.
_FAILURES: dict = {}


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """
    功能: 把 0~1 的 RGB 转成 #RRGGBB.
    参数:
        r/g/b: 0~1 的分量
    返回值: str
    """
    to255 = lambda v: max(0, min(255, int(round(v * 255))))  # noqa: E731
    return f"#{to255(r):02X}{to255(g):02X}{to255(b):02X}"


def read_component_appearance(component) -> dict | None:
    """
    功能: 读取一个组件的外观(颜色/透明度/高光).

    注意 SolidWorks 的外观是有继承的: 零件没单独设外观时, 这里读到的是它从装配体或
    材质继承来的值. 这正是我们要的 —— 最终显示成什么样.

    参数:
        component: Component2 COM 对象
    返回值: dict | None, 读取失败返回 None
    """
    try:
        values = _prop(component, "GetMaterialPropertyValues2", CONFIG_THIS, "")
    except Exception as exc:  # noqa: BLE001 - COM 调用失败不应打断整棵树的遍历
        _FAILURES["appearance"] = _FAILURES.get("appearance", 0) + 1
        _FAILURES.setdefault("appearance_reason", f"{type(exc).__name__}: {str(exc)[:90]}")
        return None
    if not values or len(values) < 9:
        return None
    # 未设置外观时 SolidWorks 返回全 -1
    if values[IDX_R] < 0:
        return None
    return {
        "hex": rgb_to_hex(values[IDX_R], values[IDX_G], values[IDX_B]),
        "rgb": [round(values[i], 4) for i in (IDX_R, IDX_G, IDX_B)],
        "ambient": round(values[IDX_AMBIENT], 3),
        "diffuse": round(values[IDX_DIFFUSE], 3),
        "specular": round(values[IDX_SPECULAR], 3),
        "shininess": round(values[IDX_SHININESS], 3),
        "transparency": round(values[IDX_TRANSPARENCY], 3),
        "emission": round(values[IDX_EMISSION], 3),
    }


def read_component_material(component) -> tuple[str, str]:
    """
    功能: 读取一个组件的材质名与材质库名.

    GetMaterialPropertyName2 的第二个参数是 [out] 的材质库名, 早期绑定下会以元组回传,
    后期绑定下要自备 VARIANT —— 两种都兜住.

    参数:
        component: Component2 COM 对象
    返回值: tuple[str, str], (材质名, 材质库); 读不到时返回 ("", "")
    """
    try:
        result = _prop(component, "GetMaterialPropertyName2", "", "")
        if isinstance(result, (tuple, list)):
            name = str(result[0] or "")
            database = str(result[1] or "") if len(result) > 1 else ""
            return (name, database)
        return (str(result or ""), "")
    except Exception as exc:  # noqa: BLE001 - 单个组件读失败不该打断整棵树
        # 但要记下来: 全部读失败与"零件确实没指定材质"在结果上一模一样,
        # 不区分的话会得出"CAD 里没有材质"这种错误结论
        _FAILURES["material"] = _FAILURES.get("material", 0) + 1
        _FAILURES.setdefault("material_reason", f"{type(exc).__name__}: {str(exc)[:90]}")
        return ("", "")


def walk_components(session: SolidWorksSession, doc_path: str, max_depth: int) -> list[dict]:
    """
    功能: 递归遍历装配体, 收集每个组件的材质与外观.
    参数:
        session: SolidWorks 会话
        doc_path: 装配体路径
        max_depth: 递归深度
    返回值: list[dict], 每项含 name/path/depth/material/appearance
    """
    model = session._find_open_model(doc_path)
    if model is None:
        raise RuntimeError(f"文档未打开: {doc_path}")

    # 这三层都必须显式转成具体接口, 否则方法在后期绑定下"找不到成员".
    # 打印实际类型: COM 绑定问题排查起来极费时, 有这一行就能立刻看出是哪一层没包上
    model = _wrap(model, "IModelDoc2")
    print(f"  文档接口: {type(model).__name__}")

    config = _wrap(_prop(model, "GetActiveConfiguration"), "IConfiguration")
    print(f"  配置接口: {type(config).__name__}")

    root = _wrap(_prop(config, "GetRootComponent3", True), "IComponent2")
    print(f"  根组件接口: {type(root).__name__}")

    results: list[dict] = []
    visited: set[str] = set()

    def visit(component, depth: int) -> None:
        """功能: 递归访问组件. 参数: 组件与深度. 返回值: None"""
        children = _prop(component, "GetChildren")
        if not children:
            return
        for raw in children:
            child = _wrap(raw, "IComponent2")
            try:
                name = child.Name2
                path = _prop(child, "GetPathName") or ""
            except Exception:  # noqa: BLE001
                continue

            material, database = read_component_material(child)
            appearance = read_component_appearance(child)

            results.append(
                {
                    "name": name,
                    "file": os.path.basename(path),
                    "path": path,
                    "depth": depth,
                    "is_assembly": path.lower().endswith(".sldasm"),
                    "material": material,
                    "material_db": database,
                    "appearance": appearance,
                }
            )

            # 同一个零件文件被引用多次时只递归一次, 否则大装配会指数级膨胀
            key = f"{path}#{depth}"
            if depth < max_depth and key not in visited:
                visited.add(key)
                visit(child, depth + 1)

    visit(root, 1)
    return results


def summarize(components: list[dict]) -> dict:
    """
    功能: 汇总有哪些不同的材质与外观, 各覆盖多少零件.

    这是回答"SolidWorks 里到底有哪些材质区别"的那份报告.

    参数:
        components: walk_components 的产出
    返回值: dict, 汇总结果
    """
    materials = Counter()
    colors = Counter()
    material_colors: dict[str, Counter] = {}
    no_material = 0
    no_appearance = 0

    for item in components:
        material = item["material"].strip()
        if material:
            materials[material] += 1
        else:
            no_material += 1

        appearance = item.get("appearance")
        if appearance:
            colors[appearance["hex"]] += 1
            material_colors.setdefault(material or "(未指定材质)", Counter())[
                appearance["hex"]
            ] += 1
        else:
            no_appearance += 1

    return {
        "total_components": len(components),
        "distinct_materials": len(materials),
        "distinct_colors": len(colors),
        "without_material": no_material,
        "without_appearance": no_appearance,
        "materials": [
            {"name": name, "count": count} for name, count in materials.most_common()
        ],
        "colors": [{"hex": hex_, "count": count} for hex_, count in colors.most_common()],
        "material_to_colors": {
            material: [{"hex": h, "count": c} for h, c in counter.most_common()]
            for material, counter in material_colors.items()
        },
    }


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    default_asm = r"E:\eit_lab\eit_lab_hardware\eit_ptlc_station\TLC设备总装.SLDASM"
    out_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "work")
    )

    parser = argparse.ArgumentParser(description="从 SolidWorks 提取真实材质与外观")
    parser.add_argument("--input", default=default_asm)
    parser.add_argument("--depth", type=int, default=2, help="递归深度(1=只看顶层)")
    parser.add_argument("--output", default=os.path.join(out_dir, "materials_from_cad.json"))
    parser.add_argument("--dry-run", action="store_true", help="只连接不读取, 验证环境")
    parser.add_argument("--keep-open", action="store_true", help="读完保持文档打开")
    args = parser.parse_args()

    session = SolidWorksSession()
    try:
        info = session.connect()
        print(f"SolidWorks {info['revision']}  已开文档 {info['open_documents']} 个")
        if args.dry_run:
            print("--dry-run: 连接正常, 未做任何读取")
            return

        print(f"打开装配体(只读): {args.input}")
        opened = session.open_document(args.input)
        if opened["reused"]:
            print("  复用已打开的文档")
        else:
            print(f"  加载耗时 {opened['elapsed_s']}s")

        print(f"遍历组件树(深度 {args.depth})…")
        components = walk_components(session, args.input, args.depth)
        print(f"  收集到 {len(components)} 个组件")

        if not args.keep_open:
            session.close_document(args.input)
    finally:
        # 刻意不在出错时关文档: 这个总装加载要好几分钟, 调试期反复重开代价太大.
        # --keep-open 时连成功路径也保留, 便于连续多次读取.
        if not args.keep_open:
            session.close_all_opened()
        session.release()

    summary = summarize(components)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "components": components}, handle,
                  ensure_ascii=False, indent=2)

    print("\n=== SolidWorks 里的材质区别 ===")
    print(f"组件 {summary['total_components']} 个 · "
          f"不同材质 {summary['distinct_materials']} 种 · "
          f"不同颜色 {summary['distinct_colors']} 种")
    print(f"未指定材质 {summary['without_material']} 个 · "
          f"未指定外观 {summary['without_appearance']} 个")

    if _FAILURES.get("material") or _FAILURES.get("appearance"):
        print("\n⚠ 读取失败(不是'没有材质', 是根本没读到):")
        if _FAILURES.get("material"):
            print(f"  材质名读取失败 {_FAILURES['material']} 次: {_FAILURES.get('material_reason')}")
        if _FAILURES.get("appearance"):
            print(f"  外观读取失败 {_FAILURES['appearance']} 次: {_FAILURES.get('appearance_reason')}")

    print(f"\n材质分布:")
    for item in summary["materials"][:30]:
        print(f"  {item['count']:>5}  {item['name']}")

    print(f"\n颜色分布(前 20):")
    for item in summary["colors"][:20]:
        print(f"  {item['count']:>5}  {item['hex']}")

    print(f"\n已写入: {args.output}")


if __name__ == "__main__":
    main()
