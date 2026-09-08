"""Backend de tray nativo Win32 + popup custom (textos centralizados, estreito).

O menu do pystray é nativo do Windows (HMENU): não permite centralizar texto
nem reduzir largura. Este backend desenha o ícone via Shell_NotifyIcon e abre
um popup Tk próprio no right-click, com a mesma ordem/itens do menu pystray.
Fallback: pystray (ver tray.run_tray).
"""
from __future__ import annotations

# Largura do popup = 67% da largura natural (33% mais estreito). O piso é
# estrutural: texto mais longo + coluna do check + respiro à direita — o
# texto ("Lembrar escolha") nunca clipa, sem folga exagerada.
POPUP_RATIO = 0.67
POPUP_TEXT_PAD = 8
CHECK = "✓"
# Coluna de check com largura FIXA (px): o texto nunca se desloca, com ou sem ✓.
CHECK_COL_PX = 24
ROW_H = 24
ROW_BG = "#ffffff"
ROW_HOVER_BG = "#e5f1fb"
# Contorno do menu como um todo (borda de 1px ao redor do popup) + traço
# fino separando cada item.
MENU_BORDER = "#9e9e9e"
MENU_SEP = "#e0e0e0"
MENU_SEP_H = 1
MENU_BORDER_PX = 1


def available() -> bool:
    try:
        import win32gui  # noqa: F401
        return True
    except Exception:
        return False


def popup_items(state: dict) -> list:
    """Itens do popup na MESMA ordem do menu pystray (ver tray.build_menu).

    Cada item: {"key", "label", "checked"} ou {"sep": True}.
    """
    items = [{"key": "panel", "label": "Abrir painel", "checked": False},
             {"sep": True}]
    for n in state["options"]:
        label = "1 Core" if n == 1 else f"{n} Cores"
        items.append({"key": ("core", n), "label": label,
                      "checked": state.get("selected") == n})
    items.append({"sep": True})
    items.append({"key": "remember", "label": "Lembrar escolha",
                  "checked": bool(state.get("remember"))})
    items.append({"key": "boot", "label": "Iniciar no boot",
                  "checked": bool(state.get("boot"))})
    items.append({"key": "quit", "label": "Sair", "checked": False})
    return items


def popup_width(natural_px: int, longest_text_px: int) -> int:
    """Largura final: 67% da natural, com piso no texto + check + respiro."""
    floor = longest_text_px + CHECK_COL_PX + POPUP_TEXT_PAD
    return max(int(natural_px * POPUP_RATIO), floor)


def natural_width(longest_text_px: int) -> int:
    """Largura que o menu nativo ocuparia (texto + coluna de check + margens)."""
    return longest_text_px + 56


def _build_popup_window(owner, items, coords=None):
    """Monta o Toplevel do popup; retorna (win, rows).

    Extraída de show_popup para teste: cada linha é um Frame de altura fixa
    (ROW_H) com 2 colunas — check de largura FIXA à esquerda + texto
    centralizado. O ✓ nunca empurra o texto. Hover sombreia a linha.
    Contorno: o Toplevel usa MENU_BORDER como fundo e um corpo interno com
    padx/pady de MENU_BORDER_PX forma a borda de 1px ao redor do menu.
    Entre cada item há um traço fino (MENU_SEP, altura MENU_SEP_H).
    rows: [(frame, check_label, text_label, item)].
    Os separadores ficam em win._tc_seps; o corpo interno em win._tc_body.
    """
    import tkinter as tk
    import tkinter.font as tkfont

    font = ("Segoe UI", 10)
    labels = [it["label"] for it in items]
    try:
        longest = max(tkfont.Font(font=font).measure(t) for t in labels)
    except Exception:
        longest = max(len(t) for t in labels) * 8
    width = popup_width(natural_width(longest), longest)
    total_h = (len(labels) * ROW_H
               + max(len(labels) - 1, 0) * MENU_SEP_H
               + MENU_BORDER_PX * 2)
    if coords:
        x, y = int(coords[0]) - width // 2, int(coords[1]) - total_h - 8
    else:
        x, y = 100, 100
    win = tk.Toplevel(owner)
    win.overrideredirect(True)
    win.configure(background=MENU_BORDER)
    win.geometry(f"{width + MENU_BORDER_PX * 2}x{total_h}+{max(x, 0)}+{max(y, 0)}")
    win.attributes("-topmost", True)
    body = tk.Frame(win, background=ROW_BG)
    body.pack(fill="both", expand=True,
              padx=MENU_BORDER_PX, pady=MENU_BORDER_PX)

    rows = []
    seps = []
    for idx, item in enumerate(items):
        if idx > 0:
            sep = tk.Frame(body, background=MENU_SEP, height=MENU_SEP_H)
            sep.pack(fill="x")
            sep.pack_propagate(False)
            seps.append(sep)
        frame = tk.Frame(body, background=ROW_BG, height=ROW_H)
        frame.pack(fill="x")
        frame.pack_propagate(False)
        frame.grid_propagate(False)  # o grid interno não pode encolher a linha
        frame.grid_columnconfigure(0, minsize=CHECK_COL_PX)
        frame.grid_columnconfigure(1, weight=1)
        check = tk.Label(frame, text=CHECK if item["checked"] else "",
                         anchor="center", font=font, background=ROW_BG)
        check.grid(row=0, column=0, sticky="ns")
        text = tk.Label(frame, text=item["label"], anchor="center", font=font,
                        background=ROW_BG)
        text.grid(row=0, column=1, sticky="nsew")

        def hover_on(_event, f=frame, c=check, t=text):
            for w in (f, c, t):
                try:
                    w.configure(background=ROW_HOVER_BG)
                except Exception:
                    pass

        def hover_off(event, f=frame, c=check, t=text):
            # Enter/Leave disparam ao transitar entre as 2 colunas da mesma
            # linha: só apaga quando o ponteiro saiu da linha de verdade.
            try:
                under = event.widget.winfo_containing(event.x_root, event.y_root)
                node = under
                while node is not None and node is not f:
                    node = node.master
                if node is f:
                    return
            except Exception:
                pass
            for w in (f, c, t):
                try:
                    w.configure(background=ROW_BG)
                except Exception:
                    pass

        for widget in (frame, check, text):
            widget.bind("<Enter>", hover_on)
            widget.bind("<Leave>", hover_off)
        rows.append((frame, check, text, item))
    win._tc_body = body
    win._tc_seps = seps
    return win, rows


def show_popup(state: dict, coords=None) -> None:
    """Abre o popup na thread da UI (chamado via run_event_loop)."""
    import tkinter as tk
    from turbocore import tray as tray_mod

    items = [it for it in popup_items(state) if not it.get("sep")]

    panel_root = state.get("panel")
    owner = None
    try:
        if panel_root is not None and panel_root.winfo_exists():
            owner = panel_root
    except Exception:
        owner = None
    own_root = False
    if owner is None:
        owner = tk.Tk()
        owner.withdraw()
        own_root = True
    try:
        win, rows = _build_popup_window(owner, items, coords)

        def close():
            try:
                win.destroy()
            except Exception:
                pass

        def choose(item):
            close()
            key = item["key"]
            if key == "panel":
                tray_mod.on_open_panel(state)
            elif key == "quit":
                tray_mod.on_quit(state, state.get("icon"))
            elif key == "remember":
                tray_mod.on_toggle_remember(state)
            elif key == "boot":
                tray_mod.on_toggle_boot(state)
            elif isinstance(key, tuple) and key[0] == "core":
                tray_mod.on_pick_core(state, key[1])

        for frame, _check, _text, item in rows:
            for widget in (frame, frame.winfo_children()[0], frame.winfo_children()[1]):
                widget.bind("<Button-1>", lambda _e, item=item: choose(item), add="+")
        win.bind("<FocusOut>", lambda _e: close())
        win.bind("<Escape>", lambda _e: close())
        try:
            win.focus_force()
        except Exception:
            pass
        owner.wait_window(win)
    finally:
        if own_root:
            try:
                owner.destroy()
            except Exception:
                pass


class Win32TrayIcon:
    """Ícone da tray via Shell_NotifyIcon (thread da tray)."""

    def __init__(self, state: dict):
        import win32api
        import win32con
        import win32gui
        self._win32gui = win32gui
        self._win32con = win32con
        self._state = state
        self._stop = False
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "TurboCoreTray"
        wc.lpfnWndProc = self._wndproc
        self._atom = win32gui.RegisterClass(wc)
        self._hwnd = win32gui.CreateWindow(self._atom, "TurboCore", 0, 0, 0, 0, 0,
                                           0, 0, wc.hInstance, None)
        self._cb_msg = win32gui.RegisterWindowMessage("TurboCoreTrayCallback")
        hicon = self._load_icon()
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self._hwnd, 0, flags, self._cb_msg, hicon, "TurboCore")
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
        self._nid = nid

    def _load_icon(self):
        from turbocore.icons import icon_candidates
        for cand in icon_candidates():
            if cand.suffix.lower() == ".ico" and cand.exists():
                try:
                    return self._win32gui.LoadImage(
                        0, str(cand), self._win32con.IMAGE_ICON, 0, 0,
                        self._win32con.LR_LOADFROMFILE)
                except Exception:
                    pass
        return None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == self._cb_msg:
            if lparam == 0x0205:  # WM_RBUTTONUP: popup custom na UI thread
                try:
                    import win32api
                    x, y = win32api.GetCursorPos()
                    self._state["tray_popup_at"] = (x, y)
                    ev = self._state.get("tray_popup_request")
                    if ev is not None:
                        ev.set()
                except Exception:
                    pass
            elif lparam == 0x0202:  # WM_LBUTTONUP: abre o painel
                try:
                    from turbocore import tray as tray_mod
                    tray_mod.on_open_panel(self._state)
                except Exception:
                    pass
        return self._win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def run(self) -> None:
        import win32gui
        win32gui.PumpMessages()

    def stop(self) -> None:
        import win32gui
        self._stop = True
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self._nid)
        except Exception:
            pass
        try:
            win32gui.PostMessage(self._hwnd, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass


def run(state: dict) -> None:
    icon = Win32TrayIcon(state)
    state["icon"] = icon
    icon.run()
