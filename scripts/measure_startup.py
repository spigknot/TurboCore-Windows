"""Decompoe o startup: quanto custa cada etapa sincrona do main() antes da janela.
Uso: python scripts/measure_startup.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

marks = []
def mark(label):
    marks.append((label, time.perf_counter()))
    if len(marks) > 1:
        dt = marks[-1][1] - marks[-2][1]
        print(f"  {dt*1000:7.1f} ms  {label}", flush=True)
    else:
        print(f"  {'—':>7}  {label} (t0)", flush=True)

t_import0 = time.perf_counter()
mark("interprete pronto, comecando imports")
import turbocore.cpu_info as cpu_info
mark("import cpu_info")
import turbocore.config as config
mark("import config")
import turbocore.autostart as autostart
mark("import autostart")
import turbocore.power as power
mark("import power")
import turbocore.tray as tray
mark("import tray (pystray!)")
import turbocore.icons as icons
mark("import icons (PIL)")
import turbocore.panel as panel_mod
mark("import panel (+updater_client, nodeslider, pdh)")
from turbocore.core_calc import build_core_options
mark("import core_calc")
print(f"imports totais: {(marks[-1][1]-t_import0)*1000:.0f} ms\n")

print("--- etapas sincronas do main() ---")
mark("inicio main")
physical = cpu_info.get_physical_cores()
mark(f"get_physical_cores -> {physical}")
logical = cpu_info.get_logical_count()
mark(f"get_logical_count -> {logical}")
cfg = config.load_config()
mark(f"load_config -> {cfg}")
options = build_core_options(physical)
mark(f"build_core_options ({len(options)} opcoes)")
boot = autostart.is_enabled()
mark(f"autostart.is_enabled -> {boot}")
migrated = autostart.migrate()
mark(f"autostart.migrate -> {migrated}")
t = time.perf_counter()
try:
    power.release_all_cores()
    mark("power.release_all_cores (3x powercfg)")
except Exception as exc:
    mark(f"power.release_all_cores ERRO: {exc}")
t = time.perf_counter()
img = icons.load_icon()
mark(f"icons.load_icon -> {type(img).__name__} {getattr(img, 'size', '?')}")
t = time.perf_counter()
import tkinter as tk
mark("import tkinter")
root = tk.Tk()
mark("tk.Tk() (criacao da 1a janela)")
root.withdraw()
root.destroy()
mark("withdraw+destroy (limpeza)")

total = marks[-1][1] - marks[0][1]
print(f"\nTOTAL ate janela Tk pronta: {total:.2f}s")
print("(falta: tray_win32 import win32gui + Shell_NotifyIcon + open_panel ~280ms + PDH settle 250ms)")
