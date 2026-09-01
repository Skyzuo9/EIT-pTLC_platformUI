#!/usr/bin/env python3
"""补充点 offset 缺失防御性校验离线测试
==========================================
功能:
    当补充点记录声明了 base_point 却漏写 offset 时,
    PointRegistry._build_supplemental 应抛出本函数统一的描述性
    ValueError (消息含 point_id), 而非裸 KeyError: 'offset',
    以避免实时启动路径 (runtime/bootstrap.py) 无提示中止。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.point_registry import PointRegistry, RobotPoint  # noqa: E402


def _make_source_point() -> RobotPoint:
    return RobotPoint(
        point_id="src.base",
        source_id="src.base",
        robot_name="BASE",
        alias="base",
        workstation="ws-a",
        role="taught",
        pose=(1.0, 2.0, 3.0, 0.0, 0.0, 0.0),
        joint=None,
        user=0,
        tool=0,
        acc=50,
        vel=50,
        cp=0,
        allowed_motion=("ptp",),
        status="validated",
        source_file="point.json",
        source_version="v0.11",
        source_sha256="0" * 64,
    )


class SupplementOffsetMissingTests(unittest.TestCase):
    def test_base_point_without_offset_raises_valueerror(self) -> None:
        record = {
            "point_id": "supp.no_offset",
            "workstation": "ws-a",
            "role": "derived",
            "base_point": "BASE",
            # 故意省略 offset
        }
        with self.assertRaises(ValueError) as ctx:
            PointRegistry._build_supplemental(
                [record],
                [_make_source_point()],
                meta_source_version="v0.11",
                meta_path=Path("meta.json"),
                meta_checksum="0" * 64,
            )
        msg = str(ctx.exception)
        self.assertIn("supp.no_offset", msg, "ValueError 消息应包含 point_id 标识")
        self.assertIn("offset", msg)

    def test_base_point_without_offset_not_keyerror(self) -> None:
        record = {
            "point_id": "supp.no_offset",
            "workstation": "ws-a",
            "role": "derived",
            "base_point": "BASE",
        }
        try:
            PointRegistry._build_supplemental(
                [record],
                [_make_source_point()],
                meta_source_version="v0.11",
                meta_path=Path("meta.json"),
                meta_checksum="0" * 64,
            )
        except KeyError:  # pragma: no cover - 回归断言
            self.fail("不应抛出裸 KeyError: 'offset'")
        except ValueError:
            pass


if __name__ == "__main__":
    unittest.main()
