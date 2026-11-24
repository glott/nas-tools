"""SAID builder: derive SAID polygons from the hand-drawn tower-cab layers (diagrams/<APT>/).

A SAID is traced to the painted EDGE LINES, not to the full width of concrete.  The tower-cab map already
holds those lines, drawn by hand, so nothing is traced from imagery here:

  runway    = rectangle spanned by the runway side stripes (markings layer), one per runway
  taxiway   = movement-area pavement on the centreline side of the SOLID taxiway edge lines (taxi_lines layer)
  apron     = non-movement (ramp) pavement on the usable side of any solid edge line drawn on it
  structure = building footprints kept in airports/<APT>/structures.geojson

Shoulders (pavement outside a solid edge line), runway shoulders and blast pads are left out.  Dashed edge
lines are not dividers: the taxiway/apron divider is the non-movement boundary (movement vs ramp base).
Where the map has no edge line for a stretch, the drawn pavement edge is the boundary.

Every tower-cab layer is first moved by a per-airport registration shift (tc.SHIFT, ~0.9 m) so the linework
sits on the current ArcGIS imagery.

Where the base layer is not what the SAID should show (old pavement beyond a painted edge, grass drawn as ramp,
a pad whose paint is not where the base edge is), airports/<APT>/fix.geojson holds the corrections: see load_fix().

  python build.py SCK CCR APC           # writes new/<APT> SAID.geojson and prints a report
  python build.py --install SCK ...     # also copies the result to the maps repo: asdex/<APT> SAID.geojson
                                        # (a SAID there that this builder did not make is left alone: the build
                                        #  is saved as '<APT> SAID AUTO.geojson'; --overwrite replaces it, --auto
                                        #  always uses the AUTO name)
"""
import sys, os, json, importlib.util, warnings, collections, shutil
warnings.simplefilter('ignore')
import numpy as np
from shapely.geometry import LineString, Polygon, Point, shape, mapping
from shapely.ops import unary_union, polygonize, nearest_points, transform
import shapely
from shapely import set_precision
from tc import TC, T, TI
import paths

S = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ small helpers
def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon' and not p.is_empty]


def lines_of(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'LineString':
        return [g]
    return [p for p in getattr(g, 'geoms', []) if p.geom_type == 'LineString' and p.length > 0]


def is_dash(l):
    """One dash of a dashed edge line (they are drawn dash by dash, ~4.8 m each)."""
    return l.length < 8


def unit(v):
    n = np.hypot(*v)
    return v / n if n > 0 else v


def opening(g, r):
    """Morphological opening with mitred corners: removes parts thinner than 2r, leaves everything else as drawn."""
    return g.buffer(-r, join_style=2, mitre_limit=5.0).buffer(r, join_style=2, mitre_limit=5.0)


# ------------------------------------------------------------------ closing the ends of edge lines
def close_ends(barriers, fixed, mov, avoid, ext=4.0, cap_mov=16.0, cap_ramp=6.0, ring_gap=1.5, join_gap=3.0):
    """Edge lines are drawn up to, but rarely exactly onto, the thing they end at.  Make each free end meet
    something, trying in order:
      1. the line's own other end (an island outline whose ring was left a few cm open)
      2. another line's free end close by (one edge line drawn as two features)
      3. the first line met when the end is extended along its own direction by up to `ext` metres
      4. the nearest line, by a straight cap, if within `cap_mov` (movement area) / `cap_ramp` (ramp) metres
    An extension or cap never crosses a centreline (`avoid`): an edge line is closed toward the pavement edge
    on its own side, never across the taxiway it borders.
    An end that meets nothing stays dangling; a dangling line divides nothing, so it is harmless.
    """
    lines = [[np.array(p, dtype=float) for p in b.coords] for b in barriers]
    # 1. close open rings
    for c in lines:
        if len(c) > 3 and 1e-7 < np.hypot(*(c[0] - c[-1])) <= ring_gap and LineString(c).length > 10:
            c.append(c[0].copy())

    def closed(c):
        return np.hypot(*(c[0] - c[-1])) < 1e-7
    # 2. join free ends of different lines
    for i in range(len(lines)):
        for ei in (0, -1):
            if closed(lines[i]):
                continue
            p = lines[i][ei]
            best = None
            for j in range(len(lines)):
                if j == i:
                    continue
                for ej in (0, -1):
                    q = lines[j][ej]
                    d = np.hypot(*(q - p))
                    if 1e-7 < d <= join_gap and (best is None or d < best[0]):
                        best = (d, q)
            if best is not None:
                if ei == 0:
                    lines[i].insert(0, best[1].copy())
                else:
                    lines[i].append(best[1].copy())
    geoms = [LineString(c) for c in lines]
    out, caps, dangling = [], [], []
    for i, c in enumerate(lines):
        c = list(c)
        if closed(c):
            out.append(LineString(c))
            continue
        cands = [g for g in getattr(fixed, 'geoms', [fixed])] + [g for j, g in enumerate(geoms) if j != i]
        others = unary_union(cands)
        for end in (0, -1):
            p = c[end]
            q = c[1] if end == 0 else c[-2]
            tan = unit(p - q)
            if others.distance(Point(p)) < 1e-7:
                continue
            hit = LineString([p, p + tan * ext]).intersection(others)
            if not hit.is_empty:
                hp = nearest_points(Point(p), hit)[1]
                if not LineString([p, hp.coords[0]]).crosses(avoid):
                    newp = np.array(hp.coords[0]) + tan * 0.05
                    if end == 0:
                        c.insert(0, newp)
                    else:
                        c.append(newp)
                    continue
            limit = cap_mov if mov.contains(Point(p)) else cap_ramp
            best = None
            for g in cands:
                n = nearest_points(Point(p), g)[1]
                d = n.distance(Point(p))
                if 1e-7 < d <= limit and (best is None or d < best[0]) and not LineString([p, n.coords[0]]).crosses(avoid):
                    best = (d, np.array(n.coords[0]))
            if best is not None:
                v = unit(best[1] - p)
                caps.append(LineString([p, best[1] + v * 0.05]))
            else:
                dangling.append((tuple(p), float(others.distance(Point(p)))))
        out.append(LineString(c))
    return out, caps, dangling


# ------------------------------------------------------------------ per-airport overrides and corrections
def load_cfg(ap):
    """airports/<APT>/cfg.py, if there is one: a module defining CFG = {...} (extra_edges, drop_edges, force,
    thresholds)."""
    path = paths.afile(ap, 'cfg.py')
    if not os.path.exists(path):
        return {}
    spec = importlib.util.spec_from_file_location(f"cfg_{ap}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CFG


def load_fix(ap):
    """airports/<APT>/fix.geojson: corrections to the tower-cab base, drawn over the imagery (true lon/lat, so the
    registration shift is NOT applied to them).  Each feature has a property `op`:
      cut   Polygon     not usable pavement (old pavement outside a painted edge, grass): removed from the
                        movement and ramp pavement before anything else happens
      add   Polygon     pavement the base lacks; property `to` = movement (default) or ramp
      edge  LineString  a painted solid edge line the taxi_lines layer lacks (used as a divider)
      taxiway Polygon   ramp pavement that is really a taxiway (e.g. a concrete taxiway laid through an apron):
                        the part of the apron inside it becomes taxiway
    A `note` property says why.  The file can be opened and edited in QGIS like any other layer."""
    out = dict(cut=[], add_mov=[], add_ramp=[], edge=[], taxiway=[])
    path = paths.afile(ap, 'fix.geojson')
    if not os.path.exists(path):
        return out
    for f in json.load(open(path, encoding='utf-8'))['features']:
        g = transform(T, shape(f['geometry']))
        op = f['properties'].get('op')
        if op == 'cut':
            out['cut'].append(g.buffer(0))
        elif op == 'add':
            out['add_ramp' if f['properties'].get('to') == 'ramp' else 'add_mov'].append(g.buffer(0))
        elif op == 'edge':
            out['edge'] += lines_of(g)
        elif op == 'taxiway':
            out['taxiway'].append(g.buffer(0))
        else:
            raise ValueError(f"{ap} fix.geojson: unknown op {op!r}")
    return out


# ------------------------------------------------------------------ build
def build(ap):
    import rwy
    cfg = load_cfg(ap)
    t = TC(ap, shift=cfg.get('shift'))
    src = json.load(open(paths.afile(ap, 'structures.geojson'), encoding='utf-8'))
    structures = [transform(T, shape(f['geometry'])).buffer(0) for f in src['features']]

    mov = t.mov.buffer(0)
    ramp0 = t.ramp.buffer(0)
    fix = load_fix(ap)
    if fix['add_mov']:
        mov = unary_union([mov] + fix['add_mov'])
    if fix['add_ramp']:
        ramp0 = unary_union([ramp0] + fix['add_ramp']).difference(mov)
    if fix['cut']:
        cut = unary_union(fix['cut'])
        mov, ramp0 = mov.difference(cut), ramp0.difference(cut)
    # the ramp and movement polygons were not always snapped to each other: close hairline gaps between them
    g = cfg.get('snap_gap', 0.4)
    both = unary_union([mov, ramp0])
    hair = [p for p in polys(both.buffer(g, join_style=2).buffer(-g, join_style=2).difference(both))
            if p.distance(mov) < 1e-6 and p.distance(ramp0) < 1e-6 and 2 * p.area / p.length < 2 * g]
    ramp = unary_union([ramp0] + hair).difference(mov)

    # --- runways
    rws = rwy.runways(ap, t, mov)
    rects = [r for r, i in rws if r is not None]
    rw = unary_union(rects)
    P = unary_union([mov, ramp]).difference(rw)            # all pavement except runways

    # --- dividers: the solid taxiway edge lines (plus any listed in cfg for paint the map does not have)
    drop = set(cfg.get('drop_edges', ()))
    solid = [e for i, e in enumerate(l for l in t.edge if not is_dash(l)) if i not in drop]
    extra = [LineString([T(*p) for p in pts]) for pts in cfg.get('extra_edges', [])] + fix['edge']
    inP = P.buffer(0.5)
    barriers = [part for b in solid + extra for part in lines_of(b.intersection(inP)) if part.length > 1.0]
    fixed = unary_union([mov.boundary, ramp.boundary, rw.boundary]).intersection(P.buffer(0.01))
    cl = unary_union(t.cl_mov) if t.cl_mov else LineString()
    clr = unary_union(t.cl_ramp) if t.cl_ramp else LineString()
    barriers, caps, dangling = close_ends(barriers, fixed, mov, unary_union([cl, clr]), ext=cfg.get('ext', 4.0),
                                          cap_mov=cfg.get('cap_mov', 16.0), cap_ramp=cfg.get('cap_ramp', 6.0))

    # --- pavement beyond a runway end.  Where the map has edge lines / chevrons they already separate it;
    #     an airport drawn without edge lines needs the runway sides projected past each end to cut it off.
    zones, zlines = [], []
    if cfg.get('overrun_barriers', len(solid) == 0):
        L = cfg.get('overrun_len', 400.0)
        for r in rects:
            c = np.array(r.exterior.coords)[:4]            # (u0,v0) (u1,v0) (u1,v1) (u0,v1)
            ax = unit(c[1] - c[0])
            for a, b, d in ((c[0], c[3], -ax), (c[1], c[2], ax)):
                zones.append(Polygon([a, b, b + d * L, a + d * L]))
                zlines += [LineString([a, a + d * L]), LineString([b, b + d * L])]
    zone = unary_union(zones) if zones else Polygon()
    # A blast pad drawn with chevrons but with no line between it and a taxiway beside it would stay part of
    # that taxiway's face.  Box the chevrons beyond each runway end (along the runway axis) and cut along it.
    chev_all = unary_union(t.marks_y) if t.marks_y else Polygon()
    if not zlines and not chev_all.is_empty and cfg.get('blast_boxes', True):
        Lb = cfg.get('blast_len', 200.0)
        for r in rects:
            c = np.array(r.exterior.coords)[:4]
            ax = unit(c[1] - c[0])
            nr = np.array([-ax[1], ax[0]])
            w = float((c[3] - c[0]) @ nr)
            for a, d in ((c[0], -ax), (c[1], ax)):
                side = min(0.0, w), max(0.0, w)
                reach = Polygon([a + nr * (side[0] - 15), a + nr * (side[1] + 15), a + nr * (side[1] + 15) + d * Lb, a + nr * (side[0] - 15) + d * Lb])
                ch = chev_all.intersection(reach)
                if ch.area < 5:
                    continue
                pts = np.array([q for g in polys(ch) for q in g.exterior.coords])
                u1 = float(((pts - a) @ d).max()) + 1.0
                v0 = min(side[0], float(((pts - a) @ nr).min()) - 0.5)      # never inside the runway's own width,
                v1 = max(side[1], float(((pts - a) @ nr).max()) + 0.5)      # so the legs start on its outline
                p0, p1, p2, p3 = a + nr * v0, a + nr * v1, a + nr * v1 + d * u1, a + nr * v0 + d * u1
                zlines += [LineString([a + nr * side[0] - d * 0.5, p0, p3]), LineString([p3, p2]), LineString([p2, p1, a + nr * side[1] - d * 0.5])]

    net = unary_union([fixed] + barriers + caps + zlines)
    faces = [f for f in polygonize(net) if f.area > 0.05 and P.contains(f.representative_point())]

    # --- classify every face
    chev = unary_union(t.marks_y) if t.marks_y else Polygon()
    bar = unary_union(barriers + caps) if barriers else LineString()
    force = {k: [Point(T(*p)) for p in v] for k, v in cfg.get('force', {}).items()}
    pad_r = cfg.get('pad_r', 7.0)
    out = []
    for f in faces:
        in_mov = mov.contains(f.representative_point())
        clen = cl.intersection(f).length
        crlen = clr.intersection(f).length
        wide = not f.buffer(-pad_r).is_empty
        on_edge = f.boundary.intersection(bar.buffer(0.05)).length / f.length
        on_rw = f.boundary.intersection(rw.buffer(0.05)).length
        k = None
        for kk, pts in force.items():
            if any(f.contains(p) for p in pts):
                k = kk
        if k is None and in_mov:
            if clen >= cfg.get('min_cl', 6.0) and (wide or clen >= 0.25 * f.length / 2):
                k = 'taxiway'                       # has a taxiway centreline on it
            elif chev.intersection(f).area > 5 or (not zone.is_empty and f.intersection(zone).area > 0.5 * f.area):
                k = 'blastpad'                      # chevrons, or pavement straight beyond a runway end
            elif on_rw > 30:
                k = 'rwy_shoulder'
            else:
                k = 'shoulder'                      # outside a solid edge line
        elif k is None:
            if crlen >= 6.0 or wide or on_edge < 0.02:
                k = 'apron'
            else:
                k = 'ramp_shoulder'                 # strip of ramp pavement outside a solid edge line
        out.append(dict(geom=f, kind=k, in_mov=in_mov, clen=clen, crlen=crlen, on_edge=on_edge, on_rw=on_rw, wide=wide))
    return dict(ap=ap, t=t, cfg=cfg, structures=structures, mov=mov, ramp=ramp, rws=rws, rw=rw, P=P, barriers=barriers,
                caps=caps, dangling=dangling, faces=out, solid=solid, zone=zone, fix=fix)


# ------------------------------------------------------------------ assemble + write
def assemble(r):
    cfg = r['cfg']
    # blast pads: left out (ZOA) or drawn as taxiway (ZMA): config.json "blast_pads", or cfg.py per airport
    blast = cfg.get('blast_pads', paths.config().get('blast_pads', 'exclude')) == 'taxiway'
    bp = unary_union([f['geom'] for f in r['faces'] if f['kind'] == 'blastpad']) if blast else Polygon()
    tw = unary_union([f['geom'] for f in r['faces'] if f['kind'] == 'taxiway'] + ([bp] if blast else []))
    ap = unary_union([f['geom'] for f in r['faces'] if f['kind'] == 'apron'])
    if r['fix']['taxiway']:                     # taxiways laid through the ramp
        z = unary_union(r['fix']['taxiway'])
        tw, ap = unary_union([tw, ap.intersection(z)]), ap.difference(z)

    def desliver(g, rad):
        """Cut away pieces thinner than 2*rad (strips left between a runway stripe and the pavement edge,
        hairline faces).  Every other vertex is left exactly where it was drawn."""
        cut = [p for p in polys(g.difference(opening(g, rad))) if p.area > cfg.get('sliver_min_area', 0.05)]
        if not cut:
            return g, []
        return g.difference(unary_union(cut)), cut
    if r['structures'] and cfg.get('cut_structures', True):     # aprons are drawn around buildings, not under them
        ap = ap.difference(unary_union(r['structures']))
    tw, cut_tw = desliver(tw, cfg.get('sliver', 1.25))
    ap, cut_ap = desliver(ap, cfg.get('apron_sliver', 0.75))
    # every taxiway piece must still carry a centreline once the slivers are gone (a chunk of blast pad or
    # shoulder that was only attached through a sliver is not a taxiway)
    cl = unary_union(r['t'].cl_mov) if r['t'].cl_mov else LineString()
    tw = unary_union([p for p in polys(tw) if p.area >= cfg.get('min_tw', 150.0)
                      and (cl.intersection(p).length >= cfg.get('min_cl', 6.0) or p.intersection(bp).area > 0.5 * p.area)])
    ap = unary_union([p for p in polys(ap) if p.area >= cfg.get('min_apron', 200.0)]).difference(tw)
    return dict(runway=[x for x, i in r['rws'] if x is not None], taxiway=polys(tw), apron=polys(ap),
                structure=[g for j, g in enumerate(r['structures']) if j not in cfg.get('drop_struct', ())],
                removed=cut_tw + cut_ap)


def node_polygons(geoms, tol=0.02):
    """Give neighbouring polygons identical vertices along the edges they share: every vertex of one polygon
    that lies on (within `tol` of) another polygon's ring is inserted into that ring.  Shared edges then
    match exactly, in any projection, instead of to within a rounding step."""
    import shapely
    pts = np.array([p for g in geoms for ring in [g.exterior] + list(g.interiors) for p in ring.coords[:-1]])
    tree = shapely.STRtree(shapely.points(pts))

    def node(ring):
        c = np.array(ring.coords)
        out = []
        for a, b in zip(c[:-1], c[1:]):
            seg = LineString([a, b])
            out.append((a[0], a[1]))
            if seg.length < 2 * tol:
                continue
            idx = tree.query(seg.buffer(tol))
            on = []
            for i in idx:
                p = pts[i]
                s_ = seg.project(Point(p))
                if tol < s_ < seg.length - tol and seg.distance(Point(p)) <= tol:
                    on.append((s_, (p[0], p[1])))
            for s_, p in sorted(on):
                if np.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
                    out.append(p)
        out.append(out[0])
        return out
    res = []
    for g in geoms:
        q = Polygon(node(g.exterior), [node(h) for h in g.interiors])
        res.append(q if q.is_valid else g)
    return res


def partition(parts, grid=0.01):
    """Rebuild taxiways and aprons from ONE arrangement of every boundary, noded on a 1 cm grid, so that
    polygons that meet share exactly the same vertices: no overlaps and no hairline gaps, in any projection."""
    rw = [set_precision(g, grid) for g in parts['runway']]
    tw = [q for g in parts['taxiway'] for q in polys(set_precision(g, grid))]
    apn = [q for g in parts['apron'] for q in polys(set_precision(g, grid))]
    RW = unary_union(rw)
    net = shapely.union_all([g.boundary for g in rw + tw + apn], grid_size=grid)
    rw_f, tw_f, ap_f = [[] for _ in rw], [[] for _ in tw], [[] for _ in apn]
    for f in polygonize(net):
        rp = f.representative_point()
        if f.area <= 0:
            continue
        on_rw = [k for k, g in enumerate(rw) if g.contains(rp)]
        if on_rw:
            for k in on_rw:                  # where two runways cross, the face belongs to both
                rw_f[k].append(f)
            continue
        i = next((i for i, g in enumerate(tw) if g.contains(rp)), None)
        if i is not None:
            tw_f[i].append(f)
            continue
        j = next((j for j, g in enumerate(apn) if g.contains(rp)), None)
        if j is not None:
            ap_f[j].append(f)
    rw2 = [unary_union(fs) for fs in rw_f]
    tw2 = [q for fs in tw_f if fs for q in polys(unary_union(fs)) if q.area >= 5]
    ap2 = [q for fs in ap_f if fs for q in polys(unary_union(fs)) if q.area >= 5]
    return rw2, tw2, ap2


def write(ap, parts, path):
    rw, tw, apn = partition(parts)
    feats = []
    for k, geoms in (('runway', rw), ('taxiway', tw), ('apron', apn), ('structure', parts['structure'])):
        for g in geoms:
            for p in polys(g):
                feats.append({"type": "Feature", "properties": {"said": k},
                              "geometry": mapping(set_precision(transform(TI, p), 1e-9))})
    out = {"type": "FeatureCollection", "name": f"{ap} SAID",
           "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": feats}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, 'w'), separators=(',', ':'))
    return collections.Counter(f['properties']['said'] for f in feats)


def install(ap, path, mode=None):
    """Copy a built SAID into the maps repository.  An existing '<APT> SAID.geojson' that this builder did not
    make (a hand-drawn one) is never replaced unless mode='overwrite': the build goes next to it as
    '<APT> SAID AUTO.geojson' instead (mode='auto' forces that name).  Returns the path written."""
    ours = paths.meta(ap).get('installed')
    main = paths.said_path(ap)
    if mode is None:
        mode = 'auto' if ours == 'auto' or (os.path.exists(main) and not ours) else 'overwrite'
    dest = paths.said_path(ap, auto=(mode == 'auto'))
    d = json.load(open(path))
    d['name'] = os.path.splitext(os.path.basename(dest))[0]
    json.dump(d, open(dest, 'w'), separators=(',', ':'))
    paths.save_meta(ap, installed='auto' if mode == 'auto' else True)
    return dest


def report(r, parts, counts):
    print(f"== {r['ap']}: {len(r['solid'])} solid edge lines -> {len(r['barriers'])} dividers, {len(r['caps'])} caps, "
          f"{len(r['dangling'])} dangling ends; registration shift {r['t'].shift} m")
    fx = r['fix']
    if any(fx.values()):
        print('   corrections (airports/%s/fix.geojson): %d cut, %d add, %d edge, %d taxiway'
              % (r['ap'], len(fx['cut']), len(fx['add_mov']) + len(fx['add_ramp']), len(fx['edge']), len(fx['taxiway'])))
    for rect, i in r['rws']:
        ext = [e for e in i.get('end_ext', ()) if e]
        print('   runway', i.get('ref'), 'from', i.get('src'),
              ('%.0f x %.0f ft' % (i['length'] / .3048, i['width'] / .3048)) if rect is not None else 'FAILED',
              ('(one end moved %.1f m out to the pavement end)' % ext[0]) if ext else '')
    c, a = collections.Counter(), collections.Counter()
    for f in r['faces']:
        c[f['kind']] += 1
        a[f['kind']] += f['geom'].area
    print('   faces:', {k: (c[k], round(a[k])) for k in c})
    print('   caps over 1 m:', [(round(x.length, 1), '%.5f,%.5f' % TI(*x.coords[0])) for x in r['caps'] if x.length > 1] or 'none')
    print('   wrote', dict(counts), '; slivers cut', len(parts['removed']), 'totalling', round(sum(p.area for p in parts['removed'])), 'm2')


if __name__ == '__main__':
    sys.path.insert(0, S)
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    for ap in args:
        r = build(ap)
        parts = assemble(r)
        path = f"{S}/new/{ap} SAID.geojson"
        counts = write(ap, parts, path)
        report(r, parts, counts)
        if '--install' in sys.argv:
            mode = 'overwrite' if '--overwrite' in sys.argv else 'auto' if '--auto' in sys.argv else None
            print('   installed to', install(ap, path, mode))
