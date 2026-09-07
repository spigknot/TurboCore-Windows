"""TurboCoreUpdater — atualizador transacional do TurboCore (Windows, onedir).

Autocontido (só stdlib; tkinter com import tardio): funciona mesmo com a
instalação corrompida. Espelha o protocolo do SigUpdater (manifesto schema 2,
RSA puro-python, UA próprio), reduzido ao tamanho do TurboCore.

Modos:
  worker diff:  --target <dir> --pid <pid> --log <arq> [--force]
  worker full:  --target <dir> --pid <pid> --log <arq> --full-zip <zip> [--full-sha256 <hex>]
  standalone:   sem argumentos -> UI Tkinter (diff R2, full GitHub, reparar)
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

VERSION_RE = re.compile(r"^\d{8}_\d{3}$")
APP_EXE_NAME = "TurboCore.exe"
UPDATER_EXE_NAME = "TurboCoreUpdater.exe"
UPDATE_LOCK_NAME = ".turbocore-update.lock"
UPDATER_LOG_NAME = "TurboCoreUpdater.log"
R2_PUBLIC_BASE = "https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev"
R2_MANIFEST_URL = f"{R2_PUBLIC_BASE}/sync_manifest.json"
GITHUB_RELEASES_API = "https://api.github.com/repos/spigknot/TurboCore-Windows/releases?per_page=20"
HTTP_USER_AGENT = "TurboCoreUpdater/1.0 (+https://github.com/spigknot/TurboCore-Windows)"
SYNC_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_UNCOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024
MAX_MEMBER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

UPDATE_PUBLIC_KEY_E = 65537
UPDATE_PUBLIC_KEY_N = 27004211898441161124830374800031538314053307966648721810182685395076946899324580017600288719057691739827143901803882476371020154181249528056966703840011591622428334767533983798905525607202683520094713535990316619148322944193574555715737024474662359200779893292693847651808768816417057131214822881326013999795581487109316671253094203676827258023312892415519517817670400542079114422013321544334735368744003710503796422316387624601984999168322330550227154438543004219320867926340985108707463847813578217247971314465494376231954859778023750907115523737221226217606884214190171918429130107814222989926011495710627043997121

SYNC_REQUIRED_FILES = (
    "TurboCore.exe",
    "TurboCoreUpdater.exe",
    "build-info.json",
    "_internal/base_library.zip",
    "_internal/python311.dll",
)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class UpdateError(RuntimeError):
    pass


def _log(log_path: Path | None, message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass


# -- Protocolo (mesma forma canônica do sync) --------------------------------

def _verify_rsa_sha256_signature(signature_b64: str, canonical_bytes: bytes) -> bool:
    try:
        signature = base64.b64decode(signature_b64 or "", validate=True)
        key_size = (UPDATE_PUBLIC_KEY_N.bit_length() + 7) // 8
        if len(signature) != key_size:
            return False
        encoded = pow(int.from_bytes(signature, "big"), UPDATE_PUBLIC_KEY_E, UPDATE_PUBLIC_KEY_N)
        encoded_bytes = encoded.to_bytes(key_size, "big")
        digest_info = (
            bytes.fromhex("3031300d060960864801650304020105000420")
            + hashlib.sha256(canonical_bytes).digest()
        )
        padding_size = key_size - len(digest_info) - 3
        if padding_size < 8:
            return False
        return encoded_bytes == b"\x00\x01" + b"\xff" * padding_size + b"\x00" + digest_info
    except Exception:
        return False


def canonical_sync_manifest(manifest: dict) -> bytes:
    files = sorted(
        (
            {
                "path": str(entry["path"]),
                "sha256": str(entry["sha256"]).lower(),
                "size": int(entry["size"]),
                "drive_id": str(entry.get("drive_id") or ""),
                "github_url": str(entry.get("github_url") or ""),
            }
            for entry in manifest.get("files", [])
        ),
        key=lambda item: item["path"],
    )
    payload = {
        "schema": int(manifest.get("schema") or 0),
        "version": str(manifest.get("version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "files": files,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_sync_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise UpdateError("manifesto inválido")
    if int(manifest.get("schema") or 0) != 2:
        raise UpdateError("schema do manifesto não suportado")
    version = str(manifest.get("version") or "")
    if not VERSION_RE.fullmatch(version):
        raise UpdateError("versão do manifesto inválida")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateError("manifesto sem arquivos")
    paths = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("entrada do manifesto inválida")
        path = str(entry.get("path") or "")
        if not path or ".." in path.split("/") or path.startswith("/"):
            raise UpdateError(f"caminho inseguro no manifesto: {path!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "").lower()):
            raise UpdateError(f"sha256 inválido no manifesto: {path!r}")
        paths.add(path)
    missing = [name for name in SYNC_REQUIRED_FILES if name not in paths]
    if missing:
        raise UpdateError(f"manifesto sem arquivos obrigatórios: {', '.join(missing)}")
    if not _verify_rsa_sha256_signature(str(manifest.get("signature") or ""), canonical_sync_manifest(manifest)):
        raise UpdateError("assinatura do manifesto inválida")
    return manifest


def _urlopen(request: urllib.request.Request, timeout: int = 60):
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_sync_manifest() -> dict:
    request = urllib.request.Request(R2_MANIFEST_URL, headers={"User-Agent": HTTP_USER_AGENT})
    with _urlopen(request) as response:
        payload = response.read(SYNC_MANIFEST_MAX_BYTES + 1)
    if len(payload) > SYNC_MANIFEST_MAX_BYTES:
        raise UpdateError("manifesto excede o tamanho permitido")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("manifesto não contém JSON válido") from exc
    return validate_sync_manifest(manifest)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_sync_files(target: Path, files: dict[str, dict]) -> dict:
    download, keep = [], []
    for path, entry in files.items():
        local = target / Path(*path.split("/"))
        if local.is_file() and _sha256_file(local).lower() == str(entry["sha256"]).lower():
            keep.append(path)
        else:
            download.append(path)
    return {"download": download, "keep": keep}


def installed_version(target: Path) -> str | None:
    try:
        metadata = json.loads((Path(target) / "build-info.json").read_text(encoding="utf-8"))
        version = str(metadata.get("version") or "")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return version if VERSION_RE.fullmatch(version) else None


def version_key(version: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(version or ""):
        return (0, 0, 0)
    return tuple(int(part) for part in version.split("_"))


def download_file(url: str, destination: Path, max_bytes: int = MAX_UNCOMPRESSED_BYTES) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError(f"URL de download não confiável: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _urlopen(request) as response, destination.open("wb") as handle:
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UpdateError("download excede o tamanho permitido")
            handle.write(chunk)


# -- ZIP completo ------------------------------------------------------------

def zip_version(zip_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = {member.filename for member in archive.infolist()}
            if "build-info.json" not in names:
                return None
            metadata = json.loads(archive.read("build-info.json").decode("utf-8"))
        version = str(metadata.get("version") or "")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError):
        return None
    return version if VERSION_RE.fullmatch(version) else None


def _is_symlink_info(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0o170000)


def validate_zip(zip_path: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"pacote ZIP inválido: {exc}") from exc
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UpdateError("pacote ZIP com entradas demais")
    total_uncompressed = 0
    seen: set[str] = set()
    for info in infos:
        name = info.filename.replace("\\", "/")
        if not name or name.startswith("/") or ".." in name.split("/") or name.endswith("/"):
            if name.endswith("/"):
                continue
            raise UpdateError(f"entrada insegura no ZIP: {name!r}")
        if name in seen:
            raise UpdateError(f"entrada duplicada no ZIP: {name!r}")
        seen.add(name)
        if _is_symlink_info(info):
            raise UpdateError(f"symlink no ZIP: {name!r}")
        if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise UpdateError(f"membro grande demais no ZIP: {name!r}")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise UpdateError("pacote ZIP grande demais")
        top = name.split("/")[0]
        if "." in top and top.split(".")[-1].upper() in WINDOWS_RESERVED_NAMES:
            raise UpdateError(f"nome reservado do Windows no ZIP: {name!r}")
    names = {n for n in seen}
    missing = [req for req in SYNC_REQUIRED_FILES if req not in names]
    if missing:
        raise UpdateError(f"ZIP sem arquivos obrigatórios: {', '.join(missing)}")
    if zip_version(zip_path) is None:
        raise UpdateError("ZIP sem build-info.json com versão válida")
    return "full"


def _extract_zip(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            target = destination / Path(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest, length=1024 * 256)


# -- Lock, transações, rollback ----------------------------------------------

@contextmanager
def installation_lock(target: Path, stale_after: int = 1800):
    lock = Path(target) / UPDATE_LOCK_NAME
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0
        if age < stale_after:
            raise UpdateError("outra atualização em andamento (lock presente)")
        try:
            lock.unlink()
        except OSError:
            pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise UpdateError("outra atualização em andamento (lock presente)")
    try:
        os.write(fd, f"pid={os.getpid()} ts={int(time.time())}".encode())
        os.close(fd)
    except OSError:
        pass
    try:
        yield lock
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _transaction_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path(tempfile.gettempdir())
    root = base / "TurboCore" / "updater" / "transactions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _recover_interrupted(target: Path, log_path: Path | None) -> None:
    try:
        entries = sorted(_transaction_root().iterdir())
    except OSError:
        return
    for entry in entries:
        journal = entry / "journal.json"
        if not entry.is_dir() or not journal.is_file():
            continue
        try:
            data = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "done":
            shutil.rmtree(entry, ignore_errors=True)
            continue
        _log(log_path, f"Recuperando transação interrompida: {entry.name}")
        try:
            _rollback(entry, target, log_path)
        except Exception as exc:
            _log(log_path, f"Falha ao reverter {entry.name}: {exc}")
        shutil.rmtree(entry, ignore_errors=True)


def _journal_write(transaction: Path, data: dict) -> None:
    (transaction / "journal.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _rollback(transaction: Path, target: Path, log_path: Path | None) -> None:
    try:
        journal = json.loads((transaction / "journal.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        journal = {}
    for relative in journal.get("added", []):
        try:
            victim = target / Path(*str(relative).split("/"))
            if victim.is_file():
                victim.unlink()
        except OSError:
            pass
    backup = transaction / "backup"
    if not backup.is_dir():
        return
    for path in sorted(backup.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(backup)
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    _log(log_path, "Rollback concluído: arquivos anteriores restaurados.")


def _apply_staged(staged: Path, target: Path, transaction: Path,
                  removals: set[str], log_path: Path | None) -> None:
    """Copia staged->target com backup journalizado; remove órfãos."""
    backup = transaction / "backup"
    staged_files = [p for p in staged.rglob("*") if p.is_file()]
    added = []
    for path in staged_files:
        relative = path.relative_to(staged)
        dest = target / relative
        if dest.is_file():
            current = backup / relative
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, current)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            added.append(relative.as_posix())
        shutil.copy2(path, dest)
    for relative in sorted(removals):
        victim = target / Path(*relative.split("/"))
        if victim.is_file():
            current = backup / Path(*relative.split("/"))
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(victim, current)
            victim.unlink()
    _journal_write(transaction, {"status": "applied", "added": added})
    _log(log_path, f"Aplicados {len(staged_files)} arquivo(s), removidos {len(removals)}.")


def _target_tree(target: Path) -> set[str]:
    out = set()
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        if relative == UPDATE_LOCK_NAME or relative == UPDATER_LOG_NAME:
            continue
        out.add(relative)
    return out


# -- Processos e verificação --------------------------------------------------

def _wait_for_pid(pid: int, timeout: int, log_path: Path | None) -> None:
    if not pid or pid <= 0 or os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        deadline = time.monotonic() + max(timeout, 1)
        while time.monotonic() < deadline:
            if kernel32.WaitForSingleObject(handle, 500) == 0:
                _log(log_path, f"Processo {pid} encerrado.")
                return
        raise UpdateError(f"o app (PID {pid}) não encerrou a tempo")
    finally:
        kernel32.CloseHandle(handle)


def _terminate_stray_processes(exe_path: Path, log_path: Path | None) -> None:
    if os.name != "nt":
        return
    me = os.getpid()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x2
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED = 0x1000

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260)]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value:
        return
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            if pid != me and entry.szExeFile.lower() == exe_path.name.lower():
                handle = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED, False, pid)
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(260)
                        psapi.GetModuleFileNameExW(handle, None, buf, 260)
                        if Path(buf.value or "").resolve() == exe_path.resolve():
                            kernel32.TerminateProcess(handle, 0)
                            _log(log_path, f"Processo residual {pid} encerrado.")
                    finally:
                        kernel32.CloseHandle(handle)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)


def _launch_and_verify(target_exe: Path, timeout: int, log_path: Path | None):
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    proc = subprocess.Popen([str(target_exe)], creationflags=flags, close_fds=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + max(timeout, 1)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise UpdateError(f"o app atualizado encerrou na verificação (código {proc.returncode})")
        time.sleep(0.5)
    _log(log_path, "App atualizado permanece em execução: verificação OK.")
    return proc


# -- Workers ------------------------------------------------------------------

def _default_log_path() -> Path:
    base = os.environ.get("TEMP") or str(Path.cwd())
    return Path(base) / UPDATER_LOG_NAME


def worker_diff(target: Path, pid: int, log_path: Path, *, force: bool = False,
                wait_timeout: int = 120, startup_timeout: int = 12) -> None:
    target, log_path = target.resolve(), log_path.resolve()
    _log(log_path, f"TurboCoreUpdater diff: target={target} pid={pid}")
    _recover_interrupted(target, log_path)
    manifest = fetch_sync_manifest()
    remote = str(manifest["version"])
    local = installed_version(target)
    _log(log_path, f"Instalado={local or '?'} remoto={remote}")
    if not force and local is not None and version_key(remote) <= version_key(local):
        _log(log_path, "Já atualizado. Nada a fazer.")
        return
    entries = {str(e["path"]): e for e in manifest["files"] if isinstance(e, dict)}
    plan = classify_sync_files(target, entries)
    _log(log_path, f"Baixar={len(plan['download'])} manter={len(plan['keep'])}")
    transaction = Path(tempfile.mkdtemp(prefix=".tc-updater-", dir=str(_transaction_root())))
    _journal_write(transaction, {"status": "started", "version": remote})
    try:
        with installation_lock(target):
            staged = transaction / "staged"
            for index, path in enumerate(plan["download"], 1):
                entry = entries[path]
                dest = staged / Path(*path.split("/"))
                _log(log_path, f"Baixando {index}/{len(plan['download'])}: {path}")
                download_file(str(entry.get("github_url") or ""), dest)
                if _sha256_file(dest).lower() != str(entry["sha256"]).lower():
                    raise UpdateError(f"SHA-256 divergente: {path}")
            removals = _target_tree(target) - set(entries)
            removals.discard(UPDATER_LOG_NAME)
            _wait_for_pid(pid, wait_timeout, log_path)
            _terminate_stray_processes(target / APP_EXE_NAME, log_path)
            _apply_staged(staged, target, transaction, removals, log_path)
        if installed_version(target) != remote:
            raise UpdateError("versão aplicada não confere com o manifesto")
        _launch_and_verify(target / APP_EXE_NAME, startup_timeout, log_path)
        _journal_write(transaction, {"status": "done", "version": remote})
        _log(log_path, "Atualização aplicada e validada.")
    except Exception:
        try:
            _rollback(transaction, target, log_path)
        except Exception as rollback_error:
            _log(log_path, f"Falha crítica no rollback: {rollback_error}")
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def worker_full(zip_path: Path, target: Path, pid: int, log_path: Path, *,
                wait_timeout: int = 120, startup_timeout: int = 12) -> None:
    target, log_path = target.resolve(), log_path.resolve()
    _log(log_path, f"TurboCoreUpdater full: zip={zip_path} target={target}")
    _recover_interrupted(target, log_path)
    kind = validate_zip(zip_path)
    assert kind == "full"
    remote = zip_version(zip_path)
    transaction = Path(tempfile.mkdtemp(prefix=".tc-updater-", dir=str(_transaction_root())))
    _journal_write(transaction, {"status": "started", "version": remote})
    try:
        with installation_lock(target):
            staged = transaction / "staged"
            _extract_zip(zip_path, staged)
            removals = _target_tree(target) - {p.relative_to(staged).as_posix()
                                               for p in staged.rglob("*") if p.is_file()}
            removals.discard(UPDATER_LOG_NAME)
            _wait_for_pid(pid, wait_timeout, log_path)
            _terminate_stray_processes(target / APP_EXE_NAME, log_path)
            _apply_staged(staged, target, transaction, removals, log_path)
        _launch_and_verify(target / APP_EXE_NAME, startup_timeout, log_path)
        _journal_write(transaction, {"status": "done", "version": remote})
        _log(log_path, "Instalação completa aplicada e validada.")
    except Exception:
        try:
            _rollback(transaction, target, log_path)
        except Exception as rollback_error:
            _log(log_path, f"Falha crítica no rollback: {rollback_error}")
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def select_full_release_asset(release: dict) -> dict:
    version = str(release.get("tag_name") or release.get("tagName") or "")
    if not VERSION_RE.fullmatch(version):
        raise UpdateError("a release completa possui uma versão inválida")
    candidates = [
        asset for asset in release.get("assets", [])
        if isinstance(asset, dict)
        and str(asset.get("name") or "").lower().endswith(".zip")
        and int(asset.get("size") or 0) > 0
    ]
    if not candidates:
        raise UpdateError("a release mais recente não possui um pacote ZIP completo")
    candidates.sort(key=lambda a: ("full" in str(a.get("name") or "").casefold(),
                                   int(a.get("size") or 0)), reverse=True)
    asset = candidates[0]
    digest = str(asset.get("digest") or "").lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UpdateError("o GitHub não forneceu o SHA-256 do pacote completo")
    url = str(asset.get("browser_download_url") or asset.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "objects.githubusercontent.com"}:
        raise UpdateError("a release completa contém uma URL de download não confiável")
    return {"kind": "full", "version": version, "zip_name": str(asset["name"]),
            "url": url, "sha256": digest, "size": int(asset["size"])}


def fetch_full_releases() -> list[dict]:
    request = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": HTTP_USER_AGENT,
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with _urlopen(request) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise UpdateError("a resposta das releases excedeu o tamanho permitido")
    try:
        releases = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("o GitHub não retornou a lista de releases") from exc
    if not isinstance(releases, list):
        raise UpdateError("o GitHub não retornou a lista de releases")
    descriptors = []
    for release in releases[:20]:
        if not isinstance(release, dict):
            continue
        try:
            descriptors.append(select_full_release_asset(release))
        except UpdateError:
            continue
    if not descriptors:
        raise UpdateError("nenhum pacote completo válido foi encontrado")
    return descriptors


# -- Self-update: relocar para fora do target ---------------------------------

def _relocate_self(extra_args: list[str]) -> int:
    helpers = _transaction_root().parent / "helpers"
    helpers.mkdir(parents=True, exist_ok=True)
    for previous in helpers.iterdir():
        try:
            if previous.is_dir():
                shutil.rmtree(previous, ignore_errors=True)
            else:
                previous.unlink()
        except OSError:
            pass  # helper em execução fica travado: usa dir novo
    helper_root = helpers / uuid.uuid4().hex
    helper_root.mkdir(parents=True, exist_ok=True)
    helper = helper_root / UPDATER_EXE_NAME
    shutil.copy2(Path(sys.executable).resolve(), helper)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(helper), *extra_args, "--relocated"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return 0


# -- UI standalone ------------------------------------------------------------

def run_standalone(target: Path | None = None) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    if target is None:
        target = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    state: dict = {"target": Path(target), "events": queue.Queue()}

    root = tk.Tk()
    root.title("TurboCore — Atualização")
    root.geometry("520x430")
    root.resizable(False, False)

    tk.Label(root, text="TurboCore — Atualização e reparo", font=("Segoe UI", 12, "bold")).pack(pady=8)
    target_var = tk.StringVar(value=str(state["target"]))
    row = tk.Frame(root)
    row.pack(fill="x", padx=12)
    tk.Entry(row, textvariable=target_var, width=52).pack(side="left", padx=(0, 6))
    tk.Button(row, text="Escolher...",
              command=lambda: target_var.set(filedialog.askdirectory() or target_var.get())).pack(side="left")
    ver_var = tk.StringVar(value="Instalado: ?   Remoto: ?")
    tk.Label(root, textvariable=ver_var).pack(pady=6)
    bar = ttk.Progressbar(root, length=480, mode="determinate")
    bar.pack(pady=4)
    log = tk.Text(root, height=12, width=62, state="disabled")
    log.pack(padx=12, pady=4)

    def emit(kind: str, payload: str = ""):
        state["events"].put((kind, payload))

    def append(text: str):
        log.configure(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")

    def set_busy(busy: bool, label: str = ""):
        for button in buttons:
            button.configure(state="disabled" if busy else "normal")
        status_var.set(label)

    status_var = tk.StringVar(value="Pronto.")
    tk.Label(root, textvariable=status_var).pack()

    def do_check():
        set_busy(True, "Verificando...")
        def work():
            try:
                manifest = fetch_sync_manifest()
                local = installed_version(Path(target_var.get()))
                emit("checked", f"{local or '?'} -> {manifest['version']}")
            except Exception as exc:
                emit("fail", str(exc))
        threading.Thread(target=work, daemon=True).start()

    def do_update(full: bool):
        set_busy(True, "Baixando e aplicando...")
        def work():
            try:
                tgt = Path(target_var.get())
                tmp_log = _default_log_path()
                emit("progress", "20")
                if full:
                    desc = fetch_full_releases()[0]
                    zp = tgt.parent / desc["zip_name"]
                    download_file(desc["url"], zp)
                    if _sha256_file(zp).lower() != desc["sha256"]:
                        raise UpdateError("SHA-256 do pacote completo divergente")
                    emit("progress", "60")
                    worker_full(zp, tgt, 0, tmp_log)
                else:
                    worker_diff(tgt, 0, tmp_log)
                emit("progress", "100")
                emit("done", "")
            except Exception as exc:
                emit("fail", str(exc))
        threading.Thread(target=work, daemon=True).start()

    buttons = [
        tk.Button(root, text="Verificar", width=14, command=do_check),
        tk.Button(root, text="Atualizar (diff)", width=14, command=lambda: do_update(False)),
        tk.Button(root, text="Reparar (full)", width=14, command=lambda: do_update(True)),
    ]
    brow = tk.Frame(root)
    brow.pack(pady=6)
    for button in buttons:
        button.pack(side="left", padx=4)

    def poll():
        try:
            while True:
                kind, payload = state["events"].get_nowait()
                if kind == "checked":
                    ver_var.set(f"Instalado: {payload.split(' -> ')[0]}   Remoto: {payload.split(' -> ')[1]}")
                    set_busy(False, "Pronto.")
                elif kind == "progress":
                    bar["value"] = float(payload)
                elif kind == "done":
                    set_busy(False, "Concluído.")
                    messagebox.showinfo("TurboCore", "Operação concluída.")
                elif kind == "fail":
                    set_busy(False, "Falhou.")
                    append(f"ERRO: {payload}")
                    messagebox.showerror("TurboCore", payload)
        except queue.Empty:
            pass
        root.after(150, poll)

    root.after(150, poll)
    root.mainloop()
    return 0


# -- CLI ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TurboCoreUpdater")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--full-zip", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--relocated", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=120)
    parser.add_argument("--startup-timeout", type=int, default=12)
    args = parser.parse_args(argv)
    if args.target is None and args.full_zip is None:
        if getattr(sys, "frozen", False) and not args.relocated:
            origin = Path(sys.executable).resolve().parent
            helpers = _transaction_root().parent / "helpers"
            helpers.mkdir(parents=True, exist_ok=True)
            return _relocate_self([])
        return run_standalone()
    if args.target is None or args.log is None:
        parser.error("--target e --log devem ser informados juntos")
    if getattr(sys, "frozen", False) and not args.relocated:
        return _relocate_self([a for a in (sys.argv[1:] if argv is None else argv)])
    try:
        if args.full_zip is not None:
            worker_full(args.full_zip, args.target, args.pid, args.log,
                        wait_timeout=args.wait_timeout, startup_timeout=args.startup_timeout)
        else:
            worker_diff(args.target, args.pid, args.log, force=args.force,
                        wait_timeout=args.wait_timeout, startup_timeout=args.startup_timeout)
        return 0
    except (UpdateError, OSError, ValueError) as exc:
        try:
            _log(args.log.resolve(), f"Falha na atualização: {exc}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
