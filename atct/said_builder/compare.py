"""Build airports that already have a SAID / ASDE-X file and measure how the build differs from it.
Nothing is installed and nothing is stored except the fetched OpenStreetMap inputs.

  python compare.py HWD STS RNO                      # against the configured maps repository
  python compare.py --maps PATH --blast taxiway SRQ  # another repository / blast-pad convention

Per airport: how much of each hand-drawn class the build reproduces, and the largest disagreements.
"""
import sys, os, json, glob, collections, traceback, warnings
warnings.simplefilter('ignore')
if '--maps' in sys.argv:
    os.environ['SAID_MAPS_REPO'] = sys.argv[sys.argv.index('--maps') + 1]
import paths, fetch, build
from shapely.geometry import shape
from shapely.ops import transform, unary_union
from tc import T, TI

KINDS = ('runway', 'taxiway', 'apron')


def existing(ap):
    for p in glob.glob(os.path.join(paths.said_dir(), f"{ap} *.geojson")):
        if os.path.basename(p) in (f"{ap} SAID.geojson", f"{ap} ASDEX.geojson", f"{ap} ASSC.geojson"):
            return p


def load(p):
    out = collections.defaultdict(list)
    for f in json.load(open(p, encoding='utf-8'))['features']:
        if f.get('geometry'):
            k = f['properties'].get('said') or f['properties'].get('asdex')
            out[k].append(transform(T, shape(f['geometry'])).buffer(0))
    return {k: unary_union(v) for k, v in out.items()}


def one(ap, blast):
    ref = existing(ap)
    if not ref:
        return print(f"{ap}: no existing SAID / ASDE-X file")
    fetch.fetch(ap)
    orig = build.load_cfg
    build.load_cfg = lambda a: dict(orig(a), blast_pads=blast)
    try:
        r = build.build(ap)
        parts = build.assemble(r)
    finally:
        build.load_cfg = orig
    path = os.path.join(paths.S, 'new', f"{ap} SAID.geojson")
    build.write(ap, parts, path)
    a, b = load(path), load(ref)
    pa = unary_union([a[k] for k in KINDS if k in a])
    pb = unary_union([b[k] for k in KINDS if k in b])
    row = dict(ap=ap, edges=len(r['solid']), iou=pa.intersection(pb).area / pa.union(pb).area)
    print(f"== {ap} vs {os.path.basename(ref)}: {len(r['solid'])} solid edge lines; all pavement agrees {100 * row['iou']:.0f}% (IoU)")
    print('   runways:', ', '.join('%s %.0f x %.0f ft' % (i['ref'], i['length'] / .3048, i['width'] / .3048) for x, i in r['rws'] if x is not None))
    for k in KINDS:
        if k not in b or k not in a:
            print(f"   {k}: missing in {'build' if k not in a else 'hand-drawn'}")
            continue
        row[k] = a[k].intersection(b[k]).area / b[k].area
        print(f"   {k:8s} build covers {100 * row[k]:3.0f}% of the hand-drawn; build-only {a[k].difference(b[k]).area:7.0f} m2, hand-only {b[k].difference(a[k]).area:7.0f} m2")
    for name, g in (('build has pavement, hand-drawn none', pa.difference(pb)), ('hand-drawn has pavement, build none', pb.difference(pa))):
        g = g.buffer(-2).buffer(2)
        ps = sorted([p for p in getattr(g, 'geoms', [g]) if p.area > 400], key=lambda p: -p.area)[:4]
        if ps:
            print(f"   {name}:", ', '.join('%.0f m2 at %.5f,%.5f' % (p.area, *TI(*p.representative_point().coords[0])[::-1]) for p in ps))
    return row


if __name__ == '__main__':
    blast = sys.argv[sys.argv.index('--blast') + 1] if '--blast' in sys.argv else 'exclude'
    skip = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a in ('--maps', '--blast')}
    rows = []
    for ap in [a.upper() for a in sys.argv[1:] if not a.startswith('--') and a not in skip]:
        try:
            row = one(ap, blast)
            if row:
                rows.append(row)
        except (Exception, SystemExit):
            print(f"== {ap}: FAILED\n" + traceback.format_exc(limit=3))
    print('\nsummary (share of the hand-drawn class the build reproduces)')
    for r in rows:
        print('  %-4s edge lines %3d  pavement IoU %3.0f%%  runway %s  taxiway %s  apron %s' % (
            r['ap'], r['edges'], 100 * r['iou'], *('%3.0f%%' % (100 * r[k]) if k in r else '  - ' for k in KINDS)))
