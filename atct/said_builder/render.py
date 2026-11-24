import sys,json,math,os,io,requests
import numpy as np
from pyproj import Transformer
from PIL import Image,ImageDraw
S=os.path.dirname(os.path.abspath(__file__))
for _d in ('tiles','new','out'): os.makedirs(f"{S}/{_d}",exist_ok=True)
def ll2px(lon,lat,z):
    n=256*2**z; x=(lon+180)/360*n
    y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    return x,y
def tile(z,x,y):
    p=f"{S}/tiles/{z}_{x}_{y}.jpg"
    if not os.path.exists(p):
        r=requests.get(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",timeout=30)
        r.raise_for_status(); open(p,'wb').write(r.content)
    return Image.open(p).convert('RGB')
_TI=Transformer.from_crs(32610,4326,always_xy=True); _px={}
def sample(X,Y,z=19):
    """RGB of the imagery at UTM zone 10N coordinates (numpy arrays of any shape)."""
    lon,lat=_TI.transform(X,Y); n=256*2**z
    x=(lon+180)/360*n; y=(1-np.arcsinh(np.tan(np.radians(lat)))/np.pi)/2*n
    tx=(x//256).astype(int); ty=(y//256).astype(int); out=np.zeros(X.shape+(3,),dtype=np.float32)
    for a,b in set(zip(tx.ravel().tolist(),ty.ravel().tolist())):
        if (z,a,b) not in _px: _px[(z,a,b)]=np.asarray(tile(z,a,b),dtype=np.float32)
        m=(tx==a)&(ty==b); out[m]=_px[(z,a,b)][(y[m]-b*256).astype(int),(x[m]-a*256).astype(int)]
    return out
COL={'runway':(255,0,0),'taxiway':(0,255,255),'apron':(255,255,0),'structure':(255,0,255)}
def render(path,bbox,z,out,fill=True,outline_only=False,maxpx=1900):
    d=json.load(open(path))
    w,s,e,n=bbox
    x0,y0=ll2px(w,n,z); x1,y1=ll2px(e,s,z)
    tx0,ty0,tx1,ty1=int(x0//256),int(y0//256),int(x1//256),int(y1//256)
    im=Image.new('RGB',((tx1-tx0+1)*256,(ty1-ty0+1)*256))
    for tx in range(tx0,tx1+1):
        for ty in range(ty0,ty1+1):
            im.paste(tile(z,tx,ty),((tx-tx0)*256,(ty-ty0)*256))
    ov=Image.new('RGBA',im.size,(0,0,0,0)); dr=ImageDraw.Draw(ov)
    def P(c): 
        x,y=ll2px(c[0],c[1],z); return (x-tx0*256,y-ty0*256)
    for f in d['features']:
        g=f['geometry']; c=COL.get(f['properties'].get('said'),(255,255,255))
        polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        for poly in polys:
            if fill and not outline_only:
                m=Image.new('L',im.size,0); md=ImageDraw.Draw(m)
                md.polygon([P(p) for p in poly[0]],fill=70)
                for h in poly[1:]: md.polygon([P(p) for p in h],fill=0)
                ov.paste(Image.new('RGBA',im.size,c+(255,)),(0,0),m)
            for ring in poly:
                dr.line([P(p) for p in ring],fill=c+(255,),width=1)
    im=Image.alpha_composite(im.convert('RGBA'),ov).convert('RGB')
    im=im.crop((int(x0-tx0*256),int(y0-ty0*256),int(x1-tx0*256),int(y1-ty0*256)))
    if max(im.size)>maxpx:
        k=maxpx/max(im.size); im=im.resize((int(im.width*k),int(im.height*k)),Image.LANCZOS)
    im.save(out,quality=88); print(out,im.size)
if __name__=='__main__':
    path=sys.argv[1]; z=int(sys.argv[2]); out=sys.argv[3]
    if len(sys.argv)>4 and sys.argv[4]!='-': bbox=[float(v) for v in sys.argv[4].split(',')]
    else:
        d=json.load(open(path)); xs=[];ys=[]
        def walk(c):
            if isinstance(c[0],(int,float)): xs.append(c[0]);ys.append(c[1])
            else: [walk(i) for i in c]
        for f in d['features']: walk(f['geometry']['coordinates'])
        bbox=[min(xs)-.0005,min(ys)-.0005,max(xs)+.0005,max(ys)+.0005]; print('bbox',bbox)
    render(path,bbox,z,out,outline_only=(len(sys.argv)>5 and sys.argv[5]=='o'))
