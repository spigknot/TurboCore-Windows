"""Entrada do app: deteccao -> decisao inicial -> tray (+painel na main thread)."""
from __future__ import annotations

import sys
import threading

from turbocore import autostart, config, cpu_info, power, tray
from turbocore.core_calc import build_core_options
from turbocore.icons import load_icon
from turbocore import panel as panel_mod

# Flag do updater ao relançar o app novo: abre o painel p/ conferir a versão.
POST_UPDATE_FLAG = "--post-update"


def decide_initial_action(physical: int, cfg: dict) -> tuple[str, int | None]:
    """('apply', cores) se remember+valor valido e dentro das opcoes; senão ('release', None)."""
    cores = cfg.get("cores")
    if cfg.get("remember") and isinstance(cores, int) and cores in build_core_options(physical):
        return ("apply", cores)
    return ("release", None)


def decide_panel_at_start(argv: list[str], migrated_boot: bool) -> tuple[bool, bool]:
    """(abrir_painel, pos_update).

    Manual ou pós-update -> painel junto da tray. Boot (--tray ou entrada
    antiga do Run migrada agora) -> silencioso, só tray.
    """
    silent = autostart.SILENT_FLAG in argv or migrated_boot
    post = POST_UPDATE_FLAG in argv
    return (post or not silent), post


def run_event_loop(state: dict, icon_fn, panel_fn, popup_fn=None,
                   poll_timeout: float = 0.2) -> None:
    """Tray numa thread, painel Tk na main thread. Sai quando o ícone parar.

    popup_fn(coords) abre o popup custom da tray (backend win32) na main thread
    quando tray_popup_request dispara; None = backend pystray (menu nativo).
    """

    def boot():
        try:
            icon_fn()
        finally:
            state["stopped"].set()

    threading.Thread(target=boot, daemon=True).start()
    while not state["stopped"].is_set():
        if state["panel_request"].wait(timeout=poll_timeout):
            state["panel_request"].clear()
            if not state["stopped"].is_set():
                panel_fn()
        popup_ev = state.get("tray_popup_request")
        if popup_fn is not None and popup_ev is not None and popup_ev.is_set():
            popup_ev.clear()
            if not state["stopped"].is_set():
                popup_fn(state.get("tray_popup_at"))


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    physical = cpu_info.get_physical_cores()
    logical = cpu_info.get_logical_count()
    cfg = config.load_config()
    options = build_core_options(physical)
    state = {"physical": physical, "logical": logical,
             "options": options,
             "selected": cfg.get("cores") if cfg.get("cores") in options else None,
             "remember": bool(cfg.get("remember")),
             "boot": autostart.is_enabled(),
             "icon": None, "panel": None, "log": None, "pending_update": None,
             "post_update": False,
             "panel_request": threading.Event(), "stopped": threading.Event(),
             "tray_popup_request": threading.Event(), "tray_popup_at": None}
    open_panel, post_update = decide_panel_at_start(list(argv), autostart.migrate())
    state["post_update"] = post_update
    action, cores = decide_initial_action(physical, cfg)
    try:
        if action == "apply":
            power.apply_selection(chosen_cores=cores, physical_cores=physical,
                                  logical_count=logical)
            state["selected"] = cores
        else:
            power.release_all_cores()  # Lembrar=OFF (ou sem valor): libera explicitamente com 100
    except RuntimeError as e:
        # Sem privilegio p/ powercfg: abre o tray mesmo assim; usuario tenta de novo como admin.
        print(f"[TurboCore] aviso: nao apliquei limite inicial: {e}")
    panel_mod.start_auto_check(state)
    if open_panel:
        state["panel_request"].set()
    run_event_loop(state,
                   icon_fn=lambda: tray.run_tray(state, load_icon()),
                   panel_fn=lambda: panel_mod.run_panel(state),
                   popup_fn=lambda coords: tray.open_tray_popup(state, coords))


if __name__ == "__main__":
    main()
