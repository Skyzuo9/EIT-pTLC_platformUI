"""装配台标红基线(work/prune_preview.json)的离线契约测试.

守的是一条只会静默出错的通路: 装配台拿当前 prune_list.yaml 的戳与基线里记的戳比对,
不一致才挂"预览为近似"的告警。两边算法一漂, 戳就要么永远对不上、要么永远对得上 ——
前者是一条修不掉的噪声, 后者等于把"预览悄悄骗人"这件事重新放回来。

所以这里把几个具体值钉死, 与 web/tests/three-d/pruneEval.test.js 里
「sourceStamp 与管线 03_clean_model.source_stamp 逐位一致」那条互为镜像:
任何一侧改了算法, 两边测试必有一边红。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PIPELINE = Path(__file__).resolve().parents[1] / "three_d" / "pipeline"


@pytest.fixture(scope="module")
def clean03():
    """
    功能:
        加载 03_clean_model.py.

    模块名以数字开头, import 语句写不出来, 只能走 importlib 按路径加载;
    它自身 `from common import ...`, 所以 pipeline 目录要先进 sys.path.

    返回:
        已执行的模块对象.
    """
    # 用完就把 sys.path 收回去: pipeline 目录里有 common.py 这种大众名字, 常驻在
    # 搜索路径最前面会悄悄遮蔽后续测试要 import 的同名模块, 排查起来极费劲
    added = str(_PIPELINE) not in sys.path
    if added:
        sys.path.insert(0, str(_PIPELINE))
    try:
        spec = importlib.util.spec_from_file_location("clean03", _PIPELINE / "03_clean_model.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        if added and str(_PIPELINE) in sys.path:
            sys.path.remove(str(_PIPELINE))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "0:811c9dc5"),
        ("min_dimension_mm: 6.0\n", "22:cf2b3c63"),
        # 含中文: 长度前缀按 UTF-8 字节数(44)而非字符数(38)
        ("keep_patterns:\n  - san_se_deng  # 三色灯\n", "44:ca596eb1"),
    ],
)
def test_source_stamp_matches_browser_side(clean03, text: str, expected: str) -> None:
    assert clean03.source_stamp(text) == expected


def test_source_stamp_changes_with_content(clean03) -> None:
    """内容一变戳必变 —— 否则规则改了页面也不会告警, 又回到静默骗人."""
    assert clean03.source_stamp("min_dimension_mm: 6.0\n") != clean03.source_stamp(
        "min_dimension_mm: 8.0\n"
    )
