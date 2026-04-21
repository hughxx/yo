; InnoSetup 安装脚本 - 邮件转发助手 Outlook插件
; 下载 InnoSetup: https://jrsoftware.org/isinfo.php

#define MyAppName "邮件转发助手"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "EmailForwarder"
#define MyAppGUID "{{A3F2B7C1-8D4E-4F5A-9B6C-1E2D3F4A5B6C}"
#define MyDllName "OutlookEmailForwarder.dll"

[Setup]
AppId={#MyAppGUID}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=EmailForwarderSetup_v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; 需要管理员权限来注册COM
PrivilegesRequired=admin
OutputDir=Output

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Add-in DLL 及依赖
Source: "..\OutlookEmailForwarder\bin\Release\OutlookEmailForwarder.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\OutlookEmailForwarder\bin\Release\*.dll"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "..\OutlookEmailForwarder\bin\Release\*.config"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; 安装后注册COM组件
Filename: "{dotnet4064}\RegAsm.exe"; Parameters: """{app}\{#MyDllName}"" /codebase"; Flags: runhidden waituntilterminated; StatusMsg: "正在注册Outlook插件..."

[UninstallRun]
; 卸载前取消注册COM
Filename: "{dotnet4064}\RegAsm.exe"; Parameters: """{app}\{#MyDllName}"" /unregister"; Flags: runhidden waituntilterminated; StatusMsg: "正在卸载Outlook插件..."

[Code]
// 检查Outlook是否正在运行
function IsOutlookRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('tasklist', '/FI "IMAGENAME eq OUTLOOK.EXE" /NH', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // 提示关闭Outlook
    if MsgBox('安装前请确保已关闭 Microsoft Outlook。' + #13#10 + '是否继续安装？',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Abort;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    MsgBox('卸载前请确保已关闭 Microsoft Outlook。', mbInformation, MB_OK);
  end;
end;
