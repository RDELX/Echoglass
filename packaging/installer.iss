; Inno Setup script. Built by packaging\build.ps1, which passes /DAppVersion.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2C1B7A-3E44-4C1B-9D4E-6A1E2B7C9F10}
AppName=LiveTranslate
AppVersion={#AppVersion}
AppPublisher=LiveTranslate
DefaultDirName={autopf}\LiveTranslate
DefaultGroupName=LiveTranslate
DisableProgramGroupPage=yes
; Per-user install by default: no admin prompt, installs to %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=LiveTranslate-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\LiveTranslate.exe
Compression=lzma2/fast
SolidCompression=no
; GitHub release assets are capped at 2 GiB, so split the installer into the .exe plus
; .bin slices; users download all of them into one folder and run the .exe.
DiskSpanning=yes
DiskSliceSize=1900000000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\LiveTranslate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"
Name: "{group}\Uninstall LiveTranslate"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LiveTranslate.exe"; Description: "Launch LiveTranslate"; Flags: nowait postinstall skipifsilent
; In-app updates run the installer with /SILENT: relaunch the app when it finishes.
Filename: "{app}\LiveTranslate.exe"; Flags: nowait skipifnotsilent

; Settings (%APPDATA%\LiveTranslate) and downloaded models (%USERPROFILE%\.cache\huggingface)
; are kept on uninstall so a reinstall doesn't re-download 3 GB.
