"""
WGC 截图链路测试（不依赖真实游戏窗口）。

覆盖：is_black_image 判定、Unreal 窗口跳过 PrintWindow/DXCam/BitBlt、
WGC 首帧与拷贝语义、帧过期(>2s)/全黑回落、windows-capture 缺包回落、
回调与读取并发加锁安全、last_backend 导出契约。
"""
import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image

from core._base import capture
from core._base.window import GameWindow


def _gw(hwnd=4321, right=20, bottom=20):
    return GameWindow(hwnd=hwnd, title="测试窗口",
                      left=0, top=0, right=right, bottom=bottom)


@pytest.fixture(autouse=True)
def _reset_wgc():
    """每个用例前后清空 WGC 会话与 last_backend，避免串场。"""
    capture._wgc_drop()
    capture.last_backend = None
    yield
    capture._wgc_drop()


# ---------------- windows_capture 桩 ----------------

class _FakeFrame:
    def __init__(self, arr):
        self.frame_buffer = arr


class _FakeControl:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeWindowsCapture:
    """按真实包接口建模的最小桩：event 按函数名挂 handler，
    start_free_threaded 起独立线程执行注入的出帧逻辑 deliver(cap)。"""

    def __init__(self, deliver=None, reject_secondary=False, **kwargs):
        if reject_secondary and kwargs.get("secondary_window"):
            raise TypeError("unexpected keyword argument 'secondary_window'")
        self.kwargs = kwargs
        self._handlers = {}
        self._deliver = deliver
        self.control = None

    def event(self, fn):
        self._handlers[fn.__name__] = fn
        return fn

    def start_free_threaded(self):
        self.control = _FakeControl()
        if self._deliver is not None:
            threading.Thread(target=self._deliver, args=(self,), daemon=True).start()
        return self.control


def _cap_cls(deliver=None, reject_secondary=False):
    class Cap(_FakeWindowsCapture):
        def __init__(self, **kwargs):
            super().__init__(deliver=deliver,
                             reject_secondary=reject_secondary, **kwargs)
    return Cap


def _install_fake(monkeypatch, cap_cls):
    mod = types.ModuleType("windows_capture")
    mod.WindowsCapture = cap_cls
    monkeypatch.setitem(sys.modules, "windows_capture", mod)


def _deliver_once(arr):
    """起会话后稍候投递一帧（模拟首帧异步到达）。"""
    def deliver(cap):
        time.sleep(0.05)
        cap._handlers["on_frame_arrived"](_FakeFrame(arr), None)
    return deliver


def _blue_bgra(width=20, height=20):
    """BGRA 蓝 帧：转 RGB 后为蓝色，均值远高于黑帧阈值。"""
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[..., 2] = 255
    return arr


# ---------------- 基础判定 ----------------

def test_is_black_image():
    assert capture.is_black_image(Image.new("RGB", (8, 8), (0, 0, 0)))
    assert capture.is_black_image(Image.new("RGB", (8, 8), (5, 5, 5)))  # 低于阈值
    assert not capture.is_black_image(Image.new("RGB", (8, 8), (255, 255, 255)))


# ---------------- 主入口路由与 last_backend 契约 ----------------

def test_unreal_skips_printwindow_dxcam_bitblt(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "GetClassName", lambda hwnd: "UnrealWindow")
    called = []

    def _recorder(name):
        def fn(*a, **k):
            called.append(name)
            return None
        return fn

    for name in ("capture_printwindow_pca", "capture_dxcam", "capture_bitblt"):
        monkeypatch.setattr(capture, name, _recorder(name))
    monkeypatch.setattr(capture, "capture_wgc", lambda gw: None)
    red = Image.new("RGB", (10, 10), (255, 0, 0))
    monkeypatch.setattr(capture, "capture_mss", lambda gw: red)

    img = capture.capture_game_screen(_gw())
    assert img is red
    assert called == []  # Unreal：GDI/DXCam 三路全部跳过，直接 MSS
    assert capture.last_backend == "mss"


def test_non_unreal_backend_order(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "GetClassName", lambda hwnd: "NormalWindow")
    monkeypatch.setattr(capture, "capture_wgc", lambda gw: None)
    calls = []

    def _none_recorder(name):
        def fn(*a, **k):
            calls.append(name)
            return None
        return fn

    monkeypatch.setattr(capture, "capture_printwindow_pca", _none_recorder("printwindow"))
    monkeypatch.setattr(capture, "capture_dxcam", _none_recorder("dxcam"))
    red = Image.new("RGB", (10, 10), (255, 0, 0))

    def _bitblt(hwnd, gw):
        calls.append("bitblt")
        return red

    monkeypatch.setattr(capture, "capture_bitblt", _bitblt)
    monkeypatch.setattr(capture, "capture_mss",
                        lambda gw: pytest.fail("bitblt 成功时不应走到 MSS"))

    img = capture.capture_game_screen(_gw())
    assert img is red
    assert calls == ["printwindow", "dxcam", "bitblt"]
    assert capture.last_backend == "bitblt"


def test_mss_focus_backend(monkeypatch):
    monkeypatch.setattr(capture.win32gui, "GetForegroundWindow", lambda: 0)
    monkeypatch.setattr("core._base.window.focus_window", lambda hwnd: None)
    monkeypatch.setattr(capture.time, "sleep", lambda s: None)  # 加速，不真睡
    red = Image.new("RGB", (10, 10), (255, 0, 0))
    monkeypatch.setattr(capture, "capture_mss", lambda gw: red)

    img = capture.capture_game_screen(_gw(), background_mode=False)
    assert img is red
    assert capture.last_backend == "mss-focus"


# ---------------- WGC 通路 ----------------

def test_wgc_success_uses_copied_frame(monkeypatch):
    # 源缓冲模拟 mapped 内存：回调后会被"下一帧"覆盖，已拷贝的帧必须不受影响
    src = np.zeros((20, 20, 4), dtype=np.uint8)
    src[..., 0] = 200  # BGRA 的 B 通道 -> RGB (0, 0, 200)
    made = []

    class Cap(_cap_cls(deliver=_deliver_once(src))):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            made.append(self)

    _install_fake(monkeypatch, Cap)
    img = capture.capture_wgc(_gw())
    assert img is not None
    src[..., 0] = 0  # 模拟下一帧覆盖 mapped 内存
    assert img.getpixel((5, 5)) == (0, 0, 200)  # 读到的是拷贝，不是原视图

    # 构造参数契约：无光标/无边框/secondary_window 优先/指定句柄
    assert made[0].kwargs["cursor_capture"] is False
    assert made[0].kwargs["draw_border"] is False
    assert made[0].kwargs["secondary_window"] is True
    assert made[0].kwargs["window_hwnd"] == _gw().hwnd


def test_wgc_secondary_window_rejected_uses_base_form(monkeypatch):
    _install_fake(monkeypatch, _cap_cls(deliver=_deliver_once(_blue_bgra()),
                                        reject_secondary=True))
    assert capture.capture_wgc(_gw()) is not None  # API 拒绝 secondary 时退回基础形式


def test_wgc_backend_contract_via_main_entry(monkeypatch):
    made = []

    class Cap(_cap_cls(deliver=_deliver_once(_blue_bgra()))):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            made.append(self)

    _install_fake(monkeypatch, Cap)
    monkeypatch.setattr(capture, "capture_mss",
                        lambda gw: pytest.fail("wgc 成功时不应回落 MSS"))
    img = capture.capture_game_screen(_gw())
    assert img is not None
    assert capture.last_backend == "wgc"


def test_wgc_no_first_frame_releases_session(monkeypatch):
    monkeypatch.setattr(capture, "_WGC_FIRST_FRAME_S", 0.05)  # 缩短等待
    _install_fake(monkeypatch, _cap_cls(deliver=None))  # 永不出帧的死会话
    assert capture.capture_wgc(_gw()) is None
    with capture._wgc_lock:
        assert capture._wgc_session["control"] is None
        assert capture._wgc_session["key"] is None


def test_wgc_missing_package_falls_back(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", None)  # import 即 ImportError
    assert capture.capture_wgc(_gw()) is None
    red = Image.new("RGB", (10, 10), (255, 0, 0))
    monkeypatch.setattr(capture.win32gui, "GetClassName", lambda hwnd: "UnrealWindow")
    monkeypatch.setattr(capture, "capture_mss", lambda gw: red)
    img = capture.capture_game_screen(_gw())
    assert img is red  # 缺包不崩，主入口回落 MSS
    assert capture.last_backend == "mss"


def test_wgc_stale_frame_returns_none(monkeypatch):
    _install_fake(monkeypatch, _cap_cls(deliver=_deliver_once(_blue_bgra())))
    assert capture.capture_wgc(_gw()) is not None
    with capture._wgc_lock:
        capture._wgc_session["ts"] = time.time() - 3.0  # 拨回 3s 前，超过 2s 过期线
    assert capture.capture_wgc(_gw()) is None


def test_wgc_black_frame_returns_none(monkeypatch):
    _install_fake(monkeypatch, _cap_cls(deliver=_deliver_once(np.zeros((20, 20, 4), dtype=np.uint8))))
    assert capture.capture_wgc(_gw()) is None


def test_wgc_resizes_to_window_rect(monkeypatch):
    _install_fake(monkeypatch, _cap_cls(deliver=_deliver_once(_blue_bgra(30, 40))))
    img = capture.capture_wgc(_gw(right=10, bottom=20))  # 帧 30x40，窗口 10x20
    assert img is not None
    assert img.size == (10, 20)


def test_wgc_concurrent_capture_and_callback(monkeypatch):
    stop = threading.Event()

    def deliver(cap):
        i = 0
        while not stop.is_set():
            arr = _blue_bgra()
            arr[..., 1] = i % 256  # 持续变化的内容，放大竞态窗口
            cap._handlers["on_frame_arrived"](_FakeFrame(arr), None)
            i += 1
            time.sleep(0.001)

    _install_fake(monkeypatch, _cap_cls(deliver=deliver))
    errors = []

    def worker():
        try:
            for _ in range(30):
                capture.capture_wgc(_gw())
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    stop.set()
    assert errors == []
