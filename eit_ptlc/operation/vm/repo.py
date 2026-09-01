"""脚本仓库 (文件系统, 单根 + 组子目录)
========================================
功能:
    流程 (operation 节点树 YAML) 的持久化与管理: list/get/create/update/delete/clone/rename
    + 全量快照版本历史 + 内容哈希. 每次写入前经校验器校验, 失败即拒 (不落半成品); 内容未变跳过快照.

磁盘布局:
    仓库根直接是流程库 (如 config/operation); 其顶层子目录即"组":
        <root>/<组>/<名>.yaml        活跃节点树 (组为空则 <root>/<名>.yaml)
    版本历史按名存于独立 history_root (默认 <root>/.history, 运行期可指向 var/ 避免污染配置目录):
        <history_root>/<名>/NNNN_<iso>_<h8>.yaml

说明:
    脚本名在整个仓库内全局唯一 (VM 按名解析子脚本), 故对外 API 仍按名寻址, "组" 仅决定落盘子目录。
    workspace 概念已退化为单一逻辑库 (list_workspaces 恒返回 ["default"]); ws 参数保留仅为 API/测试兼容。
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

import yaml

log = logging.getLogger(__name__)


class ScriptRepo:
    """文件系统脚本仓库 (单根 + 组子目录)."""

    def __init__(self, root: str | Path, *, validator: Optional[Callable[[dict], list]] = None,
                 time_fn: Callable[[], float] = time.time, history_root: Optional[str | Path] = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._validator = validator
        self._time = time_fn
        # 版本历史可落到库外 (运行期数据), 避免快照污染 git 配置目录
        self._history_root = Path(history_root) if history_root else (self._root / ".history")

    # ------------------------------------------------------------------
    # 路径 (按名定位, 跨组扫描)
    # ------------------------------------------------------------------

    def _find_path(self, name: str) -> Optional[Path]:
        """按名定位活跃脚本文件: 先库根, 再一层组子目录 (排除 . 开头目录)."""
        direct = self._root / f"{name}.yaml"
        if direct.is_file():
            return direct
        for p in sorted(self._root.glob(f"*/{name}.yaml")):
            if not p.parent.name.startswith("."):
                return p
        return None

    def _group_of(self, path: Path) -> str:
        """脚本文件所属组 (父目录名); 直接位于库根则空串."""
        return "" if path.parent == self._root else path.parent.name

    def _target_path(self, name: str, group: str = "") -> Path:
        """新建/落盘目标路径 (组为空则置库根)."""
        return (self._root / group / f"{name}.yaml") if group else (self._root / f"{name}.yaml")

    def _hist_dir(self, name: str) -> Path:
        return self._history_root / name

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_workspaces(self) -> list[str]:
        # 单一逻辑库; 顶层子目录是"组"而非工作区
        return ["default"]

    def list_scripts(self, ws: str = "default", kind: Optional[str] = None) -> list[dict]:
        """列出全部脚本摘要 (含 group; 可按 kind 过滤)."""
        out: list[dict] = []
        # 库根 (组为空)
        for p in sorted(self._root.glob("*.yaml")):
            doc = self._read(p)
            if kind and doc.get("kind") != kind:
                continue
            out.append(self._summary(doc, p))
        # 各组子目录 (排除 . 开头, 如 .history)
        for sub in sorted(d for d in self._root.iterdir() if d.is_dir() and not d.name.startswith(".")):
            for p in sorted(sub.glob("*.yaml")):
                doc = self._read(p)
                if kind and doc.get("kind") != kind:
                    continue
                out.append(self._summary(doc, p))
        return out

    def exists(self, ws: str, name: str) -> bool:
        return self._find_path(name) is not None

    def get(self, ws: str, name: str) -> dict:
        p = self._find_path(name)
        if p is None:
            raise KeyError(f"脚本不存在: {name}")
        return self._read(p)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def create(self, ws: str, name: str, doc: dict, group: str = "") -> dict:
        if self._find_path(name) is not None:
            raise ValueError(f"脚本已存在: {name}")
        return self._write(self._target_path(name, group), doc)

    def update(self, ws: str, name: str, doc: dict) -> dict:
        # 更新保持原组 (按名定位现有文件); 不存在则新建于库根
        path = self._find_path(name) or self._target_path(name, "")
        return self._write(path, doc)

    def delete(self, ws: str, name: str) -> None:
        p = self._find_path(name)
        if p is not None:
            p.unlink()
        h = self._hist_dir(name)
        if h.is_dir():
            shutil.rmtree(h)

    def clone(self, ws: str, src: str, dst: str) -> dict:
        sp = self._find_path(src)
        if sp is None:
            raise KeyError(f"脚本不存在: {src}")
        doc = dict(self._read(sp))
        doc["name"] = dst
        return self.create(ws, dst, doc, group=self._group_of(sp))

    def rename(self, ws: str, src: str, dst: str) -> dict:
        """重命名脚本: 同组内移动活跃文件 + 改 name; 版本历史目录按名搬移."""
        sp = self._find_path(src)
        if sp is None:
            raise KeyError(f"脚本不存在: {src}")
        if self._find_path(dst) is not None:
            raise ValueError(f"目标脚本已存在: {dst}")
        doc = dict(self._read(sp))
        doc["name"] = dst
        dp = self._target_path(dst, self._group_of(sp))
        sp.rename(dp)
        with dp.open("w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        sh, dh = self._hist_dir(src), self._hist_dir(dst)
        if sh.is_dir():
            dh.parent.mkdir(parents=True, exist_ok=True)
            sh.rename(dh)
        return self._summary(doc, dp)

    def set_label(self, ws: str, name: str, label: str) -> dict:
        """仅改流程显示名 (label): 原地更新 doc, 不动文件名/英文ID; 经 _write 校验+落盘+快照."""
        p = self._find_path(name)
        if p is None:
            raise KeyError(f"脚本不存在: {name}")
        doc = dict(self._read(p))
        doc["label"] = label
        # _write 强制 doc["name"]=path.stem, 天然锁死英文ID/文件名不被 label 改动波及
        return self._write(p, doc)

    # ------------------------------------------------------------------
    # 版本历史
    # ------------------------------------------------------------------

    def history(self, ws: str, name: str) -> list[dict]:
        h = self._hist_dir(name)
        if not h.is_dir():
            return []
        out: list[dict] = []
        for p in sorted(h.glob("*.yaml")):
            parts = p.stem.split("_", 2)
            out.append({"rev": parts[0], "ts": parts[1] if len(parts) > 1 else "",
                        "hash": parts[2] if len(parts) > 2 else "", "file": p.name})
        return out

    def get_version(self, ws: str, name: str, rev: str) -> dict:
        h = self._hist_dir(name)
        for p in sorted(h.glob(f"{rev}_*.yaml")):
            return self._read(p)
        raise KeyError(f"版本不存在: {name}@{rev}")

    def content_hash(self, doc: dict) -> str:
        """脚本内容规范化哈希 (sort_keys 规范化后 sha256 前 16 位)."""
        canon = yaml.safe_dump(doc, allow_unicode=True, sort_keys=True)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _summary(self, doc: dict, path: Path) -> dict:
        ui = doc.get("ui") if isinstance(doc.get("ui"), dict) else {}
        # path 只进摘要不进 doc 本体: doc 会被前端整体 PUT 回来落盘, 混入 path 会写进 YAML 文件
        return {"name": doc.get("name", path.stem), "kind": doc.get("kind"),
                "label": doc.get("label", path.stem), "group": self._group_of(path),
                "ui": ui, "path": str(path),
                # 流程注释 (doc.note): 左栏悬停提示用; 编辑入口在右栏「注释」tab
                "note": doc.get("note") if isinstance(doc.get("note"), str) else "",
                # 脚本根部资源声明 (schema 强制为字符串列表), 供排程统计标注资源占用
                "resources": [r for r in (doc.get("resources") or []) if isinstance(r, str)],
                "updated_at": path.stat().st_mtime, "hash": self.content_hash(doc)}

    def _read(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _write(self, path: Path, doc: dict) -> dict:
        if self._validator is not None:
            errors = self._validator(doc)
            if errors:
                raise ValueError("脚本校验失败: " + "; ".join(errors))
        name = path.stem
        doc = dict(doc)
        doc["name"] = name
        new_hash = self.content_hash(doc)
        prev_hash = self.content_hash(self._read(path)) if path.is_file() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        if prev_hash != new_hash:
            self._snapshot(name, doc, new_hash)
        return self._summary(doc, path)

    def _snapshot(self, name: str, doc: dict, content_hash: str) -> None:
        hd = self._hist_dir(name)
        hd.mkdir(parents=True, exist_ok=True)
        seq = len(list(hd.glob("*.yaml"))) + 1
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(self._time()))
        fname = f"{seq:04d}_{stamp}_{content_hash[:8]}.yaml"
        with (hd / fname).open("w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
