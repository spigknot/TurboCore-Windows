"""Monitor por núcleo: PDH via ctypes + fallback WMI/powershell."""
import sys

import pytest

from turbocore import pdh


def test_aggregate_threads_em_cores():
    stats = [3000, 3100, 0, 0]
    assert pdh.aggregate_cores(stats, threads_per_core=2) == [3100, 0]


def test_aggregate_sem_ht():
    assert pdh.aggregate_cores([2500, 0], threads_per_core=1) == [2500, 0]


def test_format_row():
    assert pdh.format_core_row(0, 3732) == "Core  0   3732 MHz"
    assert pdh.format_core_row(17, 1) == "Core 17      1 MHz"


def test_efetivo_desconta_ociosidade():
    # 3774 MHz a 46% de uso -> 1736 MHz efetivos (definição do HWiNFO)
    assert pdh.effective_mhz(3774, 54) == 1736
    assert pdh.effective_mhz(2301, 100) == 0
    assert pdh.effective_mhz(3800, 0) == 3800


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
    assert max(stats) > 0, "efetivo zerado = leitura quebrada"
