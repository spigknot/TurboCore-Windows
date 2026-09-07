#!/usr/bin/env python3
"""Pipeline de release do TurboCore (espelha o fluxo do SIG, reduzido).

Uso (com o Python 3.11 do build):
    python scripts/tc_release.py preflight
    python scripts/tc_release.py bump --version YYYYMMDD_NNN
    python scripts/tc_release.py build --version YYYYMMDD_NNN
    python scripts/tc_release.py installer-offline --version YYYYMMDD_NNN
    python scripts/tc_release.py installer-online --version YYYYMMDD_NNN
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"^\d{8}_\d{3}$")
APP_VERSION_FILE = ROOT / "src" / "turbocore" / "__init__.py"
ISCC_CANDIDATES = [
    pathlib.Path(r"C:\Users\Gustavo\AppData\Local\Programs\Inno Setup 6\ISCC.exe"),
    pathlib.Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    pathlib.Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
]
PACKAGE_REQUIRED = [
    "TurboCore.exe",
    "TurboCoreUpdater.exe",
    "build-info.json",
    "assets/chip.ico",
    "assets/chip.png",
    "_internal/base_library.zip",
    "_internal/python311.dll",
]


def validate_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version or ""):
        raise SystemExit(f"versão inválida (esperado YYYYMMDD_NNN): {version!r}")
    return version


def bump_version(version: str) -> None:
    validate_version(version)
    text = APP_VERSION_FILE.read_text(encoding="utf-8")
    new = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', text)
    if new == text:
        raise SystemExit("não achei __version__ para bump")
    APP_VERSION_FILE.write_text(new, encoding="utf-8")
    print(f"versão: {version}")


def check_build_python() -> None:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(f"build exige Python 3.11 (atual: {sys.version.split()[0]})")


def kill_app_processes() -> None:
    for name in ("TurboCore.exe", "TurboCoreUpdater.exe"):
        subprocess.run(["taskkill", "/F", "/IM", name],
                       capture_output=True, timeout=30)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "Stop-Process -Name TurboCore,TurboCoreUpdater -Force -ErrorAction SilentlyContinue"],
        capture_output=True, timeout=60)


def write_build_info(package: pathlib.Path, version: str) -> None:
    import time
    (package / "build-info.json").write_text(
        json.dumps({"version": version,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "app": "TurboCore-Windows"}, indent=2),
        encoding="utf-8")


def assert_package_files(package: pathlib.Path) -> None:
    missing = [name for name in PACKAGE_REQUIRED if not (package / Path(*name.split("/"))).is_file()]
    if missing:
        raise SystemExit(f"package incompleto, faltando: {', '.join(missing)}")


def build_package(version: str) -> pathlib.Path:
    """Build onedir + monta release/generated/<v>/package. Retorna o package."""
    validate_version(version)
    check_build_python()
    kill_app_processes()
    gen = ROOT / "release" / "generated" / version
    if gen.exists():
        raise SystemExit(f"release/generated/{version} já existe (não rode 2x a mesma versão)")
    package = gen / "package"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--name", "TurboCore", "--windowed", "--icon", "assets/chip.ico",
           "--paths", "src",
           "--add-data", "assets/chip.ico;assets",
           "--add-data", "assets/chip.png;assets",
           "--distpath", str(gen / "dist"), "--workpath", str(ROOT / "build" / "app"),
           "src/turbocore/main.py"]
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), timeout=900)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller falhou (código {proc.returncode})")
    built = gen / "dist" / "TurboCore"
    if not (built / "TurboCore.exe").is_file():
        raise SystemExit("TurboCore.exe não foi gerado")
    shutil.copytree(built, package)
    updater_bin = ROOT / "updater" / "bin" / "TurboCoreUpdater.exe"
    if not updater_bin.is_file():
        raise SystemExit("updater/bin/TurboCoreUpdater.exe não existe (rode updater/build.ps1)")
    shutil.copy2(updater_bin, package / "TurboCoreUpdater.exe")
    write_build_info(package, version)
    assert_package_files(package)
    full_zip = gen / f"turbocore_{version}_full.zip"
    with zipfile.ZipFile(full_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package).as_posix())
    print(f"package: {package}")
    print(f"full: {full_zip} ({full_zip.stat().st_size} bytes)")
    return package


def build_installer_offline(version: str) -> pathlib.Path:
    validate_version(version)
    iscc = next((p for p in ISCC_CANDIDATES if p.is_file()), None)
    if iscc is None:
        raise SystemExit("ISCC.exe não encontrado (instale o Inno Setup 6)")
    gen = ROOT / "release" / "generated" / version
    proc = subprocess.run([str(iscc), f"/DAppVersion={version}", "installer/turbocore.iss"],
                          cwd=str(ROOT), timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"Inno falhou (código {proc.returncode})")
    setup = gen / f"setup_turbocore_{version}.exe"
    if not setup.is_file():
        raise SystemExit("setup offline não foi gerado")
    print(f"offline: {setup} ({setup.stat().st_size} bytes)")
    return setup


def build_installer_online(version: str) -> pathlib.Path:
    validate_version(version)
    check_build_python()
    name = f"online_setup_turbocore{version}.exe"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--windowed", "--uac-admin", "--noupx",
           "--name", f"online_setup_turbocore{version}",
           "--distpath", str(ROOT / "release" / "generated" / version),
           "--workpath", str(ROOT / "build" / "installer-online"),
           "installer/installer_online.py"]
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), timeout=900)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller (online) falhou (código {proc.returncode})")
    exe = ROOT / "release" / "generated" / version / name
    if not exe.is_file():
        raise SystemExit("instalador online não foi gerado")
    print(f"online: {exe} ({exe.stat().st_size} bytes)")
    return exe


def preflight() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                          cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise SystemExit("preflight: suíte vermelha")
    print("PASS: preflight (pytest)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="tc_release.py")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("bump", "build", "installer-offline", "installer-online"):
        parser = sub.add_parser(name)
        parser.add_argument("--version", required=True)
    sub.add_parser("preflight")
    args = ap.parse_args()
    if args.command == "bump":
        bump_version(args.version)
    elif args.command == "build":
        build_package(args.version)
    elif args.command == "installer-offline":
        build_installer_offline(args.version)
    elif args.command == "installer-online":
        build_installer_online(args.version)
    elif args.command == "preflight":
        preflight()


if __name__ == "__main__":
    main()
