import math
from unittest.mock import patch

import pytest

from turbocore import hardware_clock as clock


def test_direct_clock_keeps_core_order_and_measured_bus_ratio():
    rows = clock.sensor_clocks([
        ("CPU Core #2", "Clock", 3745.6),
        ("Bus Speed", "Clock", 98.5684210526),
        ("CPU Core #1", "Clock", 1971.368421052),
        ("CPU Core #1 Effective", "Clock", 20),
        ("CPU Core #1", "Load", 7),
        ("CPU Package", "Clock", 9999),
    ], 2)
    assert rows[0].mhz == pytest.approx(1971.368421052)
    assert rows[0].ratio == pytest.approx(20)
    assert rows[1].ratio == pytest.approx(38)


@pytest.mark.parametrize("sensors", [
    [("CPU Core #1", "Clock", 2300)],  # TSC fallback, no bus measurement
    [("Bus Speed", "Clock", 100), ("CPU Core #1", "Clock", None)],
    [("Bus Speed", "Clock", 0), ("CPU Core #1", "Clock", 2300)],
    [("Bus Speed", "Clock", 100), ("CPU Core #1", "Clock", math.nan)],
])
def test_unavailable_hardware_never_turns_into_a_plausible_clock(sensors):
    with pytest.raises(clock.HardwareClockError):
        clock.sensor_clocks(sensors, 1)


def test_monitor_updates_cpu_only_and_releases_shared_handle():
    class Sensor:
        def __init__(self, name, value):
            self.Name, self.Value, self.SensorType = name, value, "Clock"

    class Cpu:
        HardwareType = "Cpu"
        Sensors = [Sensor("Bus Speed", 98.5684210526),
                   Sensor("CPU Core #1", 3745.6)]

        def Update(self):
            self.updated = True

    class Computer:
        Hardware = [Cpu()]

        def Close(self):
            self.closed = True

    computer = Computer()
    with patch.object(clock, "_computer", None), \
            patch.object(clock, "is_elevated", return_value=True), \
            patch.object(clock, "_open_computer", return_value=computer) as opener:
        monitor = clock.HardwareClockMonitor(1)
        try:
            sample = monitor.read()
            assert sample.cores[0].ratio == pytest.approx(38)
            assert sample.maximum == 3800
            computer.Hardware[0].Sensors[1].Value = 1200
            assert monitor.read().maximum == 3800  # scale does not jump on idle
            assert computer.Hardware[0].updated
            opener.assert_called_once()
        finally:
            monitor.close()
            clock.reset()
        assert computer.closed
        assert clock._computer is None
