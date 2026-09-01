"""孔位三态 (ABSENT) 离线测试
============================
背景 (2026-08-15 用户定案):
    粉桶在三维里要有三种表现 —— 在位·新的(直立) / 在位·已用(倒扣) / 不在位(不画),
    对应账本把孔位从二态扩为三态。本文件钉住四件事:
      ① mark/mark_plate 接受 ABSENT, 且内容物随"件被拿走"一并清零;
      ② 旧库(带二态 state CHECK)开库即被原地重建放行三态, 数据逐行保留;
      ③ ABSENT 不计入 summary 的任何余量统计 (与无板库位的孔同理);
      ④ 流程选料 (next_fresh) 只认 FRESH, ABSENT 天然不可选。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_material_absent_state_offline.py -q
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from eit_ptlc.runtime.material_store import (
    STATE_ABSENT,
    STATE_FRESH,
    STATE_USED,
    MaterialStore,
    load_topology,
)

_TOPOLOGY_FILE = Path(__file__).resolve().parent.parent / "config" / "material_topology.yaml"


def _store(path=":memory:") -> MaterialStore:
    return MaterialStore(path, topology=load_topology(_TOPOLOGY_FILE), bindings=None)


def _cell(store: MaterialStore, kind: str, plate: int, hole: int) -> dict:
    for row in store.grid()["cells"]:
        if row["kind"] == kind and row["plate"] == plate and row["hole"] == hole:
            return row
    raise AssertionError(f"找不到孔位 {kind} {plate}-{hole}")


class TestAbsentMark(unittest.TestCase):
    def test_mark_absent_and_contents_cleared(self):
        """标 ABSENT = 件被拿走: 状态落账且粉/液/淋洗随件清零."""
        store = _store()
        store.mark("collector", 1, 2, STATE_FRESH)
        store.set_cell_amount("collector", 1, 2, powder_mm3=12.5, eluted=True)
        store.mark("collector", 1, 2, STATE_ABSENT)
        cell = _cell(store, "collector", 1, 2)
        self.assertEqual(cell["state"], STATE_ABSENT)
        self.assertEqual(cell["powder_mm3"], 0)
        self.assertEqual(cell["eluted"], False)
        store.close()

    def test_mark_plate_absent(self):
        """整板标 ABSENT 覆盖 6 孔."""
        store = _store()
        store.mark_plate("bottle", 3, STATE_ABSENT)
        for hole in range(1, 7):
            self.assertEqual(_cell(store, "bottle", 3, hole)["state"], STATE_ABSENT)
        store.close()

    def test_invalid_state_still_rejected(self):
        """写入口把关未松动: 非法状态照拒."""
        store = _store()
        with self.assertRaises(ValueError):
            store.mark("collector", 1, 1, "GONE")
        store.close()

    def test_absent_excluded_from_summary_and_next_fresh(self):
        """ABSENT 不进余量统计, 也不可被流程选中."""
        store = _store()
        store.mark_plate("collector", 1, STATE_FRESH)
        store.mark("collector", 1, 1, STATE_ABSENT)
        summary = store.grid()["summary"]["collector"]
        # 播种把其余 5 板 ×6 孔初始化为 USED(空孔); ABSENT 那孔哪边都不计
        self.assertEqual(summary["fresh"], 5)
        self.assertEqual(summary["used"], 30)
        self.assertEqual(summary["fresh"] + summary["used"], 35)
        # 直查: 全库唯一的 FRESH 都在板 1, ABSENT 那孔不算 FRESH
        fresh = [row for row in store.grid()["cells"]
                 if row["kind"] == "collector" and row["state"] == STATE_FRESH]
        self.assertEqual(len(fresh), 5)
        store.close()


class TestLegacyCheckMigration(unittest.TestCase):
    def test_legacy_two_state_check_rebuilt_with_data_kept(self):
        """带二态 CHECK 的旧库开库即重建: 约束拆掉, 已有盘点行逐行保留."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.db"
            conn = sqlite3.connect(path)
            # 造一份 2026-08-15 之前形制的表 (含 state 二态 CHECK) 与一行真数据
            conn.executescript(
                """
                CREATE TABLE material_cells (
                    kind       TEXT    NOT NULL,
                    plate      INTEGER NOT NULL,
                    hole       INTEGER NOT NULL,
                    state      TEXT    NOT NULL,
                    sample_id  TEXT    NOT NULL DEFAULT '',
                    updated_at REAL    NOT NULL,
                    run_id     TEXT    NOT NULL DEFAULT '',
                    powder_mm3 REAL    NOT NULL DEFAULT 0,
                    liquid_ml  REAL    NOT NULL DEFAULT 0,
                    eluted     INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (kind, plate, hole),
                    CHECK (state IN ('FRESH', 'USED')),
                    CHECK (plate BETWEEN 1 AND 6),
                    CHECK (hole BETWEEN 1 AND 6)
                );
                """
            )
            conn.execute(
                "INSERT INTO material_cells (kind, plate, hole, state, updated_at, powder_mm3)"
                " VALUES ('collector', 2, 5, 'FRESH', ?, 7.5)", (time.time(),))
            conn.commit()
            conn.close()

            store = _store(path)
            # 旧行原样保留
            cell = _cell(store, "collector", 2, 5)
            self.assertEqual(cell["state"], STATE_FRESH)
            self.assertEqual(cell["powder_mm3"], 7.5)
            # 三态可写 (旧 CHECK 已拆)
            store.mark("collector", 2, 5, STATE_ABSENT)
            self.assertEqual(_cell(store, "collector", 2, 5)["state"], STATE_ABSENT)
            store.close()

            # 再开一次: 迁移幂等, 不再动表
            second = _store(path)
            self.assertEqual(_cell(second, "collector", 2, 5)["state"], STATE_ABSENT)
            second.mark("collector", 2, 5, STATE_USED)
            second.close()


if __name__ == "__main__":
    unittest.main()
