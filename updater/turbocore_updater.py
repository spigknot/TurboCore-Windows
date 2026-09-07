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


class ElevatedRelaunch(RuntimeError):
    """Sinal interno: uma cópia elevada foi disparada; o processo atual deve sair."""


def _is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _target_writable(target: Path) -> bool:
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".tc-updater-write-{uuid.uuid4().hex}.tmp"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _shell_execute_runas(executable: str, args: list[str]) -> int:
    params = " ".join(f'"{a}"' for a in args)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    if int(result) <= 32:
        raise UpdateError(f"elevação negada ou falhou (ShellExecute={int(result)})")
    return int(result)


def ensure_writable_or_elevate(target: Path, argv: list[str]) -> None:
    """Garante escrita no target ou relança elevado (cong.) / orienta (dev)."""
    if _target_writable(target):
        return
    if _is_admin():
        return  # admin sem escrita = problema real; o erro aparece na operação
    if getattr(sys, "frozen", False):
        _shell_execute_runas(str(Path(sys.executable).resolve()), list(argv))
        raise ElevatedRelaunch("cópia elevada disparada")
    raise UpdateError(
        f"sem permissão de escrita em {target}. Execute como administrador.")


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


def download_file(url: str, destination: Path, max_bytes: int = MAX_UNCOMPRESSED_BYTES,
                  progress=None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError(f"URL de download não confiável: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _urlopen(request) as response, destination.open("wb") as handle:
        try:
            total_size = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total_size = 0
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UpdateError("download excede o tamanho permitido")
            handle.write(chunk)
            if progress is not None:
                progress(total, total_size)


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


def _standalone_cache_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path(tempfile.gettempdir())
    return base / "TurboCore" / "updater"


def _default_target() -> Path:
    """A instalação mora em C:\\Program Files\\TurboCore (põe o instalador)."""
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "TurboCore"


def _standalone_log_path(target: Path) -> Path:
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".tc-updater-write-{uuid.uuid4().hex}.tmp"
        probe.write_bytes(b"")
        probe.unlink()
        return target / UPDATER_LOG_NAME
    except OSError:
        fallback = _standalone_cache_root() / UPDATER_LOG_NAME
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback


def full_download_path(target: Path, version: str, kind: str, zip_name: str) -> Path:
    """Destino do full: cache gravável — NUNCA o pai do target (Program Files)."""
    dest = _standalone_cache_root() / "downloads" / str(version) / str(kind) / str(zip_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


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
                wait_timeout: int = 120, startup_timeout: int = 12,
                progress=None) -> None:
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
                if progress is not None:
                    progress(index, len(plan["download"]), path)
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


# -- UI standalone (clone da UI do SigUpdater) ---

def _validate_sync_target(target: Path) -> None:
    has_files = any(p.is_file() for p in target.rglob("*")) if target.is_dir() else False
    if has_files and not (target / APP_EXE_NAME).is_file():
        raise UpdateError("A pasta não parece ser uma instalação do TurboCore. Use o pacote completo.")


def _set_window_icon(root) -> None:
    """Chip do TurboCore em vez da pena padrão do Tk."""
    try:
        import tkinter as tk
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "chip.png")
        candidates.append(Path(__file__).resolve().parent.parent / "assets" / "chip.png")
        for cand in candidates:
            if cand.is_file():
                photo = tk.PhotoImage(file=str(cand), master=root)
                root.iconphoto(True, photo)
                root._chip_icon = photo
                return
    except Exception:
        pass


def _validate_sync_target(target: Path) -> None:
    has_files = any(p.is_file() for p in target.rglob("*")) if target.is_dir() else False
    if has_files and not (target / APP_EXE_NAME).is_file():
        raise UpdateError("A pasta não parece ser uma instalação do TurboCore. Use o pacote completo.")


class StandaloneUpdaterUI:
    def __init__(self, target: Path):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.target = Path(target).resolve()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.sync_state: dict | None = None
        self.full: dict | None = None
        self.full_releases: list[dict] = []
        self.manual_zip: Path | None = None
        self.busy = False

        self.root = tk.Tk()
        self.root.title("Atualizador do TurboCore")
        self.root.geometry("620x430")
        self.root.minsize(580, 410)
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        _set_window_icon(self.root)

        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Accent.TButton", foreground="#13753b")

        container = ttk.Frame(self.root, padding=18)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Atualizador do TurboCore", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text=("Atualize uma instalação existente ou use o pacote completo para "
                  "instalar e reparar o aplicativo."),
            wraplength=570,
        ).pack(anchor="w", pady=(3, 14))

        path_row = ttk.Frame(container)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="Pasta do TurboCore:").pack(side="left")
        self.path_var = tk.StringVar(value=str(self.target))
        ttk.Entry(path_row, textvariable=self.path_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(8, 6)
        )
        self.choose_button = ttk.Button(path_row, text="Escolher...", command=self._choose_target)
        self.choose_button.pack(side="right")

        self.installed_var = tk.StringVar()
        self.available_var = tk.StringVar(value="Consultando versões disponíveis...")
        ttk.Label(container, textvariable=self.installed_var).pack(anchor="w", pady=(14, 2))
        ttk.Label(container, textvariable=self.available_var, wraplength=570).pack(anchor="w")

        self.progress = ttk.Progressbar(container, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(16, 5))
        self.status_var = tk.StringVar(value="Aguardando.")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w")

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(16, 10))
        self.check_button = ttk.Button(actions, text="Verificar", command=self.check_updates)
        self.check_button.pack(side="left")
        self.incremental_button = ttk.Button(
            actions, text="Atualizar", style="Accent.TButton",
            command=self._install_update, state="disabled")
        self.incremental_button.pack(side="left", padx=(8, 0))
        self.full_button = ttk.Button(
            actions, text="Instalar / reparar completo",
            command=lambda: self.install("full"), state="disabled")
        self.full_button.pack(side="left", padx=(8, 0))
        self.choose_zip_button = ttk.Button(
            actions, text="Escolher ZIP...", command=self._choose_manual_zip)
        self.choose_zip_button.pack(side="left", padx=(8, 0))

        version_row = ttk.Frame(container)
        version_row.pack(fill="x", pady=(0, 10))
        ttk.Label(version_row, text="Versão do pacote completo:").pack(side="left")
        self.full_version_var = tk.StringVar(value="(mais recente)")
        self.full_version_combo = ttk.Combobox(
            version_row, textvariable=self.full_version_var, state="readonly", width=26)
        self.full_version_combo.pack(side="left", padx=(8, 0))
        self.full_version_combo.bind("<<ComboboxSelected>>", self._on_full_version_selected)

        self.log = tk.Text(container, height=6, state="disabled", wrap="word",
                           background="#f4f6f5", relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True)
        self._refresh_installed_version()
        self.root.after(80, self._poll_events)
        self.root.after(250, self.check_updates)

    @staticmethod
    def _format_size(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} GB"

    def _write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _refresh_installed_version(self) -> None:
        version = installed_version(self.target)
        if version:
            text = f"Versão instalada: {version}"
        elif (self.target / APP_EXE_NAME).is_file():
            text = "Versão instalada: não identificada"
        else:
            text = "TurboCore ainda não instalado nesta pasta."
        self.installed_var.set(text)

    def _choose_target(self) -> None:
        selected = self.filedialog.askdirectory(
            title="Escolha a pasta de instalação do TurboCore",
            initialdir=str(self.target if self.target.exists() else self.target.parent),
            mustexist=False)
        if not selected:
            return
        self.target = Path(selected).resolve()
        self.path_var.set(str(self.target))
        self._refresh_installed_version()

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self.busy = busy
        normal = "disabled" if busy else "normal"
        self.check_button.configure(state=normal)
        self.choose_button.configure(state=normal)
        self.choose_zip_button.configure(state=normal)
        self.full_version_combo.configure(state="disabled" if busy else "readonly")
        self.incremental_button.configure(
            state="normal" if not busy and self.sync_state else "disabled")
        full_available = bool(self.full or self.manual_zip)
        self.full_button.configure(state="normal" if not busy and full_available else "disabled")
        if status:
            self.status_var.set(status)

    def check_updates(self) -> None:
        if self.busy:
            return
        self.progress["value"] = 0
        self._set_busy(True, "Consultando o R2 e o GitHub...")
        self._write_log("Verificando pacotes disponíveis.")
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        errors = []
        notice = None
        sync_state = None
        full_releases: list[dict] = []
        installed = installed_version(self.target)
        try:
            sync_manifest = fetch_sync_manifest()
            if installed and version_key(sync_manifest["version"]) <= version_key(installed):
                notice = (f"Sincronização {sync_manifest['version']} ignorada: "
                          f"a versão instalada ({installed}) já é igual ou mais nova.")
            else:
                classification = classify_sync_files(self.target, sync_manifest["files"])
                sync_state = {"kind": "sync", "version": sync_manifest["version"],
                              "files": {str(e["path"]): e for e in sync_manifest["files"]
                                        if isinstance(e, dict)},
                              "download": classification["download"]}
        except Exception as exc:
            errors.append(f"sincronização R2: {exc}")
        try:
            full_releases = fetch_full_releases()
        except Exception as exc:
            errors.append(f"completo: {exc}")
        self.events.put(("checked", sync_state, full_releases, errors, notice))

    def _on_full_version_selected(self, _event=None) -> None:
        selected = self.full_version_var.get()
        for descriptor in self.full_releases:
            if str(descriptor.get("version")) == selected:
                self.full = dict(descriptor)
                self._set_busy(False, f"Pacote completo {selected} selecionado.")
                self._write_log(f"Pacote completo selecionado: {selected} "
                                f"({self._format_size(int(descriptor['size']))}).")
                return

    def _choose_manual_zip(self) -> None:
        if self.busy:
            return
        selected = self.filedialog.askopenfilename(
            title="Escolha o pacote completo (.zip) baixado manualmente",
            initialdir=str(self.target.parent if self.target.exists() else Path.cwd()),
            filetypes=(("Pacote TurboCore", "*.zip"), ("Todos os arquivos", "*.*")))
        if not selected:
            return
        path = Path(selected).resolve()
        if not path.is_file():
            self.messagebox.showerror("Pacote completo", "O arquivo escolhido não existe.")
            return
        version = zip_version(path)
        if version is None:
            self.messagebox.showerror(
                "Pacote completo",
                "O arquivo escolhido não parece ser um pacote completo do TurboCore "
                "(build-info.json com versão válida não encontrado).")
            return
        try:
            validate_zip(path)
        except UpdateError as exc:
            self.messagebox.showerror(
                "Pacote completo", f"O pacote escolhido foi recusado na validação:\n\n{exc}")
            return
        self.manual_zip = path
        self.full_version_var.set(f"Manual: {version}")
        self._write_log(f"Pacote manual selecionado: {path.name} (versão {version}).")
        self._set_busy(False, f"Pacote manual {version} pronto para instalar.")

    def _confirm_regression(self, descriptor: dict) -> bool:
        installed = installed_version(self.target)
        target_version = str(descriptor.get("version") or "")
        if not installed or not target_version or version_key(target_version) >= version_key(installed):
            return True
        if not self.messagebox.askyesno(
                "Regressão de versão",
                "ATENÇÃO: REGRESSÃO DE VERSÃO\n\n"
                f"A versão instalada é {installed} e o pacote selecionado é {target_version}.\n\n"
                "Instalar este pacote REVERTERÁ o TurboCore para um estado mais antigo.\n"
                "Use apenas para corrigir um problema grave introduzido por uma "
                "versão mais nova.\n\nDeseja continuar mesmo assim?", icon="warning"):
            return False
        return self.messagebox.askyesno(
            "Regressão de versão",
            f"Confirmação final: instalar a versão ANTIGA {target_version} "
            f"por cima da {installed}?\n\nEsta ação sobrescreverá arquivos da "
            "instalação atual.", icon="warning")

    def _ensure_elevated_or_block(self) -> bool:
        if _target_writable(self.target) or _is_admin():
            return True
        if getattr(sys, "frozen", False):
            _shell_execute_runas(
                str(Path(sys.executable).resolve()),
                ["--standalone-worker", "--standalone-target", str(self.target)])
            self._write_log("Reiniciando como administrador...")
            self.root.destroy()
            return False
        self.messagebox.showerror(
            "Atualizador do TurboCore",
            f"Sem permissão de escrita em {self.target}.\n\nExecute como administrador.")
        return False

    def install(self, kind: str) -> None:
        if self.busy:
            return
        if not self._ensure_elevated_or_block():
            return
        if kind == "sync":
            if not self.sync_state:
                return
            try:
                _validate_sync_target(self.target)
            except UpdateError as exc:
                self.messagebox.showerror(
                    "Atualização",
                    f"A instalação não pode ser sincronizada.\n\n{exc}\n\nUse o pacote completo.",
                    parent=self.root)
                return
            if len(self.sync_state["download"]) > 100:
                if self.messagebox.askyesno(
                        "Muitos arquivos para baixar",
                        f"A sincronização precisa baixar {len(self.sync_state['download'])} arquivos. "
                        "Para instalações muito desatualizadas, o pacote completo é mais rápido "
                        "e confiável.\n\nDeseja usar o pacote completo do GitHub em vez da sincronização?",
                        icon="warning", parent=self.root):
                    self.install("full")
                    return
            self.progress["value"] = 0
            self._set_busy(True, "Baixando arquivos da sincronização...")
            self._write_log(f"Sincronização {self.sync_state['version']}: "
                            f"{len(self.sync_state['download'])} arquivo(s) para baixar.")
            threading.Thread(target=self._sync_install_worker,
                             args=(dict(self.sync_state),), daemon=True).start()
            return
        if kind == "manual":
            if not self.manual_zip:
                return
            version = zip_version(self.manual_zip) or ""
            descriptor = {"kind": "manual", "version": version,
                          "zip_name": self.manual_zip.name,
                          "local_zip": str(self.manual_zip),
                          "size": self.manual_zip.stat().st_size, "sha256": ""}
        else:
            descriptor = self.full
        if not descriptor:
            return
        if not self._confirm_regression(descriptor):
            return
        if kind == "manual":
            warning = (f"O pacote manual {descriptor['zip_name']} (versão {descriptor['version']}) "
                       "será instalado por cima da instalação atual.\n\n"
                       "O TurboCore aberto será fechado. Continuar?")
        else:
            warning = (f"O pacote completo {descriptor['version']} "
                       f"({self._format_size(descriptor['size'])}) será instalado. Ele pode reparar "
                       "uma instalação quebrada ou criar uma nova.\n\n"
                       "O TurboCore aberto será fechado. Continuar?")
        if not self.messagebox.askyesno("Atualizador do TurboCore", warning):
            return
        self.progress["value"] = 0
        self._set_busy(True, "Preparando o download..." if kind != "manual" else "Preparando a instalação...")
        threading.Thread(target=self._install_worker,
                         args=(dict(descriptor), kind), daemon=True).start()

    def _install_worker(self, descriptor: dict, kind: str) -> None:
        version = str(descriptor["version"])
        try:
            if descriptor.get("local_zip"):
                zip_path = Path(str(descriptor["local_zip"])).resolve()
                if not zip_path.is_file():
                    raise UpdateError("o pacote manual não está mais disponível")
            else:
                zip_path = full_download_path(self.target, version, kind, str(descriptor["zip_name"]))
                download_root = zip_path.parent
                download_root.mkdir(parents=True, exist_ok=True)

                def progress(downloaded: int, total: int) -> None:
                    percent = min(100, int(downloaded * 100 / max(1, total)))
                    self.events.put(("progress", percent, downloaded, total))

                self.events.put(("status", f"Baixando {descriptor['zip_name']}..."))
                download_file(descriptor["url"], zip_path, progress=progress)
            self.events.put(("status", "Validando o pacote antes de alterar a instalação..."))
            validate_zip(zip_path)
            log_path = _standalone_log_path(self.target)
            if getattr(sys, "frozen", False) and _same_path(sys.executable, self.target / UPDATER_EXE_NAME):
                raise UpdateError("o atualizador não foi realocado para a pasta temporária")
            _terminate_stray_processes(self.target / APP_EXE_NAME, log_path)
            self.events.put(("status", "Aplicando a atualização com rollback protegido..."))
            worker_full(zip_path, self.target, 0, log_path)
            if not descriptor.get("local_zip"):
                zip_path.unlink(missing_ok=True)
            self.events.put(("installed", version, log_path))
        except Exception as exc:
            self.events.put(("failed", str(exc)))

    def _install_update(self) -> None:
        if self.sync_state:
            self.install("sync")
        else:
            self._write_log("Nenhuma sincronização R2 disponível.")

    def _sync_install_worker(self, sync_state: dict) -> None:
        try:
            version = str(sync_state["version"])
            log_path = _standalone_log_path(self.target)

            def progress(index: int, total: int, path: str) -> None:
                percent = min(100, int(index * 100 / max(1, total)))
                self.events.put(("sync_file", index, total, path, percent))

            worker_diff(self.target, 0, log_path, force=True, progress=progress)
            self.events.put(("installed", version, log_path))
        except Exception as exc:
            self.events.put(("failed", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "checked":
                    self.sync_state, self.full_releases, errors, notice = (
                        event[1], event[2], event[3], event[4])
                    self.full = self.full_releases[0] if self.full_releases else None
                    details = []
                    if self.sync_state:
                        download_count = len(self.sync_state["download"])
                        download_size = sum(int(self.sync_state["files"][p]["size"])
                                            for p in self.sync_state["download"])
                        details.append(f"Sincronização: {self.sync_state['version']} "
                                       f"({download_count} arquivo(s), {self._format_size(download_size)})")
                    if self.full_releases:
                        labels = [str(item["version"]) for item in self.full_releases]
                        self.full_version_combo.configure(values=labels)
                        self.full_version_var.set(labels[0])
                        details.append(f"Completo: {labels[0]} "
                                       f"({self._format_size(int(self.full_releases[0]['size']))})")
                    self.available_var.set(" | ".join(details) or "Nenhum pacote disponível.")
                    for error in errors:
                        self._write_log("Não foi possível consultar o pacote " + error)
                    if notice:
                        self._write_log(notice)
                    if details:
                        self._write_log(f"Consulta concluída: {len(self.full_releases)} pacote(s) "
                                        "completo(s) disponíveis no GitHub.")
                    self._set_busy(False, "Pronto.")
                elif kind == "progress":
                    _name, percent, downloaded, total = event
                    self.progress["value"] = percent
                    self.status_var.set(f"Baixando: {percent}% ({self._format_size(downloaded)} de "
                                        f"{self._format_size(total)})")
                elif kind == "sync_file":
                    _index, _count, _path, _percent = event[1], event[2], event[3], event[4]
                    self.progress["value"] = _percent
                    self.status_var.set(f"Baixando arquivo {_index}/{_count}: {_path} ({_percent}%)")
                elif kind == "status":
                    self.status_var.set(event[1])
                    self._write_log(event[1])
                elif kind == "installed":
                    version, log_path = event[1], event[2]
                    self.progress["value"] = 100
                    self._set_busy(False, f"Versão {version} instalada e validada.")
                    self._write_log(f"Instalação concluída. Log: {log_path}")
                    self.messagebox.showinfo(
                        "Atualizador do TurboCore",
                        f"A versão {version} foi instalada e o TurboCore foi iniciado.")
                    self.root.destroy()
                    return
                elif kind == "failed":
                    self._set_busy(False, "A operação falhou; a instalação anterior foi preservada.")
                    self._write_log("Falha: " + event[1])
                    self.messagebox.showerror(
                        "Atualizador do TurboCore",
                        "Não foi possível concluir a operação.\n\n" + event[1])
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(80, self._poll_events)

    def _close(self) -> None:
        if self.busy:
            self.messagebox.showinfo("Atualizador do TurboCore", "Aguarde a operação em andamento terminar.")
            return
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def _relocate_standalone_updater(origin: Path) -> int:
    helpers = _standalone_cache_root() / "helpers"
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
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(helper), "--standalone-worker", "--standalone-target", str(origin)],
                     cwd=str(origin), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return 0


def run_standalone(target: Path | None = None, *, worker: bool = False) -> int:
    if target is None:
        target = _default_target()
    target = Path(target).resolve()
    if getattr(sys, "frozen", False) and not worker:
        return _relocate_standalone_updater(target)
    return StandaloneUpdaterUI(target).run()


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
    parser.add_argument("--standalone-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--standalone-target", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.standalone_worker:
        return run_standalone(args.standalone_target, worker=True)
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
        ensure_writable_or_elevate(
            args.target, list(sys.argv[1:] if argv is None else argv))
        if args.full_zip is not None:
            worker_full(args.full_zip, args.target, args.pid, args.log,
                        wait_timeout=args.wait_timeout, startup_timeout=args.startup_timeout)
        else:
            worker_diff(args.target, args.pid, args.log, force=args.force,
                        wait_timeout=args.wait_timeout, startup_timeout=args.startup_timeout)
        return 0
    except ElevatedRelaunch as exc:
        try:
            _log(args.log.resolve(), str(exc))
        except Exception:
            pass
        return 0
    except (UpdateError, OSError, ValueError) as exc:
        try:
            _log(args.log.resolve(), f"Falha na atualização: {exc}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
