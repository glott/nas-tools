"""Diagram updater core: compare a SAID / ASDE-X file or a tower-cab base layer with OpenStreetMap and current
satellite imagery, and propose an updated copy.

How it decides
  * The imagery is classified into paved / not paved with a colour model learned from the diagram itself
    (pixels well inside the drawn pavement against pixels well outside it).  Most of a diagram is still right,
    so the model survives the parts that are not.
  * REMOVED  drawn pavement that now looks like grass or soil (wide enough, big enough).
  * ADDED    paved ground outside the drawn pavement that OpenStreetMap also has as taxiway / taxilane / apron,
             or (lower confidence) a large paved area directly attached to the drawn pavement.
  * Buildings, roads and car parks known to OpenStreetMap are never proposed as pavement.
Nothing is traced finely: proposed outlines are simplified imagery outlines meant to show WHERE the diagram is
out of date and roughly what changed.  They are drafts to redraw by hand.
"""
import json, os, math, io, time, warnings
warnings.simplefilter('ignore')
import numpy as np
import requests
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from pyproj import Transformer
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, LineString, Point, box
from shapely.ops import transform, unary_union
import contourpy

S = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(S, 'cache')
PAVED = ('runway', 'taxiway', 'apron')
MOV, RAMP = '#717171', '#a1a1a1'
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


# ------------------------------------------------------------------ geometry helpers
class Geo:
    """Local metric frame (UTM zone of the airport)."""

    def __init__(self, lon, lat):
        epsg = 32600 + int((lon + 180) // 6) + 1 + (100 if lat < 0 else 0)
        self.T = Transformer.from_crs(4326, epsg, always_xy=True).transform
        self.TI = Transformer.from_crs(epsg, 4326, always_xy=True).transform

    def m(self, g):
        return transform(self.T, g)

    def ll(self, g):
        return transform(self.TI, g)


def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon' and not p.is_empty]


def clean(g):
    g = g if g.is_valid else g.buffer(0)
    return unary_union(polys(g)) if polys(g) else Polygon()


# ------------------------------------------------------------------ diagrams
class Diagram:
    """One file to update.  kind = 'said' | 'asdex' | 'towercab'.
    classes: name -> list of feature indexes; the pavement classes are `mov` (taxiway-like) and `ramp`."""

    def __init__(self, path):
        self.path = path
        self.doc = json.load(open(path, encoding='utf-8'))
        feats = self.doc['features']
        keys = [k for f in feats for k in f.get('properties', {}) if k in ('said', 'asdex')]
        if keys:
            self.key = max(set(keys), key=keys.count)
            self.kind = self.key                           # 'said' or 'asdex'
            self.cls = [str(f['properties'].get(self.key) or '').lower() if f.get('geometry') else None for f in feats]
            self.mov, self.ramp = 'taxiway', 'apron'
        else:
            self.key, self.kind = 'color', 'towercab'
            col = [str(f['properties'].get('color') or '').strip().lower() if f.get('geometry') else None for f in feats]
            self.cls = [{MOV: 'movement', RAMP: 'ramp'}.get(c, c) for c in col]
            self.mov, self.ramp = 'movement', 'ramp'
        g0 = [shape(f['geometry']) for f in feats if f.get('geometry')]
        c = unary_union([g.envelope for g in g0]).centroid
        self.geo = Geo(c.x, c.y)
        self.geom = [clean(self.geo.m(shape(f['geometry']))) if f.get('geometry') else None for f in feats]

    @property
    def paved_classes(self):
        return PAVED if self.kind != 'towercab' else ('movement', 'ramp')

    def union(self, *classes):
        gs = [g for g, c in zip(self.geom, self.cls) if c in classes and g is not None]
        return unary_union(gs) if gs else Polygon()

    @property
    def pavement(self):
        return self.union(*self.paved_classes)

    @property
    def structures(self):
        return self.union('structure')

    @property
    def label(self):
        return {'said': 'SAID', 'asdex': 'ASDE-X', 'towercab': 'tower-cab base'}[self.kind]


# ------------------------------------------------------------------ sources: OpenStreetMap
def osm(apt, bounds_ll, refresh=False):
    """Aeroways, buildings, roads and car parks in the bounding box (cached)."""
    os.makedirs(os.path.join(CACHE, apt), exist_ok=True)
    p = os.path.join(CACHE, apt, 'osm.json')
    if os.path.exists(p) and not refresh:
        return json.load(open(p, encoding='utf-8'))
    w, s, e, n = bounds_ll
    bb = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    q = f'[out:json][timeout:90];(way["aeroway"]{bb};way["building"]{bb};way["highway"]{bb};way["amenity"="parking"]{bb};);out geom;'
    err = None
    for url in OVERPASS + OVERPASS:
        try:
            r = requests.post(url, data={'data': q}, timeout=90, headers={'User-Agent': 'diagram-updater'})
            r.raise_for_status()
            d = r.json()
            json.dump(d, open(p, 'w', encoding='utf-8'))
            return d
        except Exception as ex:
            err = ex
            time.sleep(2)
    raise SystemExit(f"OpenStreetMap (Overpass) request failed: {err}")


def osm_layers(d, geo):
    """OSM elements as metric geometries, grouped."""
    out = dict(runway=[], taxiway=[], taxilane=[], apron=[], building=[], road=[], parking=[])
    for el in d['elements']:
        tg, gm = el.get('tags', {}), el.get('geometry')
        if not gm or len(gm) < 2:
            continue
        pts = [geo.T(p['lon'], p['lat']) for p in gm]
        closed = len(pts) >= 4 and pts[0] == pts[-1]
        a = tg.get('aeroway')
        if a in ('runway', 'taxiway', 'taxilane') and not (closed and tg.get('area') == 'yes'):
            out[a].append((LineString(pts), tg))
        elif a == 'apron' and closed:
            out['apron'].append((clean(Polygon(pts)), tg))
        elif ('building' in tg or a in ('hangar', 'terminal')) and closed:
            out['building'].append((clean(Polygon(pts)), tg))
        elif tg.get('amenity') == 'parking' and closed:
            out['parking'].append((clean(Polygon(pts)), tg))
        elif 'highway' in tg and not a:
            out['road'].append((LineString(pts), tg))
    return out


# ------------------------------------------------------------------ sources: imagery
def _tile(z, x, y):
    d = os.path.join(CACHE, 'tiles')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{z}_{x}_{y}.jpg")
    if not os.path.exists(p):
        for attempt in range(3):
            try:
                r = requests.get(TILES.format(z=z, x=x, y=y), timeout=30)
                r.raise_for_status()
                open(p, 'wb').write(r.content)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1.5)
    return np.asarray(Image.open(p).convert('RGB'))


class Raster:
    """Imagery resampled onto a north-up metric grid: rgb[row, col], x = x0 + col*res, y = y1 - row*res."""

    def __init__(self, geo, bounds_m, res=0.6, z=18, progress=None):
        self.geo, self.res = geo, res
        x0, y0, x1, y1 = bounds_m
        self.x0, self.y1 = x0, y1
        self.w, self.h = int((x1 - x0) / res) + 1, int((y1 - y0) / res) + 1
        xs = x0 + (np.arange(self.w) + 0.5) * res
        ys = y1 - (np.arange(self.h) + 0.5) * res
        self.rgb = np.zeros((self.h, self.w, 3), np.uint8)
        n = 256 * 2 ** z
        lon0, lat0 = geo.TI(x0, y0)
        lon1, lat1 = geo.TI(x1, y1)
        px = lambda lon: (lon + 180) / 360 * n
        py = lambda lat: (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n
        tx0, tx1 = int(px(min(lon0, lon1) - 2e-4) // 256), int(px(max(lon0, lon1) + 2e-4) // 256)
        ty0, ty1 = int(py(max(lat0, lat1) + 2e-4) // 256), int(py(min(lat0, lat1) - 2e-4) // 256)
        mos = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
        total, k = (tx1 - tx0 + 1) * (ty1 - ty0 + 1), 0
        for a in range(tx0, tx1 + 1):
            for b in range(ty0, ty1 + 1):
                mos[(b - ty0) * 256:(b - ty0 + 1) * 256, (a - tx0) * 256:(a - tx0 + 1) * 256] = _tile(z, a, b)
                k += 1
                if progress and k % 100 == 0:
                    progress(f"imagery tiles {k}/{total}")
        for r0 in range(0, self.h, 512):                      # row blocks keep memory small
            X, Y = np.meshgrid(xs, ys[r0:r0 + 512])
            lon, lat = geo.TI(X, Y)
            cx = np.clip((px(lon) - tx0 * 256).astype(int), 0, mos.shape[1] - 1)
            cy = np.clip((py(lat) - ty0 * 256).astype(int), 0, mos.shape[0] - 1)
            self.rgb[r0:r0 + 512] = mos[cy, cx]

    def mask(self, g):
        """Rasterise a (multi)polygon."""
        im = Image.new('L', (self.w, self.h), 0)
        dr = ImageDraw.Draw(im)
        for p in polys(g):
            dr.polygon([((x - self.x0) / self.res, (self.y1 - y) / self.res) for x, y in p.exterior.coords], fill=1)
            for h in p.interiors:
                dr.polygon([((x - self.x0) / self.res, (self.y1 - y) / self.res) for x, y in h.coords], fill=0)
        return np.asarray(im, bool)

    def line_mask(self, lines, width_m):
        im = Image.new('L', (self.w, self.h), 0)
        dr = ImageDraw.Draw(im)
        for l in lines:
            dr.line([((x - self.x0) / self.res, (self.y1 - y) / self.res) for x, y in l.coords], fill=1, width=max(1, int(round(width_m / self.res))))
        return np.asarray(im, bool)

    def vectorise(self, m, simplify=1.2):
        """Mask -> polygons (metric), lightly simplified."""
        if not m.any():
            return []
        pad = np.pad(m.astype(np.float32), 1)
        gen = contourpy.contour_generator(z=pad, fill_type=contourpy.FillType.OuterOffset)
        pts_list, offs_list = gen.filled(0.5, 2.0)
        out = []
        for pts, offs in zip(pts_list, offs_list):
            rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
            rings = [np.c_[self.x0 + (r[:, 0] - 1 + 0.5) * self.res, self.y1 - (r[:, 1] - 1 + 0.5) * self.res] for r in rings if len(r) >= 4]
            if not rings:
                continue
            p = clean(Polygon(rings[0], [r for r in rings[1:]]))
            for q in polys(p.simplify(simplify)):
                out.append(q)
        return out

    def crop(self, cx, cy, half, px=520):
        """Imagery crop as a PIL image plus a function mapping metric coords to its pixels."""
        c0, r0 = int((cx - half - self.x0) / self.res), int((self.y1 - (cy + half)) / self.res)
        n = int(2 * half / self.res)
        a = np.zeros((n, n, 3), np.uint8)
        rs, cs = max(r0, 0), max(c0, 0)
        re, ce = min(r0 + n, self.h), min(c0 + n, self.w)
        if re > rs and ce > cs:
            a[rs - r0:re - r0, cs - c0:ce - c0] = self.rgb[rs:re, cs:ce]
        im = Image.fromarray(a).resize((px, px), Image.BICUBIC)
        k = px / (2 * half)
        return im, (lambda x, y: ((x - (cx - half)) * k, ((cy + half) - y) * k))


def disk(r_px):
    r = max(1, int(round(r_px)))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def opening(m, r_m, res):
    """Keep only parts at least 2*r_m wide (distance-transform opening: fast for large radii)."""
    r = r_m / res
    core = ndi.distance_transform_edt(m) > r
    return (ndi.distance_transform_edt(~core) <= r) & m


def dilate(m, r_m, res):
    return ndi.distance_transform_edt(~m) <= r_m / res


def erode(m, r_m, res):
    return ndi.distance_transform_edt(m) > r_m / res


def imagery_date(lon, lat):
    """Capture date of the World Imagery at a point (YYYY-MM-DD), or None."""
    try:
        r = requests.get("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/identify",
                         params=dict(geometry=f"{lon:.5f},{lat:.5f}", geometryType='esriGeometryPoint', sr=4326, layers='all', tolerance=1,
                                     mapExtent=f"{lon - .01:.5f},{lat - .01:.5f},{lon + .01:.5f},{lat + .01:.5f}", imageDisplay='400,400,96',
                                     returnGeometry='false', f='json'), timeout=30)
        best = None
        for res in r.json().get('results', []):
            a = res.get('attributes', {})
            d = str(a.get('SRC_DATE2') or a.get('SRC_DATE') or '')
            try:
                rs = float(a.get('SRC_RES') or 99)
            except ValueError:
                rs = 99
            if d and d.lower() != 'null' and (best is None or rs < best[0]):
                best = (rs, d)
        if not best:
            return None
        d = best[1]
        if '/' in d:
            m, dd, y = d.split()[0].split('/')
            return f"{int(y):04d}-{int(m):02d}-{int(dd):02d}"
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 and d[:8].isdigit() else d
    except Exception:
        return None


# ------------------------------------------------------------------ paved / not paved
def classify(ras, paved_mask, exclude_mask, near_m=250.0):
    """Probability that each pixel is pavement, from colour histograms learned on the diagram itself."""
    res = ras.res
    pos = erode(paved_mask, 3.0, res) & ~exclude_mask
    far = ~dilate(paved_mask, 12.0, res)
    neg = far & dilate(paved_mask, near_m, res) & ~exclude_mask
    q = (ras.rgb >> 3).astype(np.int32)
    idx = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    hp = np.bincount(idx[pos], minlength=32768).astype(np.float64).reshape(32, 32, 32)
    hn = np.bincount(idx[neg], minlength=32768).astype(np.float64).reshape(32, 32, 32)
    hp = ndi.gaussian_filter(hp, 0.8) / max(hp.sum(), 1)
    hn = ndi.gaussian_filter(hn, 0.8) / max(hn.sum(), 1)
    lut = (hp + 1e-9) / (hp + hn + 2e-9)
    prob = lut.reshape(-1)[idx].astype(np.float32)
    return ndi.uniform_filter(prob, size=max(3, int(round(2.4 / res)) | 1))


def vegetation(rgb):
    """Grass or bare soil: clearly more red/green than blue.  Asphalt and concrete, light or dark, are grey."""
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    return (np.minimum(r, g) - b > 26) & (r + g + b > 210)


# ------------------------------------------------------------------ change detection
def detect(dg, ras, layers, opt, say=print):
    """Returns a list of changes: dict(change, kind, geom, area, basis, confidence, apply, note)."""
    res = ras.res
    pav_g = dg.pavement
    pav = ras.mask(pav_g)
    bld_g = unary_union([g for g, t in layers['building']] + ([dg.structures] if not dg.structures.is_empty else []))
    bld = dilate(ras.mask(bld_g), 2.0, res) if not bld_g.is_empty else np.zeros_like(pav)
    roads = ras.line_mask([l for l, t in layers['road'] if t.get('highway') not in ('footway', 'path', 'cycleway', 'steps')], 9.0)
    park = ras.mask(unary_union([g for g, t in layers['parking']])) if layers['parking'] else np.zeros_like(pav)
    say('   learning the pavement colours from the diagram')
    prob = classify(ras, pav, bld)
    paved = prob > 0.5
    veg = vegetation(ras.rgb)
    lum = ras.rgb.mean(axis=2)
    changes = []

    # --- removed: drawn pavement that is now vegetation / soil
    notp = pav & ~paved & ~bld & veg                             # grey of any brightness is still pavement
    notp = opening(notp, opt['removed_width'] / 2, res)
    lab, n = ndi.label(notp)
    if n:
        area = ndi.sum(notp, lab, np.arange(1, n + 1)) * res * res
        keep = np.nonzero(area >= opt['removed_area'])[0] + 1
        for i in keep:
            m = lab == i
            vfrac = float(veg[m].mean())
            for g in ras.vectorise(dilate(m, res, res)):
                g = clean(g.intersection(pav_g))
                if g.area < opt['removed_area'] * 0.6:
                    continue
                changes.append(dict(change='removed', geom=g, basis='imagery', vegetation=vfrac, confidence='medium',
                                    note='drawn pavement that looks like grass or bare ground in the imagery '
                                         '(or new construction the imagery predates)'))

    # --- added: paved ground outside the drawn pavement
    lines = [(l, 'taxiway') for l, t in layers['taxiway']] + [(l, 'taxilane') for l, t in layers['taxilane']]
    osm_tw = ras.line_mask([l for l, k in lines if k == 'taxiway'], 46.0)
    osm_tl = ras.line_mask([l for l, k in lines if k == 'taxilane'], 30.0)
    osm_ap = ras.mask(unary_union([g for g, t in layers['apron']])) if layers['apron'] else np.zeros_like(pav)
    osm_any = osm_tw | osm_tl | osm_ap
    free = paved & ~dilate(pav, 2.0, res) & ~bld & ~roads & ~park
    backed = opening(free & osm_any, opt['added_width'] / 2, res)
    loose = opening(free & ~osm_any, opt['loose_width'] / 2, res)
    touch = dilate(pav, 4.0, res)
    # blast pads: pavement straight beyond a runway end
    blast_g = blast_zones(dg, layers)
    for mask, basis in ((backed, 'OpenStreetMap + imagery'), (loose, 'imagery only')):
        lab, n = ndi.label(mask)
        if not n:
            continue
        area = ndi.sum(mask, lab, np.arange(1, n + 1)) * res * res
        amin = opt['added_area'] if basis.startswith('Open') else opt['loose_area']
        for i in np.nonzero(area >= amin)[0] + 1:
            m = lab == i
            if basis == 'imagery only' and not (m & touch).any():
                continue                                          # must be attached to drawn pavement
            for g in ras.vectorise(dilate(m, 2.0, res)):
                g = clean(g.difference(pav_g))
                if g.area < amin * 0.6:
                    continue
                c = dict(change='added', geom=g, basis=basis, confidence='high' if basis.startswith('Open') else 'low')
                if not blast_g.is_empty and g.intersection(blast_g).area > 0.6 * g.area:
                    c.update(kind='blastpad', note='pavement straight beyond a runway end (blast pad / overrun)')
                changes.append(c)

    # --- what each added piece should be
    for c in changes:
        c['area'] = float(c['geom'].area)
        g = c['geom']
        if c['change'] == 'added' and c.get('kind') != 'blastpad' and dg.kind != 'towercab':
            # a narrow strip running along drawn pavement is a paved shoulder: SAID / ASDE-X leave those out
            core_w = g.buffer(-opt['shoulder_width'] / 2)
            along = g.boundary.intersection(pav_g.buffer(3.0)).length / g.length
            if core_w.is_empty and along > 0.35:
                c.update(kind='shoulder', confidence='low', note='narrow paved strip along drawn pavement: probably a shoulder')
        if c['change'] == 'removed' or c.get('kind') in ('blastpad', 'shoulder'):
            c.setdefault('kind', 'pavement')
            continue
        g = c['geom']
        tw_len = sum(l.intersection(g).length for l, k in lines if k == 'taxiway')
        ap_share = unary_union([a for a, t in layers['apron']]).intersection(g).area / g.area if layers['apron'] else 0
        ring = g.buffer(3.0)
        share = {k: ring.intersection(dg.union(k)).area for k in dg.paved_classes if k != 'runway'}
        if tw_len >= 25 and ap_share < 0.5:
            c['kind'] = dg.mov
        elif ap_share >= 0.5 or not share or max(share.values()) == 0:
            c['kind'] = dg.ramp
        else:
            c['kind'] = max(share, key=share.get)
        c['note'] = 'paved in the imagery' + (', mapped in OpenStreetMap' if c['basis'].startswith('Open') else ', attached to drawn pavement; not in OpenStreetMap')

    # --- OpenStreetMap taxiways with no drawn pavement under them (reported even where imagery is undecided)
    cover = pav_g.buffer(6.0)
    added_g = unary_union([c['geom'] for c in changes if c['change'] == 'added']).buffer(8.0) if any(c['change'] == 'added' for c in changes) else Polygon()
    for l, k in lines:
        out = l.difference(cover).difference(added_g)
        for part in getattr(out, 'geoms', [out]):
            if part.geom_type == 'LineString' and part.length >= opt['osm_line']:
                pm = ras.line_mask([part], 8.0)
                frac = float(paved[pm].mean()) if pm.any() else 0.0
                if frac < 0.35:
                    continue                                      # OSM is probably out of date there, not the diagram
                changes.append(dict(change='check', kind=dg.mov if k == 'taxiway' else dg.ramp, geom=part.buffer(9.0, cap_style=2),
                                    area=float(part.length * 18), basis='OpenStreetMap', confidence='low',
                                    note='OpenStreetMap has a %s here (%.0f m) that the diagram does not cover; imagery %.0f%% paved'
                                         % (k, part.length, 100 * frac)))

    # --- decide what gets applied to the updated copy
    for c in changes:
        if c['change'] == 'check':
            c['apply'] = False
        elif c.get('kind') == 'blastpad':
            c['apply'] = dg.kind == 'said' and opt.get('blast_pads') == 'taxiway'
            if not c['apply']:
                c['note'] += '; not applied (%s)' % ('never part of an ASDE-X map' if dg.kind == 'asdex' else 'blast pads are left out' if dg.kind == 'said' else 'draw it by hand if the map shows blast pads')
        elif c.get('kind') == 'shoulder':
            c['apply'] = False
        else:
            # a 'removed' can also be new construction the imagery predates: flagged, applied only on request
            c['apply'] = c['confidence'] == 'high' or (c['change'] == 'removed' and opt.get('apply_removed', False)) or opt.get('apply_low', False)
    changes.sort(key=lambda c: (c['change'] == 'check', -c['area']))
    for i, c in enumerate(changes, 1):
        c['id'] = i
        p = c['geom'].representative_point()
        c['lon'], c['lat'] = dg.geo.TI(p.x, p.y)
    return changes, dict(prob=prob, paved=paved, pav=pav)


def blast_zones(dg, layers, length=320.0):
    """Rectangles straight beyond each runway end (runway width + 10 m each side)."""
    zones = []
    rw = [p.minimum_rotated_rectangle for p in polys(dg.union('runway'))] if dg.kind != 'towercab' else []
    if not rw:                                                    # tower-cab base has no runway class: use OSM axes
        for l, t in layers['runway']:
            try:
                w = float(str(t.get('width', '45')).split()[0])
            except ValueError:
                w = 45.0
            rw.append(l.buffer(w / 2, cap_style=2).minimum_rotated_rectangle)
    for r in rw:
        c = np.array(r.exterior.coords)[:4]
        e = [c[1] - c[0], c[2] - c[1]]
        i = 0 if np.hypot(*e[0]) >= np.hypot(*e[1]) else 1          # long side
        ax = e[i] / np.hypot(*e[i])
        nr = np.array([-ax[1], ax[0]])
        ctr = c.mean(axis=0)
        L, W = np.hypot(*e[i]) / 2, np.hypot(*e[1 - i]) / 2 + 10
        for sgn in (1, -1):
            a = ctr + ax * sgn * L
            zones.append(Polygon([a + nr * W, a + nr * W + ax * sgn * length, a - nr * W + ax * sgn * length, a - nr * W]))
    return unary_union(zones) if zones else Polygon()


# ------------------------------------------------------------------ writing
def apply_changes(dg, changes):
    """New feature geometries: removed areas cut out of every pavement feature, added areas merged into the
    feature of their kind they touch most.  Features that are not touched keep their original geometry."""
    geom = list(dg.geom)
    touched = set()
    rem = unary_union([c['geom'] for c in changes if c['apply'] and c['change'] == 'removed'])
    if not rem.is_empty:
        for i, (g, k) in enumerate(zip(geom, dg.cls)):
            if g is not None and k in dg.paved_classes and g.intersects(rem):
                geom[i] = clean(g.difference(rem))
                touched.add(i)
    new = []
    for c in changes:
        if not (c['apply'] and c['change'] == 'added'):
            continue
        kind = dg.mov if c['kind'] == 'blastpad' else c['kind']
        # grown slightly so it closes onto the drawn pavement beside it, without overlapping any of it
        g = clean(c['geom'].buffer(2.2, join_style=2).difference(unary_union([x for x, k in zip(geom, dg.cls) if x is not None and k in dg.paved_classes])))
        cand = [(geom[i].buffer(0.5).intersection(g).area, i) for i, k in enumerate(dg.cls) if k == kind and geom[i] is not None]
        cand = [x for x in cand if x[0] > 0]
        if cand:
            i = max(cand)[1]
            geom[i] = clean(unary_union([geom[i], g]))
            touched.add(i)
        else:
            new.append((kind, g))
    return geom, touched, new


def write_updated(dg, changes, out_dir):
    """<name> UPDATED.geojson (the proposal) and <name> CHANGES.geojson (what differs, for overlaying)."""
    os.makedirs(out_dir, exist_ok=True)
    geom, touched, new = apply_changes(dg, changes)
    doc = json.loads(json.dumps(dg.doc))
    stem = os.path.splitext(os.path.basename(dg.path))[0]

    def enc(g, like):
        g = dg.geo.ll(g)
        if like == 'MultiPolygon' and g.geom_type == 'Polygon':
            g = MultiPolygon([g])
        return json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), 8))
    feats = []
    for i, f in enumerate(doc['features']):
        if i in touched:
            if geom[i].is_empty:
                continue
            like = f['geometry']['type']
            if like == 'Polygon' and len(polys(geom[i])) > 1:          # a cut split it: one feature per piece
                for p in polys(geom[i]):
                    feats.append(dict(f, geometry=enc(p, 'Polygon')))
                continue
            f = dict(f, geometry=enc(geom[i], like))
        feats.append(f)
    for kind, g in new:
        props = {dg.key: kind} if dg.kind != 'towercab' else {'color': MOV if kind == 'movement' else RAMP, 'zIndex': 0 if kind == 'movement' else 1}
        for p in polys(g):
            feats.append({"type": "Feature", "properties": props, "geometry": enc(p, 'Polygon' if dg.kind != 'towercab' else 'MultiPolygon')})
    doc['features'] = feats
    if 'name' in doc:
        doc['name'] = stem + ' UPDATED'
    up = os.path.join(out_dir, stem + ' UPDATED.geojson')
    json.dump(doc, open(up, 'w', encoding='utf-8'), separators=(',', ':'))
    cf = []
    for c in changes:
        cf.append({"type": "Feature", "geometry": json.loads(json.dumps(mapping(dg.geo.ll(c['geom']))), parse_float=lambda s: round(float(s), 7)),
                   "properties": dict(id=c['id'], change=c['change'], kind=c['kind'], area_m2=round(c['area']), basis=c['basis'],
                                      confidence=c['confidence'], applied=bool(c['apply']), note=c['note'],
                                      lon=round(c['lon'], 6), lat=round(c['lat'], 6))})
    ch = os.path.join(out_dir, stem + ' CHANGES.geojson')
    json.dump({"type": "FeatureCollection", "name": stem + ' CHANGES',
               "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": cf},
              open(ch, 'w', encoding='utf-8'), indent=1)
    return up, ch


# ------------------------------------------------------------------ pictures
COL = {'added': (0, 255, 120), 'removed': (255, 60, 60), 'check': (255, 200, 0)}


def _outline(dr, P, g, col, width=1):
    for p in polys(g):
        for ring in [p.exterior] + list(p.interiors):
            dr.line([P(x, y) for x, y in ring.coords], fill=col, width=width)


def report_images(dg, ras, changes, out_dir, per_sheet=12, px=520):
    """An overview with numbered markers, and sheets of one tile per change."""
    stem = os.path.splitext(os.path.basename(dg.path))[0]
    pav = dg.pavement
    x0, y0, x1, y1 = pav.bounds
    half = max(x1 - x0, y1 - y0) / 2 + 60
    im, P = ras.crop((x0 + x1) / 2, (y0 + y1) / 2, half, px=1800)
    dr = ImageDraw.Draw(im, 'RGBA')
    _outline(dr, P, pav, (255, 255, 255), 1)
    for c in changes:
        for p in polys(c['geom']):
            dr.polygon([P(x, y) for x, y in p.exterior.coords], fill=COL[c['change']] + (110,), outline=COL[c['change']] + (255,))
    for c in changes:
        q = c['geom'].representative_point()
        dr.text(P(q.x, q.y), str(c['id']), fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0), font_size=22)
    paths_ = [os.path.join(out_dir, stem + ' overview.jpg')]
    im.convert('RGB').save(paths_[0], quality=88)
    for s in range(0, len(changes), per_sheet):
        part = changes[s:s + per_sheet]
        cols = 4
        sheet = Image.new('RGB', (cols * px, ((len(part) + cols - 1) // cols) * px))
        for k, c in enumerate(part):
            bx0, by0, bx1, by1 = c['geom'].bounds
            h = max(bx1 - bx0, by1 - by0) / 2 + 45
            t, P = ras.crop((bx0 + bx1) / 2, (by0 + by1) / 2, h, px=px)
            dr = ImageDraw.Draw(t)
            _outline(dr, P, pav.intersection(box(bx0 - h, by0 - h, bx1 + h, by1 + h)), (255, 255, 255), 1)
            _outline(dr, P, c['geom'], COL[c['change']], 2)
            dr.text((6, 4), "#%d %s %s  %.0f m2%s" % (c['id'], c['change'], c['kind'], c['area'], '' if c['apply'] else '  (not applied)'),
                    fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0), font_size=15)
            dr.text((6, px - 22), "%.5f, %.5f   %s confidence" % (c['lat'], c['lon'], c['confidence']), fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0), font_size=13)
            sheet.paste(t, ((k % cols) * px, (k // cols) * px))
        p = os.path.join(out_dir, stem + ' changes %d-%d.jpg' % (part[0]['id'], part[-1]['id']))
        sheet.save(p, quality=88)
        paths_.append(p)
    return paths_


DEFAULTS = dict(res=0.6, zoom=18, removed_width=7.0, removed_area=300.0, added_width=8.0, added_area=400.0,
                loose_width=18.0, loose_area=1500.0, osm_line=40.0, shoulder_width=17.0, blast_pads='exclude', apply_low=False, apply_removed=False)


def run(path, apt, out_dir, opt=None, say=print, refresh=False):
    """Update one diagram.  Returns (diagram, changes, files)."""
    o = dict(DEFAULTS)
    o.update(opt or {})
    dg = Diagram(path)
    say(f"   {os.path.basename(path)}: {dg.label}, {sum(c in dg.paved_classes for c in dg.cls)} pavement features")
    pav = dg.pavement
    x0, y0, x1, y1 = pav.buffer(150).bounds
    w, s = dg.geo.TI(x0, y0)
    e, n = dg.geo.TI(x1, y1)
    say('   OpenStreetMap')
    layers = osm_layers(osm(apt, (w, s, e, n), refresh), dg.geo)
    say(f"      {len(layers['runway'])} runways, {len(layers['taxiway'])} taxiways, {len(layers['taxilane'])} taxilanes, "
        f"{len(layers['apron'])} aprons, {len(layers['building'])} buildings")
    c0 = pav.centroid
    date = imagery_date(*dg.geo.TI(c0.x, c0.y))
    say('   satellite imagery' + (f' (captured {date})' if date else ' (capture date not available)'))
    ras = Raster(dg.geo, (x0, y0, x1, y1), o['res'], o['zoom'], progress=lambda t: say('      ' + t))
    changes, dbg = detect(dg, ras, layers, o, say)
    up, ch = write_updated(dg, changes, out_dir)
    pics = report_images(dg, ras, changes, out_dir) if changes else []
    return dg, changes, dict(updated=up, changes=ch, pictures=pics, imagery_date=date), dict(ras=ras, layers=layers, **dbg)
