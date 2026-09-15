"""Topologia da CPU sem subprocesso: GetLogicalProcessorInformation (ctypes).

fisicos = nº de entradas RelationProcessorCore; logicos = os.cpu_count().
Custo ~0,01 ms: o caminho anterior (2x `powershell.exe` + CIM, ~6,7 s no
startup) era o maior custo da abertura do app — a janela esperava 3,8 s +
2,9 s antes de existir. Sem fallback lento: fora do Windows ou sem a API, os
fisicos degradam para o logico (os.cpu_count, instantaneo; seguro: % de 100%).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import threading

_RELATION_PROCESSOR_CORE = 0
# x64: ProcessorMask (u64) + Relationship (u32) + union (16B) = 32B.
_ENTRY_BYTES = 32
_REL_OFFSET = 8

_cache: dict = {}
_cache_lock = threading.RLock()
_kernel32_holder: dict = {}


def _kernel32():
    """kernel32 com a assinatura declarada (uma vez por processo)."""
    kernel = _kernel32_holder.get("kernel")
    if kernel is not None:
        return kernel
    with _cache_lock:
        kernel = _kernel32_holder.get("kernel")
        if kernel is not None:
            return kernel
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("topologia nativa disponível apenas no Windows")
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetLogicalProcessorInformation.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetLogicalProcessorInformation.restype = wintypes.BOOL
        _kernel32_holder["kernel"] = kernel
        return kernel


def _count_cores(raw: bytes) -> int | None:
    """Nº de núcleos em um buffer de SYSTEM_LOGICAL_PROCESSOR_INFORMATION.

    None se o buffer for inconsistente (tamanho não-múltiplo ou zero núcleos):
    quem chama degrada para os.cpu_count().
    """
    if not raw or len(raw) % _ENTRY_BYTES != 0:
        return None
    cores = 0
    for base in range(0, len(raw), _ENTRY_BYTES):
        relationship = int.from_bytes(raw[base + _REL_OFFSET:base + _REL_OFFSET + 4],
                                      "little")
        if relationship == _RELATION_PROCESSOR_CORE:
            cores += 1
    return cores or None


def _native_core_count() -> int | None:
    """Nº de núcleos físicos via API nativa; None se indisponível."""
    try:
        kernel = _kernel32()
    except OSError:
        return None
    try:
        size = wintypes.DWORD(0)
        kernel.GetLogicalProcessorInformation(None, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not kernel.GetLogicalProcessorInformation(buffer, ctypes.byref(size)):
            return None
        return _count_cores(bytes(buffer.raw[:size.value]))
    except Exception:
        return None


def _logical_count() -> int:
    return os.cpu_count() or 1


def _topology() -> tuple[int, int]:
    """(fisicos, logicos), com cache: uma chamada nativa por processo."""
    cached = _cache.get("topology")
    if cached is not None:
        return cached
    with _cache_lock:
        cached = _cache.get("topology")
        if cached is not None:
            return cached
        logical = _logical_count()
        physical = _native_core_count() or logical
        if physical < 1:
            physical = logical
        topology = (physical, logical)
        _cache["topology"] = topology
        return topology


def get_physical_cores() -> int:
    """Fisicos (nativo). Fallback: os.cpu_count() se a API falhar."""
    return _topology()[0]


def get_logical_count() -> int:
    """Logicos (os.cpu_count)."""
    return _topology()[1]


def reset() -> None:
    """Limpa o cache (testes)."""
    with _cache_lock:
        _cache.pop("topology", None)
