"""Imagery crop with a local metre grid (east/north offsets from a reference lon/lat) for digitising."""
import sys, os, math, warnings
warnings.simplefilter('ignore')
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance
from render import sample
from tc import T, TI

S = os.path.dirname(os.path.abspath(__file__))


def crop(lon, lat, half, px=1100, step=5.0, lines=None, enhance=1.6, label=True, x0=None, y0=None):
    cx, cy = T(lon, lat)
    ox, oy = (cx, cy) if x0 is None else (x0, y0)
    res = 2 * half / px
    xs = cx - half + (np.arange(px) + 0.5) * res
    ys = cy + half - (np.arange(px) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    im = Image.fromarray(sample(X, Y).astype('uint8'))
    im = ImageEnhance.Contrast(im).enhance(enhance)
    dr = ImageDraw.Draw(im)
    P = lambda x, y: ((x - (cx - half)) / res, ((cy + half) - y) / res)
    if step:
        e0 = math.ceil((cx - half - ox) / step) * step
        while ox + e0 < cx + half:
            x = P(ox + e0, 0)[0]
            dr.line([(x, 0), (x, px)], fill=(255, 255, 255) if e0 % (step * 2) == 0 else (190, 190, 190), width=1)
            if label and e0 % (step * 2) == 0:
                dr.text((x + 2, 2), f"{e0:.0f}", fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0), font_size=13)
            e0 += step
        n0 = math.ceil((cy - half - oy) / step) * step
        while oy + n0 < cy + half:
            y = P(0, oy + n0)[1]
            dr.line([(0, y), (px, y)], fill=(255, 255, 255) if n0 % (step * 2) == 0 else (190, 190, 190), width=1)
            if label and n0 % (step * 2) == 0:
                dr.text((2, y + 2), f"{n0:.0f}", fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0), font_size=13)
            n0 += step
    for pts, col in (lines or []):
        dr.line([P(ox + a, oy + b) for a, b in pts], fill=col, width=1)
    return im


if __name__ == '__main__':
    lon, lat, half = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    out = sys.argv[4]
    crop(lon, lat, half, step=float(sys.argv[5]) if len(sys.argv) > 5 else 5.0).save(out, quality=93)
    print(out)
