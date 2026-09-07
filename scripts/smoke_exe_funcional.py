"""Prova funcional do EXE congelado: config remember+10 -> EXE deve aplicar 56 sozinho."""
import json
import os
import subprocess
import sys
import time

EXE = "D:/Projetos/TurboCore/dist/TurboCore/TurboCore.exe"
CFG = os.path.join(os.environ["APPDATA"], "TurboCore", "config.json")

sys.path.insert(0, "D:/Projetos/TurboCore/src")
from turbocore.power import apply_percent, query_current_percent  # noqa: E402


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    return p.returncode


# estado inicial conhecido: 100 + config remember/10
apply_percent(100)
os.makedirs(os.path.dirname(CFG), exist_ok=True)
had_cfg = os.path.exists(CFG)
old_cfg = open(CFG, encoding="utf-8").read() if had_cfg else None
with open(CFG, "w", encoding="utf-8") as f:
    json.dump({"remember": True, "cores": 10}, f)
print("seed: AC =", query_current_percent())

proc = subprocess.Popen([EXE])
time.sleep(12)
val = query_current_percent()
print("AC apos EXE =", val)
proc.terminate()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()
    print("precisou matar a forca")

# restaura maquina ao estado anterior
apply_percent(100)
if had_cfg:
    with open(CFG, "w", encoding="utf-8") as f:
        f.write(old_cfg)
elif os.path.exists(CFG):
    os.remove(CFG)
print("restaurado: AC =", query_current_percent())
assert val == 56, f"EXE nao aplicou o salvo: AC={val}"
print("EXE_FUNCIONAL_OK")
