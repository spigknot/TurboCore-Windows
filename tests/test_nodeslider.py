"""Testes da NodeSlider (geometria pura + API sem depender de eventos)."""
import pytest

from turbocore.nodeslider import (EDGE_PAD, SLIDER_HEIGHT, THUMB_RADIUS,
                                  NodeSlider, nearest_index, node_positions)


def test_node_positions_espacamento_e_limites():
    pos = node_positions(10, 240)
    assert len(pos) == 10
    assert pos[0] == pytest.approx(EDGE_PAD)
    assert pos[-1] == pytest.approx(240 - EDGE_PAD)
    # igualmente espaçados
    steps = [pos[i + 1] - pos[i] for i in range(9)]
    assert max(steps) - min(steps) < 1e-6


def test_node_positions_casos_degenerados():
    assert node_positions(0, 240) == []
    assert len(node_positions(1, 240)) == 1
    assert node_positions(1, 240)[0] == pytest.approx(120)


def test_nearest_index_atracao_magnetica():
    pos = [0.0, 100.0, 200.0]
    assert nearest_index(49.0, pos) == 0
    assert nearest_index(51.0, pos) == 1
    assert nearest_index(150.0, pos) == 1
    assert nearest_index(151.0, pos) == 2
    assert nearest_index(-999.0, pos) == 0
    assert nearest_index(9999.0, pos) == 2
    assert nearest_index(5.0, []) == 0


def test_slider_so_para_em_noes(tk_root):
    s = NodeSlider(tk_root, count=5, length=200)
    s.update_idletasks()
    s._positions = node_positions(5, 200)
    fired: list[str] = []
    s._command = fired.append
    # arrastar para um x entre nós => para no nó mais próximo (sem fluidez)
    mid_between = (s._positions[1] + s._positions[2]) / 2.0 + 5
    s._select(nearest_index(mid_between, s._positions), fire=True)
    assert s.get() == 2.0
    assert fired == ["2.0"]
    # set() programático NÃO dispara command (sem recursão)
    fired.clear()
    s.set(4)
    assert s.get() == 4.0
    assert fired == []
    s.destroy()


def test_set_trava_limites_e_aceita_str(tk_root):
    s = NodeSlider(tk_root, count=3, length=120)
    s.set(99)
    assert s.get() == 2.0
    s.set(-5)
    assert s.get() == 0.0
    s.set("1,0")
    assert s.get() == 1.0
    s.set("abc")          # inválido: mantém atual
    assert s.get() == 1.0
    s.destroy()


def test_command_so_dispara_em_mudanca_real(tk_root):
    s = NodeSlider(tk_root, count=4, length=160)
    fired: list[str] = []
    s._command = fired.append
    s._select(1, fire=True)
    s._select(1, fire=True)   # mesmo índice: não re-dispara
    assert fired == ["1.0"]
    s.destroy()


def test_altura_estreita():
    assert SLIDER_HEIGHT <= 30
    assert THUMB_RADIUS < SLIDER_HEIGHT / 2.0
