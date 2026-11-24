"""Measure registration of hand-drawn tower-cab linework against ArcGIS imagery.
For each straight stretch of an edge line, find the nearest bright ridge (paint) across the line; the signed
normal offsets constrain a global (dx,dy) shift by least squares."""
import sys,json,os,warnings,numpy as np
warnings.simplefilter('ignore')
import twr
from render import sample
from tc import T, TI
from shapely.geometry import shape,LineString
from shapely.ops import transform
from scipy.ndimage import uniform_filter1d
def lines(ap,suffix,color):
    out=[]
    for f in twr.feats(ap,suffix):
        if str(f['properties'].get('color','')).strip().lower()!=color: continue
        for r in twr.rings(f['geometry']):
            if len(r)>1: out.append(LineString([T(*c[:2]) for c in r]))
    return out
def offsets(ln,step=4.0,D=3.0,ds=0.1,dark=False):
    res=[]; s=step
    DS=np.arange(-D,D+ds/2,ds)
    while s<ln.length-step:
        a=ln.interpolate(s-2.5);b=ln.interpolate(s+2.5);c=ln.interpolate(s)
        t=np.array([b.x-a.x,b.y-a.y]); L=np.linalg.norm(t)
        if L<4.9: s+=step; continue      # curved
        t/=L; n=np.array([-t[1],t[0]])
        al=np.arange(-2,2.01,0.5)
        X=c.x+n[0]*DS[:,None]+t[0]*al[None,:]; Y=c.y+n[1]*DS[:,None]+t[1]*al[None,:]
        lum=np.median(sample(X,Y).mean(-1),axis=1)
        sm=uniform_filter1d(lum,3)
        bg=uniform_filter1d(lum,31)
        r=(sm-bg)*(-1 if dark else 1)
        i=int(np.argmax(r))
        if r[i]>5 and 3<i<len(DS)-4: res.append((n[0],n[1],DS[i],r[i],c.x,c.y))
        s+=step
    return res
def solve(obs):
    A=np.array([[o[0],o[1]] for o in obs]); b=np.array([o[2] for o in obs])
    sh=np.zeros(2)
    for it in range(8):
        r=b-A@sh; w=(np.abs(r)<max(0.6,1.5*np.median(np.abs(r)))).astype(float)
        sh=np.linalg.lstsq(A*w[:,None],b*w,rcond=None)[0]
    r=b-A@sh
    return sh,float(np.median(np.abs(r))),float(np.mean(np.abs(r)<0.5)),len(obs)
if __name__=='__main__':
    for ap in sys.argv[1:]:
        ls=lines(ap,'_taxi_lines.geojson','#a29857')
        obs=[o for l in ls for o in offsets(l)]
        if len(obs)>20:
            sh,mad,inl,n=solve(obs); print(ap,f"edge lines: n={n} shift dx={sh[0]:+.2f} dy={sh[1]:+.2f} m  residual MAD={mad:.2f} inliers(<0.5m)={inl:.0%}")
            b=np.array([o[2] for o in obs]); print('   raw |offset| median',round(float(np.median(np.abs(b))),2),' quartiles',np.round(np.percentile(b,[10,25,50,75,90]),2))
            # regional variation
            xs=np.array([o[4] for o in obs]); ys=np.array([o[5] for o in obs])
            for nm,m in [('W',xs<np.median(xs)),('E',xs>=np.median(xs)),('S',ys<np.median(ys)),('N',ys>=np.median(ys))]:
                o2=[o for o,k in zip(obs,m) if k]
                if len(o2)>20: s2,mad2,inl2,n2=solve(o2); print(f"   {nm}: dx={s2[0]:+.2f} dy={s2[1]:+.2f} n={n2}")
        cl=lines(ap,'_taxi_lines.geojson','#858585')
        obs=[o for l in cl for o in offsets(l)]
        if len(obs)>20:
            sh,mad,inl,n=solve(obs); print(ap,f"centerlines: n={n} shift dx={sh[0]:+.2f} dy={sh[1]:+.2f} m  residual MAD={mad:.2f} inliers={inl:.0%}")
