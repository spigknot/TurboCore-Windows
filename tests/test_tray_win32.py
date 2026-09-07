"""Backend win32 da tray: mesma ordem do pystray, popup estreito centralizado."""
import sys

import pytest

from turbocore import tray_win32 as w32


def _state():
    return {"physical": 18, "logical": 36,
            "options": [1, 2, 4, 6, 8, 10, 12, 14, 16, 18],
            "selected": 10, "remember": True, "boot": False}


def test_popup_ordem_igual_pystray():
    items = w32.popup_items(_state())
    labels = ["SEP" if it.get("sep") else it["label"] for it in items]
    assert labels[0] == "Abrir painel"
    assert labels[2] == "1 Core"
    assert labels[11] == "18 Cores"
    assert labels[-1] == "Sair"
    assert labels[-2] == "Iniciar no boot"
    assert labels[-3] == "Lembrar escolha"


def test_popup_checks_espelham_state():
    items = {it["label"]: it.get("checked") for it in w32.popup_items(_state())
             if not it.get("sep")}
    assert items["10 Cores"] is True
    assert items["8 Cores"] is False
    assert items["Lembrar escolha"] is True
    assert items["Iniciar no boot"] is False


def test_popup_33_por_cento_mais_estreito():
    assert w32.popup_width(300, 100) == 201
    assert w32.popup_width(150, 100) == 116  # piso: texto + respiro


def test_popup_piso_nunca_clipa_texto():
    assert w32.popup_width(100, 200) == 216


@pytest.mark.skipif(sys.platform != "win32", reason="popup Tk no Windows")
def test_show_popup_centralizado_e_estreito(tk_root):
    import tkinter as tk
    import tkinter.font as tkfont
    state = _state()
    state["panel"] = tk_root  # popup usa o root existente como dono
    opened = []
    real_toplevel = tk.Toplevel

    class SpyTop(real_toplevel):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)

    tk.Toplevel = SpyTop
    medida = {}
    try:
        def auto():
            # roda na UI thread: mede e fecha
            win = opened[0]
            win.update_idletasks()
            labels = [c for c in win.winfo_children() if c.winfo_class() == "Label"]
            medida["anchors"] = {l.cget("anchor") for l in labels}
            medida["texts"] = [l.cget("text") for l in labels]
            medida["width"] = win.winfo_width()
            win.destroy()
        tk_root.after(800, auto)
        w32.show_popup(state, coords=(500, 500))
        font = tkfont.Font(font=("Segoe UI", 10))
        medida["longest"] = max(font.measure(t) for t in medida["texts"])
    finally:
        tk.Toplevel = real_toplevel
    assert opened, "popup não abriu"
    assert medida["texts"], "sem linhas no popup"
    assert medida["anchors"] == {"center"}
    esperado = w32.popup_width(w32.natural_width(medida["longest"]), medida["longest"])
    assert abs(medida["width"] - esperado) <= 4, (medida["width"], esperado)
