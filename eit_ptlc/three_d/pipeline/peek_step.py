"""
功能: 从超大 STEP 文件中抽样打印指定实体类型的原始行, 用于确认其书写格式.
用法: python peek_step.py <step> --entity NEXT_ASSEMBLY_USAGE_OCCURRENCE --count 5
参数: 见 argparse
返回值: 无(打印样例)
"""

from __future__ import annotations

import argparse


def main() -> None:
    """功能: 命令行入口. 参数: 无. 返回值: None"""
    parser = argparse.ArgumentParser(description="抽样查看 STEP 实体行")
    parser.add_argument("path")
    parser.add_argument("--entity", action="append", required=True, help="实体类型名, 可重复")
    parser.add_argument("--count", type=int, default=4, help="每种实体打印几行")
    args = parser.parse_args()

    wanted = {name.upper().encode(): 0 for name in args.entity}
    remaining = len(wanted) * args.count

    with open(args.path, "rb") as handle:
        for line in handle:
            if remaining <= 0:
                break
            for token, seen in list(wanted.items()):
                if seen >= args.count:
                    continue
                if token in line:
                    print(f"--- {token.decode()} #{seen + 1} ---")
                    # 用 latin-1 解码保证任何字节都能打印出来, 便于观察编码问题
                    print(line.decode("latin-1").rstrip())
                    wanted[token] = seen + 1
                    remaining -= 1
                    break


if __name__ == "__main__":
    main()
