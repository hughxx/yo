@echo off
REM 一键打包：先打 outlook_cli.exe，再打 Tauri 安装包。
setlocal

echo === [1/4] 构建 outlook_cli.exe ===
python sidecar\outlook_cli\build.py
if errorlevel 1 (
  echo outlook_cli.exe 构建失败
  exit /b 1
)

echo === [2/4] 构建 html2md.exe ===
python sidecar\html2md\build.py
if errorlevel 1 (
  echo html2md.exe 构建失败
  exit /b 1
)

echo === [3/4] 安装前端依赖 ===
call pnpm install
if errorlevel 1 exit /b 1

echo === [4/4] 构建 Tauri 安装包 ===
call pnpm tauri build
if errorlevel 1 exit /b 1

echo.
echo 完成。安装包位于 src-tauri\target\release\bundle\
endlocal
