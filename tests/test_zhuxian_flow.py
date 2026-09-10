"""
主线推图流程测试（不依赖真游戏窗口）。

覆盖：地图 NEW 点击走卡面偏移（不打色块中心）、_battle_ended 默认 _find 可命中、
5.5 关卡弹窗进关记 fighting_stage（否则结算不知道已到停止关）、
_already_in_story_flow 的黄色兜底 ROI 约束（底栏/标题栏/弹窗金色不算，地图才算）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core._base.window import GameWindow
from core.daily import zhuxian_battle as zb


def _gw():
    """真机比例窗口：2024x1098 客户区（左上 100,50）。"""
    return GameWindow(hwnd=777, title='测试', left=100, top=50,
                      right=100 + 2024, bottom=50 + 1098)


class FakeBot:
    def __init__(self, gw, alive=1):
        self.game_window = gw
        self._alive = alive
        self.logs = []

    @property
    def is_running(self):
        ok = self._alive > 0
        self._alive -= 1
        return ok

    def _log(self, msg):
        self.logs.append(str(msg))

    def find_image(self, path, **kw):
        return None

    def capture(self):
        return None

    def go_back_to_main(self, tpl_path):
        pass


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(zb.time, 'sleep', lambda s: None)


def _patch_clicks(monkeypatch, clicks):
    def fake_click(hwnd, x, y):
        clicks.append((x, y))
    monkeypatch.setattr(zb, 'post_click', fake_click)
    return fake_click


def _patch_find(monkeypatch, handler):
    def fake_find(b, name, multi_scale=True, threshold=None, region=None):
        return handler(str(name), multi_scale, threshold, region)
    monkeypatch.setattr(zb, '_find', fake_find)


# ---------------- 地图 NEW → 卡面偏移 ----------------

def test_map_new_clicks_card_face_not_badge(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=1)
    # 轴下剧情卡（密会）：点胶片，不是角标中心
    marker = (gw.left + 1000, gw.top + 686)
    _patch_find(monkeypatch, lambda n, ms, t, r: marker if n.endswith('主线NEW.png') else None)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    clicks = []
    _patch_clicks(monkeypatch, clicks)

    run = zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False)
    assert run is False  # 只跑一轮 NEW 分支，随后按 is_running 退出

    assert len(clicks) >= 1
    x, y = clicks[0]
    assert (x, y) != marker
    assert marker[0] - x == int(gw.width * 45 / 2024)
    assert y - marker[1] == int(gw.height * 40 / 1098)


def test_map_new_on_timeline_clicks_badge(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=1)
    marker = (gw.left + 1000, gw.top + 531)  # 红轴高度：点角标，不点胶片
    _patch_find(monkeypatch, lambda n, ms, t, r: marker if n.endswith('主线NEW.png') else None)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    clicks = []
    _patch_clicks(monkeypatch, clicks)
    zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False)
    assert clicks[0] == marker


def test_map_new_stuck_stops(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=20)
    marker = (gw.left + 1000, gw.top + 531)
    _patch_find(monkeypatch, lambda n, ms, t, r: marker if n.endswith('主线NEW.png') else None)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    _patch_clicks(monkeypatch, [])
    run = zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False)
    assert run is False
    assert any('NEW 连点 3 次未进关' in m for m in bot.logs)


def test_collapse_three_times_stops(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=20)
    collapse = (gw.left + 900, gw.top + 400)
    _patch_find(monkeypatch, lambda n, ms, t, r: collapse if n.endswith('系统陷落.png') else None)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    _patch_clicks(monkeypatch, [])
    run = zb.run_zhuxian_battle(bot, stop_stage='10-20', from_home=False)
    assert run is False
    assert '战斗失败 1/3' in bot.logs
    assert '战斗失败 2/3' in bot.logs
    assert '战斗失败 3/3' in bot.logs
    assert any('连续 3 次战斗失败' in m for m in bot.logs)


# ---------------- 结算默认 _find ----------------

def test_battle_ended_default_find(monkeypatch):
    bot = FakeBot(_gw())
    calls = []

    def handler(name, multi_scale, threshold, region):
        calls.append((name, multi_scale, threshold))
        if name.endswith('异常排除.png'):
            return (10, 10)
        return None

    _patch_find(monkeypatch, handler)
    assert zb._battle_ended(bot) is True
    assert ('异常排除.png', True, None) in calls  # 命中异常排除
    assert all(ms for _, ms, _ in calls)          # 全部多尺度（不再单尺度）
    assert all(t is None for _, _, t in calls)    # 全部默认阈值（不再 0.82/0.80）


# ---------------- 5.5 弹窗进关记 fighting_stage ----------------

def test_popup_branch_sets_fighting_stage(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=5)
    popup_go, badge = (gw.left + 1500, gw.top + 850), (gw.left + 1200, gw.top + 600)
    state = {'entered': False}

    def handler(name, multi_scale, threshold, region):
        if name.endswith('关卡弹窗前往挑战.png') and not state['entered']:
            return popup_go
        if name.endswith('关卡弹窗NEW.png'):
            return badge
        if state['entered'] and name.endswith('获得物品.png'):
            return (gw.left + 900, gw.top + 400)   # 打完后的结算页
        if state['entered'] and name.endswith('主线战斗.png'):
            return (gw.left + 700, gw.top + 300)   # _wait_battle_entry 立即放行
        return None

    _patch_find(monkeypatch, handler)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    monkeypatch.setattr(zb, '_ocr_current_stage', lambda b: (9, 1))  # 弹窗 OCR
    clicks = []

    def fake_click(hwnd, x, y):
        clicks.append((x, y))
        if (x, y) == popup_go:
            state['entered'] = True
    monkeypatch.setattr(zb, 'post_click', fake_click)

    run = zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False)
    assert run is True
    assert '[OK] 已打完停止关 #9-1' in bot.logs
    # 子关 NEW 仍点色块中心（5.5 不做卡面偏移）
    assert clicks[0] == badge
    assert popup_go in clicks


def test_popup_without_stage_record_does_not_stop(monkeypatch):
    """对照组：若 5.5 不记 fighting_stage，同样流程不会判停。"""
    gw = _gw()
    bot = FakeBot(gw, alive=5)
    popup_go, badge = (gw.left + 1500, gw.top + 850), (gw.left + 1200, gw.top + 600)
    state = {'entered': False}

    def handler(name, multi_scale, threshold, region):
        if name.endswith('关卡弹窗前往挑战.png') and not state['entered']:
            return popup_go
        if name.endswith('关卡弹窗NEW.png'):
            return badge
        if state['entered'] and name.endswith('获得物品.png'):
            return (gw.left + 900, gw.top + 400)
        if state['entered'] and name.endswith('主线战斗.png'):
            return (gw.left + 700, gw.top + 300)
        return None

    _patch_find(monkeypatch, handler)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    monkeypatch.setattr(zb, '_ocr_current_stage', lambda b: None)  # OCR 拿不到关号
    monkeypatch.setattr(zb, 'post_click', lambda hwnd, x, y: None)

    assert zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False) is not True


# ---------------- _already_in_story_flow 黄色兜底约束 ----------------

def test_already_in_story_flow_yellow_guards(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw)
    _patch_find(monkeypatch, lambda n, ms, t, r: None)

    # 标题栏 / 底栏聊天 / 弹窗金色：都不判真
    bad = [(gw.left + 500, gw.top + 10),                        # 标题栏
           (gw.left + 500, gw.top + int(gw.height * 0.90)),    # 底栏聊天（height-80 裁不掉）
           (gw.left + int(gw.width * 0.8), gw.top + int(gw.height * 0.3))]  # 右上培养计划金色
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: list(bad))
    assert zb._already_in_story_flow(bot) is False

    # 地图中部的黄点：判真
    good = (gw.left + int(gw.width * 0.51), gw.top + int(gw.height * 0.5))
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [good])
    assert zb._already_in_story_flow(bot) is True

    # 地图偏右、时间轴高度的剧情 NEW：不能当弹窗金色滤掉
    right = (gw.left + int(gw.width * 0.68), gw.top + int(gw.height * 0.48))
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [right])
    assert zb._already_in_story_flow(bot) is True

    # NEW 邻近锁定：不判真（锁定关不可点）
    def lock_find(name, multi_scale, threshold, region):
        if name.endswith('主线锁定.png'):
            return (good[0] + 10, good[1] + 5)
        return None
    _patch_find(monkeypatch, lock_find)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [good])
    assert zb._already_in_story_flow(bot) is False


def test_skip_uses_default_find(monkeypatch):
    bot = FakeBot(_gw(), alive=1)
    calls = []

    def handler(name, multi_scale, threshold, region):
        calls.append((name, multi_scale, threshold, region))
        return None

    _patch_find(monkeypatch, handler)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False)
    skip_calls = [c for c in calls
                  if c[0].endswith('主线跳过.png') or c[0].endswith('主线剧情自动.png')]
    assert skip_calls
    assert all(ms is True and t is None for _, ms, t, _ in skip_calls)
    assert all(r is not None for *_, r in skip_calls)


def test_ocr_reads_popup_title_from_fixture():
    from PIL import Image
    fx = os.path.join(os.path.dirname(__file__), 'fixtures')
    bot = FakeBot(_gw())
    for name in ('zhuxian_popup_9_4.jpg', 'zhuxian_popup_9_4_dark.jpg'):
        bot.capture = lambda p=os.path.join(fx, name): Image.open(p)
        assert zb._ocr_current_stage(bot) == (9, 4), name


def test_popup_past_stop_returns_true(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=3)
    popup_go = (gw.left + 1500, gw.top + 850)
    _patch_find(monkeypatch, lambda n, ms, t, r: popup_go if n.endswith('关卡弹窗前往挑战.png') else None)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    monkeypatch.setattr(zb, '_ocr_current_stage', lambda b: (9, 4))
    clicks = []
    _patch_clicks(monkeypatch, clicks)
    assert zb.run_zhuxian_battle(bot, stop_stage='9-1', from_home=False) is True
    assert any('已超过停止关' in m for m in bot.logs)
    assert popup_go not in clicks


def test_loot_stop_clears_settlement(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=20)
    go = (gw.left + 1500, gw.top + 850)
    loot, end = (gw.left + 900, gw.top + 400), (gw.left + 800, gw.top + 300)
    state = {'entered': False, 'screens': 2}

    def handler(name, multi_scale, threshold, region):
        if not state['entered'] and name.endswith('主线前往挑战.png'):
            return go
        if state['entered']:
            if name.endswith('获得物品.png') and state['screens'] >= 2:
                return loot
            if name.endswith('异常排除.png') and state['screens'] == 1:
                return end
        return None

    _patch_find(monkeypatch, handler)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    monkeypatch.setattr(zb, '_ocr_current_stage', lambda b: (9, 4))
    monkeypatch.setattr(zb, '_wait_battle_entry', lambda b: None)
    clicks = []

    def fake_click(hwnd, x, y):
        clicks.append((x, y))
        if (x, y) == go:
            state['entered'] = True
        elif state['entered'] and state['screens'] > 0:
            state['screens'] -= 1
    monkeypatch.setattr(zb, 'post_click', fake_click)

    run = zb.run_zhuxian_battle(bot, stop_stage='9-4', from_home=False)
    assert run is True
    assert '[OK] 已打完停止关 #9-4' in bot.logs
    assert len(clicks) >= 3  # 前往挑战 + 掉落空白 + 异常排除空白


def test_chapter_banner_does_not_stop(monkeypatch):
    gw = _gw()
    bot = FakeBot(gw, alive=3)
    banner = (gw.left + 900, gw.top + 200)
    popup_go, badge = (gw.left + 1500, gw.top + 850), (gw.left + 1200, gw.top + 600)
    n = {'i': 0}

    def handler(name, multi_scale, threshold, region):
        n['i'] += 1
        if n['i'] < 8 and name.endswith('章节完成.png'):
            return banner
        if name.endswith('关卡弹窗前往挑战.png'):
            return popup_go
        if name.endswith('关卡弹窗NEW.png'):
            return badge
        return None

    _patch_find(monkeypatch, handler)
    monkeypatch.setattr(zb, 'find_all_by_color', lambda b, **kw: [])
    monkeypatch.setattr(zb, '_ocr_current_stage', lambda b: (9, 4))
    clicks = []
    _patch_clicks(monkeypatch, clicks)
    run = zb.run_zhuxian_battle(bot, stop_stage='9-4', from_home=False)
    assert run is not True
    assert not any('已打完停止关' in m for m in bot.logs)
    assert any('章节完成' in m for m in bot.logs)
