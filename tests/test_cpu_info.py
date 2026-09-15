"""Topologia da CPU sem subprocesso: GetLogicalProcessorInformation (ctypes).

Vacina do startup lento: get_physical_cores + get_logical_count eram 2x
`powershell.exe` (~6,7 s) e bloqueavam a janela do app. Estes testes travam o
caminho novo: sem processo externo e leitura em milissegundos.
"""
import sys
from unittest.mock import patch

import pytest

from turbocore import cpu_info


def _entry(relationship: int, mask: int = 1) -> bytes:
    return (mask.to_bytes(8, "little") + relationship.to_bytes(4, "little")
            + bytes(20))


def test_conta_so_nucleos_e_ignora_outros_tipos():
    raw = (_entry(0) * 2 + _entry(3) + _entry(2) + _entry(0) + _entry(1))
    assert cpu_info._count_cores(raw) == 3


def test_buffer_inconsistente_degrada():
    assert cpu_info._count_cores(b"") is None
    assert cpu_info._count_cores(b"\x00" * 31) is None  # não-múltiplo de 32
    assert cpu_info._count_cores(_entry(3) * 2) is None  # zero núcleos


def test_topologia_usa_nativo_quando_disponivel():
    cpu_info.reset()
    try:
        with patch.object(cpu_info, "_native_core_count", return_value=18), \
                patch("os.cpu_count", return_value=36):
            assert cpu_info.get_physical_cores() == 18
            assert cpu_info.get_logical_count() == 36
    finally:
        cpu_info.reset()


def test_fallback_sem_api_nativa():
    cpu_info.reset()
    try:
        with patch.object(cpu_info, "_native_core_count", return_value=None), \
                patch("os.cpu_count", return_value=36):
            assert cpu_info.get_logical_count() == 36
            # sem a API, fisicos degradam para o logico (seguro: % correto p/ 100%)
            assert cpu_info.get_physical_cores() == 36
    finally:
        cpu_info.reset()


def test_topologia_com_cache_unica_chamada_nativa():
    cpu_info.reset()
    try:
        with patch.object(cpu_info, "_native_core_count", return_value=8) as nat, \
                patch("os.cpu_count", return_value=16):
            assert cpu_info.get_physical_cores() == 8
            assert cpu_info.get_logical_count() == 16
            assert cpu_info.get_physical_cores() == 8
            assert nat.call_count == 1
    finally:
        cpu_info.reset()


def test_sem_subprocesso():
    """Vacina: a detecção nunca mais spawna powershell."""
    import subprocess
    cpu_info.reset()
    try:
        def boom(*_args, **_kwargs):
            raise AssertionError("cpu_info spawnou processo externo")

        with patch.object(subprocess, "run", side_effect=boom), \
                patch.object(subprocess, "Popen", side_effect=boom):
            assert cpu_info.get_physical_cores() >= 1
            assert cpu_info.get_logical_count() >= 1
    finally:
        cpu_info.reset()


@pytest.mark.skipif(sys.platform != "win32", reason="API nativa do Windows")
def test_live_topologia_correta_e_rapida():
    """Regressão do startup: topologia real em <1 s (era ~6,7 s de PowerShell)."""
    import os
    import time
    cpu_info.reset()
    try:
        started = time.perf_counter()
        physical = cpu_info.get_physical_cores()
        logical = cpu_info.get_logical_count()
        elapsed = time.perf_counter() - started
    finally:
        cpu_info.reset()
    assert physical >= 1
    assert logical == (os.cpu_count() or 1)
    assert logical >= physical
    assert elapsed < 1.0, f"topologia levou {elapsed:.2f}s (limite 1s)"
