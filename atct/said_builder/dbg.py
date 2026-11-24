"""Plot every pavement face coloured by how the builder classified it (for checking the classification)."""
import sys,warnings; warnings.simplefilter('ignore')
import numpy as np, matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from schem import poly_patch
from tc import T
import build
COL={'taxiway':'#8fd18f','shoulder':'#ffa94d','pad':'#b197fc','blastpad':'#faa2c1','apron':'#ffe066','rwy_shoulder':'#dee2e6','ramp_shoulder':'#e8590c'}
def plot(ap,out,bbox=None,size=17,r=None,labels=False):
    r=r or build.build(ap); fig,ax=plt.subplots(figsize=(size,size))
    for rw,i in r['rws']:
        if rw is not None: poly_patch(ax,rw,fc='#ffc9c9',ec='#c92a2a',lw=0.8)
    for f in r['faces']: poly_patch(ax,f['geom'],fc=COL.get(f['kind'],'#ffffff'),ec='#666666',lw=0.3)
    t=r['t']
    for l in t.cl_mov: ax.plot(*l.xy,color='#087f5b',lw=0.5)
    for l in t.cl_ramp: ax.plot(*l.xy,color='#1098ad',lw=0.4)
    for e in t.edge:
        if e.length<8 and len(e.coords)==2: ax.plot(*e.xy,color='#1c5fd6',lw=1.0)
    for l in t.hold: ax.plot(*l.xy,color='#d63384',lw=1.0)
    for l in t.nonmov: ax.plot(*l.xy,color='black',lw=0.8,ls=(0,(4,2)))
    for i,l in enumerate(r['barriers']):
        ax.plot(*l.xy,color='#e03131',lw=0.9)
        if labels:
            m=l.interpolate(0.5,normalized=True); ax.text(m.x,m.y,str(i),color='#7a0000',fontsize=7)
    for l in r['caps']: ax.plot(*l.xy,color='#1c7ed6',lw=2.5)
    for p,d in r['dangling']: ax.plot([p[0]],[p[1]],'x',color='blue',ms=10)
    ax.set_aspect('equal')
    if bbox:
        (x0,y0)=T(bbox[0],bbox[1]); (x1,y1)=T(bbox[2],bbox[3]); ax.set_xlim(x0,x1); ax.set_ylim(y0,y1)
    ax.set_xticks([]);ax.set_yticks([]); fig.subplots_adjust(0,0,1,1); fig.savefig(out,dpi=110); plt.close(fig); print(out)
    return r
if __name__=='__main__':
    ap=sys.argv[1]; bbox=[float(v) for v in sys.argv[3].split(',')] if len(sys.argv)>3 else None
    plot(ap,sys.argv[2],bbox,size=float(sys.argv[4]) if len(sys.argv)>4 else 17)
