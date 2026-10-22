# -*- coding: utf-8 -*-
"""天气降级链回归（2026-10-22）：街道级码失效 / 镇级标签搜不到。

两个真机复现的缺陷：

1. 检索会把「马桥镇 · 上海」解析成 **12 位街道码** ``101020200005``；``sk_2d``
   对它 302 到 404 页面，解析必然失败。旧实现的"按码失败 → 回退检索"又把同一个
   坏码选回来，于是气泡只剩「返回数据无效：返回数据无效」。
2. 源 B 只拿标签前半段（马桥镇）去 GeoNames，镇名查不到就整源失败，明明标签
   后半段（上海）一定有。

修法见 ``pet/weather/__init__.py``：``cn_code_variants`` 退 9 位区县码并逐个
试候选；``open_meteo_query_names`` 按基础名 → 标签两侧 → 全串逐个试。
"""
from __future__ import annotations

import json

from pet import weather as W

CN_CURRENT_闵行 = (
    'var dataSK={"nameen":"minhang","cityname":"闵行","city":"101020200","temp":"22.1",'
    '"tempf":"71.8","WD":"东风","wde":"E","WS":"2级","SD":"47%","time":"15:05",'
    '"weather":"多云"}'
)
OM_GEOCODE = json.dumps(
    {"results": [{"id": 1, "name": "上海", "latitude": 31.22, "longitude": 121.46,
                  "country_code": "CN"}]},
    ensure_ascii=False,
)
OM_CURRENT = json.dumps(
    {"current": {"time": "2026-10-22T15:05", "temperature_2m": 22.1,
                 "relative_humidity_2m": 47, "wind_speed_10m": 7.2,
                 "wind_direction_10m": 90, "weather_code": 2}},
    ensure_ascii=False,
)


class _FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers, *, use_proxy, timeout):
        self.calls.append(url)
        for key, value in self.routes:
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"未预期的请求：{url}")

    def urls(self):
        return list(self.calls)


def _client(http):
    return W.WeatherClient(http=http)


def test_street_level_code_falls_back_to_its_district_prefix():
    """12 位街道码 302→404：必须退到 9 位区县码再取，而不是把坏码再选一次。"""
    http = _FakeHttp([
        ("d1.weather.com.cn/sk_2d/101020200005", "<html>404</html>"),
        ("d1.weather.com.cn/sk_2d/101020200", CN_CURRENT_闵行),
    ])
    reading = _client(http).fetch("马桥镇 · 上海", code="101020200005")

    assert reading.city == "闵行"
    assert reading.temperature == "22.1℃"
    assert reading.source == W.SOURCE_CN
    assert http.urls() == [
        "http://d1.weather.com.cn/sk_2d/101020200005.html",
        "http://d1.weather.com.cn/sk_2d/101020200.html",
    ]
    assert not any("toy1.weather.com.cn" in url for url in http.urls()), (
        "退到区县码就能取到数据时，不应该再走城市检索"
    )


def test_code_variants_keep_short_codes_untouched():
    assert W.cn_code_variants("101020200") == ("101020200",)
    assert W.cn_code_variants("101020200005") == ("101020200005", "101020200")
    assert W.cn_code_variants("") == ()
    assert W.cn_code_variants("10121070101A") == ("10121070101A",)


def test_open_meteo_retries_with_the_region_part_when_the_town_is_unknown():
    """「马桥镇 · 上海」：镇名 GeoNames 没有，必须退到「上海」再查一次。"""
    http = _FakeHttp([
        ("toy1.weather.com.cn", TimeoutError("timed out")),
        ("name=%E9%A9%AC%E6%A1%A5%E9%95%87", "{}"),          # 马桥镇：查不到
        ("geocoding-api.open-meteo.com", OM_GEOCODE),          # 上海：查得到
        ("api.open-meteo.com", OM_CURRENT),
    ])
    reading = _client(http).fetch("马桥镇 · 上海")

    assert reading.source == W.SOURCE_OPEN_METEO
    geocodes = [url for url in http.urls() if "geocoding" in url]
    assert len(geocodes) == 2, geocodes
    assert "%E9%A9%AC%E6%A1%A5%E9%95%87" in geocodes[0]     # 先查镇名
    assert "%E4%B8%8A%E6%B5%B7" in geocodes[1]              # 再查城市名


def test_open_meteo_query_names_put_base_name_first():
    assert W.open_meteo_query_names("马桥镇 · 上海") == ("马桥镇", "上海", "马桥镇 · 上海")
    assert W.open_meteo_query_names("北京") == ("北京",)
