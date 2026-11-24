"""Measure how far an airport's tower-cab linework sits from the current ArcGIS imagery and store it.

Two independent measurements:
  lines     the paint ridge under the drawn edge lines and centrelines (reg.py)
  markings  correlation of the drawn white runway markings with image brightness (reg2.py)
The stored shift (airports/<APT>/airport.json) is the lines one when it exists, the markings one otherwise; the
other is the cross-check.  If they disagree by more than half a metre the result is flagged: look at a review
sheet before trusting it.

  python register.py LVK           # measure and store
  python register.py --dry LVK     # measure only
"""
import sys, warnings
warnings.simplefilter('ignore')
import numpy as np
import paths, reg, reg2
from tc import TC


def by_lines(ap):
    obs = []
    for color in ('#a29857', '#fcb737', '#858585'):
        for l in reg.lines(ap, '_taxi_lines.geojson', color):
            if l.length >= 8:
                obs += reg.offsets(l)
    if len(obs) < 40:
        return None
    sh, mad, inl, n = reg.solve(obs)
    return dict(shift=(float(sh[0]), float(sh[1])), n=n, mad=mad, inliers=inl)


def by_markings(ap, windows=14):
    marks = TC(ap, shift=(0, 0)).marks_w
    cents = np.array([[m.centroid.x, m.centroid.y] for m in marks if 20 < m.area < 2000])
    if len(cents) == 0:
        return None
    rng = np.random.default_rng(1)
    res, used = [], []
    for idx in rng.permutation(len(cents)):
        c = cents[idx]
        if any(np.hypot(*(c - u)) < 150 for u in used):
            continue
        used.append(c)
        r = reg2.window_shift(marks, c[0], c[1])
        if r:
            res.append(r)
        if len(used) >= windows:
            break
    if len(res) < 3:
        return None
    a = np.array([[r[0], r[1]] for r in res])
    sharp = np.array([r[2] for r in res])
    good = a[sharp >= np.median(sharp)]
    m = np.median(good, axis=0)
    return dict(shift=(float(m[0]), float(m[1])), n=len(res), mad=float(np.median(np.abs(good - m))))


def measure(ap):
    out = {k: f(ap) for k, f in (('lines', by_lines), ('markings', by_markings))}
    got = [v['shift'] for v in out.values() if v]
    if not got:
        return None, out, False
    sh = tuple(round(float(x), 2) for x in got[0])      # lines when there are any (thousands of samples), else markings
    agree = len(got) < 2 or float(np.hypot(*(np.array(got[0]) - np.array(got[1])))) <= 0.5
    return sh, out, agree


def run(ap, store=True):
    sh, out, agree = measure(ap)
    for k, v in out.items():
        print(f"   {ap} {k:9s}:", ('dx %+.2f dy %+.2f m  (%d samples)' % (*v['shift'], v['n'])) if v else 'not enough to measure')
    if sh is None:
        print(f"   {ap}: could not measure a shift; using (0, 0): the SAID will sit exactly on the tower-cab linework")
        sh = (0.0, 0.0)
    elif not agree:
        print(f"   {ap}: WARNING the two measurements disagree by more than 0.5 m; check a review sheet")
    print(f"   {ap}: shift dx {sh[0]:+.2f} dy {sh[1]:+.2f} m" + ('' if store else '  (not stored)'))
    if store:
        paths.save_meta(ap, shift=list(sh))
    return sh, agree


if __name__ == '__main__':
    for a in [a for a in sys.argv[1:] if not a.startswith('--')]:
        run(a.upper(), store='--dry' not in sys.argv)
