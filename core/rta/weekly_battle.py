"""
RTA每周自动模块

全 PostMessage 后台点击，零键盘依赖。
"""
import cv2 as _cv2_buff
import os
import time

import numpy as np

from core._base.input import post_click, post_drag
from core._common.battle_common import (
    tpl, wait_for_image, open_sidebar, exit_battle,
    _find_manual_button, wait_for_image_gone,
)
from core.config import GAME_CONFIG

_BASE_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
_RTA_TPL = os.path.join(_BASE_DIR, 'templates', 'rta')


def _rtpl(name: str) -> str:
    """RTA模板路径 — templates/rta/"""
    return os.path.join(_RTA_TPL, name)


def _wait_buff_gone(bot, timeout: float, confirm_times: int = 3, interval: float = 5):
    """等 Buff 消失。每 interval 秒检测一次，连续 confirm_times 次未匹配到判定消失。

    Buff 可能在战斗中短暂消失（过场/动画），用 5s 间隔避免误判。
    """
    from core._base.template_match import _imread as _read_tpl
    tpl_buff = _read_tpl(tpl('Buff.png'))
    if tpl_buff is None:
        bot._log('[WARN] Buff.png 模板无法读取，回退到 wait_for_image_gone')
        return wait_for_image_gone(bot, tpl('Buff.png'),
                                   timeout=timeout, confirm_times=confirm_times, interval=interval)

    deadline = time.time() + timeout
    gone_streak = 0

    while time.time() < deadline:
        if not bot.is_running:
            return False
        img = bot.capture()
        if img is None:
            gone_streak += 1
            bot._log(f'Buff 检测: 截图失败 ({gone_streak}/{confirm_times})')
        else:
            scr = _cv2_buff.cvtColor(np.array(img), _cv2_buff.COLOR_RGB2BGR)
            result = _cv2_buff.matchTemplate(
                scr, tpl_buff, _cv2_buff.TM_CCOEFF_NORMED)
            _, max_val, _, _ = _cv2_buff.minMaxLoc(result)
            if max_val >= 0.7:
                gone_streak = 0
                bot._log(f'Buff 仍在 ({max_val:.2%})')
            else:
                gone_streak += 1
                bot._log(
                    f'Buff 未匹配 ({max_val:.2%}) ({gone_streak}/{confirm_times})')
                if gone_streak >= confirm_times:
                    bot._log(f'Buff 连续 {confirm_times} 次未匹配，判定已消失')
                    return True
        time.sleep(interval)
    bot._log(f'超时 {timeout}s，Buff 仍未消失')
    return False


_VICTORY = object()


class _VictoryDetected(Exception):
    """对手直接投降，跳过当前局剩余步骤"""
    pass


def _check_victory(bot):
    """快速检查是否出现直接胜利结算界面"""
    v = bot.find_image(_rtpl('巅峰直接胜利.png'), multi_scale=False)
    if v is not None:
        bot._log(f'🎉 检测到巅峰直接胜利！({v.confidence:.1%})')
        return True
    return False


def _wait_or_victory(bot, template, timeout=None, check_interval=0.5):
    """等待模板出现，期间每 check_interval 秒检测对手投降。

    Returns:
        (x, y) — 模板匹配成功 (屏幕绝对坐标)
        _VICTORY — 检测到对手直接胜利
        None — 超时未匹配
    """
    # 解析模板路径：完整路径直接使用，否则走 _rtpl
    tpl_path = template if (os.path.isabs(
        template) or '/' in template or '\\' in template) else _rtpl(template)
    timeout = timeout or 30
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not bot.is_running:
            return None
        if _check_victory(bot):
            return _VICTORY
        match = bot.find_image(tpl_path)
        if match:
            time.sleep(0.15)
            match2 = bot.find_image(tpl_path)
            if match2 is not None:
                abs_x = bot.game_window.left + match2.x
                abs_y = bot.game_window.top + match2.y
                return (abs_x, abs_y)
        time.sleep(check_interval)

    # 超时前最后检查一次 victory
    if _check_victory(bot):
        return _VICTORY
    return None


def _wait(bot, template, timeout=None, label=''):
    """wait + victory check。对手投降时抛出 _VictoryDetected。"""
    result = _wait_or_victory(bot, template, timeout=timeout)
    if result is _VICTORY:
        bot._log(f'对手直接胜利 → 跳过剩余流程 ({label})')
        raise _VictoryDetected()
    if result is None:
        bot._log(f'[FAIL] 未检测到: {label or template}')
    return result


def run_rta_weekly_battle(bot, character_name: str = '', difficulty: str = '普通', streak: int = 1) -> bool:
    """RTA每周完整流程。streak 决定步骤 4-8 循环次数。"""
    hwnd = bot.game_window.hwnd
    bot._running = True
    import cv2
    try:
        bot._log('=' * 40)
        bot._log(f'RTA每周开始 → {difficulty} ×{streak}')
        bot._log('=' * 40)

        # === 1. 回到主界面 ===
        bot._log('回到主界面...')
        bot.go_back_to_main(tpl('返回.png'))
        time.sleep(0.5)

        # === 2. 开侧边栏 → 点竞技场图标 ===
        if not open_sidebar(bot):
            return False
        bot._log('点击竞技场图标...')
        pos = wait_for_image(bot, '竞技场图标.png')
        if pos is None:
            return False
        post_click(hwnd, pos[0], pos[1])
        time.sleep(2)

        # === 3. 点击巅峰竞技场入口（rta 模板） ===
        pos = wait_for_image(bot, _rtpl('巅峰竞技场入口.png'))
        if pos is None:
            return False
        post_click(hwnd, pos[0], pos[1])
        time.sleep(2)

        # === 4-8 循环：根据 streak 次数重复 ===
        for r in range(streak):
            if not bot.is_running:
                break
            bot._log(f'=== RTA 第 {r+1}/{streak} 局 ===')

            try:
                time.sleep(2)
                # === 4. 匹配 → 判定先手/后手 ===
                bot._log('点击巅峰匹配...')
                pos = _wait(bot, _rtpl('巅峰匹配.png'), label='巅峰匹配')
                if pos is None:
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(2)

                # 先等 bp 界面加载完成
                bot._log('等待 BP 界面加载...')
                bp_deadline = time.time() + 180
                bp_found = None
                while bot.is_running and time.time() < bp_deadline:
                    if _check_victory(bot):
                        raise _VictoryDetected()
                    bp_found = bot.find_image(
                        _rtpl('bp标志.png'), multi_scale=False)
                    if bp_found is not None:
                        bot._log(f'BP 界面已加载 ({bp_found.confidence:.1%})')
                        break
                    time.sleep(5)
                if bp_found is None:
                    bot._log('[FAIL] 180s 内未检测到 BP 界面')
                    return False

                # 交替识别先手/后手，都识别到后选置信度高的
                first_move = None  # True=先手, False=后手
                deadline = time.time() + 180
                toggle = True  # True=识别先手, False=识别后手
                conf_f = 0.0
                conf_l = 0.0
                while bot.is_running and first_move is None and time.time() < deadline:
                    if _check_victory(bot):
                        raise _VictoryDetected()
                    if toggle:
                        m_f = bot.find_image(
                            _rtpl('巅峰先手bp.png'), multi_scale=False)
                        if m_f is not None:
                            conf_f = m_f.confidence
                            bot._log(f'先手 置信度: {conf_f:.1%}')
                    else:
                        m_l = bot.find_image(
                            _rtpl('巅峰后手bp.png'), multi_scale=False)
                        if m_l is not None:
                            conf_l = m_l.confidence
                            bot._log(f'后手 置信度: {conf_l:.1%}')
                    toggle = not toggle

                    # 两边都识别到了 → 选高的
                    if conf_f > 0 and conf_l > 0:
                        if conf_f >= conf_l:
                            first_move = True
                            bot._log(
                                f'判定: 先手 (先手{conf_f:.1%} ≥ 后手{conf_l:.1%})')
                        else:
                            first_move = False
                            bot._log(
                                f'判定: 后手 (后手{conf_l:.1%} > 先手{conf_f:.1%})')
                        break
                    time.sleep(0.3)
                if first_move is None:
                    bot._log('[FAIL] 180s 内未检测到先手/后手 bp')
                    return False

                # === 5. 全部相性 → ban 属性 ===
                bot._log('点击巅峰全部相性...')
                pos = _wait(bot, _rtpl('巅峰全部相性.png'), label='巅峰全部相性')
                if pos is None:
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(1)

                ban_tpl = _rtpl('巅峰先手必ban属性.png') if first_move else _rtpl(
                    '巅峰后手必ban属性.png')
                bot._log(f'点击 {"先手" if first_move else "后手"}必ban属性...')
                pos = _wait(bot, ban_tpl, label='必ban属性')
                if pos is None:
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(1)

                # === 6. 选择 BP 角色 + 确认设置 ===
                sel_tpl = _rtpl('巅峰先手选择bp角色.png') if first_move else _rtpl(
                    '巅峰后手选择bp角色.png')
                bot._log(f'点击 {"先手" if first_move else "后手"}选择bp角色...')
                pos = _wait(bot, sel_tpl, label='选择bp角色')
                if pos is None:
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(1)

                pos = _wait(bot, _rtpl('确认设置.png'), label='确认设置')
                if pos is None:
                    bot._log('[FAIL] 未检测到确认设置')
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(2)

                # === 7. 三阶段选人 ===
                phases = [
                    ('第一阶段.png', 1 if first_move else 2),
                    ('第二阶段.png', 2 if first_move else 2),
                    ('第三阶段.png', 2 if first_move else 1),
                ]
                for phase_tpl, picks_needed in phases:
                    bot._log(f'等待{phase_tpl}...')
                    while bot.is_running:
                        if _check_victory(bot):
                            raise _VictoryDetected()
                        pos = wait_for_image(bot, _rtpl(phase_tpl))
                        if pos is not None:
                            break
                        time.sleep(0.3)

                    for pick_i in range(picks_needed):
                        bot._log(
                            f'  {phase_tpl[:4]} 选人 #{pick_i+1}/{picks_needed}')
                        # 找所有置顶角色
                        from core._base.template_match import _imread as _read_tpl
                        tpl_top = _read_tpl(_rtpl('置顶角色.png'))
                        if tpl_top is None:
                            bot._log('[WARN] 置顶角色模板无法读取')
                            break
                        gw = bot.game_window

                        while bot.is_running:
                            if _check_victory(bot):
                                raise _VictoryDetected()
                            img = bot.capture()
                            if img is None:
                                break
                            scr = cv2.cvtColor(
                                np.array(img), cv2.COLOR_RGB2BGR)
                            result = cv2.matchTemplate(
                                scr, tpl_top, cv2.TM_CCOEFF_NORMED)
                            loc = np.where(
                                result >= 0.8)
                            # 打印所有 >=0.8 的匹配点及其置信度（调试用）
                            matched_confs = result[result >= 0.8]
                            if len(matched_confs) > 0:
                                bot._log(f'    置顶角色匹配: {len(matched_confs)} 个点 >=0.8, '
                                         f'最高 {np.max(matched_confs):.2%}')
                            pts = []
                            for pt in zip(*loc[::-1]):
                                if not any(abs(pt[0]-p[0]) < 20 and abs(pt[1]-p[1]) < 20 for p in pts):
                                    pts.append(pt)
                            if pts:
                                # 从左到右排序
                                pts.sort(key=lambda p: p[0])
                                blocked_count = 0

                                for pick_i, (cx_w, cy_w) in enumerate(pts):
                                    screen_x = gw.left + cx_w + \
                                        tpl_top.shape[1] // 2
                                    screen_y = gw.top + cy_w + \
                                        tpl_top.shape[0] // 2
                                    bot._log(
                                        f'    点击置顶角色 #{pick_i+1} ({screen_x}, {screen_y})')
                                    post_click(hwnd, screen_x, screen_y)
                                    time.sleep(0.4)

                                    # 检测三种封锁标志
                                    blocked = (
                                        bot.find_image(_rtpl('对方已选择.png'), multi_scale=False) is not None or
                                        bot.find_image(_rtpl('巅峰已禁用.png'), multi_scale=False) is not None or
                                        bot.find_image(
                                            _rtpl('巅峰已选择.png'), multi_scale=False) is not None
                                    )
                                    if not blocked:
                                        blocked_count = 0
                                        break
                                    blocked_count += 1
                                    bot._log(f'    检测到封锁标志，1.8s后点击下一个置顶角色...')
                                    time.sleep(1.8)

                                # 所有置顶角色都被封锁 → 拖动刷新列表
                                if blocked_count == len(pts):
                                    bot._log('    所有置顶角色均被封锁，拖动刷新...')
                                    last_pt = pts[-1]
                                    drag_x = int(
                                        gw.left + last_pt[0] + tpl_top.shape[1] // 2)
                                    drag_y = int(
                                        gw.top + last_pt[1] + tpl_top.shape[0] // 2)
                                    for _ in range(3):
                                        post_drag(hwnd, drag_x, drag_y, drag_x - 75, drag_y,
                                                  steps=10, step_delay=0.015)
                                        time.sleep(0.3)
                                    time.sleep(1)
                                    # 重新扫描
                                    img2 = bot.capture()
                                    if img2 is not None and tpl_top is not None:
                                        scr2 = cv2.cvtColor(
                                            np.array(img2), cv2.COLOR_RGB2BGR)
                                        result2 = cv2.matchTemplate(
                                            scr2, tpl_top, cv2.TM_CCOEFF_NORMED)
                                        loc2 = np.where(
                                            result2 >= 0.8)
                                        pts2 = []
                                        for pt in zip(*loc2[::-1]):
                                            if not any(abs(pt[0]-p[0]) < 20 and abs(pt[1]-p[1]) < 20 for p in pts2):
                                                pts2.append(pt)
                                        if pts2:
                                            pts2.sort(key=lambda p: p[0])
                                            for cx_w, cy_w in pts2:
                                                screen_x = gw.left + cx_w + \
                                                    tpl_top.shape[1] // 2
                                                screen_y = gw.top + cy_w + \
                                                    tpl_top.shape[0] // 2
                                                bot._log(
                                                    f'    刷新后点击置顶角色 ({screen_x}, {screen_y})')
                                                post_click(
                                                    hwnd, screen_x, screen_y)
                                                time.sleep(0.4)

                                                blocked = (
                                                    bot.find_image(_rtpl('对方已选择.png'), multi_scale=False) is not None or
                                                    bot.find_image(_rtpl('巅峰已禁用.png'), multi_scale=False) is not None or
                                                    bot.find_image(
                                                        _rtpl('巅峰已选择.png'), multi_scale=False) is not None
                                                )
                                                if not blocked:
                                                    break
                                                bot._log(
                                                    f'    刷新后检测到封锁标志，1.5s后点击下一个...')
                                                time.sleep(1.5)
                                        else:
                                            bot._log('    刷新后仍未找到置顶角色')

                                # 完成本轮选人 → 确认
                                pos_cfm = wait_for_image(
                                    bot, _rtpl('巅峰确认选择.png'))
                                if pos_cfm is not None:
                                    post_click(hwnd, pos_cfm[0], pos_cfm[1])
                                    time.sleep(1)
                                break
                            time.sleep(0.5)

                # === 8. 保护禁用阶段 ===
                bot._log('等待保护禁用...')
                pos = _wait(bot, _rtpl('保护禁用.png'), label='保护禁用')
                if pos is None:
                    return False

                # 点击位置 = 保护禁用左偏移 150px
                click_x = pos[0] - 150
                click_y = pos[1]
                bot._log(f'保护禁用偏移点击 ({click_x}, {click_y})')
                post_click(hwnd, click_x, click_y)
                time.sleep(1)

                pos = _wait(bot, _rtpl('确认禁用.png'), label='确认禁用')
                if pos is None:
                    return False
                post_click(hwnd, pos[0], pos[1])
                time.sleep(2)

                # === 9. 等 Buff 出现 → 手动检测 → 等 Buff 消失 → exit ===
                bot._log('等待 Buff 出现（战斗加载中）...')
                buff_pos = _wait_or_victory(bot, tpl('Buff.png'),
                                            timeout=GAME_CONFIG.battle_end_timeout)
                if buff_pos is _VICTORY:
                    raise _VictoryDetected()
                if buff_pos is not None:
                    bot._log('Buff 已出现，开始检查手动模式...')

                manual_pos = _find_manual_button(bot)
                if manual_pos is not None:
                    bot._log('检测到手动按钮')
                    post_click(hwnd, manual_pos[0], manual_pos[1])
                    time.sleep(0.5)
                else:
                    bot._log('未检测到手动按钮')

                bot._log('等待 Buff 消失...')
                timeout = GAME_CONFIG.battle_end_timeout
                _wait_buff_gone(bot, timeout=timeout)

            except _VictoryDetected:
                bot._log(f'对手直接胜利，跳过当前局剩余步骤')

            exit_battle(bot, 5, 10)
            bot._log(f'=== 第 {r+1}/{streak} 局完成 ===')

        bot._log('[OK] RTA每周完成')
        bot._log('=' * 40)
        return True
    finally:
        bot._running = False
