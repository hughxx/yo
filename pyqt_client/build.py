"""Install dependencies and build the pywebview/WebView2 onefile executable."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

print("===== 安装依赖 =====")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
    check=True,
)

print("===== PyInstaller onefile 打包 =====")
subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "pywebview.spec"],
    check=True,
)

target = ROOT / "dist" / "CoreMiner.exe"
print("\n===== 完成 =====")
print(f"产物：{target}")
print("目标电脑需要 Microsoft Edge WebView2 Runtime（Windows 10/11 通常已预装）。")
