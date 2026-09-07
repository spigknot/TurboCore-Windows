"""Clock EFETIVO por processador lógico (definição do HWiNFO).

efetivo = ActualFrequency × (100 − PercentIdleTime) / 100, via WMI
(Win32_PerfFormattedData_Counters_ProcessorInformation, sem janela).

NÃO usar ProcessorFrequency (nominal fixo) nem ActualFrequency puro (P-state
sem descontar ociosidade — foi o erro que divergiu do HWiNFO).
"""
from __future__ import annotations

import os
import re
import subprocess


def effective_mhz(actual_mhz: int, idle_pct: int) -> int:
    busy = max(0, min(100, 100 - idle_pct))
    return round(actual_mhz * busy / 100)


def aggregate_cores(effective: list[int], threads_per_core: int) -> list[int]:
    """Agrega threads lógicas em núcleos físicos: efetivo = max."""
    if threads_per_core < 1:
        raise ValueError("threads_per_core deve ser >= 1")
    return [max(effective[base:base + threads_per_core])
            for base in range(0, len(effective), threads_per_core)]


def format_core_row(index: int, mhz: int) -> str:
    return f"Core {index:2d}  {mhz:5d} MHz"


def read_logical_stats(logical: int) -> list[int]:
    """[MHz efetivos] por processador lógico, ordem 0..L-1."""
    ps = ("Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
          " | Select-Object Name,ActualFrequency,PercentIdleTime | Format-List")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                         capture_output=True, timeout=60,
                         **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                            if os.name == "nt" else {}))
    text = out.stdout.decode("utf-8", errors="replace") if isinstance(out.stdout, bytes) else ""
    freqs: dict[str, int] = {}
    for name, value in re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ActualFrequency\s*:\s*(\d+)", text):
        freqs.setdefault(name, int(value))
    idles: dict[str, int] = {}
    for name, value in re.findall(r"Name\s*:\s*(\S+)[\s\S]*?PercentIdleTime\s*:\s*(\d+)", text):
        idles.setdefault(name, int(value))

    def key(name: str):
        parts = name.split(",")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return (0, int(parts[0]), int(parts[1]))
        return (1, 0, 0)

    ordered = sorted([n for n in freqs if "," in n], key=key)[:logical]
    return [effective_mhz(int(freqs[n]), int(idles.get(n, 100))) for n in ordered]


class FreqMonitor:
    """Leitura periódica; read() -> [MHz efetivos] por processador lógico."""

    def __init__(self, logical: int):
        self.logical = logical

    def read(self) -> list[int]:
        stats = read_logical_stats(self.logical)
        if len(stats) != self.logical:
            raise OSError(f"WMI retornou {len(stats)} linhas, esperado {self.logical}")
        return stats

    def close(self) -> None:
        pass
