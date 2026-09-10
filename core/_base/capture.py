"""
游戏画面截图 - 支持多种后台截图方案
"""
import time
import os
import threading
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image
import mss
import win32gui
import win32con

from core._base.window import GameWindow

# 最近一次成功出图的后端名（CLI worker 依赖的导出契约）：
# 'wgc' | 'printwindow' | 'dxcam' | 'bitblt' | 'mss' | 'mss-focus' | None。
# 由 capture_game_screen 赋值（返回 None 时置 None），每次调用先重置。
last_backend: Optional[str] = None

# ============================================================
# WGC 后台捕获（最优先）：Windows.Graphics.Capture 走 DWM 合成层，窗口
# 被完全遮挡也能出帧；最小化停渲染则帧过期回落。依赖可选包 windows-capture
# （未安装自动跳过）。会话常驻、句柄/尺寸变化重建；回调在捕获线程执行。
# ============================================================
_wgc_lock = threading.Lock()
_wgc_session = {'key': None, 'control': None, 'frame': None, 'ts': 0.0}
_WGC_FIRST_FRAME_S = 1.5  # 等首帧上限（实测 ~0.2s）
_WGC_STALE_S = 2.0        # 帧过期上限：最小化停渲染后回落下一路


def _wgc_drop():
    """释放当前 WGC 会话。stop() 必须在锁外调：它会等捕获线程收尾，持锁互等会死锁。"""
    with _wgc_lock:
        control = _wgc_session['control']
        _wgc_session.update(key=None, control=None, frame=None, ts=0.0)
    if control is not None:
        try:
            control.stop()
        except Exception:
            pass


def _wgc_make_cap(game_window: GameWindow):
    """构造 WindowsCapture；优先 secondary_window=True（被遮挡更可靠），旧包不认则退回。"""
    from windows_capture import WindowsCapture
    try:
        return WindowsCapture(
            cursor_capture=False, draw_border=False,
            secondary_window=True, window_hwnd=game_window.hwnd)
    except TypeError:
        return WindowsCapture(
            cursor_capture=False, draw_border=False,
            window_hwnd=game_window.hwnd)


def _wgc_ensure(game_window: GameWindow) -> bool:
    """确保存在对目标窗口的 WGC 捕获会话（未建/失效/句柄尺寸变化则重建）。
    等不到首帧视为死会话：释放并返回 False，让主入口回落下一路。"""
    key = (game_window.hwnd, game_window.width, game_window.height)
    with _wgc_lock:
        alive = _wgc_session['key'] == key and _wgc_session['control'] is not None
    if alive:
        return True
    _wgc_drop()
    try:
        cap = _wgc_make_cap(game_window)
    except Exception:  # windows-capture 未安装 / 会话创建失败：本路跳过
        return False

    @cap.event
    def on_frame_arrived(frame, capture_control):
        try:
            # frame_buffer 是原生 mapped 内存的零拷贝视图，下一帧到来即被
            # 覆盖，必须立刻拷贝，否则读取端拿到的是被污染的后续帧
            arr = np.array(frame.frame_buffer, copy=True)
        except Exception:
            return
        with _wgc_lock:
            _wgc_session['frame'] = arr
            _wgc_session['ts'] = time.time()

    @cap.event
    def on_closed():
        # 窗口关闭：只置空 control，下次调用按未建会话重建
        with _wgc_lock:
            _wgc_session['control'] = None

    try:
        control = cap.start_free_threaded()
    except Exception:
        return False
    with _wgc_lock:
        mine = _wgc_session['control'] is None
        if mine:
            _wgc_session['key'] = key
            _wgc_session['control'] = control
    if not mine:
        try:
            control.stop()  # 并发重建竞态：已有人装上会话，弃用本次多余的
        except Exception:
            pass
    deadline = time.time() + _WGC_FIRST_FRAME_S
    while time.time() < deadline:
        with _wgc_lock:
            if _wgc_session['control'] is control and _wgc_session['frame'] is not None:
                return True
        time.sleep(0.02)
    with _wgc_lock:
        still_mine = _wgc_session['control'] is control
    if still_mine:
        _wgc_drop()
    return False


def capture_wgc(game_window: GameWindow) -> Optional[Image.Image]:
    """WGC 截图：取会话最新帧（BGRA->RGB）。无首帧/帧过期(>2s)/全黑返回 None。"""
    try:
        if not _wgc_ensure(game_window):
            return None
        with _wgc_lock:
            buf = _wgc_session['frame']
            ts = _wgc_session['ts']
        if buf is None or time.time() - ts > _WGC_STALE_S:
            return None
        img = Image.fromarray(np.ascontiguousarray(buf[:, :, :3][:, :, ::-1]))
        # DPI/边框兜底：帧尺寸与窗口矩形不一致时归一化，保证坐标系一致
        if img.size != (game_window.width, game_window.height):
            img = img.resize((game_window.width, game_window.height))
        return None if is_black_image(img) else img
    except Exception:
        return None


def capture_mss(game_window: GameWindow) -> Optional[Image.Image]:
    """MSS 前台截图（窗口必须可见，不能被遮挡）。"""
    try:
        with mss.mss() as sct:
            monitor = {
                "top": game_window.top,
                "left": game_window.left,
                "width": game_window.width,
                "height": game_window.height,
            }
            screenshot = sct.grab(monitor)
            return Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )
    except Exception:
        return None


def capture_dxcam(game_window: GameWindow) -> Optional[Image.Image]:
    """DXCam 桌面复制截图（需要 dxcam 库；窗口被遮挡时抓到的是遮挡物）。"""
    try:
        import dxcam
        camera = dxcam.create(output_color="RGB")
        frame = camera.grab(region=(
            game_window.left, game_window.top,
            game_window.right, game_window.bottom,
        ))
        if frame is not None:
            return Image.fromarray(frame)
        return None
    except Exception:
        return None


def _gdi_capture(hwnd: int, game_window: GameWindow, use_printwindow: bool) -> Optional[Image.Image]:
    """PrintWindow / BitBlt 共用实现：建兼容位图 -> 采集 -> 转 PIL。
    use_printwindow=True 走 PW_RENDERFULLCONTENT(2)，否则 BitBlt（被遮挡时是过期残影）。"""
    try:
        import win32ui
        from ctypes import windll

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)

        if use_printwindow:
            result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        else:
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)
            result = 1

        bmpinfo = save_bitmap.GetInfo()
        bmpstr = save_bitmap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr, "raw", "BGRX", 0, 1,
        )

        win32gui.DeleteObject(save_bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        return img if result == 1 else None
    except Exception:
        return None


def capture_printwindow_pca(hwnd: int, game_window: GameWindow) -> Optional[Image.Image]:
    """PrintWindow with PW_RENDERFULLCONTENT（方法1），尝试从 DWM 取完整内容。"""
    return _gdi_capture(hwnd, game_window, use_printwindow=True)


def capture_bitblt(hwnd: int, game_window: GameWindow) -> Optional[Image.Image]:
    """BitBlt 截图（窗口可被遮挡但内容可能过期）。"""
    return _gdi_capture(hwnd, game_window, use_printwindow=False)


def is_black_image(image: Image.Image, threshold: float = 10.0) -> bool:
    """检查截图是否为全黑（后台截图失败的标志）"""
    arr = np.array(image)
    return float(arr.mean()) < threshold


def _is_unreal_window(game_window: GameWindow) -> bool:
    """当前客户端是 UnrealWindow（伊瑟 PC），PrintWindow/BitBlt 会拿到脏 GDI 缓冲。"""
    try:
        return 'Unreal' in win32gui.GetClassName(game_window.hwnd)
    except Exception:
        return False


def capture_game_screen(
    game_window: GameWindow,
    background_mode: bool = True,
    auto_focus: bool = True,
) -> Optional[Image.Image]:
    """截取游戏窗口画面（主入口）。

    background_mode 时按 WGC -> (非 Unreal: PrintWindow/DXCam/BitBlt) -> MSS 取第一张
    非黑帧；全失败且 auto_focus 时切前台 MSS 重截。成功时写入 last_backend，失败置 None。
    """
    global last_backend
    last_backend = None
    if background_mode:
        unreal = _is_unreal_window(game_window)
        # Unreal（伊瑟 PC）：PrintWindow 全黑、BitBlt 是过期 GDI 残影、DXCam 被遮挡即失效，全跳过。
        methods = [('wgc', lambda: capture_wgc(game_window))]
        if not unreal:
            methods += [
                ('printwindow',
                 lambda: capture_printwindow_pca(game_window.hwnd, game_window)),
                ('dxcam', lambda: capture_dxcam(game_window)),
                ('bitblt', lambda: capture_bitblt(game_window.hwnd, game_window)),
            ]
        for name, method in methods:
            try:
                img = method()
                if img is not None and not is_black_image(img):
                    last_backend = name
                    return img
            except Exception:
                continue

        mss_img = capture_mss(game_window)
        if mss_img is not None:
            last_backend = 'mss'
            if not is_black_image(mss_img):
                return mss_img
        if not auto_focus:
            return mss_img  # 不允许抢焦点：黑帧/None 也原样返回

    # 前台截图 - 自动切换到游戏窗口
    img = _capture_with_auto_focus(game_window)
    last_backend = 'mss-focus' if img is not None else None
    return img


def _capture_with_auto_focus(game_window: GameWindow) -> Optional[Image.Image]:
    """切换到游戏窗口，截图后恢复"""
    from .window import focus_window

    current_hwnd = win32gui.GetForegroundWindow()

    try:
        focus_window(game_window.hwnd)
        time.sleep(0.3)
        img = capture_mss(game_window)

        if current_hwnd and current_hwnd != game_window.hwnd:
            time.sleep(0.1)
            try:
                win32gui.SetForegroundWindow(current_hwnd)
            except Exception:
                pass

        return img
    except Exception:
        return capture_mss(game_window)


def save_screenshot(image: Image.Image, directory: str = "screenshots") -> str:
    """保存截图到文件，返回文件路径"""
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.png"
    filepath = os.path.join(directory, filename)
    image.save(filepath)
    return filepath


def save_template(image: Image.Image, name: str, directory: str = "templates") -> str:
    """保存图标模板到文件，返回文件路径"""
    os.makedirs(directory, exist_ok=True)
    filename = f"{name}.png"
    filepath = os.path.join(directory, filename)
    image.save(filepath)
    return filepath
