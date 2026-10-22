# -*- coding: utf-8 -*-
"""右键菜单「点外部也收起」回归（Windows 无激活窗口场景）。

缺陷：桌宠窗带 ``WS_EX_NOACTIVATE``（issue #98，不抢焦点），QMenu 的 popup 因此
也不激活，Qt 原生"点菜单外部自动关闭"依赖激活态，永远不触发；点别的应用更是
不进本进程事件循环。修法见 ``pet/menu_dismiss.py``：``run_menu`` 在 exec 期间
轮询全局左键。

为什么要 ``run_menu`` 而不是包 ``QMenu.exec``：PySide6 里 ``QMenu.exec`` 是 C++
方法，Python 层赋值实测无效（真机验证包装器从不被调用）。

本用例用**注入探针**驱动，不需要真实鼠标，也不弹真实菜单：

1. 菜单外的"新的按下"→ 收起菜单并停表；
2. 菜单内的按下 → 不动（交给 Qt 选中）；
3. 启动瞬间已按住的按键（就是打开菜单的那次点击）→ 不算外部点击；
4. 探针取不到坐标（None）→ 不崩、不误关；
5. ``run_menu`` 返回 exec 的返回值，并且无论正常返回还是看门狗启动失败都
   会把菜单弹出来、事后停表。
"""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import menu_dismiss
from pet.menu_dismiss import OutsideClickCloser


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def menu(app):
    widget = QMenu()
    widget.addAction("示例项")
    widget.move(200, 200)
    widget.resize(240, 160)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _closer(menu, events):
    """events 是探针返回值的队列；用完后一直重复最后一项。"""
    queue = list(events)

    def probe():
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    return OutsideClickCloser(menu, probe=probe, interval_ms=10_000)


def _menu_point(menu):
    rect = menu.frameGeometry()
    return rect.center().x(), rect.center().y()


def _outside_point(menu):
    rect = menu.frameGeometry()
    return rect.left() - 50, rect.top() - 50


def test_outside_press_closes_menu(app, menu):
    closer = _closer(menu, [(False, (0, 0)), (True, _outside_point(menu))])
    closer.start()
    assert menu.isVisible()
    closer.poll_once()
    assert not menu.isVisible(), "菜单外的左键按下必须收起菜单"
    assert not closer._timer.isActive(), "收起后必须停表"


def test_inside_press_keeps_menu(app, menu):
    closer = _closer(menu, [(False, (0, 0)), (True, _menu_point(menu))])
    closer.start()
    closer.poll_once()
    assert menu.isVisible(), "菜单内的按下交给 Qt 处理，不应由看门狗关闭"


def test_press_already_down_at_start_is_ignored(app, menu):
    """打开菜单的那次左键（或按住不放）不能被当成"外部点击"。"""
    closer = _closer(menu, [(True, _outside_point(menu)), (True, _outside_point(menu))])
    closer.start()
    closer.poll_once()
    assert menu.isVisible()
    assert not closer._timer.isActive(), "起始已按住时不应启动轮询"


def test_missing_cursor_position_does_not_close(app, menu):
    closer = _closer(menu, [(False, (0, 0)), (True, None), (False, None)])
    closer.start()
    closer.poll_once()
    assert menu.isVisible(), "拿不到坐标时宁可不关"


class _FakeMenu:
    def __init__(self):
        self.positions = []

    def exec(self, position):
        self.positions.append(position)
        return "sentinel"


def test_run_menu_returns_exec_result_and_manages_guard(monkeypatch):
    events = []

    class _Recorder:
        def __init__(self, menu, *, probe=None, interval_ms=menu_dismiss.POLL_INTERVAL_MS):
            events.append(("init", menu))

        def start(self):
            events.append(("start", None))

        def stop(self):
            events.append(("stop", None))

    monkeypatch.setattr(menu_dismiss, "OutsideClickCloser", _Recorder)
    target = _FakeMenu()
    assert menu_dismiss.run_menu(target, (12, 34)) == "sentinel"
    assert target.positions == [(12, 34)]
    kinds = [kind for kind, _ in events]
    assert kinds == ["init", "start", "stop"], events


def test_run_menu_still_shows_menu_when_guard_fails(monkeypatch):
    class _Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("guard unavailable")

    monkeypatch.setattr(menu_dismiss, "OutsideClickCloser", _Boom)
    target = _FakeMenu()
    assert menu_dismiss.run_menu(target, (0, 0)) == "sentinel"


def test_real_probe_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert menu_dismiss.windows_probe() == (False, None)
