"""
失败现场包测试（P0A）

验证：七要素文件齐全、info.json 字段完整、无帧降级、同错误去重、保留策略。
不依赖游戏窗口，Bot 用桩对象。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import core._base.scene_pack as scene_pack


class _FakeWindow:
    title = "测试窗口"
    hwnd = 1234
    left = 10
    top = 20
    width = 960
    height = 540


class _FakeBot:
    def __init__(self, frame=None):
        self.last_frame = frame
        self.last_action = {"desc": "点击图标 测试按钮.png", "x": 100, "y": 80}
        self.game_window = _FakeWindow()

    def capture(self):
        return self.last_frame


def _fresh(tmp_path):
    scene_pack._LAST_PACK = None
    scene_pack._BOTS.clear()
    return tmp_path


def test_seven_elements_present(tmp_path, monkeypatch):
    """七要素：info / 原始帧 / 标注帧 / 日志尾 全部落盘，字段完整"""
    root = _fresh(tmp_path)
    monkeypatch.setattr(scene_pack, "_pack_root", lambda: str(root))
    scene_pack.record_log("12:00:00.000 [Bot] 测试日志行")

    frame = Image.new("RGB", (960, 540), (30, 30, 30))
    pack = scene_pack.write_scene_pack(
        task="zhike_test", node="测试节点",
        error=ValueError("测试错误"), bot=_FakeBot(frame))

    assert pack and os.path.isdir(pack)
    files = set(os.listdir(pack))
    assert {"info.json", "frame.png", "frame_annotated.png",
            "log_tail.txt"} <= files, f"缺文件: {files}"

    with open(os.path.join(pack, "info.json"), encoding="utf-8") as f:
        info = json.load(f)
    assert info["task"]["id"] == "zhike_test"
    assert info["node"] == "测试节点"
    assert info["time"]  # 时间要素
    assert info["error"]["type"] == "ValueError"
    assert "测试错误" in info["error"]["message"]

    env = info["environment"]
    assert env["app_version"]  # 环境：版本
    assert env["window"]["hwnd"] == 1234  # 环境：窗口
    assert env["window"]["width"] == 960
    assert "config" in env  # 环境：配置快照

    with open(os.path.join(pack, "log_tail.txt"), encoding="utf-8") as f:
        assert "测试日志行" in f.read()


def test_missing_frame_degrades(tmp_path, monkeypatch):
    """无帧降级：不落图但不炸，info 照常"""
    root = _fresh(tmp_path)
    monkeypatch.setattr(scene_pack, "_pack_root", lambda: str(root))

    class NoFrameBot(_FakeBot):
        def __init__(self):
            super().__init__(frame=None)
            self.last_action = None

        def capture(self):
            return None

    pack = scene_pack.write_scene_pack(
        task="noframe", node="无帧节点", error=RuntimeError("没有画面"),
        bot=NoFrameBot())
    assert pack and os.path.isdir(pack)
    assert "info.json" in os.listdir(pack)
    assert "frame.png" not in os.listdir(pack)


def test_same_error_dedup(tmp_path, monkeypatch):
    """2 秒内同错误只落一份（注册表出口 + 兜底钩子双层触发不重复）"""
    root = _fresh(tmp_path)
    monkeypatch.setattr(scene_pack, "_pack_root", lambda: str(root))

    first = scene_pack.write_scene_pack(
        task="dup", node="n", error=ValueError("同一错误"), bot=None)
    second = scene_pack.write_scene_pack(
        task="dup", node="n", error=ValueError("同一错误"), bot=None)
    assert first
    assert second is None


def test_prune_keeps_recent(tmp_path):
    """保留策略：只留最近 KEEP_PACKS 份，删最旧"""
    root = _fresh(tmp_path)
    for i in range(scene_pack.KEEP_PACKS + 3):
        os.makedirs(os.path.join(str(root), f"20260906-0000{i:02d}-000-old"))
    scene_pack._prune(str(root))
    left = os.listdir(str(root))
    assert len(left) == scene_pack.KEEP_PACKS
    assert "20260906-000000-000-old" not in left  # 最旧被删
    assert "20260906-000022-000-old" in left  # 最新保留


def test_register_bot_current(tmp_path):
    """最后注册的 Bot 是当前 Bot（现场包取帧/窗口来源）"""
    _fresh(tmp_path)
    b1, b2 = _FakeBot(), _FakeBot()
    scene_pack.register_bot(b1)
    scene_pack.register_bot(b2)
    assert scene_pack.current_bot() is b2
