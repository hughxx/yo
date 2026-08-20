@echo off
setlocal
cd /d %~dp0..
pyinstaller --noconfirm --clean --onefile --windowed --name CoreInsightMiner --icon pyqt_client\assets\icon.ico --add-data "miner\web;miner\web" --add-data "pyqt_client\assets;pyqt_client\assets" miner\main.py
echo EXE: dist\CoreInsightMiner.exe
pause
