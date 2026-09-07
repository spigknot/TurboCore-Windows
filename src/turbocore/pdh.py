"""Frequência efetiva + parking por processador lógico (PDH via ctypes).

Primário: PDH `PdhAddEnglishCounterW` (nomes em inglês, sem locale) com uma
query aberta entre leituras — sem spawn de processo. Fallback: uma consulta
WMI via powershell (CREATE_NO_WINDOW) se o PDH não entregar nada.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess

PDH_FMT_LONG = 0x00000100


class _PDHValue(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_long), ("longValue", ctypes.c_long),
                ("doubleValue", ctypes.c_double), ("largeValue", ctypes.c_int64),
                ("AnsiStringValue", ctypes.c_char_p), ("WideStringValue", ctypes.c_wchar_p)]


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


def _powershell_stats(logical: int) -> list[tuple[int, bool]]:
    ps = ("Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
          " | Select-Object Name,ProcessorFrequency,ParkingStatus | Format-List")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                         capture_output=True, timeout=30,
                         **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                            if os.name == "nt" else {}))
    text = out.stdout.decode("utf-8", errors="replace") if isinstance(out.stdout, bytes) else ""
    freqs: dict[str, int] = dict(re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ProcessorFrequency\s*:\s*(\d+)", text))
    parks: dict[str, int] = {k: int(v) for k, v in
                             re.findall(r"Name\s*:\s*(\S+)[\s\S]*?ParkingStatus\s*:\s*(\d+)", text)}
    # ordena por (grupo, indice): "0,12" -> (0, 12); "_Total" por ultimo
    def key(name: str):
        parts = name.split(",")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return (0, int(parts[0]), int(parts[1]))
        return (1, 0, 0)
    ordered = sorted([n for n in freqs if n in parks and "," in n], key=key)[:logical]
    return [(int(freqs[n]), bool(parks[n])) for n in ordered]


class FreqMonitor:
    """Query PDH persistente; read() -> [(freq_mhz, parked)] por processador lógico."""

    def __init__(self, logical: int):
        self.logical = logical
        self._pdh = None
        self._query = None
        self._counters: list = []
        self._use_pdh = False
        if os.name == "nt":
            try:
                self._open_pdh()
            except Exception:
                self.close()

    def _open_pdh(self) -> None:
        pdh = ctypes.WinDLL("pdh.dll")
        query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
            raise OSError("PdhOpenQueryW falhou")
        counters = []
        try:
            for index in range(self.logical):
                for counter, storage in (
                        (rf"\Processor Information(0,{index})\Processor Frequency", "freq"),
                        (rf"\Processor Information(0,{index})\Parking Status", "park")):
                    handle = ctypes.c_void_p()
                    if pdh.PdhAddEnglishCounterW(query, counter, 0, ctypes.byref(handle)) != 0:
                        raise OSError(f"contador inexistente: {counter}")
                    counters.append((storage, handle))
            if pdh.PdhCollectQueryData(query) != 0:
                raise OSError("PdhCollectQueryData falhou")
        except Exception:
            pdh.PdhCloseQuery(query)
            raise
        self._pdh, self._query, self._counters = pdh, query, counters
        self._use_pdh = True

    def read(self) -> list[tuple[int, bool]]:
        if self._use_pdh:
            try:
                return self._read_pdh()
            except Exception:
                self.close()
        return _powershell_stats(self.logical)

    def _read_pdh(self) -> list[tuple[int, bool]]:
        if self._pdh.PdhCollectQueryData(self._query) != 0:
            raise OSError("PdhCollectQueryData falhou")
        values = []
        for _, handle in self._counters:
            value = _PDHValue()
            if self._pdh.PdhGetFormattedCounterValue(handle, PDH_FMT_LONG, None,
                                                    ctypes.byref(value)) != 0:
                raise OSError("PdhGetFormattedCounterValue falhou")
            values.append(value.longValue)
        freqs = values[0::2]
        parks = values[1::2]
        if len(freqs) != self.logical:
            raise OSError("nº de contadores divergente")
        return [(max(int(f), 0), bool(p)) for f, p in zip(freqs, parks)]

    def close(self) -> None:
        self._use_pdh = False
        if self._pdh is not None and self._query is not None:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
        self._pdh, self._query, self._counters = None, None, []
