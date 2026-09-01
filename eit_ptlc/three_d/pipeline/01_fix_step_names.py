"""
功能: 修复 SolidWorks 导出的 STEP 文件的命名问题, 让转换出的 GLB 带有可用的语义名称.

本步骤解决两个各自独立、但都会让后续管线失效的问题:

问题一 —— 中文名是裸 GBK 字节.
    SolidWorks 中文版把零件名以 cp936 字节直接写进字符串字面量, 而没有使用
    ISO-10303-21 规定的 \\X2\\....\\X0\\ Unicode 转义. OCCT/cascadio/FreeCAD 一律按
    UTF-8 或 Latin-1 解析, 结果是乱码.

问题二 —— 装配实例没有名字, 导致 GLB 节点全叫 NAUO1234.
    SolidWorks 写出的装配实例长这样(name 与 description 都是空白):
        #3301311 = NEXT_ASSEMBLY_USAGE_OCCURRENCE ( 'NAUO1', ' ', ' ', #440267, #1556346, $ ) ;
    OCCT 见 name 为空便退回使用 id 字段 'NAUO1' 给 glTF 节点命名, 于是整个模型
    2000 多个节点全无语义 —— 删减规则、材质规则、装配归属映射会同时失效.
    修复办法是顺着 STEP 的实体引用把真正的零件名取出来, 回填到 NAUO 的 name 字段:
        NAUO.related_product_definition
          -> PRODUCT_DEFINITION            (第 3 个参数指向 formation)
          -> PRODUCT_DEFINITION_FORMATION  (第 3 个参数指向 product)
          -> PRODUCT                       (第 1 个参数即零件名)

处理为两遍扫描: 第一遍只收集实体引用关系与零件名, 第二遍才改写并落盘.

用法:
    python 01_fix_step_names.py                       # 用配置里的 legacy_full_step
    python 01_fix_step_names.py --input X.STEP --output Y.STEP
    python 01_fix_step_names.py --mode escape         # 保留中文(转 \\X2\\ 转义)而非转拼音
    python 01_fix_step_names.py --no-propagate        # 不回填装配实例名(排查用)

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 STEP 文件 + names.csv + 报告 JSON)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import unicodedata

from common import ensure_dir, human_size, load_config, log, timed, write_report

# STEP 字符串字面量: 单引号包裹; 连续两个单引号表示字面量内的单引号
STRING_LITERAL = re.compile(rb"'((?:[^']|'')*)'")

# 只有这些实体行里的字符串才是"名称", 逐行做 in 判断远快于对每行跑正则
NAME_BEARING_TOKENS = (b"PRODUCT", b"NEXT_ASSEMBLY_USAGE_OCCURRENCE", b"FILE_NAME")

# -- 实体解析正则(用于建立引用关系) -----------------------------------------
# #123 = PRODUCT ( 'name', 'name', '', ( #ctx ) ) ;
RE_PRODUCT = re.compile(rb"^#(\d+)\s*=\s*PRODUCT\s*\(\s*'((?:[^']|'')*)'")
# #123 = PRODUCT_DEFINITION_FORMATION[_WITH_SPECIFIED_SOURCE] ( 'x', '', #product, ... ) ;
RE_FORMATION = re.compile(
    rb"^#(\d+)\s*=\s*PRODUCT_DEFINITION_FORMATION\w*\s*\(\s*'(?:[^']|'')*'\s*,\s*'(?:[^']|'')*'\s*,\s*#(\d+)"
)
# #123 = PRODUCT_DEFINITION ( 'x', '', #formation, #ctx ) ;
RE_DEFINITION = re.compile(
    rb"^#(\d+)\s*=\s*PRODUCT_DEFINITION\s*\(\s*'(?:[^']|'')*'\s*,\s*'(?:[^']|'')*'\s*,\s*#(\d+)"
)
# #123 = NEXT_ASSEMBLY_USAGE_OCCURRENCE ( 'id', 'name', 'desc', #relating, #related, $ ) ;
RE_NAUO = re.compile(
    rb"^(#\d+\s*=\s*NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*)"
    rb"('(?:[^']|'')*')(\s*,\s*)"          # 第 1 组: id
    rb"('(?:[^']|'')*')(\s*,\s*)"          # 第 2 组: name  <- 要回填的就是它
    rb"('(?:[^']|'')*')(\s*,\s*)"          # 第 3 组: description
    rb"#(\d+)(\s*,\s*)"                    # relating(父)
    rb"#(\d+)"                             # related(子) <- 顺着它去查零件名
)

# 供应商目录件被 OCCT 自动命名; 这类名字保持原样, 它是后续删减规则的锚点
VENDOR_AUTO_NAME = "Open CASCADE STEP translator"


def _lazy_pinyin():
    """
    功能: 惰性导入 pypinyin, 未安装时返回 None 以便回退到码点方案.
    参数: 无
    返回值: callable | None
    """
    try:
        from pypinyin import Style, lazy_pinyin

        return lambda text: lazy_pinyin(text, style=Style.NORMAL)
    except ImportError:
        return None


_PINYIN = _lazy_pinyin()


def slugify(name: str, max_len: int = 48) -> str:
    """
    功能: 把可能含中文的名称转成 ASCII slug, 尽量保留可读语义.

    中文转拼音, 英文数字原样保留, 其余符号折叠为下划线.
    之所以不直接保留中文: OCCT 的 C++ 层在 Windows 上按 ANSI 代码页处理字符串与路径,
    中文会在转换链的某一环变成乱码或直接报错; 拼音让整条工具链无需处理编码问题,
    真正的中文名保存在 names.csv 里, 供界面标签与人工查阅使用.

    参数:
        name: 原始名称(已正确解码的 Unicode 字符串)
        max_len: 结果最大长度
    返回值: str, ASCII slug; 无可用字符时返回 "unnamed"
    """
    if not name:
        return "unnamed"

    pieces: list[str] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        """功能: 把缓冲区里的非中文字符成段输出. 参数: 无. 返回值: None"""
        if buffer:
            pieces.append("".join(buffer))
            buffer.clear()

    for char in name:
        if "一" <= char <= "鿿":  # CJK 统一汉字
            flush_buffer()
            if _PINYIN is not None:
                pieces.extend(_PINYIN(char))
            else:
                pieces.append(f"u{ord(char):04x}")
        else:
            buffer.append(char)
    flush_buffer()

    raw = "_".join(p for p in pieces if p)
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^A-Za-z0-9_.\-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_.")

    if not raw:
        return "unnamed"
    return raw[:max_len].rstrip("_.")


def to_step_escape(name: str) -> str:
    """
    功能: 把含非 ASCII 的名称编码成 ISO-10303-21 的 \\X2\\ Unicode 转义形式.
    参数:
        name: 原始名称
    返回值: str, 纯 ASCII 的 STEP 字符串内容
    """
    out: list[str] = []
    pending: list[str] = []

    def flush_pending() -> None:
        """功能: 输出累积的非 ASCII 字符为一段转义. 参数: 无. 返回值: None"""
        if pending:
            out.append("\\X2\\" + "".join(f"{ord(c):04X}" for c in pending) + "\\X0\\")
            pending.clear()

    for char in name:
        if ord(char) < 128:
            flush_pending()
            out.append(char)
        else:
            pending.append(char)
    flush_pending()
    return "".join(out)


class NameFixer:
    """功能: 承载名称改写过程的状态 —— 解码、slug 去重、映射表累积."""

    def __init__(self, encoding: str = "cp936", mode: str = "slug", max_slug_len: int = 48):
        """
        功能: 初始化.
        参数:
            encoding: 源文件中名称的真实编码
            mode: "slug"(转拼音) 或 "escape"(转 Unicode 转义)
            max_slug_len: slug 最大长度
        返回值: None
        """
        self.encoding = encoding
        self.mode = mode
        self.max_slug_len = max_slug_len
        self.byte_cache: dict[bytes, bytes] = {}
        self.mapping: dict[str, str] = {}
        self.used_slugs: set[str] = set()
        self.decode_failures = 0

    def decode(self, raw: bytes) -> str:
        """
        功能: 把字面量字节解码成 Unicode 文本.
        参数:
            raw: 原始字节
        返回值: str, 解码后的文本
        """
        try:
            return raw.decode("ascii")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode(self.encoding)
        except UnicodeDecodeError:
            self.decode_failures += 1
            return raw.decode(self.encoding, errors="replace")

    def _unique_slug(self, base: str) -> str:
        """
        功能: 保证 slug 全局唯一(冲突时追加序号).
        参数:
            base: 候选 slug
        返回值: str, 唯一 slug
        """
        if base not in self.used_slugs:
            self.used_slugs.add(base)
            return base
        index = 2
        while f"{base}_{index}" in self.used_slugs:
            index += 1
        unique = f"{base}_{index}"
        self.used_slugs.add(unique)
        return unique

    def portable_name(self, raw: bytes) -> bytes:
        """
        功能: 把一个名称字节串改写成可移植形式(纯 ASCII 内容原样返回).
        参数:
            raw: 字面量内部的原始字节
        返回值: bytes, 改写后的字节
        """
        if raw in self.byte_cache:
            return self.byte_cache[raw]

        try:
            raw.decode("ascii")
            self.byte_cache[raw] = raw
            return raw
        except UnicodeDecodeError:
            pass

        text = self.decode(raw)
        if self.mode == "escape":
            converted = to_step_escape(text).encode("ascii", errors="replace")
        else:
            slug = self._unique_slug(slugify(text, self.max_slug_len))
            self.mapping[slug] = text
            converted = slug.encode("ascii")

        self.byte_cache[raw] = converted
        return converted

    def fix_literals(self, line: bytes) -> bytes:
        """
        功能: 改写一行中所有含非 ASCII 的字符串字面量.
        参数:
            line: 原始行字节
        返回值: bytes, 改写后的行
        """
        return STRING_LITERAL.sub(lambda m: b"'" + self.portable_name(m.group(1)) + b"'", line)


class ProductGraph:
    """
    功能: STEP 装配引用图 —— 用于把零件名沿引用链传播到装配实例上.

    只保存 PRODUCT / PRODUCT_DEFINITION_FORMATION / PRODUCT_DEFINITION 三类实体的
    引用关系, 内存占用与零件数(而非文件大小)成正比, 因此几百 MB 的文件也不成问题.
    """

    def __init__(self):
        """功能: 初始化空图. 参数: 无. 返回值: None"""
        self.product_name: dict[int, bytes] = {}      # product 实体 id -> 名称字节
        self.formation_to_product: dict[int, int] = {}
        self.definition_to_formation: dict[int, int] = {}

    def observe(self, line: bytes) -> None:
        """
        功能: 从一行中提取引用关系(若该行属于关注的实体类型).
        参数:
            line: 原始行字节
        返回值: None
        """
        match = RE_PRODUCT.match(line)
        if match:
            self.product_name[int(match.group(1))] = match.group(2)
            return

        match = RE_FORMATION.match(line)
        if match:
            self.formation_to_product[int(match.group(1))] = int(match.group(2))
            return

        match = RE_DEFINITION.match(line)
        if match:
            self.definition_to_formation[int(match.group(1))] = int(match.group(2))

    def name_for_definition(self, definition_id: int) -> bytes | None:
        """
        功能: 顺着 定义 -> 版本 -> 零件 的引用链取出零件名.
        参数:
            definition_id: PRODUCT_DEFINITION 的实体 id
        返回值: bytes | None, 零件名字节; 链路断裂时返回 None
        """
        formation_id = self.definition_to_formation.get(definition_id)
        if formation_id is None:
            return None
        product_id = self.formation_to_product.get(formation_id)
        if product_id is None:
            return None
        return self.product_name.get(product_id)

    def summary(self) -> dict:
        """功能: 返回图的规模摘要. 参数: 无. 返回值: dict"""
        return {
            "products": len(self.product_name),
            "formations": len(self.formation_to_product),
            "definitions": len(self.definition_to_formation),
        }


def collect_graph(input_path: str) -> ProductGraph:
    """
    功能: 第一遍扫描 —— 建立装配引用图.
    参数:
        input_path: 源 STEP 路径
    返回值: ProductGraph
    """
    graph = ProductGraph()
    with open(input_path, "rb") as handle:
        for line in handle:
            # 三类目标实体名字里都含 PRODUCT, 先做一次廉价筛选
            if b"PRODUCT" in line:
                graph.observe(line)
    return graph


def fix_step_file(
    input_path: str,
    output_path: str,
    encoding: str = "cp936",
    mode: str = "slug",
    max_slug_len: int = 48,
    propagate: bool = True,
) -> dict:
    """
    功能: 对整个 STEP 文件执行名称修复与装配实例名回填(流式处理, 支持数百 MB 文件).
    参数:
        input_path: 源 STEP 路径
        output_path: 目标 STEP 路径
        encoding: 源名称编码
        mode: "slug" 或 "escape"
        max_slug_len: slug 最大长度
        propagate: 是否把零件名回填到装配实例的 name 字段
    返回值: dict, 统计报告(含 mapping)
    """
    fixer = NameFixer(encoding=encoding, mode=mode, max_slug_len=max_slug_len)
    ensure_dir(output_path)

    graph = ProductGraph()
    if propagate:
        with timed("第一遍: 建立装配引用图"):
            graph = collect_graph(input_path)
        log(f"  引用图规模: {graph.summary()}")

    total_lines = 0
    touched_lines = 0
    nauo_renamed = 0
    nauo_unresolved = 0

    def rewrite_nauo(match: re.Match[bytes]) -> bytes:
        """
        功能: 把装配实例的 name 字段替换为其所引用零件的名称.
        参数:
            match: RE_NAUO 的匹配对象
        返回值: bytes, 改写后的实体行片段
        """
        nonlocal nauo_renamed, nauo_unresolved
        related_id = int(match.group(10))
        raw_name = graph.name_for_definition(related_id)
        if raw_name is None:
            nauo_unresolved += 1
            return match.group(0)

        nauo_renamed += 1
        portable = fixer.portable_name(raw_name)
        # 保留 id / description 与两个引用不动, 只替换第 2 个参数(name)
        return (
            match.group(1)
            + match.group(2)
            + match.group(3)
            + b"'"
            + portable
            + b"'"
            + match.group(5)
            + match.group(6)
            + match.group(7)
            + b"#"
            + match.group(8)
            + match.group(9)
            + b"#"
            + match.group(10)
        )

    with timed("第二遍: 改写名称并落盘"):
        with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
            for line in fin:
                total_lines += 1
                original = line

                if propagate and b"NEXT_ASSEMBLY_USAGE_OCCURRENCE" in line:
                    line = RE_NAUO.sub(rewrite_nauo, line, count=1)

                if any(token in line for token in NAME_BEARING_TOKENS):
                    line = fixer.fix_literals(line)

                if line != original:
                    touched_lines += 1
                fout.write(line)

                if total_lines % 1_000_000 == 0:
                    log(f"  已处理 {total_lines:,} 行 …")

    return {
        "input": input_path,
        "output": output_path,
        "input_size": human_size(os.path.getsize(input_path)),
        "output_size": human_size(os.path.getsize(output_path)),
        "mode": mode,
        "encoding": encoding,
        "propagate_product_names": propagate,
        "graph": graph.summary(),
        "total_lines": total_lines,
        "touched_lines": touched_lines,
        "nauo_renamed": nauo_renamed,
        "nauo_unresolved": nauo_unresolved,
        "unique_names_converted": len(fixer.mapping),
        "decode_failures": fixer.decode_failures,
        "mapping": fixer.mapping,
    }


def write_names_csv(path: str, mapping: dict[str, str]) -> str:
    """
    功能: 导出 slug -> 中文原名 映射表, 供 rig_map 编写与界面标签使用.
    参数:
        path: 输出 CSV 路径
        mapping: slug 到中文名的字典
    返回值: str, 输出路径
    """
    ensure_dir(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["slug", "original_name", "is_vendor_auto"])
        for slug in sorted(mapping):
            writer.writerow([slug, mapping[slug], int(VENDOR_AUTO_NAME in mapping[slug])])
    log(f"名称映射表已写入: {path} ({len(mapping)} 条)")
    return path


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    defaults = config.get("step_names", {})

    parser = argparse.ArgumentParser(description="修复 STEP 名称编码并回填装配实例名")
    parser.add_argument("--input", default=config["sources"]["legacy_full_step"])
    parser.add_argument("--output", default=None, help="默认写入 work/<ascii名>_named.STEP")
    parser.add_argument("--mode", default=defaults.get("mode", "slug"), choices=["slug", "escape"])
    parser.add_argument("--encoding", default=defaults.get("source_encoding", "cp936"))
    parser.add_argument("--max-slug-len", type=int, default=defaults.get("max_slug_len", 48))
    parser.add_argument("--no-propagate", action="store_true", help="不回填装配实例名")
    parser.add_argument("--names-csv", default=None, help="名称映射表输出路径")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(f"错误: 输入文件不存在: {args.input}")

    work_dir = config["paths"]["work"]
    # 中间产物一律使用纯 ASCII 文件名: OCCT 的 C++ 层在 Windows 上按 ANSI 代码页解析路径,
    # 含中文的路径会直接报 "Cannot open input file".
    stem = slugify(os.path.splitext(os.path.basename(args.input))[0])
    output = args.output or os.path.join(work_dir, f"{stem}_named.STEP")

    log(f"源文件: {args.input} ({human_size(os.path.getsize(args.input))})")
    log(f"模式: {args.mode}; 源编码: {args.encoding}; 回填装配实例名: {not args.no_propagate}")

    report = fix_step_file(
        args.input,
        output,
        encoding=args.encoding,
        mode=args.mode,
        max_slug_len=args.max_slug_len,
        propagate=not args.no_propagate,
    )

    mapping = report.pop("mapping")
    if mapping:
        csv_path = args.names_csv or os.path.join(work_dir, f"{stem}_names.csv")
        report["names_csv"] = write_names_csv(csv_path, mapping)
        report["vendor_auto_named"] = sum(1 for v in mapping.values() if VENDOR_AUTO_NAME in v)

    write_report(os.path.join(work_dir, f"{stem}_01_fix_step_names.report.json"), report)
    log(
        f"输出: {report['output']} ({report['output_size']}); "
        f"装配实例回填 {report['nauo_renamed']} 个, 未解析 {report['nauo_unresolved']} 个"
    )


if __name__ == "__main__":
    main()
