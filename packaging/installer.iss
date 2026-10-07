; Inno Setup script. Built by packaging\build.ps1, which passes /DAppVersion and generates
; runtime.generated.iss (the GPU runtime download entries).
;
; Web installer: the setup .exe holds only the app. PyTorch + torchaudio (with their CUDA
; libraries, ~2.8 GB) are downloaded from the official PyTorch wheel index during setup, and
; the Whisper model (~3 GB) from Hugging Face if the user keeps that task ticked. Both are
; verified by SHA-256 and skipped when already present.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2C1B7A-3E44-4C1B-9D4E-6A1E2B7C9F10}
AppName=Echoglass
AppVersion={#AppVersion}
AppPublisher=Echoglass
DefaultDirName={autopf}\Echoglass
DefaultGroupName=Echoglass
DisableProgramGroupPage=yes
; Start menu folder was "LiveTranslate" before v0.9.0; always use the new name.
UsePreviousGroup=no
; Per-user install by default: no admin prompt, installs to %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Echoglass-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Echoglass.exe
Compression=lzma2/max
SolidCompression=yes
; Use all cores for LZMA2 (otherwise compression is effectively single-threaded).
LZMANumBlockThreads=16
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ArchiveExtraction=full

[Tasks]
Name: "downloadmodel"; Description: "Download the speech recognition model now (about 3 GB). Otherwise Echoglass downloads it the first time you press Start."; Check: NeedModel
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Echoglass\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#include "deps.generated.iss"
; Whisper large-v3, pinned to a Hugging Face revision. Kept on uninstall (it's big and
; reinstalls reuse it). livetranslate/asr/model_download.py looks here first.
#define ModelUrl "https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478"
#define ModelDir "{localappdata}\Echoglass\models\faster-whisper-large-v3"
Source: "{#ModelUrl}/model.bin"; DestName: "model.bin"; DestDir: "{#ModelDir}"; Hash: "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1"; ExternalSize: 3087284237; Flags: external download ignoreversion uninsneveruninstall; Tasks: downloadmodel
Source: "{#ModelUrl}/config.json"; DestName: "config.json"; DestDir: "{#ModelDir}"; ExternalSize: 2394; Flags: external download ignoreversion uninsneveruninstall; Tasks: downloadmodel
Source: "{#ModelUrl}/preprocessor_config.json"; DestName: "preprocessor_config.json"; DestDir: "{#ModelDir}"; ExternalSize: 340; Flags: external download ignoreversion uninsneveruninstall; Tasks: downloadmodel
Source: "{#ModelUrl}/tokenizer.json"; DestName: "tokenizer.json"; DestDir: "{#ModelDir}"; ExternalSize: 2480617; Flags: external download ignoreversion uninsneveruninstall; Tasks: downloadmodel
Source: "{#ModelUrl}/vocabulary.json"; DestName: "vocabulary.json"; DestDir: "{#ModelDir}"; ExternalSize: 1068114; Flags: external download ignoreversion uninsneveruninstall; Tasks: downloadmodel

[InstallDelete]
; Leftovers from when the app was called LiveTranslate (before v0.9.0). Upgrades keep the
; old install folder, but the exe and shortcuts get the new name.
Type: files; Name: "{app}\LiveTranslate.exe"
Type: filesandordirs; Name: "{autoprograms}\LiveTranslate"
Type: files; Name: "{autodesktop}\LiveTranslate.lnk"

[Icons]
Name: "{group}\Echoglass"; Filename: "{app}\Echoglass.exe"
Name: "{group}\Uninstall Echoglass"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Echoglass"; Filename: "{app}\Echoglass.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Echoglass.exe"; Description: "Launch Echoglass"; Flags: nowait postinstall skipifsilent
; In-app updates run the installer with /SILENT: relaunch the app when it finishes.
Filename: "{app}\Echoglass.exe"; Flags: nowait skipifnotsilent

[UninstallDelete]
; In-app partial updates add files the uninstaller's own list doesn't know about.
Type: filesandordirs; Name: "{app}"

; Settings (%APPDATA%\Echoglass) and models (%LOCALAPPDATA%\Echoglass\models,
; %USERPROFILE%\.cache\huggingface) are kept on uninstall.

[Code]
// A PyTorch wheel is already installed if that exact version's dist-info is there.
function NeedWheel(Marker: String): Boolean;
begin
  Result := not FileExists(ExpandConstant('{app}\_internal\') + Marker);
end;

function NeedModel: Boolean;
begin
  // The app moves %LOCALAPPDATA%\LiveTranslate\models here on first start, so count it too.
  Result := not FileExists(ExpandConstant('{#ModelDir}\model.bin')) and
            not FileExists(ExpandConstant('{localappdata}\LiveTranslate\models\faster-whisper-large-v3\model.bin')) and
            not DirExists(ExpandConstant('{%USERPROFILE}\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3\snapshots'));
end;
