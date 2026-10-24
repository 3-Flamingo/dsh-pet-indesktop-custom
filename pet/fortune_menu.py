# -*- coding: utf-8 -*-
"""右键菜单「AI算命」：先选人，再选项目，结果交给桌宠当前的对话模型。"""
from __future__ import annotations

import logging

from .context_menus.shared import add_action, add_submenu
from .fortune import TOPICS, ChartError, build_prompt, load_profiles, profile_menu_label, render_chart

log = logging.getLogger(__name__)


def _bubble(pet, text: str) -> None:
    for name in ("show_bubble", "_bubble"):
        fn = getattr(pet, name, None)
        if not callable(fn):
            continue
        try:
            fn(text, 6000)
            return
        except TypeError:
            try:
                fn(text)
                return
            except Exception:
                log.debug("算命提示没显示出来", exc_info=True)
        except Exception:
            log.debug("算命提示没显示出来", exc_info=True)


def _menu_text(text: str) -> str:
    return str(text).replace("&", "&&")


def ask_fortune(pet, profile_id: str, topic_id: str) -> None:
    profiles = load_profiles(getattr(pet, "cfg", None))
    profile = next((item for item in profiles if item["id"] == profile_id), None)
    if profile is None:
        _bubble(pet, "这个算命对象已经不在了，重新选一个")
        return
    if topic_id not in dict(TOPICS):
        return
    try:
        chart = render_chart(profile)
        prompt = build_prompt(profile, topic_id, chart)
    except ChartError as exc:
        _bubble(pet, str(exc))
        return
    except Exception:
        log.debug("排盘失败", exc_info=True)
        _bubble(pet, "排盘没算成，检查一下生日和时辰")
        return
    ask = getattr(pet, "on_fortune_ask", None)
    if not callable(ask):
        _bubble(pet, "对话还没开，先到设置里配好 AI 对话")
        return
    ask(prompt)


def _manage(pet) -> None:
    manage = getattr(pet, "on_fortune_manage", None)
    if callable(manage):
        manage()
        return
    _bubble(pet, "现在还不能编辑算命对象")


def add_fortune_menu(menu, pet):
    """「AI算命」→ 每个人 → 每日运势 / 情感 / 财运 / 事业 / 健康。"""
    sub = add_submenu(menu, "AI算命", "todo")
    add_action(sub, "管理算命对象…", "settings", lambda: _manage(pet), close_on_trigger=True)
    profiles = load_profiles(getattr(pet, "cfg", None))
    if not profiles:
        hint = sub.addAction("还没有算命对象")
        hint.setEnabled(False)
        return sub
    sub.addSeparator()
    for profile in profiles:
        person = add_submenu(sub, _menu_text(profile_menu_label(profile, profiles)))
        for topic_id, label in TOPICS:
            add_action(
                person,
                label,
                None,
                lambda pid=profile["id"], tid=topic_id: ask_fortune(pet, pid, tid),
                close_on_trigger=True,
            )
    return sub
