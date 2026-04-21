@echo off
chcp 65001 >nul
echo ====================================
echo   邮件转发助手 - 后端服务
echo ====================================
echo.

pip install -r requirements.txt -q

echo 启动服务，监听 0.0.0.0:5000 ...
echo 按 Ctrl+C 停止
echo.

python app.py
pause
