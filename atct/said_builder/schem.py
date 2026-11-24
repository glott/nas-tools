"""Schematic plot of tower-cab linework (no imagery) for topology review."""
import sys,warnings; warnings.simplefilter('ignore')
import numpy as np, matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from tc import *
def poly_patch(ax,g,**kw):
    for p in getattr(g,'geoms',[g]):
        if p.geom_type!='Polygon': continue
        verts=[];codes=[]
        for r in [p.exterior]+list(p.interiors):
            c=np.asarray(r.coords); verts+=list(c); codes+=[Path.MOVETO]+[Path.LINETO]*(len(c)-2)+[Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts,codes),**kw))
def schem(ap,out,bbox=None,size=16,labels=True,extra=None,rot=0):
    t=TC(ap); fig,ax=plt.subplots(figsize=(size,size))
    poly_patch(ax,t.mov,fc='#dcdcdc',ec='#555555',lw=0.6)
    poly_patch(ax,t.ramp,fc='#fff3b0',ec='#b59a00',lw=0.6)
    for m in t.marks_w: poly_patch(ax,m,fc='white',ec='#9a9a9a',lw=0.3)
    for m in t.marks_y: poly_patch(ax,m,fc='#ffe45c',ec='#c8a800',lw=0.3)
    for l in t.cl_mov: ax.plot(*l.xy,color='#1a9e1a',lw=0.6)
    for l in t.cl_ramp: ax.plot(*l.xy,color='#22b8cf',lw=0.6)
    for l in t.hold: ax.plot(*l.xy,color='#d63384',lw=1.4)
    for l in t.nonmov: ax.plot(*l.xy,color='black',lw=1.0,ls=(0,(4,2)))
    E=t.edge
    for i,l in enumerate(E):
        d=l.length<8 and len(l.coords)==2
        ax.plot(*l.xy,color='#1c5fd6' if d else '#e03131',lw=1.2 if d else 1.0)
        if not d:
            ax.plot([l.coords[0][0],l.coords[-1][0]],[l.coords[0][1],l.coords[-1][1]],'o',color='#e03131',ms=2.5)
            if labels:
                m=l.interpolate(0.5,normalized=True); ax.text(m.x,m.y,str(i),color='#7a0000',fontsize=7)
    if extra: extra(ax,t)
    ax.set_aspect('equal')
    if bbox:
        (x0,y0)=T(bbox[0],bbox[1]); (x1,y1)=T(bbox[2],bbox[3]); ax.set_xlim(x0,x1); ax.set_ylim(y0,y1)
    ax.set_xticks([]);ax.set_yticks([]); fig.subplots_adjust(0,0,1,1); fig.savefig(out,dpi=110); plt.close(fig); print(out)
if __name__=='__main__':
    ap=sys.argv[1]; bbox=[float(v) for v in sys.argv[3].split(',')] if len(sys.argv)>3 else None
    schem(ap,sys.argv[2],bbox,size=float(sys.argv[4]) if len(sys.argv)>4 else 16)
