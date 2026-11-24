"""Synthesize the two edge lines of a straight taxiway connector whose edge lines are missing from the
tower-cab map: straight edges parallel to the drawn centreline + one tangent circular fillet per corner.

Only three kinds of number are taken from the imagery, each by a 1-D fit to the paint:
  * the half-width on each side (median paint offset along the straight part)
  * one fillet radius per corner (radius whose arc lies on the most paint)
so the result is as smooth as a drafted line.  Output: lon/lat polylines in airports/SCK/extra_edges.json (read by airports/SCK/cfg.py).
"""
import sys, os, math, warnings
warnings.simplefilter('ignore')
import numpy as np
from shapely.geometry import LineString, Point
from scipy.ndimage import uniform_filter1d
from render import sample
from tc import TC, T, TI
import paths

S = os.path.dirname(os.path.abspath(__file__))


def unit(v):
    return v / np.hypot(*v)


def paint(pts, nrm, half=1.6, ds=0.1):
    """Ridge strength (bright thin line on darker surroundings) at points, measured across `nrm`."""
    DS = np.arange(-half, half + ds / 2, ds)
    X = pts[:, 0, None] + nrm[:, 0, None] * DS[None, :]
    Y = pts[:, 1, None] + nrm[:, 1, None] * DS[None, :]
    lum = sample(X, Y).mean(-1)
    k = len(DS) // 2
    core = lum[:, k - 1:k + 2].mean(1)
    side = np.minimum(lum[:, :6].mean(1), lum[:, -6:].mean(1))
    return core - side


def half_width(p0, d, n, s0, s1, guess, win=2.5):
    """Median paint offset on one side (n = unit normal toward that side) along the straight part."""
    offs = []
    DS = np.arange(guess - win, guess + win + 0.05, 0.1)
    for s in np.arange(s0, s1, 2.0):
        c = p0 + d * s
        al = np.arange(-1.5, 1.51, 0.5)
        X = c[0] + n[0] * DS[:, None] + d[0] * al[None, :]
        Y = c[1] + n[1] * DS[:, None] + d[1] * al[None, :]
        lum = np.median(sample(X, Y).mean(-1), axis=1)
        r = uniform_filter1d(lum, 3) - uniform_filter1d(lum, 31)
        i = int(np.argmax(r))
        if r[i] > 8:
            offs.append(DS[i])
    return float(np.median(offs)), len(offs), float(np.std(offs)), offs


def line_x(p, d, q, e):
    """Intersection of p + t d and q + u e."""
    A = np.array([[d[0], -e[0]], [d[1], -e[1]]])
    t, u = np.linalg.solve(A, q - p)
    return p + d * t


def arc(Q, d1, d2, R, step_deg=4.0):
    """Tangent arc of radius R joining direction d1 (arriving at corner Q) to d2 (leaving Q)."""
    cosphi = float(np.clip(d1 @ d2, -1, 1))
    phi = math.acos(cosphi)                       # turning angle
    Tn = R * math.tan(phi / 2)
    P1 = Q - d1 * Tn
    P2 = Q + d2 * Tn
    turn = np.sign(d1[0] * d2[1] - d1[1] * d2[0])  # +1 left turn
    nL = np.array([-d1[1], d1[0]]) * turn
    C = P1 + nL * R
    a0 = math.atan2(P1[1] - C[1], P1[0] - C[0])
    n = max(2, int(math.degrees(phi) / step_deg) + 1)
    pts = [C + R * np.array([math.cos(a0 + turn * phi * i / n), math.sin(a0 + turn * phi * i / n)]) for i in range(n + 1)]
    return np.array(pts), Tn


def fit_radius(Q, d1, d2, radii):
    best = None
    for R in radii:
        pts, Tn = arc(Q, d1, d2, R, step_deg=1.0)
        seg = np.diff(pts, axis=0)
        mid = (pts[:-1] + pts[1:]) / 2
        nrm = np.stack([-seg[:, 1], seg[:, 0]], 1)
        nrm = nrm / np.hypot(nrm[:, 0], nrm[:, 1])[:, None]
        sc = paint(mid, nrm)
        score = float(np.mean(np.clip(sc, 0, 40)))
        if best is None or score > best[0]:
            best = (score, R)
    return best


def connector(ap, cl_index, s_range, runway_sides, guess=11.4, radii=np.arange(8, 90.5, 1.0)):
    """runway_sides: two (point, direction) straight lines (UTM) the connector ends on, in order along the centreline."""
    t = TC(ap)
    cl = t.cl_mov[cl_index]
    a = np.array(cl.interpolate(s_range[0]).coords[0])
    b = np.array(cl.interpolate(s_range[1]).coords[0])
    d = unit(b - a)
    nL = np.array([-d[1], d[0]])
    L = float(np.hypot(*(b - a)))
    out = {}
    # refine the axis direction so that the paint on both sides runs parallel to it
    for _ in range(0):   # axis refinement disabled: the drawn centreline chord already fits (checked visually)
        rot = []
        for n in (nL, -nL):
            hw, cnt, sd, offs = half_width(a, d, n, 0, L, guess)
            ss = np.arange(0, L, 2.0)[:len(offs)]
            if len(offs) > 8:
                k = np.polyfit(ss, offs, 1)[0]
                rot.append(k * (1 if n is nL else -1))
        if not rot:
            break
        ang = float(np.mean(rot))                 # radians (small): + = paint drifts left
        c, s_ = math.cos(ang), math.sin(ang)
        d = unit(np.array([d[0] * c - d[1] * s_, d[0] * s_ + d[1] * c]))
        nL = np.array([-d[1], d[0]])
    for name, n in (('left', nL), ('right', -nL)):
        hw, cnt, sd, _o = half_width(a, d, n, 0, L, guess)
        e0 = a + n * hw                                  # a point on the straight edge line
        line = []
        info = [f"half-width {hw:.2f} m ({cnt} samples, sd {sd:.2f})"]
        ends = []
        for k, (q, e) in enumerate(runway_sides):
            Q = line_x(e0, d, q, e)                      # corner of the edge line with the runway side
            d1 = d if k == 1 else -d                     # travelling toward this runway
            e = unit(e)
            # the edge line turns outward (away from the taxiway interior): pick the runway-side direction on side n
            d2 = e if e @ n > 0 else -e
            score, R = fit_radius(Q, d1, d2, radii)
            pts, Tn = arc(Q, d1, d2, R)
            info.append(f"corner {k}: R={R:.0f} m (paint score {score:.1f}, tangent {Tn:.1f} m)")
            ends.append(pts)
        # order: runway A side ... straight ... runway B side
        A = ends[0][::-1]       # from runway A tangent point back to the straight
        B = ends[1]
        pts = np.vstack([A, B])
        out[name] = (pts, info)
    return out


if __name__ == '__main__':
    import build
    ap = 'SCK'
    r = build.build(ap)
    rects = {i['ref']: rect for rect, i in r['rws']}
    def side_facing(rect, pt):
        c = np.array(rect.exterior.coords)[:4]
        best = None
        for i in range(4):
            p, q = c[i], c[(i + 1) % 4]
            if np.hypot(*(q - p)) < 200:
                continue
            dist = LineString([p, q]).distance(Point(pt))
            if best is None or dist < best[0]:
                best = (dist, p, unit(q - p))
        return best[1], best[2]
    t = r['t']
    cl = t.cl_mov[12]
    mid = np.array(cl.interpolate(254).coords[0])
    sides = [side_facing(rects['11R/29L'], mid), side_facing(rects['11L/29R'], mid)]
    res = connector(ap, 12, (210, 290), sides)
    lines = []
    for name, (pts, info) in res.items():
        print(name, '; '.join(info))
        lines.append([tuple(round(v, 7) for v in TI(*p)) for p in pts])
    import json
    json.dump(lines, open(paths.afile('SCK', 'extra_edges.json'), 'w'))
    print('wrote airports/SCK/extra_edges.json', [len(l) for l in lines])
