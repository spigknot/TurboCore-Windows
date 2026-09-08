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
from turbocore.nodeslider import NodeSlider
from turbocore.pdh import FreqMonitor, aggregate_cores, format_core_row

# Verde idêntico ao botão de update do SIG (style "Update.TButton").
UPDATE_GREEN = "#16833a"
UPDATE_GREEN_ACTIVE = "#116b30"
UPDATE_GREEN_DISABLED = "#7ea98a"
UPDATE_FG_DISABLED = "#f1f4f2"
UPDATE_LABEL = "Atualizar"
REFRESH_MS = 1000
# Largura justa: linha do slider (240px) + margens, e espaço para o label
# centralizado conviver com o botão Atualizar à direita sem sobreposição.
PANEL_GEOMETRY = "300x720"
# Raio do botão Aplicar (px): com padding simétrico o botão sai quadrado;
# 21px + padding (4,4) ~= 36px de lado (+50% sobre os 24px originais).
BOLT_PX = 21


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


def create_apply_button(master, style_name: str, command):
    """Botão Aplicar quadrado com ícone de raio (sem texto).

    Extraído de open_panel para teste (a suíte só permite um Tk() por
    processo). Fallback para texto se o PIL falhar. Padding simétrico do
    estilo => largura == altura por construção.
    """
    from tkinter import ttk
    try:
        from PIL import ImageTk
        from turbocore.icons import bolt_image
        photo = ImageTk.PhotoImage(bolt_image(BOLT_PX), master=master)
    except Exception:
        photo = None
    if photo is not None:
        btn = ttk.Button(master, image=photo, text="", style=style_name,
                         command=command)
        btn.image = photo  # mantém referência (sem GC)
    else:
        btn = ttk.Button(master, text="Aplicar", style=style_name,
                         command=command)
    return btn


def cores_label(selected: int | None, physical: int) -> str:
    """Texto do botão de núcleos: 'Cores: X' (X = selecionado ou total livre)."""
    return f"Cores: {selected if selected is not None else physical}"


def slider_index_for(options: list[int], selected: int | None) -> int:
    """Índice inicial do slider: o aplicado; sem valor, tudo livre (último)."""
    try:
        return list(options).index(selected)
    except ValueError:
        return len(options) - 1


def needs_apply(preview: int, selected: int | None) -> bool:
    """Há comando a executar: preview difere do aplicado."""
    return preview != selected


def apply_outcome(preview: int, selected: int | None,
                  physical: int) -> tuple[str, bool]:
    """Mensagem de log + se executa comandos. Pura (testável).

    Mesmo valor => no-op com "já é". Sem aplicado (tudo livre) => o
    anterior é o total físico.
    """
    if not needs_apply(preview, selected):
        return f"Núcleos ativos já é {preview}.", False
    old = selected if selected is not None else physical
    return f"Núcleos ativos {old} -> {preview}.", True


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
        # Órfãos = arquivos no disco que NÃO estão no manifesto novo (espelha
        # worker_full: _target_tree - staged). NUNCA o manifesto inteiro:
        # ele lista o que deve EXISTIR, não o que deve sair. Protegidos:
        # o updater em execução, seu lock e seu log (não estão no staged).
        protected = {updater_client.UPDATER_EXE_NAME, ".turbocore-update.lock",
                     "TurboCoreUpdater.log"}
        manifest_names = set(files)
        removals = []
        for local in sorted(Path(target).rglob("*")):
            if not local.is_file():
                continue
            rel = local.relative_to(Path(target)).as_posix()
            if rel not in manifest_names and rel not in protected:
                removals.append(rel)
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


def poll_update_settle(state: dict) -> bool:
    """Recolhe state["update_settle"] e executa. O tick() chama na UI thread.

    Retorna True se havia um desfecho pendente (executado ou não).
    """
    try:
        settle_fn = state.pop("update_settle", None)
    except Exception:
        return False
    if settle_fn is None:
        return False
    try:
        settle_fn()
    except Exception:
        pass
    return True


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
    # Trava de duplo-clique: um segundo updater concorrente no mesmo target
    # intercalava applies/rollbacks (23:17 do log real). Roda na UI thread.
    if state.get("updating"):
        if log is not None:
            try:
                log.append("Atualização já em andamento.", "warning")
            except Exception:
                pass
        return False
    state["updating"] = True
    if log is not None:
        log.append(f"Atualização {pending} iniciada.", "warning")
    if set_busy is not None:
        set_busy(True)

    # O desfecho (Popen do updater + teardown + diálogos) PRECISA rodar na UI
    # thread — mas NENHUM chamado Tkinter é confiável a partir da thread de
    # download (after e event_generate levantam "main thread is not in main
    # loop" de forma racy: foi assim que o app ficou vivo e o updater expirou
    # os 120s sem relançar). Mecanismo determinístico: a worker deposita o
    # outcome em state["update_settle"] e o tick() (UI thread, 1s) recolhe e
    # executa. Um watchdog cobre o caso do painel fechado no meio do
    # download (tick morto): aí o teardown roda direto — o destroy falha e é
    # ignorado, mas o stop TEM que rodar para o updater prosseguir.
    outcome: dict = {}

    def teardown() -> None:
        try:
            destroy_fn()
        except Exception:
            pass
        try:
            stop_fn()
        except Exception:
            pass

    def settle() -> None:
        result = outcome.pop("result", None)
        if result is None:
            return  # recolhido 2x (tick + watchdog): nada a fazer
        # Libera a trava mesmo no sucesso: se o teardown não matar o processo
        # (stop quebrado), o usuário ainda pode tentar de novo.
        try:
            state.pop("updating", None)
        except Exception:
            pass
        kind, payload = result
        try:
            if kind == "ready":
                launched = updater_client.launch_updater_sync(
                    payload["staged"], payload["removals"], payload["version"], target)
                if not launched:
                    error_fn("Atualizador não encontrado nesta instalação.")
                    if set_busy is not None:
                        set_busy(False)
                    return
                # O updater espera o PID morrer: o teardown TEM que rodar para
                # o processo encerrar e o relançamento ocorrer.
                teardown()
            else:
                error_fn(f"Não foi possível atualizar: {payload}")
                if set_busy is not None:
                    set_busy(False)
        except Exception as exc:
            try:
                error_fn(f"Não foi possível iniciar o atualizador: {exc}")
            except Exception:
                pass
            try:
                if set_busy is not None:
                    set_busy(False)
            except Exception:
                pass

    def watchdog() -> None:
        if state.pop("update_settle", None) is None:
            return  # a UI (tick) já recolheu
        try:
            settle()
        except Exception:
            pass

    def done(kind, payload):
        if kind == "ready" and log is not None:
            try:
                log.append("Download concluído: aplicando atualização...", "vad_total")
            except Exception:
                pass
        outcome["result"] = (kind, payload)
        state["update_settle"] = settle
        timer = threading.Timer(8.0, watchdog)
        timer.daemon = True
        timer.start()

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
    root.geometry(PANEL_GEOMETRY)
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

    # Linha 1: "Cores: X" fixo no centro da tela + update verde à direita.
    # Linha 2: slider centralizada. Linha 3: botão Aplicar compacto, centrado.
    top = tk.Frame(root, height=34)
    top.pack(fill="x", padx=10, pady=(10, 0))
    top.pack_propagate(False)

    def apply_choice(n: int) -> None:
        from turbocore import tray as tray_mod  # tardio: tray importa este módulo
        # Botão sempre clicável e com a mesma aparência: mesmo valor => no-op
        # (só loga "já é"), sem executar powercfg.
        message, run = apply_outcome(n, state.get("selected"), physical)
        if run:
            tray_mod.on_pick_core(state, n)
        log = state.get("log")
        if log is not None:
            try:
                log.append(message, "vad_total")
            except Exception:
                pass

    options = build_core_options(physical)
    preview_var = tk.StringVar()
    preview_label = tk.Label(top, textvariable=preview_var, font=("Segoe UI", 10))
    # place() com âncora no centro do frame: o botão Atualizar (à direita)
    # não desloca o texto — ele fica fixo no centro da tela.
    preview_label.place(relx=0.5, rely=0.5, anchor="center")

    def current_option() -> int:
        try:
            return options[int(round(float(scale.get())))]
        except (ValueError, IndexError):
            return options[-1]

    def refresh_aplicar() -> None:
        # Só o preview; o botão NUNCA desabilita (mesmo valor => no-op no clique).
        preview_var.set(f"Cores: {current_option()}")

    def on_scale(value: str) -> None:
        # A NodeSlider já trava em nós e só dispara em mudança real de índice;
        # aqui apenas reflete o preview e habilita/desabilita o Aplicar.
        refresh_aplicar()

    slider_row = tk.Frame(root)
    slider_row.pack(fill="x", pady=(2, 0))
    scale = NodeSlider(slider_row, count=len(options), length=240,
                       command=on_scale)
    scale.pack(anchor="center")
    try:
        start_idx = slider_index_for(options, state.get("selected"))
        scale.set(start_idx)
        scale.set_applied(start_idx)
    except Exception:
        pass

    # Botão Aplicar: quadrado com ícone de raio (sem texto). Padding simétrico
    # => largura == altura por construção (~36px de lado).
    style.configure("Apply.TButton", padding=(4, 4))
    aplicar_row = tk.Frame(root)
    aplicar_row.pack(fill="x", pady=(2, 4))
    aplicar_btn = create_apply_button(aplicar_row, "Apply.TButton",
                                      lambda: apply_choice(current_option()))
    aplicar_btn.pack(anchor="center")
    refresh_aplicar()

    update_button = ttk.Button(top, text="", style="Update.TButton")
    update_button.place(relx=1.0, rely=0.5, anchor="e")
    update_button.place_forget()

    def show_update(version: str) -> None:
        update_button.configure(text=UPDATE_LABEL)
        update_button.place(relx=1.0, rely=0.5, anchor="e")

    def on_update_click():
        handle_update_click(
            state,
            destroy_fn=lambda: (root.destroy(), state.update(panel=None)),
            stop_fn=lambda: (state.get("icon").stop() if state.get("icon") else None),
            error_fn=lambda msg: messagebox.showerror("TurboCore", msg),
            set_busy=lambda busy: update_button.configure(
                state="disabled" if busy else "normal"))

    update_button.configure(command=on_update_click)

    # Lista direta, sem caixa: um Label por núcleo, linhas centralizadas.
    core_labels: list = []
    for _ in range(physical):
        label = tk.Label(root, text="", font=("Consolas", 10), anchor="center")
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
    activity.append("Painel aberto.", "vad_total")
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
        activity.begin("update:check", "Buscando updates")

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
            # Desfecho do update via botão verde: a thread de download deposita
            # state["update_settle"] e o tick (UI thread) executa em até 1s.
            # Sem nenhum chamado Tkinter a partir da worker (racy) o teardown
            # sempre roda: o PID morre e o updater relança o app.
            poll_update_settle(state)
            # O nó aplicado acompanha o aplicado (ex.: mudança pela tray); o
            # slider em si não é movido para não brigar com o arraste.
            # O botão nunca desabilita (mesmo valor => no-op no clique).
            try:
                applied_idx = slider_index_for(options, state.get("selected"))
                scale.set_applied(applied_idx)
            except Exception:
                pass
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
