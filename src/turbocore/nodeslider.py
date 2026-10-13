"""Slider discreto com trilho verde, marcações e desenho antialias.

Substitui o ttk.Scale no painel: as únicas posições possíveis são os nós, e a
seleção é atraída pelo nó mais próximo enquanto o usuário arrasta
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
SLIDER_HEIGHT = 28
LINE_WIDTH = 3
NODE_RADIUS = 1.5
THUMB_RADIUS = 7
EDGE_PAD = THUMB_RADIUS + 3

LINE_COLOR = "#d5ddd6"
NODE_COLOR = "#a2afa5"
NODE_ACTIVE_COLOR = "#f0f7f2"
THUMB_COLOR = "#ffffff"
THUMB_OUTLINE = "#16833a"


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
    """Trilho desenhado a 4×, com mouse e teclado limitados às opções válidas."""

    def __init__(self, master, count: int, length: int = 240, command=None,
                 **kwargs):
        kwargs.setdefault("height", SLIDER_HEIGHT)
        kwargs.setdefault("width", length)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("takefocus", True)
        kwargs.setdefault("cursor", "hand2")
        super().__init__(master, **kwargs)
        self.configure(bg=master.cget("bg"))
        self._count = max(int(count), 1)
        self._command = command
        self._index = 0
        self._applied = None
        self._hover = self._focused = self._dragging = False
        self._photo = None
        self._image_item = self.create_image(0, 0, anchor="nw")
        self._positions: list[float] = []
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._feedback("_hover", True))
        self.bind("<Leave>", lambda e: self._feedback("_hover", False))
        self.bind("<FocusIn>", lambda e: self._feedback("_focused", True))
        self.bind("<FocusOut>", lambda e: self._feedback("_focused", False))
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
        from PIL import Image, ImageDraw, ImageTk
        if not self._positions:
            return
        scale = 4
        width = max(self.winfo_width(), int(self.cget("width")), 1)
        background = tuple(v // 257 for v in self.winfo_rgb(self.cget("bg")))
        img = Image.new("RGB", (width * scale, SLIDER_HEIGHT * scale), background)
        draw = ImageDraw.Draw(img)

        def circle(x, y, radius, fill, outline=None, stroke=1):
            draw.ellipse(((x - radius) * scale, (y - radius) * scale,
                          (x + radius) * scale, (y + radius) * scale),
                         fill=fill, outline=outline, width=round(stroke * scale))

        mid = SLIDER_HEIGHT / 2.0
        first, last = self._positions[0], self._positions[-1]
        tx = self._positions[self._index]
        draw.rounded_rectangle((first * scale, (mid - LINE_WIDTH / 2) * scale,
                                last * scale, (mid + LINE_WIDTH / 2) * scale),
                               radius=LINE_WIDTH * scale / 2, fill=LINE_COLOR)
        if tx > first:
            draw.rounded_rectangle((first * scale, (mid - LINE_WIDTH / 2) * scale,
                                    tx * scale, (mid + LINE_WIDTH / 2) * scale),
                                   radius=LINE_WIDTH * scale / 2, fill=THUMB_OUTLINE)
        for i, px in enumerate(self._positions):
            if i == self._index:
                continue
            circle(px, mid, NODE_RADIUS,
                   NODE_ACTIVE_COLOR if i < self._index else NODE_COLOR)
        if self._applied is not None and self._applied != self._index:
            applied = max(0, min(self._applied, self._count - 1))
            circle(self._positions[applied], mid + 9, 1.5, THUMB_OUTLINE)
        if self._hover or self._focused:
            circle(tx, mid, THUMB_RADIUS + 3, "#dcebe0")
        circle(tx, mid + .75, THUMB_RADIUS, "#bdcbbf")
        circle(tx, mid, THUMB_RADIUS,
               THUMB_OUTLINE if self._dragging else THUMB_COLOR,
               THUMB_OUTLINE, 1.5)
        circle(tx, mid, 2, "#ffffff" if self._dragging else THUMB_OUTLINE)
        img = img.resize((width, SLIDER_HEIGHT), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(img, master=self)
        self.itemconfigure(self._image_item, image=self._photo)

    def _feedback(self, attribute: str, value: bool) -> None:
        setattr(self, attribute, value)
        self._redraw()

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
        self._dragging = True
        self.focus_set()
        self._select(self._index_at(event.x), fire=True)

    def _on_drag(self, event) -> None:
        self._select(self._index_at(event.x), fire=True)

    def _on_release(self, _event) -> None:
        self._dragging = False
        self._redraw()

    def _on_key_left(self, _event) -> str:
        self._select(self._index - 1, fire=True)
        return "break"

    def _on_key_right(self, _event) -> str:
        self._select(self._index + 1, fire=True)
        return "break"
