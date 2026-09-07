"""Fixture Tk compartilhada: o Python deste ambiente só cria UM Tk() por processo.

Testes que precisam de widgets Tk reais DEVEM usar `tk_root` (session-scoped)
em vez de `tk.Tk()` próprio — o 2º/3º Tk() na mesma sessão levanta TclError
(tk.tcl capado no runtime). A root é withdraw e destruída no fim da sessão.
"""
import pytest


@pytest.fixture(scope="session")
def tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception as exc:
        pytest.skip(f"Tk indisponível: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass
