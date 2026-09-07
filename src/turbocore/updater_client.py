"""Lado app da atualização: consulta o manifesto R2 e dispara o updater.

Sem dependências além da stdlib (vai congelado no TurboCore.exe).
A verificação RSA é puro-python (pow), igual ao SigUpdater.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION_RE = re.compile(r"^\d{8}_\d{3}$")
R2_PUBLIC_BASE = "https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev"
R2_MANIFEST_URL = f"{R2_PUBLIC_BASE}/sync_manifest.json"
GITHUB_RELEASES_API = "https://api.github.com/repos/spigknot/TurboCore-Windows/releases?per_page=20"
HTTP_USER_AGENT = "TurboCoreUpdater/1.0 (+https://github.com/spigknot/TurboCore-Windows)"
SYNC_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
UPDATER_EXE_NAME = "TurboCoreUpdater.exe"

# Chave PUBLICA do manifesto (seguro embutir; a privada fica só em release/).
UPDATE_PUBLIC_KEY_E = 65537
UPDATE_PUBLIC_KEY_N = 27004211898441161124830374800031538314053307966648721810182685395076946899324580017600288719057691739827143901803882476371020154181249528056966703840011591622428334767533983798905525607202683520094713535990316619148322944193574555715737024474662359200779893292693847651808768816417057131214822881326013999795581487109316671253094203676827258023312892415519517817670400542079114422013321544334735368744003710503796422316387624601984999168322330550227154438543004219320867926340985108707463847813578217247971314465494376231954859778023750907115523737221226217606884214190171918429130107814222989926011495710627043997121

# Arquivos que TORNAM um manifesto válido p/ o TurboCore. Componentes
# desconhecidos são IGNORADOS (forward-compat: updaters antigos não travam).
SYNC_REQUIRED_FILES = (
    "TurboCore.exe",
    "TurboCoreUpdater.exe",
    "build-info.json",
    "_internal/base_library.zip",
    "_internal/python311.dll",
)


class UpdateError(RuntimeError):
    pass


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
        expected = b"\x00\x01" + b"\xff" * padding_size + b"\x00" + digest_info
        return encoded_bytes == expected
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


def fetch_sync_manifest(urlopen=None) -> dict:
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(R2_MANIFEST_URL, headers={"User-Agent": HTTP_USER_AGENT})
    with opener(request, timeout=60) as response:
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
    """Separa arquivos do manifesto em baixar/manter por hash local."""
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


def check_for_update(target: Path, manifest: dict) -> dict:
    local = installed_version(target)
    remote = str(manifest.get("version") or "")
    return {"local": local, "remote": remote, "update": version_key(remote) > version_key(local or "")}


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def find_updater_exe() -> Path | None:
    for base in (install_dir(), Path(__file__).resolve().parent.parent / "updater"):
        candidate = base / UPDATER_EXE_NAME
        if candidate.is_file():
            return candidate
    return None


def launch_updater(target: Path) -> bool:
    updater = find_updater_exe()
    if updater is None:
        return False
    log_path = Path(os.environ.get("TEMP") or ".") / "TurboCoreUpdater.log"
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(updater), "--target", str(target), "--pid", str(os.getpid()),
         "--log", str(log_path)],
        creationflags=creationflags, close_fds=True,
    )
    return True


def download_url(url: str, destination: Path, progress_callback=None,
                 urlopen=None) -> str:
    """Baixa de URL (R2) devolvendo o sha256 (clone SIG download_github_url).

    progress_callback(downloaded, total) é chamado a cada chunk.
    """
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = urlopen or urllib.request.urlopen
    digest = hashlib.sha256()
    with opener(request, timeout=120) as response, destination.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if progress_callback:
                progress_callback(downloaded, total)
    return digest.hexdigest()


def launch_updater_sync(staged: Path, removals_path: Path, version: str,
                        target: Path) -> bool:
    """Dispara o updater para aplicar um staged já baixado (fluxo SIG)."""
    updater = find_updater_exe()
    if updater is None:
        return False
    log_path = Path(os.environ.get("TEMP") or ".") / "TurboCoreUpdater.log"
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(updater), "--sync-staged", str(staged), "--sync-removals",
         str(removals_path), "--sync-version", str(version),
         "--target", str(target), "--pid", str(os.getpid()),
         "--log", str(log_path)],
        creationflags=creationflags, close_fds=True,
    )
    return True
