"""Zoomed review sheets: the SAID (translucent fill + outline) over ArcGIS imagery.

  python review.py SCK walk 0 12          # tiles 0..11 of an automatic walk along every taxiway centreline
  python review.py SCK at lab,lon,lat ... # specific spots
  env: H (half-size m, default 60)  PX (tile px, default 470)  FILE (path, default new/<APT> SAID.geojson)  FILL=0 outline only
"""
import sys, os, json, math, warnings
warnings.simplefilter('ignore')
from PIL import Image, ImageDraw
from render import ll2px, tile, S

COL = {'runway': (255, 60, 60), 'taxiway': (0, 235, 255), 'apron': (255, 235, 0), 'structure': (255, 0, 255)}


def crop(feats, lon, lat, h, px, label=None, fill=True, z=19):
    dy = h / 111000
    dx = h / (111000 * math.cos(math.radians(lat)))
    x0, y0 = ll2px(lon - dx, lat + dy, z)
    x1, y1 = ll2px(lon + dx, lat - dy, z)
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    im = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            im.paste(tile(z, tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    im = im.crop((int(x0 - tx0 * 256), int(y0 - ty0 * 256), int(x1 - tx0 * 256), int(y1 - ty0 * 256)))
    k = px / im.width
    im = im.resize((px, px), Image.BICUBIC).convert('RGBA')
    P = lambda c: ((ll2px(c[0], c[1], z)[0] - x0) * k, (ll2px(c[0], c[1], z)[1] - y0) * k)
    ov = Image.new('RGBA', im.size, (0, 0, 0, 0))
    lines = []
    for f in feats:
        kind = f['properties'].get('said')
        c = COL.get(kind, (255, 255, 255))
        g = f['geometry']
        for poly in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
            xs = [p[0] for p in poly[0]]
            ys = [p[1] for p in poly[0]]
            if max(xs) < lon - dx or min(xs) > lon + dx or max(ys) < lat - dy or min(ys) > lat + dy:
                continue
            if fill and kind != 'structure':
                m = Image.new('L', im.size, 0)
                md = ImageDraw.Draw(m)
                md.polygon([P(p) for p in poly[0]], fill=70)
                for hh in poly[1:]:
                    md.polygon([P(p) for p in hh], fill=0)
                ov.paste(Image.new('RGBA', im.size, c + (255,)), (0, 0), m)
            for ring in poly:
                lines.append(([P(p) for p in ring], c))
    im = Image.alpha_composite(im, ov).convert('RGB')
    dr = ImageDraw.Draw(im)
    for pts, c in lines:
        dr.line(pts, fill=c, width=1)
    m = k / (0.29858 * math.cos(math.radians(lat)))
    dr.line([(8, px - 8), (8 + 10 * m, px - 8)], fill=(255, 255, 255), width=3)
    dr.text((6, 4), label or f"{lon:.5f},{lat:.5f}", fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0), font_size=14)
    return im


def walk_points(ap, spacing=95.0):
    """Tile centres covering every movement centreline plus every runway/taxiway boundary of the file."""
    from tc import TC, TI
    import numpy as np
    t = TC(ap)
    pts = []
    for l in t.cl_mov:
        n = max(1, int(l.length / spacing))
        for i in range(n + 1):
            p = l.interpolate(i / n, normalized=True)
            if all(abs(p.x - q[0]) > spacing * 0.75 or abs(p.y - q[1]) > spacing * 0.75 for q in pts):
                pts.append((p.x, p.y))
    pts.sort(key=lambda p: (-round(p[1] / 250), p[0]))
    return [("W%d" % i,) + TI(x, y) for i, (x, y) in enumerate(pts)]


def sheet(feats, pts, out, h=60.0, px=470, cols=4, fill=True):
    rows = (len(pts) + cols - 1) // cols
    im = Image.new('RGB', (cols * px, rows * px))
    for i, (lab, lon, lat) in enumerate(pts):
        im.paste(crop(feats, lon, lat, h, px, f"{lab} {lon:.5f},{lat:.5f}", fill), ((i % cols) * px, (i // cols) * px))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out, quality=88)
    print(out, im.size, len(pts), 'tiles')


if __name__ == '__main__':
    ap, mode = sys.argv[1], sys.argv[2]
    h = float(os.environ.get('H', '60'))
    px = int(os.environ.get('PX', '470'))
    path = os.environ.get('FILE', f"{S}/new/{ap} SAID.geojson")
    feats = json.load(open(path))['features']
    fill = os.environ.get('FILL', '1') == '1'
    if mode == 'walk':
        pts = walk_points(ap, spacing=h * 1.6)
        print(len(pts), 'walk points')
        a, b = int(sys.argv[3]), int(sys.argv[4])
        sheet(feats, pts[a:b], f"{S}/out/{ap}_walk_{a}.jpg", h, px, int(os.environ.get('COLS', '4')), fill)
    else:
        pts = [(a.split(',')[0], float(a.split(',')[1]), float(a.split(',')[2])) for a in sys.argv[3:]]
        sheet(feats, pts, f"{S}/out/{ap}_at.jpg", h, px, int(os.environ.get('COLS', '4')), fill)
