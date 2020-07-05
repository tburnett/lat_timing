"""
Manage weights

"""

import os, pickle
import healpy
import numpy as np
import pandas as pd
from . binner import BinnedWeights



class WeightedData(object):
    """ Add  weights to a TimedData object
        Use either a file derived from an time-averaged model, basically a map from position and energy/event type,
        or a simple functional model to map from radial position  and energy/event type
    """    
    def __init__(self, data, weight_filename=None, 
                       weight_model=None):
        """
        data : a TimedData object containing basic photon data
        weight_filename : str, the file name to open
        fix_weights: use weight_model to set or override weights
        weight_model : None or instance of WeigthModel
            if None, create a WeightModel from data and apply to bands with missing weights
            else use to override or set weights
        """
        self.data = data
        self.photon_data = data.photon_data
        self.verbose = data.verbose
        self.nside = data.nside
        self.nest  = data.nest # True if index scheme is NEST
        if  weight_filename is not None:
            self.add_weights_from_skymodel(weight_filename)
        elif weight_model is not None:
            self.add_weights_from_model(weight_model)
        else:
            raise Exception('No weight procedure')
        self.source_name = data.source_name
        self.edges=data.edges

    def dump(self, filename):
        """save all but the data object itself, only used to get a new binned exposure
        """
        d = dict(photon_data=self.photon_data.to_dict('records'),
                nside=self.nside,
                nest=self.nest,
                source_name=self.source_name,
                edges=self.edges,
                exposure=self.get_binned_exposure(self.edges) 
                )
        with open(filename, 'wb') as out:
            pickle.dump(d, out) 

    def __repr__(self):
        return f'WeightedData for source "{self.source_name}": {len(self.photon_data):,} entries'
    
    def add_weights_from_skymodel(self, filename, ):
        """Add weights to the photon data
        
        filename: pickled dict with map info
        fix_weights : bool
            if True, make model to fill in missing or bad maps
        """     
        # load a pickle containing weights, generated by pointlike
        assert os.path.exists(filename),f'File {filename} not found.'
        with open(filename, 'rb') as file:
            wtd = pickle.load(file, encoding='latin1')
        assert type(wtd)==dict, 'Expect a dictionary'
        test_elements = 'energy_bins pixels weights nside model_name radius order roi_name'.split()
        assert np.all([x in wtd.keys() for x in test_elements]),f'Dict missing one of the keys {test_elements}'

        if self.verbose>0:
            print(f'Adding weights from file {os.path.realpath(filename)}')
            pos = wtd['source_lb']
            print(f'Found weights for {wtd["source_name"]} at ({pos[0]:.2f}, {pos[1]:.2f})')
        # extract pixel ids and nside used
        wt_pix   = wtd['pixels']
        nside_wt = wtd['nside']
    
        # merge the weights into a table, with default nans
        # indexing is band id rows by weight pixel columns
        # append one empty column for photons not in a weight pixel
        # calculated weights are in a dict with band id keys        
        wts = np.full((32, len(wt_pix)+1), np.nan, dtype=np.float32)    
        weight_dict = wtd['weights']
        for k in weight_dict.keys():
            t = weight_dict[k]
            if len(t.shape)==2:
                t = t.T[0] #???
            wts[k,:-1] = t   

        # get the photon pixel ids, convert to NEST (if not already) and right shift them 
        photons = self.photon_data
        if not self.nest:
            # data are RING
            photon_pix = healpy.ring2nest(self.nside, photons.pixel.values)
        else:
            photon_pix = photons.pixel.values
        to_shift = 2*int(np.log2(self.nside/nside_wt)); 
        shifted_pix =   np.right_shift(photon_pix, to_shift)
        bad = np.logical_not(np.isin(shifted_pix, wt_pix)) 
        if self.verbose>0:
            print(f'\t{sum(bad)} / {len(bad)} photon pixels are outside weight region')
        if sum(bad)==len(bad):
            raise Exception('No weights found')
        shifted_pix[bad] = 12*nside_wt**2 # set index to be beyond pixel indices

        # find indices with search and add a "weights" column
        # (expect that wt_pix are NEST ordering and sorted) 
        weight_index = np.searchsorted(wt_pix,shifted_pix)
        band_index = np.fmin(31, photons.band.values) #all above 1 TeV into last bin
        
        # final grand lookup -- isn't numpy wonderful!
        photons.loc[:,'weight'] = wts[tuple([band_index, weight_index])] 
        if self.verbose>0:
            print(f'\t{sum(np.isnan(photons.weight.values))} weights set to NaN')
        return wtd # for reference   
    
    def add_weights_from_model(self, filename):
        assert os.path.exists(filename),f'File {filename} not found.'
        with open(filename, 'rb') as inp:
            z = pickle.load(inp)
            assert type(z)==dict, f'expected a dictionary in file {filenanme}'
            self.wm = WeightModel(z)
        if self.verbose>0:
            print(f'Adding weights from model at\n   {os.path.realpath(filename)}')
            df = self.photon_data
            df.loc[:,'weight'] = list(map(self.wm, df.band.values, df.radius.values))
        
    def get_binned_exposure(self, bins=None):
        # pass on request to the data, unless bins is an integer or None
        
        if bins is None:  return self.exposure 
        if np.isscalar(bins):
            # combine bins, leave off last bit
            n = bins
            if n==1: return self.exposure
            m = len(self.exposure)//n * n 
            return self.exposure[:m].reshape(m//n,n).sum(axis=1)
        
        return self.exposure
        ### follwing needed if bins different from starting edges
        # return self.data.get_binned_exposure(bins))
    
    def binned_weights(self, bins):
        return BinnedWeights(self, bins)     
    
class WeightedDataX(WeightedData):
    """Subclass reads in file generated by its super, which implements only multiples of basic binning,
       as saved in edges and exposure.
    """
    def __init__(self, filename):

        try:
            with open(filename, 'rb') as inp:
                dd = pickle.load(inp)
            self.photon_data = pd.DataFrame.from_dict(dd.pop('photon_data'))
            self.__dict__.update(dd)
        except Exception as e:
            print(f'WeightedDataX: failed to open data file {filename}: {e}')
            raise


def create_model_dict(df, outfile=None, make_plot=False):
    """Determine paramaters to model weight vs radius
    df : photon dataframe with weights
    outfile : output pickle
    
    returns the dictionary with parameters
    """
    import matplotlib.pyplot as plt
    dd = dict()
    vals = [0]*3
    if make_plot:
        fig, axx = plt.subplots(4,4, figsize=(10,10), sharex=True, sharey=True)
        for i, ax in enumerate(axx.flatten()):
            dfx = df[df.band==i]
            if len(dfx)>0 and max(dfx.weight)>1e-6:
                r = dfx.radius.values
                cuts = [r<0.5, np.abs(r-1)<0.2, np.abs(r-4)<0.2]
                vals = [np.mean(dfx.weight[cut]) for cut in cuts]
                dd[i]=vals
                ax.semilogy(np.sqrt(dfx.radius), dfx.weight, '.', color='lightgrey')
            else:
                # no, or bad data; use previous perhaps with mod
                dd[i]=[vals[0], vals[1], vals[2]*(4 if i<4 else 1)]

            ax.plot([0.25, 1.0, 2.0], vals, '-r', lw=2)
            ax.set(title=f'band {i}')
            ax.grid(alpha=0.5);
        ax.set(ylim=(1e-5,1));
    else:
        for i in range(16):
            dfx = df[df.band==i]
            if len(dfx)>0 and max(dfx.weight)>1e-6:
                r = dfx.radius.values
                cuts = [r<0.5, np.abs(r-1)<0.2, np.abs(r-4)<0.2]
                vals = [np.mean(dfx.weight[cut]) for cut in cuts]
                dd[i]=vals
            else:
                # no, or bad data; use previous perhaps with mod
                dd[i]=[vals[0], vals[1], vals[2]*(4 if i<4 else 1)]
              
    if outfile:
        with open(outfile, 'wb') as file:
            pickle.dump(dd, file )
        print(f'Wrote file {outfile}')
    return dd

class WeightModel(object):
    """ An empirical formula based on the weights for a weak pulsar-like source at high latitude
    """
    def __init__(self, model):
        """Parameterize weights as function of radius
        
        model_file : string | parameter dict
            if string, assume filename for the dict
        """
        if type(model)==str:
            with open(model, 'rb') as f:
                self.dd =pickle.load(f)
        else:
            self.dd=model
            
    def __call__(self, i, r):
        
        a,b,c = self.dd[min(i,13)] 
        if c==0: return 0 # kluge
        
        # note limit -- use more-reliable band 13 parameters for all above that
        sr =np.sqrt(r)
        if r<=1: 
            return a * np.exp(np.log(b/a)*sr)
        # exponential interpolation: b at 1 to c at 2
        alpha=np.log(c/b)
        beta = b**2/c
        return min(0.99, beta*np.exp(alpha*sr)) # prevent from being 1 or greater
    
    def __repr__(self):
        import pandas as pd
        r = f'{self.__class__}: parameters\n'
        r +=(str(pd.DataFrame.from_dict(self.dd, orient='index')))
        return r
    
    def plot(self, df, title=None, **kwargs):
        """
        Overplot of the model with data
        
        df : DataFrame with band, radius, and weight
        """
        import matplotlib.pyplot as plt
        fig, axx = plt.subplots(2,8, figsize=(15,4), 
                                gridspec_kw=dict(top=0.85, left=0.08, bottom=0.15),
                                sharex=True, sharey=True)
        dom = np.linspace(0,5)
        for i, ax in enumerate(axx.flatten()):
            dfx = df[df.band==i]
            if len(dfx)>0 and max(dfx.weight)>1e-6:
                r = dfx.radius.values
                ax.semilogy(np.sqrt(r), dfx.weight, 'o', color='lightgrey')
            y = [self(i,x) for x in dom]
            ax.plot(np.sqrt(dom), y, '--r', lw=2)
            ax.set_title(f'band {i}', fontsize=10)
            ax.grid(alpha=0.5);
        ax.set(ylim=(1e-4,1))
        fig.text(0.5, 0.02, r'$\sqrt{r}$', ha='center', fontsize=14)
        fig.text(0.02, 0.5, 'weight', va='center', rotation='vertical', fontsize=14)
        fig.suptitle(title)
        
    @classmethod
    def from_data(cls, data, plotit=True, **kwargs):
        """
        """
        dd = create_model_dict(data, **kwargs)
        s = cls(dd)
        if plotit:
            s.plot(data)            
        return s
    

class GetWeightedData(object):

    skymodel =   'P8_10years/uw9011'
    model_path = '/nfs/farm/g/glast/g/catalog/pointlike/skymodels/'+skymodel
    server =     'rhel6-64.slac.stanford.edu'
    username =   'burnett'

    def __init__(self, source_name, skymodel=skymodel):

        import pysftp as sftp
        from IPython.display import Image
        
        print(f'Processing model {skymodel}: retreiving data from {self.server}')
        
        srv = sftp.Connection(self.server, self.username)
        srv.chdir(self.model_path)
        
        listdir = srv.listdir()
        for needed in ['weight_files', 'sedfig']:
            if not needed in listdir:
                print( f'Did not find "{needed}" in "{self.model_path}"',file=sys.stderr)
                return
            
        # copy the source table
        f = list(filter( lambda n: n.startswith('sources_uw') , listdir))
        srv.get(f[0], '/tmp/sources.csv')
                
        # check for the weight file
        t = srv.listdir('weight_files')
        f=''
        for x in t:
            if x.startswith(source_name):
                f = x
        if not f:
            print('Did not find a weight file: need to run ...', file=sys.stderr)
            srv.close(); return
        
        tmpwf = '/tmp/'+f
        
        # copy the weight file
        srv.get('weight_files/'+f, tmpwf)
        with open(tmpwf, 'rb') as inp:
            p = pickle.load(inp,  encoding='latin1')
        key_list = 'radius  weights source_name'.split()
        for key in key_list:
            if key not in p.keys():
                print(f'Did not find key {key} in {list(p.keys())}')
                srv.close(); return
            
        # get the SED, using the actual name
        model_source_name = p['source_name']
        fname = model_source_name.replace(' ', '_').replace('+', 'p')
        t = srv.listdir('sedfig')
        f = ''
        for x in t:
            if x.startswith(fname):
                f = x
        if not f:
            print(f'Did not find SED file {fname}*', file=sys.stderr)
            srv.close(); return    
        
        print(f'found SED: {f}')
        tmpf = '/tmp/'+f
        srv.get('sedfig/'+f, tmpf)
        self.sed_image_file = tmpf

        # check the source info table for the source
        df = pd.read_csv('/tmp/sources.csv', index_col=0)
        self.src_info = df.loc[model_source_name]
        
        # finally, add the SED to the pickle
        p['sed'] = self.sed_image = Image(tmpf)
        p['model_source_name']=model_source_name
        p['src_info']=self.src_info
        with open(tmpwf, 'wb') as out:
            pickle.dump(p, out)
            



        srv.close()
                
