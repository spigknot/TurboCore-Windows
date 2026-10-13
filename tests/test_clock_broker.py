import socket
import struct
from unittest.mock import patch

import pytest

from turbocore import clock_broker as broker, hardware_clock as clock


def test_transport_uses_bounded_json_not_executable_serialization():
    left, right = socket.socketpair()
    try:
        payload = {"ok": True, "maximum": 3800,
                   "cores": [{"mhz": 3746, "ratio": 38}],
                   "effective": [{"mhz": 745, "ratio": 7.57}]}
        broker._send(left, payload)
        sample = broker.decode_sample(broker._receive(right), 1)
        assert sample.cores[0].mhz == 3746
        assert sample.cores[0].ratio == 38
        assert sample.effective[0].mhz == 745
        assert sample.effective[0].ratio == 7.57
        left.sendall(struct.pack("!I", broker.MAX_PACKET + 1))
        with pytest.raises(ValueError, match="Pacote inválido"):
            broker._receive(right)
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("payload", [
    {"ok": True, "maximum": 3800, "cores": []},
    {"ok": True, "maximum": 0, "cores": [{"mhz": 3746, "ratio": 38}]},
    {"ok": True, "maximum": 3800, "cores": [{"mhz": float("nan"), "ratio": 38}]},
    {"ok": True, "maximum": 3800, "cores": [{"mhz": True, "ratio": 38}]},
])
def test_reader_rejects_invalid_or_incomplete_hardware_data(payload):
    with pytest.raises(ValueError):
        broker.decode_sample(payload, 1)


def test_reader_rejects_malformed_effective_data():
    payload = {"ok": True, "maximum": 3800,
               "cores": [{"mhz": 3746, "ratio": 38}],
               "effective": [{"mhz": float("nan"), "ratio": 7.57}]}
    with pytest.raises(ValueError, match="efetivo"):
        broker.decode_sample(payload, 1)


def test_canceled_permission_is_not_requested_again_by_refresh():
    class Canceled(OSError):
        winerror = 1223
    with patch.object(broker, "_broker", None), \
            patch.object(broker, "_failure", None), \
            patch.object(broker, "ClockBroker", side_effect=Canceled()) as launch:
        for _ in range(3):
            with pytest.raises(clock.HardwareClockError, match="cancelada"):
                broker.get_broker()
        assert launch.call_count == 1
        broker.begin_panel_session()
        with pytest.raises(clock.HardwareClockError, match="cancelada"):
            broker.get_broker()
        assert launch.call_count == 2


def test_normal_startup_prewarm_does_not_request_elevation():
    with patch.object(clock, "is_elevated", return_value=False), \
            patch.object(clock, "_open_computer") as computer, \
            patch.object(broker, "get_broker") as launch:
        clock.prewarm()
        computer.assert_not_called()
        launch.assert_not_called()


def test_unelevated_monitor_uses_the_shared_reader_and_never_opens_driver():
    with patch.object(clock, "is_elevated", return_value=False), \
            patch.object(clock, "_open_computer") as computer, \
            patch.object(broker, "get_broker") as reader:
        monitor = clock.HardwareClockMonitor(18)
        assert monitor.read() == reader.return_value.read.return_value
        reader.return_value.read.assert_called_once_with(18)
        computer.assert_not_called()


def test_worker_entry_never_starts_ui_or_changes_power_settings():
    from turbocore import main
    with patch.object(broker, "run_worker") as worker, \
            patch.object(main, "start_initial_power") as power, \
            patch.object(main, "run_event_loop") as ui:
        main.main(["--clock-worker", "12345", "a" * 64, "456"])
        worker.assert_called_once_with(12345, "a" * 64, 456)
        power.assert_not_called()
        ui.assert_not_called()
