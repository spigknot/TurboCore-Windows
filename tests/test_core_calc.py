import pytest

from turbocore.core_calc import (
    build_core_options,
    min_percent_for_one_thread,
    parse_powercfg_ac_hex,
    parse_powercfg_hex,
    percent_for_cores,
)


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


PT_QH_56 = (
    "GUID de Configura\xe7\xe3o de Energia: ea062031-0e34-4ff1-9b6d-eb1059334028\r\n"
    "    \xcdndice de Configura\xe7\xf5es de Correntes Alternadas Atuais: 0x00000038\r\n"
    "    \xcdndice de Configura\xe7\xf5es de Correntes Cont\xednuas Atuais: 0x00000064\r\n"
)

EN_QH_56 = (
    "Power Setting GUID: ea062031-0e34-4ff1-9b6d-eb1059334028\r\n"
    "    Current AC Power Setting Index: 0x00000038\r\n"
    "    Current DC Power Setting Index: 0x00000064\r\n"
)


def test_parse_ac_prefere_linha_ac_ptbr():
    # AC=56 mas DC=100: deve retornar 56, nao o ultimo hex
    assert parse_powercfg_ac_hex(PT_QH_56) == 56


def test_parse_ac_prefere_linha_ac_en():
    assert parse_powercfg_ac_hex(EN_QH_56) == 56


def test_parse_ac_sem_linha_ac():
    with pytest.raises(ValueError):
        parse_powercfg_ac_hex("0x00000064 sem rotulo")


def test_min_uma_thread_36_logicos():
    # 1 thread de 36 = 2.77% -> teto 3
    assert min_percent_for_one_thread(36) == 3


def test_min_uma_thread_8_logicos():
    assert min_percent_for_one_thread(8) == 13


def test_min_uma_thread_1_logico():
    assert min_percent_for_one_thread(1) == 100


def test_min_nunca_acima_do_max():
    # min(1 thread) <= max(1 core) em qualquer topologia
    for physical, logical in [(18, 36), (6, 6), (4, 8), (2, 2), (8, 16)]:
        assert min_percent_for_one_thread(logical) <= percent_for_cores(1, physical)


def test_min_invalido():
    with pytest.raises(ValueError):
        min_percent_for_one_thread(0)
