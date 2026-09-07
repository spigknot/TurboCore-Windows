from unittest.mock import MagicMock, patch

from turbocore import power


def _ok():
    m = MagicMock()
    m.returncode = 0
    m.stdout = ""
    m.stderr = ""
    return m


def test_apply_emite_dois_comandos_em_ordem():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _ok()

    with patch.object(power.subprocess, "run", side_effect=fake_run):
        power.apply_percent(56)
    assert calls[0] == ["powercfg", "-setacvalueindex", "scheme_current",
                        "sub_processor", "CPMAXCORES", "56"]
    assert calls[1] == ["powercfg", "-setactive", "scheme_current"]


def test_release_eh_apply_100():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _ok()

    with patch.object(power.subprocess, "run", side_effect=fake_run):
        power.release_all_cores()
    assert calls[0][-1] == "100"
    assert calls[1] == ["powercfg", "-setactive", "scheme_current"]


def test_apply_core_limit_converte_cores_em_percent():
    with patch.object(power, "apply_percent") as ap:
        power.apply_core_limit(chosen_cores=10, physical_cores=18)
        ap.assert_called_once_with(56)


def test_falha_levanta():
    bad = MagicMock()
    bad.returncode = 1
    bad.stderr = b"acesso negado"
    with patch.object(power.subprocess, "run", return_value=bad):
        try:
            power.apply_percent(56)
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
