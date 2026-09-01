"""接粉桶翻料缸到位判定离线用例 (controller/photoscrape_rot)。

关键钉子:
    1. IX9 是共享字节 —— 取位不得被 bit0/1 的上样料架检测干扰
    2. 到位即返回, 不白等满超时
    3. 超时/读不到**一律不抛** —— 这是哨兵不是工艺步, 抛错会把已完成的标定判成中止
    4. 读回 None 不当 0 用 (全 0 恰好是"两个到位位都没到"的故障态, 当 0 会指错方向)
"""

from __future__ import annotations

import asyncio

import pytest

from eit_ptlc.controller.photoscrape_rot import (
    _IX9_ROT_EXTEND_BIT,
    _IX9_ROT_HOME_BIT,
    rot_state,
    wait_rot,
)

_EXTEND = 1 << _IX9_ROT_EXTEND_BIT      # 动点 = 已翻倒
_HOME = 1 << _IX9_ROT_HOME_BIT          # 原点 = 刮取位
# runtime/material_store.py:93 记下的真机活值; 拿它当夹具, 保证取位逻辑对真实字节成立
_LIVE_IX9 = 91                          # 0b01011011: bit0/1/3/4/6 置位 → 原点成立, 动点不成立


def _clock():
    """可控时钟 + 假 sleep: 让超时用例零耗时, 且不依赖真实时序。"""
    now = {"t": 0.0}

    async def sleep(sec):
        now["t"] += sec

    return (lambda: now["t"]), sleep


# --------------------------------------------------------------------------
# 1) 按位取 (共享字节, 不得被别的位干扰)
# --------------------------------------------------------------------------

def test_bits_are_read_independently():
    assert rot_state(_EXTEND) == {"at_extend": True, "at_home": False, "raw": _EXTEND}
    assert rot_state(_HOME) == {"at_extend": False, "at_home": True, "raw": _HOME}
    assert rot_state(0) == {"at_extend": False, "at_home": False, "raw": 0}


def test_rack_detect_bits_do_not_leak_into_rot_state():
    """bit0/1 是上样料架检测 —— 它们置位不得被读成翻料缸到位。"""
    noise = 0b0000_0011                       # 料架检测 1/2 都有料
    assert rot_state(noise)["at_extend"] is False
    assert rot_state(noise)["at_home"] is False
    assert rot_state(noise | _EXTEND)["at_extend"] is True


def test_live_ix9_sample_reads_as_home_not_extend():
    """真机实测 IX9=91: bit6 置位 bit7 未置 → 原点成立、动点不成立。"""
    state = rot_state(_LIVE_IX9)
    assert state["at_home"] is True
    assert state["at_extend"] is False


# --------------------------------------------------------------------------
# 2) 到位即返回
# --------------------------------------------------------------------------

def test_returns_immediately_when_already_at_extend():
    time_fn, sleep = _clock()

    async def read():
        return _EXTEND

    res = asyncio.run(wait_rot(read, target="extend", timeout_s=6.0,
                               time_fn=time_fn, sleep=sleep))
    assert res["ok"] is True
    assert res["at_extend"] is True
    assert res["elapsed_s"] == 0.0            # 没白等


def test_waits_until_cylinder_arrives():
    """前几轮未到位, 到位那一轮立刻返回 —— 且不等满超时。"""
    time_fn, sleep = _clock()
    seq = [_HOME, _HOME, 0, _EXTEND]
    calls = {"n": 0}

    async def read():
        val = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return val

    res = asyncio.run(wait_rot(read, target="extend", timeout_s=6.0, poll_s=0.2,
                               time_fn=time_fn, sleep=sleep))
    assert res["ok"] is True
    assert calls["n"] == 4
    assert res["elapsed_s"] == pytest.approx(0.6)      # 3 次轮询间隔, 远小于 6s


def test_home_target_waits_for_the_other_bit():
    time_fn, sleep = _clock()

    async def read():
        return _HOME

    res = asyncio.run(wait_rot(read, target="home", timeout_s=6.0,
                               time_fn=time_fn, sleep=sleep))
    assert res["ok"] is True
    assert res["at_home"] is True


# --------------------------------------------------------------------------
# 3) 失败一律不抛 (哨兵语义)
# --------------------------------------------------------------------------

def test_timeout_returns_not_ok_without_raising():
    """缸卡住: 必须返回 ok=false 而不是抛 —— 抛会把已完成的标定判成 ABORTED。"""
    time_fn, sleep = _clock()

    async def read():
        return _HOME                          # 永远停在原点, 翻不过去

    res = asyncio.run(wait_rot(read, target="extend", timeout_s=6.0, poll_s=0.2,
                               time_fn=time_fn, sleep=sleep))
    assert res["ok"] is False
    assert res["at_extend"] is False
    assert res["elapsed_s"] >= 6.0
    assert "超时" in res["message"]


def test_unreadable_node_is_not_treated_as_zero():
    """读回 None 是"读不到"不是"全 0" —— 全 0 恰好也是故障态, 当 0 会指错方向。"""
    time_fn, sleep = _clock()

    async def read():
        return None

    res = asyncio.run(wait_rot(read, target="extend", time_fn=time_fn, sleep=sleep))
    assert res["ok"] is False
    assert res["raw"] is None
    assert "空值" in res["message"]


def test_bad_target_falls_back_to_extend_without_raising():
    """编排笔误不该炸掉收尾链。"""
    time_fn, sleep = _clock()

    async def read():
        return _EXTEND

    res = asyncio.run(wait_rot(read, target="nonsense", time_fn=time_fn, sleep=sleep))
    assert res["ok"] is True
    assert res["target"] == "extend"
