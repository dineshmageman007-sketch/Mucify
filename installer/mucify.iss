; Inno Setup 6 script for the Mucify installer.
; Build:  ISCC.exe /DMyAppVersion=1.0.0 installer\mucify.iss   (build.ps1 / GitHub Actions do this for you)
; Expects the PyInstaller output in ..\dist\Mucify\

#define MyAppName "Mucify"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppExe "Mucify.exe"
#define WebView2Setup "redist\MicrosoftEdgeWebview2Setup.exe"

[Setup]
AppId={{6F1B7C52-3A0E-4D9B-8E47-2C5A91D0B3F8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=mageman007
AppPublisherURL=https://github.com/dineshmageman007-sketch/Mucify
AppSupportURL=https://github.com/dineshmageman007-sketch/Mucify/issues
AppCopyright=Copyright (C) 2026 mageman007 and contributors
InfoBeforeFile=NOTICE.txt
VersionInfoCompany=mageman007
VersionInfoCopyright=Copyright (C) 2026 mageman007 and contributors
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Mucify-Setup-{#MyAppVersion}
SetupIconFile=..\assets\mucify.ico
WizardImageFile=..\assets\wizard-large-164.bmp,..\assets\wizard-large-192.bmp,..\assets\wizard-large-246.bmp,..\assets\wizard-large-328.bmp
WizardSmallImageFile=..\assets\wizard-small-55.bmp,..\assets\wizard-small-64.bmp,..\assets\wizard-small-83.bmp,..\assets\wizard-small-110.bmp
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installs just for the current user by default (no admin prompt); the user can choose "all users" in the first dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Mucify creates this mutex while running, so Setup asks the user to close it before updating.
AppMutex=Mucify.SingleInstance
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Mucify\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#if FileExists(SourcePath + "\" + WebView2Setup)
Source: "{#WebView2Setup}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2
#endif

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
#if FileExists(SourcePath + "\" + WebView2Setup)
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime (needed to show Mucify's window)..."; Flags: waituntilterminated; Check: NeedsWebView2
#endif
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Present(): Boolean;
var
  v: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2Guid, 'pv', v) then
    Result := (v <> '') and (v <> '0.0.0.0');
  if (not Result) and RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2Guid, 'pv', v) then
    Result := (v <> '') and (v <> '0.0.0.0');
end;

function NeedsWebView2(): Boolean;
begin
  Result := not WebView2Present();
end;

{ On uninstall, offer to remove settings + working files (default: Yes, so a reinstall starts fresh).
  The music library is never touched. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    dataDir := ExpandConstant('{userappdata}\Mucify');
    if DirExists(dataDir) then
      if MsgBox('Also delete your Mucify settings and working files?' + #13#10 + #13#10 +
                dataDir + #13#10 + #13#10 +
                'Your music library is not affected.', mbConfirmation, MB_YESNO) = IDYES then
        DelTree(dataDir, True, True, True);
  end;
end;
