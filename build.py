"""瑞玛丽小助手 — 一键打包脚本 (Python 版, 无编码问题)"""
import subprocess
import sys
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))

# 版本单一来源：core/__init__.py（zip 名随版本号自动更新）
from core import __version__


def run(cmd, cwd=None, desc=""):
    print(f"\n{'='*50}")
    print(f"  {desc}")
    print(f"{'='*50}\n")
    result = subprocess.run(cmd, shell=True, cwd=cwd or ROOT)
    if result.returncode != 0:
        print(f"\n[FAIL] {desc}")
        sys.exit(1)
    print(f"\n[OK] {desc}")


# Step 0: 构建前检查（P0A）：边界冻结 + PC 构建检查，任一失败即中止
run(f'"{sys.executable}" scripts/check_freeze.py',
    desc="[1/5] 边界冻结检查")
run(f'"{sys.executable}" scripts/build_check.py',
    desc="[2/5] PC 构建检查（版本可追溯 / 无模拟器依赖 / 资源完整）")

# Step 1: build frontend
run("npm run build", cwd=os.path.join(ROOT, "frontend"), desc="[3/5] 构建前端")

# Step 2: PyInstaller（跟随当前解释器，不依赖终端是否激活了虚拟环境）
run(f'"{sys.executable}" -m PyInstaller YiseAssistant.spec --noconfirm',
    desc="[4/5] PyInstaller 打包 exe")

# Step 3: zip dist
dist_dir = os.path.join(ROOT, "dist", "瑞玛丽小助手")
zip_path = os.path.join(ROOT, "dist", f"瑞玛丽小助手_V{__version__}.zip")
if os.path.exists(zip_path):
    os.remove(zip_path)
print(f"\n{'='*50}")
print(f"  [5/5] 压缩 dist 文件夹")
print(f"{'='*50}\n")
shutil.make_archive(zip_path.replace(".zip", ""), "zip",
                    os.path.join(ROOT, "dist"), "瑞玛丽小助手")
if os.path.exists(zip_path):
    print(f"\n[OK] 压缩完成: {zip_path}")

# Done
print(f"\n{'='*50}")
print(f"  打包全部完成!")
print(f"  exe: {os.path.join(dist_dir, '瑞玛丽小助手.exe')}")
print(f"  zip: {zip_path}")
print(f"{'='*50}\n")
os.system("pause")
