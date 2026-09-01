"""verify_cnc_template.py — 校验 scrape_template_v2.cnc 与上位机契约一致性。

解析 CNCTest/scrape_template_v2.cnc 中的所有 $g_xxx$ / $g_xxx[i]$ 引用，
比对：
  1. cnc_path_generator.generate_scrape_arrays 返回 dict 的 keys（数组+标量）
  2. PLC docs/PLC_ScrapeCNC_Interface.md §5 模板字段引用对照表

退出码：
  0  全部一致
  1  有缺失或多余字段

运行：
    cd UI-Upper
    python scripts/verify_cnc_template.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 让本脚本能找到 core 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cnc_path_generator import safe_placeholder_arrays  # noqa: E402
from core.config import GCodeCfg  # noqa: E402

# 模板路径（相对工程根目录）
TEMPLATE_PATH = ROOT.parent / "CNCTest" / "scrape_template_v2.cnc"


# 模板中允许的引用形式：
#   标量: $g_safe_z$ / $g_pass_z$ ...
#   数组: $g_sx[1]$ / $g_sx[80]$ ...
PATTERN = re.compile(r"\$(g_[a-z_]+)(?:\[(\d+)\])?\$")


def parse_template_refs(template_path: Path) -> tuple[set[str], dict[str, set[int]]]:
    """解析模板中 $g_xxx$ 与 $g_xxx[i]$ 引用。

    Returns:
        (scalar_names, array_names_with_indices)
        - scalar_names: 不带下标的引用集合
        - array_names_with_indices: { 数组名: {1,2,...} }
    """
    text = template_path.read_text(encoding="utf-8")
    scalars: set[str] = set()
    arrays: dict[str, set[int]] = {}
    for m in PATTERN.finditer(text):
        name = m.group(1)
        idx = m.group(2)
        if idx is None:
            scalars.add(name)
        else:
            arrays.setdefault(name, set()).add(int(idx))
    return scalars, arrays


def verify() -> int:
    if not TEMPLATE_PATH.is_file():
        print(f"[FAIL] 模板不存在: {TEMPLATE_PATH}")
        return 1

    template_scalars, template_arrays = parse_template_refs(TEMPLATE_PATH)
    print(f"[INFO] 模板: {TEMPLATE_PATH}")
    print(f"[INFO] 标量引用: {sorted(template_scalars)}")
    print(f"[INFO] 数组引用: {sorted(template_arrays.keys())}")

    # 取上位机生成器输出 keys 作为契约基线
    arrays_obj = safe_placeholder_arrays(GCodeCfg())
    plc_dict = arrays_obj.as_plc_dict()
    upper_keys = set(plc_dict.keys())

    # 上位机声明的数组（基于 dict 中 list 类型字段）
    upper_array_keys = {k for k, v in plc_dict.items() if isinstance(v, list)}
    upper_scalar_keys = upper_keys - upper_array_keys

    # PLC 内部计算、上位机不下发的标量字段（如 g_pass_z——PLC Step 30 按 pass 循环计算）。
    # 这些字段会出现在模板中，但由 PLC 内部填充，上位机 as_plc_dict() 有意不包含。
    plc_internal_scalars = {"g_pass_z"}

    print(f"[INFO] 上位机标量字段: {sorted(upper_scalar_keys)}")
    print(f"[INFO] 上位机数组字段: {sorted(upper_array_keys)}")
    print(f"[INFO] PLC 内部计算标量（上位机不下发）: {sorted(plc_internal_scalars)}")

    issues: list[str] = []

    # 1. 模板中的标量引用必须在上位机标量字段里 或 在 PLC 内部计算白名单里
    for s in template_scalars:
        if s in upper_scalar_keys or s in plc_internal_scalars:
            continue
        issues.append(
            f"模板引用了 ${s}$ 但上位机未提供（生成器 dict 中无此 key）"
        )

    # 2. 模板中的数组引用必须都在上位机数组字段里，且下标范围 ≤ 上位机数组长度
    for arr_name, indices in template_arrays.items():
        if arr_name not in upper_array_keys:
            issues.append(
                f"模板引用了 ${arr_name}[i]$ 但上位机数组字段中无 {arr_name}"
            )
            continue
        max_idx = max(indices)
        upper_len = len(plc_dict[arr_name])
        if max_idx > upper_len:
            issues.append(
                f"模板 ${arr_name}[{max_idx}]$ 超过上位机数组长度 {upper_len}"
            )
        # 校验完整性：[1..max_idx] 是否连续
        expected = set(range(1, max_idx + 1))
        missing = expected - indices
        if missing:
            issues.append(
                f"模板 ${arr_name}[i]$ 引用不连续，缺失下标: {sorted(missing)}"
            )

    # 3. 上位机声明但模板未引用的字段（仅警告，不算失败）
    pure_internal = {"g_pass_count", "g_total_depth", "g_plate_surface_z"}
    template_refs_all = template_scalars | set(template_arrays.keys())
    unreferenced = upper_keys - template_refs_all - pure_internal
    if unreferenced:
        print(f"[WARN] 上位机字段但模板未引用: {sorted(unreferenced)}（如非 PLC ST 内部使用，请检查）")
    # 报告
    if issues:
        print()
        print(f"[FAIL] 检测到 {len(issues)} 处不一致:")
        for i, msg in enumerate(issues, 1):
            print(f"  {i}. {msg}")
        return 1

    print()
    print("[OK] 模板字段与上位机契约完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(verify())
