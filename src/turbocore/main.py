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


def start_initial_power(state: dict, action: str, cores: int | None,
                        physical: int, logical: int) -> None:
    """Aplica a decisão inicial (apply/release) em thread de fundo.

    Vacina do startup lento: os 3 powercfg sequenciais (~200 ms, com picos de
    1,2 s) bloqueavam a criação da janela. A UI abre primeiro; o estado do
    sistema converge em seguida. O _WRITE_LOCK do power serializa com um
    clique no Aplicar/tray concorrente: o estado final é sempre o da última
    chamada. Falha vira aviso no stdout (mesmo comportamento de antes) e nunca
    mata o app — e, se o painel já estiver aberto, uma linha no log.
    """
    def work():
        try:
            if action == "apply":
                power.apply_selection(chosen_cores=cores, physical_cores=physical,
                                      logical_count=logical)
                state["selected"] = cores
            else:
                power.release_all_cores()
        except RuntimeError as e:
            # Sem privilegio p/ powercfg: abre o tray mesmo assim; usuario tenta de novo como admin.
            print(f"[TurboCore] aviso: nao apliquei limite inicial: {e}")
            _log_to_panel(state, f"Não apliquei o limite inicial: {e}")
        except Exception as e:  # a thread nunca pode morrer em silêncio
            print(f"[TurboCore] aviso: falha inesperada no limite inicial: {e}")
            _log_to_panel(state, f"Falha no limite inicial: {e}")

    threading.Thread(target=work, daemon=True).start()


def _log_to_panel(state: dict, message: str) -> None:
    """Aviso na caixa de log se o painel já existir; senão, só stdout."""
    log = state.get("log")
    if log is None:
        return
    try:
        log.append(message, "warning")
    except Exception:
        pass


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
    if argv and argv[0] == "--clock-worker":
        if len(argv) != 4:
            raise SystemExit(2)
        from turbocore.clock_broker import run_worker
        run_worker(int(argv[1]), argv[2], int(argv[3]))
        return
    if len(argv) == 2 and argv[0] == "--clock-report":
        from turbocore.hardware_clock import write_diagnostic_report
        write_diagnostic_report(argv[1])
        return
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
    start_initial_power(state, action, cores, physical, logical)
    panel_mod.start_auto_check(state)
    # Inicialização do monitor de hardware fora da thread da interface.
    panel_mod.start_monitor_prewarm()
    if open_panel:
        state["panel_request"].set()
    try:
        run_event_loop(state,
                       icon_fn=lambda: tray.run_tray(state, load_icon()),
                       panel_fn=lambda: panel_mod.run_panel(state),
                       popup_fn=lambda coords: tray.open_tray_popup(state, coords))
    finally:
        from turbocore.hardware_clock import reset
        reset()


if __name__ == "__main__":
    main()
