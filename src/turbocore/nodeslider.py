"""Slider de nós (discreta): traço fino + um nó cinza por opção + bolinha azul.

Substitui o ttk.Scale no painel: as únicas posições possíveis são os nós, e a
bolinha azul é atraída pelo nó mais próximo enquanto o usuário arrasta
(comportamento "magnético"), em vez de deslizar fluida.

A API imita o ttk.Scale que ela substitui — get()/set()/command — para o
painel não mudar sua lógica:

  * get()  -> índice atual como float (compatível com int(round(float(...))))
  * set(i) -> move a bolinha SEM disparar command (evita recursão command->set)
  * command é disparada apenas por interação real do usuário (arrastar,
    clicar num nó, setas do teclado).
"""
from __future__ import annotations

import tkinter as tk

# Geometria e cores do desenho.
SLIDER_HEIGHT = 26      # altura do canvas (traço + bolinhas)
LINE_WIDTH = 2          # espessura do traço horizontal
NODE_RADIUS = 4         # raio do nó cinza
THUMB_RADIUS = 7        # raio da bolinha azul (maior: fica sobre o nó)
EDGE_PAD = THUMB_RADIUS + 2   # folga para a bolinha não ser cortada nas pontas

LINE_COLOR = "#c8cdd2"
NODE_COLOR = "#9aa4ad"
NODE_ACTIVE_COLOR = "#5b6672"   # nó já aplicado (à esquerda da seleção)
THUMB_COLOR = "#1f6feb"
THUMB_OUTLINE = "#1553b8"


def node_positions(count: int, width: int, pad: int = EDGE_PAD) -> list[float]:
    """X dos nós, igualmente espaçados entre `pad` e `width - pad`."""
    if count <= 0:
        return []
    usable = max(width - 2 * pad, 1)
    if count == 1:
        return [pad + usable / 2.0]
    step = usable / (count - 1)
    return [pad + step * i for i in range(count)]


def nearest_index(x: float, positions: list[float]) -> int:
    """Índice do nó mais próximo de `x` (a atração magnética)."""
    if not positions:
        return 0
    best, best_d = 0, abs(x - positions[0])
    for i, px in enumerate(positions[1:], start=1):
        d = abs(x - px)
        if d < best_d:
            best, best_d = i, d
    return best


class NodeSlider(tk.Canvas):
    """Canvas com traço, nós e bolinha azul arrastável com snap por nó."""

    def __init__(self, master, count: int, length: int = 240, command=None,
                 **kwargs):
        kwargs.setdefault("height", SLIDER_HEIGHT)
        kwargs.setdefault("width", length)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        super().__init__(master, **kwargs)
        self.configure(bg=master.cget("bg"))
        self._count = max(int(count), 1)
        self._command = command
        self._index = 0
        self._applied = None
        self._positions: list[float] = []
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Left>", self._on_key_left)
        self.bind("<Right>", self._on_key_right)
        self.bind("<Home>", lambda e: self._select(0, fire=True))
        self.bind("<End>", lambda e: self._select(self._count - 1, fire=True))
        self.after_idle(self._relayout)

    # -- API compatível com ttk.Scale ------------------------------------
    def get(self) -> float:
        return float(self._index)

    def set(self, index) -> None:
        """Move a bolinha programaticamente, sem disparar command."""
        try:
            idx = int(round(float(str(index).replace(",", "."))))
        except (TypeError, ValueError):
            return
        self._select(max(0, min(idx, self._count - 1)), fire=False)

    def set_applied(self, index) -> None:
        """Marca o nó do valor já aplicado (nó escurecido). None = sem marca."""
        try:
            value = None if index is None else int(index)
        except (TypeError, ValueError):
            value = None
        if value != self._applied:
            self._applied = value
            self._redraw()

    # -- desenho ----------------------------------------------------------
    def _relayout(self) -> None:
        self._positions = node_positions(self._count, self.winfo_width())
        self._redraw()

    def _on_configure(self, _event) -> None:
        self._relayout()

    def _redraw(self) -> None:
        self.delete("all")
        if not self._positions:
            return
        mid = SLIDER_HEIGHT / 2.0
        first, last = self._positions[0], self._positions[-1]
        self.create_line(first, mid, last, mid, fill=LINE_COLOR,
                         width=LINE_WIDTH, capstyle="round")
        for i, px in enumerate(self._positions):
            if i == self._index:
                continue                      # a bolinha azul cobre este nó
            color = (NODE_ACTIVE_COLOR if self._applied is not None
                     and i <= self._applied else NODE_COLOR)
            self.create_oval(px - NODE_RADIUS, mid - NODE_RADIUS,
                             px + NODE_RADIUS, mid + NODE_RADIUS,
                             fill=color, outline="")
        tx = self._positions[self._index]
        self.create_oval(tx - THUMB_RADIUS, mid - THUMB_RADIUS,
                         tx + THUMB_RADIUS, mid + THUMB_RADIUS,
                         fill=THUMB_COLOR, outline=THUMB_OUTLINE, width=1)

    # -- interação --------------------------------------------------------
    def _select(self, index: int, fire: bool) -> None:
        index = max(0, min(index, self._count - 1))
        changed = index != self._index
        self._index = index
        self._redraw()
        if changed and fire and self._command is not None:
            self._command(str(float(index)))

    def _index_at(self, x: int) -> int:
        return nearest_index(float(x), self._positions)

    def _on_press(self, event) -> None:
        self.focus_set()
        self._select(self._index_at(event.x), fire=True)

    def _on_drag(self, event) -> None:
        self._select(self._index_at(event.x), fire=True)

    def _on_key_left(self, _event) -> str:
        self._select(self._index - 1, fire=True)
        return "break"

    def _on_key_right(self, _event) -> str:
        self._select(self._index + 1, fire=True)
        return "break"
