"""
P0A 边界冻结检查 — 旧仓库进入冻结期，只修致命问题不加功能。

《Etheria升级总计划》第四章红线 5 的机械化：
  - core/ 文件数与总行数：只许变小不许变大（功能迁出时同一次提交内删除旧实现）；
  - ui/ 与 frontend/src/：不得新增文件（防止手写任务入口继续繁殖，审计点名的 25 个入口问题）。

用法：
    python scripts/check_freeze.py            # 校验，违规退出码 1
    python scripts/check_freeze.py --update   # 基线缩减后锁定新数字（只许用于变小之后）
"""
import json
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "freeze_baseline.json")

CORE_DIR = os.path.join(ROOT, "core")
# 这些目录只许减不许增文件；static 是前端构建产物，不计入
NO_NEW_FILES = {
    "ui": (os.path.join(ROOT, "ui"), {".py"}),
    "frontend/src": (os.path.join(ROOT, "frontend", "src"),
                     {".py", ".vue", ".ts", ".js", ".css"}),
}

_SKIP_DIRS = {"__pycache__", "node_modules"}


def _walk(root, exts):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1] in exts:
                files.append(os.path.join(dirpath, name))
    return files


def _count_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def measure():
    core_files = _walk(CORE_DIR, {".py"})
    cur = {
        "core_files": len(core_files),
        "core_lines": sum(_count_lines(p) for p in core_files),
    }
    for key, (root, exts) in NO_NEW_FILES.items():
        cur[key.replace("/", "_") + "_files"] = len(_walk(root, exts))
    return cur


def _git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:
        return "(git 不可用)"


def update_baseline():
    cur = measure()
    cur["_说明"] = ("P0A 冻结基线。规则见 scripts/check_freeze.py："
                    "core/ 文件数与总行数只许变小；ui 与 frontend/src 文件数不许变大。"
                    "仅在合规缩减后用 --update 重新锁定。")
    cur["_生成"] = f"{date.today().isoformat()} @ {_git_commit()}"
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[OK] 基线已锁定: {BASELINE}")
    for k, v in cur.items():
        if not k.startswith("_"):
            print(f"     {k}: {v}")


def check():
    with open(BASELINE, "r", encoding="utf-8") as f:
        base = json.load(f)
    cur = measure()

    violations = []
    if cur["core_files"] > base["core_files"]:
        violations.append(
            f"core/ 文件数 {cur['core_files']} > 基线 {base['core_files']}（禁止新增文件）")
    if cur["core_lines"] > base["core_lines"]:
        violations.append(
            f"core/ 总行数 {cur['core_lines']} > 基线 {base['core_lines']}"
            f"（红线 5：只许变小不许变大，致命修复须缩减抵消）")
    if cur["ui_files"] > base["ui_files"]:
        violations.append(
            f"ui/ Python 文件数 {cur['ui_files']} > 基线 {base['ui_files']}"
            f"（禁止新增任务入口）")
    if cur["frontend_src_files"] > base["frontend_src_files"]:
        violations.append(
            f"frontend/src 文件数 {cur['frontend_src_files']} > 基线 {base['frontend_src_files']}")

    if violations:
        print("[FAIL] 边界冻结检查未通过：")
        for v in violations:
            print(f"  - {v}")
        print("\n本仓库已冻结（P0A）：新功能请开发于 EtheriaMaa 仓库；")
        print("致命修复可以改现有文件，但按红线 core/ 只许变小不许变大。")
        return 1

    shrunk = [k for k in ("core_files", "core_lines", "ui_files", "frontend_src_files")
              if cur[k] < base[k]]
    print(f"[OK] 边界冻结检查通过（core {cur['core_files']} 文件 / "
          f"{cur['core_lines']} 行，ui {cur['ui_files']}，frontend {cur['frontend_src_files']}）")
    if shrunk:
        print("     基线已缩减，可运行 --update 锁定新数字：" + ", ".join(shrunk))
    return 0


def main():
    if "--update" in sys.argv:
        update_baseline()
        return
    sys.exit(check())


if __name__ == "__main__":
    main()
