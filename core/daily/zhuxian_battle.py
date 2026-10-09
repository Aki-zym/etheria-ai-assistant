"""
主线推图模块：按画面里出现的模板决定下一步，没有全局状态机。
停止关可配（默认 4-7），后面章节改参数即可。
"""
import os
import re
import time

import numpy as np

from core._base.input import post_click
from core._common.battle_common import (
    tpl, wait_for_image, setup_preset, find_all_by_color)
from core.config import GAME_CONFIG

_BASE_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
_ZHUXIAN_TPL = os.path.join(_BASE_DIR, 'templates', 'zhuxian')

# 弹窗标题 #X-Y 的 8×12 点阵（Segoe UI Bold），不依赖 paddlepaddle
_STAGE_GLYPHS = {
    '0': 0x3c7e77e7e7e7e7e7e7f77e3c, '1': 0xfffffff0f0f0f0f0f0f0f0f,
    '2': 0x7cfecf07070e1e7870e0ffff, '3': 0x7c7e4f070e7c7e0f0787fffc,
    '4': 0xe0e1e3e3e7e6effffff0e0e, '5': 0x7efee0e0f8feff07078ffefc,
    '6': 0x1e3e70e0fcfff7e7e7e77e3c, '7': 0xffff070e0e1c1c1838383830,
    '8': 0x3c7ee7e77e7c7ee7e7e7fe7c, '9': 0x3c7ee7e7e7ff7f37070efe78,
    '#': 0x3636367fff366cfefe6c6c48,
}


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
    return (0, int(gw.height * 0.82), gw.width, gw.height)


def _click(bot, pos):
    post_click(bot.game_window.hwnd, pos[0], pos[1])


def _click_blank(bot):
    """结算 / 章节完成页点画面中心空白返回，避开左下战斗统计。"""
    gw = bot.game_window
    x = gw.left + gw.width // 2
    y = gw.top + int(gw.height * 0.91)
    bot._log(f'点击空白返回 ({x}, {y})')
    post_click(gw.hwnd, x, y)
    time.sleep(1.2)


def _collapsed(bot) -> bool:
    """系统陷落失败页。旧模板在 2024×1098 只有 ~0.60，会漏成未知界面。"""
    return _find(bot, tpl('系统陷落.png')) is not None


def _battle_ended(bot) -> bool:
    """战斗结束：异常排除/获得物品/章节完成。默认 _find（0.82 单尺度真机会漏异常排除），静默查避免刷 miss。"""
    return (
        _find(bot, '异常排除.png') is not None
        or _find(bot, '点击空白返回.png') is not None
        or _find(bot, '获得物品.png', threshold=0.85) is not None
        or _find(bot, '章节完成.png') is not None
    )


def _ocr_current_stage(bot):
    """弹窗左侧标题 #X-Y：8×12 点阵匹配，不依赖 paddlepaddle。"""
    img = bot.capture()
    if img is None:
        return None
    import cv2
    w, h = img.size
    gray = cv2.cvtColor(np.array(img.crop(
        (int(w * 0.08), int(h * 0.22), int(w * 0.42), int(h * 0.48)))), cv2.COLOR_RGB2GRAY)
    # WGC 有时比人眼暗（标题最高约 170），固定 180 会把字滤掉
    _, th = cv2.threshold(gray, max(130, min(180, int(gray.max() * 0.82))), 255, cv2.THRESH_BINARY)
    n, _, st, _ = cv2.connectedComponentsWithStats(th, 8)
    glyphs = {c: np.array([(v >> (95 - i)) & 1 for i in range(96)], np.uint8).reshape(12, 8)
              for c, v in _STAGE_GLYPHS.items()}
    items = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if bh < 18 or bh > 80 or area < 40 or bw > 50 or y > gray.shape[0] * 0.65:
            continue
        b = cv2.resize(th[y:y + bh, x:x + bw], (8, 12), interpolation=cv2.INTER_AREA)
        b = (b > 80).astype(np.uint8)
        best, who = 29, None
        for ch, g in glyphs.items():
            d = int(np.count_nonzero(b != g))
            if d < best:
                best, who = d, ch
        if who:
            items.append((int(x), who, int(x + bw)))
    digits = [t for t in sorted(items) if t[1] != '#']
    if len(digits) < 2:
        return None
    if len(digits) == 2:
        stage = (int(digits[0][1]), int(digits[1][1]))
    else:
        cut = max(range(1, len(digits)), key=lambda i: digits[i][0] - digits[i - 1][2])
        stage = (int(''.join(t[1] for t in digits[:cut])),
                 int(''.join(t[1] for t in digits[cut:])))
    bot._log(f'OCR 关卡: #{stage[0]}-{stage[1]}')
    return stage


def _read_stage(bot):
    """OCR 当前关（#X-Y）；OCR 不可用/异常时 None。"""
    try:
        return _ocr_current_stage(bot)
    except Exception as e:
        bot._log(f'OCR 跳过: {e}')
        return None


def _use_stamina_potion(bot) -> bool:
    """在体力兑换弹窗内用体力药兑换体力。成功返回 True（弹窗已关闭）。"""
    bot._log('体力不足 → 自动使用体力药兑换...')
    potion_tpl = tpl('体力兑换药.png')
    if not os.path.exists(potion_tpl):
        bot._log('[WARN] 缺少模板 templates/richang/体力兑换药.png（体力兑换弹窗里的体力药图标），'
                 '可用界面「截模板」截取，或在主线面板关闭「体力不足自动用药」')
        return False
    pos = wait_for_image(bot, potion_tpl, timeout=5)
    if pos is None:
        bot._log('[FAIL] 体力兑换弹窗中未找到体力药图标')
        return False
    _click(bot, pos)
    time.sleep(1.0)
    confirm = wait_for_image(bot, tpl('确定.png'), timeout=3)
    if confirm is None:
        confirm = wait_for_image(bot, tpl('协会提示确定按钮.png'), timeout=2)
    if confirm is not None:
        _click(bot, confirm)
        bot._log('已确认兑换')
    else:
        bot._log('未出现确认按钮（可能点药图标已直接兑换）')
    time.sleep(1.5)
    if _find(bot, tpl('体力兑换.png'), multi_scale=False) is None:
        bot._log('[OK] 体力兑换完成')
        return True
    bot._log('[FAIL] 兑换后体力兑换弹窗仍未关闭')
    return False


def _handle_out_of_stamina(bot, use_stamina_potion):
    """体力弹窗。返回 True=已处理继续，False=停止，None=没有弹窗。"""
    stable = _find(bot, '兑换稳定值.png', multi_scale=False)
    if stable is not None:
        if not use_stamina_potion:
            bot._log('[WARN] 稳定值不足，未开启自动兑换，停止主线')
            return False
        bot._log('稳定值不足，点击兑换稳定值')
        _click(bot, stable)
        time.sleep(1.2)
        if _find(bot, '兑换稳定值.png', multi_scale=False) is not None:
            bot._log('[FAIL] 兑换稳定值弹窗还在')
            return False
        bot._log('[OK] 已兑换稳定值')
        return True
    if _find(bot, tpl('体力兑换.png'), multi_scale=False) is not None:
        if not use_stamina_potion:
            bot._log('[WARN] STAMINA_MISSING: 体力不足，停止主线')
            return False
        return True if _use_stamina_potion(bot) else False
    return None


def _wait_story_battle(bot, use_preset: bool, use_stamina_potion: bool = False,
                       already_started: bool = False) -> bool:
    """进战斗后等待结束。返回 True=正常结束 / False=需中止 / 'failed'=战斗失败（已点空白返回）。"""
    hwnd = bot.game_window.hwnd
    if not already_started:
        # 前往挑战之后开战按钮已经在画面上，不再先空等 1 秒。
        # 用 _find：bot.find_image 每次没对上都会打「未找到匹配图标」。
        bot._log('检查手动模式...')
        manual = _find(bot, tpl('手动.png'), multi_scale=False)
        if manual is not None:
            _click(bot, manual)
            time.sleep(0.4)
        else:
            bot._log('未检测到手动按钮')

        if use_preset:
            if not setup_preset(bot):
                bot._log('[WARN] 预设失败，继续用场上队伍')

        fight = _await_fight_button(bot, timeout=8)
        if fight is None:
            bot._log('[FAIL] 未检测到战斗按钮')
            return False
        bot._log('点击战斗...')
        _click(bot, fight)
        # 点完战斗直接扫描：只有体力不足才弹体力弹窗，由循环内体力检测处理
        time.sleep(2)

    timeout = GAME_CONFIG.battle_end_timeout
    bot._log(f'战斗中，每 2s 扫结束标志（最多 {timeout}s）...')
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        if not bot.is_running:
            return False
        if _collapsed(bot):
            bot._log('[WARN] 系统陷落：战斗失败')
            _click_blank(bot)
            return 'failed'
        if _battle_ended(bot):
            seen += 1
            if seen >= 2:
                bot._log('检测到战斗结束标志')
                return True
        else:
            seen = 0
        stamina = _handle_out_of_stamina(bot, use_stamina_potion)
        if stamina is False:
            return False
        if stamina:
            time.sleep(1.5)
            again = _find(bot, '主线战斗.png', multi_scale=False)
            if again is None:
                again = _find(bot, tpl('F战斗.png'), multi_scale=False)
            if again is not None:
                bot._log('重新点击战斗...')
                _click(bot, again)
                time.sleep(2)
        time.sleep(2)
    bot._log('[WARN] 等待战斗结束超时，继续')
    return True



def _entry_button_names():
    return (
        '主线战斗.png',
        '主线跳过.png',
        '异常排除.png',
        tpl('F战斗.png'),
        tpl('手动.png'),
    )


def _scan_buttons(bot, names, multi_scale):
    hits = {}
    for name in names:
        pos = _find(bot, name, multi_scale=multi_scale)
        if pos is not None:
            hits[os.path.basename(name)] = pos
    return hits


def _await_fight_button(bot, timeout):
    names = ('主线战斗.png', tpl('F战斗.png'))
    deadline = time.time() + timeout
    while time.time() < deadline and bot.is_running:
        hits = _scan_buttons(bot, names, False)
        if not hits:
            hits = _scan_buttons(bot, names, True)
        pos = hits.get('主线战斗.png') or hits.get('F战斗.png')
        if pos is not None:
            return pos
        time.sleep(0.2)
    return None


def _wait_battle_entry(bot):
    deadline = time.time() + 25
    while time.time() < deadline and bot.is_running:
        popup = _find(bot, '关卡弹窗前往挑战.png', threshold=0.80, multi_scale=False)
        if popup is not None:
            bot._log('弹窗还在，再次点击前往挑战')
            _click(bot, popup)
            time.sleep(1.0)
            continue
        names = _entry_button_names()
        hits = _scan_buttons(bot, names, False)
        fight = hits.get('主线战斗.png') or hits.get('F战斗.png')
        if (fight is None and '主线跳过.png' not in hits
                and '异常排除.png' not in hits):
            for name, pos in _scan_buttons(bot, names, True).items():
                hits.setdefault(name, pos)
            fight = hits.get('主线战斗.png') or hits.get('F战斗.png')
        if not hits:
            time.sleep(0.2)
            continue
        if fight is not None:
            manual = hits.get('手动.png')
            if manual is not None:
                bot._log('点击手动，改为自动')
                _click(bot, manual)
                time.sleep(0.15)
            if GAME_CONFIG.zhuxian_use_preset:
                if not setup_preset(bot):
                    bot._log('[WARN] 预设失败，继续用场上队伍')
            bot._log('点击战斗...')
            _click(bot, fight)
            time.sleep(2)
            return True
        if '主线跳过.png' in hits:
            bot._log('点击跳过')
            _click(bot, hits['主线跳过.png'])
            time.sleep(0.3)
            continue
        if '异常排除.png' in hits:
            return False
        time.sleep(0.2)
    return False


def _map_new_marker(bot):
    """地图 NEW：先模板（960 下经常 miss），失败用黄色色块兜底。色块只在地图
    ROI 内认——排除标题栏、底栏聊天、子关弹窗金色图标——取最靠中线的（主进度），
    不能把任意黄色轮廓当主线进度。"""
    gw = bot.game_window
    y_hi = int(gw.height * 0.82)
    marker = _find(bot, '主线NEW.png', region=(0, 40, gw.width, y_hi))
    if marker is not None:
        return marker
    yellows = [p for p in find_all_by_color(bot, target_rgb=(255, 214, 40), tolerance=45)
               if gw.top + 40 < p[1] < gw.top + y_hi
               and not (p[0] > gw.left + gw.width * 0.72
                        and p[1] < gw.top + gw.height * 0.42)]
    if not yellows:
        return None
    mid_x = gw.left + gw.width // 2
    yellows.sort(key=lambda p: abs(p[0] - mid_x))
    bot._log(f'黄色 NEW 色块 {yellows[0]}')
    return yellows[0]


def _near_lock(bot, marker):
    """NEW 位置邻近锁定图标则不可点。"""
    lock = _find(bot, '主线锁定.png')
    return (lock is not None and abs(lock[0] - marker[0]) < 80
            and abs(lock[1] - marker[1]) < 80)


def _on_chapter_select(bot) -> bool:
    """章节选择页：CHAPTER / 普通模式。章节名也会出现在关卡地图里，不能单独当信号。"""
    return _find(bot, '主线章节.png') is not None or _find(bot, '普通模式.png') is not None


def _enter_chapter_card(bot) -> bool:
    """要打的章在中间时点正中一次进图；锁了点左、已通关点右后再点正中。"""
    gw = bot.game_window
    mid = (gw.left + gw.width // 2, gw.top + gw.height // 2)
    bot._log(f'点击章节正中 {mid}'); _click(bot, mid); time.sleep(2)
    if not _on_chapter_select(bot):
        return True
    fx = 0.18 if _find(bot, '主线锁定.png') else 0.86
    side = (gw.left + int(gw.width * fx), gw.top + int(gw.height * 0.42))
    bot._log(f'点击侧章 {side}'); _click(bot, side); time.sleep(2)
    bot._log(f'点击章节正中 {mid}'); _click(bot, mid); time.sleep(2)
    return not _on_chapter_select(bot)


def _already_in_story_flow(bot) -> bool:
    """关卡地图 / 关卡弹窗 / 战斗 / 结算 / 剧情，都不必再从主界面进。"""
    if _on_chapter_select(bot):
        return False
    checks = ('主线前往挑战.png', '主线战斗.png', '异常排除.png',
              '获得物品.png', '主线跳过.png', '章节完成.png')
    for name in checks:
        if _find(bot, name) is not None:
            return True
    marker = _map_new_marker(bot)
    if marker is not None and not _near_lock(bot, marker):
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

    if not on_chapter:
        if not _click_story_tab(bot):
            return False
        if _already_in_story_flow(bot):
            return True
    _enter_chapter_card(bot)
    return True


def run_zhuxian_battle(bot, character_name: str = '', difficulty: str = '',
                       streak: int = 1, stop_stage: str = None,
                       from_home: bool = None,
                       use_stamina_potion: bool = None) -> bool:
    """自动推主线。stop_stage 默认 4-7，打完该关后的结算即停；体力药开关读 GAME_CONFIG。"""
    bot._running = True
    stop_stage = stop_stage or GAME_CONFIG.zhuxian_stop_stage or character_name or '4-7'
    if from_home is None:
        from_home = GAME_CONFIG.zhuxian_from_home
    if use_stamina_potion is None:
        use_stamina_potion = GAME_CONFIG.zhuxian_use_stamina_potion
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
        fail_count = 0
        last_stage = None
        fighting_stage = None
        loot_seen_for_stop = False
        new_miss = 0

        while bot.is_running:
            if _collapsed(bot):
                bot._log('[WARN] 系统陷落：战斗失败')
                _click_blank(bot)
                fail_count += 1
                bot._log(f'战斗失败 {fail_count}/3')
                if fail_count >= 3:
                    bot._log('[FAIL] 连续 3 次战斗失败（系统陷落），停止主线')
                    return False
                stale = 0
                continue
            stamina = _handle_out_of_stamina(bot, use_stamina_potion)
            if stamina is False:
                return False
            if stamina:
                stale = 0
                continue

            # 1. 剧情跳过（无确认）— 只在右上角找，避免和地图 UI 串
            gw = bot.game_window
            skip_region = (int(gw.width * 0.70), 0, gw.width, int(gw.height * 0.22))
            skip = _find(bot, '主线跳过.png', region=skip_region)
            if skip is not None:
                bot._log('点击跳过')
                _click(bot, skip)
                time.sleep(1.2)
                stale = 0
                continue
            auto = _find(bot, '主线剧情自动.png', region=skip_region)
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

            # 2. 三关掉落（只认主线模板；试炼模板/低阈值会把剧情页当掉落）
            loot = _find(bot, '获得物品.png', threshold=0.85)
            if loot is not None:
                bot._log('获得物品 → 点空白返回')
                if fighting_stage and _stage_ge(fighting_stage, stop):
                    loot_seen_for_stop = True
                _click_blank(bot)
                if loot_seen_for_stop:
                    for _ in range(3):
                        if not _battle_ended(bot):
                            break
                        _click_blank(bot)
                    bot._log(f'[OK] 已打完停止关 #{stop[0]}-{stop[1]}')
                    return True
                fail_count = 0  # 胜利后清空连败计数
                stale = 0
                continue

            # 3. 战斗结算 / 章节完成条。章节完成只是过场，不等于整关打完；停关看掉落或下一关号
            chapter_done = _find(bot, '章节完成.png', threshold=0.85)
            end = _find(bot, '异常排除.png')
            if end is None:
                end = _find(bot, '点击空白返回.png')
            if chapter_done is not None or end is not None:
                bot._log('章节完成 → 点空白继续' if chapter_done else '异常排除 → 点空白返回')
                _click_blank(bot)
                fail_count = 0
                stale = 0
                continue

            # 4. 布阵开打
            fight = _find(bot, '主线战斗.png')
            if fight is None:
                fight = _abs_pos(bot, bot.find_image(tpl('F战斗.png')))
            if fight is not None:
                result = _wait_story_battle(bot, use_preset, use_stamina_potion)
                if result == 'failed':
                    fail_count += 1
                    bot._log(f'战斗失败 {fail_count}/3')
                    if fail_count >= 3:
                        bot._log('[FAIL] 连续 3 次战斗失败（系统陷落），停止主线')
                        return False
                elif not result:
                    return False
                stale = 0
                continue

            # 5. 前往挑战
            go = _find(bot, '主线前往挑战.png')
            if go is not None:
                stage = _read_stage(bot)
                if stage is not None:
                    last_stage = stage
                    if _stage_gt(stage, stop):
                        bot._log(f'当前 #{stage[0]}-{stage[1]} 已超过停止关，结束')
                        return True
                fighting_stage = stage or last_stage
                bot._log('点击前往挑战')
                _click(bot, go)
                started = _wait_battle_entry(bot)
                stale = 0
                if started:
                    result = _wait_story_battle(
                        bot, use_preset, use_stamina_potion, already_started=True)
                    if result == 'failed':
                        fail_count += 1
                        bot._log(f'战斗失败 {fail_count}/3')
                        if fail_count >= 3:
                            bot._log('[FAIL] 连续 3 次战斗失败（系统陷落），停止主线')
                            return False
                    elif not result:
                        return False
                continue

            # 5.5 关卡选择弹窗：底部「敌方情报」金色图标也是黄色且更靠中线，
            # 会污染通用 NEW 色块逻辑（点小怪无效果 → 永久循环），必须提前精确处理
            popup_go = _find(bot, '关卡弹窗前往挑战.png', threshold=0.80)
            if popup_go is not None:
                stage = _read_stage(bot)
                if stage is not None:
                    last_stage = stage
                    if _stage_gt(stage, stop):
                        bot._log(f'当前 #{stage[0]}-{stage[1]} 已超过停止关，结束')
                        return True
                badge = _find(bot, '关卡弹窗NEW.png', threshold=0.72)
                if badge is None:
                    # 模板兜底：只在弹窗右侧子关列表区域内找黄色点
                    gw = bot.game_window
                    yellows = find_all_by_color(bot, target_rgb=(255, 214, 40), tolerance=45)
                    in_popup = [p for p in yellows
                                if p[0] > gw.left + gw.width * 0.62
                                and gw.top + 40 < p[1] < gw.top + gw.height * 0.55]
                    if in_popup:
                        in_popup.sort(key=lambda p: (p[1], p[0]))
                        badge = in_popup[0]
                        bot._log(f'关卡弹窗：色块定位 NEW 子关 {badge}')
                if badge is not None:
                    bot._log('关卡弹窗：点击 NEW 子关')
                    _click(bot, badge)
                    time.sleep(0.8)
                else:
                    bot._log('[WARN] 关卡弹窗内无 NEW 子关，点空白关闭弹窗')
                    _click_blank(bot)
                    continue
                fighting_stage = stage or last_stage
                fresh = _find(bot, '关卡弹窗前往挑战.png', threshold=0.80, multi_scale=False)
                if fresh is not None:
                    popup_go = fresh
                bot._log('关卡弹窗：点击前往挑战')
                _click(bot, popup_go)
                new_miss = 0
                started = _wait_battle_entry(bot)
                stale = 0
                if started:
                    result = _wait_story_battle(
                        bot, use_preset, use_stamina_potion, already_started=True)
                    if result == 'failed':
                        fail_count += 1
                        bot._log(f'战斗失败 {fail_count}/3')
                        if fail_count >= 3:
                            bot._log('[FAIL] 连续 3 次战斗失败（系统陷落），停止主线')
                            return False
                    elif not result:
                        return False
                continue

            # 6. 章节选择先于地图 NEW（底栏/特殊篇 NEW 不是地图节点）
            if _on_chapter_select(bot):
                stale = 0 if _enter_chapter_card(bot) else stale + 1
                if stale >= GAME_CONFIG.zhuxian_stale_rounds:
                    bot._log('[FAIL] 章节选择无法进图')
                    return False
                continue

            # 7. 当前进度 NEW（模板 miss 时的黄色色块兜底见 _map_new_marker）
            marker = _map_new_marker(bot)
            if marker is not None:
                if _near_lock(bot, marker):
                    bot._log('[WARN] NEW 附近有锁，跳过该点')
                else:
                    # 时间轴上胶片压红线，点下去会拖地图，改点角标（密会已验证可开）；
                    # 轴下剧情卡点胶片播放三角。
                    line_y = gw.top + int(gw.height * 531 / 1098)
                    if abs(marker[1] - line_y) < 40:
                        face = marker
                    else:
                        face = (marker[0] - int(gw.width * 45 / 2024),
                                marker[1] + int(gw.height * 40 / 1098))
                    bot._log(f'点击 NEW 卡面 {face}')
                    _click(bot, face)
                    opened = False
                    for _ in range(20):
                        if not bot.is_running:
                            break
                        opened = (_find(bot, '主线跳过.png') or _find(bot, '主线剧情自动.png')
                              or _find(bot, '关卡弹窗前往挑战.png', threshold=0.80)
                              or _find(bot, '获得物品.png', threshold=0.85))
                        if opened:
                            break
                        time.sleep(0.4)
                    if opened:
                        new_miss = 0
                    else:
                        new_miss += 1
                        if new_miss >= 3:
                            bot._log('[FAIL] 地图 NEW 连点 3 次未进关/剧情，停止')
                            return False
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
