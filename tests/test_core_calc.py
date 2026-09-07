import pytest

from turbocore.core_calc import build_core_options, parse_powercfg_hex, percent_for_cores


def test_18_cores():
    assert build_core_options(18) == [1, 2, 4, 6, 8, 10, 12, 14, 16, 18]


def test_6_cores():
    assert build_core_options(6) == [1, 2, 4, 6]


def test_odd_includes_total():
    assert build_core_options(5) == [1, 2, 4, 5]


def test_1_core():
    assert build_core_options(1) == [1]


def test_2_cores():
    assert build_core_options(2) == [1, 2]


def test_percent_exemplo_spec_10_de_18():
    assert percent_for_cores(10, 18) == 56


def test_percent_teto_nao_piso():
    # 1/18 = 5.55% -> 6 (int() daria 5: proibido)
    assert percent_for_cores(1, 18) == 6


def test_percent_tudo_liberado():
    assert percent_for_cores(18, 18) == 100
    assert percent_for_cores(6, 6) == 100


def test_percent_ht_off():
    # sem HT: 3/6 = 50 exato
    assert percent_for_cores(3, 6) == 50


def test_percent_invalido():
    with pytest.raises(ValueError):
        percent_for_cores(0, 18)
    with pytest.raises(ValueError):
        percent_for_cores(19, 18)


def test_parse_hex_56():
    out = "Indice de Configuracoes de Correntes Alternadas Atuais: 0x00000038"
    assert parse_powercfg_hex(out) == 56


def test_parse_hex_100():
    out = "Current AC Power Setting Index: 0x00000064"
    assert parse_powercfg_hex(out) == 100


def test_parse_hex_sem_valor():
    with pytest.raises(ValueError):
        parse_powercfg_hex("sem nada aqui")
