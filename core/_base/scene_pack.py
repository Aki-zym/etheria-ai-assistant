"""
失败现场包（P0A）— 任务失败时自动落盘七要素，规范见 docs/失败现场包规范.md。

七要素：任务、节点、时间、原始帧、标注帧、日志尾、环境。
目录：scene_packs/<YYYYmmdd-HHMMSS-mmm>-<任务>/，自动只保留最近 KEEP_PACKS 份。

设计纪律：现场包是诊断设施——任何自身异常都必须静默吞掉并只打标准输出，
绝不允许把主流程砸出第二个错。
"""
import collections
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime

from core import __version__
from core.config import GAME_CONFIG

ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

KEEP_PACKS = 20
LOG_BUFFER_SIZE = 300

# ---------------- 日志环形缓冲（日志尾的来源） ----------------
_LOG_BUFFER = collections.deque(maxlen=LOG_BUFFER_SIZE)
_LOG_LOCK = threading.Lock()

# ---------------- Bot 注册（最后注册者为当前使用中的 Bot） ----------------
_BOTS = []
_PACK_LOCK = threading.Lock()
_HOOKS_INSTALLED = False
_LAST_PACK = None  # (错误类型, 错误消息, 时间戳) — 2 秒去重


def record_log(line: str):
    """记录一行带时间戳的日志（GameBot._log 与 UI 日志汇入）。"""
    with _LOG_LOCK:
        _LOG_BUFFER.append(line)


def log_tail(n: int = LOG_BUFFER_SIZE):
    with _LOG_LOCK:
        return list(_LOG_BUFFER)[-n:]


def register_bot(bot):
    """GameBot 构造时自注册；现场包取帧/窗口信息用最后注册的实例。"""
    _BOTS.append(bot)


def current_bot():
    return _BOTS[-1] if _BOTS else None


# ============================================================
# 落盘
# ============================================================

def write_scene_pack(task: str, node: str, error: Exception,
                     bot=None, extra=None):
    """落一份现场包，返回目录路径；自身失败不抛出。"""
    try:
        return _write(task, node, error, bot, extra)
    except Exception:
        try:
            print("[ScenePack] 现场包落盘失败:\n" + traceback.format_exc())
        except Exception:
            pass
        return None


def _write(task, node, error, bot, extra):
    global _LAST_PACK
    if bot is None:
        bot = current_bot()

    # 2 秒内同一错误只落一份（注册表出口落包后再抛，兜底钩子会再次看到）
    key = (type(error).__name__, str(error), time.monotonic())
    if _LAST_PACK and _LAST_PACK[0] == key[0] and _LAST_PACK[1] == key[1] \
            and key[2] - _LAST_PACK[2] < 2.0:
        return None

    with _PACK_LOCK:
        if _LAST_PACK and _LAST_PACK[0] == key[0] and _LAST_PACK[1] == key[1] \
                and key[2] - _LAST_PACK[2] < 2.0:
            return None
        _LAST_PACK = key

        ts = datetime.now()
        pack_dir = os.path.join(_pack_root(), _pack_name(ts, task))
        os.makedirs(pack_dir, exist_ok=True)

        info = _build_info(task, node, error, bot, extra, ts)
        with open(os.path.join(pack_dir, "info.json"), "w",
                  encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        frame, source = _get_frame(bot)
        if frame is not None:
            frame.save(os.path.join(pack_dir, "frame.png"))
            annotated = _annotate(frame, bot, task, node, error, ts, source)
            if annotated is not None:
                annotated.save(os.path.join(pack_dir, "frame_annotated.png"))

        with open(os.path.join(pack_dir, "log_tail.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(log_tail()))

        _prune(os.path.dirname(pack_dir))
        print(f"[ScenePack] 已落盘现场包: {pack_dir}")
        return pack_dir


def _pack_root():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "scene_packs")
    return os.path.join(ROOT, "scene_packs")


def _pack_name(ts, task):
    slug = re.sub(r"[^0-9A-Za-z_-]+", "_", str(task))[:40] or "task"
    name = ts.strftime("%Y%m%d-%H%M%S") + f"-{ts.microsecond // 1000:03d}-{slug}"
    return name


def _build_info(task, node, error, bot, extra, ts):
    tb = getattr(error, "__traceback__", None)
    tail = "".join(traceback.format_exception(
        type(error), error, tb)[-6:]) if tb else ""
    info = {
        "task": {"id": task, "params": extra or {}},
        "node": node,
        "time": ts.isoformat(timespec="milliseconds"),
        "error": {
            "type": type(error).__name__,
            "message": str(error),
            "traceback_tail": tail.strip(),
        },
        "environment": _environment(bot),
    }
    return info


def _environment(bot):
    env = {
        "app_version": __version__,
        "commit": _git_commit(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "cwd": os.getcwd(),
        "config": asdict(GAME_CONFIG),
    }
    try:  # 屏幕分辨率（仅 Windows）
        import ctypes
        env["screen"] = {
            "width": ctypes.windll.user32.GetSystemMetrics(0),
            "height": ctypes.windll.user32.GetSystemMetrics(1),
        }
    except Exception:
        pass
    gw = getattr(bot, "game_window", None) if bot else None
    if gw is not None:
        env["window"] = {
            "title": getattr(gw, "title", ""),
            "hwnd": getattr(gw, "hwnd", None),
            "left": getattr(gw, "left", None),
            "top": getattr(gw, "top", None),
            "width": getattr(gw, "width", None),
            "height": getattr(gw, "height", None),
        }
    return env


def _git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True,
                             check=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return "(unknown)"


def _get_frame(bot):
    """优先任务最后成功帧；没有则失败瞬间补截一帧（并注明来源）。"""
    img = getattr(bot, "last_frame", None) if bot else None
    if img is not None:
        return img, "缓存帧（任务最后成功截图）"
    if bot is not None:
        try:
            img = bot.capture()
            if img is not None:
                return img, "失败时补截（可能与出错时刻不同）"
        except Exception:
            pass
    return None, "无帧"


def _annotate(frame, bot, task, node, error, ts, source):
    """标注帧：最近动作坐标画圈 + 顶部任务/节点/错误文字条。纯 PIL，免中文乱码。"""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = frame.convert("RGB").copy()
        draw = ImageDraw.Draw(img)
        w, h = img.size

        action = getattr(bot, "last_action", None) if bot else None
        if action and action.get("x") is not None:
            x, y = int(action["x"]), int(action["y"])
            r = 16
            draw.ellipse((x - r, y - r, x + r, y + r),
                         outline=(255, 40, 40), width=3)
            draw.line((x - r - 6, y, x - r + 4, y), fill=(255, 40, 40), width=2)
            draw.line((x + r - 4, y, x + r + 6, y), fill=(255, 40, 40), width=2)
            draw.line((x, y - r - 6, x, y - r + 4), fill=(255, 40, 40), width=2)
            draw.line((x, y + r - 4, x, y + r + 6), fill=(255, 40, 40), width=2)

        font = None
        for candidate in ("C:/Windows/Fonts/msyh.ttc",
                          "C:/Windows/Fonts/simhei.ttf"):
            try:
                font = ImageFont.truetype(candidate, 15)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        lines = [
            f"任务: {task}   节点: {node}",
            f"错误: {type(error).__name__}: {str(error)[:80]}",
            f"时间: {ts.isoformat(timespec='milliseconds')}   帧来源: {source}"
            + (f"   最近动作: {action.get('desc')}" if action else ""),
        ]
        strip_h = 4 + 19 * len(lines)
        draw.rectangle((0, 0, w, strip_h), fill=(0, 0, 0))
        for i, text in enumerate(lines):
            draw.text((8, 3 + 19 * i), text, fill=(255, 255, 255), font=font)
        return img
    except Exception:
        return None


def _prune(root):
    """只保留最近 KEEP_PACKS 份。目录名以时间戳开头，按名排序即按时间排序。"""
    try:
        dirs = sorted(
            d for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d)))
        for d in dirs[:-KEEP_PACKS] if len(dirs) > KEEP_PACKS else []:
            import shutil
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    except Exception:
        pass


# ============================================================
# 全局兜底钩子
# ============================================================

def _node_from_tb(tb):
    """回溯位置当节点：取最后两帧 '文件:行 函数'。"""
    try:
        frames = []
        while tb is not None:
            frames.append(
                f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:"
                f"{tb.tb_lineno} {tb.tb_frame.f_code.co_name}")
            tb = tb.tb_next
        return " ← ".join(frames[-2:]) if frames else "(无回溯)"
    except Exception:
        return "(回溯不可用)"


def install():
    """装全局兜底钩子（主线程 + 子线程），幂等。ui/app.py 与 scripts/run.py 启动时调用。"""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True

    def _handle(kind, exc, tb, thread_name):
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return
        write_scene_pack(
            task=f"uncaught-{thread_name}",
            node=_node_from_tb(tb),
            error=exc)

    prev_sys = sys.excepthook

    def _sys_hook(exc_type, exc_value, exc_tb):
        _handle("main", exc_value, exc_tb, "main")
        if prev_sys is not None:
            prev_sys(exc_type, exc_value, exc_tb)

    sys.excepthook = _sys_hook

    prev_thread = getattr(threading, "excepthook", None)

    def _thread_hook(args):
        _handle("thread", args.exc_value, args.exc_traceback,
                getattr(getattr(args, "thread", None), "name", "thread"))
        if prev_thread is not None:
            prev_thread(args)

    threading.excepthook = _thread_hook
