"""Prova funcional do EXE congelado: config remember+10 -> EXE deve aplicar 56 sozinho."""
import json
import os
import subprocess
import sys
import time

EXE = "D:/Projetos/TurboCore/dist/TurboCore/TurboCore.exe"
CFG = os.path.join(os.environ["APPDATA"], "TurboCore", "config.json")

sys.path.insert(0, "D:/Projetos/TurboCore/src")
from turbocore.core_calc import parse_powercfg_ac_hex  # noqa: E402
from turbocore.power import query_current_percent, release_all_cores  # noqa: E402


def query_min():
    import subprocess
    p = subprocess.run(
        ["powercfg", "/QH", "SCHEME_CURRENT", "SUB_PROCESSOR", "CPMINCORES"],
        capture_output=True, timeout=30,
    )
    out = p.stdout.decode("utf-8", errors="replace")
    return parse_powercfg_ac_hex(out)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    return p.returncode


# estado inicial conhecido: 100 + config remember/10
release_all_cores()
os.makedirs(os.path.dirname(CFG), exist_ok=True)
had_cfg = os.path.exists(CFG)
old_cfg = open(CFG, encoding="utf-8").read() if had_cfg else None
with open(CFG, "w", encoding="utf-8") as f:
    json.dump({"remember": True, "cores": 10}, f)
print("seed: AC =", query_current_percent())

proc = subprocess.Popen([EXE])
time.sleep(12)
val_max = query_current_percent()
val_min = query_min()
print("MIN apos EXE =", val_min, "| MAX apos EXE =", val_max)
proc.terminate()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()
    print("precisou matar a forca")

# restaura maquina ao estado anterior
release_all_cores()
if had_cfg:
    with open(CFG, "w", encoding="utf-8") as f:
        f.write(old_cfg)
elif os.path.exists(CFG):
    os.remove(CFG)
print("restaurado: MIN =", query_min(), "MAX =", query_current_percent())
assert (val_min, val_max) == (3, 56), f"EXE nao aplicou min+max: {(val_min, val_max)}"
print("EXE_FUNCIONAL_OK")
