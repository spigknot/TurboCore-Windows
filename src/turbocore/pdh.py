"""Frequência efetiva + uso + parking por processador lógico (WMI).

Propriedades REAIS da classe Win32_PerfFormattedData_Counters_ProcessorInformation:
- ActualFrequency: MHz efetivos AGORA (com turbo). NÃO usar ProcessorFrequency
  (é o nominal fixo, ex. 2301 — foi esse erro que zerou/viciou o monitor).
- PercentIdleTime: 100 - idle = uso %.
- ParkingStatus: 0 desperto, != 0 estacionado.
"""
from __future__ import annotations

import os
import re
import subprocess


def aggregate_cores(stats: list[tuple[int, int, bool]],
                    threads_per_core: int) -> list[tuple[int, int, bool]]:
    """Agrega threads em núcleos: freq = max, uso = max, parked = todos."""
    if threads_per_core < 1:
        raise ValueError("threads_per_core deve ser >= 1")
    out = []
    for base in range(0, len(stats), threads_per_core):
        group = stats[base:base + threads_per_core]
        out.append((max(freq for freq, _, _ in group),
                    max(busy for _, busy, _ in group),
                    all(parked for _, _, parked in group)))
    return out


def format_core_row(index: int, freq_mhz: int, busy_pct: int, parked: bool) -> str:
    row = f"Core {index:2d}  {freq_mhz:5d} MHz  {busy_pct:3d}%"
    return row + ("  (estacionado)" if parked else "")


def read_logical_stats(logical: int) -> list[tuple[int, int, bool]]:
    """[(freq_mhz, uso_pct, parked)] por processador lógico, ordem 0..L-1."""
    ps = ("Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
          " | Select-Object Name,ActualFrequency,PercentIdleTime,ParkingStatus | Format-List")
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
    parks: dict[str, int] = {}
    for name, value in re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ParkingStatus\s*:\s*(\d+)", text):
        parks.setdefault(name, int(value))

    def key(name: str):
        parts = name.split(",")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return (0, int(parts[0]), int(parts[1]))
        return (1, 0, 0)

    ordered = sorted([n for n in freqs if n in parks and "," in n], key=key)[:logical]
    return [(int(freqs[n]), max(0, min(100, 100 - int(idles.get(n, 100)))), bool(parks[n]))
            for n in ordered]


class FreqMonitor:
    """Leitura periódica; read() -> [(freq_mhz, uso_pct, parked)] por lógico."""

    def __init__(self, logical: int):
        self.logical = logical

    def read(self) -> list[tuple[int, int, bool]]:
        stats = read_logical_stats(self.logical)
        if len(stats) != self.logical:
            raise OSError(f"WMI retornou {len(stats)} linhas, esperado {self.logical}")
        return stats

    def close(self) -> None:
        pass
