# TurboCoreUpdater — build reproduzível (onefile, windowed, sem UPX).
# Uso: powershell -ExecutionPolicy Bypass -File updater/build.ps1
$ErrorActionPreference = "Stop"
$PY = "C:\Users\Gustavo\AppData\Local\Programs\Python\Python311\python.exe"
$ROOT = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
Set-Location $ROOT
$env:SOURCE_DATE_EPOCH = "946684800"
$env:PYTHONHASHSEED = "0"
& $PY -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
  --name TurboCoreUpdater `
  --distpath updater/bin --workpath build/updater --specpath build/updater `
  updater/turbocore_updater.py
if ($LASTEXITCODE -ne 0) { exit 1 }
$bin = Join-Path $ROOT "updater/bin/TurboCoreUpdater.exe"
$src = Join-Path $ROOT "updater/turbocore_updater.py"
$size = (Get-Item $bin).Length
$sha = (Get-FileHash $bin -Algorithm SHA256).Hash.ToLower()
$srcSha = (Get-FileHash $src -Algorithm SHA256).Hash.ToLower()
$artifact = [ordered]@{
  schema = 1; name = "TurboCoreUpdater.exe"; size = $size; sha256 = $sha
  source = "updater/turbocore_updater.py"; source_sha256 = $srcSha
  builder = "PyInstaller 6.21.0, Python 3.11.0, --onefile --windowed --clean --noupx, SOURCE_DATE_EPOCH=946684800, PYTHONHASHSEED=0"
}
$artifact | ConvertTo-Json | Set-Content (Join-Path $ROOT "updater/artifact.json") -Encoding utf8
Write-Output "OK: updater/bin/TurboCoreUpdater.exe size=$size sha256=$sha"
