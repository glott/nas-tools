"""Tower-cab layers in UTM metres, registered to imagery by a per-airport shift."""
import json,os,warnings,numpy as np
warnings.simplefilter('ignore')
import twr, paths
from shapely.geometry import shape,LineString,Polygon,MultiPolygon,Point
from shapely.ops import unary_union,transform
from shapely.affinity import translate
from pyproj import Transformer
T=Transformer.from_crs(4326,32610,always_xy=True).transform; TI=Transformer.from_crs(32610,4326,always_xy=True).transform
def shift_of(ap):
    """Registration shift (dx,dy) in metres from airports/<APT>/airport.json; (0,0) if not measured."""
    return tuple(paths.meta(ap).get('shift',(0.0,0.0)))
def col(f): return str(f['properties'].get('color','') or '').strip().lower()
class TC:
    def __init__(self,ap,shift=None):
        self.ap=ap; self.shift=shift_of(ap) if shift is None else tuple(shift)
        self.layers={}
        for L in ('base','taxi_lines','lines','markings'):
            out=[]
            for f in twr.feats(ap,'_'+L+'.geojson'):
                g=shape(f['geometry'])
                if g.is_empty: continue
                g=translate(transform(lambda x,y,z=None:T(x,y),g),*self.shift)
                out.append((col(f),f['properties'],g))
            self.layers[L]=out
    def lines(self,layer,color):
        out=[]
        for c,p,g in self.layers[layer]:
            if c!=color: continue
            for part in getattr(g,'geoms',[g]):
                if part.geom_type=='LineString' and part.length>0: out.append(part)
        return out
    def polys(self,layer,color):
        out=[]
        for c,p,g in self.layers[layer]:
            if c!=color: continue
            g=g.buffer(0)
            for part in getattr(g,'geoms',[g]):
                if part.geom_type=='Polygon' and part.area>0: out.append(part)
        return out
    @property
    def edge(self): return self.lines('taxi_lines','#a29857')
    @property
    def cl_mov(self): return self.lines('taxi_lines','#858585')
    @property
    def cl_ramp(self): return self.lines('taxi_lines','#c5c5c5')
    @property
    def hold(self): return self.lines('lines','#fce028')
    @property
    def nonmov(self): return self.lines('lines','#ffffff')
    @property
    def mov(self): return unary_union(self.polys('base','#717171'))
    @property
    def ramp(self): return unary_union(self.polys('base','#a1a1a1'))
    @property
    def marks_w(self): return self.polys('markings','#ffffff')
    @property
    def marks_y(self): return self.polys('markings','#fce028')+self.polys('markings','#fff777')   # chevrons, X marks (two yellows in use)
def ll(g): return transform(lambda x,y,z=None:TI(x,y),g)
