"""Gera icone de chip eletronico em alta resolucao (PNG 256 + ICO multi-size)."""
from PIL import Image, ImageDraw

SIZE = 256


def draw_chip(s=SIZE) -> Image.Image:
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 256  # unidade escalavel
    # fundo arredondado escuro
    d.rounded_rectangle([8 * u, 8 * u, 248 * u, 248 * u], radius=44 * u,
                        fill=(24, 28, 36, 255), outline=(90, 200, 255, 255), width=int(6 * u))
    # pinos dourados (6 por lado)
    pin = (212, 175, 55, 255)
    for i in range(6):
        y = (52 + i * 28) * u
        d.rounded_rectangle([0, y, 22 * u, y + 14 * u], radius=4 * u, fill=pin)  # esq
        d.rounded_rectangle([234 * u, y, 256 * u, y + 14 * u], radius=4 * u, fill=pin)  # dir
        x = (52 + i * 28) * u
        d.rounded_rectangle([x, 0, x + 14 * u, 22 * u], radius=4 * u, fill=pin)  # topo
        d.rounded_rectangle([x, 234 * u, x + 14 * u, 256 * u], radius=4 * u, fill=pin)  # base
    # die central verde-azulado + trilhas
    d.rounded_rectangle([64 * u, 64 * u, 192 * u, 192 * u], radius=18 * u,
                        fill=(16, 122, 87, 255), outline=(255, 255, 255, 255), width=int(5 * u))
    trace = (255, 255, 255, 230)
    w = int(5 * u)
    for x0, y0, x1, y1 in [(80 * u, 128 * u, 120 * u, 128 * u), (136 * u, 128 * u, 176 * u, 128 * u),
                           (128 * u, 80 * u, 128 * u, 112 * u), (128 * u, 144 * u, 128 * u, 176 * u)]:
        d.line([x0, y0, x1, y1], fill=trace, width=w)
    for cx, cy in [(80 * u, 128 * u), (176 * u, 128 * u), (128 * u, 80 * u), (128 * u, 176 * u)]:
        d.ellipse([cx - 8 * u, cy - 8 * u, cx + 8 * u, cy + 8 * u],
                  fill=(255, 215, 0, 255), outline=(255, 255, 255, 255), width=int(3 * u))
    # nucleo (sem brilho oval: em 16px virava mancha)
    d.rounded_rectangle([100 * u, 100 * u, 156 * u, 156 * u], radius=12 * u,
                        fill=(10, 40, 70, 255), outline=(90, 200, 255, 255), width=int(6 * u))
    # furo marcador pino 1
    d.ellipse([72 * u, 72 * u, 90 * u, 90 * u], fill=(255, 255, 255, 255))
    return img


if __name__ == "__main__":
    from pathlib import Path
    out = Path(__file__).parent
    img = draw_chip()
    img.save(out / "chip.png")
    img.save(out / "chip.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok:", out / "chip.ico")
