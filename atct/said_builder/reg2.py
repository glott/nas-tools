"""Independent registration check: correlate the white runway-marking polygons with image brightness."""
import sys, warnings
warnings.simplefilter('ignore')
import numpy as np
from PIL import Image, ImageDraw
from tc import TC, T, TI
from render import sample
from scipy.ndimage import gaussian_filter

RES = 0.15


def window_shift(marks, cx, cy, half=60.0, maxs=3.5):
    n = int(2 * half / RES)
    xs = cx - half + (np.arange(n) + 0.5) * RES
    ys = cy + half - (np.arange(n) + 0.5) * RES
    X, Y = np.meshgrid(xs, ys)
    lum = sample(X, Y).mean(-1)
    lum = lum - gaussian_filter(lum, 40)
    im = Image.new('L', (n, n), 0)
    dr = ImageDraw.Draw(im)
    k = 0
    for m in marks:
        if m.distance(__import__('shapely').geometry.Point(cx, cy)) > half * 1.5:
            continue
        ext = [((x - (cx - half)) / RES, ((cy + half) - y) / RES) for x, y in m.exterior.coords]
        dr.polygon(ext, fill=1)
        for h in m.interiors:
            dr.polygon([((x - (cx - half)) / RES, ((cy + half) - y) / RES) for x, y in h.coords], fill=0)
        k += 1
    mask = np.asarray(im, dtype=float)
    if mask.sum() < 200:
        return None
    mask = mask - gaussian_filter(mask, 40)
    F = np.fft.rfft2(lum) * np.conj(np.fft.rfft2(mask))
    c = np.fft.irfft2(F, s=lum.shape)
    ms = int(maxs / RES)
    c = np.roll(np.roll(c, ms, 0), ms, 1)[:2 * ms + 1, :2 * ms + 1]
    i, j = np.unravel_index(np.argmax(c), c.shape)
    peak = c[i, j]
    # sub-pixel by centroid of the 3x3 around the peak
    if 0 < i < 2 * ms and 0 < j < 2 * ms:
        w = c[i - 1:i + 2, j - 1:j + 2] - c[i - 1:i + 2, j - 1:j + 2].min()
        di = (w.sum(1) @ np.array([-1, 0, 1])) / w.sum()
        dj = (w.sum(0) @ np.array([-1, 0, 1])) / w.sum()
    else:
        di = dj = 0
    dy = -((i + di) - ms) * RES   # image rows go south
    dx = ((j + dj) - ms) * RES
    sharp = (peak - np.median(c)) / (c.std() + 1e-9)
    return dx, dy, sharp, k


if __name__ == '__main__':
    for ap in sys.argv[1:]:
        t = TC(ap, shift=(0, 0))
        marks = t.marks_w
        # windows centred on clusters of small markings (numbers, threshold stripes)
        cents = np.array([[m.centroid.x, m.centroid.y] for m in marks if 20 < m.area < 2000])
        rng = np.random.default_rng(1)
        res = []
        used = []
        for idx in rng.permutation(len(cents)):
            c = cents[idx]
            if any(np.hypot(*(c - u)) < 150 for u in used):
                continue
            used.append(c)
            r = window_shift(marks, c[0], c[1])
            if r:
                res.append(r + (c[0], c[1]))
            if len(used) >= 14:
                break
        if not res:
            print(ap, 'no windows'); continue
        a = np.array([[r[0], r[1]] for r in res]).reshape(-1, 2)
        sh = np.array([r[2] for r in res])
        good = a[sh >= np.median(sh)]
        print(ap, 'windows', len(res), 'median shift (sharper half) dx=%+.2f dy=%+.2f' % tuple(np.median(good, axis=0)),
              ' all: dx=%+.2f dy=%+.2f' % tuple(np.median(a, axis=0)), ' MAD %.2f %.2f' % tuple(np.median(np.abs(a - np.median(a, axis=0)), axis=0)))
        for r in res:
            print('    dx=%+.2f dy=%+.2f sharp=%.1f n=%d at %.5f,%.5f' % (r[0], r[1], r[2], r[3], *TI(r[4], r[5])))
