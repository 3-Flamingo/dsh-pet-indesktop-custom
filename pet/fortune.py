# -*- coding: utf-8 -*-
"""算命对象档案，以及把本机排盘收成可交给对话模型的短文。

四柱只走 ``pet.bazi.pai_pan``（bazi-skill，MIT）。这里不调用任何在线排盘服务。
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .bazi import pai_pan

MAX_PROFILES = 12
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
SHICHEN = ("子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥")
SHICHEN_LABELS = (
    ("", "不确定"),
    ("子", "子时（23:00–01:00）"),
    ("丑", "丑时（01:00–03:00）"),
    ("寅", "寅时（03:00–05:00）"),
    ("卯", "卯时（05:00–07:00）"),
    ("辰", "辰时（07:00–09:00）"),
    ("巳", "巳时（09:00–11:00）"),
    ("午", "午时（11:00–13:00）"),
    ("未", "未时（13:00–15:00）"),
    ("申", "申时（15:00–17:00）"),
    ("酉", "酉时（17:00–19:00）"),
    ("戌", "戌时（19:00–21:00）"),
    ("亥", "亥时（21:00–23:00）"),
)

TOPICS = (
    ("daily", "每日运势"),
    ("love", "情感"),
    ("wealth", "财运"),
    ("career", "事业"),
    ("health", "健康"),
)

_TOPIC_FOCUS = {
    "daily": "只看今天这一天：心情、顺手的事、容易马虎的地方。对照当前大运和今年的流年，不要把一辈子复述一遍。",
    "love": "看感情里的相处方式、容易别扭的点、这段时间更适合怎么相处。不要断言某个人一定会怎样，也不要鼓动去控制对方。",
    "wealth": "看求财的节奏、宜稳还是宜试、近期少碰的花钱方式。不要给具体投资标的，不要承诺赚多少。",
    "career": "看做事的风格、比较顺的方向、近期宜进还是宜守。不要断言一定会升职或失业。",
    "health": "只按传统五行说说容易累的地方，当成生活习惯提醒。先说明这不是诊断，不舒服要去看医生。不要开方，不要建议停药或换药。",
}


class ChartError(Exception):
    """出生信息不足以排盘，或农历日期在历法里不存在。"""


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return False


def _parse_ymd(text):
    raw = str(text or "").strip().replace("/", "-").replace(".", "-")
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return None
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


def _clean_text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_profile(raw) -> dict | None:
    """单条档案。缺字段、性别或日期不合法时丢掉整条，避免脏配置把菜单撑坏。"""
    if not isinstance(raw, dict):
        return None
    profile_id = str(raw.get("id") or "").strip()
    if not _ID_RE.fullmatch(profile_id):
        return None
    name = _clean_text(raw.get("name"), 16)
    if not name:
        return None
    sex = str(raw.get("sex") or "").strip()
    if sex not in ("男", "女"):
        return None
    calendar = str(raw.get("calendar") or "").strip()
    if calendar not in ("solar", "lunar"):
        return None
    numbers = _parse_ymd(raw.get("date"))
    if numbers is None:
        return None
    year, month, day = numbers
    if calendar == "solar":
        try:
            date(year, month, day)
        except ValueError:
            return None
    elif day > 30:
        return None
    shichen = str(raw.get("shichen") or "").strip()
    if shichen not in ("", *SHICHEN):
        return None
    return {
        "id": profile_id,
        "name": name,
        "sex": sex,
        "calendar": calendar,
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "leap": _as_bool(raw.get("leap")) and calendar == "lunar",
        "shichen": shichen,
        "place": _clean_text(raw.get("place"), 24),
    }


def clean_fortune_profiles(raw) -> list:
    if not isinstance(raw, list):
        return []
    profiles = []
    seen = set()
    for item in raw:
        profile = normalize_profile(item)
        if profile is None or profile["id"] in seen:
            continue
        seen.add(profile["id"])
        profiles.append(profile)
        if len(profiles) >= MAX_PROFILES:
            break
    return profiles


def load_profiles(cfg) -> list:
    raw = []
    getter = getattr(cfg, "get", None)
    if callable(getter):
        raw = getter("fortune_profiles", [])
    return clean_fortune_profiles(raw)


def explain_profile(fields: dict, *, profile_id: str) -> tuple[dict | None, str]:
    """给管理窗口用的校验：失败时返回能直接显示的原因。"""
    name = _clean_text(fields.get("name"), 40)
    if not name:
        return None, "先写一个称呼"
    if len(name) > 16:
        return None, "称呼最多 16 个字"
    sex = str(fields.get("sex") or "").strip()
    if sex not in ("男", "女"):
        return None, "选一下性别"
    calendar = str(fields.get("calendar") or "").strip()
    if calendar not in ("solar", "lunar"):
        return None, "选阳历或农历"
    numbers = _parse_ymd(fields.get("date"))
    if numbers is None:
        return None, "生日写成 1990-05-15，年份要在 1900 到 2100 之间"
    year, month, day = numbers
    if calendar == "solar":
        try:
            date(year, month, day)
        except ValueError:
            return None, "这个阳历日期不存在"
    elif day > 30:
        return None, "农历日期的日要在 1 到 30 之间"
    shichen = str(fields.get("shichen") or "").strip()
    if shichen not in ("", *SHICHEN):
        return None, "时辰没选对"
    place = _clean_text(fields.get("place"), 40)
    if len(place) > 24:
        return None, "出生地最多 24 个字"
    draft = {
        "id": profile_id,
        "name": name,
        "sex": sex,
        "calendar": calendar,
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "leap": _as_bool(fields.get("leap")) and calendar == "lunar",
        "shichen": shichen,
        "place": place,
    }
    profile = normalize_profile(draft)
    if profile is None:
        return None, "这条信息没能存下来"
    if profile["calendar"] == "lunar":
        try:
            pai_pan.lunar_to_solar(year, month, day, leap=profile["leap"])
        except ValueError as exc:
            return None, str(exc)
    return profile, ""


def profile_menu_label(profile: dict, profiles: list) -> str:
    name = profile["name"]
    if sum(item["name"] == name for item in profiles) > 1:
        return f"{name}（{profile['date']}）"
    return name


def compute_chart(profile, *, now=None) -> dict:
    normalized = normalize_profile(profile)
    if normalized is None:
        raise ChartError("出生信息不完整")
    year, month, day = (int(part) for part in normalized["date"].split("-"))
    lunar_display = None
    if normalized["calendar"] == "lunar":
        try:
            solar = pai_pan.lunar_to_solar(year, month, day, leap=normalized["leap"])
        except ValueError as exc:
            raise ChartError(str(exc)) from exc
        lunar_display = pai_pan.format_lunar(year, month, day, normalized["leap"])
    else:
        solar = date(year, month, day)
    if not 1900 <= solar.year <= 2100:
        raise ChartError("只支持 1900 到 2100 年")
    return pai_pan.compute(
        solar,
        shichen=normalized["shichen"] or None,
        sex=normalized["sex"],
        place=normalized["place"] or None,
        lunar_display=lunar_display,
        now=now,
    )


def _pillar_line(title: str, cell) -> str:
    gan, zhi, god, hidden = cell
    return f"{title} {gan}{zhi} 十神{god} 藏干{hidden}"


def render_chart(profile, *, now=None) -> str:
    result = compute_chart(profile, now=now)
    pillars = result["pillars"]
    lines = [
        f"阳历：{result['solar_text']}",
        f"农历：{result['lunar_text']}",
        f"时辰：{result['shichen_text']}",
        f"性别：{result['sex']}",
        f"子时：{result['zishi']}",
    ]
    if result.get("place"):
        lines.append(f"出生地：{result['place']}（只记录，没有换算真太阳时）")
    lines.append("四柱：")
    lines.append(_pillar_line("年柱", pillars["year"]))
    lines.append(_pillar_line("月柱", pillars["month"]))
    lines.append(_pillar_line("日柱", pillars["day"]))
    lines.append(_pillar_line("时柱", pillars["hour"]))
    direction = "顺排" if result["forward"] else "逆排"
    lines.append(f"大运：{direction}，起运 {result['qiyun_text']}")
    for seq, ages, gz in result["dayun_rows"]:
        lines.append(f"  {seq} {ages} {gz}")
    current = int(result["current_year"])
    nearby = "，".join(
        f"{year}年{pai_pan.liunian_gz(year)}" for year in (current - 1, current, current + 1)
    )
    lines.append(f"当前流年：{current}年{result['current_gz']}")
    lines.append(f"邻近流年：{nearby}")
    shensha = [str(item) for item in result.get("shensha_lines") or []]
    lines.append("神煞：" if shensha else "神煞：这张表没有命中")
    lines.extend(shensha)
    warnings = []
    for item in result.get("warnings") or []:
        text = str(item)
        if text not in warnings:
            warnings.append(text)
    lines.append("排盘提示：" + ("；".join(warnings) if warnings else "无"))
    return "\n".join(lines)


def beijing_today(now=None):
    moment = now if now is not None else datetime.now(pai_pan.BJ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=pai_pan.BJ)
    return moment.astimezone(pai_pan.BJ).date()


def build_prompt(profile, topic_id: str, chart: str, *, today=None) -> str:
    labels = dict(TOPICS)
    if topic_id not in labels:
        raise ChartError("没有这个算命项目")
    normalized = normalize_profile(profile)
    if normalized is None:
        raise ChartError("出生信息不完整")
    day = today or beijing_today()
    lines = [
        f"请给「{normalized['name']}」看「{labels[topic_id]}」。",
        f"今天是北京时间 {day.isoformat()}。",
        _TOPIC_FOCUS[topic_id],
        "下面这张盘是已经算好的，请直接用它。不要重排四柱，不要改任何一个干支。",
        "用你平时跟主人说话的口气，先说一句结论，再讲两三句原因。",
        "这是传统文化娱乐，不是医疗、法律或投资建议。",
    ]
    if not normalized["shichen"]:
        lines.append("时辰没有填，时柱是未知，不要把时柱说死。")
    if normalized["shichen"] == "子":
        lines.append("只知道是子时、没有钟点，盘按当天早子时（0点后）排。如果其实是 23 点后的晚子时，日柱会差一天，先把这个边界说出来。")
    if normalized["place"]:
        lines.append("出生地只是记录，没有换算真太阳时。时刻如果卡在时辰交界，不要把时柱说死。")
    lines.append("")
    lines.append(chart)
    return "\n".join(lines)
