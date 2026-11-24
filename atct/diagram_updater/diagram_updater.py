"""Diagram updater: checks SAID / ASDE-X files and tower-cab base layers against OpenStreetMap and current
satellite imagery, and writes an updated COPY plus a layer and pictures showing what differs and where.
The original file is never changed.

  python diagram_updater.py                       # asks for the folder and which diagrams to check
  python diagram_updater.py PATH                  # PATH = the atct folder (has asdex/ and diagrams/)
  python diagram_updater.py PATH SRQ SJC          # these airports, both kinds of diagram
  options:  --said-only  --towercab-only  --blast-pads taxiway|exclude  --apply-removed  --apply-low  --refresh-osm  --yes

Output, per diagram, in out/<APT>/ next to this script:
  <name> UPDATED.geojson    the proposed diagram (same format and properties as the original)
  <name> CHANGES.geojson    one polygon per difference: change (added / removed / check), kind, area, basis,
                            confidence, applied, note, lon/lat.  Load it over the diagram in QGIS.
  <name> overview.jpg       the airport with numbered differences
  <name> changes N-M.jpg    one imagery tile per difference
"""
import sys, os, glob, json, re

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
CONF = os.path.join(S, 'config.json')
YES = '--yes' in sys.argv


def ask(q, default=''):
    if YES:
        return default
    try:
        a = input(f"{q} " + (f"[{default}] " if default else '')).strip()
    except EOFError:
        a = ''
    return a or default


def conf():
    return json.load(open(CONF)) if os.path.exists(CONF) else {}


def find(root):
    """{APT: {'said': path, 'towercab': path}} for a folder with asdex/ and diagrams/."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, 'asdex', '*.geojson'))):
        m = re.match(r'^([A-Z0-9]{3,4}) (SAID|ASDEX|ASSC)\.geojson$', os.path.basename(p))
        if m:
            out.setdefault(m.group(1), {})['said'] = p
    for d in sorted(glob.glob(os.path.join(root, 'diagrams', '*'))):
        if os.path.isdir(d):
            b = [p for p in glob.glob(os.path.join(d, '*.geojson')) if p.lower().endswith('_base.geojson')]
            if b:
                out.setdefault(os.path.basename(d).upper(), {})['towercab'] = b[0]
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt_val = lambda name: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None
    if opt_val('--blast-pads') in args:
        args.remove(opt_val('--blast-pads'))
    print(__doc__.split('\n')[0])
    c = conf()
    root = args[0] if args and os.path.isdir(args[0]) else None
    while not root or not (os.path.isdir(os.path.join(root, 'asdex')) or os.path.isdir(os.path.join(root, 'diagrams'))):
        if root:
            print(f"{root} has neither an asdex/ nor a diagrams/ folder.")
        if YES and root is None and not c.get('root'):
            raise SystemExit('Give the folder: python diagram_updater.py PATH')
        root = ask('Folder with the diagrams (the one containing asdex/ and diagrams/):', c.get('root', '')).strip('"')
    root = os.path.abspath(root)
    found = find(root)
    apts = [a.upper() for a in args[1 if args and os.path.isdir(args[0]) else 0:]]
    if not apts:
        print('\n      SAID / ASDE-X            tower-cab base')
        for a, v in found.items():
            print(f"  {a:5s} {os.path.basename(v.get('said', '-')):24s} {os.path.basename(v.get('towercab', '-'))}")
        apts = ask('\nWhich airports? (e.g. SRQ TPA):').upper().replace(',', ' ').split()
    which = 'said' if '--said-only' in sys.argv else 'towercab' if '--towercab-only' in sys.argv else None
    if which is None and not YES:
        a = ask('Check (s) the SAID / ASDE-X file, (t) the tower-cab base layer, or (b) both?', 'b').lower()[:1]
        which = {'s': 'said', 't': 'towercab'}.get(a)
    jobs = []
    for a in apts:
        if a not in found:
            print(f"{a}: no diagram found in {root}")
            continue
        jobs += [(a, k, p) for k, p in found[a].items() if which in (None, k)]
    if not jobs:
        return
    import core
    # blast pads are only ever part of a SAID (never an ASDE-X map); tower-cab maps have their own spec
    blast = opt_val('--blast-pads') or c.get('blast_pads')
    if any(k == 'said' and core.Diagram(p).kind == 'said' for a, k, p in jobs) and blast not in ('taxiway', 'exclude'):
        print("\nBlast pads (paved areas beyond runway ends) are drawn as taxiway in a SAID at some facilities (ZMA)")
        print("and left out at others (ZOA).")
        blast = 'taxiway' if ask('Include blast pads in the SAID as taxiway? (y/N)', 'n').lower().startswith('y') else 'exclude'
    json.dump(dict(c, root=root, blast_pads=blast or 'exclude'), open(CONF, 'w'), indent=1)
    for apt, k, path in jobs:
        print(f"\n=== {apt}: {os.path.relpath(path, root)} " + '=' * 30)
        out = os.path.join(S, 'out', apt)
        try:
            dg, changes, files, _ = core.run(path, apt, out, dict(blast_pads=blast or 'exclude', apply_low='--apply-low' in sys.argv, apply_removed='--apply-removed' in sys.argv),
                                             refresh='--refresh-osm' in sys.argv)
        except SystemExit as e:
            print(f"   {e}")
            continue
        n = {t: sum(c['change'] == t for c in changes) for t in ('added', 'removed', 'check')}
        ap = [c for c in changes if c['apply']]
        print(f"   {len(changes)} differences: {n['added']} added, {n['removed']} removed, {n['check']} to check; "
              f"{len(ap)} applied to the updated copy ({sum(c['area'] for c in ap if c['change'] == 'added'):.0f} m2 added, "
              f"{sum(c['area'] for c in ap if c['change'] == 'removed'):.0f} m2 removed)")
        for ch in changes[:40]:
            print("   #%-3d %-8s %-9s %7.0f m2  %-6s %s  %.5f, %.5f  %s" % (ch['id'], ch['change'], ch['kind'], ch['area'], ch['confidence'],
                                                                         'applied' if ch['apply'] else '-      ', ch['lat'], ch['lon'], ch['note']))
        if files.get('imagery_date'):
            print(f"   The imagery was captured {files['imagery_date']}. If the diagram was drawn from something newer,")
            print("   'removed' findings there mean the IMAGERY is behind, not the diagram.")
        print(f"   updated copy : {files['updated']}\n   differences  : {files['changes']}")
        for p in files['pictures']:
            print(f"   picture      : {p}")
    print("\nThe updated copies are drafts: outlines of new pavement are rough imagery outlines to redraw by hand.")


if __name__ == '__main__':
    main()
