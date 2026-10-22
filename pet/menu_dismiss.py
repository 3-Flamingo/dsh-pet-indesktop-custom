# -*- coding: utf-8 -*-
"""右键菜单：点击菜单以外的地方也收起（Windows 专项）。

## 症状

右键桌宠弹出菜单后，点击菜单以外的任意位置（桌面、别的应用、任务栏）都不会
收起菜单，只有点击桌宠本身才关。

## 成因

桌宠叠层窗按 issue #98 置了 ``WS_EX_NOACTIVATE``——点击桌宠不抢前台、不夺
键盘焦点。代价是：``QMenu`` 的 popup 也跟着不激活，而 Qt 原生"点别处 →
popup 失活 / 丢鼠标抓取 → 自动关闭"这条路**依赖激活态**，因此永远走不到；
点别的应用更是根本不进本进程的事件循环。``docs/CONTEXT-MENU-RESEARCH`` 里
"点到菜单外部仍沿用 Qt 原生关闭行为"的假设，在 Windows + 不抢焦点窗口下
不成立。

## 做法

菜单 ``exec()`` 期间挂一个 30ms 定时器，轮询**全局**左键与光标位置：

* 只认"新的按下"（边沿触发）：起始时已经按住的不算，避免菜单刚弹出就被打开
  它的那次点击带走；
* 光标落在菜单树（根菜单 + 子菜单）几何之内时不动，交给 Qt 自己选中；
* 落在外面就 ``close()`` 并立刻停表。

不装全局钩子（``WH_MOUSE_LL`` 会拖慢全系统输入）、不抢焦点、不改窗口样式。
``exec()`` 返回后看门狗立即停止，平时零开销。

## 为什么是 ``run_menu`` 而不是包 ``QMenu.exec``

PySide6 的 ``QMenu.exec`` 是 C++ 方法，实测在 Python 层赋值
``QMenu.exec = wrapper`` 之后，``menu.exec(pos)`` **仍然走原生实现**（真机
验证：包装器从未被调用），所以在类上打补丁这条路不通。改成显式入口
:func:`run_menu`，由调用点替换 ``menu.exec(pos)``——行为等价，且可测。

非 Windows 平台 :func:`windows_probe` 返回空值，看门狗不会启动（那边 QMenu
的激活语义正常，沿用 Qt 原生行为）。
"""
from __future__ import annotations

import logging
import sys
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu

log = logging.getLogger(__name__)

#: 轮询间隔（毫秒）。30ms 对"点击后多久收起"无感，对帧率也可以忽略。
POLL_INTERVAL_MS = 30

#: 探针返回值：(左键是否按下, 光标全局坐标或 None)。
ProbeResult = Tuple[bool, Optional[Tuple[int, int]]]
Probe = Callable[[], ProbeResult]

_win32_state: dict = {}


def _load_win32():
    """惰性取 user32 并声明签名（64 位下坐标必须用 POINT，不能默认 int）。"""
    if _win32_state:
        return _win32_state.get("user32")
    user32 = None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        _win32_state["ctypes"] = ctypes
        _win32_state["wintypes"] = wintypes
    except Exception:  # noqa: BLE001 - 取不到 user32 就当作不支持
        log.debug("菜单外部点击：user32 不可用", exc_info=True)
        user32 = None
    _win32_state["user32"] = user32
    return user32


def windows_probe() -> ProbeResult:
    """真实探针：``GetAsyncKeyState(VK_LBUTTON)`` + ``GetCursorPos``。"""
    if sys.platform != "win32":
        return (False, None)
    user32 = _load_win32()
    if user32 is None:
        return (False, None)
    try:
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        point = _win32_state["wintypes"].POINT()
        if not user32.GetCursorPos(_win32_state["ctypes"].byref(point)):
            return (False, None)
        return (down, (int(point.x), int(point.y)))
    except Exception:  # noqa: BLE001 - 探针失败只意味着"这次没看见点击"
        log.debug("菜单外部点击：探针取值失败", exc_info=True)
        return (False, None)


class OutsideClickCloser(QObject):
    """菜单可见期间监听"菜单外的左键按下"，命中就收起菜单。

    探针可注入（测试用）；``poll_once`` 暴露单步驱动，测试不必等定时器。
    """

    def __init__(self, menu: QMenu, *, probe: Optional[Probe] = None,
                 interval_ms: int = POLL_INTERVAL_MS, parent: Optional[QObject] = None):
        super().__init__(parent if parent is not None else menu)
        self._menu = menu
        self._probe: Probe = probe or windows_probe
        self._was_down = False
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        self._timer.timeout.connect(self.poll_once)

    # ---- 生命周期
    def start(self) -> None:
        """开始监听；已有按键按下时先记账，避免把"打开菜单的那次点击"算进来。"""
        down, _position = self._probe()
        self._was_down = bool(down)
        if not self._was_down:
            self._timer.start()

    def stop(self) -> None:
        try:
            self._timer.stop()
        except RuntimeError:  # 底层对象已销毁
            pass

    # ---- 判定
    def _inside_menu_tree(self, x: int, y: int) -> bool:
        candidates = [self._menu]
        try:
            candidates.extend(self._menu.findChildren(QMenu))
        except RuntimeError:
            pass
        for candidate in candidates:
            try:
                if candidate.isVisible() and candidate.frameGeometry().contains(x, y):
                    return True
            except (RuntimeError, AttributeError):
                continue
        return False

    def poll_once(self) -> None:
        down, position = self._probe()
        if down and not self._was_down:
            self._was_down = True
            if position is not None and not self._inside_menu_tree(*position):
                self.stop()
                try:
                    self._menu.close()
                except RuntimeError:  # 菜单已先一步销毁
                    pass
            return
        if not down:
            self._was_down = False


def run_menu(menu: QMenu, position, *, probe: Optional[Probe] = None,
             interval_ms: int = POLL_INTERVAL_MS):
    """``menu.exec(position)`` + 菜单外点击收起。返回值与 ``QMenu.exec`` 一致。

    所有**右键菜单**的弹出都应走这里，而不是直接 ``menu.exec(...)``：桌宠窗
    不激活，Qt 原生的"点外部关闭"不会触发（见模块头部说明）。
    """
    closer = None
    try:
        closer = OutsideClickCloser(menu, probe=probe, interval_ms=interval_ms)
        closer.start()
    except Exception:  # noqa: BLE001 - 看门狗装不上也必须有菜单
        log.debug("菜单外部点击看门狗启动失败", exc_info=True)
        closer = None
    try:
        return menu.exec(position)
    finally:
        if closer is not None:
            closer.stop()
