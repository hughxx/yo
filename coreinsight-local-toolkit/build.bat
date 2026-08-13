@echo off
setlocal
cd /d "%~dp0"

tasklist /fi "imagename eq coreinsight-local-toolkit.exe" /nh 2>nul | find /i "coreinsight-local-toolkit" >nul
if not errorlevel 1 (
    echo CoreInsight Local Toolkit is running and the EXE is locked.
    choice /m "Stop it and continue building"
    if errorlevel 2 exit /b 1
    taskkill /f /im coreinsight-local-toolkit.exe >nul 2>&1
)

echo Building CoreInsight Local Toolkit...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
if errorlevel 1 (
    echo.
    echo Build failed. See the errors above.
    pause
    exit /b 1
)

echo.
echo Build completed:
echo %~dp0dist\coreinsight-local-toolkit.exe
pause
endlocal
