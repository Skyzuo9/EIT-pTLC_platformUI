"""PLC 工程(.project)全量版本仓库
====================================
功能:
    对 CODESYS .project 二进制工程做全量快照版本管理. 每次「保存到工程」后按内容哈希去重
    快照整份工程, 部署成功后给最新快照打部署标记(下发台账), 支持列出历史/下载某版/按版还原.
    镜像 operation/vm/repo.py(ScriptRepo)的快照模式, 但作用于二进制文件: 哈希为文件字节
    sha256(非 YAML 规范化), 内容未变即跳过快照.

磁盘布局:
    <root>/<工程名>/NNNN_<iso>_<sha8>.project   历史快照(只读留档)
    <root>/<工程名>/index.json                   各版元数据 [{rev,ts,sha256,size,file,deployed_at,message}]

说明:
    快照与哈希在后端(Python3)算, 不进 worker(Py2 沙箱); worker save=true 已 flush .project,
    后端共享文件系统只读拷贝即可. 历史落 var/(已 gitignore 运行期数据), 不污染 git.
    还原会覆盖活动工程, 调用方须先停 worker 释放文件锁(见 PlcProgramService.restore_version).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


class PlcVersionRepo:
    """CODESYS .project 二进制工程的全量快照版本仓库 (内容哈希去重 + 部署台账)."""

    def __init__(self, project: str | Path, root: str | Path, *,
                 time_fn: Callable[[], float] = time.time) -> None:
        """
        参数:
            project: 活动 .project 文件绝对路径(被编辑/下发的真源)
            root: 历史仓库根目录(运行期数据, 建议 var/plc-history)
            time_fn: 取时函数(可注入便于测试)
        """
        self._project = Path(project)
        self._dir = Path(root) / self._project.stem  # 按工程名分目录
        self._time = time_fn

    # ------------------------------------------------------------------
    # 内部: 索引与哈希
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self._dir / "index.json"

    def _read_index(self) -> list[dict]:
        """读元数据索引(升序, 末项为最新); 不存在返回空表."""
        p = self._index_path()
        if not p.is_file():
            return []
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_index(self, index: list[dict]) -> None:
        """原子写索引: 先写 .tmp 再 replace, 避免半写被读到."""
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / "index.json.tmp"
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        tmp.replace(self._index_path())

    @staticmethod
    def _file_sha256(path: Path) -> str:
        """逐块(1MB)读文件算 sha256 全 64 位十六进制(3.7MB 工程约几毫秒)."""
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def current_sha256(self) -> str:
        """Return the SHA-256 of the exact active project bytes on disk."""
        if not self._project.is_file():
            raise FileNotFoundError("工程文件不存在: %s" % self._project)
        return self._file_sha256(self._project)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def snapshot_if_changed(self, message: str = "") -> Optional[dict]:
        """读活动 .project → sha256 → 与最新快照比对, 变化才拷贝留档(去重).

        参数:
            message: 本版说明(手动打标记时可填)
        返回:
            dict, 新建版本元数据; 内容未变返回 None(等价 repo.py 的 prev_hash==new_hash 跳过)
        """
        if not self._project.is_file():
            raise FileNotFoundError("工程文件不存在: %s" % self._project)
        sha = self._file_sha256(self._project)
        index = self._read_index()
        if index and index[-1].get("sha256") == sha:
            return None  # 内容未变, 去重
        seq = len(index) + 1
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(self._time()))
        fname = "%04d_%s_%s.project" % (seq, stamp, sha[:8])  # 序号 + ISO + 哈希前 8
        self._dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._project, self._dir / fname)
        entry = {
            "rev": "%04d" % seq,
            "ts": stamp,
            "sha256": sha,
            "size": self._project.stat().st_size,
            "file": fname,
            "deployed_at": None,
            "message": message,
        }
        index.append(entry)
        self._write_index(index)
        log.info("[plc-version] 快照 rev=%s (%d bytes, sha=%s)", entry["rev"], entry["size"], sha[:8])
        return entry

    def mark_deployed(self, *, expected_sha256: str) -> dict:
        """Only mark the exact host-authorized project SHA as deployed.

        返回:
            dict, 被标记为已部署的版本元数据
        """
        expected = str(expected_sha256 or "").lower()
        current = self.current_sha256()
        if current != expected:
            raise RuntimeError(
                "active PLC project SHA changed before ledger update "
                "(expected=%s, current=%s)" % (expected, current)
            )
        self.snapshot_if_changed()  # 当前内容若未入库(如未改动直接下发)则补一份
        index = self._read_index()
        if not index:
            raise RuntimeError("无可标记的版本快照")
        if index[-1].get("sha256") != expected:
            raise RuntimeError(
                "latest PLC snapshot does not match deployed SHA "
                "(expected=%s, latest=%s)" % (expected, index[-1].get("sha256"))
            )
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(self._time()))
        index[-1]["deployed_at"] = stamp
        self._write_index(index)
        log.info("[plc-version] 标记已部署 rev=%s @ %s", index[-1]["rev"], stamp)
        return index[-1]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def history(self) -> list[dict]:
        """列出全部版本元数据(按 rev 升序; 末项为最新)."""
        return self._read_index()

    def get_version(self, rev: str) -> dict:
        """取某版元数据(rev 为 4 位序号字符串如 "0001")."""
        for entry in self._read_index():
            if entry["rev"] == rev:
                return entry
        raise KeyError("版本不存在: %s" % rev)

    def version_bytes(self, rev: str) -> bytes:
        """读某版快照二进制内容(供下载)."""
        entry = self.get_version(rev)
        return (self._dir / entry["file"]).read_bytes()

    # ------------------------------------------------------------------
    # 还原
    # ------------------------------------------------------------------

    def restore(self, rev: str) -> dict:
        """把某版快照覆盖回活动 .project(还原前先自快照当前, 自身可逆).

        注意:
            调用方须保证活动工程未被 worker 占用(应先 shutdown worker 释放文件锁), 否则
            Windows 下覆盖会因占用失败.
        返回:
            dict, 被还原的版本元数据
        """
        entry = self.get_version(rev)
        if self._project.is_file():
            self.snapshot_if_changed(message="还原 %s 前自动快照" % rev)
        shutil.copy2(self._dir / entry["file"], self._project)
        log.info("[plc-version] 还原 rev=%s → %s", rev, self._project)
        return entry
