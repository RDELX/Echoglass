# Rebuild the installer:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# 1. PyInstaller bundles the app into dist\LiveTranslate\
# 2. Inno Setup (if installed) wraps it into dist\LiveTranslate-Setup-<version>.exe
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$version = (Get-Content "$root\livetranslate\__init__.py" | Select-String '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building LiveTranslate $version"

& "$root\.venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "$root\dist" --workpath "$root\build" "$root\packaging\LiveTranslate.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup not found; the app is in dist\LiveTranslate\ but no installer was made."
    exit 0
}
& $iscc "/DAppVersion=$version" "$root\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Installer: $root\dist\LiveTranslate-Setup-$version.exe"
