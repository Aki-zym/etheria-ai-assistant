"""
P0A 边界冻结检查 — 旧仓库进入冻结期，只修致命问题不加功能。

《Etheria升级总计划》第四章红线 5 的机械化。P1 开工前评审加固为**文件级基线**：
  1. core/ 文件数与总行数：只许变小不许变大；
  2. 文件级基线：core/ 下任何已有文件的行数不得超过其基线行数，
     且不得出现基线中不存在的新文件——防止"在一个旧文件堆代码、
     删另一个旧文件抵消总量"绕过门禁；
  3. ui/ 与 frontend/src/：不得新增文件（防手写任务入口继续繁殖）。

用法：
    python scripts/check_freeze.py                        # 校验，违规退出码 1
    python scripts/check_freeze.py --update --reason "..."  # 重锁基线（见下）

--update 限制（禁止随意放宽基线）：
    - 旧格式（无文件级基线）→ 允许一次性迁移，必须 --reason 留痕；
    - 新格式 → 仅当 core/ 文件数与总行数**同时严格减少**、其余指标不增时允许，
      且 --reason 必填，写入基线文件（说明迁移了哪个功能）。
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
    return sorted(files)


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
        "core_per_file": {
            os.path.relpath(p, ROOT).replace(os.sep, "/"): _count_lines(p)
            for p in core_files
        },
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


def _load_baseline():
    with open(BASELINE, "r", encoding="utf-8") as f:
        return json.load(f)


def update_baseline(argv):
    """重锁基线：仅限一次性迁移或指标严格下降，reason 必填留痕。"""
    args = [a for a in argv[1:] if a != "--update"]
    reason = None
    if args and args[0] == "--reason":
        reason = " ".join(args[1:]).strip() or None
    if not reason:
        print("[FAIL] --update 必须附带 --reason，说明本次基线变动原因"
              "（如：迁移了哪个功能、删除了哪些旧实现）。")
        sys.exit(1)

    old = _load_baseline()
    cur = measure()
    legacy = "core_per_file" not in old  # 旧格式：一次性迁移

    if not legacy:
        blockers = []
        if cur["core_files"] >= old["core_files"]:
            blockers.append(
                f"core/ 文件数未严格减少（{cur['core_files']} >= {old['core_files']}）")
        if cur["core_lines"] >= old["core_lines"]:
            blockers.append(
                f"core/ 总行数未严格减少（{cur['core_lines']} >= {old['core_lines']}）")
        if cur["ui_files"] > old["ui_files"]:
            blockers.append("ui/ 文件数增加")
        if cur["frontend_src_files"] > old["frontend_src_files"]:
            blockers.append("frontend/src 文件数增加")
        for path, lines in cur["core_per_file"].items():
            base = old["core_per_file"].get(path)
            if base is None:
                blockers.append(f"基线外新文件: {path}")
            elif lines > base:
                blockers.append(f"文件行数增长: {path} {lines} > {base}")
        if blockers:
            print("[FAIL] 拒绝重锁基线（只许在旧实现迁出后收紧，不许放宽）：")
            for b in blockers:
                print(f"  - {b}")
            sys.exit(1)

    new = dict(cur)
    new["_说明"] = ("P0A 冻结基线（文件级）。规则见 scripts/check_freeze.py："
                    "core/ 文件数与总行数只许严格变小、任何已有文件行数不许增长、"
                    "不得出现基线外新文件；ui 与 frontend/src 文件数不许变大。")
    new["_生成"] = f"{date.today().isoformat()} @ {_git_commit()}"
    new["_原因"] = ("一次性迁移：旧格式基线补充文件级明细，指标不变"
                    if legacy else reason)
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[OK] 基线已重锁（{'旧格式迁移' if legacy else '严格收紧'}）: {BASELINE}")
    print(f"     原因: {new['_原因']}")
    print(f"     core: {cur['core_files']} 文件 / {cur['core_lines']} 行")


def check():
    base = _load_baseline()
    cur = measure()

    violations = []
    if cur["core_files"] > base["core_files"]:
        violations.append(
            f"core/ 文件数 {cur['core_files']} > 基线 {base['core_files']}（禁止新增文件）")
    if cur["core_lines"] > base["core_lines"]:
        violations.append(
            f"core/ 总行数 {cur['core_lines']} > 基线 {base['core_lines']}"
            f"（红线 5：只许变小不许变大，致命修复须缩减抵消）")

    base_per_file = base.get("core_per_file")
    if base_per_file is None:
        print("[WARN] 基线为旧格式（无文件级明细），文件级检查未启用；"
              "请执行 --update --reason 完成一次性迁移。")
    else:
        for path, lines in cur["core_per_file"].items():
            base_lines = base_per_file.get(path)
            if base_lines is None:
                violations.append(f"core/ 基线外新文件: {path}（文件级冻结禁止新增）")
            elif lines > base_lines:
                violations.append(
                    f"core/ 文件行数增长: {path} {lines} > 基线 {base_lines}")

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

    print(f"[OK] 边界冻结检查通过（core {cur['core_files']} 文件 / "
          f"{cur['core_lines']} 行，ui {cur['ui_files']}，frontend {cur['frontend_src_files']}，"
          f"文件级基线{'已启用' if base_per_file is not None else '未启用'}）")
    return 0


def main():
    if "--update" in sys.argv:
        update_baseline(sys.argv)
        return
    sys.exit(check())


if __name__ == "__main__":
    main()
