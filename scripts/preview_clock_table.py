"""Render the reference values for visual comparison (no CPU/power changes)."""
import argparse
import tkinter as tk

from turbocore.clock_table import ClockTable, CoreClock

parser = argparse.ArgumentParser()
parser.add_argument("--capture")
parser.add_argument("--effective", action="store_true")
args = parser.parse_args()
root = tk.Tk()
root.title("TurboCore — prévia do relógio ativo")
root.resizable(False, False)
table = ClockTable(root, 18)
table.pack()
values = [745, 927, 89] + [1] * 14 + [13]
ratios = [7.57, 9.42, .90] + [.01] * 14 + [.14]
effective = [CoreClock(value, ratio) for value, ratio in zip(values, ratios)]
table.show_clocks([CoreClock(3745.6, 38)] * 18, maximum=3800, effective=effective)
if args.effective:
    table.toggle_mode()
if args.capture:
    root.attributes("-topmost", True)
    # Capture our own rendered artifact after Tk has completed its first paint.
    def capture():
        from PIL import ImageGrab
        x, y = table.winfo_rootx(), table.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + table.winfo_width(),
                            y + table.winfo_height())).save(args.capture)
        root.destroy()
    root.after(500, capture)
root.mainloop()
