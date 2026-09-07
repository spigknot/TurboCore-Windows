"""Envelopa powercfg. Ordem SEMPRE: set MIN -> set MAX -> setactive."""
from __future__ import annotations

import os
import subprocess

from turbocore.core_calc import min_percent_for_one_thread, parse_powercfg_ac_hex, percent_for_cores

if os.name == "nt":
    _NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
else:
    _NO_WINDOW = {}


def _decode(data) -> str:
    """Decodifica saida de console Windows (PT-BR pode nao ser UTF-8)."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, timeout=60, **_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(f"falhou {' '.join(cmd)}: {_decode(p.stderr).strip()[:300]}")


def _setParking(setting: str, percent: int) -> None:
    if not (1 <= int(percent) <= 100):
        raise ValueError(f"{setting} deve estar em 1..100")
    _run(["powercfg", "-setacvalueindex", "scheme_current",
          "sub_processor", setting, str(int(percent))])


def apply_selection(chosen_cores: int, physical_cores: int, logical_count: int) -> tuple[int, int]:
    """Aplica min=1 thread + max=escolha, depois reativa. Retorna (min_pct, max_pct).

    O minimo em 1 thread e obrigatorio: com CPMINCORES em 100% o algoritmo de
    parking fica desabilitado e o maximo sozinho nao tem efeito.
    """
    min_pct = min_percent_for_one_thread(logical_count)
    max_pct = percent_for_cores(chosen_cores, physical_cores)
    _setParking("CPMINCORES", min_pct)
    _setParking("CPMAXCORES", max_pct)
    _run(["powercfg", "-setactive", "scheme_current"])
    return (min_pct, max_pct)


def release_all_cores() -> None:
    """Libera explicitamente tudo: MIN 100 + MAX 100 + setactive."""
    _setParking("CPMINCORES", 100)
    _setParking("CPMAXCORES", 100)
    _run(["powercfg", "-setactive", "scheme_current"])


def query_current_percent() -> int:
    """Le o CPMAXCORES atual via /qh e converte o HEX p/ decimal. Opcional (diagnostico)."""
    p = subprocess.run(
        ["powercfg", "/qh", "SCHEME_CURRENT", "SUB_PROCESSOR", "CPMAXCORES"],
        capture_output=True,
        timeout=30,
        **_NO_WINDOW,
    )
    if p.returncode != 0:
        raise RuntimeError(f"query falhou: {_decode(p.stderr).strip()[:200]}")
    return parse_powercfg_ac_hex(_decode(p.stdout))
