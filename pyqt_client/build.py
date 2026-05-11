import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

EXE_NAME = "RD-Extension"   # ASCII only — window title set separately in shell.py

print("===== 安装依赖 =====")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
    check=True,
)

print("===== 打包 =====")
subprocess.run(
    [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", EXE_NAME,
        "--icon", "assets/icon.ico",
        "--add-data", "assets;assets",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--hidden-import", "win32timezone",
        "main.py",
    ],
    check=True,
)

print("\n===== 完成 =====")
print("产物：", os.path.abspath(os.path.join("dist", f"{EXE_NAME}.exe")))
