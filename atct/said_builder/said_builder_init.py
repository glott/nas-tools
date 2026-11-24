"""SAID builder: guided setup.

  python said_builder_init.py              # walks you through everything, asking as it goes
  python said_builder_init.py LVK MRY      # same, for these airports
  python said_builder_init.py --yes LVK    # no questions (never installs; add --install to install as well:
                                           # next to an existing hand-drawn SAID it writes 'LVK SAID AUTO.geojson')
  python said_builder_init.py --maps PATH  # set where the tower-cab maps repository is

What it does
  1. checks the Python packages the builder needs
  2. finds the tower-cab maps repository (the folder with diagrams/ and asdex/) and remembers it
  3. shows which airports have tower-cab layers and which already have a SAID
  4. for each airport you pick: fetches runway axes and building footprints from OpenStreetMap, measures how
     far the linework sits from the imagery, builds the SAID, checks it and renders review sheets
  5. installs the SAID into asdex/ only when you say so
"""
import sys, os, json, importlib, traceback, subprocess

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
NEEDS = [('shapely', 'shapely>=2'), ('pyproj', 'pyproj'), ('numpy', 'numpy'), ('scipy', 'scipy'), ('PIL', 'Pillow'),
         ('requests', 'requests'), ('matplotlib', 'matplotlib')]
LAYERS = ('base', 'markings', 'lines', 'taxi_lines')
YES = '--yes' in sys.argv


def say(s=''):
    print(s, flush=True)


def head(n, s):
    say(f"\n[{n}] {s}\n" + '-' * (len(s) + 4))


def ask(q, default=''):
    if YES:
        return default
    try:
        a = input(f"{q} " + (f"[{default}] " if default else '')).strip()
    except EOFError:
        a = ''
    return a or default


def yes(q, default=False):
    a = ask(q + (' (Y/n)' if default else ' (y/N)'), 'y' if default else 'n')
    return a.lower().startswith('y')


# ---------------------------------------------------------------- 1. packages
def step_packages():
    head(1, 'Python packages')
    missing = []
    for mod, pip in NEEDS:
        try:
            m = importlib.import_module(mod)
            if mod == 'shapely' and int(m.__version__.split('.')[0]) < 2:
                missing.append(pip)
        except ImportError:
            missing.append(pip)
    if not missing:
        say(f"All there (Python {sys.version.split()[0]}).")
        return
    cmd = [sys.executable, '-m', 'pip', 'install'] + missing
    say('Missing: ' + ', '.join(missing))
    if yes('Install them now with pip?', True):
        if subprocess.call(cmd) == 0:
            return
    raise SystemExit('Install them with:\n  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))


# ---------------------------------------------------------------- 2. maps repository
def looks_like_maps(p):
    return bool(p) and os.path.isdir(os.path.join(p, 'diagrams'))


def step_maps():
    import paths
    head(2, 'Tower-cab maps repository')
    arg = sys.argv[sys.argv.index('--maps') + 1] if '--maps' in sys.argv else None
    cur = arg or os.environ.get('SAID_MAPS_REPO') or paths.config().get('maps_repo')
    if not looks_like_maps(cur):
        up = os.path.dirname
        guesses = [os.path.join(up(up(up(S))), 'zoa-facility-data', 'zoa-twr-cab-maps'), os.getcwd(), up(os.getcwd())]
        cur = next((g for g in guesses if looks_like_maps(g)), None)
    while True:
        if looks_like_maps(cur):
            if arg or yes(f"Use {os.path.normpath(cur)} ?", True):
                break
        elif cur:
            say(f"{cur} has no diagrams/ folder.")
        if YES:
            raise SystemExit('Pass the repository with --maps PATH')
        cur = ask('Folder of the tower-cab maps repository (the one containing diagrams/ and asdex/):').strip('"')
    cur = os.path.normpath(os.path.abspath(cur))
    paths.save_config(maps_repo=cur)
    os.makedirs(paths.said_dir(), exist_ok=True)
    if 'blast_pads' not in paths.config():
        say("\nBlast pads (the chevron areas beyond runway ends) are left out of a SAID at some facilities (ZOA) and")
        say("drawn as taxiway at others (ZMA).")
        paths.save_config(blast_pads='taxiway' if yes('Draw blast pads as taxiway?', False) else 'exclude')
    say(f"Blast pads: {'drawn as taxiway' if paths.config()['blast_pads'] == 'taxiway' else 'left out'}"
        "  (config.json \"blast_pads\": \"exclude\" or \"taxiway\")")
    say(f"Tower-cab layers are read from   {paths.diagrams_dir()}")
    say(f"Finished SAIDs are installed to  {paths.said_dir()}")


# ---------------------------------------------------------------- 3. airports
def survey():
    import paths
    rows = []
    for ap in sorted(os.listdir(paths.diagrams_dir())):
        d = os.path.join(paths.diagrams_dir(), ap)
        if not os.path.isdir(d):
            continue
        names = [f.lower() for f in os.listdir(d)]
        have = [L for L in LAYERS if any(n.endswith('_' + L + '.geojson') for n in names)]
        if not have:
            continue
        rows.append(dict(ap=ap, layers=have, ready=all(L in have for L in ('base', 'markings', 'taxi_lines')),
                         said=os.path.exists(paths.said_path(ap)), setup=os.path.exists(paths.afile(ap, 'airport.json')),
                         ours=paths.meta(ap).get('installed') is True, auto=os.path.exists(paths.said_path(ap, auto=True))))
    return rows


def step_survey():
    head(3, 'Airports')
    rows = survey()
    say('         tower-cab layers                   SAID in asdex/              builder')
    for r in rows:
        lay = ' '.join(L if L in r['layers'] else '-' * len(L) for L in LAYERS)
        said = ('built here' if r['ours'] else 'yes (not from here)' + (' + AUTO' if r['auto'] else '')) if r['said'] else 'none'
        note = 'set up' if r['setup'] else ('can be built' if r['ready'] else 'needs base, markings and taxi_lines layers')
        say(f"   {r['ap']:5s} {lay:34s} {said:27s} {note}")
    say("\nThe builder needs the base, markings and taxi_lines layers (lines is optional). It works best where the")
    say("taxi_lines layer has solid edge lines; without them taxiways follow the drawn pavement edge.")
    return rows


# ---------------------------------------------------------------- 4. one airport
def overview(ap, path, out):
    import render
    d = json.load(open(path))
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            [walk(i) for i in c]
    for f in d['features']:
        walk(f['geometry']['coordinates'])
    render.render(path, [min(xs) - .0005, min(ys) - .0005, max(xs) + .0005, max(ys) + .0005], 17, out)


def do_airport(ap, row):
    import paths
    say(f"\n=== {ap} " + '=' * 60)
    if not row or not row['ready']:
        say(f"{ap}: needs base, markings and taxi_lines layers in diagrams/{ap}/ - skipped.")
        return False
    import fetch, register, build, check, review
    say('a. Runway axes and building footprints from OpenStreetMap')
    rw = fetch.fetch(ap)
    if not rw:
        say(f"   {ap}: OpenStreetMap has no runway here, so no runway can be fitted - skipped.")
        return False
    say('b. Registration: how far the linework sits from the ArcGIS imagery')
    if 'shift' in paths.meta(ap):
        say(f"   {ap}: already measured: dx %+.2f dy %+.2f m (python register.py {ap} measures again)" % tuple(paths.meta(ap)['shift']))
    else:
        register.run(ap)
    say('c. Build')
    r = build.build(ap)
    parts = build.assemble(r)
    path = os.path.join(S, 'new', f"{ap} SAID.geojson")
    counts = build.write(ap, parts, path)
    build.report(r, parts, counts)
    say('d. Checks')
    ok = check.check(ap, path)
    say('e. Review sheets')
    ov = os.path.join(S, 'out', f"{ap}_overview.jpg")
    overview(ap, path, ov)
    feats = json.load(open(path))['features']
    pts = review.walk_points(ap, spacing=96.0)
    sheets = []
    for a in range(0, len(pts), 20):
        o = os.path.join(S, 'out', f"{ap}_walk_{a}.jpg")
        review.sheet(feats, pts[a:a + 20], o)
        sheets.append(o)
    say(f"""
{ap} is built: {path}
   checks: {'PASS' if ok else 'FAILED - see the list above'}
   runways: {', '.join('%s %.0f x %.0f ft' % (i['ref'], i['length'] / .3048, i['width'] / .3048) for x, i in r['rws'] if x is not None)}
            compare these with the published lengths: a short runway means its stripes were drawn short
   solid edge lines used: {len(r['solid'])}{'  (none: taxiways follow the drawn pavement edge)' if not r['solid'] else ''}
Look before installing:
   {ov}
   {len(sheets)} sheet(s) of zoomed tiles along every taxiway: {os.path.join(S, 'out', ap + '_walk_*.jpg')}
   or load the built file in QGIS over the imagery.
If something is wrong where the base layer no longer matches the ground (old pavement, grass drawn as ramp, a pad
whose paint is elsewhere), draw the correction into airports/{ap}/fix.geojson (README: Corrections) and run
   python build.py {ap}""")
    if not YES and hasattr(os, 'startfile') and yes('Open the overview picture now?', True):
        os.startfile(ov)
    dest, auto = paths.said_path(ap), paths.said_path(ap, auto=True)
    ours = paths.meta(ap).get('installed')
    foreign = os.path.exists(dest) and ours is not True          # a SAID there that this builder did not make
    mode = None
    if YES:
        if '--install' in sys.argv:
            mode = 'overwrite' if ('--overwrite' in sys.argv or not foreign) else 'auto'
    elif foreign:
        say(f"\n{dest} already exists and was NOT made by this builder (hand-drawn?).")
        if yes('Overwrite it with the built SAID?', False):
            mode = 'overwrite'
        elif yes(f"Keep it, and save the built one next to it as '{os.path.basename(auto)}'?", True):
            mode = 'auto'
    elif yes(f"Install it to {dest}?", False):
        mode = 'overwrite'
    if mode:
        say(f"Installed to {build.install(ap, path, mode)}")
    else:
        say(f"Not installed. When you are happy with it:  python build.py --install {ap}")
    return ok


def main():
    say(__doc__.split('\n')[0])
    step_packages()
    step_maps()
    rows = step_survey()
    by = {r['ap']: r for r in rows}
    aps = [a.upper() for i, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and sys.argv[i - 1] != '--maps']
    if not aps:
        aps = ask('\nWhich airport(s) do you want to build now? (e.g. LVK MRY, or Enter for none):').upper().replace(',', ' ').split()
    head(4, 'Build')
    if not aps:
        say('Nothing to build now.')
    for ap in aps:
        try:
            do_airport(ap, by.get(ap))
        except SystemExit as e:
            say(f"{ap}: {e}")
        except Exception:
            say(f"{ap}: the build stopped with an error:\n" + traceback.format_exc(limit=4))
    head(5, 'From here on')
    say("""   python said_builder_init.py APT      set up and build another airport
   python build.py APT                  rebuild after the tower-cab map or a correction changed
   python check.py APT                  geometry checks
   python review.py APT walk 0 20       zoomed review tiles -> out/APT_walk_0.jpg
   python build.py --install APT        rebuild and copy to asdex/APT SAID.geojson
README.md explains the rules the builder follows and how to correct a spot it gets wrong.""")


if __name__ == '__main__':
    main()
