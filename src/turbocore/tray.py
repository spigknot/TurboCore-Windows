"""Tray pystray: menu, checks e callbacks. Sem logica de deteccao (vem do main)."""
from __future__ import annotations

import pystray
from PIL import Image

from turbocore import autostart, config, power


def core_label(n: int) -> str:
    return "1 Core" if n == 1 else f"{n} Cores"


def on_open_panel(state: dict) -> None:
    """Sinaliza a thread principal p/ abrir o painel (Tk só roda na main)."""
    event = state.get("panel_request")
    if event is not None:
        event.set()


def _close_panel(state: dict) -> None:
    panel = state.get("panel")
    state["panel"] = None
    if panel is not None:
        try:
            panel.destroy()
        except Exception:
            pass


def on_quit(state: dict, icon, _item=None) -> None:
    _close_panel(state)
    try:
        icon.stop()
    except Exception:
        pass


def on_pick_core(state: dict, n: int) -> None:
    power.apply_selection(chosen_cores=n, physical_cores=state["physical"],
                          logical_count=state["logical"])
    state["selected"] = n
    config.save_config({"remember": state["remember"], "cores": n})
    _refresh(state)


def on_toggle_remember(state: dict) -> None:
    state["remember"] = not state["remember"]
    config.save_config({"remember": state["remember"], "cores": state["selected"]})
    _refresh(state)


def on_toggle_boot(state: dict) -> None:
    autostart.set_enabled(not state["boot"])
    state["boot"] = autostart.is_enabled()
    _refresh(state)


def _refresh(state: dict) -> None:
    icon = state.get("icon")
    if icon is not None:
        icon.menu = build_menu(state)
        icon.update_menu()


def _pick_callback(state: dict, n: int):
    def pick(_icon, _item):
        on_pick_core(state, n)
    return pick


def _checked_picked(state: dict, n: int):
    def is_picked(_item):
        return state["selected"] == n
    return is_picked


def build_menu(state: dict):
    items = [
        pystray.MenuItem("Abrir painel", lambda *_a: on_open_panel(state), default=True),
        pystray.Menu.SEPARATOR,
    ]
    for n in state["options"]:
        items.append(pystray.MenuItem(
            core_label(n), _pick_callback(state, n),
            checked=_checked_picked(state, n)))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(
        "Lembrar escolha", lambda *_a: on_toggle_remember(state),
        checked=lambda _item: state["remember"]))
    items.append(pystray.MenuItem(
        "Iniciar no boot", lambda *_a: on_toggle_boot(state),
        checked=lambda _item: state["boot"]))
    items.append(pystray.MenuItem("Sair", lambda icon, _item: on_quit(state, icon)))
    return pystray.Menu(*items)


def run_tray(state: dict, icon_image: Image.Image) -> None:
    icon = pystray.Icon("TurboCore", icon_image, "TurboCore", menu=build_menu(state))
    state["icon"] = icon
    icon.run()
