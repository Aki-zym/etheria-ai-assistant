"""
开发启动脚本

    python scripts/run.py                  桌面 GUI
    python scripts/run.py --list           列出可跑任务
    python scripts/run.py --capture        截图
    python scripts/run.py --find ICON      找模板（templates/ 相对路径）
    python scripts/run.py --click ICON     找并点击
    python scripts/run.py --resize [WxH]   缩放游戏窗到左上角，默认 960x540
    python scripts/run.py --scan           当前画面命中哪些主线模板
    python scripts/run.py --run TASK [参数]
    python scripts/run.py --cli            交互 REPL
"""
import sys
import os
import argparse

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 管道/后台跑时立刻刷日志，避免「盯了五分钟没输出」
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass


def _bot():
    from core._common.bot import GameBot
    from core.config import load_env
    load_env()
    bot = GameBot()
    if not bot.init():
        print("未找到游戏窗口")
        return None
    return bot


def _tpl_path(name: str) -> str:
    if not name.endswith('.png'):
        name += '.png'
    name = name.replace('/', os.sep).replace('\\', os.sep)
    path = name if os.path.isabs(name) else os.path.join(BASE_DIR, 'templates', name)
    return path


def main():
    # 失败现场包（P0A）：装全局兜底钩子，未捕获异常自动落盘 scene_packs/
    from core._base import scene_pack
    scene_pack.install()

    argv = sys.argv[1:]
    if not argv:
        run_gui()
        return

    parser = argparse.ArgumentParser(description='伊瑟助手 CLI')
    parser.add_argument('--cli', action='store_true')
    parser.add_argument('--list', action='store_true', help='列出任务')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--find', metavar='ICON')
    parser.add_argument('--click', metavar='ICON')
    parser.add_argument('--resize', nargs='?', const='960x540', metavar='WxH')
    parser.add_argument('--scan', action='store_true', help='扫描主线模板命中')
    parser.add_argument('--run', metavar='TASK', help='跑任务，见 --list')
    parser.add_argument('--stop', dest='stop_stage', default='4-7')
    parser.add_argument('--from-home', dest='from_home', action='store_true', default=None)
    parser.add_argument('--no-from-home', dest='from_home', action='store_false')
    parser.add_argument('--preset', dest='use_preset', action='store_true', default=False)
    parser.add_argument('--name', dest='character_name', default='')
    parser.add_argument('--diff', dest='difficulty', default='')
    parser.add_argument('--streak', type=int, default=1)
    args = parser.parse_args(argv)

    if args.list:
        from core.tasks import TASKS
        print("id            说明")
        for t in TASKS.values():
            print(f"  {t.id:<13} {t.label}")
        print("\n例: python scripts/run.py --run zhuxian --stop 4-7 --no-from-home")
        return
    if args.cli:
        run_cli()
        return
    if args.capture:
        run_capture()
        return
    if args.find:
        run_find(args.find)
        return
    if args.click:
        run_click(args.click)
        return
    if args.resize is not None:
        run_resize(args.resize)
        return
    if args.scan:
        run_scan()
        return
    if args.run:
        kwargs = {
            'stop_stage': args.stop_stage,
            'character_name': args.character_name,
            'difficulty': args.difficulty or ('炼狱' if args.run == 'zhike' else ''),
            'streak': args.streak,
            'use_preset': args.use_preset,
        }
        if args.from_home is not None:
            kwargs['from_home'] = args.from_home
        run_named_task(args.run, **kwargs)
        return
    run_gui()


def run_gui():
    from ui.app import run
    run()


def run_capture():
    bot = _bot()
    if not bot:
        return
    path = bot.save_screenshot()
    if path:
        print(f"截图已保存: {path}")


def run_find(template_name: str = None):
    if template_name is None:
        template_name = input("模板文件名: ").strip()
    path = _tpl_path(template_name)
    if not os.path.exists(path):
        print(f"模板不存在: {path}")
        return
    bot = _bot()
    if not bot:
        return
    pos = bot.find_image_position(path)
    if pos:
        print(f"找到图标，屏幕坐标: ({pos[0]}, {pos[1]})")
    else:
        print("未找到匹配图标")


def run_click(template_name: str = None):
    if template_name is None:
        template_name = input("模板文件名: ").strip()
    path = _tpl_path(template_name)
    if not os.path.exists(path):
        print(f"模板不存在: {path}")
        return
    bot = _bot()
    if not bot:
        return
    ok = bot.click_image(path)
    print("已点击" if ok else "未找到匹配图标")


def run_resize(size: str):
    from core._base.window import resize_window
    from core.config import GAME_CONFIG
    try:
        w, h = size.lower().split('x')
        w, h = int(w), int(h)
    except Exception:
        w, h = GAME_CONFIG.resize_width, GAME_CONFIG.resize_height
    bot = _bot()
    if not bot:
        return
    ok = resize_window(bot.game_window.hwnd, w, h, 0, 0)
    bot.init()
    gw = bot.game_window
    print(f"缩放{'成功' if ok else '失败'} → {gw.width}x{gw.height} @ ({gw.left},{gw.top})")
    if not ok:
        print("提示: 改游戏窗需要管理员（run_admin.bat / 管理员终端）")


def run_scan():
    """扫 templates/zhuxian 下正式模板，打印命中。"""
    bot = _bot()
    if not bot:
        return
    folder = os.path.join(BASE_DIR, 'templates', 'zhuxian')
    print(f"窗口 {bot.game_window.width}x{bot.game_window.height} @ "
          f"({bot.game_window.left},{bot.game_window.top})")
    hits = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith('.png') or name.startswith('_'):
            continue
        path = os.path.join(folder, name)
        match = bot.find_image(path)
        if match:
            abs_x = bot.game_window.left + match.x
            abs_y = bot.game_window.top + match.y
            line = f"  HIT  {name:<16} ({abs_x},{abs_y}) {match.confidence:.1%}"
            hits.append(name)
        else:
            line = f"  miss {name}"
        print(line)
    print(f"命中 {len(hits)} 个")


def run_named_task(task_id: str, **kwargs):
    from core.tasks import run_task, TASKS
    if task_id not in TASKS:
        print(f"未知任务: {task_id}")
        print("可用:", ", ".join(TASKS))
        return
    bot = _bot()
    if not bot:
        return
    print(f"运行 {TASKS[task_id].label}  kwargs={ {k:v for k,v in kwargs.items() if v not in (None,'')} }")
    try:
        ok = run_task(bot, task_id, **kwargs)
        print("结果:", "成功" if ok else "失败")
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        bot.stop()
        print("已停止")
        sys.exit(130)


def run_cli():
    from core._common.bot import GameBot
    from core._base.window import get_all_windows

    print("=" * 50)
    print("游戏 AI 助手 - CLI")
    print("=" * 50)

    bot = GameBot()
    print("\n当前可见窗口:")
    for i, (hwnd, title) in enumerate(get_all_windows()[:15], 1):
        print(f"  {i}. {title}")

    if not bot.init():
        kw = input("\n输入窗口标题关键词（留空退出）: ").strip()
        if kw:
            bot = GameBot(window_keyword=kw)
            if not bot.init():
                print("仍未找到游戏窗口")
                return
        else:
            return

    print("\n命令: screenshot / find 文字 / click 文字 / template 名 / tclick 名 / quit")
    while True:
        try:
            cmd = input("\n> ").strip()
            if not cmd:
                continue
            parts = cmd.split(maxsplit=1)
            action = parts[0].lower()
            if action == 'quit':
                break
            elif action == 'screenshot':
                path = bot.save_screenshot()
                if path:
                    print(f"截图已保存: {path}")
            elif action == 'find':
                if len(parts) > 1:
                    from core._base.ocr import create_ocr_engine, find_text
                    screenshot = bot.capture()
                    if screenshot:
                        engine = create_ocr_engine()
                        pos = find_text(engine, screenshot, parts[1])
                        if pos:
                            abs_x = bot.game_window.left + pos[0]
                            abs_y = bot.game_window.top + pos[1]
                            print(f"找到文字 '{parts[1]}' 位置: ({abs_x}, {abs_y})")
                        else:
                            print(f"未找到文字: '{parts[1]}'")
            elif action == 'click':
                if len(parts) > 1:
                    bot.click_text(parts[1])
            elif action == 'template':
                if len(parts) > 1:
                    path = _tpl_path(parts[1] if '/' in parts[1] or '\\' in parts[1]
                                     else parts[1])
                    pos = bot.find_image_position(path)
                    if pos:
                        print(f"找到图标 位置: ({pos[0]}, {pos[1]})")
                    else:
                        print("未找到图标")
            elif action == 'tclick':
                if len(parts) > 1:
                    path = _tpl_path(parts[1])
                    ok = bot.click_image(path)
                    print("已点击" if ok else "未找到图标")
            else:
                print(f"未知命令: {action}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"错误: {e}")


if __name__ == '__main__':
    main()
