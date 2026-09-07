"""Instalador online do TurboCore (Tkinter, PyInstaller onefile + uac-admin).

Baixa pelo manifesto R2 (todos os `files`, com SHA-256); fallback: full.zip
do GitHub. Instala em Program Files\\TurboCore + atalhos. Autocontido
(não importa o updater: só o que o script importa vai no exe).
"""
from __future__ import annotations

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

APP_NAME = "TurboCore"
APP_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "TurboCore"
R2_MANIFEST_URL = "https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev/sync_manifest.json"
GITHUB_API_LATEST = "https://api.github.com/repos/spigknot/TurboCore-Windows/releases/latest"
HTTP_USER_AGENT = "TurboCoreInstaller/1.0 (+https://github.com/spigknot/TurboCore-Windows)"
STAGING_DIR = Path(os.environ.get("TEMP") or ".") / "turbocore_installer_online"

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
        digest_info = (bytes.fromhex("3031300d060960864801650304020105000420")
                       + hashlib.sha256(canonical_bytes).digest())
        padding = key_size - len(digest_info) - 3
        if padding < 8:
            return False
        return encoded_bytes == b"\x00\x01" + b"\xff" * padding + b"\x00" + digest_info
    except Exception:
        return False


def canonical_sync_manifest(manifest: dict) -> bytes:
    files = sorted(
        ({"path": str(e["path"]), "sha256": str(e["sha256"]).lower(),
          "size": int(e["size"]), "drive_id": str(e.get("drive_id") or ""),
          "github_url": str(e.get("github_url") or "")} for e in manifest.get("files", [])),
        key=lambda item: item["path"])
    payload = {"schema": int(manifest.get("schema") or 0),
               "version": str(manifest.get("version") or ""),
               "created_at": str(manifest.get("created_at") or ""), "files": files}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def download_manifest(url: str = R2_MANIFEST_URL, urlopen=None) -> dict:
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with opener(request, timeout=60) as response:
        manifest = json.loads(response.read(2 * 1024 * 1024 + 1).decode("utf-8"))
    if int(manifest.get("schema") or 0) != 2 or not manifest.get("files"):
        raise RuntimeError("Manifesto do R2 inválido.")
    if not _verify_rsa_sha256_signature(str(manifest.get("signature") or ""),
                                        canonical_sync_manifest(manifest)):
        raise RuntimeError("Assinatura do manifesto inválida.")
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


def _download_with_progress(url: str, destination: Path, progress_callback) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    if urllib.parse.urlparse(url).scheme != "https":
        raise RuntimeError(f"URL não confiável: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            progress_callback(downloaded, total)


def _github_full_asset_url() -> str:
    import urllib.parse
    request = urllib.request.Request(
        GITHUB_API_LATEST,
        headers={"Accept": "application/vnd.github+json", "User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.loads(response.read(1024 * 1024).decode("utf-8"))
    zips = [a for a in release.get("assets", [])
            if str(a.get("name", "")).lower().endswith(".zip") and int(a.get("size") or 0) > 0]
    if not zips:
        raise RuntimeError("Release sem pacote ZIP.")
    zips.sort(key=lambda a: ("full" in str(a.get("name", "")).casefold(), int(a.get("size") or 0)),
              reverse=True)
    url = str(zips[0].get("browser_download_url") or "")
    if urllib.parse.urlparse(url).scheme != "https":
        raise RuntimeError("URL do GitHub não confiável.")
    return url


def install_tree(source_root: Path, app_dir: Path, report) -> None:
    files = [item for item in source_root.rglob("*") if item.is_file()]
    total = max(len(files), 1)
    for index, item in enumerate(files):
        target = app_dir / item.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        report("Instalando...", 5 + 85 * (index + 1) / total, f"Arquivo {index + 1}/{total}")


class InstallerApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.root = root
        self.root.title("TurboCore — Instalação")
        self.root.geometry("460x300")
        self.root.resizable(False, False)
        self._messages: queue.Queue = queue.Queue()
        self.download_ok = False
        self.source = ""
        self.staged_files: list = []
        self.staged_zip = None
        tk.Label(root, text="TurboCore — Instalação",
                 font=("Segoe UI", 13, "bold")).pack(pady=10)
        self.status = tk.Label(root, text="Pronto para baixar.", wraplength=420)
        self.status.pack()
        self.counter = tk.Label(root, text="")
        self.counter.pack()
        self.bar = ttk.Progressbar(root, length=400, mode="determinate")
        self.bar.pack(pady=10)
        self.action_button = tk.Button(root, text="Baixar e instalar",
                                       width=20, command=self._on_action_button)
        self.action_button.pack(pady=6)
        self.root.after(150, self._poll)

    def _on_action_button(self):
        self.action_button.configure(state="disabled", text="Baixando...")
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _on_close(self):
        self.root.destroy()

    def _report(self, status: str, percent: float, counter: str = ""):
        self._messages.put(("REPORT", status, percent, counter))

    def _poll(self):
        try:
            while True:
                message = self._messages.get_nowait()
                kind = message[0]
                if kind == "REPORT":
                    _, status, percent, counter = message
                    self.status.configure(text=status)
                    self.counter.configure(text=counter)
                    self.bar["value"] = percent
                elif kind == "ENABLE":
                    self.action_button.configure(state="normal", text="Instalar")
                    self.action_button.configure(
                        command=lambda: [self.action_button.configure(
                            state="disabled", text="Instalando..."), self._start_install()])
                elif kind == "DONE":
                    from tkinter import messagebox
                    messagebox.showinfo("TurboCore", f"Instalação concluída em {message[1]}")
                    self.root.destroy()
                elif kind in ("FAIL", "FAIL_INSTALL"):
                    from tkinter import messagebox
                    messagebox.showerror("TurboCore", str(message[1]))
                    self.action_button.configure(state="normal", text="Tentar de novo")
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _download_worker(self):
        if self._download_from_r2():
            return
        self._download_from_github()

    def _download_from_r2(self) -> bool:
        try:
            self._report("Localizando a versão atual no Cloudflare R2...", 1, "")
            manifest = download_manifest()
            entries = [e for e in manifest.get("files") or []
                       if isinstance(e, dict) and e.get("path") and e.get("github_url")]
            if not entries:
                raise RuntimeError("Manifesto do R2 sem arquivos para baixar.")
            entries.sort(key=lambda e: str(e["path"]))
            total = len(entries)
            STAGING_DIR.mkdir(parents=True, exist_ok=True)
            self.staged_files = []
            for index, entry in enumerate(entries):
                path = str(entry["path"])
                dest = STAGING_DIR / "sync" / Path(*path.split("/"))
                self._download_r2_file(str(entry["github_url"]), dest, path, index, total)
                verify_entry(dest, str(entry.get("sha256") or ""))
                self.staged_files.append(dest)
            self.source = "r2"
            self.download_ok = True
            self._report(f"Download concluído (versão {manifest.get('version')}).", 100, "")
            self._messages.put(("ENABLE",))
            return True
        except Exception as error:
            self._report(f"R2 indisponível ({type(error).__name__}); tentando o GitHub...", 2, "")
            return False

    def _download_r2_file(self, url, destination, path, index, total):
        def _progress(done, file_total):
            self._report(f"Baixando {path}", 2 + 96 * (index + done / max(file_total, 1)) / total,
                         f"Arquivo {index + 1}/{total}")
        try:
            _download_with_progress(url, destination, _progress)
        except Exception:
            _download_with_progress(url, destination, _progress)

    def _download_from_github(self) -> None:
        try:
            self._report("Localizando o pacote mais recente no GitHub...", 2, "")
            full_url = _github_full_asset_url()
            self._report("Baixando o pacote do GitHub...", 3, "")
            STAGING_DIR.mkdir(parents=True, exist_ok=True)
            self.staged_zip = STAGING_DIR / "turbocore_full.zip"
            _download_with_progress(full_url, self.staged_zip,
                                    lambda d, t: self._report(
                                        "Baixando o pacote do GitHub...", 3 + 95 * d / max(t, 1), ""))
            self.source = "github"
            self.download_ok = True
            self._report("Download concluído.", 100, "")
            self._messages.put(("ENABLE",))
        except Exception as error:
            self._messages.put(("FAIL", f"Falha no download: {error}"))

    def _start_install(self):
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
        start_menu = (Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                      / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TurboCore")
        start_menu.mkdir(parents=True, exist_ok=True)
        for executable, label in ((APP_DIR / "TurboCore.exe", "TurboCore"),
                                  (APP_DIR / "TurboCoreUpdater.exe", "TurboCoreUpdater")):
            for folder in (desktop, start_menu):
                shortcut = shell.CreateShortCut(str(folder / f"{label}.lnk"))
                shortcut.TargetPath = str(executable)
                shortcut.WorkingDirectory = str(APP_DIR)
                shortcut.Save()
        desktop.mkdir(parents=True, exist_ok=True)


def main():
    import tkinter as tk
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
