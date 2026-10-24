# -*- coding: utf-8 -*-
"""AI算命：档案、本机四柱、菜单层级。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMenu

from pet.config import Config
from pet.context_menus.registry import ACTION_LABELS, MENU_ACTIONS
from pet.fortune import build_prompt, compute_chart, render_chart
from pet.fortune_dialog import FortuneProfilesDialog
from pet.fortune_menu import add_fortune_menu, ask_fortune
from pet.sprite_menu_facade import SpriteMenuFacade


def _app():
    return QApplication.instance() or QApplication([])


def _profile(**overrides):
    data = {
        "id": "person1990",
        "name": "小鲸",
        "sex": "男",
        "calendar": "solar",
        "date": "1990-05-15",
        "leap": False,
        "shichen": "午",
        "place": "北京",
    }
    data.update(overrides)
    return data


class _Cfg:
    def __init__(self, profiles):
        self.data = {"fortune_profiles": profiles}

    def get(self, key, default=None):
        return self.data.get(key, default)


class _Pet:
    def __init__(self, profiles):
        self.cfg = _Cfg(profiles)
        self.asked = None
        self.bubbles = []
        self.on_open_chat = lambda: None

    def on_fortune_ask(self, text):
        self.asked = text

    def show_bubble(self, text, duration_ms=0):
        self.bubbles.append(text)


def _pillars(result):
    pillars = result["pillars"]
    return tuple(pillars[key][0] + pillars[key][1] for key in ("year", "month", "day", "hour"))


def test_solar_anchor_matches_bazi_skill_example():
    result = compute_chart(_profile())
    assert _pillars(result) == ("庚午", "辛巳", "庚辰", "壬午")


def test_lunar_anchor_matches_the_same_solar_day():
    lunar = compute_chart(_profile(
        id="lunar1990", calendar="lunar", date="1990-04-21", leap=False,
    ))
    assert _pillars(lunar) == _pillars(compute_chart(_profile()))


def test_prompt_uses_the_computed_chart_and_refuses_a_new_one():
    profile = _profile()
    prompt = build_prompt(profile, "daily", render_chart(profile))
    assert "庚午" in prompt
    assert "辛巳" in prompt
    assert "庚辰" in prompt
    assert "壬午" in prompt
    assert "每日运势" in prompt
    assert "不要重排四柱" in prompt
    assert "不是医疗、法律或投资建议" in prompt


def test_health_prompt_says_it_is_not_a_diagnosis():
    profile = _profile()
    prompt = build_prompt(profile, "health", render_chart(profile))
    assert "这不是诊断" in prompt


def test_unknown_hour_is_not_invented():
    result = compute_chart(_profile(shichen=""))
    assert result["pillars"]["hour"][0] == "未知"
    prompt = build_prompt(_profile(shichen=""), "career", render_chart(_profile(shichen="")))
    assert "时柱是未知" in prompt


def test_invalid_profile_is_dropped_and_roundtrips(tmp_path):
    config = Config(tmp_path)
    config.set("fortune_profiles", [_profile(), {"id": "nope"}, "bad"])
    assert [item["id"] for item in config.get("fortune_profiles")] == ["person1990"]
    assert config.save()
    restored = Config(tmp_path)
    assert restored.get("fortune_profiles")[0]["name"] == "小鲸"
    assert restored.get("fortune_profiles")[0]["shichen"] == "午"


def test_dialog_saves_a_person(tmp_path):
    _app()
    config = Config(tmp_path)
    dialog = FortuneProfilesDialog(config)
    try:
        dialog._name.setText("小鲸")
        dialog._date.setText("1990-05-15")
        dialog._shichen.setCurrentIndex(dialog._shichen.findData("午"))
        dialog._place.setText("北京")
        dialog._save()
        assert dialog._status.text().startswith("已保存")
    finally:
        dialog.close()
    restored = Config(tmp_path)
    saved = restored.get("fortune_profiles")
    assert saved[0]["name"] == "小鲸"
    assert saved[0]["sex"] == "男"
    assert saved[0]["date"] == "1990-05-15"
    assert saved[0]["shichen"] == "午"


def test_menu_lists_people_then_topics_and_sends_the_chart():
    _app()
    other = _profile(id="person1991", name="小鲸", date="1991-05-15")
    pet = _Pet([_profile(), other])
    menu = QMenu()
    try:
        built = add_fortune_menu(menu, pet)
        labels = [action.text() for action in built.actions() if not action.isSeparator()]
        assert labels[0] == "管理算命对象…"
        assert "小鲸（1990-05-15）" in labels
        assert "小鲸（1991-05-15）" in labels
        person = next(action.menu() for action in built.actions() if action.text() == "小鲸（1990-05-15）")
        topics = [action.text() for action in person.actions()]
        assert topics == ["每日运势", "情感", "财运", "事业", "健康"]
        person.actions()[0].trigger()
        assert pet.asked is not None
        assert "庚午" in pet.asked
        assert "每日运势" in pet.asked
        assert "不要重排四柱" in pet.asked
    finally:
        menu.close()


def test_bad_leap_month_does_not_open_chat():
    pet = _Pet([_profile(
        id="badleap01", calendar="lunar", date="1990-06-01", leap=True,
    )])
    ask_fortune(pet, "badleap01", "daily")
    assert pet.asked is None
    assert pet.bubbles
    assert "闰" in pet.bubbles[0]


def test_fortune_entry_follows_chat_and_is_in_the_default_menu():
    class Silent:
        on_open_chat = None

    spec = MENU_ACTIONS._specs["ai_fortune"]
    assert spec.available(Silent()) is False
    Silent.on_open_chat = lambda: None
    assert spec.available(Silent()) is True
    assert ACTION_LABELS["ai_fortune"] == "AI算命"
    assert isinstance(getattr(SpriteMenuFacade, "on_fortune_ask"), property)
    assert isinstance(getattr(SpriteMenuFacade, "on_fortune_manage"), property)
