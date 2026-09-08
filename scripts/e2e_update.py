"""E2E: instala pacote velho/corrompido num dir temp e atualiza via updater congelado + R2 real."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

PKG = Path("D:/Projetos/TurboCore/release/generated/20260907_009/package")
EXE = Path("D:/Projetos/TurboCore/updater/bin/TurboCoreUpdater.exe")

target = Path(tempfile.mkdtemp(prefix="tc-e2e-"))
shutil.copytree(PKG, target, dirs_exist_ok=True)
(target / "build-info.json").write_text(json.dumps({"version": "20260906_001"}))
(target / "TurboCore.exe").write_bytes(b"corrompido")
shutil.rmtree(target / "_internal" / "assets")
log = target.parent / "e2e.log"
print("alvo:", target, flush=True)

flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
proc = subprocess.run(
    [str(EXE), "--target", str(target), "--pid", "0",
     "--log", str(log), "--relocated"],
    capture_output=True, timeout=1200)
print("exit:", proc.returncode)
tail = log.read_text(encoding="utf-8").splitlines()[-4:]
print("\n".join(tail))

version = json.loads((target / "build-info.json").read_text())["version"]
assert version == "20260907_010", version
assert (target / "TurboCore.exe").read_bytes() != b"corrompido"
assert (target / "_internal" / "assets" / "chip.ico").is_file()
assert (target / "_internal" / "assets" / "appwin.png").is_file()
print("E2E_UPDATE_OK")
subprocess.run(
    ["powershell.exe", "-NoProfile", "-Command",
     f"Get-Process TurboCore -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{target / 'TurboCore.exe'}' }} | Stop-Process -Force"],
    capture_output=True, timeout=60)
shutil.rmtree(target, ignore_errors=True)
