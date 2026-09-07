"""Monitor por núcleo: PDH via ctypes + fallback WMI/powershell."""
import sys

import pytest

from turbocore import pdh


def test_aggregate_threads_em_cores():
    stats = [(3000, False), (3100, False),  # core 0
             (0, True), (0, True)]          # core 1 parked
    out = pdh.aggregate_cores(stats, threads_per_core=2)
    assert out == [(3100, False), (0, True)]


def test_aggregate_sem_ht():
    stats = [(2500, False), (0, True)]
    assert pdh.aggregate_cores(stats, threads_per_core=1) == stats


def test_format_row():
    assert pdh.format_core_row(0, 3450, False) == "Core  0   3450 MHz"
    assert "estacionado" in pdh.format_core_row(1, 0, True)


@pytest.mark.skipif(sys.platform != "win32", reason="contadores do Windows")
def test_live_retorna_linhas_validas():
    from turbocore import cpu_info
    logical = cpu_info.get_logical_count()
    mon = pdh.FreqMonitor(logical)
    try:
        stats = mon.read()
    finally:
        mon.close()
    assert len(stats) == logical
    assert all(freq >= 0 for freq, _ in stats)
    assert max(freq for freq, _ in stats) > 0, "frequência zerada = leitura quebrada"
    assert all(isinstance(parked, bool) for _, parked in stats)
