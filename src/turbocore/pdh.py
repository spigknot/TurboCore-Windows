"""Frequência efetiva + parking por processador lógico.

Fonte: WMI `Win32_PerfFormattedData_Counters_ProcessorInformation` via
powershell sem janela (provado ao vivo: 2301 MHz; o contador PDH
`Processor Frequency` retorna 0 nesta máquina, por isso NÃO é usado).
"""
from __future__ import annotations

import os
import re
import subprocess


def aggregate_cores(stats: list[tuple[int, bool]], threads_per_core: int) -> list[tuple[int, bool]]:
    """Agrega threads lógicas em núcleos físicos: freq = max, parked = todos."""
    if threads_per_core < 1:
        raise ValueError("threads_per_core deve ser >= 1")
    out = []
    for base in range(0, len(stats), threads_per_core):
        group = stats[base:base + threads_per_core]
        out.append((max(freq for freq, _ in group), all(parked for _, parked in group)))
    return out


def format_core_row(index: int, freq_mhz: int, parked: bool) -> str:
    row = f"Core {index:2d}  {freq_mhz:5d} MHz"
    return row + ("  (estacionado)" if parked else "")


def read_logical_stats(logical: int) -> list[tuple[int, bool]]:
    """[(freq_mhz, parked)] por processador lógico, na ordem 0..L-1."""
    ps = ("Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
          " | Select-Object Name,ProcessorFrequency,ParkingStatus | Format-List")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                         capture_output=True, timeout=30,
                         **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                            if os.name == "nt" else {}))
    text = out.stdout.decode("utf-8", errors="replace") if isinstance(out.stdout, bytes) else ""
    freqs: dict[str, int] = {}
    for name, value in re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ProcessorFrequency\s*:\s*(\d+)", text):
        freqs.setdefault(name, int(value))
    parks: dict[str, int] = {}
    for name, value in re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ParkingStatus\s*:\s*(\d+)", text):
        parks.setdefault(name, int(value))

    def key(name: str):
        parts = name.split(",")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return (0, int(parts[0]), int(parts[1]))
        return (1, 0, 0)

    ordered = sorted([n for n in freqs if n in parks and "," in n], key=key)[:logical]
    return [(int(freqs[n]), bool(parks[n])) for n in ordered]


class FreqMonitor:
    """Leitura periódica; read() -> [(freq_mhz, parked)] por processador lógico."""

    def __init__(self, logical: int):
        self.logical = logical

    def read(self) -> list[tuple[int, bool]]:
        stats = read_logical_stats(self.logical)
        if len(stats) != self.logical:
            raise OSError(f"WMI retornou {len(stats)} linhas, esperado {self.logical}")
        return stats

    def close(self) -> None:
        pass
