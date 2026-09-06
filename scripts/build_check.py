"""
PC 构建检查（P0A）— 打包前的三组守卫，可独立运行也可由 build.py 第 0 步调用。

    python scripts/build_check.py

1. 版本可追溯：版本号单一来源（core/__init__.py）且格式合法；README 标题同步；
   生成 build_info.json（版本 / 提交号 / 构建时间）供打包进产物。
2. 无模拟器依赖：黑名单词扫描。模拟器路线已封存（总计划第六章），
   PC 主线禁止重新引入 ADB / 模拟器依赖。
3. 资源完整：打包声明、前端产物、模板图可解码、OCR 模型、图标；
   并抽查代码里引用的模板文件名在 templates/ 下真实存在。
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 自身包含黑名单词，扫描时排除
_SELF = os.path.abspath(__file__)

failures = []


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    failures.append(msg)
    print(f"  [FAIL] {msg}")


# ============================================================
# 1. 版本可追溯
# ============================================================
def check_version():
    print("\n[1/3] 版本可追溯")
    from core import __version__

    if re.fullmatch(r"\d+\.\d+\.\d+", __version__):
        ok(f"版本号格式合法: {__version__}（单一来源 core/__init__.py）")
    else:
        fail(f"版本号格式异常: {__version__!r}（应为 x.y.z）")

    readme = os.path.join(ROOT, "README.md")
    try:
        with open(readme, "r", encoding="utf-8") as f:
            first_line = f.readline()
        if f"V{__version__}" in first_line:
            ok("README 标题版本与 core 一致")
        else:
            fail(f"README 标题未含 V{__version__}（版本漂移）: {first_line.strip()!r}")
    except OSError as e:
        fail(f"README 读取失败: {e}")

    commit = "(unknown)"
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True, timeout=10)
        commit = out.stdout.strip()
        ok(f"构建提交号: {commit[:12]}")
    except Exception:
        print("  [WARN] git 不可用，build_info.json 将不含提交号")

    info = {
        "version": __version__,
        "commit": commit,
        "build_time": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
    }
    info_path = os.path.join(ROOT, "build_info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
        f.write("\n")
    ok(f"build_info.json 已生成（随包分发，产物可追溯）")


# ============================================================
# 2. 无模拟器依赖
# ============================================================
# ASCII 词用词边界防误伤；中文词直接子串匹配
_BLACKLIST = [
    (re.compile(r"\b(adb|mumu|emulator|scrcpy|uiautomator|minicap|droidcast"
                r"|ldconsole|bluestacks|memu)\b", re.IGNORECASE), None),
    (None, "模拟器"),
]


def _scan_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for rx, literal in _BLACKLIST:
                    if (rx and rx.search(line)) or (literal and literal in line):
                        return lineno, line.strip()
    except OSError:
        pass
    return None


def check_no_emulator():
    print("\n[2/3] 无模拟器依赖（模拟器路线已封存）")
    targets = [os.path.join(ROOT, "requirements.txt"),
               os.path.join(ROOT, "YiseAssistant.spec")]
    targets += glob.glob(os.path.join(ROOT, "core", "**", "*.py"), recursive=True)
    targets += glob.glob(os.path.join(ROOT, "ui", "**", "*.py"), recursive=True)
    targets += glob.glob(os.path.join(ROOT, "scripts", "*.py"))
    targets = [t for t in targets
               if os.path.abspath(t) != _SELF and os.path.isfile(t)]

    hits = []
    for path in targets:
        hit = _scan_file(path)
        if hit:
            lineno, text = hit
            hits.append(f"{os.path.relpath(path, ROOT)}:{lineno}: {text[:80]}")

    if hits:
        for h in hits:
            fail(f"疑似模拟器/ADB 依赖: {h}")
    else:
        ok(f"黑名单词扫描通过（{len(targets)} 个文件）")


# ============================================================
# 3. 资源完整
# ============================================================
_REQUIRED_FILES = ["ui/static/index.html", "app.ico"]
_REQUIRED_DIRS = ["ui/static/assets", "templates", "easyocr_models"]
_TEMPLATE_SUBDIRS = ["huodong", "richang", "rta", "shilian", "zhuxian"]
# 日志文案会被上面的字面量扫描误认成模板名；真实模板文件名不含这些字符
_NON_RESOURCE_CHARS = re.compile(r"[\s\[\]（）()：:，,。]")


def _template_index():
    index = {}
    for dirpath, _, filenames in os.walk(os.path.join(ROOT, "templates")):
        for name in filenames:
            if name.lower().endswith(".png"):
                index.setdefault(name, os.path.join(dirpath, name))
    return index


def check_resources():
    print("\n[3/3] 资源完整")
    for rel in _REQUIRED_FILES:
        path = os.path.join(ROOT, rel)
        (ok if os.path.isfile(path) else fail)(f"打包资源: {rel}")
    for rel in _REQUIRED_DIRS:
        path = os.path.join(ROOT, rel)
        if os.path.isdir(path) and os.listdir(path):
            ok(f"打包资源目录: {rel}/（{len(os.listdir(path))} 项）")
        else:
            fail(f"打包资源目录缺失或为空: {rel}/")

    # 模板子目录与图片可解码
    from PIL import Image
    index = _template_index()
    for sub in _TEMPLATE_SUBDIRS:
        d = os.path.join(ROOT, "templates", sub)
        pngs = [f for f in glob.glob(os.path.join(d, "*.png"))]
        if not pngs:
            fail(f"templates/{sub}/ 无模板图")
            continue
        ok(f"templates/{sub}/: {len(pngs)} 张")
    bad = []
    for name, path in index.items():
        try:
            with Image.open(path) as im:
                im.load()
        except Exception as e:
            bad.append(f"{name}: {e}")
    if bad:
        for b in bad[:10]:
            fail(f"模板图无法解码: {b}")
    else:
        ok(f"全部 {len(index)} 张模板图可正常解码")

    models = glob.glob(os.path.join(ROOT, "easyocr_models", "*.pth"))
    if models:
        ok(f"OCR 模型: {len(models)} 个 .pth")
    else:
        fail("easyocr_models/ 缺少 .pth 模型文件")

    # 模板引用抽查：任务代码里的字面量模板名必须真实存在。
    # core/_base 是基础设施层（scene_pack 的输出文件名、capture 的保存名），
    # 其 png 字面量是输出路径而非模板查找，不参与此检查。
    missing = set()
    for path in glob.glob(os.path.join(ROOT, "core", "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        if rel.startswith("core" + os.sep + "_base" + os.sep):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for m in re.finditer(r"""['"]([^'"]+\.png)['"]""", line):
                    name = m.group(1)
                    if "{" in name or _NON_RESOURCE_CHARS.search(name):
                        continue  # 动态拼接 / 日志文案
                    if name not in index:
                        missing.add(f"{os.path.relpath(path, ROOT)}:{lineno}: {name}")
    if missing:
        for m in sorted(missing):
            fail(f"代码引用的模板不存在: {m}")
    else:
        ok("代码引用的模板名全部存在（字面量抽查）")


def main():
    print("=" * 50)
    print("  PC 构建检查（P0A）")
    print("=" * 50)
    check_version()
    check_no_emulator()
    check_resources()

    print("\n" + "=" * 50)
    if failures:
        print(f"  [FAIL] {len(failures)} 项未通过，禁止打包")
        print("=" * 50)
        sys.exit(1)
    print("  [OK] PC 构建检查全部通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
