# -*- coding: utf-8 -*-
"""网易云窗口标题源（不注册 SMTC 的播放器兜底）。

2026-10-23 实测：网易云音乐 3.1.42 在 ``get_sessions()`` 里**一个会话都没有**
（在播时也只有 chrome.exe），SMTC 链路看不见它 → 歌词永远等不到曲目、右键
「音乐 → 歌词对齐」恒灰。

修法：SMTC 没有在播会话时，读网易云主窗口标题（``歌名 - 歌手``）当补充源，
并用系统音频峰值否决"暂停"（标题会停在上一首）。
"""
from __future__ import annotations

import pytest

from pet import foobar_playing, music_detect, netease_playing, now_playing


def _fake_titles(monkeypatch, titles):
    monkeypatch.setattr(foobar_playing, "pids_for", lambda exe, use_cache=True: (4321,))
    monkeypatch.setattr(foobar_playing, "_window_titles_for_pids", lambda pids: list(titles))


def test_netease_reads_title_and_artist(monkeypatch):
    _fake_titles(monkeypatch, ["无名(写给杨乃文的歌) - 张震岳"])
    parsed = netease_playing.read_track()
    assert parsed == ("无名(写给杨乃文的歌)", "张震岳")


def test_title_splits_on_the_last_separator():
    """歌名里允许出现 ``" - "``：歌手取最后一段。"""
    assert netease_playing.parse_window_title("A - B - C") == ("A - B", "C")


def test_title_without_separator_is_unusable():
    assert netease_playing.parse_window_title("只有歌名") is None
    assert netease_playing.parse_window_title("") is None
    assert netease_playing.parse_window_title(" - 歌手") is None


def test_netease_returns_none_without_windows(monkeypatch):
    _fake_titles(monkeypatch, [])
    assert netease_playing.read_track() is None


def test_netease_returns_none_when_process_absent(monkeypatch):
    monkeypatch.setattr(foobar_playing, "pids_for", lambda exe, use_cache=True: ())
    assert netease_playing.read_track() is None


def test_playback_marks_estimated_position(monkeypatch):
    """位置必须是 None（无进度源）——控制器据此走本地时钟推算 + 允许手动对齐。"""
    _fake_titles(monkeypatch, ["晴天 - 周杰伦"])
    monkeypatch.setattr(music_detect, "audio_peak_level", lambda: 0.2)
    playback = now_playing._read_netease_playback()
    assert playback is not None
    assert playback.position is None
    assert playback.app_id == netease_playing.NETEASE_APP_ID
    assert playback.track.playing is True
    assert "晴天" in playback.track.title


def test_paused_music_is_vetoed_by_audio_peak(monkeypatch):
    """标题停在上一首、实际没出声 → 不能当成在播（否则歌词继续滚）。"""
    _fake_titles(monkeypatch, ["晴天 - 周杰伦"])
    monkeypatch.setattr(music_detect, "audio_peak_level", lambda: 0.0)
    assert now_playing._read_netease_playback() is None


def test_unknown_peak_falls_back_to_playing(monkeypatch):
    """峰值读不到（None）时按在播处理：宁可多显示一次，别把读不到当暂停。"""
    _fake_titles(monkeypatch, ["晴天 - 周杰伦"])
    monkeypatch.setattr(music_detect, "audio_peak_level", lambda: None)
    assert now_playing._read_netease_playback() is not None
