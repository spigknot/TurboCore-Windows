from unittest.mock import patch

from turbocore import cpu_info

FAKE_PS = "NumberOfCores : 18\r\nNumberOfLogicalProcessors : 36\r\n"


def test_parses_powershell_output():
    with patch.object(cpu_info, "_powershell_cim", return_value=FAKE_PS):
        assert cpu_info.get_physical_cores() == 18
        assert cpu_info.get_logical_count() == 36


def test_soma_multiplos_sockets():
    out = "NumberOfCores : 8\r\nNumberOfLogicalProcessors : 16\r\n" * 2
    with patch.object(cpu_info, "_powershell_cim", return_value=out):
        assert cpu_info.get_physical_cores() == 16
        assert cpu_info.get_logical_count() == 32


def test_fallback_sem_powershell():
    with patch.object(cpu_info, "_powershell_cim", side_effect=Exception("wmi off")):
        with patch("os.cpu_count", return_value=36):
            assert cpu_info.get_logical_count() == 36
            # sem WMI, fisicos degradam para o logico (seguro: % continua correto p/ 100%)
            assert cpu_info.get_physical_cores() == 36
