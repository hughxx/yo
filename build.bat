@echo off
chcp 65001 >nul
echo ============================================
echo   邮件转发助手 - 构建脚本
echo ============================================
echo.

:: 查找 MSBuild
set MSBUILD=
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe`) do (
    set MSBUILD=%%i
)

if "%MSBUILD%"=="" (
    echo [错误] 未找到 MSBuild，请安装 Visual Studio 或 Build Tools
    pause
    exit /b 1
)

echo [1/2] 编译 Outlook 插件 (Release x64)...
"%MSBUILD%" OutlookEmailForwarder\OutlookEmailForwarder.csproj /p:Configuration=Release /p:Platform=x64 /t:Build /v:minimal
if errorlevel 1 (
    echo [错误] 插件编译失败
    pause
    exit /b 1
)
echo [OK] 插件编译成功
echo.

echo [2/2] 打包安装程序...
where iscc >nul 2>&1
if errorlevel 1 (
    echo [跳过] 未安装 InnoSetup，请手动运行 Installer\setup.iss
    echo        下载地址: https://jrsoftware.org/isinfo.php
) else (
    iscc Installer\setup.iss
    if errorlevel 1 (
        echo [错误] 打包失败
        pause
        exit /b 1
    )
    echo [OK] 安装包已生成: Installer\Output\EmailForwarderSetup_v1.0.0.exe
)

echo.
echo ============================================
echo   构建完成！
echo ============================================
echo.
echo 后端启动: cd backend ^&^& python app.py
echo 安装包:   Installer\Output\
echo.
pause
