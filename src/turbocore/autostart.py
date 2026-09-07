"""Iniciar no boot via HKCU\\...\\Run\\TurboCore (por usuario, sem admin)."""
from __future__ import annotations

import sys

REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TurboCore"


def _winreg():
    import winreg  # import tardio p/ testes mockarem sys.modules['winreg']
    return winreg


def get_startup_command() -> str:
    """Comando gravado no Run. Congelado (PyInstaller): o .exe; senão pythonw + main.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    import pathlib
    main_py = pathlib.Path(__file__).resolve().parent / "main.py"
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{main_py}"'


def is_enabled() -> bool:
    try:
        wr = _winreg()
        key = wr.OpenKey(wr.HKEY_CURRENT_USER, REG_SUBKEY, 0, wr.KEY_READ)
        try:
            wr.QueryValueEx(key, VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            wr.CloseKey(key)
    except Exception:
        return False


def set_enabled(on: bool) -> None:
    wr = _winreg()
    key = wr.OpenKey(wr.HKEY_CURRENT_USER, REG_SUBKEY, 0, wr.KEY_WRITE)
    try:
        if on:
            wr.SetValueEx(key, VALUE_NAME, 0, wr.REG_SZ, get_startup_command())
        else:
            try:
                wr.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        wr.CloseKey(key)
