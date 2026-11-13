"""Draws the product images of the fictitious catalogue: flat illustrations, one per style and colour.

The supplier files point at these images. They are published with the portfolio site, so a Shopify
import can download them like any supplier's image links. Every image the two files mention is drawn:
one per colour, plus a line-up of all colours and a close-up per style.

    python -m vendorfeed.art
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .clean import COLOR_OF, text
from .generate import CDN, INPUT
from .read import read_supplier

OUT = Path(__file__).resolve().parent.parent / "img" / "products"
S, W = 2, 900                       # supersampling factor, output size in pixels
BG = (242, 241, 237)
RGB = {"Black": (40, 40, 42), "Navy": (38, 52, 82), "Charcoal": (72, 74, 78), "Heather Grey": (160, 162, 165),
       "Forest Green": (44, 82, 58), "Olive": (98, 106, 62), "Rust": (176, 84, 52), "Ochre": (196, 146, 52),
       "Sand": (205, 186, 150), "Slate Blue": (92, 116, 146), "White": (236, 236, 232), "Red": (168, 44, 44)}


def shade(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def P(pts):
    return [(x * S, y * S) for x, y in pts]


def B(x0, y0, x1, y1):
    return [x0 * S, y0 * S, x1 * S, y1 * S]


def outline(c):
    return shade(c, 0.72) if sum(c) > 150 else shade(c, 1.6)


def tee(d, c, name):
    body = [(300, 210), (410, 168), (450, 200), (500, 214), (550, 200), (590, 168), (700, 210), (830, 340), (745, 425),
            (680, 380), (680, 830), (320, 830), (320, 380), (255, 425), (170, 340)]
    d.polygon(P(body), fill=c, outline=outline(c), width=4 * S)
    d.arc(B(428, 150, 572, 245), 15, 165, fill=outline(c), width=10 * S)
    if "POCKET" in name:
        d.rectangle(B(540, 330, 620, 420), outline=outline(c), width=4 * S)


def long_sleeve(d, c, name, hood=False):
    if hood:
        d.ellipse(B(370, 95, 630, 330), fill=shade(c, 0.85), outline=outline(c), width=4 * S)
    body = [(300, 210), (410, 168), (450, 200), (500, 214), (550, 200), (590, 168), (700, 210), (765, 300), (810, 780),
            (735, 795), (680, 430), (680, 830), (320, 830), (320, 430), (265, 795), (190, 780), (235, 300)]
    d.polygon(P(body), fill=c, outline=outline(c), width=4 * S)
    if hood:
        d.line(P([(470, 215), (465, 330)]), fill=outline(c), width=5 * S)
        d.line(P([(530, 215), (535, 330)]), fill=outline(c), width=5 * S)
        d.polygon(P([(380, 600), (620, 600), (655, 730), (345, 730)]), fill=shade(c, 0.88), outline=outline(c), width=3 * S)
    else:
        d.arc(B(428, 150, 572, 245), 15, 165, fill=outline(c), width=10 * S)
    if "ZIP" in name:
        d.line(P([(500, 214), (500, 380)]), fill=outline(c), width=6 * S)
    d.rectangle(B(320, 800, 680, 830), fill=shade(c, 0.88))


def sock(d, c, name):
    shape = [(400, 140), (580, 140), (585, 560), (770, 680), (790, 760), (730, 825), (560, 825), (430, 730), (398, 600)]
    d.polygon(P(shape), fill=c, outline=outline(c), width=4 * S)
    d.rectangle(B(402, 142, 578, 230), fill=shade(c, 0.85))
    for x in range(418, 578, 22):
        d.line(P([(x, 146), (x, 226)]), fill=outline(c), width=3 * S)
    d.polygon(P([(704, 688), (770, 680), (790, 760), (730, 825), (690, 825)]), fill=shade(c, 0.82))
    d.polygon(P([(399, 605), (450, 650), (470, 768), (430, 730)]), fill=shade(c, 0.82))


def beanie(d, c, name):
    if "POM" in name:
        d.ellipse(B(445, 120, 555, 230), fill=shade(c, 1.15), outline=outline(c), width=3 * S)
    d.chord(B(300, 210, 700, 770), 180, 360, fill=c, outline=outline(c), width=4 * S)
    d.rectangle(B(302, 488, 698, 560), fill=c)
    d.rounded_rectangle(B(282, 540, 718, 700), radius=24 * S, fill=shade(c, 0.86), outline=outline(c), width=4 * S)
    for x in range(305, 700, 26):
        d.line(P([(x, 552), (x, 688)]), fill=outline(c), width=2 * S)


def glove(d, c, name):
    for i, top in enumerate((250, 205, 215, 270)):
        x = 388 + i * 64
        d.rounded_rectangle(B(x, top, x + 58, 520), radius=29 * S, fill=c, outline=outline(c), width=4 * S)
    for color, half in ((outline(c), 33), (c, 29)):         # thumb: a thick stroke with a rounded tip
        d.line(P([(420, 660), (318, 488)]), fill=color, width=2 * half * S)
        d.ellipse(B(318 - half, 488 - half, 318 + half, 488 + half), fill=color)
    d.rounded_rectangle(B(380, 440, 646, 800), radius=46 * S, fill=c, outline=outline(c), width=4 * S)
    d.rounded_rectangle(B(384, 770, 642, 860), radius=12 * S, fill=shade(c, 0.85), outline=outline(c), width=4 * S)


def backpack(d, c, name):
    d.arc(B(440, 150, 560, 270), 180, 360, fill=outline(c), width=14 * S)
    d.rounded_rectangle(B(330, 220, 670, 850), radius=90 * S, fill=c, outline=outline(c), width=4 * S)
    d.rounded_rectangle(B(330, 220, 670, 440), radius=90 * S, fill=shade(c, 0.86), outline=outline(c), width=4 * S)
    d.rounded_rectangle(B(390, 560, 610, 790), radius=40 * S, fill=shade(c, 0.88), outline=outline(c), width=4 * S)
    d.line(P([(500, 440), (500, 520)]), fill=outline(c), width=6 * S)


def bottle(d, c, name):
    d.rounded_rectangle(B(395, 300, 605, 870), radius=70 * S, fill=c, outline=outline(c), width=4 * S)
    d.rectangle(B(440, 230, 560, 310), fill=shade(c, 0.9))
    d.rounded_rectangle(B(420, 140, 580, 240), radius=22 * S, fill=(58, 58, 58))
    d.rounded_rectangle(B(425, 420, 455, 760), radius=14 * S, fill=shade(c, 1.25))


DRAW = {"SOX": sock, "TEE": tee, "HOOD": lambda d, c, n: long_sleeve(d, c, n, hood=True), "BASE": long_sleeve,
        "HAT": beanie, "GLV": glove, "PACK": backpack, "BTL": bottle}


def _font(size):
    for f in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def canvas():
    img = Image.new("RGB", (1000 * S, 1000 * S), BG)
    d = ImageDraw.Draw(img)
    d.ellipse(B(280, 875, 720, 915), fill=shade(BG, 0.9))
    return img, d


def mark(img):
    d = ImageDraw.Draw(img)
    d.polygon([(40, 960), (62, 924), (84, 960)], fill=(150, 150, 146))
    d.text((94, 930), "HARROW PEAK", fill=(150, 150, 146), font=_font(26))
    d.text((760, 936), "illustration", fill=(175, 175, 170), font=_font(20))
    return img


def product(code, color, name):
    img, d = canvas()
    DRAW[code](d, RGB.get(color, (128, 128, 128)), name.upper())
    return mark(img.resize((1000, 1000), Image.LANCZOS))


def lineup(code, colors, name):
    n = len(colors)
    cols = 1 if n == 1 else 2 if n in (2, 4) else 3
    tw = 940 // cols
    th = int(tw * 0.84)
    tiles = [product(code, c, name).crop((80, 80, 920, 920)).resize((tw, tw), Image.LANCZOS).crop((0, 0, tw, th))
             for c in colors]
    sheet = Image.new("RGB", (1000, 1000), BG)
    rows = (n + cols - 1) // cols
    y0 = (960 - rows * th) // 2
    for i, t in enumerate(tiles):
        r, k = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        x0 = (1000 - in_row * tw) // 2
        sheet.paste(t, (x0 + k * tw, y0 + r * th))
    return mark(sheet)


def closeup(code, color, name):
    return mark(product(code, color, name).crop((250, 150, 750, 650)).resize((1000, 1000), Image.LANCZOS))


def save(img, name):
    img.resize((W, W), Image.LANCZOS).quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(OUT / name, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    styles: dict[str, dict] = {}
    for f in sorted(INPUT.glob("*.xlsx")):
        raw, _ = read_supplier(f)
        rows = raw[raw["kind"] == "product"]
        for _, r in rows.iterrows():
            st = styles.setdefault(str(r["style"]).strip(), {"code": str(r["category"]).strip().upper(), "colors": {},
                                                             "name": str(r["description"])})
            color = COLOR_OF.get(text(r["color"]).upper())
            url = text(r["image1"])
            if color and url:
                st["colors"].setdefault(color, url.rsplit("/", 1)[-1])
    n = 0
    for style, st in sorted(styles.items()):
        name = st["name"]
        for color, fname in st["colors"].items():
            save(product(st["code"], color, name), fname)
            n += 1
        colors = list(st["colors"])
        if colors:
            save(lineup(st["code"], colors, name), f"{style}-detail-1.png")
            save(closeup(st["code"], colors[0], name), f"{style}-detail-2.png")
            n += 2
    size = sum(p.stat().st_size for p in OUT.glob("*.png"))
    print(f"{n} images in {OUT} ({size / 1e6:.1f} MB); served from {CDN}")


if __name__ == "__main__":
    main()
