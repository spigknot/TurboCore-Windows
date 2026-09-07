"""Instalador online do TurboCore.

Abre com um botão "Baixar"; nada é baixado até o usuário clicar. Ao clicar,
baixa os arquivos do Cloudflare R2 (sync_manifest.json schema 2 assinado, um
arquivo por vez com SHA-256 e contador "Arquivo X de N") — fallback: pacote
full da última release do GitHub. Instala em C:\\Program Files\\TurboCore com
atalhos, sem pacote embutido.

Build: PyInstaller --onefile --windowed --uac-admin (o UAC pede admin antes
da janela; a instalação em Program Files exige elevação).
"""

import base64
import hashlib
import json
import os
import queue
import shutil
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

GITHUB_API = "https://api.github.com/repos/spigknot/TurboCore-Windows/releases/latest"
R2_MANIFEST_URL = "https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev/sync_manifest.json"
# O R2.dev responde HTTP 1010 para User-Agent de bot (urllib) — usar o mesmo
# UA do TurboCoreUpdater, já liberado no bucket.
HTTP_USER_AGENT = "TurboCoreUpdater/1.0 (+https://github.com/spigknot/TurboCore-Windows)"
GITHUB_API_USER_AGENT = "turbocore-installer-online"
APP_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "TurboCore"
STAGING_DIR = Path(os.environ.get("TEMP") or r"C:\Windows\Temp") / "turbocore_installer_online"

SYNC_MANIFEST_SCHEMA = 2
SYNC_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
SYNC_MANIFEST_MAX_FILES = 20_000
FULL_ZIP_SUFFIX = "_full.zip"

# Chave pública de verificação do manifesto (a privada nunca sai da máquina de
# publicação). Cópia embutida de propósito: o instalador NÃO importa módulos do
# app/updater (o PyInstaller onefile empacota só o que é importado estaticamente).
UPDATE_PUBLIC_KEY_E = 65537
UPDATE_PUBLIC_KEY_N = 27004211898441161124830374800031538314053307966648721810182685395076946899324580017600288719057691739827143901803882476371020154181249528056966703840011591622428334767533983798905525607202683520094713535990316619148322944193574555715737024474662359200779893292693847651808768816417057131214822881326013999795581487109316671253094203676827258023312892415519517817670400542079114422013321544334735368744003710503796422316387624601984999168322330550227154438543004219320867926340985108707463847813578217247971314465494376231954859778023750907115523737221226217606884214190171918429130107814222989926011495710627043997121


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
        expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
        return encoded_bytes == expected
    except (TypeError, ValueError):
        return False


def canonical_sync_manifest(manifest: dict) -> bytes:
    """Payload canônico assinado (schema 2). Precisa bater byte a byte com o sync."""
    files = manifest.get("files") or []
    canonical_files = sorted(
        (
            {
                "path": str(entry.get("path") or ""),
                "sha256": str(entry.get("sha256") or "").lower(),
                "size": int(entry.get("size") or 0),
                "drive_id": str(entry.get("drive_id") or ""),
                "github_url": str(entry.get("github_url") or ""),
            }
            for entry in files
        ),
        key=lambda item: item["path"],
    )
    signed_payload = {
        "schema": int(manifest.get("schema") or 0),
        "version": str(manifest.get("version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "files": canonical_files,
    }
    return json.dumps(
        signed_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def download_manifest(url: str = R2_MANIFEST_URL, urlopen=None) -> dict:
    """Baixa e valida o sync_manifest.json (schema 2) publicado no R2."""
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with opener(request, timeout=30) as response:
        body = response.read(SYNC_MANIFEST_MAX_BYTES + 1)
    if len(body) > SYNC_MANIFEST_MAX_BYTES:
        raise RuntimeError("O manifesto do R2 excede o tamanho permitido.")
    try:
        manifest = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise RuntimeError("O manifesto do R2 não é um JSON válido.") from error
    if not isinstance(manifest, dict):
        raise RuntimeError("O manifesto do R2 não é um objeto JSON.")
    if int(manifest.get("schema") or 0) != SYNC_MANIFEST_SCHEMA:
        raise RuntimeError("O manifesto do R2 não usa o schema esperado.")
    if not _verify_rsa_sha256_signature(
        str(manifest.get("signature") or ""), canonical_sync_manifest(manifest)
    ):
        raise RuntimeError("O manifesto do R2 não possui assinatura válida.")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RuntimeError("O manifesto do R2 não lista arquivos.")
    if len(raw_files) > SYNC_MANIFEST_MAX_FILES:
        raise RuntimeError("O manifesto do R2 excede o limite de arquivos.")
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_entry(path: Path, sha256: str) -> bool:
    if _sha256_file(path).lower() != str(sha256).lower():
        raise RuntimeError(f"SHA-256 divergente ao baixar: {path.name}")
    return True


def _github_full_asset_url() -> str:
    """URL do asset ..._full.zip da última release do GitHub."""
    request = urllib.request.Request(
        GITHUB_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": GITHUB_API_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    for asset in data.get("assets", []):
        if asset["name"].endswith(FULL_ZIP_SUFFIX):
            return asset["browser_download_url"]
    raise RuntimeError("Nenhum pacote full encontrado na última release do GitHub.")


def _download_with_progress(url: str, destination: Path, progress_callback) -> None:
    """Baixa com barra de progresso (Content-Length quando disponível)."""
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(destination, "wb") as output:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    progress_callback(downloaded, total)
                else:
                    progress_callback(downloaded, downloaded or 1)
    progress_callback(destination.stat().st_size, destination.stat().st_size)


def install_tree(source_root: Path, app_dir: Path, report) -> None:
    files = [item for item in source_root.rglob("*") if item.is_file()]
    total = max(len(files), 1)
    for index, item in enumerate(files):
        target = app_dir / item.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        report("Instalando...", 5 + 85 * (index + 1) / total, f"Arquivo {index + 1}/{total}")


class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.staged_zip: Path | None = None
        self.staged_files: list[Path] | None = None
        self.source: str = ""  # "r2" | "github"
        self.download_started = False
        self.download_ok = False
        self._messages: queue.Queue = queue.Queue()
        root.title("TurboCore — Instalação online")
        root.geometry("560x280")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Instalação do TurboCore", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.status_var = tk.StringVar(value="Clique em Baixar para iniciar o download.")
        ttk.Label(frame, textvariable=self.status_var, wraplength=520).pack(anchor="w", pady=(6, 10))
        self.progress = ttk.Progressbar(frame, maximum=100, mode="determinate")
        self.progress.pack(fill="x")
        progress_info = ttk.Frame(frame)
        progress_info.pack(fill="x", pady=(2, 0))
        self.counter_var = tk.StringVar(value="")
        ttk.Label(progress_info, textvariable=self.counter_var).pack(side="left")
        self.percent_var = tk.StringVar(value="")
        ttk.Label(progress_info, textvariable=self.percent_var).pack(side="right")
        self.action_button = ttk.Button(frame, text="Baixar", command=self._on_action_button)
        self.action_button.pack(anchor="e", pady=(14, 0))
        ttk.Label(
            frame,
            text="O download é feito uma única vez e a instalação fica em "
            f"{APP_DIR}.",
            foreground="#555",
        ).pack(anchor="w", pady=(12, 0))
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)

    # -- Botão único: Baixar -> (download) -> Instalar ---------------------

    def _on_action_button(self):
        if self.download_ok:
            self._start_install()
        else:
            self._start_download()

    def _start_download(self):
        self.download_started = True
        self.download_ok = False
        self.source = ""
        self.action_button.configure(state="disabled", text="Baixando...")
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _on_close(self):
        if self.download_started and not self.download_ok:
            if not messagebox.askyesno("TurboCore", "Cancelar o download e fechar?"):
                return
        self.root.destroy()

    def _report(self, status: str, percent: float, counter: str = ""):
        self._messages.put((status, percent, counter))

    def _poll(self):
        try:
            while True:
                message = self._messages.get_nowait()
                if isinstance(message, tuple) and message[0] == "ENABLE":
                    self.action_button.configure(state="normal", text="Instalar")
                    continue
                if isinstance(message, tuple) and message[0] == "FAIL":
                    self.action_button.configure(state="normal", text="Baixar")
                    messagebox.showerror(
                        "TurboCore", f"Não foi possível baixar o pacote:\n{message[1]}"
                    )
                    continue
                if isinstance(message, tuple) and message[0] == "FAIL_INSTALL":
                    self.action_button.configure(text="Instalar")
                    self.action_button.configure(state="normal")
                    messagebox.showerror(
                        "TurboCore", f"Não foi possível instalar:\n{message[1]}"
                    )
                    continue
                if isinstance(message, tuple) and message[0] == "DONE":
                    app_dir = message[1]
                    self.status_var.set("TurboCore instalado com sucesso.")
                    try:
                        import subprocess
                        subprocess.Popen([str(Path(app_dir) / "TurboCore.exe")], cwd=str(app_dir))
                    except Exception:
                        pass
                    messagebox.showinfo("TurboCore", f"TurboCore instalado em {app_dir}.")
                    self.root.destroy()
                    continue
                status, percent, counter = message
                self.status_var.set(status)
                self.progress["value"] = percent
                self.percent_var.set(f"{round(percent)}%")
                self.counter_var.set(counter)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # -- Download: R2 (por arquivo) com fallback no GitHub (full.zip) ------

    def _download_worker(self):
        if self._download_from_r2():
            return
        self._download_from_github()

    def _download_from_r2(self) -> bool:
        try:
            self._report("Localizando a versão atual no Cloudflare R2...", 1, "")
            manifest = download_manifest()
            entries = [
                entry for entry in manifest.get("files") or []
                if isinstance(entry, dict)
                and str(entry.get("path") or "")
                and str(entry.get("github_url") or "")
            ]
            if not entries:
                raise RuntimeError("Manifesto do R2 sem arquivos para baixar.")
            entries.sort(key=lambda entry: str(entry["path"]))
            total = len(entries)
            STAGING_DIR.mkdir(parents=True, exist_ok=True)
            self.staged_files = []
            for index, entry in enumerate(entries):
                path = str(entry["path"])
                destination = STAGING_DIR / "sync" / Path(*path.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._download_r2_file(
                    str(entry["github_url"]), destination, path, index, total
                )
                verify_entry(destination, str(entry.get("sha256") or ""))
                self.staged_files.append(destination)
            self.source = "r2"
            self.download_ok = True
            self._report(
                f"Download concluído (versão {manifest.get('version')}) — clique em Instalar.",
                100, "",
            )
            self._messages.put(("ENABLE",))
            return True
        except Exception as error:
            import traceback
            detail = traceback.format_exc(limit=4)
            print(detail, file=sys.stderr)
            self._report(
                f"R2 indisponível ({type(error).__name__}); tentando o GitHub...", 2, ""
            )
            return False

    def _download_r2_file(
        self, url: str, destination: Path, path: str, index: int, total: int
    ) -> None:
        def _progress(downloaded: int, file_total: int) -> None:
            fraction = downloaded / max(file_total, 1)
            self._report(
                f"Baixando {path}",
                2 + 96 * (index + fraction) / total,
                f"Arquivo {index + 1}/{total}",
            )

        try:
            _download_with_progress(url, destination, _progress)
        except Exception:
            # Uma tentativa extra por arquivo: com ~1 mil downloads, uma
            # falha transitória de rede não deveria abortar a instalação.
            _download_with_progress(url, destination, _progress)

    def _download_from_github(self) -> None:
        try:
            self._report("Localizando o pacote mais recente no GitHub...", 2, "")
            full_url = _github_full_asset_url()
            self._report("Baixando o pacote do GitHub...", 3, "")
            STAGING_DIR.mkdir(parents=True, exist_ok=True)
            self.staged_zip = STAGING_DIR / "turbocore_full.zip"
            _download_with_progress(
                full_url, self.staged_zip, lambda d, t: self._report(
                    "Baixando o pacote do GitHub...", 3 + 95 * d / max(t, 1), ""
                )
            )
            self.source = "github"
            self.download_ok = True
            self._report("Download concluído — clique em Instalar.", 100, "")
            self._messages.put(("ENABLE",))
        except Exception as error:
            import traceback
            detail = traceback.format_exc(limit=4)
            print(detail, file=sys.stderr)
            self._messages.put(("FAIL", f"{error}\n{detail}"))

    # -- Instalação --------------------------------------------------------

    def _start_install(self):
        self.action_button.configure(state="disabled")
        self.action_button.configure(text="Instalando...")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        try:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
            self._report("Extraindo os arquivos...", 5, "")
            if self.source == "r2":
                source_root = STAGING_DIR / "sync"
            else:
                if self.staged_zip is None or not self.staged_zip.exists():
                    raise RuntimeError("Pacote baixado não encontrado.")
                with zipfile.ZipFile(self.staged_zip) as archive:
                    archive.extractall(STAGING_DIR / "extracted")
                source_root = STAGING_DIR / "extracted"
            APP_DIR.mkdir(parents=True, exist_ok=True)
            install_tree(source_root, APP_DIR, self._report)
            self._report("Criando os atalhos...", 92, "")
            self._create_shortcuts()
            self._report("Instalação concluída!", 100, "")
            self._messages.put(("DONE", str(APP_DIR)))
        except Exception as error:
            self._messages.put(("FAIL_INSTALL", str(error)))

    def _create_shortcuts(self):
        import win32com.client  # pywin32

        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
        start_menu = (
            Path(os.environ.get("ProgramData", r"C:\ProgramData"))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TurboCore"
        )
        start_menu.mkdir(parents=True, exist_ok=True)
        targets = [
            (APP_DIR / "TurboCore.exe", "TurboCore"),
            (APP_DIR / "TurboCoreUpdater.exe", "TurboCoreUpdater"),
        ]
        for executable, label in targets:
            for folder in (desktop, start_menu):
                shortcut = shell.CreateShortCut(str(folder / f"{label}.lnk"))
                shortcut.TargetPath = str(executable)
                shortcut.WorkingDirectory = str(APP_DIR)
                shortcut.Save()
        desktop.mkdir(parents=True, exist_ok=True)


def main():
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
