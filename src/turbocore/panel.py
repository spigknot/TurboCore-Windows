"""Painel visual do TurboCore (Tkinter): núcleos, monitor live, update, sobre.

Aberto pelo menu ("Abrir painel") ou clique-esquerdo na tray. Instância única
por processo (state["panel"]). O loop de refresh lê o state e todo acesso a
widget roda na UI thread via after().
"""
from __future__ import annotations

import threading
from pathlib import Path

from turbocore import __version__, updater_client
from turbocore.core_calc import build_core_options
from turbocore.pdh import FreqMonitor, aggregate_cores, format_core_row

# Verde idêntico ao botão de update do SIG (style "Update.TButton").
UPDATE_GREEN = "#16833a"
UPDATE_GREEN_ACTIVE = "#116b30"
UPDATE_GREEN_DISABLED = "#7ea98a"
REFRESH_MS = 1000


def sobre_texts() -> tuple[str, str, str]:
    return ("TurboCore", "Limitador de núcleos da CPU", f"Versão: {__version__}")


def cores_label(selected: int | None, physical: int) -> str:
    """Texto do botão de núcleos: 'Cores: X' (X = selecionado ou total livre)."""
    return f"Cores: {selected if selected is not None else physical}"


def poll_update_once(target: Path | str, fetcher=None) -> str | None:
    """Retorna a versão remota se houver update, senão None (nunca levanta)."""
    try:
        manifest = (fetcher or updater_client.fetch_sync_manifest)()
        status = updater_client.check_for_update(Path(target), manifest)
    except Exception:
        return None
    return status["remote"] if status["update"] else None


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
    """Verificação manual com trava de concorrência (espelha o SIG)."""

    def __init__(self):
        self.busy = False

    def start(self, target, on_done, fetcher=None) -> bool:
        """Retorna False se já houver verificação em andamento."""
        if self.busy:
            return False
        self.busy = True

        def work():
            try:
                manifest = (fetcher or updater_client.fetch_sync_manifest)()
                status = updater_client.check_for_update(Path(target), manifest)
                if status["update"]:
                    on_done("updated", status["remote"])
                else:
                    on_done("uptodate", None)
            except Exception as exc:
                on_done("error", str(exc))
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()
        return True


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
        from turbocore.icons import icon_candidates
        png = next(c for c in icon_candidates() if c.suffix.lower() == ".png" and c.exists())
        with Image.open(png) as source:
            source = source.convert("RGBA").resize((415, 415), Image.LANCZOS)
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
    root.geometry("360x640")
    root.resizable(False, False)
    state["panel"] = root
    _window_icon(root)

    style = ttk.Style(root)
    style.configure("Update.TButton", foreground="#ffffff", background=UPDATE_GREEN,
                    font=("Segoe UI Semibold", 10), padding=(12, 4))
    style.map("Update.TButton", background=[("active", UPDATE_GREEN_ACTIVE),
                                            ("disabled", UPDATE_GREEN_DISABLED)])

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
    drop = tk.Menu(nucleos_btn, tearoff=0)
    nucleos_btn.configure(menu=drop)
    for n in build_core_options(physical):
        drop.add_command(label=core_label(n), command=lambda n=n: apply_choice(n))

    update_button = ttk.Button(top, text="", style="Update.TButton")
    update_button.pack(side="right")
    update_button.pack_forget()

    def show_update(version: str) -> None:
        update_button.configure(text=f"Atualizar para {version}")
        update_button.pack(side="right")

    def on_update_click():
        updater_client.launch_updater(updater_client.install_dir())
        icon = state.get("icon")
        try:
            root.destroy()
        finally:
            state["panel"] = None
            if icon is not None:
                try:
                    icon.stop()
                except Exception:
                    pass

    update_button.configure(command=on_update_click)

    # Lista direta, sem caixa: um Label por núcleo, mesma margem da linha 1.
    core_labels: list = []
    for _ in range(physical):
        label = tk.Label(root, text="", font=("Consolas", 10), anchor="w")
        label.pack(fill="x", padx=10)
        core_labels.append(label)
    monitor = FreqMonitor(logical)

    # Linha final: Verificar Atualizações + Sobre (espelha o menu do SIG).
    checker = ManualCheck()
    bottom = tk.Frame(root)
    bottom.pack(side="bottom", fill="x", padx=10, pady=10)

    def on_manual_done(kind: str, payload) -> None:
        def ui():
            check_btn.configure(state="normal")
            if kind == "updated":
                state["pending_update"] = payload
                show_update(payload)
            elif kind == "uptodate":
                messagebox.showinfo("TurboCore", "O TurboCore já está atualizado.")
            else:
                messagebox.showerror("TurboCore", f"Não foi possível verificar: {payload}")
        try:
            root.after(0, ui)
        except Exception:
            pass

    def on_check_click():
        if not checker.start(updater_client.install_dir(), on_manual_done):
            messagebox.showinfo("TurboCore", "A verificação já está em andamento.")
            return
        check_btn.configure(state="disabled")

    check_btn = ttk.Button(bottom, text="Verificar Atualizações", command=on_check_click)
    check_btn.pack(side="left")
    ttk.Button(bottom, text="Sobre",
               command=lambda: open_sobre(root)).pack(side="left", padx=(8, 0))

    def tick():
        try:
            if not root.winfo_exists():
                return
        except Exception:
            return
        try:
            stats = monitor.read()
            for index, (freq, parked) in enumerate(aggregate_cores(stats, threads_per_core)):
                if index < len(core_labels):
                    core_labels[index].configure(text=format_core_row(index, freq, parked))
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
