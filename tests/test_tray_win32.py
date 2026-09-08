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
    assert w32.popup_width(150, 100) == 132  # piso: texto + check + respiro


def test_popup_piso_nunca_clipa_texto():
    assert w32.popup_width(100, 200) == 232


def test_popup_piso_cabe_lembrar_escolha(tk_root):
    """Vacina do print: 'Lembrar escolha' clipava ('Lembrar escol...')."""
    import tkinter.font as tkfont
    font = tkfont.Font(font=("Segoe UI", 10))
    longest = font.measure("Lembrar escolha")
    width = w32.popup_width(w32.natural_width(longest), longest)
    assert width >= longest + w32.CHECK_COL_PX + w32.POPUP_TEXT_PAD
    assert width - (longest + w32.CHECK_COL_PX) <= 12, width  # sem exagero


@pytest.mark.skipif(sys.platform != "win32", reason="popup Tk no Windows")
def test_popup_check_coluna_fixa_texto_nao_desloca(tk_root):
    """O ✓ mora em coluna de largura fixa: o texto fica no mesmo x/largura."""
    state = _state()
    items = [it for it in w32.popup_items(state) if not it.get("sep")]
    assert any(it["checked"] for it in items) and any(not it["checked"] for it in items)
    win, rows = w32._build_popup_window(tk_root, items, coords=(500, 500))
    try:
        win.deiconify()
        win.update()
        posicoes = {(t.winfo_x(), t.winfo_width()) for _, _, t, _ in rows}
        assert len(posicoes) == 1, posicoes
        for _f, _c, t, _it in rows:
            assert t.cget("anchor") == "center"
        for f, _c, _t, _it in rows:
            assert f.winfo_reqheight() == w32.ROW_H
    finally:
        win.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="popup Tk no Windows")
def test_popup_sem_faixa_cinza(tk_root):
    """Janela e linhas brancas, altura exata (nada de fundo aparecendo)."""
    state = _state()
    items = [it for it in w32.popup_items(state) if not it.get("sep")]
    win, rows = w32._build_popup_window(tk_root, items, coords=(500, 500))
    try:
        win.update_idletasks()
        assert str(win.cget("background")).lower() == "#ffffff"
        assert win.winfo_reqheight() == len(rows) * w32.ROW_H
        for f, c, t, _it in rows:
            for w in (f, c, t):
                assert str(w.cget("background")).lower() == "#ffffff"
    finally:
        win.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="popup Tk no Windows")
def test_popup_hover_sombreia_linha(tk_root):
    """Enter sombreia a linha inteira; Leave (fora dela) restaura o branco."""
    state = _state()
    items = [it for it in w32.popup_items(state) if not it.get("sep")]
    win, rows = w32._build_popup_window(tk_root, items, coords=(500, 500))
    try:
        win.deiconify()
        win.update()
        f, c, t, _it = rows[0]
        assert f.bind("<Enter>") != "" and f.bind("<Leave>") != ""
        f.event_generate("<Enter>")
        tk_root.update()
        assert str(t.cget("background")).lower() == w32.ROW_HOVER_BG.lower()
        assert str(c.cget("background")).lower() == w32.ROW_HOVER_BG.lower()
        assert str(f.cget("background")).lower() == w32.ROW_HOVER_BG.lower()
        f.event_generate("<Leave>")
        tk_root.update()
        assert str(t.cget("background")).lower() == "#ffffff"
        assert str(f.cget("background")).lower() == "#ffffff"
    finally:
        win.destroy()


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
            def all_labels(w):
                for c in w.winfo_children():
                    if c.winfo_class() == "Label":
                        yield c
                    yield from all_labels(c)
            labels = list(all_labels(win))
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
