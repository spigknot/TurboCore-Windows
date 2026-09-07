from unittest.mock import MagicMock, patch

from turbocore import power


def _ok():
    m = MagicMock()
    m.returncode = 0
    m.stdout = b""
    m.stderr = b""
    return m


def test_apply_selection_emite_tres_comandos_em_ordem():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _ok()

    with patch.object(power.subprocess, "run", side_effect=fake_run):
        result = power.apply_selection(chosen_cores=10, physical_cores=18, logical_count=36)
    assert result == (3, 56)
    assert calls[0] == ["powercfg", "-setacvalueindex", "scheme_current",
                        "sub_processor", "CPMINCORES", "3"]
    assert calls[1] == ["powercfg", "-setacvalueindex", "scheme_current",
                        "sub_processor", "CPMAXCORES", "56"]
    assert calls[2] == ["powercfg", "-setactive", "scheme_current"]


def test_release_libera_min_e_max_100():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _ok()

    with patch.object(power.subprocess, "run", side_effect=fake_run):
        power.release_all_cores()
    assert calls[0][-2:] == ["CPMINCORES", "100"]
    assert calls[1][-2:] == ["CPMAXCORES", "100"]
    assert calls[2] == ["powercfg", "-setactive", "scheme_current"]


def test_falha_levanta():
    bad = MagicMock()
    bad.returncode = 1
    bad.stderr = b"acesso negado"
    with patch.object(power.subprocess, "run", return_value=bad):
        try:
            power.apply_selection(chosen_cores=10, physical_cores=18, logical_count=36)
            assert False, "deveria levantar"
        except RuntimeError as e:
            assert "acesso negado" in str(e)


def test_query_decodifica_saida_ptbr_nao_utf8():
    # powercfg em PT-BR emite bytes fora do UTF-8 (ex. 0x87); nao pode quebrar
    raw = ("\xcdndice de Configura\xe7\xf5es de Correntes Alternadas Atuais: "
           "\x87 0x00000038").encode("latin-1")
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = raw
    ok.stderr = b""
    with patch.object(power.subprocess, "run", return_value=ok):
        assert power.query_current_percent() == 56
