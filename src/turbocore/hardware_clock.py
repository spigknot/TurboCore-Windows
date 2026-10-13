"""Direct CPU clocks via LibreHardwareMonitor/PawnIO, never via HWiNFO.

The sensor library measures BCLK and samples core hardware ratios (MSRs on
Intel). No idle-time weighting or PDH fallback is used. Only CPU monitoring
is enabled; this adapter does not change power limits or CPU configuration.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys
import threading

from turbocore.clock_table import CoreClock

CORE_NAME = re.compile(r"^(?:CPU )?Core #(\d+)\b")


class HardwareClockError(OSError):
    pass


@dataclass(frozen=True)
class ClockSample:
    cores: list[CoreClock]
    maximum: float
    effective: list[CoreClock] | None = None
    effective_error: str | None = None


def sensor_clocks(sensors, physical: int) -> list[CoreClock]:
    """Keep physical core identities, excluding bus/effective/aggregate clocks."""
    clocks = {}
    bus = None
    for name, kind, value in sensors:
        if kind != "Clock" or value is None or not math.isfinite(value):
            continue
        if name in ("Bus Speed", "Bus Clock") and value > 0:
            bus = value
        match = CORE_NAME.match(name)
        if match and "effective" not in name.casefold() and value >= 0:
            clocks[int(match.group(1)) - 1] = value
    # A bus reading is required: otherwise Intel's library can report a TSC
    # fallback as a core clock even though access to the MSRs failed.
    if bus is None:
        raise HardwareClockError("Clock base indisponível; não foi possível ler "
                                 "os registradores da CPU pelo PawnIO")
    if any(index not in clocks for index in range(physical)):
        raise HardwareClockError("O hardware não entregou o clock de todos os "
                                 "núcleos físicos")
    return [CoreClock(clocks[index], clocks[index] / bus)
            for index in range(physical)]


def _library_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / "hardware-monitor"


def is_elevated():
    return sys.platform == "win32" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def _open_computer():
    if sys.platform != "win32":
        raise HardwareClockError("Leitura de hardware disponível apenas no Windows")
    if not is_elevated():
        raise HardwareClockError("O leitor de hardware precisa da permissão do Windows")
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            pass
    except FileNotFoundError as exc:
        raise HardwareClockError("Instale o driver PawnIO para habilitar a leitura "
                                 "direta dos clocks (https://pawnio.eu)") from exc
    directory = _library_dir()
    library = directory / "LibreHardwareMonitorLib.dll"
    if not library.is_file():
        raise HardwareClockError("Biblioteca de hardware ausente; execute "
                                 "scripts/fetch_hardware_monitor.py e gere o build")
    # Lazy import keeps opening the UI independent of CLR/CPU initialization.
    try:
        import clr
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        clr.AddReference(str(library))
        from LibreHardwareMonitor.Hardware import Computer
        computer = Computer()
        computer.IsCpuEnabled = True
        try:
            computer.Open()
        except Exception:
            computer.Close()
            raise
        return computer
    except Exception as exc:
        raise HardwareClockError(f"Falha ao carregar a biblioteca de hardware: {exc}") from exc


_lock = threading.RLock()
_computer = None
_effective_sampler = None


def prewarm():
    global _computer
    # Silent tray startup must not open a UAC dialog. The broker is started only
    # when an unelevated panel actually requests hardware readings.
    if not is_elevated():
        return
    with _lock:
        if _computer is None:
            _computer = _open_computer()


def reset_reader():
    global _computer, _effective_sampler
    with _lock:
        sampler, _effective_sampler = _effective_sampler, None
        if sampler is not None:
            sampler.close()
        computer, _computer = _computer, None
        if computer is not None:
            computer.Close()


def reset():
    reset_reader()
    from turbocore.clock_broker import close
    close()


class HardwareClockMonitor:
    def __init__(self, physical: int):
        self.physical = physical
        self._maximum = 0.0
        self._broker = None
        if sys.platform != "win32":
            raise HardwareClockError("Leitura de hardware disponível apenas no Windows")
        if is_elevated():
            prewarm()
        else:
            from turbocore.clock_broker import get_broker
            self._broker = get_broker()

    def read(self) -> ClockSample:
        global _effective_sampler
        if self._broker is not None:
            return self._broker.read(self.physical)
        with _lock:
            prewarm()
            # The reference window is CPU #0; don't join separate sockets into
            # a fake common bus. LibreHardwareMonitor handles SMT topology.
            cpus = [h for h in _computer.Hardware if str(h.HardwareType) == "Cpu"]
            if len(cpus) != 1:
                raise HardwareClockError("Este painel requer uma CPU física; "
                                         "topologia com múltiplos sockets não suportada")
            cpu = cpus[0]
            cpu.Update()
            sensors = [(str(s.Name), str(s.SensorType),
                        None if s.Value is None else float(s.Value)) for s in cpu.Sensors]
            clocks = sensor_clocks(sensors, self.physical)
            effective, effective_error = None, None
            try:
                if _effective_sampler is None:
                    from turbocore.effective_clock import create_intel_sampler
                    _effective_sampler = create_intel_sampler(cpu, self.physical)
                bus_mhz = next(value for name, kind, value in sensors
                               if kind == "Clock" and name in ("Bus Speed", "Bus Clock")
                               and value is not None and math.isfinite(value) and value > 0)
                effective = _effective_sampler.sample(bus_mhz)
            except Exception as exc:
                effective_error = str(exc)
        peak = max(clock.mhz for clock in clocks)
        # A stable common scale: highest observed clock rounded up to 100 MHz.
        self._maximum = max(self._maximum, math.ceil(peak / 100) * 100, 100)
        return ClockSample(clocks, self._maximum, effective, effective_error)

    def close(self):
        # A monitor owns no native handles; the process shares one computer.
        pass


def write_diagnostic_report(destination: str):
    """Exercise the same packaged backend without changing CPU power settings."""
    import json
    import time
    from turbocore.cpu_info import get_physical_cores
    report = {"interface_elevated": is_elevated()}
    try:
        monitor = HardwareClockMonitor(get_physical_cores())
        samples = []
        for _ in range(3):
            started = time.perf_counter()
            sample = monitor.read()
            samples.append({"ms": (time.perf_counter() - started) * 1000,
                            "maximum": sample.maximum,
                            "cores": [{"mhz": c.mhz, "ratio": c.ratio}
                                      for c in sample.cores],
                            "effective": (None if sample.effective is None else
                                          [{"mhz": c.mhz, "ratio": c.ratio}
                                           for c in sample.effective]),
                            "effective_error": sample.effective_error})
            time.sleep(.5)
        report.update(ok=True, samples=samples)
    except Exception as exc:
        report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        reset()
        Path(destination).write_text(json.dumps(report, indent=2), encoding="utf-8")
