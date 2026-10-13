"""Mede o tempo ATE O USUARIO VER a lista: janela aberta -> 1o label com MHz.

Instrumentacao roda dentro da UI thread (root.after), como no app real.
`--load` usa N PROCESSOS girando (carga nativa: nenhum GIL compartilhado com
quem mede — threads Python no mesmo processo distorcem o resultado).

Cenarios (espelham o app):
  default       app ja rodando (prewarm feito) e usuario abre o painel
  --immediate   painel aberto no mesmo instante do start do app
  --no-prewarm  sem prewarm (pior caso: provider frio na 1a leitura)

Antes (PowerShell/WMI): 3,32 s ocioso; nao completou em 40 s sob carga.
Uso: python scripts/measure_panel_open2.py [--load] [--immediate|--no-prewarm]
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from turbocore import cpu_info
from turbocore import panel as panel_mod
from turbocore.clock_table import ClockTable

LOAD = "--load" in sys.argv
IMMEDIATE = "--immediate" in sys.argv
NO_PREWARM = "--no-prewarm" in sys.argv
TIMEOUT = 30.0


def start_native_load(threads: int):
    code = "while True: pass\n"
    return [subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x00000008)  # DETACHED_PROCESS
            for _ in range(threads)]


def stop_load(procs):
    for proc in procs:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> None:
    physical = cpu_info.get_physical_cores()
    logical = cpu_info.get_logical_count()
    procs = []
    if LOAD:
        print(f"carga nativa: {logical} processos girando...", flush=True)
        procs = start_native_load(logical)
        time.sleep(4.0)

    if not NO_PREWARM:
        panel_mod.start_monitor_prewarm()  # igual ao main() do app
        if not IMMEDIATE:
            time.sleep(1.0)  # app rodando ha um tempo antes de abrir o painel

    state = {"physical": physical, "logical": logical, "selected": None,
             "panel": None, "log": None, "pending_update": None}

    marks: dict = {}
    started = time.perf_counter()
    root = panel_mod.open_panel(state)
    marks["open_panel_s"] = time.perf_counter() - started

    def first_row_text():
        for widget in root.winfo_children():
            if isinstance(widget, ClockTable):
                text = widget.itemcget(widget._rows[0][1], "text")
                if text != "—":
                    return f"Core 0: {text} MHz"
        return None

    def poll():
        if "first_label_s" in marks:
            return
        text = first_row_text()
        if text is not None:
            marks["first_label_s"] = time.perf_counter() - started
            marks["first_label_txt"] = text
            root.after(50, root.destroy)
            return
        if time.perf_counter() - started > TIMEOUT:
            root.after(50, root.destroy)
            return
        root.after(20, poll)

    root.after(20, poll)
    root.mainloop()
    stop_load(procs)

    cenario = ("imediato" if IMMEDIATE else "app rodando") if not NO_PREWARM \
        else "sem prewarm"
    print(f"logicos={logical} fisicos={physical} cenario={cenario} "
          f"carga={'SIM' if LOAD else 'nao'}")
    print(f"open_panel() retornou em        {marks['open_panel_s']*1000:.0f} ms")
    if "first_label_s" in marks:
        print(f"1a linha 'Core .. MHz' visivel  {marks['first_label_s']*1000:.0f} ms "
              f"-> {marks['first_label_txt']!r}")
    else:
        print(f"NAO preencheu em {TIMEOUT:.0f}s")


if __name__ == "__main__":
    main()
