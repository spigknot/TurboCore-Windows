"""Icone da tray: o MESMO artwork do executavel (assets/chip.ico/png).

Cobre layout dev (raiz do projeto) e congelado PyInstaller 6 (datas em
sys._MEIPASS, i.e. `_internal/` no onedir). Renderiza em 64x64 RGBA.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

TRAY_SIZE = 64
_FALLBACK_COLOR = (16, 122, 87)


def load_tray_image(path: Path, size: int = TRAY_SIZE) -> Image.Image:
    """Abre chip.ico/png, pega o maior frame e normaliza p/ size x size RGBA."""
    img = Image.open(path)
    try:
        frames = getattr(img, "n_frames", 1) or 1
        if frames > 1:
            best, best_px = 0, -1
            for i in range(frames):
                img.seek(i)
                px = img.size[0] * img.size[1]
                if px > best_px:
                    best, best_px = i, px
            img.seek(best)
    except Exception:
        pass
    img = img.convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    return img


def artwork_candidates(filename: str) -> list[Path]:
    """Onde procurar um artwork (chip.*, appwin.*), do mais especifico ao generico."""
    cands: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # congelado: onedir (_internal) ou onefile (temp)
        cands.append(Path(meipass) / "assets" / filename)
    if getattr(sys, "frozen", False):  # dir do exe (layouts antigos/instalados)
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "assets" / filename)
    import turbocore.main as main_mod  # __file__ real do modulo (mockavel em teste)
    here = Path(main_mod.__file__).resolve()
    cands.append(here.parent.parent.parent / "assets" / filename)  # dev: raiz
    cands.append(Path(f"assets/{filename}"))
    return cands


def icon_candidates() -> list[Path]:
    """Onde procurar chip.ico/png, do mais especifico ao mais generico."""
    return artwork_candidates("chip.png") + artwork_candidates("chip.ico")


def load_icon() -> Image.Image:
    for cand in icon_candidates():
        try:
            if cand.exists():
                return load_tray_image(cand)
        except Exception:
            continue
    # ultimo recurso p/ nunca quebrar o boot (era o quadrado verde do print)
    return Image.new("RGB", (TRAY_SIZE, TRAY_SIZE), _FALLBACK_COLOR)


# Ícone âmbar preenchido, com bordas suaves no tamanho final.
BOLT_FILL = (222, 158, 22, 255)
_BOLT_POINTS = ((0.60, 0.06), (0.23, 0.55), (0.46, 0.55),
                (0.38, 0.94), (0.77, 0.41), (0.54, 0.41))


def bolt_image(size_px: int = 16, supersample: int = 4) -> Image.Image:
    """Raio RGBA size_px x size_px, nítido via supersampling."""
    from PIL import ImageDraw
    big = max(int(size_px) * max(int(supersample), 1), 8)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pts = [(x * big, y * big) for x, y in _BOLT_POINTS]
    draw.polygon(pts, fill=BOLT_FILL)
    if (big, big) != (size_px, size_px):
        img = img.resize((size_px, size_px), Image.LANCZOS)
    return img


def apply_button_image(size_px: int = 32, state: str = "normal") -> Image.Image:
    """Botão arredondado com raio, renderizado a 4× para evitar serrilhado."""
    from PIL import ImageDraw
    scale = 4
    size = size_px * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill, border = {
        "normal": ("#fafcfa", "#cbd3cc"),
        "hover": ("#fff9e9", "#d7ba74"),
        "pressed": ("#f5ecd2", "#c6a65b"),
        "focus": ("#fafcfa", "#16833a"),
    }.get(state, ("#fafcfa", "#cbd3cc"))
    draw.rounded_rectangle((scale, 2 * scale, size - scale, size - scale),
                           radius=8 * scale, fill="#dfe3df")
    draw.rounded_rectangle((scale, scale, size - scale, size - 2 * scale),
                           radius=8 * scale, fill=fill, outline=border, width=scale)
    bolt = bolt_image(20 * scale, supersample=1)
    offset = (size - bolt.width) // 2
    img.alpha_composite(bolt, (offset, offset - scale // 2))
    return img.resize((size_px, size_px), Image.Resampling.LANCZOS)
