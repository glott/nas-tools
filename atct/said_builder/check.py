"""Checks for a built SAID file.

  python check.py SCK CCR APC             # checks new/<APT> SAID.geojson
  python check.py --installed SCK ...     # checks the installed asdex/<APT> SAID.geojson

For each airport it reports
  * format        only {"said": ...} properties, only Polygon geometries
  * validity      invalid polygons
  * overlaps      between different polygons (crossing runways overlap on purpose)
  * connectivity  runways + taxiways + aprons should form one connected piece
  * hairline gaps places where two polygons come within 0.6 m without touching
  * spurs         parts of a polygon thinner than 0.8 m
  * provenance    how much of the taxiway / apron boundary lies on a hand-drawn edge line, pavement edge or runway
  * coverage      every hand-drawn centreline should lie on a taxiway, runway or apron polygon
and ends with PASS or the list of failed checks.
"""
import json, sys, os, warnings, collections
warnings.simplefilter('ignore')
import numpy as np
from shapely.geometry import shape, Polygon
from shapely.ops import transform, unary_union
from tc import TC, T, TI
import paths

S = os.path.dirname(os.path.abspath(__file__))


def where(g):
    p = g.representative_point()
    return '%.6f,%.6f' % TI(p.x, p.y)


def check(ap, path):
    d = json.load(open(path))
    feats = d['features']
    G = [(f['properties'].get('said'), transform(T, shape(f['geometry']))) for f in feats]
    pav = [(k, g) for k, g in G if k != 'structure']
    fails = []
    print(f"== {ap}  ({path})")

    # --- format
    counts = collections.Counter(k for k, g in G)
    props = set(tuple(sorted(f['properties'])) for f in feats)
    types = set(f['geometry']['type'] for f in feats)
    print('   features:', dict(counts), ' properties:', props, ' geometry types:', types)
    if props != {('said',)} or types != {'Polygon'} or set(counts) - {'runway', 'taxiway', 'apron', 'structure'}:
        fails.append('format')

    # --- validity
    bad = [(k, where(g)) for k, g in G if not g.is_valid]
    print('   invalid polygons:', bad or 'none')
    if bad:
        fails.append('validity')

    # --- overlaps
    ov = []
    for i in range(len(pav)):
        for j in range(i + 1, len(pav)):
            if pav[i][0] == pav[j][0] == 'runway':
                continue
            a = pav[i][1].intersection(pav[j][1]).area
            if a > 0.05:
                ov.append((pav[i][0], pav[j][0], round(a, 2)))
    print('   overlaps (crossing runways excluded):', ov or 'none')
    if ov:
        fails.append('overlaps')

    # --- connectivity
    U = unary_union([g.buffer(0.02) for k, g in pav])
    comps = sorted(getattr(U, 'geoms', [U]), key=lambda c: -c.area)
    print('   connected pieces:', len(comps), [(round(c.area), where(c)) for c in comps[1:]] or '')
    if len(comps) != 1:
        fails.append('connectivity')

    # --- hairline gaps between different polygons
    U0 = unary_union([g for k, g in pav])
    hair = U0.buffer(0.3, join_style=2).buffer(-0.3, join_style=2).difference(U0.buffer(0.012))
    hl = [g for g in getattr(hair, 'geoms', [hair])
          if g.geom_type == 'Polygon' and g.area > 0.05 and sum(1 for k, x in pav if x.distance(g) < 0.05) >= 2]
    tot = sum(g.area for g in hl)
    print('   hairline gaps:', [(round(g.area, 2), where(g)) for g in sorted(hl, key=lambda g: -g.area)[:8]] or 'none',
          f' total {tot:.2f} m2')
    if tot > 1.0:
        fails.append('hairline gaps')

    # --- spurs
    sp = []
    for k, g in pav:
        o = g.buffer(-0.4, join_style=2, mitre_limit=5.0).buffer(0.4, join_style=2, mitre_limit=5.0)
        rest = g.difference(o)
        sp += [(k, p) for p in getattr(rest, 'geoms', [rest]) if p.geom_type == 'Polygon' and p.area > 0.05]
    print('   spurs thinner than 0.8 m:', [(k, round(p.area, 2), where(p)) for k, p in sorted(sp, key=lambda x: -x[1].area)[:8]] or 'none')
    if sp:
        fails.append('spurs')

    # --- provenance
    t = TC(ap)
    import build
    fix = build.load_fix(ap)
    fixg = fix['cut'] + fix['add_mov'] + fix['add_ramp'] + fix['taxiway']
    src = {'edge line': unary_union([e for e in t.edge if e.length >= 8]),
           'pavement edge': t.mov.boundary.union(t.ramp.boundary),
           'runway': unary_union([g for k, g in G if k == 'runway']).boundary,
           'correction': unary_union([g.boundary for g in fixg] + fix['edge'])}
    src = {k: v for k, v in src.items() if not v.is_empty}
    for cat in ('taxiway', 'apron'):
        g = unary_union([x for k, x in G if k == cat])
        if g.is_empty:
            continue
        b = g.boundary
        n = 4000
        best = collections.Counter()
        for i in range(n):
            p = b.interpolate(i / n, normalized=True)
            dd = {k: v.distance(p) for k, v in src.items()}
            k = min(dd, key=dd.get)
            best[k if dd[k] < 0.15 else 'other'] += 1
        nv = sum(len(p.exterior.coords) + sum(len(h.coords) for h in p.interiors) for p in getattr(g, 'geoms', [g]))
        print(f"   {cat} boundary follows:", {k: f"{v / n:.0%}" for k, v in best.most_common()}, f' ({nv} vertices)')

    # --- coverage of the hand-drawn centrelines
    by = collections.defaultdict(list)
    for k, g in G:
        by[k].append(g)
    mv = unary_union(by['taxiway'] + by['runway']).buffer(0.3)
    al = unary_union(by['taxiway'] + by['runway'] + by['apron']).buffer(0.3)
    for name, lines, cover in (('movement centrelines', t.cl_mov, mv), ('ramp centrelines', t.cl_ramp, al)):
        total = sum(l.length for l in lines)
        miss = []
        cutg = unary_union(fix['cut']).buffer(0.5) if fix['cut'] else None
        over_cut = 0.0
        for l in lines:
            m = l.difference(cover)
            if cutg is not None:               # a centreline over pavement that a correction removed is expected
                over_cut += m.intersection(cutg).length
                m = m.difference(cutg)
            miss += [p for p in getattr(m, 'geoms', [m]) if p.geom_type == 'LineString' and p.length > 3]
        ml = sum(m.length for m in miss)
        print(f"   {name}: {total:.0f} m drawn, {ml:.0f} m not covered",
              [('%.0f m' % m.length, where(m)) for m in sorted(miss, key=lambda m: -m.length)[:6]] or '',
              (f" ({over_cut:.0f} m more run over pavement removed by {ap}'s fix.geojson)" if over_cut > 3 else ''))
        if ml > 0:
            fails.append(name + ' not covered')

    print('   RESULT:', 'PASS' if not fails else 'FAIL: ' + ', '.join(fails))
    return not fails


if __name__ == '__main__':
    installed = '--installed' in sys.argv
    ok = True
    for ap in [a for a in sys.argv[1:] if not a.startswith('--')]:
        path = paths.installed_path(ap) if installed else f"{S}/new/{ap} SAID.geojson"
        ok &= check(ap, path)
    sys.exit(0 if ok else 1)
