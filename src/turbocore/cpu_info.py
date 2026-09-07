"""Deteccao de nucleos fisicos/logicos no Windows via WMI (CIM)."""
from __future__ import annotations

import os
import re
import subprocess


def _powershell_cim() -> str:
    """Retorna texto bruto de NumberOfCores/NumberOfLogicalProcessors (um bloco por socket)."""
    ps = (
        "Get-CimInstance Win32_Processor | "
        "Select-Object NumberOfCores,NumberOfLogicalProcessors | Format-List"
    )
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"powershell CIM falhou: {out.stderr.strip()[:200]}")
    return out.stdout


def _sum_field(text: str, field: str) -> int:
    vals = [int(v) for v in re.findall(rf"{field}\s*:\s*(\d+)", text)]
    return sum(vals)


def get_physical_cores() -> int:
    """Fisicos (soma sockets). Fallback: os.cpu_count() se WMI falhar."""
    try:
        total = _sum_field(_powershell_cim(), "NumberOfCores")
        if total > 0:
            return total
    except Exception:
        pass
    return os.cpu_count() or 1


def get_logical_count() -> int:
    """Logicos. Fallback: os.cpu_count()."""
    try:
        total = _sum_field(_powershell_cim(), "NumberOfLogicalProcessors")
        if total > 0:
            return total
    except Exception:
        pass
    return os.cpu_count() or 1
