"""Compact live-clock table, measured from the supplied HWiNFO window.

All coordinates and fonts use pixels, so Windows' Tk font scaling does not
stretch the 14-pixel rows. Telemetry is supplied separately from painting.
"""
from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True)
class CoreClock:
    mhz: float | None = None
    ratio: float | None = None


def clock_text(clock: CoreClock) -> tuple[str, str]:
    mhz = (str(round(clock.mhz)) if clock.mhz is not None
           and math.isfinite(clock.mhz) and clock.mhz >= 0 else "—")
    ratio = (f"x{clock.ratio:.2f}" if clock.ratio is not None
             and math.isfinite(clock.ratio) and clock.ratio >= 0 else "—")
    return mhz, ratio


def bar_pixels(mhz: float | None, maximum: float, width: int = 98) -> int:
    if mhz is None or not math.isfinite(mhz) or maximum <= 0:
        return 0
    return int(width * max(0.0, min(1.0, mhz / maximum)))


class ClockTable(tk.Canvas):
    WIDTH = 250
    ROW_HEIGHT = 14
    FIRST_ROW = 23
    BACKGROUND = "#f0f0f0"
    FONT = ("Tahoma", -9)

    def __init__(self, master, cores: int):
        self.cores = cores
        height = 20 + cores * self.ROW_HEIGHT
        super().__init__(master, width=self.WIDTH, height=height,
                         background=self.BACKGROUND, highlightthickness=0,
                         borderwidth=0, cursor="hand2")
        self.mode = "active"
        self._active = []
        self._effective = None
        self._maximum = 100
        self.bind("<Button-1>", self.toggle_mode)
        self._font = self.FONT
        for x, title, anchor in ((21, "Core", "center"),
                                 (86, "Relógio", "center"),
                                 (166, "MHz", "center"),
                                 (244, "Relação", "e")):
            self.create_text(x, 10, text=title, anchor=anchor,
                             font=self._font, fill="#000000")

        self._bar_images = []
        self._bar_items = []
        self._last_bars = [None] * cores
        self._rows = []
        for index in range(cores):
            y = self.FIRST_ROW + index * self.ROW_HEIGHT
            self.create_text(31, y, text=str(index), anchor="e",
                             font=self._font, fill="#008000")
            self.create_rectangle(36, y - 5, 135, y + 5,
                                  fill="#ffffff", outline="#a0a0a0")
            photos = {mode: tk.PhotoImage(master=self, width=98, height=9)
                      for mode in ("active", "effective")}
            self._bar_images.append(photos)
            self._bar_items.append(self.create_image(
                37, y - 4, image=photos["active"], anchor="nw"))
            mask = self.create_rectangle(37, y - 4, 135, y + 5,
                                         fill="#ffffff", outline="")
            mhz = self.create_text(176, y, text="—", anchor="e",
                                   font=self._font, fill="#000000")
            ratio = self.create_text(244, y, text="—", anchor="e",
                                     font=self._font, fill="#000000")
            self._rows.append((mask, mhz, ratio))

    def show_clocks(self, clocks: list[CoreClock], *, maximum: float,
                    effective: list[CoreClock] | None = None):
        self._active, self._effective, self._maximum = clocks, effective, maximum
        self._paint()

    def toggle_mode(self, _event=None):
        self.mode = "effective" if self.mode == "active" else "active"
        self._paint()

    def _paint(self):
        clocks = (self._active if self.mode == "active" else self._effective) or []
        for index, (mask, mhz_item, ratio_item) in enumerate(self._rows):
            clock = clocks[index] if index < len(clocks) else CoreClock()
            mhz, ratio = clock_text(clock)
            self.itemconfigure(mhz_item, text=mhz)
            self.itemconfigure(ratio_item, text=ratio)
            y = self.FIRST_ROW + index * self.ROW_HEIGHT
            pixels = bar_pixels(clock.mhz, self._maximum)
            key = (self.mode, pixels)
            if self._last_bars[index] != key:
                photo = self._bar_images[index][self.mode]
                if pixels:
                    # HWiNFO stretches the dark-to-bright gradient across the
                    # filled part, even when a green bar is only a few pixels.
                    values = [64 + int(191 * x / pixels) for x in range(pixels)]
                    colors = [(f"#{v:02x}{v:02x}00" if self.mode == "active"
                               else f"#00{v:02x}00") for v in values]
                    photo.put(" ".join("{" + " ".join(colors) + "}"
                                       for _ in range(9)), to=(0, 0, pixels, 9))
                self.itemconfigure(self._bar_items[index], image=photo)
                self._last_bars[index] = key
            self.coords(mask, 37 + pixels, y - 4, 135, y + 5)
            self.itemconfigure(mask, state="hidden" if pixels == 98 else "normal")
