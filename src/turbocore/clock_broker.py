"""A narrowly scoped elevated reader for an otherwise unelevated application.

The private loopback connection carries bounded JSON and the two fixed commands
READ/CLOSE. It exposes no arbitrary MSR, process, file or power-setting operation.
The reader exits when the owning application exits or closes the connection.
"""
from __future__ import annotations

import ctypes
import hmac
import json
import math
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time

MAX_PACKET = 65536
_lock = threading.RLock()
_broker = None
_failure = None


def _receive(connection):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise OSError("O leitor de hardware foi encerrado")
            data.extend(chunk)
        return bytes(data)
    size = struct.unpack("!I", exact(4))[0]
    if size < 1 or size > MAX_PACKET:
        raise ValueError("Pacote inválido do leitor de hardware")
    return json.loads(exact(size).decode("utf-8"))


def _send(connection, payload):
    data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_PACKET:
        raise ValueError("Pacote excedeu o limite do leitor de hardware")
    connection.sendall(struct.pack("!I", len(data)) + data)


def decode_sample(payload, physical):
    from turbocore.hardware_clock import ClockSample, HardwareClockError
    from turbocore.clock_table import CoreClock
    if not isinstance(payload, dict):
        raise ValueError("Resposta inválida do leitor de hardware")
    if payload.get("ok") is not True:
        raise HardwareClockError(str(payload.get("error", "Leitura indisponível"))[:512])
    rows = payload.get("cores")
    maximum = payload.get("maximum")
    def valid(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    if (not isinstance(rows, list) or len(rows) != physical
            or not valid(maximum) or maximum == 0):
        raise ValueError("Amostra inválida do leitor de hardware")
    clocks = []
    for row in rows:
        if (not isinstance(row, dict) or not valid(row.get("mhz"))
                or not valid(row.get("ratio"))):
            raise ValueError("Clock inválido do leitor de hardware")
        clocks.append(CoreClock(row["mhz"], row["ratio"]))
    effective = payload.get("effective")
    if effective is not None:
        if not isinstance(effective, list) or len(effective) != physical:
            raise ValueError("Amostra efetiva inválida do leitor de hardware")
        rows = []
        for row in effective:
            if (not isinstance(row, dict) or not valid(row.get("mhz"))
                    or not valid(row.get("ratio"))):
                raise ValueError("Clock efetivo inválido do leitor de hardware")
            rows.append(CoreClock(row["mhz"], row["ratio"]))
        effective = rows
    error = payload.get("effective_error")
    if error is not None and not isinstance(error, str):
        raise ValueError("Estado inválido do leitor de hardware")
    return ClockSample(clocks, maximum, effective, error[:512] if error else None)


def _launch_worker(port, token):
    from win32com.shell import shell, shellcon
    import win32api
    if getattr(sys, "frozen", False):
        args = ["--clock-worker", str(port), token, str(win32api.GetCurrentProcessId())]
    else:
        args = [str(Path(__file__).with_name("clock_worker_entry.py")),
                str(port), token, str(win32api.GetCurrentProcessId())]
    launched = shell.ShellExecuteEx(
        fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
        lpVerb="runas", lpFile=sys.executable,
        lpParameters=subprocess.list2cmdline(args), nShow=0)
    return launched["hProcess"]


class ClockBroker:
    def __init__(self):
        self.connection = None
        self.process = None
        self._io_lock = threading.Lock()
        token = secrets.token_hex(32)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                # No network interface or shared well-known port is exposed.
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                server.bind(("127.0.0.1", 0))
                server.listen(4)
                self.process = _launch_worker(server.getsockname()[1], token)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    server.settimeout(max(.1, deadline - time.monotonic()))
                    connection, _ = server.accept()
                    connection.settimeout(2)
                    try:
                        hello = _receive(connection)
                        if (not isinstance(hello, dict) or hello.get("version") != 1
                                or not isinstance(hello.get("token"), str)
                                or not hmac.compare_digest(hello["token"], token)):
                            connection.close()
                            continue
                        _send(connection, {"version": 1, "token": token})
                        connection.settimeout(10)
                        self.connection = connection
                        break
                    except (OSError, ValueError):
                        connection.close()
                if self.connection is None:
                    raise OSError("O leitor elevado não iniciou a conexão")
        except Exception:
            self.close()
            raise

    def read(self, physical):
        with self._io_lock:
            if self.connection is None:
                raise OSError("O leitor de hardware foi encerrado")
            _send(self.connection, "READ")
            return decode_sample(_receive(self.connection), physical)

    def close(self):
        if self.connection is not None:
            try:
                # Disconnect also interrupts an outstanding request. The worker
                # owns no UI and exits on EOF; no unrelated process is stopped.
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            self.connection = None
        if self.process is not None:
            self.process.Close()
            self.process = None


def get_broker():
    global _broker, _failure
    from turbocore.hardware_clock import HardwareClockError
    with _lock:
        if _failure is not None:
            raise HardwareClockError(_failure)
        if _broker is None:
            try:
                _broker = ClockBroker()
            except Exception as exc:
                if getattr(exc, "winerror", None) == 1223:
                    _failure = ("Permissão do leitor de hardware cancelada. "
                                "Reabra o painel para tentar novamente.")
                else:
                    _failure = (f"Não foi possível iniciar o leitor de hardware: {exc}. "
                                "Reabra o painel para tentar novamente.")
                raise HardwareClockError(_failure) from exc
        return _broker


def begin_panel_session():
    global _failure
    with _lock:
        if _failure is not None:
            close()
            _failure = None


def close():
    global _broker
    with _lock:
        broker, _broker = _broker, None
        if broker is not None:
            broker.close()


def run_worker(port, token, parent_pid):
    """Internal entry point: privileged CPU samples only, no tray or powercfg."""
    if (sys.platform != "win32" or not ctypes.windll.shell32.IsUserAnAdmin()
            or not 1 <= port <= 65535 or parent_pid <= 0
            or len(token) != 64 or any(c not in "0123456789abcdef" for c in token)):
        raise ValueError("Inicialização inválida do leitor de hardware")
    import win32api
    import win32event
    import win32con
    from turbocore.cpu_info import get_physical_cores
    from turbocore.hardware_clock import HardwareClockMonitor, reset_reader
    # Hold the original parent's process handle, avoiding PID reuse on shutdown.
    parent = win32api.OpenProcess(win32con.SYNCHRONIZE, False, parent_pid)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
            _send(connection, {"version": 1, "token": token})
            hello = _receive(connection)
            if (not isinstance(hello, dict) or hello.get("version") != 1
                    or not isinstance(hello.get("token"), str)
                    or not hmac.compare_digest(hello["token"], token)):
                raise ValueError("Aplicativo proprietário do leitor não autenticado")
            connection.settimeout(2)
            monitor = None
            while win32event.WaitForSingleObject(parent, 0) == win32con.WAIT_TIMEOUT:
                # Idle waits don't poll the CPU when the panel is closed.
                import select
                if not select.select([connection], [], [], 1)[0]:
                    continue
                request = _receive(connection)
                if request == "CLOSE":
                    break
                if request != "READ":
                    raise ValueError("Operação não suportada pelo leitor de hardware")
                try:
                    if monitor is None:
                        monitor = HardwareClockMonitor(get_physical_cores())
                    sample = monitor.read()
                    response = {"ok": True, "maximum": sample.maximum,
                                "cores": [{"mhz": c.mhz, "ratio": c.ratio}
                                          for c in sample.cores],
                                "effective": (None if sample.effective is None else
                                              [{"mhz": c.mhz, "ratio": c.ratio}
                                               for c in sample.effective]),
                                "effective_error": sample.effective_error}
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)[:512]}
                    reset_reader()
                    monitor = None
                _send(connection, response)
    except (OSError, ValueError):
        pass  # parent exit, disconnection or invalid protocol: release the reader
    finally:
        reset_reader()
        parent.Close()
