"""Runway rectangles from the tower-cab runway markings (side stripes), one per OSM runway axis."""
import json, os, warnings
warnings.simplefilter('ignore')
import numpy as np
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union
from tc import T, TI
import paths

S = os.path.dirname(os.path.abspath(__file__))


def osm_axes(ap):
    out = []
    for el in json.load(open(paths.afile(ap, 'osm.json'), encoding='utf-8'))['elements']:
        if el['tags'].get('aeroway') == 'runway' and 'geometry' in el:
            g = el['geometry']
            out.append((el['tags'].get('ref', '?'), np.array(T(g[0]['lon'], g[0]['lat'])), np.array(T(g[-1]['lon'], g[-1]['lat']))))
    return out


def long_segments(geoms, p0, ax0, L, reach, min_len=60.0, max_ang=1.5):
    """Long straight ring segments roughly parallel to an axis, as (midpoint, direction, length, a, b)."""
    out = []
    nr0 = np.array([-ax0[1], ax0[0]])
    cosmin = np.cos(np.radians(max_ang))
    for g in geoms:
        for ring in [g.exterior] + list(g.interiors):
            c = np.array(ring.coords)
            for a, b in zip(c[:-1], c[1:]):
                d = b - a
                n = np.hypot(*d)
                if n < min_len:
                    continue
                d = d / n
                if abs(d @ ax0) < cosmin:
                    continue
                if d @ ax0 < 0:
                    a, b, d = b, a, -d
                m = (a + b) / 2 - p0
                if abs(m @ nr0) > reach or not (-300 < m @ ax0 < L + 300):
                    continue
                out.append((a, b, d, n))
    return out


def threshold_setback(mov, p0, ax, nr, u, v0, v1, sgn, lo=4.5, hi=8.0, n=11, tol=0.6):
    """Threshold bars start 20 ft (6.1 m) in from the runway end.  Where the side stripes were drawn starting
    at the bars, the runway pavement carries on for that 20 ft and then stops.  Returns the distance from the
    stripe end (station u, direction sgn) to that pavement end, or 0 if the pavement does not end there:
    rays are cast along the runway across its width and at least a third must agree on one distance in
    lo..hi metres (a ray that runs on into a blast pad or a stub simply does not count)."""
    ds = []
    for v in np.linspace(v0 + 1.0, v1 - 1.0, n):
        a = p0 + ax * (u + sgn * 0.05) + nr * v
        if not mov.contains(Point(a)):
            continue
        hit = LineString([a, a + ax * sgn * (hi + 2.0)]).intersection(mov.boundary)
        if not hit.is_empty:
            ds.append(Point(a).distance(hit) + 0.05)
    ds = np.array(sorted(ds))
    best = np.array([])
    for d in ds:
        grp = ds[np.abs(ds - d) <= tol]
        if len(grp) > len(best):
            best = grp
    if len(best) >= max(3, n // 3) and lo <= float(np.median(best)) <= hi:
        return float(np.median(best))
    return 0.0


def fit(ref, p0, p1, marks, mov, reach=40.0):
    """Runway rectangle on an OSM axis: sides = outer edges of the side stripes, ends = ends of the stripes
    (moved out to the pavement end where the stripes were drawn from the threshold bars, see threshold_setback).
    Falls back to the pavement (movement base) edges for a runway with no side stripes."""
    ax0 = (p1 - p0) / np.hypot(*(p1 - p0))
    L = np.hypot(*(p1 - p0))
    info = dict(ref=ref)
    for src, geoms in (('stripes', marks), ('pavement', list(getattr(mov, 'geoms', [mov])))):
        segs = long_segments(geoms, p0, ax0, L, reach)
        tot = sum(n for a, b, d, n in segs)
        if src == 'stripes' and tot < 1.2 * L:
            continue
        if not segs:
            continue
        ax = np.sum([d * n for a, b, d, n in segs], axis=0)
        ax = ax / np.hypot(*ax)
        nr = np.array([-ax[1], ax[0]])
        rows = [((((a + b) / 2 - p0) @ nr), (a - p0) @ ax, (b - p0) @ ax, n) for a, b, d, n in segs]
        vs = np.array([r[0] for r in rows])
        if src == 'stripes':
            v0, v1 = float(vs.min()), float(vs.max())
        else:
            # pavement: nearest long parallel edge on each side of the centreline
            neg = vs[vs < -3]
            pos = vs[vs > 3]
            if len(neg) == 0 or len(pos) == 0:
                continue
            v0, v1 = float(neg.max()), float(pos.min())
        # ends: every stripe piece lying on the two side lines counts, however short (side stripes are broken
        # where another runway crosses, so the piece beyond a crossing can be much shorter than min_len)
        short = long_segments(geoms, p0, ax0, L, reach, min_len=3.0, max_ang=1.5)
        rows2 = [((((a + b) / 2 - p0) @ nr), (a - p0) @ ax, (b - p0) @ ax, n) for a, b, d, n in short]
        on = [r for r in rows2 if abs(r[0] - v0) < 0.4 or abs(r[0] - v1) < 0.4]
        u0 = float(min(min(r[1], r[2]) for r in on))
        u1 = float(max(max(r[1], r[2]) for r in on))
        if src == 'pavement':
            # ends = where the pavement itself ends on the centreline
            c = p0 + nr * (v0 + v1) / 2
            sec = LineString([c - ax * 400, c + ax * (L + 400)]).intersection(mov)
            mid = Point(c + ax * L / 2)
            part = min([g for g in getattr(sec, 'geoms', [sec]) if g.geom_type == 'LineString'], key=lambda g: g.distance(mid))
            q = (np.array(part.coords) - p0) @ ax
            u0, u1 = float(q.min()), float(q.max())
        else:
            e0 = threshold_setback(mov, p0, ax, nr, u0, v0, v1, -1)
            e1 = threshold_setback(mov, p0, ax, nr, u1, v0, v1, +1)
            u0, u1 = u0 - e0, u1 + e1
            info.update(end_ext=(round(e0, 2), round(e1, 2)))
        rect = Polygon([tuple(p0 + ax * a + nr * b) for a, b in [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]])
        info.update(src=src, length=u1 - u0, width=v1 - v0, nseg=len(segs), seglen=tot,
                    axis_fix_deg=float(np.degrees(np.arcsin(ax0[0] * ax[1] - ax0[1] * ax[0]))))
        return rect, info
    return None, info


def runways(ap, t, mov):
    out = []
    for ref, p0, p1 in osm_axes(ap):
        out.append(fit(ref, p0, p1, t.marks_w, mov))
    return out
