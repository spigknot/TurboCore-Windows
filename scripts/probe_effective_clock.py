"""Validate a busy SMT sibling against an idle baseline without power changes."""
from pathlib import Path
import json
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from turbocore import cpu_info, hardware_clock

physical = cpu_info.get_physical_cores()
logical = cpu_info.get_logical_count() - 1
report = {"interface_elevated": hardware_clock.is_elevated(), "logical_load": logical}
child = None
try:
    monitor = hardware_clock.HardwareClockMonitor(physical)
    monitor.read()
    time.sleep(1)
    idle = monitor.read()
    assert idle.effective is not None, idle.effective_error
    report["idle_mhz"] = [c.mhz for c in idle.effective]
    code = """
import ctypes,time,sys
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetCurrentThread.restype=ctypes.c_void_p
k.SetThreadAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
k.SetThreadAffinityMask.restype=ctypes.c_size_t
if not k.SetThreadAffinityMask(k.GetCurrentThread(),1<<int(sys.argv[1])):
 raise ctypes.WinError(ctypes.get_last_error())
deadline=time.perf_counter()+3
while time.perf_counter()<deadline: pass
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(logical)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(1.2)
    loaded = monitor.read()
    assert loaded.effective is not None, loaded.effective_error
    report["loaded_mhz"] = [c.mhz for c in loaded.effective]
    # The last logical processor belongs to the last physical row on this
    # validation machine. A sleeping first sibling must not hide that load.
    assert loaded.effective[-1].mhz > idle.effective[-1].mhz + 500, report
    child.wait(timeout=5)
    report["ok"] = True
except Exception as exc:
    report.update(ok=False, error=str(exc))
finally:
    if child is not None and child.poll() is None:
        child.terminate()
        child.wait(timeout=5)
    hardware_clock.reset()
    destination = Path(__file__).resolve().parents[1] / "build" / "effective-load-report.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
