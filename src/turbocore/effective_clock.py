"""Effective Intel clocks from read-only APERF/MPERF hardware counters.

APERF counts actual executed cycles while a logical processor is in C0.
Cycles divided by the complete wall-time interval include halted states.
No counters are reset or written, and no utilization estimate is substituted.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

from turbocore.clock_table import CoreClock


@dataclass(frozen=True)
class CounterReading:
    aperf: int
    mperf: int
    timestamp: float


def effective_mhz(previous: CounterReading, current: CounterReading):
    elapsed = current.timestamp - previous.timestamp
    # Re-prime after an idle panel, very short window, rollover or external
    # counter reset. An unsigned subtraction would invent an enormous clock.
    if (not .05 <= elapsed <= 5 or current.aperf < previous.aperf
            or current.mperf < previous.mperf):
        return None
    return (current.aperf - previous.aperf) / elapsed / 1_000_000


class EffectiveClockSampler:
    def __init__(self, core_threads, read_counter, close=None):
        self._core_threads = core_threads
        self._read_counter = read_counter
        self._close = close
        self._previous = None

    def sample(self, bus_mhz):
        readings = [[self._read_counter(affinity) for affinity in core]
                    for core in self._core_threads]
        previous, self._previous = self._previous, readings
        if previous is None:
            return None
        cores = []
        for old_threads, new_threads in zip(previous, readings):
            values = [effective_mhz(old, new)
                      for old, new in zip(old_threads, new_threads)]
            if not values or any(value is None for value in values):
                return None
            # A busy SMT sibling must still appear in its physical core's row.
            mhz = max(values)
            cores.append(CoreClock(mhz, mhz / bus_mhz))
        return cores

    def close(self):
        if self._close is not None:
            self._close()
            self._close = None


def create_intel_sampler(cpu, physical):
    from turbocore.hardware_clock import HardwareClockError
    if not str(cpu.Identifier).startswith("/intelcpu/"):
        raise HardwareClockError("Leitura do relógio efetivo ainda não suportada "
                                 "neste modelo de CPU")
    # The hardware list exposes IHardware wrappers in pythonnet. Query the
    # public CpuId property on the concrete type, without private-field access.
    ids = cpu.GetType().GetProperty("CpuId").GetValue(cpu)
    if len(ids) != physical or any(len(core) == 0 for core in ids):
        raise HardwareClockError("Topologia dos contadores efetivos indisponível")
    if any(core[0].Data.GetLength(0) <= 6 or not (int(core[0].Data[6, 2]) & 1)
           for core in ids):
        raise HardwareClockError("CPU sem os contadores APERF/MPERF")
    from System import UInt32
    from LibreHardwareMonitor.PawnIo import IntelMsr
    module = IntelMsr()
    core_threads = [[thread.Affinity for thread in core] for core in ids]

    def read_msr(index, affinity):
        ok, low, high = module.ReadMsr(UInt32(index), UInt32(0), UInt32(0), affinity)
        if not ok:
            raise HardwareClockError("Falha ao ler o contador efetivo pelo PawnIO")
        return (int(high) << 32) | int(low)

    def read_counter(affinity):
        start = time.perf_counter()
        aperf = read_msr(0xE8, affinity)
        end = time.perf_counter()
        mperf = read_msr(0xE7, affinity)
        if aperf == 0 and mperf == 0:
            raise HardwareClockError("Contadores APERF/MPERF indisponíveis no driver")
        return CounterReading(aperf, mperf, (start + end) / 2)

    return EffectiveClockSampler(core_threads, read_counter, module.Close)
