"""load_icon deve achar o mesmo artwork do exe em layout dev e congelado."""
import sys

from PIL import Image

from turbocore import icons
from turbocore import main as main_mod


def _make_icon(path, size=(128, 128), color=(200, 30, 30, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)
    return path


def test_dev_layout_encontra_assets(tmp_path, monkeypatch):
    _make_icon(tmp_path / "assets" / "chip.png")
    monkeypatch.setattr(main_mod, "__file__", str(tmp_path / "src" / "turbocore" / "main.py"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    img = icons.load_icon()
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((32, 32))[:3] == (200, 30, 30)


def test_frozen_onedir_usameipass(tmp_path, monkeypatch):
    _make_icon(tmp_path / "dist" / "TurboCore" / "_internal" / "assets" / "chip.png")
    monkeypatch.setattr(
        main_mod, "__file__",
        str(tmp_path / "dist" / "TurboCore" / "_internal" / "turbocore" / "main.pyc"))
    monkeypatch.setattr(sys, "_MEIPASS",
                        str(tmp_path / "dist" / "TurboCore" / "_internal"), raising=False)
    img = icons.load_icon()
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((32, 32))[:3] == (200, 30, 30)


def test_load_tray_image_redimensiona_e_converte(tmp_path):
    src = _make_icon(tmp_path / "big.png", size=(256, 256), color=(10, 20, 30, 255))
    img = icons.load_tray_image(src)
    assert img.size == (64, 64) and img.mode == "RGBA"
