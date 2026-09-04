"""
主线推图模块

按画面里出现的模板决定下一步，没有全局状态机。
停止关可配（默认 4-7），后面章节改参数即可。
"""
import os
import re
import time

import numpy as np

from core._base.input import post_click
from core._common.battle_common import (
    tpl, wait_for_image, wait_for_image_gone, exit_battle,
    _find_manual_button, _init_easyocr_reader, setup_preset,
    find_all_by_color,
)
from core.config import GAME_CONFIG

_BASE_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
_ZHUXIAN_TPL = os.path.join(_BASE_DIR, 'templates', 'zhuxian')

_ocr_stage = None
_ocr_disabled = False


def _ztpl(name: str) -> str:
    return os.path.join(_ZHUXIAN_TPL, name)


def _parse_stage(text: str):
    m = re.search(r'(\d+)\s*[-—－~～]\s*(\d+)', text or '')
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _stage_ge(a, b) -> bool:
    if a is None or b is None:
        return False
    return a[0] > b[0] or (a[0] == b[0] and a[1] >= b[1])


def _stage_gt(a, b) -> bool:
    if a is None or b is None:
        return False
    return a[0] > b[0] or (a[0] == b[0] and a[1] > b[1])


def _abs_pos(bot, match):
    if match is None:
        return None
    return (bot.game_window.left + match.x, bot.game_window.top + match.y)


def _find(bot, name, multi_scale=True, threshold=None, region=None):
    """region: (x1,y1,x2,y2) 相对截图像素，只在该矩形内匹配。"""
    path = name if os.path.isabs(name) else _ztpl(name)
    screenshot = bot.capture()
    if screenshot is None:
        return None
    from core._base.template_match import match_template, match_template_multi_scale
    from core.config import GAME_CONFIG
    threshold = threshold or GAME_CONFIG.template_threshold
    ox = oy = 0
    img = screenshot
    if region is not None:
        x1, y1, x2, y2 = region
        img = screenshot.crop((x1, y1, x2, y2))
        ox, oy = x1, y1
    if multi_scale:
        match = match_template_multi_scale(img, path, threshold=threshold)
    else:
        match = match_template(img, path, threshold=threshold)
    if match is None:
        return None
    return (bot.game_window.left + ox + match.x,
            bot.game_window.top + oy + match.y)


def _bottom_bar_region(bot):
    gw = bot.game_window
    h = gw.height
    w = gw.width
    return (0, int(h * 0.82), w, h)


def _find_any(bot, names, multi_scale=True):
    for name in names:
        pos = _find(bot, name, multi_scale=multi_scale)
        if pos is not None:
            return name, pos
    return None, None


def _click(bot, pos):
    post_click(bot.game_window.hwnd, pos[0], pos[1])


def _click_blank(bot):
    """结算 / 章节完成页点画面中心空白返回，避开左下战斗统计。"""
    gw = bot.game_window
    x = gw.left + gw.width // 2
    y = gw.top + int(gw.height * 0.72)
    bot._log(f'点击空白返回 ({x}, {y})')
    post_click(gw.hwnd, x, y)
    time.sleep(1.2)


def _battle_ended(bot) -> bool:
    """战斗结束：异常排除 / 获得物品 / 章节完成。静默查找，避免刷 miss。"""
    return (
        _find(bot, '异常排除.png', multi_scale=False, threshold=0.82) is not None
        or _find(bot, '点击空白返回.png', multi_scale=False, threshold=0.80) is not None
        or _find(bot, '获得物品.png', multi_scale=False, threshold=0.82) is not None
        or _find(bot, '章节完成.png', multi_scale=False, threshold=0.75) is not None
    )


def _get_ocr():
    global _ocr_stage, _ocr_disabled
    if _ocr_disabled:
        return None
    if _ocr_stage is None:
        from core._base.ocr import create_ocr_engine
        try:
            _ocr_stage = create_ocr_engine('paddle')
        except Exception:
            try:
                import sys as _sys
                if getattr(_sys, 'frozen', False):
                    _tl = os.path.join(_sys._MEIPASS, 'torch', 'lib')
                    if os.path.isdir(_tl):
                        os.add_dll_directory(_tl)
                _ocr_stage = _init_easyocr_reader(['en'])
            except Exception:
                _ocr_disabled = True
                return None
    return _ocr_stage


def _ocr_texts(engine, image):
    """Paddle/EasyOCR 统一抽文字。"""
    texts = []
    if hasattr(engine, 'recognize'):
        for m in engine.recognize(image):
            texts.append(m.text)
        return texts
    import numpy as np
    for det in engine.readtext(np.array(image), allowlist='0123456789-—#'):
        texts.append(det[1])
    return texts


def _ocr_current_stage(bot):
    """从关卡弹窗左侧 OCR #X-Y。引擎不可用则整场禁用，不再每关重试。"""
    global _ocr_disabled
    if _ocr_disabled:
        return None
    from PIL import Image as _Image
    img = bot.capture()
    if img is None:
        return None
    engine = _get_ocr()
    if engine is None:
        bot._log('OCR 不可用（未装 paddlepaddle/easyocr），停止关只按结算推进')
        _ocr_disabled = True
        return None
    w, h = img.size
    roi = img.crop((int(w * 0.08), int(h * 0.22), int(w * 0.42), int(h * 0.48)))
    roi2 = roi.resize((roi.width * 2, roi.height * 2), _Image.LANCZOS)
    texts = []
    try:
        texts.extend(_ocr_texts(engine, roi2))
        if not texts:
            texts.extend(_ocr_texts(engine, roi))
    except Exception as e:
        bot._log(f'OCR 不可用，本场不再尝试: {e}')
        _ocr_disabled = True
        return None
    joined = ' '.join(texts)
    stage = _parse_stage(joined)
    if stage:
        bot._log(f'OCR 关卡: #{stage[0]}-{stage[1]}  原文={texts[:6]}')
    return stage


def _wait_story_battle(bot, use_preset: bool) -> bool:
    hwnd = bot.game_window.hwnd
    time.sleep(1.0)
    bot._log('检查手动模式...')
    # 只模板匹配，不走 EasyOCR（本环境没装，会空等 3×几秒）
    match = bot.find_image(tpl('手动.png'), multi_scale=False)
    if match is not None:
        manual_pos = (bot.game_window.left + match.x, bot.game_window.top + match.y)
        _click(bot, manual_pos)
        time.sleep(0.4)
    else:
        bot._log('未检测到手动按钮')

    if use_preset:
        if not setup_preset(bot):
            bot._log('[WARN] 预设失败，继续用场上队伍')

    fight = wait_for_image(bot, _ztpl('主线战斗.png'), timeout=8)
    if fight is None:
        fight = wait_for_image(bot, tpl('F战斗.png'), timeout=5)
    if fight is None:
        bot._log('[FAIL] 未检测到战斗按钮')
        return False
    bot._log('点击战斗...')
    _click(bot, fight)
    time.sleep(2)
    confirm = wait_for_image(bot, tpl('确定.png'), timeout=4)
    if confirm is not None:
        _click(bot, confirm)
        time.sleep(1)

    timeout = GAME_CONFIG.battle_end_timeout
    bot._log(f'战斗中，每 2s 扫结束标志（最多 {timeout}s）...')
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        if not bot.is_running:
            return False
        if _battle_ended(bot):
            seen += 1
            if seen >= 2:
                bot._log('检测到战斗结束标志')
                return True
        else:
            seen = 0
        if _find(bot, tpl('体力兑换.png'), multi_scale=False) is not None:
            bot._log('[WARN] STAMINA_MISSING: 体力不足')
            return False
        time.sleep(2)
    bot._log('[WARN] 等待战斗结束超时，继续')
    return True


def _on_chapter_select(bot) -> bool:
    """章节选择页：CHAPTER / 普通模式。章节名也会出现在关卡地图里，不能单独当信号。"""
    return (
        _find(bot, '主线章节.png') is not None
        or _find(bot, '普通模式.png') is not None
    )


def _already_in_story_flow(bot) -> bool:
    """关卡地图 / 关卡弹窗 / 战斗 / 结算 / 剧情，都不必再从主界面进。"""
    if _on_chapter_select(bot):
        return False
    checks = [
        '主线前往挑战.png', '主线战斗.png',
        '异常排除.png', '获得物品.png', '主线跳过.png',
        '章节完成.png',
    ]
    for name in checks:
        if _find(bot, name) is not None:
            return True
    if _find(bot, '主线NEW.png') is not None:
        return True
    if bot.find_image(tpl('F战斗.png')) is not None:
        return True
    return False


def _click_story_tab(bot) -> bool:
    """底栏左半边找「主线」文字再点。已选模板会和「挑战」选中态串图，不能当判断。"""
    gw = bot.game_window
    left_bar = (0, int(gw.height * 0.82), int(gw.width * 0.42), gw.height)
    tab = _find(bot, '主线页签.png', multi_scale=True, region=left_bar)
    if tab is None:
        tab = _find(bot, '主线页签已选.png', multi_scale=False, region=left_bar)
    if tab is None:
        bot._log('[FAIL] 未找到主线页签')
        return False
    bot._log(f'点击主线页签 {tab}')
    _click(bot, tab)
    time.sleep(1.8)
    return True


def _enter_from_home(bot) -> bool:
    if _already_in_story_flow(bot):
        bot._log('已在主线流程中，跳过入口')
        return True

    bar = _bottom_bar_region(bot)
    on_chapter = _on_chapter_select(bot)
    on_challenge_bar = _find(bot, '主线页签.png', region=bar) is not None

    if not on_chapter and not on_challenge_bar:
        home_chal = _find(bot, '主页挑战.png')
        if home_chal is None:
            bot._log('回到主界面...')
            bot.go_back_to_main(tpl('返回.png'))
            time.sleep(0.6)
        bot._log('点击主页挑战...')
        pos = home_chal or wait_for_image(bot, _ztpl('主页挑战.png'), timeout=8)
        if pos is None:
            from core._common.battle_common import open_sidebar
            open_sidebar(bot)
            pos = wait_for_image(bot, tpl('挑战.png'), timeout=5)
        if pos is None:
            bot._log('[FAIL] 未找到挑战入口')
            return False
        _click(bot, pos)
        time.sleep(1.5)

    if not _click_story_tab(bot):
        return False

    if _already_in_story_flow(bot):
        return True

    bot._log('点击当前章节...')
    card = wait_for_image(bot, _ztpl('主线章节名.png'), timeout=6)
    if card is None:
        card = wait_for_image(bot, _ztpl('主线章节.png'), timeout=5)
    if card is None:
        bot._log('[FAIL] 未找到章节卡')
        return False
    _click(bot, card)
    time.sleep(2)
    return True


def run_zhuxian_battle(bot, character_name: str = '', difficulty: str = '',
                       streak: int = 1, stop_stage: str = None,
                       from_home: bool = None) -> bool:
    """
    自动推主线。stop_stage 默认 4-7，打完该关后的获得物品即停。
    """
    hwnd = bot.game_window.hwnd
    bot._running = True
    stop_stage = stop_stage or GAME_CONFIG.zhuxian_stop_stage or character_name or '4-7'
    if from_home is None:
        from_home = GAME_CONFIG.zhuxian_from_home
    use_preset = GAME_CONFIG.zhuxian_use_preset
    stop = _parse_stage(stop_stage)
    if stop is None:
        bot._log(f'[FAIL] 停止关格式无效: {stop_stage}（需要 4-7）')
        bot._running = False
        return False

    try:
        bot._log('=' * 40)
        bot._log(f'主线开始 → 打到 #{stop[0]}-{stop[1]}  from_home={from_home}')
        bot._log('=' * 40)

        if from_home:
            if not _enter_from_home(bot):
                return False

        stale = 0
        last_stage = None
        fighting_stage = None
        loot_seen_for_stop = False

        while bot.is_running:
            if bot.find_image(tpl('体力兑换.png')) is not None:
                bot._log('[WARN] STAMINA_MISSING: 体力不足，停止主线')
                return False

            # 1. 剧情跳过（无确认）— 只在右上角找，避免和地图 UI 串
            gw = bot.game_window
            skip_region = (int(gw.width * 0.70), 0, gw.width, int(gw.height * 0.22))
            skip = None
            for skip_name in ('主线跳过.png',):
                skip = _find(bot, skip_name, region=skip_region, threshold=0.80, multi_scale=False)
                if skip is not None:
                    break
            if skip is not None:
                bot._log('点击跳过')
                _click(bot, skip)
                time.sleep(1.2)
                stale = 0
                continue
            auto = _find(bot, '主线剧情自动.png', region=skip_region, threshold=0.80, multi_scale=False)
            if auto is not None:
                bot._log('剧情页：Esc 跳过')
                from core._base.window import focus_window
                focus_window(bot.game_window.hwnd)
                import win32api, win32con
                win32api.PostMessage(bot.game_window.hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                time.sleep(0.05)
                win32api.PostMessage(bot.game_window.hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                time.sleep(1.2)
                stale = 0
                continue

            # 2. 三关掉落
            loot = _find(bot, '获得物品.png', multi_scale=False, threshold=0.82)
            if loot is None:
                loot = _abs_pos(bot, bot.find_image(
                    os.path.join(_BASE_DIR, 'templates', 'shilian', '获得物品.png'),
                    threshold=0.82, multi_scale=False))
            if loot is not None:
                bot._log('获得物品 → 点空白返回')
                if fighting_stage and _stage_ge(fighting_stage, stop):
                    loot_seen_for_stop = True
                _click_blank(bot)
                if loot_seen_for_stop:
                    bot._log(f'[OK] 已打完停止关 #{stop[0]}-{stop[1]}')
                    return True
                stale = 0
                continue

            # 3. 战斗结算 / 章节完成（最后一关通关）
            chapter_done = _find(bot, '章节完成.png', multi_scale=False, threshold=0.75)
            end = _find(bot, '异常排除.png', multi_scale=False, threshold=0.82)
            if end is None:
                end = _find(bot, '点击空白返回.png', multi_scale=False, threshold=0.80)
            if chapter_done is not None or end is not None:
                if chapter_done is not None:
                    bot._log('章节完成 → 点空白继续')
                    if fighting_stage and _stage_ge(fighting_stage, stop):
                        loot_seen_for_stop = True
                else:
                    bot._log('异常排除 → 点空白返回')
                _click_blank(bot)
                if loot_seen_for_stop:
                    bot._log(f'[OK] 已打完停止关 #{stop[0]}-{stop[1]}')
                    return True
                stale = 0
                continue

            # 4. 布阵开打
            fight = _find(bot, '主线战斗.png')
            if fight is None:
                fight = _abs_pos(bot, bot.find_image(tpl('F战斗.png')))
            if fight is not None:
                if not _wait_story_battle(bot, use_preset):
                    return False
                stale = 0
                continue

            # 5. 前往挑战
            go = _find(bot, '主线前往挑战.png')
            if go is not None:
                try:
                    stage = _ocr_current_stage(bot)
                except Exception as e:
                    bot._log(f'OCR 跳过: {e}')
                    stage = None
                if stage is not None:
                    last_stage = stage
                    if _stage_gt(stage, stop):
                        bot._log(f'当前 #{stage[0]}-{stage[1]} 已超过停止关，结束')
                        return True
                fighting_stage = stage or last_stage
                bot._log('点击前往挑战')
                _click(bot, go)
                # 进战斗有 Scripts Loading，最多等 25s 直到出现战斗/跳过/结算
                deadline = time.time() + 25
                while time.time() < deadline and bot.is_running:
                    time.sleep(1.2)
                    if (_find(bot, '主线战斗.png') is not None
                            or _find(bot, '主线跳过.png') is not None
                            or _find(bot, '异常排除.png') is not None
                            or bot.find_image(tpl('F战斗.png')) is not None):
                        break
                stale = 0
                continue

            # 6. 当前进度 NEW：先模板，失败则按黄色色块找（960 下模板经常 miss）
            marker = _find(bot, '主线NEW.png')
            if marker is None:
                yellows = find_all_by_color(bot, target_rgb=(255, 214, 40), tolerance=45)
                # 丢掉标题栏 / 底栏聊天
                gw = bot.game_window
                yellows = [p for p in yellows
                           if gw.top + 40 < p[1] < gw.top + gw.height - 80]
                if yellows:
                    # 偏地图中线的那个（主进度），不要最边上的支线
                    mid_x = gw.left + gw.width // 2
                    yellows.sort(key=lambda p: abs(p[0] - mid_x))
                    marker = yellows[0]
                    bot._log(f'黄色 NEW 色块 {marker}')
            if marker is not None:
                lock = _find(bot, '主线锁定.png')
                if lock is not None and abs(lock[0] - marker[0]) < 80 and abs(lock[1] - marker[1]) < 80:
                    bot._log('[WARN] NEW 附近有锁，跳过该点')
                else:
                    bot._log('点击 NEW 节点')
                    _click(bot, marker)
                    time.sleep(1.8)
                stale = 0
                continue

            # 7. 章节选择页（必须 CHAPTER/普通模式 同时在，避免点到地图上的章节名）
            if _on_chapter_select(bot):
                card = _find(bot, '主线章节名.png')
                if card is None:
                    card = _find(bot, '主线章节.png')
                if card is not None:
                    bot._log('点击章节卡进入地图')
                    _click(bot, card)
                    time.sleep(2)
                    stale = 0
                    continue

            # 8. 底栏主线 / 主页挑战
            bar = _bottom_bar_region(bot)
            tab = _find(bot, '主线页签.png', region=bar)
            if tab is not None:
                bot._log('点击主线页签')
                _click(bot, tab)
                time.sleep(1.5)
                stale = 0
                continue

            home = _find(bot, '主页挑战.png', multi_scale=False, threshold=0.88)
            if home is not None:
                bot._log('点击主页挑战')
                _click(bot, home)
                time.sleep(1.5)
                stale = 0
                continue

            stale += 1
            bot._log(f'未识别到可操作界面 ({stale}/{GAME_CONFIG.zhuxian_stale_rounds})')
            if stale >= GAME_CONFIG.zhuxian_stale_rounds:
                if loot_seen_for_stop or (fighting_stage and _stage_ge(fighting_stage, stop)):
                    bot._log(f'[OK] 停止关已打过，结束')
                    return True
                bot._log('[FAIL] 连续多轮无法识别界面')
                return False
            time.sleep(1.2)

        bot._log('主线被停止')
        return False
    finally:
        bot._running = False
