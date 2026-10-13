"""E2E: corrompe uma instalação temporária e a repara pelo updater + R2 real."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from turbocore import __version__ as APP_VERSION  # noqa: E402
from turbocore.updater_client import fetch_sync_manifest  # noqa: E402

PKG = ROOT / "release" / "generated" / APP_VERSION / "package"
EXE = ROOT / "updater" / "bin" / "TurboCoreUpdater.exe"
STALE_VERSION = "20000101_001"


def stop_test_app(target: Path) -> None:
    app_exe = str(target / "TurboCore.exe").replace("'", "''")
    command = (
        f"$path = '{app_exe}'; "
        "Get-Process TurboCore -ErrorAction SilentlyContinue "
        "| Where-Object { $_.Path -eq $path } | Stop-Process -Force"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        timeout=60,
    )


def main() -> None:
    manifest = fetch_sync_manifest()
    if manifest["version"] != APP_VERSION:
        raise RuntimeError(
            f"versão local {APP_VERSION} difere do manifesto R2 {manifest['version']}"
        )
    if not PKG.is_dir():
        raise FileNotFoundError(f"package da versão {APP_VERSION} não encontrado: {PKG}")
    if not EXE.is_file():
        raise FileNotFoundError(f"updater congelado não encontrado: {EXE}")

    target = Path(tempfile.mkdtemp(prefix="tc-e2e-")).resolve()
    log = target.parent / f"{target.name}.log"
    print("alvo:", target, flush=True)
    try:
        shutil.copytree(PKG, target, dirs_exist_ok=True)
        (target / "build-info.json").write_text(
            json.dumps({"version": STALE_VERSION}), encoding="utf-8"
        )
        (target / "TurboCore.exe").write_bytes(b"corrompido")
        shutil.rmtree(target / "_internal" / "assets")

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [
                str(EXE), "--target", str(target), "--pid", "0",
                "--log", str(log), "--relocated",
            ],
            capture_output=True,
            timeout=1200,
            creationflags=flags,
        )
        print("exit:", proc.returncode)
        if log.is_file():
            print("\n".join(log.read_text(encoding="utf-8").splitlines()[-8:]))
        if proc.returncode != 0:
            raise RuntimeError(
                f"updater terminou com código {proc.returncode}: "
                f"{proc.stderr.decode(errors='replace')}"
            )

        version = json.loads((target / "build-info.json").read_text(encoding="utf-8"))["version"]
        assert version == manifest["version"], (version, manifest["version"])
        assert (target / "TurboCore.exe").read_bytes() != b"corrompido"
        assert (target / "_internal" / "assets" / "chip.ico").is_file()
        assert (target / "_internal" / "assets" / "appwin.png").is_file()
        print("E2E_UPDATE_OK")
    finally:
        try:
            stop_test_app(target)
        finally:
            shutil.rmtree(target, ignore_errors=True)
            log.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
