"""Clock efetivo por processador lógico, lido direto do PDH (pdh.dll).

efetivo = ActualFrequency × (100 − PercentIdleTime) / 100 (definição do HWiNFO),
via contadores "Actual Frequency" e "% Idle Time" do conjunto "Processor
Information" — os MESMOS números que o WMI expunha, agora dentro do processo.

Por que não PowerShell/WMI (histórico medido nesta máquina):
cada leitura era um `powershell.exe` novo: ~2,2 s ocioso e 4,0–5,6 s com a CPU
ocupada (e >40 s em carga maior), com ~19 processos/min enquanto o painel
ficasse aberto — a lista de núcleos ficava vazia por segundos. Aqui o setup do
provider custa ~400 ms UMA vez por processo e cada refresh ~0,25 ms
(1,9–3,3 ms sob carga).

SEM fallback, por decisão de projeto: se o PDH não entregar, `read()` levanta
PDHError e o painel avisa no log — não existe caminho lento escondido.

Armadilhas já pagas (não mexer sem rodar os testes):
- nomes de contador são LOCALIZADOS no Windows (pt-BR: "Frequência Real",
  "% de Tempo Ocioso"): só `PdhAddEnglishCounterW` é portável;
- ctypes sem `argtypes` manda `str` como `char*` — nome acentuado chega
  corrompido e a chamada devolve PDH_CSTATUS_NO_OBJECT;
- "Actual Frequency" só tem valor na SEGUNDA coleta (a query nasce primada) e
  a leitura imediatamente após o priming pode vir 0 — o painel mantém o
  placeholder até o primeiro valor > 0;
- PDH_FMT_COUNTERVALUE carrega uma UNIÃO: declarar só o campo double causou
  SIGSEGV ao ler o array.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import re
import threading

PDH_FMT_DOUBLE = 0x00000200
ERROR_SUCCESS = 0

# Caminhos em INGLÊS de propósito (ver docstring); o `(*)` cobre as 36 linhas.
FREQ_COUNTER = r"\Processor Information(*)\Actual Frequency"
IDLE_COUNTER = r"\Processor Information(*)\% Idle Time"

# Instância por processador lógico: "socket,core" (ex.: "0,5"). "_Total" e
# "0,_Total" ficam de fora.
INSTANCE_RE = re.compile(r"^(\d+),(\d+)$")

PLACEHOLDER = "lendo..."


class PDHError(OSError):
    """Falha do PDH (dll ausente, contador indisponível, status != 0)."""


def effective_mhz(actual_mhz: int, idle_pct: int) -> int:
    busy = max(0, min(100, 100 - idle_pct))
    return round(actual_mhz * busy / 100)


def aggregate_cores(effective: list[int], threads_per_core: int) -> list[int]:
    """Agrega threads lógicas em núcleos físicos: efetivo = max."""
    if threads_per_core < 1:
        raise ValueError("threads_per_core deve ser >= 1")
    return [max(effective[base:base + threads_per_core])
            for base in range(0, len(effective), threads_per_core)]


def format_core_row(index: int, mhz: int | None) -> str:
    """Linha da lista; `mhz` None = ainda sem leitura (placeholder)."""
    if mhz is None:
        return f"Core {index:2d}  {PLACEHOLDER}"
    return f"Core {index:2d}  {mhz:5d} MHz"


def order_logical_instances(names, logical: int) -> list[str]:
    """Nomes 'socket,core' em ordem numérica, só processadores lógicos."""
    pairs = [(int(m.group(1)), int(m.group(2)), name)
             for name in names
             if (m := INSTANCE_RE.match(name))]
    return [name for _, _, name in sorted(pairs)[:logical]]


def effective_series(freqs: dict, idles: dict, logical: int) -> list[int]:
    """[MHz efetivos] por processador lógico, ordem 0..L-1 (sem a dll)."""
    return [effective_mhz(round(freqs[name]), round(idles.get(name, 100.0)))
            for name in order_logical_instances(freqs, logical)]


class _FmtValue(ctypes.Structure):
    """PDH_FMT_COUNTERVALUE: status + UNIÃO (o double não está no offset 4)."""

    class _Union(ctypes.Union):
        _fields_ = [("longValue", wintypes.LONG),
                    ("doubleValue", ctypes.c_double),
                    ("largeValue", ctypes.c_longlong),
                    ("WideStringValue", ctypes.c_wchar_p),
                    ("AnsiStringValue", ctypes.c_char_p)]
    _anonymous_ = ("u",)
    _fields_ = [("CStatus", wintypes.DWORD), ("u", _Union)]


class _FmtItem(ctypes.Structure):
    """PDH_FMT_COUNTERVALUE_ITEM_W: nome da instância + valor formatado."""

    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _FmtValue)]


_dll_holder: dict = {}
_dll_lock = threading.Lock()


def _pdh_dll():
    """Carrega pdh.dll e declara as assinaturas (uma vez por processo)."""
    with _dll_lock:
        dll = _dll_holder.get("dll")
        if dll is not None:
            return dll
        if not hasattr(ctypes, "WinDLL"):  # fora do Windows: só o import é livre
            raise PDHError("PDH disponível apenas no Windows")
        dll = ctypes.WinDLL("pdh")
        lpcwstr = ctypes.c_wchar_p
        handle_p = ctypes.POINTER(wintypes.HANDLE)
        dword_p = ctypes.POINTER(wintypes.DWORD)
        dll.PdhOpenQueryW.argtypes = [lpcwstr, ctypes.c_void_p, handle_p]
        dll.PdhOpenQueryW.restype = wintypes.DWORD
        dll.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, lpcwstr,
                                              ctypes.c_void_p, handle_p]
        dll.PdhAddEnglishCounterW.restype = wintypes.DWORD
        dll.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        dll.PdhCollectQueryData.restype = wintypes.DWORD
        dll.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE,
                                                     wintypes.DWORD, dword_p,
                                                     dword_p, ctypes.c_void_p]
        dll.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
        dll.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        dll.PdhCloseQuery.restype = wintypes.DWORD
        _dll_holder["dll"] = dll
        return dll


def _check(status: int, what: str) -> None:
    if status != ERROR_SUCCESS:
        raise PDHError(f"{what} falhou (0x{status & 0xFFFFFFFF:08X})")


def _read_array(dll, handle) -> dict:
    """{instância: valor} do contador wildcard, em double."""
    size = wintypes.DWORD(0)
    count = wintypes.DWORD(0)
    status = dll.PdhGetFormattedCounterArrayW(handle, PDH_FMT_DOUBLE,
                                              ctypes.byref(size),
                                              ctypes.byref(count), None)
    if size.value == 0:
        raise PDHError(f"buffer vazio do contador (0x{status & 0xFFFFFFFF:08X})")
    # +64 de folga: o tamanho pode crescer entre as duas chamadas.
    buffer = ctypes.create_string_buffer(size.value + 64)
    _check(dll.PdhGetFormattedCounterArrayW(handle, PDH_FMT_DOUBLE,
                                            ctypes.byref(size),
                                            ctypes.byref(count), buffer),
           "PdhGetFormattedCounterArray")
    items = ctypes.cast(buffer, ctypes.POINTER(_FmtItem))
    values = {}
    for index in range(count.value):
        name = items[index].szName
        if name is not None:
            values[name] = items[index].FmtValue.doubleValue
    return values


class _Query:
    """Query PDH com os dois contadores; já nasce primada."""

    def __init__(self):
        self._dll = dll = _pdh_dll()
        self.handle = wintypes.HANDLE()
        _check(dll.PdhOpenQueryW(None, 0, ctypes.byref(self.handle)),
               "PdhOpenQuery")
        self._handles = []
        try:
            for path in (FREQ_COUNTER, IDLE_COUNTER):
                handle = wintypes.HANDLE()
                _check(dll.PdhAddEnglishCounterW(self.handle, path, 0,
                                                 ctypes.byref(handle)),
                       f"PdhAddEnglishCounter({path})")
                self._handles.append(handle)
            # 1ª coleta é priming: sem ela o 1º valor vem
            # PDH_CSTATUS_INVALID_DATA (~400 ms: carrega a dll do provider).
            _check(dll.PdhCollectQueryData(self.handle), "PdhCollectQueryData")
        except Exception:
            self.close()
            raise
        self._lock = threading.Lock()

    def collect(self) -> tuple[dict, dict]:
        """(freqs, idles) por instância — delta desde a coleta anterior."""
        with self._lock:
            _check(self._dll.PdhCollectQueryData(self.handle),
                   "PdhCollectQueryData")
            return (_read_array(self._dll, self._handles[0]),
                    _read_array(self._dll, self._handles[1]))

    def close(self) -> None:
        if self.handle:
            self._dll.PdhCloseQuery(self.handle)
            self.handle = wintypes.HANDLE()


_query_lock = threading.Lock()
_query: _Query | None = None


def _shared_query() -> _Query:
    """Query única do processo: o setup do provider não se repete."""
    global _query
    with _query_lock:
        if _query is None:
            _query = _Query()
        return _query


def prewarm() -> None:
    """Paga o setup do provider fora do caminho de abrir o painel.

    Chamado no start do app (thread de fundo): a primeira abertura do painel
    já encontra a query pronta.
    """
    _shared_query()


def reset() -> None:
    """Descarta a query compartilhada (o próximo uso paga o setup de novo).

    Usado quando uma leitura falha: sem isso a query quebrada ficaria para
    sempre no processo.
    """
    global _query
    with _query_lock:
        query, _query = _query, None
    if query is not None:
        try:
            query.close()
        except Exception:
            pass


class FreqMonitor:
    """Leitura periódica; read() -> [MHz efetivos] por processador lógico."""

    def __init__(self, logical: int):
        self.logical = logical
        self._query = _shared_query()
        # Re-ancora a janela do delta: o contador é uma média do intervalo
        # desde a coleta anterior, que pode ser o priming lá do start do app
        # (minutos). Sem isso a 1ª leitura mostraria uma média antiga.
        self._query.collect()

    def read(self) -> list[int]:
        freqs, idles = self._query.collect()
        stats = effective_series(freqs, idles, self.logical)
        if len(stats) != self.logical:
            raise PDHError(f"PDH retornou {len(stats)} instâncias, "
                           f"esperado {self.logical}")
        return stats

    def close(self) -> None:
        """No-op: a query é do processo (fechá-la pagaria o setup de novo)."""
