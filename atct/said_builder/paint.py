"""Fit a straight line to a painted line (edge line, pad outline, concrete edge) seen in the imagery.

  import paint
  a, b, stats = paint.fit(T(lon0, lat0), T(lon1, lat1))     # rough end points in, refined end points out (UTM)

The line is found as the ridge of a narrow bright band: brightness smoothed over the width of a painted line
minus brightness smoothed over a metre.  Colour is not used (the imagery's chroma is too blocky to help).
Typical result: rms of a few cm over 50-100 m.  Give end points within ~2.5 m of the paint.
"""
import warnings
warnings.simplefilter('ignore')
import numpy as np
from scipy import ndimage as ndi
from render import sample


def ridge(a, b, half=3.0, step=1.0, res=0.05, narrow=0.2, wide=1.0, margin=1.5, min_contrast=8.0):
    """Offset of the brightest narrow band across a->b, every `step` metres.
    Returns stations, offsets (m, + = left of a->b), contrast, usable flags and the frame (a, direction, normal)."""
    a = np.array(a, float)
    b = np.array(b, float)
    L = np.hypot(*(b - a))
    d = (b - a) / L
    n = np.array([-d[1], d[0]])
    ss = np.arange(margin, L - margin + 1e-9, step)
    oo = np.arange(-(half + 3 * wide), half + 3 * wide + 1e-9, res)
    X = a[0] + d[0] * ss[:, None] + n[0] * oo[None, :]
    Y = a[1] + d[1] * ss[:, None] + n[1] * oo[None, :]
    lum = sample(X, Y).mean(axis=2)
    D = ndi.gaussian_filter1d(lum, narrow / res, axis=1) - ndi.gaussian_filter1d(lum, wide / res, axis=1)
    m = np.abs(oo) <= half
    D, oo = D[:, m], oo[m]
    pk = D.argmax(axis=1)
    contrast = D.max(axis=1)
    ok = (contrast >= min_contrast) & (pk > 3) & (pk < len(oo) - 4)
    return ss, oo[pk], contrast, ok, (a, d, n)


def fit(a, b, iters=4, **kw):
    """Robust straight-line fit of the paint near a->b.  Returns (a', b', stats) with a', b' on the fitted line."""
    a = np.array(a, float)
    b = np.array(b, float)
    for _ in range(iters):
        ss, off, contrast, ok, (a0, d, n) = ridge(a, b, **kw)
        s, o = ss[ok], off[ok]
        if len(s) < 6:
            raise RuntimeError('no painted line found near the given end points')
        keep = np.ones(len(s), bool)
        for _ in range(5):
            k, c = np.polyfit(s[keep], o[keep], 1)
            r = o - (k * s + c)
            sd = max(0.08, 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))))
            keep = np.abs(r) < 2.5 * sd
        L = np.hypot(*(b - a))
        a, b = a0 + n * c, a0 + d * L + n * (k * L + c)
    stats = dict(points=int(keep.sum()), of=len(ss), rms=float(np.sqrt(np.mean(r[keep] ** 2))),
                 contrast=float(np.median(contrast[ok])), bearing=float((np.degrees(np.arctan2(*(b - a))) + 360) % 360))
    return a, b, stats


def isect(p1, p2, p3, p4):
    """Intersection of the infinite lines p1p2 and p3p4."""
    p1, p2, p3, p4 = (np.array(p, float) for p in (p1, p2, p3, p4))
    d1, d2 = p2 - p1, p4 - p3
    den = d1[0] * d2[1] - d1[1] * d2[0]
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    return p1 + t * d1
