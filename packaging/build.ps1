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
# The Chrome extension ships next to the exe for "Load unpacked" (Settings > General opens it).
$ext = "$root\dist\LiveTranslate\browser-extension"
Remove-Item $ext -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$root\browser-extension" $ext -Recurse
$manifest = (Get-Content "$root\browser-extension\manifest.json" -Raw) -replace '"version": "[^"]+"', "`"version`": `"$version`""
[IO.File]::WriteAllText("$ext\manifest.json", $manifest, (New-Object Text.UTF8Encoding $false))  # no BOM

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup not found; the app is in dist\LiveTranslate\ but no installer was made."
    exit 0
}
$out = "$root\dist\release"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
& $iscc "/O$out" "/DAppVersion=$version" "$root\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } | Set-Content "$out\SHA256SUMS.txt"
Write-Host "Installer: $out (LiveTranslate-Setup-$version.exe + .bin slices + SHA256SUMS.txt)"
