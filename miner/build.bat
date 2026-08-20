@echo off
setlocal
set "MINER_DIR=%~dp0"
cd /d "%MINER_DIR%"
pyinstaller --noconfirm --clean --distpath "%MINER_DIR%dist" --workpath "%MINER_DIR%build" miner.spec
echo EXE: miner\dist\miner.exe
pause
