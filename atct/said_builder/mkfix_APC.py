"""Generates airports/APC/fix.geojson: the places where the APC SAID has to differ from the tower-cab base layer.

The SAID follows painted edge lines and the pavement that is really there; at these spots the base layer
(drawn to the full width of concrete, some of it from older pavement) does not:

  1. run-up pad at the 19R end   painted outline is 3.8 m north of the drawn pad edge and 14-25 m west of its
                                 east edge; the old pavement east of the pad and of the taxiway below it is not
                                 part of the taxiway.
  2. taxiway beside the apron    the base joins taxiway and apron over ~120 m; there is a grass strip between
     (north-west corner)         them.  Taxiway edge = straight between the base's own corners either side,
                                 apron edge = the concrete edge seen in the imagery.
  3. run-up bay near the 06 end  painted outline is 6-7 m inside the drawn pavement edge (paved shoulder).
  4. concrete taxiway through    the 15 m concrete strip from the parallel taxiway to the big hangars, with its
     the main ramp               short north branch, is drawn as ramp; the SAID shows it as taxiway.

Straight paint lines are fitted from the imagery (paint.py); everything else is taken from the tower-cab
linework (pad arc, centreline, base corners).  Output coordinates are true positions as seen on the imagery,
i.e. the tower-cab frame + APC's registration shift: rerun this if that shift changes.

  python mkfix_APC.py        # writes airports/APC/fix.geojson and prints what it fitted
"""
import json, os, warnings
warnings.simplefilter('ignore')
import numpy as np
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union
import paint
from tc import TC, T, TI
import paths

S = os.path.dirname(os.path.abspath(__file__))
AP = 'APC'


def P(lon, lat):
    return np.array(T(lon, lat))


def brg(a, b):
    return float((np.degrees(np.arctan2(b[0] - a[0], b[1] - a[1])) + 360) % 360)


def vec(bearing):
    return np.array([np.sin(np.radians(bearing)), np.cos(np.radians(bearing))])


def vertex(ring, lon, lat, tol=3.0):
    """Index and position of the ring vertex nearest a lon/lat (must be within tol metres)."""
    co = np.array(ring.coords)[:-1]
    d = np.hypot(*(co - P(lon, lat)).T)
    i = int(d.argmin())
    assert d[i] < tol, f'no base vertex within {tol} m of {lon},{lat} (nearest {d[i]:.1f} m)'
    return i, co


def line_hit(a, b, ring, near, ext=30.0):
    """Where the line a->b (extended by ext both ways) crosses a ring, nearest to `near`."""
    d = (b - a) / np.hypot(*(b - a))
    x = LineString([a - d * ext, b + d * ext]).intersection(ring)
    pts = [g for g in getattr(x, 'geoms', [x]) if g.geom_type == 'Point']
    assert pts, 'line does not cross the ring'
    p = min(pts, key=lambda g: g.distance(Point(near)))
    return np.array(p.coords[0])


def main():
    t = TC(AP)
    mov_parts = [part for c, p, g in t.layers['base'] if c == '#717171' for part in g.geoms]
    mainp = max(mov_parts, key=lambda p: p.area)
    ramp = max((part for c, p, g in t.layers['base'] if c == '#a1a1a1' for part in g.geoms), key=lambda p: p.area)
    mov = unary_union(mov_parts).buffer(0)
    feats = []

    def add(op, geom, note, **props):
        feats.append({"type": "Feature", "properties": dict(op=op, note=note, **props),
                      "geometry": mapping(transform(TI, geom))})

    # ------------------------------------------------------------------ 1. run-up pad at the 19R end
    north_a, north_b, st_n = paint.fit(P(-122.276937, 38.223236), P(-122.276452, 38.223091))
    east_a, east_b, st_e = paint.fit(P(-122.276452, 38.223091), P(-122.276523, 38.222577))
    NE = paint.isect(north_a, north_b, east_a, east_b)
    print('pad north line', st_n)
    print('pad east line ', st_e)
    # west side: the pad's drawn arc already follows the paint; continue it (same chord, same turn per chord)
    # up to the painted north line
    pad = min((p for p in mov_parts if p.area < 10000), key=lambda p: p.distance(Point(NE)))
    co = np.array(pad.exterior.coords)[:-1]
    seg = np.hypot(*(np.roll(co, -1, axis=0) - co).T)
    # the drawn north edge is the long edge heading east-south-east; the arc ends where it starts
    i12 = next(i for i in range(len(co)) if seg[i] > 30 and 80 < brg(co[i], co[(i + 1) % len(co)]) < 140)
    a, b = co[i12 - 1], co[i12]
    chord = np.hypot(*(b - a))
    turn = brg(co[i12 - 2], a) - brg(a, b)       # degrees per chord (positive: bearing decreasing)
    assert chord < 3 and 0 < turn < 3, 'pad arc not found where expected'
    arc = [b]
    bearing = brg(a, b)
    north_line = LineString([north_a - (north_b - north_a), north_b + (north_b - north_a)])
    for _ in range(40):
        bearing -= turn
        nxt = arc[-1] + vec(bearing) * chord
        step = LineString([arc[-1], nxt])
        if step.intersects(north_line):
            NW = np.array(step.intersection(north_line).coords[0])
            break
        arc.append(nxt)
    else:
        raise RuntimeError('pad arc never reached the painted north line')
    print('pad: drawn north edge is %.2f m inside the paint; arc continued %d chords; NW %.6f,%.6f NE %.6f,%.6f'
          % (north_line.distance(Point(b)), len(arc) - 1, *TI(*NW), *TI(*NE)))
    d_e = (east_b - east_a) / np.hypot(*(east_b - east_a))          # down the east line (southward)
    add('add', Polygon([*arc, NW, NE, NE + d_e * 8.0]), 'run-up pad 19R: pavement up to the painted north edge line',
        to='movement')

    # taxiway east edge below the pad: parallel to the centreline, through the base corner where the drawn
    # east edge becomes the taxiway edge again (after the bend)
    iv, mco = vertex(mainp.exterior, -122.276083, 38.221674)
    V = mco[iv]
    cl = min(t.cl_mov, key=lambda l: l.distance(Point(V)))
    line = LineString(np.array(cl.coords)[::-1]) if Point(cl.coords[0]).distance(Point(NE)) > Point(cl.coords[-1]).distance(Point(NE)) else cl
    d_off = line.distance(Point(V))
    off = line.offset_curve(d_off, quad_segs=8)
    if off.project(Point(V)) < off.project(Point(NE)):                # make it run from the pad toward V
        off = LineString(list(off.coords)[::-1])
    east_line = LineString([east_a - d_e * 5, east_b + d_e * 40])
    hit = east_line.intersection(off)
    tip = min((g for g in getattr(hit, 'geoms', [hit]) if g.geom_type == 'Point'), key=lambda g: g.distance(Point(east_b)))
    s0, s1 = off.project(tip), off.project(Point(V))
    curve = [np.array(c) for c in off.coords if s0 + 0.3 < off.project(Point(c)) < s1 - 0.3]
    print('taxiway east edge below the pad: %.2f m from the centreline (west side as drawn: 7.77), %d points; '
          'paint ends %.2f m from the computed corner' % (d_off, len(curve), Point(east_b).distance(tip)))
    tip = np.array(tip.coords[0])
    nxt = mco[(iv + 1) % len(mco)]                                    # the straight taxiway edge after the bend
    assert np.hypot(*(nxt - V)) > 20
    out = vec(brg(V, nxt) - 90)                                       # away from the pavement
    if mov.contains(Point(V + out * 2)):
        out = -out
    X1 = V + out * 6
    E1 = X1 + out * 70
    N_ext = NE - d_e * 12
    E2 = np.array([E1[0], N_ext[1]])
    cut = Polygon([N_ext, NE, tip, *curve, V, X1, E1, E2])
    assert cut.is_valid
    add('cut', cut, 'run-up pad 19R: old pavement east of the painted pad edge and of the taxiway below it')

    # ------------------------------------------------------------------ 2. grass strip, taxiway / apron
    ia, mco = vertex(mainp.exterior, -122.276467, 38.220862)
    ib, _ = vertex(mainp.exterior, -122.276982, 38.219783)
    A, B = mco[ia], mco[ib]
    pale_a, pale_b, st_p = paint.fit(P(-122.276310, 38.220674), P(-122.276811, 38.219632), step=2.0, margin=1.0)
    print('apron west edge  ', st_p)
    C_nw = line_hit(pale_a, pale_b, ramp.exterior, pale_a)
    P_s = line_hit(pale_a, pale_b, ramp.exterior, pale_b)
    d_p = (pale_a - pale_b) / np.hypot(*(pale_a - pale_b))             # up the line (northward)
    N2 = C_nw + d_p * 8
    assert np.hypot(*(mco[ia - 1] - A)) > 20                            # the straight taxiway edge north of the strip
    N1 = A + vec(brg(A, mco[ia - 1])) * 5 + vec(brg(B, A) + 90) * 1.5   # just outside that edge
    assert not mov.contains(Point(N1))
    cut = Polygon([A, B, P_s, C_nw, N2, N1])
    assert cut.is_valid
    print('strip: taxiway edge %.1f m straight at %.2f deg, apron edge %.1f m at %.2f deg, %.1f m apart'
          % (np.hypot(*(B - A)), brg(A, B), np.hypot(*(P_s - C_nw)), brg(C_nw, P_s), LineString([A, B]).distance(Point(C_nw))))
    add('cut', cut, 'grass strip between the taxiway and the apron (the base joins them)')

    # ------------------------------------------------------------------ 3. run-up bay near the 06 end
    W = paint.fit(P(-122.287996, 38.209005), P(-122.287678, 38.209404))
    N = paint.fit(P(-122.287678, 38.209404), P(-122.287180, 38.209501))
    E = paint.fit(P(-122.287180, 38.209501), P(-122.286657, 38.209250))
    for nm, f in (('bay west line ', W), ('bay north line', N), ('bay east line ', E)):
        print(nm, f[2])
    NWb = paint.isect(W[0], W[1], N[0], N[1])
    NEb = paint.isect(N[0], N[1], E[0], E[1])
    jw, mco = vertex(mainp.exterior, -122.288051, 38.209044)
    je, _ = vertex(mainp.exterior, -122.286642, 38.209308)
    Jw, Je = mco[jw], mco[je]
    # the taxiway's own north edge either side of the bay, extended to the painted diagonals
    w_prev, e_next = mco[jw - 1], mco[(je + 1) % len(mco)]
    assert np.hypot(*(w_prev - Jw)) > 5 and 60 < brg(w_prev, Jw) < 100, 'taxiway edge west of the bay not found'
    assert np.hypot(*(e_next - Je)) > 5 and 60 < brg(Je, e_next) < 100, 'taxiway edge east of the bay not found'
    Pw = paint.isect(w_prev, Jw, W[0], W[1])
    Pe = paint.isect(e_next, Je, E[0], E[1])
    out_w = vec(brg(w_prev, Jw) - 90)
    out_e = vec(brg(Je, e_next) - 90)
    cut = Polygon([Jw + out_w * 60, Jw, Pw, NWb, NEb, Pe, Je, Je + out_e * 60])
    assert cut.is_valid
    ringw = [LineString([NWb, NEb]).length, LineString([Pw, NWb]).length, LineString([NEb, Pe]).length]
    print('bay: painted outline %.1f / %.1f / %.1f m (west, north, east); taxiway edge extended %.1f m (west) and %.1f m (east) to meet it'
          % (ringw[1], ringw[0], ringw[2], np.hypot(*(Pw - Jw)), np.hypot(*(Pe - Je))))
    add('cut', cut, 'run-up bay near 06: paved shoulder outside the painted bay outline')

    # ------------------------------------------------------------------ 4. concrete taxiway through the ramp
    from scipy import ndimage as ndi
    from render import sample
    O = P(-122.27440, 38.21730)
    a, b = O + (-55.0, -85.0), O + (95.0, -7.0)                       # rough axis of the strip
    d = (b - a) / np.hypot(*(b - a))
    n = np.array([-d[1], d[0]])
    oo = np.arange(-18, 18.01, 0.1)
    mid = len(oo) // 2
    en, es = [], []
    for s in np.arange(8, 129, 4.0):                                 # concrete (bright) against asphalt (dark)
        al = np.arange(-2, 2.1, 1)[:, None]
        lum = np.median(sample(a[0] + d[0] * (s + al) + n[0] * oo, a[1] + d[1] * (s + al) + n[1] * oo).mean(axis=2), axis=0)
        g = np.gradient(ndi.gaussian_filter1d(lum, 3))
        en.append(oo[mid + int(np.argmin(g[mid:]))])
        es.append(oo[int(np.argmax(g[:mid]))])
    on, os_ = float(np.median(en)), float(np.median(es))
    print('strip: edges %.2f m north / %.2f m south of the rough axis (scatter %.2f / %.2f), width %.1f m'
          % (on, -os_, np.std(en), np.std(es), on - os_))
    N = lambda s: a + d * s + n * on
    Sd = lambda s: a + d * s + n * os_
    C4 = P(-122.27360, 38.21728)                                      # north branch, read off a 5 m grid
    TL, TR, ER, WB = C4 + (-7.0, 11.5), C4 + (8.0, 19.5), C4 + (22.0, -7.0), C4 + (-2.0, 0.0)
    ERp = paint.isect(TR, ER, N(0), N(1))                              # branch east side meets the strip
    corner = paint.isect(TL, WB, N(0), N(1))
    u = (TL - WB) / np.hypot(*(TL - WB))
    tlen = np.hypot(*(WB - corner))                                    # fillet tangent length, from where the curve ends
    half = np.arccos(np.clip(np.dot(-d, u), -1, 1)) / 2
    R = tlen * np.tan(half)
    bis = (-d + u) / np.hypot(*(-d + u))
    cen = corner + bis * R / np.sin(half)
    T1, T2 = corner - d * tlen, corner + u * tlen
    a1, a2 = np.arctan2(*(T1 - cen)[::-1]), np.arctan2(*(T2 - cen)[::-1])
    if abs(a2 - a1) > np.pi:
        a2 += -2 * np.pi * np.sign(a2 - a1)
    arc = [cen + R * np.array([np.cos(t), np.sin(t)]) for t in np.linspace(a1, a2, 14)]
    sE = float((ERp - a) @ d)
    strip = Polygon([N(-20), *arc, TL, TR, ERp, Sd(sE), Sd(-20)])
    assert strip.is_valid
    print('strip: %.0f m long, branch fillet radius %.1f m' % (sE + 20, R))
    add('taxiway', strip, 'concrete taxiway through the main ramp (drawn as ramp in the base layer)')

    # ------------------------------------------------------------------ checks + write
    adds = unary_union([transform(T, shape(f['geometry'])) for f in feats if f['properties']['op'] == 'add'])
    cuts = unary_union([transform(T, shape(f['geometry'])) for f in feats if f['properties']['op'] == 'cut'])
    pav = unary_union([mov, t.ramp.buffer(0)])
    print('pavement added %.0f m2, removed %.0f m2 (movement %.0f, ramp %.0f)'
          % (adds.difference(pav).area, pav.intersection(cuts).area, mov.intersection(cuts).area, t.ramp.buffer(0).intersection(cuts).area))
    out = {"type": "FeatureCollection", "name": f"{AP} SAID corrections",
           "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": feats}
    path = paths.afile(AP, 'fix.geojson')
    json.dump(out, open(path, 'w'), indent=1)
    print('wrote', path, len(feats), 'features')


if __name__ == '__main__':
    main()
