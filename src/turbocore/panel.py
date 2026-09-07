"""Painel visual do TurboCore (Tkinter): lista de núcleos, monitor live, update.

Aberto pelo menu ("Abrir painel") ou clique-esquerdo na tray. Instância única
por processo (state["panel"]). O loop de refresh lê o state (thread-safe p/
leitura de strs/ints) e todo acesso a widget roda na UI thread via after().
"""
from __future__ import annotations

import threading
from pathlib import Path

from turbocore import __version__, updater_client
from turbocore.core_calc import build_core_options, percent_for_cores
from turbocore.pdh import FreqMonitor, aggregate_cores, format_core_row

# Verde idêntico ao botão de update do SIG (style "Update.TButton").
UPDATE_GREEN = "#16833a"
UPDATE_GREEN_ACTIVE = "#116b30"
UPDATE_GREEN_DISABLED = "#7ea98a"
REFRESH_MS = 1000


def format_status(selected: int | None, physical: int, max_pct: int | None = None) -> str:
    if selected is None:
        return "Sem limite (todos os núcleos liberados)"
    label = "1 Core" if selected == 1 else f"{selected} Cores"
    return f"Limite: {label} ({max_pct}%) — mín 1 thread"


def poll_update_once(target: Path | str, fetcher=None) -> str | None:
    """Retorna a versão remota se houver update, senão None (nunca levanta)."""
    try:
        manifest = (fetcher or updater_client.fetch_sync_manifest)()
        status = updater_client.check_for_update(Path(target), manifest)
    except Exception:
        return None
    return status["remote"] if status["update"] else None


def start_auto_check(state: dict, notify=None) -> None:
    """Checagem automática em thread (padrão SIG: verifica sozinho no boot)."""
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


def _apply_choice(state: dict, refresh_status, n: int) -> None:
    from turbocore import tray as tray_mod  # tardio: tray importa este módulo
    tray_mod.on_pick_core(state, n)
    refresh_status()


def open_panel(state: dict):
    """Abre (ou foca) o painel. Retorna a janela Tk."""
    import tkinter as tk
    from tkinter import ttk

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
    root.geometry("360x560")
    root.resizable(False, False)
    state["panel"] = root

    style = ttk.Style(root)
    style.configure("Update.TButton", foreground="#ffffff", background=UPDATE_GREEN,
                    font=("Segoe UI Semibold", 10), padding=(12, 4))
    style.map("Update.TButton", background=[("active", UPDATE_GREEN_ACTIVE),
                                            ("disabled", UPDATE_GREEN_DISABLED)])

    tk.Label(root, text=f"TurboCore {__version__}",
             font=("Segoe UI Semibold", 12)).pack(pady=(10, 0))
    status_var = tk.StringVar()

    def refresh_status():
        selected = state.get("selected")
        pct = percent_for_cores(selected, physical) if selected else None
        status_var.set(format_status(selected, physical, pct))

    refresh_status()
    tk.Label(root, textvariable=status_var, font=("Segoe UI", 10)).pack(pady=(0, 6))

    def open_chooser():
        from turbocore.tray import core_label
        top = tk.Toplevel(root)
        top.title("Núcleos")
        top.geometry("220x320")
        top.transient(root)
        box = tk.Listbox(top, font=("Segoe UI", 11), height=12)
        options = build_core_options(physical)
        for n in options:
            box.insert("end", core_label(n))
        box.pack(fill="both", expand=True, padx=8, pady=8)

        def on_select(_event=None):
            if not box.curselection():
                return
            _apply_choice(state, refresh_status, options[box.curselection()[0]])
            top.destroy()

        box.bind("<<ListboxSelect>>", on_select)

    ttk.Button(root, text="Núcleos…", command=open_chooser).pack(pady=4)

    tk.Label(root, text="Núcleos (tempo real)", font=("Segoe UI Semibold", 10)).pack(pady=(8, 0))
    monitor_box = tk.Listbox(root, font=("Consolas", 10), height=12, width=34)
    monitor_box.pack(padx=10, pady=4)
    monitor = FreqMonitor(logical)

    update_frame = ttk.Frame(root)
    update_button = ttk.Button(update_frame, text="", style="Update.TButton")

    def on_update_click():
        updater_client.launch_updater(updater_client.install_dir())
        icon = state.get("icon")
        try:
            root.destroy()
        finally:
            if icon is not None:
                try:
                    icon.stop()
                except Exception:
                    pass

    update_button.configure(command=on_update_click)

    def tick():
        try:
            if not root.winfo_exists():
                return
        except Exception:
            return
        try:
            stats = monitor.read()
            rows = aggregate_cores(stats, threads_per_core)
            monitor_box.delete(0, "end")
            for index, (freq, parked) in enumerate(rows):
                monitor_box.insert("end", format_core_row(index, freq, parked))
            pending = state.get("pending_update")
            if pending and not update_frame.winfo_ismapped():
                update_button.configure(text=f"Atualizar para {pending}")
                update_frame.pack(pady=6)
            refresh_status()
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
        update_button.configure(text=f"Atualizar para {pending}")
        update_frame.pack(pady=6)
    root.after(REFRESH_MS, tick)
    return root


def run_panel(state: dict) -> None:
    """Abre o painel e entra no mainloop (chamado fora da thread do pystray)."""
    root = open_panel(state)
    try:
        root.mainloop()
    finally:
        state["panel"] = None
