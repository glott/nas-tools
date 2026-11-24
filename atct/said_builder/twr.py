"""Load the hand-drawn tower-cab layers (diagrams/<APT>/) and draw them over imagery."""
import json,glob,os,math,sys,warnings
warnings.simplefilter('ignore')
from PIL import Image,ImageDraw
from render import ll2px,tile,S
import paths
def find(ap,suffix):
    for p in glob.glob(os.path.join(paths.diagrams_dir(),ap,'*')):
        if p.lower().endswith(suffix.lower()): return p
def feats(ap,suffix):
    p=find(ap,suffix)
    if not p: return []
    return [f for f in json.load(open(p,encoding='utf-8'))['features'] if f.get('geometry')]
def rings(g):
    t=g['type']; c=g['coordinates']
    if t=='Polygon': return [r for r in c]
    if t=='MultiPolygon': return [r for p in c for r in p]
    if t=='LineString': return [c]
    if t=='MultiLineString': return list(c)
    return []
STY={'#717171':(255,255,255),'#a1a1a1':(255,255,0),'#a29857':(255,140,0),'#858585':(0,255,0),'#c5c5c5':(0,200,255),'#848484':(120,160,255),'#fce028':(255,0,0),'#ffffff':(255,0,255)}
def crop(ap,lon,lat,h,px=700,layers=('base','taxi_lines','lines'),said=None,z=19,width=1,extra=None,label=None,shift=(0,0)):
    dy=h/111000; dx=h/(111000*math.cos(math.radians(lat)))
    x0,y0=ll2px(lon-dx,lat+dy,z); x1,y1=ll2px(lon+dx,lat-dy,z)
    tx0,ty0,tx1,ty1=int(x0//256),int(y0//256),int(x1//256),int(y1//256)
    im=Image.new('RGB',((tx1-tx0+1)*256,(ty1-ty0+1)*256))
    for tx in range(tx0,tx1+1):
        for ty in range(ty0,ty1+1): im.paste(tile(z,tx,ty),((tx-tx0)*256,(ty-ty0)*256))
    im=im.crop((int(x0-tx0*256),int(y0-ty0*256),int(x1-tx0*256),int(y1-ty0*256)))
    k=px/im.width; im=im.resize((px,int(im.height*k)),Image.BICUBIC); dr=ImageDraw.Draw(im)
    P0=lambda c:((ll2px(c[0],c[1],z)[0]-x0)*k,(ll2px(c[0],c[1],z)[1]-y0)*k)
    sx=shift[0]/(111320*math.cos(math.radians(lat))); sy=shift[1]/110950
    P=lambda c:P0((c[0]+sx,c[1]+sy))
    for L in layers:
        for f in feats(ap,'_'+L+'.geojson'):
            col=STY.get(str(f['properties'].get('color','')).strip().lower(),(200,200,200))
            if L=='markings': continue
            for r in rings(f['geometry']):
                if len(r)>1: dr.line([P(p) for p in r],fill=col,width=width)
    P=P0
    if said:
        from render import COL
        for f in json.load(open(said))['features']:
            if f['properties']['said']=='structure': continue
            for r in rings(f['geometry']): dr.line([P(p) for p in r],fill=COL[f['properties']['said']],width=1)
    if extra: extra(dr,P)
    m=k/(0.29858*math.cos(math.radians(lat))) if z==19 else k/(0.29858*2**(19-z)*math.cos(math.radians(lat)))
    dr.line([(8,im.height-8),(8+10*m,im.height-8)],fill=(255,255,255),width=3)
    dr.text((6,4),label or f"{lon:.5f},{lat:.5f} h={h}",fill=(255,255,0),stroke_width=2,stroke_fill=(0,0,0),font_size=15)
    return im
def sheet(ap,name,h,cols,pts,px=620,**kw):
    ims=[crop(ap,lon,lat,h,px,label=f"{lab} {lon:.5f},{lat:.5f}",**kw) for lab,lon,lat in pts]
    rows=(len(ims)+cols-1)//cols; out=Image.new('RGB',(cols*px,rows*ims[0].height))
    for i,im in enumerate(ims): out.paste(im,((i%cols)*px,(i//cols)*ims[0].height))
    os.makedirs(f"{S}/out",exist_ok=True); out.save(f"{S}/out/{name}.jpg",quality=90); print(name,out.size)
if __name__=='__main__':
    ap,name,h,cols=sys.argv[1],sys.argv[2],float(sys.argv[3]),int(sys.argv[4])
    pts=[(a.split(',')[0],float(a.split(',')[1]),float(a.split(',')[2])) for a in sys.argv[5:]]
    sheet(ap,name,h,cols,pts,px=int(os.environ.get('PX','620')),z=int(os.environ.get('Z','19')),layers=tuple(os.environ.get('LAYERS','base,taxi_lines,lines').split(',')))
