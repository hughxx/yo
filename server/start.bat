@echo off
setlocal
cd /d "%~dp0.."

echo ===== 安装后端依赖 =====
pip install -r server/requirements.txt -q

echo ===== 启动后端 (端口 8023) =====
python -m server
pause
