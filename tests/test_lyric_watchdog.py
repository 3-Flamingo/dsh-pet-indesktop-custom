# -*- coding: utf-8 -*-
"""歌词卡死自愈看门狗（终结"卡一次就要重启"）。

背景：歌词链路"卡一次就永久不更新"的成因被逐个发现、逐个修过（采样忙门卡死、
采样线程退出后无人重建、``_user_mode_off`` 残留、令牌错代导致结果全丢……）。
每修一个都只是"猜对了下一个 bug"，所以补一条**与成因无关**的兜底：
控制器自己盯着"最近一次走完一拍的时刻"，连续
``STALL_REVIVE_SECONDS`` 秒没有下文就原地重置并按当前配置重新启用。

本用例用**假时钟**与**无网络桩**直接驱动看门狗，不依赖真实播放器：

1. 正常心跳不断时，看门狗永远不动手；
2. 停摆超过阈值、开关开着、窗口可见 → 触发一次复活；
3. 开关关着 / 窗口隐藏 → 不复活（那不是卡死，是本来就不该工作）；
4. 复活会把整条链复位（``_user_mode_off`` 清掉、忙门结清、重新派发）。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from pet import music_lyric_controller as mlc


class _Cfg:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Host(QObject):
    def __init__(self, *, visible=True, lyric_enabled=True):
        super().__init__()
        self.cfg = _Cfg({
            "music_lyric_enabled": lyric_enabled,
            "music_browser_media_enabled": False,
            "foobar_lyrics_enabled": False,
            "music_lyric_lead_seconds": 1.0,
            "music_lyric_cache_limit": 2000,
        })
        self.visible = visible
        self.bubbles = []

    def isVisible(self):
        return self.visible

    def show_bubble(self, text, **kwargs):
        self.bubbles.append(text)

    def hold_bubble(self, *_args, **_kwargs):
        return None


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def clock(monkeypatch):
    """可控时钟：看门狗与控制器共用 time.monotonic。"""
    state = {"now": 1000.0}
    monkeypatch.setattr(mlc.time, "monotonic", lambda: state["now"])
    return state


@pytest.fixture
def controller(app, clock, monkeypatch):
    host = _Host()
    ctrl = mlc.MusicLyricController(host)
    # 不碰真实播放器/网络：采样直接返回"什么都没在放"
    monkeypatch.setattr(mlc.now_playing, "get_now_playing",
                        lambda *a, **k: None)
    yield ctrl, host
    ctrl.shutdown()


def _stall(ctrl, clock, seconds):
    clock["now"] += seconds
    ctrl._watchdog_check()


def test_healthy_heartbeat_never_revives(controller, clock, monkeypatch):
    ctrl, _host = controller
    revived = []
    monkeypatch.setattr(ctrl, "_revive", lambda reason: revived.append(reason))
    ctrl.sync_enabled(True)
    for _ in range(10):
        clock["now"] += 1.0
        ctrl._heartbeat()
        ctrl._watchdog_check()
    assert revived == [], "心跳不断时看门狗不应该动手"


def test_stall_triggers_revive(controller, clock, monkeypatch):
    ctrl, _host = controller
    revived = []
    monkeypatch.setattr(ctrl, "_revive", lambda reason: revived.append(reason))
    ctrl.sync_enabled(True)
    _stall(ctrl, clock, mlc.STALL_REVIVE_SECONDS - 1)
    assert revived == [], "还没到阈值不该动"
    _stall(ctrl, clock, 2)
    assert len(revived) == 1, "超过阈值必须复活一次"


def test_disabled_or_hidden_never_revives(controller, clock, monkeypatch):
    ctrl, host = controller
    revived = []
    monkeypatch.setattr(ctrl, "_revive", lambda reason: revived.append(reason))
    ctrl.sync_enabled(True)
    host.cfg._values["music_lyric_enabled"] = False       # 设置里关掉了
    _stall(ctrl, clock, mlc.STALL_REVIVE_SECONDS * 2)
    host.cfg._values["music_lyric_enabled"] = True
    host.visible = False                                   # 窗口隐藏
    _stall(ctrl, clock, mlc.STALL_REVIVE_SECONDS * 2)
    assert revived == [], "开关关着/窗口隐藏不是卡死，不能复活"


def test_revive_resets_and_reenables(controller, clock, monkeypatch):
    ctrl, _host = controller
    ctrl.sync_enabled(True)
    calls = []
    monkeypatch.setattr(ctrl, "sync_enabled", lambda on: calls.append(on))
    ctrl._user_mode_off = True          # 模拟"退出音乐模式"残留
    ctrl._sampling = True               # 模拟忙门卡死
    ctrl._revive("测试")
    assert ctrl._user_mode_off is False, "复活要清掉临时退出标志"
    assert ctrl._sampling is False, "复活要结清卡住的忙门"
    assert calls == [True], "复活后必须按当前配置重新启用"


def test_pause_does_not_advance_heartbeat(controller, clock):
    ctrl, _host = controller
    ctrl.sync_enabled(True)
    before = ctrl._last_progress_at
    clock["now"] += 60
    ctrl.pause()
    assert ctrl._last_progress_at == before, "隐藏期间不算进展，恢复显示后从零计时"


def test_watchdog_timer_is_running(controller):
    ctrl, _host = controller
    assert ctrl._watchdog.isActive(), "看门狗必须常驻（开销只有一个 5s 定时器）"
