@echo off
setlocal
cd /d "%~dp0"

echo ===== 安装依赖 =====
pip install -r requirements.txt -q

echo ===== PyInstaller 打包 =====
pyinstaller --onefile --windowed ^
    --name 智能助手 ^
    --hidden-import win32com.client ^
    --hidden-import pythoncom ^
    --hidden-import pywintypes ^
    main.py

if not exist "dist\智能助手.exe" (
    echo 错误：打包失败
    exit /b 1
)

echo.
echo ===== 完成 =====
echo 产物：%~dp0dist\智能助手.exe
pause
