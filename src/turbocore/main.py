"""Entrada do app: deteccao -> decisao inicial -> tray (+painel na main thread)."""
from __future__ import annotations

import threading

from turbocore import autostart, config, cpu_info, power, tray
from turbocore.core_calc import build_core_options
from turbocore.icons import load_icon
from turbocore import panel as panel_mod


def decide_initial_action(physical: int, cfg: dict) -> tuple[str, int | None]:
    """('apply', cores) se remember+valor valido e dentro das opcoes; senão ('release', None)."""
    cores = cfg.get("cores")
    if cfg.get("remember") and isinstance(cores, int) and cores in build_core_options(physical):
        return ("apply", cores)
    return ("release", None)


def run_event_loop(state: dict, icon_fn, panel_fn, poll_timeout: float = 0.2) -> None:
    """Tray numa thread, painel Tk na main thread. Sai quando o ícone parar."""

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


def main() -> None:
    physical = cpu_info.get_physical_cores()
    logical = cpu_info.get_logical_count()
    cfg = config.load_config()
    options = build_core_options(physical)
    state = {"physical": physical, "logical": logical,
             "options": options,
             "selected": cfg.get("cores") if cfg.get("cores") in options else None,
             "remember": bool(cfg.get("remember")),
             "boot": autostart.is_enabled(),
             "icon": None, "panel": None, "pending_update": None,
             "panel_request": threading.Event(), "stopped": threading.Event()}
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
    panel_mod.start_auto_check(
        state, notify=lambda version: tray._notify(
            state, f"Atualização {version} disponível — abra o painel."))
    run_event_loop(state,
                   icon_fn=lambda: tray.run_tray(state, load_icon()),
                   panel_fn=lambda: panel_mod.run_panel(state))


if __name__ == "__main__":
    main()
