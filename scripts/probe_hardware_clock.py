"""Read-only hardware/GUI verification; run as administrator for real MSRs."""
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from turbocore import cpu_info, hardware_clock, panel
from turbocore.clock_table import ClockTable

parser = argparse.ArgumentParser()
parser.add_argument("--report", required=True)
parser.add_argument("--capture")
args = parser.parse_args()
report = {"interface_elevated": hardware_clock.is_elevated()}
try:
    physical = cpu_info.get_physical_cores()
    monitor = hardware_clock.HardwareClockMonitor(physical)
    samples = []
    for _ in range(3):
        started = time.perf_counter()
        sample = monitor.read()
        samples.append({"ms": (time.perf_counter() - started) * 1000,
                        "maximum": sample.maximum,
                        "cores": [{"mhz": c.mhz, "ratio": c.ratio} for c in sample.cores],
                        "effective": (None if sample.effective is None else
                                      [{"mhz": c.mhz, "ratio": c.ratio}
                                       for c in sample.effective]),
                        "effective_error": sample.effective_error})
        time.sleep(.5)
    report["samples"] = samples
    if args.capture:
        state = {"physical": physical, "logical": cpu_info.get_logical_count(),
                 "panel": None, "selected": physical, "pending_update": None}
        root = panel.open_panel(state)
        root.attributes("-topmost", True)
        def capture():
            from PIL import ImageGrab
            table = next(w for w in root.winfo_children() if isinstance(w, ClockTable))
            report["visible_mhz"] = [table.itemcget(row[1], "text") for row in table._rows]
            report["panel_size"] = [root.winfo_width(), root.winfo_height()]
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + root.winfo_width(),
                                y + root.winfo_height())).save(args.capture)
            x, y = table.winfo_rootx(), table.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + table.winfo_width(),
                                y + table.winfo_height())).save(
                Path(args.capture).with_name("hardware-clock-live-table.png"))
            table.event_generate("<Button-1>", x=80, y=10)
            root.update_idletasks()
            assert table.mode == "effective"
            report["effective_visible_mhz"] = [table.itemcget(row[1], "text")
                                                for row in table._rows]
            assert any(value != "—" for value in report["effective_visible_mhz"])
            px, py = root.winfo_rootx(), root.winfo_rooty()
            capture_path = Path(args.capture)
            ImageGrab.grab(bbox=(px, py, px + root.winfo_width(),
                                py + root.winfo_height())).save(
                capture_path.with_name(capture_path.stem + "-effective" + capture_path.suffix))
            ImageGrab.grab(bbox=(x, y, x + table.winfo_width(),
                                y + table.winfo_height())).save(
                Path(args.capture).with_name("hardware-clock-effective-live.png"))
            table.event_generate("<Button-1>", x=80, y=10)
            assert table.mode == "active"
            assert [table.itemcget(row[1], "text") for row in table._rows] == report["visible_mhz"]
            report["click_modes"] = ["active", "effective", "active"]
            root.event_generate("<<ClosePanel>>")
        root.after(2500, capture)
        root.mainloop()
    report["ok"] = True
except Exception as exc:
    report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
finally:
    hardware_clock.reset()
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
