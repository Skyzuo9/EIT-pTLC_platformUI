"""动作源文件服务
==================
功能:
    承载「动作」编辑界面 YAML 源文件视图的原始读写: 按指令名定位其所在 .yaml 源文件,
    返回整文件原始文本供浏览/编辑; 保存时写前全量校验 (不过校验绝不写坏文件), 校验通过
    才原样落盘, 随后权威重载动作目录并热替换运行期引用 (app.state.registry / executor /
    VM 脚本校验器名集), 使表单视图与执行立即生效, 无需重启。

    与 PointsService 的 raw 读写同范式: registry 本身不可变且无 service 封装, 故由本服务
    单独承载「按文件 raw 读写 + 校验 + 热重载」职责。动作名→源文件由本服务自行扫描目录建立索引
    (ActionDef 不持有源路径, 不为此改 registry/DTO)。
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.operation.vm.knobs import _iter_calls

log = logging.getLogger(__name__)


class ActionsService:
    """动作源文件读写服务 (挂 app.state.actions)。"""

    def __init__(self, actions_dir: str | Path, *,
                 executor=None,
                 on_reload: Optional[Callable[[ActionRegistry], None]] = None,
                 operation_dir: str | Path | None = None) -> None:
        """参数:
        actions_dir: config/actions 目录 (递归 <NN_设备>/*.yaml);
        executor: ActionExecutor, 保存后热替换其动作目录 (set_registry);
        on_reload: 重载回调, 接收新 registry (更新 app.state.registry 与 VM 校验器名集);
        operation_dir: config/operation 目录 (删除动作前扫描流程引用; None 则跳过扫描)。
        """
        self._dir = Path(actions_dir)
        self._executor = executor
        self._on_reload = on_reload
        self._operation_dir = Path(operation_dir) if operation_dir is not None else None
        # _index: 动作名 -> 所在源文件绝对路径 (供按指令名定位整文件)
        self._index: dict[str, Path] = {}
        self._build_index()

    def _build_index(self) -> None:
        """扫描 actions_dir 建 动作名→源文件 索引 (同 ActionRegistry.load 的遍历口径)。"""
        index: dict[str, Path] = {}
        for path in sorted(self._dir.glob("**/*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                # 启动时 registry.load 已全量校验过, 正常不会到这; 损坏文件跳过不阻断索引
                log.warning("[Actions] 索引跳过无法解析的文件: %s", path)
                continue
            if isinstance(raw, dict):
                for name in raw:
                    index[str(name)] = path
        self._index = index

    def _path_of(self, name: str) -> Path:
        path = self._index.get(name)
        if path is None:
            raise KeyError(f"未知动作: {name}")
        return path

    def read_action_raw(self, name: str) -> dict:
        """返回指令所在源文件的整文件原始文本 (保留注释/格式)。"""
        path = self._path_of(name)
        rel = path.relative_to(self._dir)
        group = rel.parts[0] if len(rel.parts) > 1 else ""
        return {"name": name, "path": str(path), "group": group,
                "text": path.read_text(encoding="utf-8")}

    @staticmethod
    def _pair_end(text: str, value_node) -> int:
        """返回 YAML mapping 键值对的源码结束位置 (含该行换行)。"""
        end = value_node.end_mark.index
        if end > 0 and text[end - 1:end] in {"\n", "\r"}:
            return end
        line_end = text.find("\n", end)
        return len(text) if line_end < 0 else line_end + 1

    @staticmethod
    def _render_desc(desc: str, *, indent: int, newline: str) -> str:
        """把说明渲染为保留换行的 YAML block scalar。"""
        prefix = " " * indent
        body_prefix = " " * (indent + 2)
        lines = desc.split("\n")
        return (
            f"{prefix}desc: |-"
            + newline
            + newline.join(f"{body_prefix}{line}" for line in lines)
            + newline
        )

    @classmethod
    def _patch_action_desc(cls, text: str, name: str, desc: str) -> str:
        """只替换一个动作的 desc 源码片段，保留其它字段、注释和顺序。"""
        root = yaml.compose(text)
        if not isinstance(root, MappingNode):
            raise ValueError("动作 YAML 根节点必须是 mapping")

        spec = None
        for key_node, value_node in root.value:
            if isinstance(key_node, ScalarNode) and str(key_node.value) == name:
                spec = value_node
                break
        if spec is None:
            raise KeyError(f"未知动作: {name}")
        if not isinstance(spec, MappingNode) or spec.flow_style:
            raise ValueError(f"动作 {name} 必须使用块状 mapping 才能定点编辑 desc")

        newline = "\r\n" if "\r\n" in text else "\n"
        fields = [
            (key_node, value_node)
            for key_node, value_node in spec.value
            if isinstance(key_node, ScalarNode)
        ]
        for key_node, value_node in fields:
            if str(key_node.value) != "desc":
                continue
            start = text.rfind("\n", 0, key_node.start_mark.index) + 1
            end = cls._pair_end(text, value_node)
            rendered = cls._render_desc(
                desc, indent=key_node.start_mark.column, newline=newline)
            return text[:start] + rendered + text[end:]

        # 没有 desc 时放在 label 后；无 label 则放在 kind 后，仍不重排其它字段。
        anchor = next(
            ((key_node, value_node) for key_node, value_node in fields
             if str(key_node.value) == "label"),
            None,
        )
        if anchor is None:
            anchor = next(
                ((key_node, value_node) for key_node, value_node in fields
                 if str(key_node.value) == "kind"),
                None,
            )
        indent = fields[0][0].start_mark.column if fields else spec.start_mark.column
        rendered = cls._render_desc(desc, indent=indent, newline=newline)
        if anchor is not None:
            insert_at = cls._pair_end(text, anchor[1])
            if insert_at and text[insert_at - 1:insert_at] not in {"\n", "\r"}:
                rendered = newline + rendered
            return text[:insert_at] + rendered + text[insert_at:]
        raise ValueError(f"动作 {name} 定义为空，无法插入 desc")

    def save_action_description(self, name: str, desc: str) -> dict:
        """定点保存一个动作的详细说明，并复用全量校验与热重载。"""
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError("动作 desc 不能为空")
        path = self._path_of(name)
        original = path.read_text(encoding="utf-8")
        patched = self._patch_action_desc(original, name, desc.strip())
        return self.save_action_raw(name, patched)

    @staticmethod
    def _find_action_spec(root, name: str):
        """在已 compose 的根 mapping 中定位一个动作, 返回 (key_node, value_node)。"""
        if not isinstance(root, MappingNode):
            raise ValueError("动作 YAML 根节点必须是 mapping")
        for key_node, value_node in root.value:
            if isinstance(key_node, ScalarNode) and str(key_node.value) == name:
                return key_node, value_node
        raise KeyError(f"未知动作: {name}")

    @classmethod
    def _patch_action_label(cls, text: str, name: str, label: str) -> str:
        """只替换一个动作的 label 源码行, 保留其它字段、注释和顺序。

        新值以 JSON 双引号转义写入 (合法 YAML 标量), 任意字符 (#/冒号等) 均安全。
        """
        _, spec = cls._find_action_spec(yaml.compose(text), name)
        if not isinstance(spec, MappingNode) or spec.flow_style:
            raise ValueError(f"动作 {name} 必须使用块状 mapping 才能定点编辑 label")
        newline = "\r\n" if "\r\n" in text else "\n"
        fields = [
            (key_node, value_node)
            for key_node, value_node in spec.value
            if isinstance(key_node, ScalarNode)
        ]
        scalar = json.dumps(label, ensure_ascii=False)
        for key_node, value_node in fields:
            if str(key_node.value) != "label":
                continue
            start = text.rfind("\n", 0, key_node.start_mark.index) + 1
            end = cls._pair_end(text, value_node)
            rendered = " " * key_node.start_mark.column + f"label: {scalar}" + newline
            return text[:start] + rendered + text[end:]
        # 无 label 时插在 kind 后 (防御路径: 现有动作均带 label, kind 为必填字段)
        anchor = next(
            ((key_node, value_node) for key_node, value_node in fields
             if str(key_node.value) == "kind"),
            None,
        )
        if anchor is None:
            raise ValueError(f"动作 {name} 缺少 kind 字段, 无法插入 label")
        indent = fields[0][0].start_mark.column
        insert_at = cls._pair_end(text, anchor[1])
        rendered = " " * indent + f"label: {scalar}" + newline
        if insert_at and text[insert_at - 1:insert_at] not in {"\n", "\r"}:
            rendered = newline + rendered
        return text[:insert_at] + rendered + text[insert_at:]

    def save_action_label(self, name: str, label: str) -> dict:
        """定点保存一个动作的显示名, 并复用全量校验与热重载。"""
        if not isinstance(label, str) or not label.strip():
            raise ValueError("动作 label 不能为空")
        path = self._path_of(name)
        original = path.read_text(encoding="utf-8")
        patched = self._patch_action_label(original, name, label.strip())
        return self.save_action_raw(name, patched)

    @classmethod
    def _node_src_end(cls, text: str, node) -> int:
        """节点源码的精确结束位置 (含行尾换行)。

        块状集合的 end_mark 由 BlockEnd 触发, 会越过空行/注释落到下一 token 起点,
        故递归取其最后一个子节点; 标量与 flow 集合的 end_mark 精确。
        """
        if isinstance(node, (MappingNode, SequenceNode)) and not node.flow_style:
            if node.value:
                last = node.value[-1]
                child = last[1] if isinstance(last, tuple) else last
                return cls._node_src_end(text, child)
        return cls._pair_end(text, node)

    @classmethod
    def _patch_action_delete(cls, text: str, name: str) -> str:
        """从源码中整段删除一个动作: 键行起至值块末尾, 连带上方紧贴的注释行。"""
        key_node, value_node = cls._find_action_spec(yaml.compose(text), name)
        start = text.rfind("\n", 0, key_node.start_mark.index) + 1
        end = cls._node_src_end(text, value_node)
        # 上方紧贴的 # 注释行一并删除 (遇空行/非注释即停; 文件头 banner 与首动作间有空行, 安全)
        while start > 0:
            prev_start = text.rfind("\n", 0, start - 1) + 1
            if not text[prev_start:start].strip().startswith("#"):
                break
            start = prev_start
        # 吞掉紧随其后的一个空行, 避免删除后留下连续空行
        if text[end:end + 2] == "\r\n":
            end += 2
        elif text[end:end + 1] == "\n":
            end += 1
        return text[:start] + text[end:]

    def _referencing_scripts(self, name: str) -> list[str]:
        """扫描流程目录, 返回 call 引用了该动作的流程名列表 (未配置目录则跳过)。"""
        if self._operation_dir is None or not self._operation_dir.is_dir():
            return []
        refs: list[str] = []
        for path in sorted(self._operation_dir.glob("**/*.yaml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue                  # 坏文件由脚本校验器另行报错, 不阻断删除扫描
            body = doc.get("body") if isinstance(doc, dict) else None
            if not isinstance(body, list):
                continue
            if any(node.get("action") == name for node in _iter_calls(body)):
                refs.append(str(doc.get("name") or path.stem))
        return refs

    def delete_action(self, name: str) -> dict:
        """功能:
            从源文件中删除一个动作定义 (含其上方紧贴注释), 写前全量校验并热重载;
            被任一流程 call 引用时拒绝删除。
        参数:
            name: 动作名 (YAML 顶层 key)
        返回:
            Dict[str, object], {"deleted": True, "name": 动作名}
        异常:
            KeyError - 未知动作; ValueError - 动作被流程引用 (信息含引用清单)
        """
        path = self._path_of(name)
        refs = self._referencing_scripts(name)
        if refs:
            raise ValueError(f"动作被以下流程引用, 不能删除: {', '.join(refs)}")
        original = path.read_text(encoding="utf-8")
        patched = self._patch_action_delete(original, name)
        self.save_action_raw(name, patched)
        log.info("[Actions] 已删除动作: %s (%s)", name, path.name)
        return {"deleted": True, "name": name}

    def save_action_raw(self, name: str, text: str) -> dict:
        """校验 text 后整文件落盘并热重载; 不过校验抛错绝不写坏文件。

        写前校验: 把 actions_dir 复制到临时目录, 用 text 覆盖目标文件, 调 ActionRegistry.load
        复用全部校验 (YAML 语法 / kind 合法 / station+action_code 必填 / 跨文件动作名唯一 等);
        任一失败抛 (yaml.YAMLError / ValueError), 真文件原样不动。通过后原样写回, 权威重载,
        热替换 executor 动作目录 + on_reload (app.state.registry / 校验器名集)。
        """
        path = self._path_of(name)                       # 定位源文件 (未知动作抛 KeyError)
        rel = path.relative_to(self._dir)

        # 写前全量校验 (临时目录副本), 不落真盘
        tmp_root = Path(tempfile.mkdtemp(prefix="eit_actions_"))
        try:
            tmp_dir = tmp_root / self._dir.name
            shutil.copytree(self._dir, tmp_dir)
            (tmp_dir / rel).write_text(text, encoding="utf-8")
            ActionRegistry.load(tmp_dir)                  # 失败即抛, 真文件不动
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

        # 校验通过 -> 原样写回真文件 -> 权威重载 -> 热替换三处引用
        path.write_text(text, encoding="utf-8")
        new_reg = ActionRegistry.load(self._dir)
        self._build_index()
        if self._executor is not None:
            self._executor.set_registry(new_reg)
        if self._on_reload is not None:
            self._on_reload(new_reg)
        log.info("[Actions] 已保存并重载动作源文件: %s (%d 个动作)", path.name, len(new_reg))
        return {"name": name, "saved": True, "actions": len(new_reg)}

    def reload(self) -> dict:
        """从磁盘重扫动作目录并热替换运行期引用 (不写任何文件).

        功能:
            动作 YAML 在磁盘上被直接编辑 (非经本服务保存) 后, 手动触发一次权威重载,
            使动作表单 / 左栏库 / 执行立即反映磁盘现状, 无需重启后端。与 save_action_raw
            的保存后重载尾段同源 (registry / executor 动作目录 / on_reload 三处引用),
            差别仅在此处不落盘。
        返回:
            Dict[str, object], {"reloaded": True, "actions": 重载后动作数}
        异常:
            yaml.YAMLError / ValueError - 磁盘上存在损坏或非法的动作 YAML; load 在重新赋值前
            即抛出, 故 registry / executor / 校验器名集全部保持原样 (运行期不被污染)。
        """
        new_reg = ActionRegistry.load(self._dir)      # 失败即抛; 成功前不动任何运行期引用
        self._build_index()
        if self._executor is not None:
            self._executor.set_registry(new_reg)
        if self._on_reload is not None:
            self._on_reload(new_reg)
        log.info("[Actions] 已从磁盘重载动作目录 (%d 个动作)", len(new_reg))
        return {"reloaded": True, "actions": len(new_reg)}
