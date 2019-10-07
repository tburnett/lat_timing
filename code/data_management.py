"""
"""

import os, glob, pickle
import healpy
import numpy as np
import pandas as pd

from astropy.time import Time, TimeDelta
from astropy.coordinates import SkyCoord
import keyword_options

mission_start = Time('2001-01-01T00:00:00', scale='utc')
day = 24*3600

def MJD(met):
    "convert MET to MJD"
    return (mission_start+TimeDelta(met, format='sec')).mjd
def UT(met):
    " convert MET value to ISO date string"
    t=Time(MJD(met), format='mjd')
    t.format='iso'; t.out_subfmt='date_hm'
    return t.value

class Data(object):
    
    defaults=(
        ('radius', 5, 'cone radius for selection [deg]'),
        ('verbose',2,'verbosity level'),
        ('data_file_pattern','$FERMI/data/P8_P305/time_info/month_*.pkl', 'monthly photon data files'),
        ('ft2_file_pattern', '/nfs/farm/g/glast/g/catalog/P8_P305/ft2_20*.fits', 'yearly S/C history files'),
        ('gti_file_pattern', '$FERMI/data/P8_P305/yearly/*.fits', 'glob pattern for yearly Files with GTI info'),
    )

    @keyword_options.decorate(defaults)
    def __init__(self, setup,  mjd_range=None,  **kwargs):
        """
        """
        keyword_options.process(self,kwargs)
        self.l, self.b, self.mjd_range = setup.l, setup.b, mjd_range

        data_files, self.gti_files, self.ft2_files = self._check_files(mjd_range)

        self.photon_df =self._process_data(data_files)

            
    def _check_files(self, mjd_range):
        """ return lists of files to process
        """
    
        data_files = sorted(glob.glob(os.path.expandvars(self.data_file_pattern)))
        assert len(data_files)>0, 'No files found using pattern {}'.format(self.data_file_pattern)
        if self.verbose>1:
            gbtotal = np.array([os.stat(filename).st_size for filename in data_files]).sum()/2**30
            print(f'Found {len(data_files)} monthly photon data files, with {gbtotal:.1f} GB total')

        ft2_files = sorted(glob.glob(os.path.expandvars(self.ft2_file_pattern)))
        gti_files = sorted(glob.glob(os.path.expandvars(self.gti_file_pattern)))
        assert len(ft2_files)>0 and len(gti_files)>0, 'Fail to find FT2 or GTI files'
        assert len(ft2_files)--len(gti_files), 'expect to find same number of FT2 and GTI files'


        if mjd_range is not None:
            mjd_range = np.array(mjd_range).clip(mission_start.mjd, None)
            tlim =Time(mjd_range, format='mjd').datetime
            ylim,mlim = np.array([t.year for t in tlim])-2008, np.array([t.month for t in tlim])-1
            year_range = ylim.clip(0, len(gti_files)) + np.array([0,1])
            month_range = (ylim*12+mlim-8).clip(0,len(data_files)) + np.array([0,1])
            if self.verbose>0:
                print(f'Selected years {year_range}, months {month_range}')
        else:
            if self.verbose>0:
                print('Loading all found data')


        return (data_files if mjd_range is None else data_files[slice(*month_range)], 
                gti_files  if mjd_range is None else gti_files[slice(*year_range)], 
                ft2_files  if mjd_range is None else ft2_files[slice(*year_range)],
            )

    
    def _process_data(self, data_files): 

        dflist=[] 
        if self.verbose>0: print(f'Loading data from {len(data_files)} months ', end='')
        for filename in data_files:
            dflist.append(self._load_photon_data(filename))
            if self.verbose>1: print('.', end='')
        df = pd.concat(dflist)
        if self.verbose>0:
            print(f'\nSelected {len(df)} photons within {self.radius}'\
                  f' deg of  ({self.l:.2f},{self.b:.2f})')
            ta,tb = df.iloc[0].time, df.iloc[-1].time
            print(f'\tDate range: {UT(ta):20} - {UT(tb)}'\
                  f'\n\tMJD:        {MJD(ta):<20.1f} - {MJD(tb):<20.1f}')  
        return df 

    def _load_photon_data(self, filename, nside=1024):
        """Read in, process a file generated by binned_data.ConvertFT1.time_record
        
        return DataFrame with times, band id, distance from center
            
        parameters:
            filename : file name
            nside : for healpy

        returns:
            DataFrame with columns:
                band : from input, energy and event type  
                time : Mission Elapsed Time in s. (double)
                delta : distance from input position (deg, float32)
        """       
        l,b,radius = self.l, self.b, self.radius      
        with open(filename,'rb') as f:
            d = pickle.load( f ,encoding='latin1')
            tstart = d['tstart']
            df = pd.DataFrame(d['timerec'])
        # cartesian vector from l,b for healpy stuff    
        cart = lambda l,b: healpy.dir2vec(l,b, lonlat=True) 
        
        # use query_disc to get photons within given radius of position
        center = healpy.dir2vec(l,b, lonlat=True) #cart(l,b)
        ipix = healpy.query_disc(nside, cart(l,b), np.radians(radius), nest=False)
        incone = np.isin(df.hpindex, ipix)

        # times: convert to double, add to start
        t = np.array(df.time[incone],float)+tstart

        # convert position info to just distance from center             
        ll,bb = healpy.pix2ang(nside, df.hpindex[incone],  nest=False, lonlat=True)
        t2 = np.array(np.sqrt((1.-np.dot(center, cart(ll,bb)))*2), np.float32) 

        return pd.DataFrame(np.rec.fromarrays(
            [df.band[incone], t, np.degrees(t2)], names='band time delta'.split()))
    
    def write(self, filename):
        """ write to a file
        """
        out = dict(
            name=self.name, 
            galactic=(self.l,self.b), 
            radius=self.radius,
            time_data=self.data_df.to_records(index=False),
        )
        
        pickle.dump(out, open(filename, 'wb'))
    def _load_ft2(self):
        pass
    
    def _load_gti(self):
        pass
        