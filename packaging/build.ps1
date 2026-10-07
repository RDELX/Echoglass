# Rebuild the installer:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Publish]
# 1. PyInstaller bundles the app into dist\Echoglass\ (+ files.json manifest), without
#    PyTorch, which this project doesn't redistribute
# 2. Inno Setup makes a small web installer dist\release\Echoglass-Setup-<version>.exe
#    that downloads PyTorch from download.pytorch.org (and optionally the Whisper model from
#    Hugging Face) during setup
# 3. update-from-<old>.zip deltas against earlier GitHub releases, for in-app partial updates
# 4. -Publish: tag v<version> and create the GitHub release with everything in dist\release
param([switch]$Publish)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$repo = "RDELX/Echoglass"
$py = "$root\.venv\Scripts\python.exe"

$version = (Get-Content "$root\livetranslate\__init__.py" | Select-String '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Echoglass $version"

& "$root\.venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "$root\dist" --workpath "$root\build" "$root\packaging\Echoglass.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# The Chrome extension ships next to the exe for "Load unpacked" (Settings > General opens it).
$ext = "$root\dist\Echoglass\browser-extension"
Remove-Item $ext -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$root\browser-extension" $ext -Recurse
$manifest = (Get-Content "$root\browser-extension\manifest.json" -Raw) -replace '"version": "[^"]+"', "`"version`": `"$version`""
[IO.File]::WriteAllText("$ext\manifest.json", $manifest, (New-Object Text.UTF8Encoding $false))  # no BOM

# Installer entries that download PyTorch/torchaudio from download.pytorch.org.
$deps = & $py "$root\packaging\make_deps.py"
if ($LASTEXITCODE -ne 0) { throw "make_deps failed" }
$deps | Select-Object -SkipLast 1 | Write-Host
$runtimeId = $deps[-1]

# Per-file hashes, so later builds can ship only what changed.
& $py "$root\packaging\make_update.py" manifest "$root\dist\Echoglass" $version $runtimeId
if ($LASTEXITCODE -ne 0) { throw "manifest failed" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup not found; the app is in dist\Echoglass\ but no installer was made." }
$out = "$root\dist\release"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
& $iscc "/O$out" "/DAppVersion=$version" "$root\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Copy-Item "$root\dist\Echoglass\files.json" "$out\files.json"

# Deltas from every earlier published release that has a files.json manifest.
$old = "$root\build\old-manifests"
Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $old | Out-Null
$tags = gh release list -R $repo --limit 20 --json tagName,isDraft --jq '.[] | select(.isDraft | not) | .tagName'
foreach ($tag in $tags) {
    $v = $tag.TrimStart("v")
    if ($v -eq $version) { continue }
    try { gh release download $tag -R $repo -p files.json -D "$old\$v" 2>&1 | Out-Null } catch { }  # older releases have none
    if (Test-Path "$old\$v\files.json") {
        & $py "$root\packaging\make_update.py" delta "$root\dist\Echoglass" "$old\$v\files.json" "$out\update-from-$v.zip"
    }
}

# LiveTranslate 0.8.0 and older look for an asset named LiveTranslate-Setup-*.exe when
# updating; give them a copy so they can reach Echoglass.
Copy-Item "$out\Echoglass-Setup-$version.exe" "$out\LiveTranslate-Setup-$version.exe"

Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } | Set-Content "$out\SHA256SUMS.txt"
Write-Host "Release files in $out"

if ($Publish) {
    $notes = "$root\build\release-notes.md"
    if (-not (Test-Path $notes)) { throw "Write the release notes to build\release-notes.md first" }
    git tag "v$version"
    git push origin "v$version"
    gh release create "v$version" -R $repo --title "Echoglass $version" --notes-file $notes (Get-ChildItem $out -File).FullName
    if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }
}
