""" Access the Fermi CALDB for effective area tables
"""


import os
import numpy as np
from astropy.io import fits

import keyword_options


class EffectiveArea(object):

    defaults = (
        ('irf','P8R3_SOURCE_V2','IRF to use'),
        ('CALDB',None,'path to override environment variable'),
        ('use_phidep',False,'use azmithual dependence for effective area'),
        )

    @keyword_options.decorate(defaults)
    def __init__(self,**kwargs):
        keyword_options.process(self,kwargs)
        #ct0_file,ct1_file = get_irf_file(self.irf,CALDB=self.CALDB)
        if self.CALDB is None:
            self.CALDB=os.environ['CALDB']
 
        ##cdbm = pycaldb.CALDBManager(self.irf)
        aeff_file = f'{self.CALDB}/data/glast/lat/bcf/ea/aeff_{self.irf}_FB.fits'
        assert os.path.exists(aeff_file), f'Effective area file {aeff_file} not found'
        ct0_file = ct1_file = aeff_file ##cdbm.get_aeff()
        self._read_aeff(ct0_file,ct1_file)
        if self.use_phidep:
            self._read_phi(ct0_file,ct1_file)

    def _read_file(self,filename,tablename,columns):
        with fits.open(filename) as hdu:
            table = hdu[tablename]
            cbins = np.append(table.data.field('CTHETA_LO')[0],table.data.field('CTHETA_HI')[0][-1])
            ebins = np.append(table.data.field('ENERG_LO')[0],table.data.field('ENERG_HI')[0][-1])
            images = [np.asarray(table.data.field(c)[0],dtype=float).reshape(len(cbins)-1,len(ebins)-1) for c in columns]
        return ebins,cbins,images

    def _read_aeff(self,ct0_file,ct1_file):
        try:
            ebins,cbins,feffarea = self._read_file(ct0_file,'EFFECTIVE AREA',['EFFAREA'])
            ebins,cbins,beffarea = self._read_file(ct1_file,'EFFECTIVE AREA',['EFFAREA'])
        except KeyError:
            ebins,cbins,feffarea = self._read_file(ct0_file,'EFFECTIVE AREA_FRONT',['EFFAREA'])
            ebins,cbins,beffarea = self._read_file(ct1_file,'EFFECTIVE AREA_BACK',['EFFAREA'])
        self.ebins,self.cbins = ebins,cbins
        self.feffarea = feffarea[0]*1e4;self.beffarea = beffarea[0]*1e4
        self.aeff = InterpTable(np.log10(ebins),cbins)
        self.faeff_aug = self.aeff.augment_data(self.feffarea)
        self.baeff_aug = self.aeff.augment_data(self.beffarea)

    def _read_phi(self,ct0_file,ct1_file):
        try:
            ebins,cbins,fphis = self._read_file(ct0_file,'PHI_DEPENDENCE',['PHIDEP0','PHIDEP1'])
            ebins,cbins,bphis = self._read_file(ct1_file,'PHI_DEPENDENCE',['PHIDEP0','PHIDEP1'])
        except KeyError:
            ebins,cbins,fphis = self._read_file(ct0_file,'PHI_DEPENDENCE_FRONT',['PHIDEP0','PHIDEP1'])
            ebins,cbins,bphis = self._read_file(ct1_file,'PHI_DEPENDENCE_BACK',['PHIDEP0','PHIDEP1'])
        self.fphis = fphis; self.bphis = bphis
        self.phi = InterpTable(np.log10(ebins),cbins,augment=False)

    def _phi_mod(self,e,c,event_class,phi):
        # assume phi has already been reduced to range 0 to pi/2
        if phi is None: return 1
        tables = self.fphis if event_class==0 else self.bphis
        par0 = self.phi(e,c,tables[0],bilinear=False)
        par1 = self.phi(e,c,tables[1],bilinear=False,reset_indices=False)
        norm = 1. + par0/(1. + par1)
        phi = 2*abs((2./np.pi)*phi - 0.5)
        return (1. + par0*phi**par1)/norm

    def __call__(self,e,c,phi=None,event_class=-1,bilinear=True):
        """ Return bilinear (or nearest-neighbour) interpolation.
            
            Input:
                e -- bin energy; potentially array
                c -- bin cos(theta); potentially array

            NB -- if e and c are both arrays, they must be of the same
                  size; in other words, no outer product is taken
        """
        #print(f'Eff call: ({e,c})'); #return
        e = np.log10(e)
        at = self.aeff
        if event_class == -1:
            return (at(e,c,self.faeff_aug,bilinear=bilinear)*self._phi_mod(e,c,0,phi),
                    at(e,c,self.baeff_aug,bilinear=bilinear,reset_indices=False)*self._phi_mod(e,c,1,phi))
        elif event_class == 0:
            return at(e,c,self.faeff_aug)*self._phi_mod(e,c,0,phi)
        return at(e,c,self.baeff_aug)*self._phi_mod(e,c,1,phi)

    def get_file_names(self):
        return self.ct0_file,self.ct1_file


class InterpTable(object):
    def __init__(self,xbins,ybins,augment=True):
        """ Interpolation bins in energy and cos(theta)."""
        self.xbins_0,self.ybins_0 = xbins,ybins
        self.augment = augment
        if augment:
            x0 = xbins[0] - (xbins[1]-xbins[0])/2
            x1 = xbins[-1] + (xbins[-1]-xbins[-2])/2
            y0 = ybins[0] - (ybins[1]-ybins[0])/2
            y1 = ybins[-1] + (ybins[-1]-ybins[-2])/2
            self.xbins = np.concatenate(([x0],xbins,[x1]))
            self.ybins = np.concatenate(([y0],ybins,[y1]))
        else:
            self.xbins = xbins; self.ybins = ybins
        self.xbins_s = (self.xbins[:-1]+self.xbins[1:])/2
        self.ybins_s = (self.ybins[:-1]+self.ybins[1:])/2

    def augment_data(self,data):
        """ Build a copy of data with outer edges replicated."""
        d = np.empty([data.shape[0]+2,data.shape[1]+2])
        d[1:-1,1:-1] = data
        d[0,1:-1] = data[0,:]
        d[1:-1,0] = data[:,0]
        d[-1,1:-1] = data[-1,:]
        d[1:-1,-1] = data[:,-1]
        d[0,0] = data[0,0]
        d[-1,-1] = data[-1,-1]
        d[0,-1] = data[0,-1]
        d[-1,0] = data[-1,0]
        return d

    def set_indices(self,x,y,bilinear=True):
        if bilinear and (not self.augment):
            print('Not equipped for bilinear, going to nearest neighbor.')
            bilinear = False
        self.bilinear = bilinear
        if not bilinear:
            i = np.searchsorted(self.xbins,x)-1
            j = np.searchsorted(self.ybins,y)-1
        else:
            i = np.searchsorted(self.xbins_s,x)-1
            j = np.searchsorted(self.ybins_s,y)-1
        self.indices = i,j

    def value(self,x,y,data):
        i,j = self.indices
        # NB transpose here
        if not self.bilinear: return data[j,i]
        x2,x1 = self.xbins_s[i+1],self.xbins_s[i]
        y2,y1 = self.ybins_s[j+1],self.ybins_s[j]
        f00 = data[j,i]
        f11 = data[j+1,i+1]
        f01 = data[j+1,i]
        f10 = data[j,i+1]
        norm = (x2-x1)*(y2-y1)
        return ( (x2-x)*(f00*(y2-y)+f01*(y-y1)) + (x-x1)*(f10*(y2-y)+f11*(y-y1)) )/norm

    def __call__(self,x,y,data,bilinear=True,reset_indices=True):
        if reset_indices:
            self.set_indices(x,y,bilinear=bilinear)
        return self.value(x,y,data)