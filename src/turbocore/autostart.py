"""Iniciar no boot via HKCU\\...\\Run\\TurboCore (por usuario, sem admin)."""
from __future__ import annotations

import sys

REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TurboCore"
# Flag gravada no comando do Run: boot abre silencioso, só na tray.
SILENT_FLAG = "--tray"


def _winreg():
    import winreg  # import tardio p/ testes mockarem sys.modules['winreg']
    return winreg


def get_startup_command() -> str:
    """Comando gravado no Run. Congelado (PyInstaller): o .exe; senão pythonw + main.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {SILENT_FLAG}'
    import pathlib
    main_py = pathlib.Path(__file__).resolve().parent / "main.py"
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{main_py}" {SILENT_FLAG}'


def _read_value():
    try:
        wr = _winreg()
        key = wr.OpenKey(wr.HKEY_CURRENT_USER, REG_SUBKEY, 0, wr.KEY_READ)
        try:
            value, _kind = wr.QueryValueEx(key, VALUE_NAME)
            return value
        except FileNotFoundError:
            return None
        finally:
            wr.CloseKey(key)
    except Exception:
        return None


def is_enabled() -> bool:
    return _read_value() is not None


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


def migrate() -> bool:
    """Migra entrada antiga do Run (sem --tray) para o comando atual.

    Retorna True se migrou — ou seja, este processo provavelmente foi lançado
    pelo boot com o comando antigo (abrir silencioso).
    """
    try:
        current = _read_value()
    except Exception:
        return False
    if current is None or SILENT_FLAG in str(current):
        return False
    try:
        set_enabled(True)
    except Exception:
        return False
    return True
