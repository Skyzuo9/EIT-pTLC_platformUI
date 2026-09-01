"""设备参数配置服务
==================
功能:
    读取 / 校验保存 app.yaml 中已 config 化的设备参数段 (camera / gcode / vision / pump),
    供上位机在动作/流程页结构化编辑。使用 ruamel.yaml round-trip 保留注释与格式;
    保存前复用 config.loader 的 _parse_* 校验器全量校验, 不通过绝不写盘。

    注: 写盘是持久化下次启动的配置; 当前运行期对象不一定热生效 (on_saved 仅刷新
    点位页 CNC 展示用的 gcode 快照)。相机/视觉等需重启上位机生效。
"""

from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from eit_ptlc.config.loader import _parse_camera, _parse_gcode, _parse_pump, _parse_vision


def _to_plain(obj):
    """ruamel CommentedMap/Seq/Scalar -> 纯 dict/list/标量 (供校验与 JSON 序列化)。"""
    return json.loads(json.dumps(obj))


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_to_ruamel(target, values: dict) -> None:
    """把 values 深写入 ruamel 结构 (保留注释): 标量赋值, 嵌套 map 递归。"""
    for k, v in values.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _apply_to_ruamel(target[k], v)
        else:
            target[k] = v


class ConfigService:
    """app.yaml 设备参数段的读写服务 (挂 app.state.config_svc)。"""

    SECTIONS = ("camera", "gcode", "vision", "pump")

    def __init__(self, config_path, *, on_saved=None) -> None:
        """config_path: app.yaml 路径; on_saved: 保存成功后的回调 (如刷新运行期 gcode 快照)。"""
        self._path = Path(config_path)
        self._on_saved = on_saved
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    @staticmethod
    def _validate(section: str, merged: dict) -> None:
        if section == "camera":
            _parse_camera(merged)
        elif section == "gcode":
            _parse_gcode(merged)
        elif section == "vision":
            _parse_vision(merged)
        elif section == "pump":
            _parse_pump(merged)

    def read_section(self, section: str) -> dict:
        if section not in self.SECTIONS:
            raise ValueError(f"不可编辑配置段: {section} (合法 {self.SECTIONS})")
        with self._path.open(encoding="utf-8") as f:
            data = self._yaml.load(f)
        return _to_plain((data or {}).get(section) or {})

    def save_section(self, section: str, values) -> dict:
        """合并 values 到目标段, 校验通过后写回 (保留注释); 失败抛 ValueError, 不写盘。"""
        if section not in self.SECTIONS:
            raise ValueError(f"不可编辑配置段: {section} (合法 {self.SECTIONS})")
        if not isinstance(values, dict):
            raise ValueError("values 必须是对象")
        with self._path.open(encoding="utf-8") as f:
            data = self._yaml.load(f)
        if data is None:
            data = CommentedMap()
        cur = _to_plain(data.get(section) or {})
        self._validate(section, _deep_merge(cur, values))  # 校验完整段 (失败 -> 拒绝, 未写盘)
        if not isinstance(data.get(section), dict):
            data[section] = CommentedMap()
        _apply_to_ruamel(data[section], values)
        with self._path.open("w", encoding="utf-8") as f:
            self._yaml.dump(data, f)
        if self._on_saved:
            self._on_saved()
        return {"section": section, "saved": True}
