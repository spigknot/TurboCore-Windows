"""Painel visual do TurboCore (Tkinter): núcleos, monitor live, update, sobre.

Aberto pelo menu ("Abrir painel") ou clique-esquerdo na tray. Instância única
por processo (state["panel"]). O loop de refresh lê o state e todo acesso a
widget roda na UI thread via after().
"""
from __future__ import annotations

import queue as queue_mod
import threading
import time
from pathlib import Path

from turbocore import __version__, updater_client
from turbocore.core_calc import build_core_options
from turbocore.pdh import FreqMonitor, aggregate_cores, format_core_row

# Verde idêntico ao botão de update do SIG (style "Update.TButton").
UPDATE_GREEN = "#16833a"
UPDATE_GREEN_ACTIVE = "#116b30"
UPDATE_GREEN_DISABLED = "#7ea98a"
UPDATE_FG_DISABLED = "#f1f4f2"
UPDATE_LABEL = "Atualizar"
REFRESH_MS = 1000


def sobre_texts() -> tuple[str, str, str]:
    """Textos idênticos ao Sobre do SIG; só a versão é do TurboCore."""
    return ("Delegacia de Taguaí", "Setor de Investigações Gerais", f"Versão: {__version__}")


def sobre_artwork() -> Path | None:
    """Wallpaper do Sobre (o mesmo appwin.png do SIG)."""
    from turbocore.icons import artwork_candidates
    for cand in artwork_candidates("appwin.png"):
        if cand.is_file():
            return cand
    return None


def cores_label(selected: int | None, physical: int) -> str:
    """Texto do botão de núcleos: 'Cores: X' (X = selecionado ou total livre)."""
    return f"Cores: {selected if selected is not None else physical}"


def dropdown_width(button_width: int) -> int:
    """Largura do popup de núcleos: 30% mais estreito que o botão."""
    return int(button_width * 0.7)


def step_line(started_at: str, label: str) -> str:
    """Linha inicial de etapa atualizável (clone do SIG)."""
    return f"{started_at}  {label}\n"


def finished_step_line(started_at: str, label: str, elapsed: float, *,
                       error: str | None = None, suffix: str | None = None) -> str:
    """Reescreve a linha da etapa na mesma linha (clone do SIG)."""
    if error:
        return f"{started_at}  {label} ERRO ({float(elapsed):.1f}s): {str(error).rstrip(' .')}\n"
    suffix_text = f" {suffix}" if suffix else ""
    return f"{started_at}  {label}{suffix_text} ({float(elapsed):.1f}s)\n"


def sync_file_line(started_at: str, path: str, display: str) -> str:
    """Linha viva por arquivo (clone do SIG: 100% vira linha nova sem %)."""
    if display == "100%":
        return f"{started_at}  Baixando {path}\n"
    return f"{started_at}  Baixando {path} - {display}\n"


def remove_paths(target: Path, files: dict[str, dict]) -> list[str]:
    """Caminhos do manifesto presentes no alvo (remover ao aplicar staged)."""
    removals = []
    for path in files:
        local = Path(target) / Path(*str(path).split("/"))
        if local.is_file():
            removals.append(path)
    return removals


def format_size(total_bytes: int) -> str:
    """Tamanho legível idêntico ao do SIG (1 byte, 512 bytes, 1,5 KB...)."""
    size = max(0, int(total_bytes))
    if size < 1000:
        return f"{size} byte" if size == 1 else f"{size} bytes"
    units = ("KB", "MB", "GB", "TB")
    value = float(size)
    unit_index = -1
    while unit_index < len(units) - 1 and value >= 999.95:
        value /= 1000.0
        unit_index += 1
    formatted = f"{value:.1f}".replace(".", ",")
    return f"{formatted} {units[unit_index]}"


def poll_update_once(target: Path | str, fetcher=None) -> str | None:
    """Retorna a versão remota se houver update, senão None (nunca levanta)."""
    try:
        manifest = (fetcher or updater_client.fetch_sync_manifest)()
        status = updater_client.check_for_update(Path(target), manifest)
    except Exception:
        return None
    return status["remote"] if status["update"] else None


def sync_download_worker(state: dict, target: Path, files: dict[str, dict],
                         download: list[str], log, on_done, urlopen=None,
                         version: str | None = None) -> None:
    """Baixa os arquivos novos num staged (SIG), validando SHA-256 por arquivo.

    on_done(kind, payload):
      ("ready", {"version", "staged", "removals"})     -> pronto p/ updater
      ("error", str)                                   -> falha (nada aplicado)
    """
    import hashlib
    import shutil
    import tempfile

    staging_root = Path(tempfile.gettempdir()) / "turbocore_updater_sync"
    if staging_root.exists():
        shutil.rmtree(staging_root, ignore_errors=True)
    staged = staging_root / "staged"
    staged.mkdir(parents=True)
    removals = []
    try:
        for path in download:
            entry = files[path]
            dest = staged / Path(*path.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            log.file_progress(path, "0%")

            def progress(downloaded: int, total: int, path=path):
                if total:
                    percent = min(100, int(downloaded * 100 / total))
                    log.file_progress(path, f"{percent}%")
                else:
                    log.file_progress(path, f"{downloaded} bytes")

            updater_client.download_url(str(entry.get("github_url") or ""), dest,
                                        progress_callback=progress, urlopen=urlopen)
            computed = hashlib.sha256(dest.read_bytes()).hexdigest().lower()
            if computed != str(entry["sha256"]).lower():
                raise RuntimeError(f"SHA-256 divergente ao baixar: {path}")
            log.file_progress(path, "100%", done_tag="vad_total")
        for path in sorted(files):
            local = target / Path(*path.split("/"))
            if local.is_file():
                removals.append(path)
        removals_path = staging_root / "removals.txt"
        removals_path.write_text("\n".join(removals) + ("\n" if removals else ""),
                                 encoding="utf-8")
        on_done("ready", {"version": version, "staged": staged,
                          "removals": removals_path, "download": download})
    except Exception as exc:
        try:
            shutil.rmtree(staging_root, ignore_errors=True)
        except Exception:
            pass
        on_done("error", str(exc))


def handle_update_click(state, destroy_fn, stop_fn, error_fn,
                        set_busy=None, urlopen=None) -> bool:
    """Botão verde (fluxo SIG): baixa com progresso e entrega ao updater.

    Retorna True se o app pode encerrar (updater já disparado), False se deve
    permanecer aberto. O download roda em thread com linhas vivas no log;
    ao terminar, entrega o staged ao updater e fecha o app.
    """
    pending = state.get("pending_update")
    log = state.get("log")
    target = updater_client.install_dir()
    if log is not None:
        log.append(f"Atualização {pending} iniciada.", "warning")
    if set_busy is not None:
        set_busy(True)

    def done(kind, payload):
        try:
            if kind == "ready":
                if log is not None:
                    log.append("Download concluído: aplicando atualização...", "vad_total")
                launched = updater_client.launch_updater_sync(
                    payload["staged"], payload["removals"], payload["version"], target)
                if not launched:
                    error_fn("Atualizador não encontrado nesta instalação.")
                    if set_busy is not None:
                        set_busy(False)
                    return
                destroy_fn()
                try:
                    stop_fn()
                except Exception:
                    pass
            else:
                error_fn(f"Não foi possível atualizar: {payload}")
                if set_busy is not None:
                    set_busy(False)
        except Exception as exc:
            error_fn(f"Não foi possível iniciar o atualizador: {exc}")
            if set_busy is not None:
                set_busy(False)

    def work():
        try:
            manifest = updater_client.fetch_sync_manifest()
            entries = {str(e["path"]): e for e in manifest["files"] if isinstance(e, dict)}
            # Nunca auto-substituir o updater em execução (bootstrap).
            entries = {p: e for p, e in entries.items() if p != "TurboCoreUpdater.exe"}
            plan = updater_client.classify_sync_files(target, entries)
            if not plan["download"]:
                done("error", "nenhum arquivo a baixar")
                return
            sync_download_worker(state, target, entries, plan["download"],
                                 log or _NullLog(), done, urlopen=urlopen,
                                 version=str(manifest.get("version") or ""))
        except Exception as exc:
            done("error", str(exc))
    threading.Thread(target=work, daemon=True).start()
    return True


class _NullLog:
    """Log descartável usado quando o painel não está aberto."""

    def append(self, message, tag=None):
        pass

    def begin(self, key, label):
        pass

    def finish(self, key, elapsed, *, error=None, suffix=None, tag=None):
        pass

    def file_progress(self, path, display, done_tag=None):
        pass


def start_auto_check(state: dict, notify=None) -> None:
    """Checagem automática silenciosa em thread (padrão SIG)."""
    def work():
        version = poll_update_once(updater_client.install_dir())
        if version:
            state["pending_update"] = version
            if notify is not None:
                try:
                    notify(version)
                except Exception:
                    pass

    threading.Thread(target=work, daemon=True).start()


class ManualCheck:
    """Verificação manual com trava de concorrência (espelha o SIG).

    on_done recebe (kind, payload):
      ("updated", {"version", "files", "download", "remove"})  -> há novidade
      ("uptodate", None)                                       -> já atualizado
      ("error", str)                                           -> falha
    """

    def __init__(self):
        self.busy = False
        self._started = 0.0

    def start(self, target, on_done, fetcher=None) -> bool:
        """Retorna False se já houver verificação em andamento."""
        if self.busy:
            return False
        self.busy = True
        self._started = time.perf_counter()

        def work():
            try:
                manifest = (fetcher or updater_client.fetch_sync_manifest)()
                status = updater_client.check_for_update(Path(target), manifest)
                if status["update"]:
                    entries = {str(e["path"]): e for e in manifest["files"] if isinstance(e, dict)}
                    plan = updater_client.classify_sync_files(Path(target), entries)
                    on_done("updated", {
                        "version": status["remote"],
                        "files": entries,
                        "download": plan["download"],
                    })
                else:
                    on_done("uptodate", None)
            except Exception as exc:
                on_done("error", str(exc))
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()
        return True


class ActivityLog:
    """Caixa de log do painel (clone do activity log do SIG).

    Métodos públicos seguros em qualquer thread: enfileiram a operação e
    acordam a UI via evento (o drain roda na UI thread).
    """

    TAGS = {
        "activity_step_running": "#33403e",
        "activity_step_done": "#16833a",
        "activity_step_warning": "#a8711a",
        "activity_step_error": "#b3261e",
        "vad_total": "#0a7a2f",
        "warning": "#a65300",
    }

    def __init__(self, root, box):
        self._root = root
        self._box = box
        self._ops: queue_mod.Queue = queue_mod.Queue()
        self._steps: dict = {}
        root.bind("<<ActivityLog>>", lambda _event: self._drain())

    def _post(self, op) -> None:
        self._ops.put(op)
        try:
            self._root.event_generate("<<ActivityLog>>", when="tail")
        except Exception:
            pass

    def append(self, message: str, tag: str | None = None) -> None:
        self._post(("append", message, tag))

    def begin(self, key: str, label: str) -> None:
        self._post(("begin", key, label, time.strftime("%H:%M:%S")))

    def finish(self, key: str, elapsed: float, *, error: str | None = None,
               suffix: str | None = None, tag: str | None = None) -> None:
        self._post(("finish", key, float(elapsed), error, suffix, tag))

    def file_progress(self, path: str, display: str, done_tag: str | None = None) -> None:
        self._post(("file", path, display, done_tag))

    def _ensure_tags(self) -> None:
        for name, color in self.TAGS.items():
            if name not in self._box.tag_names():
                self._box.tag_configure(name, foreground=color)

    def _drain(self) -> None:
        try:
            while True:
                self._apply(self._ops.get_nowait())
        except queue_mod.Empty:
            pass

    def _apply(self, op) -> None:
        try:
            if not self._box.winfo_exists():
                return
        except Exception:
            return
        kind = op[0]
        try:
            self._box.configure(state="normal")
            self._ensure_tags()
            if kind == "append":
                _, message, tag = op
                for part in str(message).splitlines():
                    line = f"{time.strftime('%H:%M:%S')}  {part}\n"
                    self._box.insert("end", line, tag or ())
            elif kind == "begin":
                _, key, label, started_at = op
                mark = f"activity_step_{key}"
                self._box.insert("end", step_line(started_at, label), "activity_step_running")
                try:
                    self._box.mark_set(mark, "end-2l linestart")
                    self._box.mark_gravity(mark, "left")
                except Exception:
                    mark = None
                self._steps[key] = {"mark": mark, "started_at": started_at, "label": label}
            elif kind == "finish":
                _, key, elapsed, error, suffix, tag = op
                step = self._steps.pop(key, None)
                if step is None:
                    return
                text = finished_step_line(step["started_at"], step["label"], elapsed,
                                          error=error, suffix=suffix)
                line_tag = "activity_step_error" if error else (tag or "activity_step_done")
                if step["mark"]:
                    try:
                        start = self._box.index(step["mark"])
                        end = self._box.index(f"{step['mark']} lineend +1c")
                        self._box.delete(start, end)
                        self._box.insert(start, text, line_tag)
                        self._box.mark_unset(step["mark"])
                    except Exception:
                        self._box.insert("end", text, line_tag)
                else:
                    self._box.insert("end", text, line_tag)
            elif kind == "file":
                _, path, display, done_tag = op
                line_tag = f"syncfile:{path}"
                try:
                    self._box.delete(f"{line_tag}.first", f"{line_tag}.last")
                except Exception:
                    pass
                if done_tag:
                    self._box.insert("end", sync_file_line(time.strftime("%H:%M:%S"), path, display),
                                     (line_tag, done_tag))
                else:
                    self._box.insert("end", sync_file_line(time.strftime("%H:%M:%S"), path, display),
                                     line_tag)
            self._box.see("end")
            self._box.configure(state="disabled")
        except Exception:
            pass


def _window_icon(root) -> None:
    """Pena padrão do Tk NUNCA: usa o mesmo chip da tray/exe."""
    try:
        from PIL import Image, ImageTk
        from turbocore.icons import icon_candidates
        for cand in icon_candidates():
            if cand.suffix.lower() == ".png" and cand.exists():
                photo = ImageTk.PhotoImage(Image.open(cand).resize((32, 32)), master=root)
                root.iconphoto(True, photo)
                root._chip_icon = photo  # mantém referência
                return
    except Exception:
        pass


def open_sobre(parent) -> None:
    """Tela Sobre idêntica à do SIG (canvas 420x638, textos centralizados)."""
    import tkinter as tk
    try:
        from PIL import Image, ImageTk
    except Exception:
        Image = ImageTk = None
    win = tk.Toplevel(parent)
    win.title("Sobre")
    win.resizable(False, False)
    win.configure(background="#000000")
    canvas = tk.Canvas(win, width=420, height=650, highlightthickness=0, background="#000000")
    canvas.pack(fill="both", expand=True)
    title, subtitle, version_line = sobre_texts()
    try:
        png = sobre_artwork()
        if png is None:
            raise FileNotFoundError("appwin.png ausente")
        with Image.open(png) as source:
            image_width = 415
            image_height = round(source.height * image_width / source.width)
            source = source.convert("RGBA").resize((image_width, image_height), Image.LANCZOS)
            win._sobre_img = ImageTk.PhotoImage(source, master=win)
        canvas.create_image(210, 0, anchor="n", image=win._sobre_img)
    except Exception:
        canvas.create_rectangle(0, 0, 420, 556, fill="#14201f", outline="")
    canvas.create_text(210, 586, text=title, fill="#ffffff", font=("Segoe UI Semibold", 13))
    canvas.create_text(210, 612, text=subtitle, fill="#e1f0ef", font=("Segoe UI", 10))
    canvas.create_text(210, 628, text=version_line, fill="#9bb3b0", font=("Segoe UI", 9))
    win.geometry("420x638")
    win.update_idletasks()
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"420x638+{x}+{y}")
    except Exception:
        pass
    win.lift()
    win.focus_force()


def open_panel(state: dict):
    """Abre (ou foca) o painel. Retorna a janela Tk."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    existing = state.get("panel")
    try:
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return existing
    except Exception:
        pass

    physical = state["physical"]
    logical = state.get("logical") or physical
    threads_per_core = max(logical // max(physical, 1), 1)

    root = tk.Tk()
    root.title("TurboCore")
    # 18 cores (18 linhas ~16px) + log (altura fixa) + topo: janela mais alta.
    root.geometry("380x720")
    root.resizable(False, False)
    state["panel"] = root
    _window_icon(root)

    style = ttk.Style(root)
    try:
        # Igual ao SIG: sem o clam, o tema "vista" do Windows ignora o
        # background/foreground do TButton e o botão sai esbranquiçado.
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Update.TButton", foreground="#ffffff", background=UPDATE_GREEN,
                    font=("Segoe UI Semibold", 10), padding=(12, 4))
    style.map("Update.TButton", background=[("active", UPDATE_GREEN_ACTIVE),
                                            ("disabled", UPDATE_GREEN_DISABLED)],
              foreground=[("disabled", UPDATE_FG_DISABLED)])

    # Linha 1: Núcleos (esquerda) + update verde (direita, oculto sem novidade).
    top = tk.Frame(root)
    top.pack(fill="x", padx=10, pady=(10, 2))
    from turbocore.tray import core_label

    def apply_choice(n: int) -> None:
        from turbocore import tray as tray_mod  # tardio: tray importa este módulo
        tray_mod.on_pick_core(state, n)

    nucleos_var = tk.StringVar(value=cores_label(state.get("selected"), physical))
    nucleos_btn = tk.Menubutton(top, textvariable=nucleos_var, relief="raised",
                                font=("Segoe UI", 10))
    nucleos_btn.pack(side="left")
    # Popup próprio (o tk.Menu não centraliza itens): linhas centralizadas e
    # 30% mais estreito que o botão.
    drop_state: dict = {"win": None}

    def close_drop() -> None:
        win = drop_state["win"]
        drop_state["win"] = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def open_drop() -> None:
        if drop_state["win"] is not None:
            close_drop()
            return
        options = build_core_options(physical)
        width = dropdown_width(max(nucleos_btn.winfo_width(), 1))
        row_h = 24
        x = nucleos_btn.winfo_rootx() + (nucleos_btn.winfo_width() - width) // 2
        y = nucleos_btn.winfo_rooty() + nucleos_btn.winfo_height()
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.configure(background="#999999")
        win.geometry(f"{width}x{len(options) * row_h + 2}+{x}+{y}")
        for n in options:
            lab = tk.Label(win, text=core_label(n), anchor="center",
                           font=("Segoe UI", 10), background="#ffffff")
            lab.pack(fill="x")
            lab.bind("<Button-1>", lambda _e, n=n: (close_drop(), apply_choice(n)))
        win.bind("<FocusOut>", lambda _e: close_drop())
        win.bind("<Escape>", lambda _e: close_drop())
        drop_state["win"] = win
        try:
            win.focus_force()
        except Exception:
            pass

    nucleos_btn.bind("<Button-1>", lambda _e: open_drop())

    update_button = ttk.Button(top, text="", style="Update.TButton")
    update_button.pack(side="right")
    update_button.pack_forget()

    def show_update(version: str) -> None:
        update_button.configure(text=UPDATE_LABEL)
        update_button.pack(side="right")

    def on_update_click():
        handle_update_click(
            state,
            destroy_fn=lambda: (root.destroy(), state.update(panel=None)),
            stop_fn=lambda: (state.get("icon").stop() if state.get("icon") else None),
            error_fn=lambda msg: messagebox.showerror("TurboCore", msg),
            set_busy=lambda busy: update_button.configure(
                state="disabled" if busy else "normal"))

    update_button.configure(command=on_update_click)

    # Lista direta, sem caixa: um Label por núcleo, mesma margem da linha 1.
    core_labels: list = []
    for _ in range(physical):
        label = tk.Label(root, text="", font=("Consolas", 10), anchor="w")
        label.pack(fill="x", padx=10)
        core_labels.append(label)
    monitor = FreqMonitor(logical)

    # Caixa de log (clone do activity log do SIG) ocupando o espaço restante.
    log_frame = tk.Frame(root)
    log_frame.pack(fill="both", expand=True, padx=10, pady=(10, 8))
    tk.Label(log_frame, text="Log", anchor="w",
             font=("Segoe UI Semibold", 9)).pack(anchor="w")
    log_text = tk.Text(log_frame, wrap="none", state="disabled",
                       font=("Consolas", 8), background="#ffffff",
                       foreground="#33403e", relief="solid", borderwidth=1,
                       padx=7, pady=7, height=6)
    log_text.pack(fill="both", expand=True)
    activity = ActivityLog(root, log_text)
    state["log"] = activity
    # Eventos de UI (check/update) também precisam logar em qualquer thread.
    activity.append("Painel aberto.")
    if state.get("post_update"):
        activity.append(f"Atualizado para {__version__}.", "vad_total")

    # Barra superior (espelha o menu do SIG): Verificar Atualizações + Sobre.
    menubar = tk.Menu(root, tearoff=0)
    menubar.add_command(label="Verificar Atualizações", command=lambda: on_check_click())
    menubar.add_command(label="Sobre", command=lambda: open_sobre(root))
    root.config(menu=menubar)
    checker = ManualCheck()

    def set_check_enabled(enabled: bool) -> None:
        try:
            menubar.entryconfigure("Verificar Atualizações",
                                   state="normal" if enabled else "disabled")
        except Exception:
            pass

    def on_manual_done(kind: str, payload) -> None:
        elapsed = time.perf_counter() - checker._started
        def ui():
            set_check_enabled(True)
            if kind == "updated":
                state["pending_update"] = payload["version"]
                show_update(payload["version"])
                activity.finish("update:check", elapsed, suffix="- Encontrada!",
                                tag="activity_step_warning")
                count = len(payload["download"])
                size = sum(int(payload["files"][path].get("size") or 0)
                           for path in payload["download"])
                activity.append(
                    f"Nova versão {payload['version']}: {count} arquivo(s) para baixar "
                    f"({format_size(size)}).", "warning")
            elif kind == "uptodate":
                activity.finish("update:check", elapsed, suffix="- Não tem!")
            else:
                activity.finish("update:check", elapsed, error=payload)
                messagebox.showerror("TurboCore", f"Não foi possível verificar: {payload}")
        try:
            root.after(0, ui)
        except Exception:
            pass

    def on_check_click():
        if not checker.start(updater_client.install_dir(), on_manual_done):
            messagebox.showinfo("TurboCore", "A verificação já está em andamento.")
            return
        set_check_enabled(False)
        activity.begin("update:check", "Verificando atualizações")

    import queue as queue_mod
    stats_queue: queue_mod.Queue = queue_mod.Queue(maxsize=1)
    stop_reader = threading.Event()
    latest: dict = {"stats": None}

    def reader():
        while not stop_reader.is_set():
            try:
                stats = monitor.read()
                try:
                    stats_queue.get_nowait()
                except queue_mod.Empty:
                    pass
                stats_queue.put(stats)
            except Exception:
                pass
            stop_reader.wait(REFRESH_MS / 1000.0)

    threading.Thread(target=reader, daemon=True).start()

    def tick():
        try:
            if not root.winfo_exists():
                return
        except Exception:
            return
        try:
            try:
                while True:
                    latest["stats"] = stats_queue.get_nowait()
            except queue_mod.Empty:
                pass
            if latest["stats"] is not None:
                rows = aggregate_cores(latest["stats"], threads_per_core)
                for index, mhz in enumerate(rows):
                    if index < len(core_labels):
                        core_labels[index].configure(text=format_core_row(index, mhz))
            pending = state.get("pending_update")
            if pending and not update_button.winfo_ismapped():
                show_update(pending)
            nucleos_var.set(cores_label(state.get("selected"), physical))
        except Exception:
            pass
        finally:
            try:
                root.after(REFRESH_MS, tick)
            except Exception:
                pass

    def on_close():
        try:
            stop_reader.set()
            monitor.close()
        finally:
            state["panel"] = None
            try:
                root.destroy()
            except Exception:
                pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    pending = state.get("pending_update")
    if pending:
        show_update(pending)
    root.after(REFRESH_MS, tick)
    return root


def run_panel(state: dict) -> None:
    """Abre o painel e entra no mainloop (chamado fora da thread do pystray)."""
    root = open_panel(state)
    try:
        root.mainloop()
    finally:
        state["panel"] = None
