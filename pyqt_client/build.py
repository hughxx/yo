import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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
        "--name", "智能助手",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--hidden-import", "win32timezone",
        "main.py",
    ],
    check=True,
)

print("\n===== 完成 =====")
print("产物：", os.path.abspath(os.path.join("dist", "智能助手.exe")))
