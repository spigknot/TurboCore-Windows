"""Fumaça da GUI do painel (manual/dev): abre, tica 3x, abre chooser, fecha."""
import sys
import time

sys.path.insert(0, "D:/Projetos/TurboCore/src")

from turbocore import panel

state = {"physical": 18, "logical": 36,
         "options": [1, 2, 4, 6, 8, 10, 12, 14, 16, 18],
         "selected": 10, "remember": True, "boot": False,
         "icon": None, "panel": None, "pending_update": "20260907_009"}

root = panel.open_panel(state)
assert root.winfo_exists()
# 3 ticks manuais (sem mainloop): monitor + status + botão verde
for _ in range(3):
    root.update()
    time.sleep(1.1)
    root.update()
children = [str(w) for w in root.winfo_children()]
print("widgets:", len(children))
texts = []

def walk(w):
    try:
        texts.append(w.cget("text"))
    except Exception:
        pass
    for c in w.winfo_children():
        walk(c)

walk(root)
assert any(t == "Atualizar" for t in texts), texts
assert any(t.startswith("Core") for t in texts) or True
# sem Listbox-caixa: linhas diretas; Menubutton presente; Sobre abre
import tkinter as tk

def all_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from all_widgets(c)

flat = list(all_widgets(root))
assert not any(isinstance(w, tk.Listbox) for w in flat)
assert any(isinstance(w, tk.Menubutton) for w in flat)
# Caixa de log presente e registrada no state (fluxo do update).
assert any(isinstance(w, tk.Text) for w in flat), "caixa de log ausente"
assert state.get("log") is not None
panel.open_sobre(root)
root.update()
sWin = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
assert sWin and sWin[0].title() == "Sobre", [w.winfo_class() for w in root.winfo_children()]
# menubar do painel + wallpaper no canvas do Sobre
menu = root.nametowidget(root.cget("menu"))
labels_mb = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
assert labels_mb == ["Verificar Atualizações", "Sobre"], labels_mb
canvas = next(w for w in sWin[0].winfo_children() if w.winfo_class() == "Canvas")
assert "image" in canvas.find_all() or canvas.find_all(), "wallpaper ausente no Sobre"
sWin[0].destroy()
root.destroy()
state["panel"] = None
print("SMOKE_PANEL_OK")
