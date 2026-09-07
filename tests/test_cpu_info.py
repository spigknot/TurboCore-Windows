from unittest.mock import MagicMock, patch

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


def test_powershell_sem_janela_console():
    import subprocess
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        m = MagicMock()
        m.returncode = 0
        m.stdout = b"NumberOfCores : 4\r\nNumberOfLogicalProcessors : 8\r\n"
        m.stderr = b""
        return m

    with patch.object(cpu_info.subprocess, "run", side_effect=fake_run):
        assert cpu_info.get_physical_cores() == 4
    assert seen.get("creationflags") == subprocess.CREATE_NO_WINDOW
