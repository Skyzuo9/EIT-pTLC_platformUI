"""VM 编排 API 数据传输对象
========================
功能:
    脚本仓库 CRUD 与 VM 运行/调试/HITL 的 HTTP 请求体模型. 脚本节点树文档以校验后的 raw dict
    透传 (不为每种节点写 Pydantic 类), 由后端 validate_script 把关.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


def new_script_doc(name: str, kind: str = "operation", label: Optional[str] = None) -> dict:
    """构造一个最小合法的空脚本节点树文档.

    参数:
        name: 脚本名; kind: action|operation; label: 显示名 (缺省取 name)
    返回:
        节点树文档 dict
    """
    return {"schema": "ptlc.script/v1", "kind": kind, "name": name,
            "label": label or name, "vars": [], "body": []}


class ScriptCreateBody(BaseModel):
    name: str
    kind: str = "operation"
    label: Optional[str] = None
    group: Optional[str] = None     # 落盘组子目录 (config/operation/<组>/); 缺省=库根


class ScriptWriteBody(BaseModel):
    doc: dict


class NameBody(BaseModel):
    dst: str


class LabelBody(BaseModel):
    label: str


class VmStartBody(BaseModel):
    inputs: dict = {}
    mode: Optional[str] = None
    mode_run: str = "run"          # run (自由运行) | step (停在首叶子)
    start_aid: Optional[str] = None  # 从该 AID 起跑 (跳过其前设备/人工叶子); 缺省从头
    overrides: dict = {}           # 运行前旋钮覆盖 (名 -> 值); 建帧时注入带 ui 的 in var, 深层可达
    # External idempotency key.  When supplied it is also the VM run_id;
    # repeated submissions return the existing run rather than starting a
    # second physical effect.
    command_id: Optional[str] = None


class HumanReplyBody(BaseModel):
    choice: Optional[str] = None
    values: dict = {}


class BreakpointsBody(BaseModel):
    aids: list[str] = []


class ResetBody(BaseModel):
    aid: Optional[str] = None
