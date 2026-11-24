"""Fetch the two inputs the builder cannot take from the tower-cab map, from OpenStreetMap (Overpass API):

  airports/<APT>/osm.json            aeroways; only the runway axes are used (one rectangle is fitted per axis)
  airports/<APT>/structures.geojson  building footprints next to the pavement, for the SAID's structure features

  python fetch.py LVK            # skips files that already exist
  python fetch.py --force LVK    # fetch again and overwrite

Only the airport's bounding box is sent.  Footprints are a starting point: open structures.geojson in QGIS and
delete / redraw as needed, the builder copies it into the SAID unchanged.
"""
import sys, os, json, warnings
warnings.simplefilter('ignore')
import requests
from shapely.geometry import Polygon, mapping
from shapely.ops import transform, unary_union
import paths
from tc import TC, T, TI

URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")


def bbox(t, pad=200.0):
    g = unary_union([g for c, p, g in t.layers['base']])
    x0, y0, x1, y1 = g.bounds
    w, s = TI(x0 - pad, y0 - pad)
    e, n = TI(x1 + pad, y1 + pad)
    return s, w, n, e


def overpass(s, w, n, e):
    q = f'[out:json][timeout:90];(way["aeroway"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});way["building"]({s:.5f},{w:.5f},{n:.5f},{e:.5f}););out geom;'
    err = None
    for url in URLS + URLS:                # each mirror twice: they are often busy
        try:
            r = requests.post(url, data={'data': q}, timeout=60, headers={'User-Agent': 'said-builder'})
            r.raise_for_status()
            return r.json()
        except Exception as ex:          # try the next mirror
            err = ex
    raise SystemExit(f"OpenStreetMap (Overpass) request failed: {err}")


def structures(ap, osm, t, near=45.0, min_area=60.0):
    """Buildings within `near` metres of pavement."""
    pav = unary_union([g for c, p, g in t.layers['base']]).buffer(0)
    out = []
    for el in osm['elements']:
        tg = el.get('tags', {})
        if 'geometry' not in el or not ('building' in tg or tg.get('aeroway') in ('hangar', 'terminal')):
            continue
        ring = [(p['lon'], p['lat']) for p in el['geometry']]
        if len(ring) < 4 or ring[0] != ring[-1]:
            continue
        g = transform(T, Polygon(ring)).buffer(0)
        if g.is_empty or g.geom_type != 'Polygon' or g.area < min_area or g.distance(pav) > near:
            continue
        g = Polygon(g.exterior).simplify(0.05)         # no courtyards, no collinear clutter
        out.append({"type": "Feature", "properties": {"said": "structure"},
                    "geometry": mapping(Polygon([(round(x, 7), round(y, 7)) for x, y in transform(TI, g).exterior.coords]))})
    return {"type": "FeatureCollection", "name": f"{ap} structures",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": out}


def fetch(ap, force=False):
    paths.adir(ap, make=True)
    po, ps = paths.afile(ap, 'osm.json'), paths.afile(ap, 'structures.geojson')
    t = TC(ap, shift=(0, 0))
    if not t.layers['base']:
        raise SystemExit(f"{ap}: no base layer found in {os.path.join(paths.diagrams_dir(), ap)}")
    if force or not os.path.exists(po):
        osm = overpass(*bbox(t))
        json.dump(osm, open(po, 'w', encoding='utf-8'))
        print(f"   {ap}: fetched {len(osm['elements'])} OpenStreetMap features")
    else:
        osm = json.load(open(po, encoding='utf-8'))
        print(f"   {ap}: osm.json already there (use --force to fetch again)")
    rw = [el['tags'].get('ref', '?') for el in osm['elements'] if el.get('tags', {}).get('aeroway') == 'runway' and 'geometry' in el]
    print(f"   {ap}: runways in OpenStreetMap: {', '.join(rw) or 'NONE - the build needs at least one'}")
    if force or not os.path.exists(ps):
        st = structures(ap, osm, t)
        json.dump(st, open(ps, 'w', encoding='utf-8'))
        print(f"   {ap}: wrote {len(st['features'])} building footprints to structures.geojson")
    else:
        print(f"   {ap}: structures.geojson already there, left alone")
    return rw


if __name__ == '__main__':
    for a in [a for a in sys.argv[1:] if not a.startswith('--')]:
        fetch(a.upper(), force='--force' in sys.argv)
