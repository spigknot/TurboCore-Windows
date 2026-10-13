import math

from turbocore.clock_table import CoreClock, ClockTable, bar_pixels, clock_text


def test_clock_format_preserves_hwinfo_rounding_and_multiplier():
    assert clock_text(CoreClock(3745.6, 38)) == ("3746", "x38.00")
    assert clock_text(CoreClock(0, 0)) == ("0", "x0.00")
    assert clock_text(CoreClock(3745.6)) == ("3746", "—")
    assert clock_text(CoreClock(math.nan, math.inf)) == ("—", "—")


def test_bar_uses_common_scale_and_clamps_turbo():
    assert bar_pixels(3746, 3800) == 96
    assert bar_pixels(1900, 3800) == 49
    assert bar_pixels(5000, 3800) == 98
    assert bar_pixels(None, 3800) == 0
    assert bar_pixels(-1, 3800) == 0


def test_refresh_clears_missing_rows_and_does_not_allocate_widgets(tk_root):
    table = ClockTable(tk_root, 18)
    try:
        items = table.find_all()
        image_count = len(tk_root.tk.call("image", "names"))
        table.show_clocks([CoreClock(3746, 38)] * 18, maximum=3800)
        assert table.itemcget(table._rows[17][1], "text") == "3746"
        assert table.itemcget(table._rows[17][2], "text") == "x38.00"
        table.show_clocks([CoreClock(1900)], maximum=3800)
        assert table.coords(table._rows[0][0])[0] == 86
        assert table.itemcget(table._rows[17][1], "text") == "—"
        assert table.coords(table._rows[17][0])[0] == 37
        assert table.find_all() == items
        assert len(tk_root.tk.call("image", "names")) == image_count
    finally:
        table.destroy()


def test_click_switches_both_values_and_gradient_then_restores_active(tk_root):
    table = ClockTable(tk_root, 1)
    try:
        table.show_clocks([CoreClock(3800, 38)], maximum=3800,
                          effective=[CoreClock(750, 7.5)])
        images = len(tk_root.tk.call("image", "names"))
        assert table.bind("<Button-1>")
        table.toggle_mode()
        assert table.mode == "effective"
        assert table.itemcget(table._rows[0][1], "text") == "750"
        assert table.itemcget(table._rows[0][2], "text") == "x7.50"
        assert table._bar_images[0]["effective"].get(0, 0) == (0, 64, 0)
        assert table.coords(table._rows[0][0])[0] == 56
        # Refreshes preserve the chosen mode and share its active-clock scale.
        table.show_clocks([CoreClock(3800, 38)], maximum=3800,
                          effective=[CoreClock(1900, 19)])
        assert table.itemcget(table._rows[0][1], "text") == "1900"
        table.toggle_mode()
        assert table.mode == "active"
        assert table.itemcget(table._rows[0][1], "text") == "3800"
        assert table._bar_images[0]["active"].get(0, 0) == (64, 64, 0)
        assert len(tk_root.tk.call("image", "names")) == images
    finally:
        table.destroy()


def test_effective_mode_waits_for_a_measured_interval(tk_root):
    table = ClockTable(tk_root, 1)
    try:
        table.show_clocks([CoreClock(3800, 38)], maximum=3800)
        table.toggle_mode()
        assert table.itemcget(table._rows[0][1], "text") == "—"
        table.toggle_mode()
        assert table.itemcget(table._rows[0][1], "text") == "3800"
    finally:
        table.destroy()
