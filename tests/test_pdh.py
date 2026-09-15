"""Monitor por núcleo: PDH via ctypes (in-process), sem fallback.

Vacina do painel lento: a lista de núcleos levava ~3,3 s para aparecer porque
cada leitura era um `powershell.exe` novo + consulta WMI (~2,2 s ocioso,
4,0-5,6 s com a CPU ocupada). Estes testes travam o caminho novo: sem
processo externo e leitura em milissegundos.
"""
import sys
import time

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


def test_placeholder_antes_da_primeira_leitura():
    """A lista nasce com placeholder — nunca vazia esperando leitura."""
    assert pdh.format_core_row(0, None) == "Core  0  lendo..."
    assert pdh.format_core_row(17, None) == "Core 17  lendo..."


def test_efetivo_desconta_ociosidade():
    # 3774 MHz a 46% de uso -> 1736 MHz efetivos (definição do HWiNFO)
    assert pdh.effective_mhz(3774, 54) == 1736
    assert pdh.effective_mhz(2301, 100) == 0
    assert pdh.effective_mhz(3800, 0) == 3800


def test_ordena_instancias_numericamente_e_ignora_totais():
    """Ordem 0,1,...,0,10 (numérica, não alfabética) e sem "_Total"/"0,_Total"."""
    names = ["0,10", "0,2", "_Total", "0,_Total", "0,1"]
    assert pdh.order_logical_instances(names, 3) == ["0,1", "0,2", "0,10"]
    assert pdh.order_logical_instances(names, 99) == ["0,1", "0,2", "0,10"]


def test_ordena_limita_ao_numero_de_logicos():
    names = [f"0,{i}" for i in range(36)]
    ordered = pdh.order_logical_instances(names, 18)
    assert len(ordered) == 18 and ordered[-1] == "0,17"


def test_series_efetivas_por_instancia():
    freqs = {"0,0": 3800.0, "0,1": 2000.0, "0,2": 3000.0}
    idles = {"0,0": 0.0, "0,1": 50.0}  # "0,2" sem idle => 100 (totalmente ocioso)
    assert pdh.effective_series(freqs, idles, 3) == [3800, 1000, 0]


def test_monitor_sem_caminho_wmi():
    """Sem fallback: o caminho PowerShell/WMI não existe mais no módulo."""
    assert not hasattr(pdh, "read_logical_stats")
    assert "subprocess" not in dir(pdh)


def test_reset_descarta_a_query_compartilhada():
    """Uma leitura que falha não pode deixar a query quebrada no processo."""
    class FakeQuery:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeQuery()
    original = pdh._query
    pdh._query = fake
    try:
        pdh.reset()
        assert fake.closed is True
        assert pdh._query is None
    finally:
        pdh._query = original


@pytest.mark.skipif(sys.platform != "win32", reason="contadores do Windows")
def test_live_retorna_linhas_validas():
    from turbocore import cpu_info
    logical = cpu_info.get_logical_count()
    mon = pdh.FreqMonitor(logical)
    try:
        stats = mon.read()
        stats = mon.read()  # 2ª leitura: janela cheia do contador de delta
    finally:
        mon.close()
    assert len(stats) == logical
    assert max(stats) > 0, "efetivo zerado = leitura quebrada"


@pytest.mark.skipif(sys.platform != "win32", reason="contadores do Windows")
def test_live_nao_dispara_processo_externo(monkeypatch):
    """Vacina: a leitura não pode voltar a spawnar PowerShell."""
    import subprocess
    from turbocore import cpu_info

    def boom(*_args, **_kwargs):
        raise AssertionError("o monitor spawnou processo externo")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    mon = pdh.FreqMonitor(cpu_info.get_logical_count())
    try:
        assert len(mon.read()) == cpu_info.get_logical_count()
    finally:
        mon.close()


@pytest.mark.skipif(sys.platform != "win32", reason="contadores do Windows")
def test_live_leitura_rapida():
    """Regressão do atraso: 5 leituras somam menos de 1 s (era 2,2 s CADA)."""
    from turbocore import cpu_info
    logical = cpu_info.get_logical_count()
    mon = pdh.FreqMonitor(logical)
    try:
        mon.read()  # 1ª leitura aquece a janela do contador
        started = time.perf_counter()
        for _ in range(5):
            stats = mon.read()
        elapsed = time.perf_counter() - started
    finally:
        mon.close()
    assert len(stats) == logical
    assert elapsed < 1.0, f"5 leituras levaram {elapsed:.2f}s (limite 1s)"


@pytest.mark.skipif(sys.platform != "win32", reason="contadores do Windows")
def test_prewarm_paga_o_setup_do_provider():
    """prewarm() deixa a query pronta: a leitura seguinte é imediata."""
    pdh.reset()
    started = time.perf_counter()
    pdh.prewarm()
    setup = time.perf_counter() - started
    from turbocore import cpu_info
    mon = pdh.FreqMonitor(cpu_info.get_logical_count())
    try:
        started = time.perf_counter()
        mon.read()
        first = time.perf_counter() - started
    finally:
        mon.close()
    assert setup < 5.0, f"setup do provider levou {setup:.2f}s"
    assert first < 0.3, f"1ª leitura pós-prewarm levou {first:.2f}s"
