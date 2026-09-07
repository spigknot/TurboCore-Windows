"""Envelopa powercfg. Ordem SEMPRE: setacvalueindex -> setactive."""
from __future__ import annotations

import subprocess

from .core_calc import parse_powercfg_ac_hex, percent_for_cores


def _decode(data) -> str:
    """Decodifica saida de console Windows (PT-BR pode nao ser UTF-8)."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"falhou {' '.join(cmd)}: {_decode(p.stderr).strip()[:300]}")


def apply_percent(percent: int) -> None:
    """Aplica X% e reativa o esquema. percent 1..100."""
    if not (1 <= int(percent) <= 100):
        raise ValueError("percent deve estar em 1..100")
    _run(["powercfg", "-setacvalueindex", "scheme_current",
          "sub_processor", "CPMAXCORES", str(int(percent))])
    _run(["powercfg", "-setactive", "scheme_current"])


def apply_core_limit(chosen_cores: int, physical_cores: int) -> int:
    """Converte cores->% (ceil) e aplica. Retorna o % aplicado."""
    pct = percent_for_cores(chosen_cores, physical_cores)
    apply_percent(pct)
    return pct


def release_all_cores() -> None:
    """Libera explicitamente tudo: CPMAXCORES 100 + setactive (requisito Lembrar=OFF)."""
    apply_percent(100)


def query_current_percent() -> int:
    """Le o CPMAXCORES atual via /qh e converte o HEX p/ decimal. Opcional (diagnostico)."""
    p = subprocess.run(
        ["powercfg", "/qh", "SCHEME_CURRENT", "SUB_PROCESSOR", "CPMAXCORES"],
        capture_output=True,
        timeout=30,
    )
    if p.returncode != 0:
        raise RuntimeError(f"query falhou: {_decode(p.stderr).strip()[:200]}")
    return parse_powercfg_ac_hex(_decode(p.stdout))
