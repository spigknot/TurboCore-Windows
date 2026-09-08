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


# Raio do botão Aplicar: desenhado grande (supersample) e reduzido com
# LANCZOS para bordas suaves mesmo em 14-16px. Amarelo âmbar + contorno
# escuro: legível sobre o cinza-claro do tema clam.
BOLT_FILL = (255, 195, 0, 255)
BOLT_OUTLINE = (122, 82, 0, 255)
_BOLT_POINTS = ((0.60, 0.05), (0.30, 0.55), (0.47, 0.55),
                (0.40, 0.95), (0.72, 0.45), (0.54, 0.45))


def bolt_image(size_px: int = 16, supersample: int = 4) -> Image.Image:
    """Raio RGBA size_px x size_px, nítido via supersampling."""
    from PIL import ImageDraw
    big = max(int(size_px) * max(int(supersample), 1), 8)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pts = [(x * big, y * big) for x, y in _BOLT_POINTS]
    draw.polygon(pts, fill=BOLT_FILL)
    draw.polygon(pts, outline=BOLT_OUTLINE, width=max(big // 32, 2))
    if (big, big) != (size_px, size_px):
        img = img.resize((size_px, size_px), Image.LANCZOS)
    return img
