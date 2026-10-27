"""앱 아이콘 생성(PIL): 어두운 둥근 사각형 + 노란 기둥 점 + 거더(굵은 선)·보(가는 선) 격자.
python scripts/make_icon.py → assets/icon.png(256) · assets/tray.png(32)
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")


def render(size):
    s = 8  # 슈퍼샘플
    S = size * s
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = S * 0.22
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=(28, 33, 46, 255))
    m = S * 0.2
    xs = [m, S / 2, S - m]
    ys = [m, S / 2, S - m]
    girder = (255, 205, 60, 255)
    beam = (120, 170, 255, 255)
    gw = max(2, int(S * 0.055))
    bw = max(1, int(S * 0.025))
    for y in ys:
        d.line([(xs[0], y), (xs[-1], y)], fill=girder, width=gw)
    for x in xs:
        d.line([(x, ys[0]), (x, ys[-1])], fill=girder, width=gw)
    for i in range(2):
        for j in range(2):
            cx = (xs[i] + xs[i + 1]) / 2
            d.line([(cx, ys[j]), (cx, ys[j + 1])], fill=beam, width=bw)
    cr = S * 0.05
    for x in xs:
        for y in ys:
            d.ellipse([x - cr, y - cr, x + cr, y + cr], fill=(255, 255, 255, 255))
    return im.resize((size, size), Image.LANCZOS)


os.makedirs(OUT, exist_ok=True)
render(256).save(os.path.join(OUT, "icon.png"))
render(32).save(os.path.join(OUT, "tray.png"))
print("icons written to", os.path.abspath(OUT))
