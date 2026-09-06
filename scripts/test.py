"""
统一测试入口 — 任何解释器下都会固定用项目 .venv 的 Python 跑 pytest。

背景（评审意见）：系统 Python 没装 pytest/依赖，直接 `python -m pytest` 会报
"No module named pytest" 造成误报。本入口检测到当前不是项目解释器时，
自动切换到 .venv 的 Python 执行。

用法：
    python scripts/test.py            # 等价 .venv\Scripts\python.exe -m pytest -q
    python scripts/test.py -v         # 参数原样透传 pytest
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")


def main():
    args = sys.argv[1:] or ["-q"]
    cmd = [sys.executable, "-m", "pytest"] + args
    if os.path.abspath(sys.executable) != os.path.abspath(VENV_PY) \
            and os.path.isfile(VENV_PY):
        cmd[0] = VENV_PY
    print("[test]", " ".join(cmd))
    sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
