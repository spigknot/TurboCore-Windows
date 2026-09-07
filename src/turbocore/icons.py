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


def icon_candidates() -> list[Path]:
    """Onde procurar chip.ico/png, do mais especifico ao mais generico."""
    cands: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # congelado: onedir (_internal) ou onefile (temp)
        cands.append(Path(meipass) / "assets" / "chip.png")
        cands.append(Path(meipass) / "assets" / "chip.ico")
    if getattr(sys, "frozen", False):  # dir do exe (layouts antigos/instalados)
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "assets" / "chip.png")
        cands.append(exe_dir / "assets" / "chip.ico")
    import turbocore.main as main_mod  # __file__ real do modulo (mockavel em teste)
    here = Path(main_mod.__file__).resolve()
    cands.append(here.parent.parent.parent / "assets" / "chip.png")  # dev: raiz
    cands.append(here.parent.parent.parent / "assets" / "chip.ico")
    cands.append(Path("assets/chip.png"))
    return cands


def load_icon() -> Image.Image:
    for cand in icon_candidates():
        try:
            if cand.exists():
                return load_tray_image(cand)
        except Exception:
            continue
    # ultimo recurso p/ nunca quebrar o boot (era o quadrado verde do print)
    return Image.new("RGB", (TRAY_SIZE, TRAY_SIZE), _FALLBACK_COLOR)
