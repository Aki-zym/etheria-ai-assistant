"""
post_click 后台点击通道测试（不依赖真实游戏窗口，mock win32）。

覆盖：消息序列 WM_MOUSEMOVE → LBUTTONDOWN → LBUTTONUP（与真机验证一致）、
被遮挡（前台是别的窗口）时绝不 SetForegroundWindow（全后台，Cindy 前台不被打扰）、
PostMessage 抛错（如 UIPI 拒绝）回落 click_window。
"""
import os
import sys
import ctypes
from types import ModuleType
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32con
import pytest

import core._base.input as input_mod


GAME_HWND = 1234
OTHER_FG_HWND = 999   # 前台是别的窗口 → 游戏窗被遮挡场景


def _make_win32(fg=OTHER_FG_HWND):
    """win32gui/win32api 桩：ScreenToClient → (100,200)，前台窗口为 fg。"""
    gui = MagicMock()
    gui.ScreenToClient.return_value = (100, 200)
    gui.GetForegroundWindow.return_value = fg
    api = MagicMock()
    api.MAKELONG.side_effect = lambda lo, hi: (hi << 16) | lo
    return gui, api


def _install(monkeypatch, fg=OTHER_FG_HWND):
    """注入桩：post_click 函数内 import 的 win32gui/win32api、睡眠与 ctypes.windll
    （旧版被遮挡补丁正是走 ctypes.windll.user32.SetForegroundWindow）。"""
    gui, api = _make_win32(fg)
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setattr(input_mod, "time", MagicMock())  # 不真睡
    fake_windll = MagicMock()
    monkeypatch.setattr(ctypes, "windll", fake_windll)
    return gui, api, fake_windll


def test_message_order_includes_mousemove(monkeypatch):
    gui, api, _ = _install(monkeypatch)

    input_mod.post_click(GAME_HWND, 300, 400)

    msgs = [c.args[1] for c in gui.PostMessage.call_args_list]
    assert msgs == [
        win32con.WM_ACTIVATE,
        win32con.WM_ACTIVATEAPP,
        win32con.WM_MOUSEMOVE,
        win32con.WM_LBUTTONDOWN,
        win32con.WM_LBUTTONUP,
    ]
    # 激活消息带 WA_ACTIVE/1，鼠标消息 lparam 全部为 MAKELONG(client_x=100, client_y=200)
    assert gui.PostMessage.call_args_list[0].args[2] == win32con.WA_ACTIVE
    assert gui.PostMessage.call_args_list[1].args[2] == 1
    lparam = (200 << 16) | 100
    for c in gui.PostMessage.call_args_list[2:]:
        assert c.args[3] == lparam
    # DOWN 带按下态，UP 无
    assert gui.PostMessage.call_args_list[3].args[2] == win32con.MK_LBUTTON
    assert gui.PostMessage.call_args_list[4].args[2] == 0


def test_occluded_never_grabs_foreground(monkeypatch):
    """游戏窗被遮挡（前台是别的窗口）：只 PostMessage，两条路都不抢前台。"""
    gui, api, fake_windll = _install(monkeypatch, fg=OTHER_FG_HWND)

    input_mod.post_click(GAME_HWND, 300, 400)

    gui.SetForegroundWindow.assert_not_called()
    fake_windll.user32.SetForegroundWindow.assert_not_called()
    assert gui.PostMessage.call_count == 5  # 点击仍完整投递


def test_foreground_game_window_never_regrabs(monkeypatch):
    """前台就是游戏窗：同样只 PostMessage（回归：正常路径也不碰前台）。"""
    gui, api, fake_windll = _install(monkeypatch, fg=GAME_HWND)

    input_mod.post_click(GAME_HWND, 300, 400)

    gui.SetForegroundWindow.assert_not_called()
    fake_windll.user32.SetForegroundWindow.assert_not_called()
    assert gui.PostMessage.call_count == 5


def test_postmessage_failure_falls_back_to_click_window(monkeypatch):
    """PostMessage 被 UIPI 拒绝等抛错：回落 click_window，屏幕坐标原样透传。"""
    gui, api, _ = _install(monkeypatch)
    gui.PostMessage.side_effect = OSError("拒绝访问")
    fake_window_mod = ModuleType("core._base.window")
    fake_window_mod.focus_window = MagicMock()
    monkeypatch.setitem(sys.modules, "core._base.window", fake_window_mod)
    fallback_click = MagicMock()
    monkeypatch.setattr(input_mod, "click_window", fallback_click)

    input_mod.post_click(GAME_HWND, 300, 400)

    fallback_click.assert_called_once_with(GAME_HWND, 300, 400)
