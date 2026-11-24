"""Where things live.

  config.json            written by said_builder_init.py; machine specific, not committed
      maps_repo          the tower-cab maps repository (has diagrams/<APT>/ and asdex/)
      said_dir           optional; where finished SAIDs are installed (default <maps_repo>/asdex)
  airports/<APT>/        everything the builder keeps per airport
      airport.json       {"shift": [dx, dy]}  registration shift in metres (tower-cab linework -> imagery)
      osm.json           OpenStreetMap aeroways (runway axes)                      } fetch.py
      structures.geojson building footprints for the SAID's structure features     }
      fix.geojson        optional corrections to the base layer (see build.load_fix)
      cfg.py             optional overrides (CFG = {...})
  tiles/ new/ out/       imagery cache, build output, review sheets (not committed)

The environment variable SAID_MAPS_REPO overrides config.json.
"""
import json, os

S = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(S, 'config.json')


def config():
    return json.load(open(CONFIG, encoding='utf-8')) if os.path.exists(CONFIG) else {}


def save_config(**kw):
    c = config()
    c.update(kw)
    json.dump(c, open(CONFIG, 'w', encoding='utf-8'), indent=1)
    return c


def maps_repo():
    p = os.environ.get('SAID_MAPS_REPO') or config().get('maps_repo')
    if not p or not os.path.isdir(os.path.join(p, 'diagrams')):
        raise SystemExit("The tower-cab maps repository is not set up (or has no diagrams/ folder).\n"
                         "Run:  python said_builder_init.py")
    return p


def diagrams_dir():
    return os.path.join(maps_repo(), 'diagrams')


def said_dir():
    return config().get('said_dir') or os.path.join(maps_repo(), 'asdex')


def said_path(ap, auto=False):
    return os.path.join(said_dir(), f"{ap} SAID AUTO.geojson" if auto else f"{ap} SAID.geojson")


def installed_path(ap):
    """The file this builder installed for an airport: '<APT> SAID AUTO.geojson' if it was told to leave an
    existing '<APT> SAID.geojson' alone, else '<APT> SAID.geojson'."""
    return said_path(ap, auto=meta(ap).get('installed') == 'auto')


def adir(ap, make=False):
    d = os.path.join(S, 'airports', ap)
    if make:
        os.makedirs(d, exist_ok=True)
    return d


def afile(ap, name):
    return os.path.join(adir(ap), name)


def meta(ap):
    p = afile(ap, 'airport.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def save_meta(ap, **kw):
    m = meta(ap)
    m.update(kw)
    adir(ap, make=True)
    json.dump(m, open(afile(ap, 'airport.json'), 'w', encoding='utf-8'), indent=1)
    return m
