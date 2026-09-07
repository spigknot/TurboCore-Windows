"""Backend de tray nativo Win32 + popup custom (textos centralizados, estreito).

O menu do pystray é nativo do Windows (HMENU): não permite centralizar texto
nem reduzir largura. Este backend desenha o ícone via Shell_NotifyIcon e abre
um popup Tk próprio no right-click, com a mesma ordem/itens do menu pystray.
Fallback: pystray (ver tray.run_tray).
"""
from __future__ import annotations

# Largura do popup = 67% da largura natural (33% mais estreito). O piso garante
# que o texto mais longo nunca clipa (texto + respiro mínimo).
POPUP_RATIO = 0.67
POPUP_MIN_PAD = 16
CHECK = "✓ "


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
    """Largura final: 67% da natural, com piso no texto + respiro."""
    return max(int(natural_px * POPUP_RATIO), longest_text_px + POPUP_MIN_PAD)


def natural_width(longest_text_px: int) -> int:
    """Largura que o menu nativo ocuparia (texto + coluna de check + margens)."""
    return longest_text_px + 56


def show_popup(state: dict, coords=None) -> None:
    """Abre o popup na thread da UI (chamado via run_event_loop)."""
    import tkinter as tk
    from turbocore import tray as tray_mod

    items = [it for it in popup_items(state) if not it.get("sep")]
    labels = [((CHECK if it["checked"] else "") + it["label"]) for it in items]

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
        import tkinter.font as tkfont
        font = ("Segoe UI", 10)
        try:
            longest = max(tkfont.Font(font=font).measure(t) for t in labels)
        except Exception:
            longest = max(len(t) for t in labels) * 8
        width = popup_width(natural_width(longest), longest)
        row_h = 24
        if coords:
            x, y = int(coords[0]) - width // 2, int(coords[1]) - len(labels) * row_h - 8
        else:
            x, y = 100, 100
        win = tk.Toplevel(owner)
        win.overrideredirect(True)
        win.configure(background="#999999")
        win.geometry(f"{width}x{len(labels) * row_h + 2}+{max(x, 0)}+{max(y, 0)}")
        win.attributes("-topmost", True)

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

        for item, text in zip(items, labels):
            lab = tk.Label(win, text=text, anchor="center", font=font,
                           background="#ffffff")
            lab.pack(fill="x")
            lab.bind("<Button-1>", lambda _e, item=item: choose(item))
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
