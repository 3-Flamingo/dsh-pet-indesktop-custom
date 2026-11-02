# -*- coding: utf-8 -*-
"""网易云音乐的曲目来源：进程 + 主窗口标题。

**为什么需要它**：网易云音乐 3.x 在这台机器上**根本不注册 SMTC**（2026-10-23
实测：``get_sessions()`` 只有一个 chrome.exe 会话，网易云在播但零会话），所以
``now_playing`` 的 SMTC 采样看不见它——歌词永远等不到曲目，右键「音乐 → 歌词
对齐」也就一直是灰的。

**它的地位与 foobar 源相同**：SMTC 有在播会话时绝不问它；只有歌词链路显式传
``allow_netease=True`` 且 SMTC 没有在播会话时才作为补充源（见
``now_playing._read_netease_playback``）。

**播放控制不在这里**。暂停 / 切歌走 ``now_playing.toggle_play_pause`` /
``skip_track``：没有正在播放的 SMTC 会话时改发系统多媒体键。

**窗口标题格式**：网易云主窗口标题实测就是 ``歌名 - 歌手``（例：
``无名(写给杨乃文的歌) - 张震岳``），切歌时随之变化；暂停时标题不变、也没有
任何进度字段。所以：

- 曲目信息按**最后一个** ``" - "`` 切分（歌名里允许出现 ``" - "``）——这一点与
  foobar 不同：foobar 的标题是用户可配置的格式串，只能"不猜"，网易云的格式是
  稳定的，猜得动就该猜；
- 播放状态**只能靠系统音频峰值**判断（``music_detect.audio_peak_level``）——
  标题停在上一首但没在播时，不应该继续滚歌词。这是本能力的已知局限：有别的
  应用正在出声时会被当成"在播"。
"""
from __future__ import annotations

import re

from . import foobar_playing

NETEASE_EXE = "cloudmusic.exe"
#: 作为 ``Playback.app_id`` 的取值：刻意不是 SMTC 会话 id（同 foobar 的口径），
#: 让调用方能区分"这条来自窗口标题"。
NETEASE_APP_ID = NETEASE_EXE

#: 网易云窗口标题里歌名与歌手的分隔符（实测固定为这个写法，前后各一个空格）。
_TITLE_SEPARATOR = " - "


#: 标题里出现就**不是正在播放的歌**的界面文案。网易云在"没在放歌"时主窗口标题
#: 落在这些页面/弹窗上（歌单、我的音乐、搜索、弹层……），而标题格式又与曲目
#: 完全一样（``全部 - 季然/听潮阁`` 看着就像一首歌），2026-11-02 实测就是这么
#: 被当成曲目、拿标题去搜歌词搜不到，整条链路看起来"时好时坏"。
_NOT_PLAYING_RE = re.compile(
    r"(VIP|会员|专享|试听|已购买|付费|特权|高品质|无损|杜比|车载|"
    r"^全部$|^音乐$|^我的$|^收藏$|^歌单$|^推荐$|^每日$|^私人$|^心动$|"
    r"^发现$|^搜索$|^排行榜$|^下载$|^直播$|^播客$|^听书$|"
    r"^新建标签页$|^新标签页$|^New Tab$|"
    r"Settings|设置|关于|登录|注册)",
    re.I,
)
#: 浏览器类标题（含站点名）也一律不认：那是浏览器窗口，不是播放器曲目。
_SITE_NOISE_RE = re.compile(
    r"(Microsoft\u200b?\s*Edge|Google\s*Chrome|Mozilla\s*Firefox|哔哩哔哩|bilibili)", re.I
)


def parse_window_title(window_title: str) -> tuple[str, str] | None:
    """``歌名 - 歌手`` → ``(歌名, 歌手)``；切不出两边、或不像正在播放的歌时返回 ``None``。

    按**最后一个**分隔符切：``"A - B - C"`` 里 C 是歌手，A - B 是歌名。

    为什么要否决而非只切分：网易云没在放歌时标题会变成页面名（``全部 - 季然/听潮阁``、
    ``VIP 专享``、``新建标签页``…），切分照样成功，但拿它去搜歌词就是白发一次
    请求、并且把"上一首"或垃圾标题当成当前曲目。
    """
    text = str(window_title or "").strip()
    if not text:
        return None
    index = text.rfind(_TITLE_SEPARATOR)
    if index <= 0:
        return None
    title = text[:index].strip()
    artist = text[index + len(_TITLE_SEPARATOR):].strip()
    if not title or not artist:
        return None
    if _SITE_NOISE_RE.search(text):
        return None
    if _NOT_PLAYING_RE.search(title) or _NOT_PLAYING_RE.search(artist):
        return None
    return title, artist


def read_track(title_format: str = "") -> tuple[str, str] | None:
    """读网易云正在播的 ``(歌名, 歌手)``；读不到返回 ``None``。

    ``title_format`` 仅为与 :func:`foobar_playing.read_track` 签名对齐，网易云
    不需要（格式固定）。多条候选里取最长的一条——皮肤/独立窗口的标题更短。

    任何异常都按"读不到"处理——歌词只是锦上添花，不能因为第三方程序影响桌宠。
    """
    try:
        titles = foobar_playing.window_titles_for(NETEASE_EXE)
    except Exception:
        return None
    candidates: list[tuple[int, tuple[str, str]]] = []
    for title in titles[:8]:
        parsed = parse_window_title(title)
        if parsed is not None:
            candidates.append((len(title), parsed))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
