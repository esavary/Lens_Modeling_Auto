from __future__ import print_function
import numpy as np
import matplotlib.pyplot as plt
import os, sys, psutil
import PIL
import astropy.io.fits as pyfits
import astropy.io.ascii as ascii
import scipy
import pandas
from scipy.ndimage.filters import gaussian_filter as gauss1D
from scipy import optimize
from pylab import figure, cm
from matplotlib.colors import LogNorm
from lenstronomy.Workflow.fitting_sequence import FittingSequence
from lenstronomy.Data.imaging_data import ImageData
from lenstronomy.Data.psf import PSF
from lenstronomy.Util.util import make_grid_with_coordtransform
from lenstronomy.LensModel.lens_param import LensParam
from lenstronomy.LightModel.light_param import LightParam
from copy import deepcopy
from scipy.ndimage import gaussian_laplace
from skimage.feature import peak_local_max
from scipy.ndimage import gaussian_laplace
from matplotlib.patches import Circle
from matplotlib.colors import SymLogNorm
# from lenstronomy.Util.mask_util import mask_sphere
from lenstronomy.Util.mask_util import mask_center_2d
from lenstronomy.Util.param_util import ellipticity2phi_q
from astropy.table import QTable
from astropy.stats import sigma_clipped_stats
from scipy.spatial import distance


def calcBackgroundRMS(image_data):
    
    '''
    Calculate background root-mean-square (rms) of each image.
        :image_data: List of images (dim = 3)
    
    Returns:
        :background_rms: list of floats. Background rms value of each image in image_data.
    
    '''
    
    
    #Equation for root-mean-square. 
    def rms(array):
        return np.sqrt(np.mean(np.square(array)))
    
    background_rms = []
    
    for im in image_data:
        
        #take 5x5 pixel slices from each corner of image to use for rms computation
        corners = np.zeros([4,5,5])
        means = np.zeros(4)
        rms_array = np.zeros(4)
        corners[0] = im[0:5,0:5]
        corners[1] = im[-5:,0:5]
        corners[2] = im[0:5,-5:]
        corners[3] = im[-5:,-5:]


        #mean flux of each corner
        for i in range(len(corners)):
            means[i] = np.mean(corners[i]) 

        #rms of each corner
        for i in range(len(corners)):
            rms_array[i] = rms(corners[i])

#         print('Mean values: ', means, '\n',
#             'rms values: ',rms_array)

        #Exclude corners with average flux > twice the minimum flux
        rms_good = [rms_array[means == means.min()]]
        for x in means[means != means.min()]:
            if (x <= means.min() + 1.0 * np.abs(means.min())): 
                rms_good.append(rms_array[means == x])

#         print('good rms: ',rms_good, '\n',
#               'background_rms: ',np.mean(rms_good))
        background_rms.append(np.mean(rms_good)) #array of background rms values of each image

    return background_rms


def prepareData(lens_info,lens_data,psf_data):
    '''
    Takes raw data, psf, noise map, etc and formats them as lists of dictionaries, "kwargs_data" and "kwargs_psf", which can then 
    be passed to Lenstronomy.
    
        :lens_info: list of dictionaries (length = # of bands). Contains info about data in each band, including pixel scale 
        (deltaPix in arcsec/pixel), psf upsample factor, data array length (numPix), exposure time, noise map, and background 
        rms. 
        :lens_data: raw image data arrays with shape (# of bands, numPix, numPix) (e.g. [data_band1, data_band2, ...], where each 
        data_band is a 2D array of the image in that band).
        :psf_data: psf data arrays in the form [psf_band1, psf_band2, ...]
    
    Returns: 
        :kwargs_data: list of dictionaries with length = # bands, containing data and info.
        :kwargs_psf: list of dictionaries with length = # bands, containing psf data and info.
    
    '''
    
    kwargs_data = []
    kwargs_psf = []
    
    #loop though bands
    for i,x in enumerate(lens_info):
        
        #define image coordinate system/grid using image dimensions (numPix) and pixel scale (deltaPix)
        _,_,ra_at_xy_0,dec_at_xy_0,_,_,transform_pix2angle,_ =  make_grid_with_coordtransform(numPix = x['numPix'],
                                                                                              deltapix = x['deltaPix'])
        
        #make kwargs_data dictionary for band[i] with image data, coordinate grid, and info from lens_info
        kwargs_data.append({'image_data': lens_data[i],
                   'background_rms': x['background_rms'],
                   'exposure_time': x['exposure_time'],
                   'noise_map': x['noise_map'],
                   'ra_at_xy_0':ra_at_xy_0,  
                   'dec_at_xy_0': dec_at_xy_0,
                   'transform_pix2angle': transform_pix2angle})


        #make kwargs_psf for band[i] with psf data and relevant info
        kwargs_psf.append({'psf_type': x['psf_type'],  
                           'kernel_point_source': psf_data[i],  
                           'point_source_supersampling_factor': x['psf_upsample_factor']})
    
    return kwargs_data, kwargs_psf

def removekeys(d, keys):
    ''' 
    Create new dictionary, r, out of dictionary d with keys removed. 
    '''
    r = dict(d)
    for k in keys:
        del r[k]
    return r

def openFITS(filepath):
    '''
    Opens FITS files and reads data and headers. Supports datacubes with multiple bands in one FITS file.
    '''
    data = []
    hdr = []
    with pyfits.open(filepath) as file:
        for f in file:
            data.append(deepcopy(f.data))
            hdr.append(deepcopy(f.header))
            del f.data
        file.close()
    return data, hdr

def printMemory(location):
    '''
    Print total memory in Megabytes currently being used by script. 
        :location: string. Just so you know where in the modeling process this amount of memory is currently being used.
    '''
    print('$$$$$$$$$$$$$$$$$$$ Memory Usage ({}) $$$$$$$$$$$$$$$$$$$$$$$$$$'.format(location))
    process = psutil.Process(os.getpid())
    print('{} Megabytes'.format(float(process.memory_info().rss) / 2**(20)))  # in Megabytes 
    print('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    
    
def optParams(kwargs_init,opt_params,model_kwarg_names):
    '''
    Function for setting up init and fixed dictionaries for optimizing specific model parameters and fixing the rest. Can be 
    used for making a chain of PSO fits in pre-optimization scheme as desired in a less messy way. Used in optimize_dynamic.py
    script.
    
        :kwargs_init: initial parameter values for modeling. Same format as kwargs_result after a fit. 
        :opt_params: dictionary with 'kwargs_lens','kwargs_source', and 'kwargs_lens_light' as keys. Values are arrays with names 
        of parameters to optimize in the next fit. 
        :model_kwarg_names: Dictionary. All parameter names in profiles in source, lens, and lens_light model lists.
    
    Returns: 
        :args_init: dictionary of initialization parameters
        :args_fixed: dictionary of fixed parametes
    '''
    
    fixed_lens = []
    kwargs_lens_init = []
    
    for i in range(len(model_kwarg_names['kwargs_lens'])):     # num iterations correspond to num profiles in lens_model_list
        kwargs_lens_init.append(kwargs_init['kwargs_lens'][i])  
        
        #fix all params (and their values) that are not being optimized
        fixed_lens.append(removekeys(kwargs_init['kwargs_lens'][i],opt_params['kwargs_lens'][i]))  
    
    fixed_source = []
    kwargs_source_init = []
    
    for i in range(len(model_kwarg_names['kwargs_source'])):
        kwargs_source_init.append(kwargs_init['kwargs_source'][i])
        fixed_source.append(removekeys(kwargs_init['kwargs_source'][i],opt_params['kwargs_source'][i]))
    
    fixed_lens_light = []
    kwargs_lens_light_init = []
    
    for i in range(len(model_kwarg_names['kwargs_lens_light'])):
        kwargs_lens_light_init.append(kwargs_init['kwargs_lens_light'][i])
        fixed_lens_light.append(removekeys(kwargs_init['kwargs_lens_light'][i],opt_params['kwargs_lens_light'][i]))
    
    args_init = {'kwargs_lens': kwargs_lens_init, 
                 'kwargs_source': kwargs_source_init, 
                 'kwargs_lens_light': kwargs_lens_light_init}
    
    args_fixed = {'kwargs_lens': fixed_lens, 
                 'kwargs_source': fixed_source, 
                 'kwargs_lens_light': fixed_lens_light}
    return args_init, args_fixed

def get_kwarg_names(lens_model_list,source_model_list,lens_light_model_list,kwargs_fixed = None):
    '''
    Function to get all parameter names for specific profiles used in lens, source, and lens_light model_lists.
    
        :lens_model_list:list of strings. Profiles used for modeling lens mass
        :source_model_list:list of strings. Profiles used for modeling source light
        :lens_light_model_list:list of strings. Profiles used for modeling lens light
        :kwargs_fixed: dictionary corresponding to fixed parameters in lens, source, and lens light profiles.
    
    Returns:
        :model_kwarg_names: dictionary with parameter names of lens, source, and lens_light profiles
    '''
    if kwargs_fixed == None:
        kwargs_fixed = {'kwargs_lens': [], 'kwargs_source': [] , 'kwargs_lens_light': []}
        for i in range(len(lens_model_list)): kwargs_fixed['kwargs_lens'].append({})
        for j in range(len(source_model_list)): kwargs_fixed['kwargs_source'].append({})
        for k in range(len(lens_light_model_list)): kwargs_fixed['kwargs_lens_light'].append({})
    
    lens_model = LensParam(lens_model_list,kwargs_fixed['kwargs_lens'])
    lens_params_list = lens_model._param_name_list
    lens_params=np.array([np.array(xi) for xi in lens_params_list])
    
    source_model = LightParam(source_model_list,kwargs_fixed['kwargs_source'])
    source_params_list = source_model._param_name_list
    source_params = np.array([np.array(xi) for xi in source_params_list])
    
    lens_light_model = LightParam(lens_light_model_list,kwargs_fixed['kwargs_lens_light'])
    lens_light_params_list = lens_light_model._param_name_list
    lens_light_params = np.array([np.array(xi) for xi in lens_light_params_list])
    
    
    
    model_kwarg_names = {'kwargs_lens': np.array(lens_params),
                        'kwargs_source': np.array(source_params),
                        'kwargs_lens_light': np.array(lens_light_params)}
    return model_kwarg_names


def prior_phi_q_gaussian(kwargs_list, prior_list):
        """
        Function for placing gaussian priors on aspect ratio q by first converting e1 and e2 ellipticity parameters (used in 
        Lenstronomy modeling) to q and phi.
        
            :param kwargs_list: keyword argument list
            :param prior_list: prior list
            :return: logL
        """
        
        logL = 0
        
        if not kwargs_list: 
            pass                   #So nothing crashes if there is not lens light or source light model
        else:
            for i in range(len(prior_list)):
                index, param_name, value, sigma = prior_list[i]

                if (('e1' in kwargs_list[index]) and ('e2' in kwargs_list[index])): 
                    model_e1 = kwargs_list[index]['e1']
                    model_e2 = kwargs_list[index]['e2']

                    model_vals = {}
                    model_vals['phi'], model_vals['q'] = ellipticity2phi_q(model_e1,model_e2)

                    dist = (model_vals[param_name] - value) ** 2 / sigma ** 2 / 2 
                    logL -= np.sum(dist)
                    
#                     print('prior: {} \n model value: {} \n mean value: {} \n sigma: {}'.format(param_name,
#                                                                                            model_vals[param_name],
#                                                                                            value,sigma))
                else: 
                    pass
        
        return logL

def join_param_between_bands(kwargs_list, prior_list):
    """
    Gaussian prior for joining parameter in one band to that of another band.
        :param kwargs_list: keyword argument list
        :param prior_list: prior list
        :return: logL
    """
    
    logL = 0
    
    if not kwargs_list: 
            pass
    else:
        for i in range(len(prior_list)):
            mean_index,index,param,sigma = prior_list[i]

            model_val = kwargs_list[index][param]  #model parameter on which to place prior
            mean_val = kwargs_list[mean_index][param] #mean value around which gaussian is centered

            dist = (model_val - mean_val)**2 / sigma ** 2 / 2
            logL -= np.sum(dist)
#             print('prior: {} \n model value: {} \n mean value: {} \n sigma: {}'.format(param,model_val,mean_val,sigma))
            
    return logL
                
    
def join_lens_with_light_loose(kwargs_lens,kwargs_lens_light,prior_list):    
    """
    Gaussian Prior for joining parameter in lens mass to parameter in lens light     
        :param kwargs_lens (lens_light): keyword argument list of lens (lens_light) profiles
        :param prior_list: prior list
        :return: logL
        """
    
    logL = 0
    
    if not kwargs_lens: 
        pass
    elif not kwargs_lens_light:
        pass
    else:
        for i in range(len(prior_list)):
            light_index, lens_index, param, sigma = prior_list[i]
            
            model_val = kwargs_lens[lens_index][param] 
            mean_val = kwargs_lens_light[light_index][param]
            
            dist = (model_val - mean_val)**2 / sigma ** 2 / 2
            logL -= np.sum(dist)
            
#             print('prior: {}_lens \n lens_val: {} \n light value: {} \n sigma: {}'.format(param,model_val,mean_val,sigma))
            
    return logL
            
                
    
def custom_logL_addition(kwargs_lens=None, kwargs_source=None, kwargs_lens_light=None, kwargs_ps=None, kwargs_special=None,
             kwargs_extinction=None):
    '''
    custom_logL_addition function. Joins e1,e2 parameters between bands using gaussian priors. 
    Joins e1,e2 parameters of lens mass to lens light profile with gaussian priors. 
    Puts gaussian priors on q for source and lens light sersic profiles
    
    :kwargs_*: kwargs lists
    :return: logL
    '''              
    
    #make list of indices in kwargs_source corresponding to sersic profile
    if not kwargs_source:
        sersic_indices_source = []
    else:
        sersic_indices_source = [i for i,x in enumerate(kwargs_source) if 'R_sersic' in x] 

    #make list of indices in kwargs_lens_light corresponding to sersic profile
    if not kwargs_lens_light:
        sersic_indices_lens_light = []
    else:
        sersic_indices_lens_light = [i for i,x in enumerate(kwargs_lens_light) if 'R_sersic' in x]
    
    
    #prior list for source gaussian prior on q
    prior_list_source = []
    for i,x in enumerate(sersic_indices_source):
        prior_list_source.append([x,'q',0.8,0.1]) #[index,pram,mean,sigma]

    #prior list for joining source ellipticity between bands
    join_list_source = []
    for i in range(len(sersic_indices_source) - 1):
        #gaussian centered on PREVIOUS band:
        join_list_source.append([sersic_indices_source[i],sersic_indices_source[i+1],'e1',0.01]) #[mean_index,index,param,sigma]
        join_list_source.append([sersic_indices_source[i],sersic_indices_source[i+1],'e2',0.01]) 
        
        #gaussian centered on FIRST band:
    #     join_list_source.append([0,sersic_indices_source[i+1],'e1',0.01])
    #     join_list_source.append([0,sersic_indices_source[i+1],'e2',0.01])   
    
    #prior list for lens light gaussian prior on q
    prior_list_lens_light = []
    for i,x in enumerate(sersic_indices_lens_light):
        prior_list_lens_light.append([x,'q',0.8,0.1]) #[mean_index,index,param,sigma]

    #prior list for joining lens light ellipticity between bands
    join_list_lens_light = []
    for i in range(len(sersic_indices_lens_light) - 1):
        #gaussian centered on PREVIOUS band: #[mean_index,index,param,sigma]
        join_list_lens_light.append([sersic_indices_lens_light[i],sersic_indices_lens_light[i+1],'e1',0.01])
        join_list_lens_light.append([sersic_indices_lens_light[i],sersic_indices_lens_light[i+1],'e2',0.01]) 
        
        #gaussian centered on FIRST band:
    #     join_list_lens_light.append([0,sersic_indices_lens_light[i+1],'e1',0.01])
    #     join_list_lens_light.append([0,sersic_indices_lens_light[i+1],'e2',0.01])   
    
    
    #prior list for joining lens mass ellipticity with lens light ellipticity using gaussian prior
    if not kwargs_lens:
        join_list_lens_with_light = []
    else:
        join_list_lens_with_light = [[sersic_indices_lens_light[-1],0,'e1',0.01], #[light_index, lens_index, param, sigma]
                                     [sersic_indices_lens_light[-1],0,'e2',0.01]]
    
    logL = 0
    
#     print('Prior on q (lens_light)')
    logL += prior_phi_q_gaussian(kwargs_lens_light, prior_list_lens_light)
#     print('Prior on q (source)')
    logL += prior_phi_q_gaussian(kwargs_source, prior_list_source)
#     print('Loose join of lens with light e1 and e2')
    logL += join_lens_with_light_loose(kwargs_lens,kwargs_lens_light,join_list_lens_with_light)
#     print('Loose join of e1 and e2 between source bands')
    logL += join_param_between_bands(kwargs_source, join_list_source)
#     print('Loose join of e1 and e2 between lens_light bands')
    logL += join_param_between_bands(kwargs_lens_light, join_list_lens_light)
    
    return logL

    
def prepareFit(kwargs_data, kwargs_psf, lens_model_list, 
           source_model_list, lens_light_model_list, image_mask_list = None):
    
    ''' 
    Function for preparing fit settings in appropriate kwargs to pass into Lenstronomy.
        :kwargs_data: list of dicts; image data and info 
        :kwargs_psf:list of dicts; psf data and info
        :lens_model_list: list of strings; lens model profiles for a single band
        :source_model_list: list of strings; source model profiles for a single band
        :lens_light_model_list: list of strings; lens light model profiles for a single band
        :image_mask_list: List of masks. One for each band. Masks are 2D arrays of ints, with values 0 or 1
        
    Returns:
        :kwargs_likelihood: dictionary with info for likelihood computations (mask list and priors)
        :kwargs_model: dictionary for model lists, indices of profiles in model lists to be used for each band
        :kwargs_data_joint: dictionary containing multi_band_list and multi band type
        :multi_band_list: list with length = # bands. Each item (i) is another list with i'th kwargs_data, kwargs_psf, and 
                                             kwargs_numerics for that band.
        :kwargs_constraints: dictionary for constraints (e.g. joining parameters between profiles)
        
    '''
    
    kwargs_likelihood = {'source_marg': False, 
                         'image_likelihood_mask_list': image_mask_list,
                         'prior_lens_light': [],
#                          'prior_lens_light_lognormal': [],
                         'prior_source': [],
#                          'check_positive_flux': True,
                         'custom_logL_addition': custom_logL_addition,
                        }

    multi_source_model_list = [] 
    multi_lens_light_model_list = []
    
    #model lists with profiles repeated for number of bands
    for i in range(len(kwargs_data)):
        multi_source_model_list.extend(deepcopy(source_model_list))
        multi_lens_light_model_list.extend(deepcopy(lens_light_model_list))
    
    
    
    kwargs_model = {'lens_model_list': deepcopy(lens_model_list), 
                        'source_light_model_list': multi_source_model_list, 
                        'lens_light_model_list': multi_lens_light_model_list,
                       'index_lens_model_list': [[i for i in range(len(lens_model_list))] for x in kwargs_data],
                       'index_source_light_model_list': [[i+j*len(source_model_list) for i in range(len(source_model_list))] 
                                                         for j in range(len(kwargs_data))],
                       'index_lens_light_model_list': [[i+j*len(lens_light_model_list) for i in 
                                                        range(len(lens_light_model_list))] for j in range(len(kwargs_data))]}

    #indices in multi_source_model_list corresponding to sersic profile:
    SERSIC_indices_source = [i for i,x in enumerate(kwargs_model['source_light_model_list']) if x == 'SERSIC_ELLIPSE']
    
    #indices in multi_source_model_list corresponding to shapelets profile:
    SHAPELETS_indices_source = [i for i,x in enumerate(kwargs_model['source_light_model_list']) if x == 'SHAPELETS']
    
    #list of indices of source profiles
    indices_source = [i for i in range(len(kwargs_model['source_light_model_list']))]
    
    #indices in multi_lens_light_model_list corresponding to sersic profile:
    SERSIC_indices_lens_light = [i for i,x in enumerate(kwargs_model['lens_light_model_list']) if x == 'SERSIC_ELLIPSE']

    kwargs_constraints = {'joint_source_with_source': [], 
                          'joint_lens_light_with_lens_light': [],
                         'joint_lens_with_light': []}

    print('Check 1')
    #Join lens_light centroids between bands
    for i in range(len(SERSIC_indices_lens_light) - 1):
        kwargs_constraints['joint_lens_light_with_lens_light'].append([SERSIC_indices_lens_light[0],
                                                                       SERSIC_indices_lens_light[i+1],
#                                                                        ['center_x','center_y','e1','e2']
                                                                       ['center_x','center_y']
                                                                      ]) 
        

    print('Check 2')
    #Join source centroids between bands
    for i in range(len(indices_source) - 1):
        kwargs_constraints['joint_source_with_source'].append([indices_source[0],indices_source[i+1],['center_x','center_y']])

        
    #Join source 
#     for i in range(len(SERSIC_indices_source) - 1):
#         kwargs_constraints['joint_source_with_source'].append([SERSIC_indices_source[i],SERSIC_indices_source[i+1],['e1','e2']])

    for i,j in enumerate(SERSIC_indices_source):
        kwargs_likelihood['prior_source'].append([j,'R_sersic', 1.0,2.0])
        kwargs_likelihood['prior_source'].append([j,'n_sersic', 3.0,1.0])
# #         kwargs_likelihood['prior_source'].append([i,'e1', 0.,0.15])
# #         kwargs_likelihood['prior_source'].append([i,'e2', 0.,0.15])
    
    for i,j in enumerate(SHAPELETS_indices_source):
        kwargs_likelihood['prior_source'].append([j,'beta', 0.01,0.05])
    
    for i in range(len(multi_lens_light_model_list)):
        if len(lens_model_list) != 0:
            kwargs_constraints['joint_lens_with_light'].append([i,0,['center_x','center_y']])
#             kwargs_constraints['joint_lens_with_light'].append([i,0,['center_x','center_y','e1','e2']])
                
        kwargs_likelihood['prior_lens_light'].append([i,'R_sersic', 1.0,2.0])
        kwargs_likelihood['prior_lens_light'].append([i,'n_sersic', 3.0,1.0])
# #         kwargs_likelihood['prior_lens_light'].append([i,'e1', 0.,0.15])
# #         kwargs_likelihood['prior_lens_light'].append([i,'e2', 0.,0.15])
    
    multi_band_list = []
    for i in range(len(kwargs_data)):

        kwargs_numerics = {'supersampling_factor': 2, # each pixel gets super-sampled (in each axis direction) 
                      'supersampling_convolution': False}

        if kwargs_psf[i]['point_source_supersampling_factor'] != 1:
            kwargs_numerics['supersampling_convolution'] = True
            kwargs_numerics['supersampling_factor'] = kwargs_psf[i]['point_source_supersampling_factor']

        multi_band_list.append([kwargs_data[i], kwargs_psf[i], kwargs_numerics]) # if you have multiple  bands to be modeled                                                                        simultaneously,you can append them to the mutli_band_list

    kwargs_data_joint = {'multi_band_list': multi_band_list, 
                     'multi_band_type': 'multi-linear'  # 'multi-linear': every imaging band has independent solutions of the         surface brightness, 'joint-linear': there is one joint solution of the linear coefficients demanded across the bands.
                    }   

    return kwargs_likelihood, kwargs_model, kwargs_data_joint, multi_band_list, kwargs_constraints


def runFit(fitting_kwargs_list, kwargs_params, kwargs_likelihood, kwargs_model, kwargs_data_joint, kwargs_constraints = {}):
    
    ''' 
    Function for running a fit.
        :fitting_kwargs_list: list. Type of fit (PSO or MCMC), and fitting parameters
        :kwargs_params: Dictionary. Parameters (init, fixed, sigma, upper/lower bounds) for lens, lens light, and source light 
                        profiles
        :kwargs_likelihood: Dictionary with info for likelihood computations (mask list and priors)
        :kwargs_model: dictionary for model lists, indices of profiles in model lists to be used for each band
        :kwargs_data_joint: dictionary containing multi_band_list and multi band type
        :kwargs_constraints: dictionary for constraints (e.g. joining parameters between profiles)
        
    Returns:
        :chain_list: fitting results
        :kwargs_result: optimized model parameter values
    '''
    
    #set up fitting sequence
    fitting_seq = FittingSequence(kwargs_data_joint, kwargs_model, kwargs_constraints, kwargs_likelihood, kwargs_params)

    #print fit settings before starting fit
    fitting_seq.param_class.print_setting()
    
    #run fit
    chain_list = fitting_seq.fit_sequence(fitting_kwargs_list)
    kwargs_result = fitting_seq.best_fit()
    
    return chain_list, kwargs_result



def find_components_old(image,deltaPix,lens_rad_arcsec = 5.0,lens_rad_ratio = None, gal_rad_ratio = 0.1,min_size_arcsec=0.3,thresh=0.4, show_locations=False):
    """
    Detect multiple components in a pixelated model of the source and return their coordinates.
    min_size_arcsec: minimum size of features to be considered as individual components
    thresh: threshold all values below `tresh` times the max of the image after LoG filtering
    """

    # convert minimum component size in pixel units
    min_size = int(min_size_arcsec / deltaPix)
    
    #Convert lens radius and central galaxy radius to pixels
    if lens_rad_ratio == None:
        lens_rad = int(lens_rad_arcsec / deltaPix)
    else: lens_rad = int(len(image) * lens_rad_ratio)
    gal_rad = int(len(image) * gal_rad_ratio)
    
    # downscale source image to data resolution (for speed + easier for converting to data units)
    #down = image_util.re_size(image, factor=supersampling_factor_source)
    
    # apply laplacian of gaussian (LoG) filter to enhance maxima
    filtered = - gaussian_laplace(deepcopy(image), sigma = min_size, mode='constant', cval=0.)
    
#     print(filtered.min(),filtered.max(),filtered.min() + thresh * np.abs(filtered.min()))
    
    
    # assume all value below max*threshold can not be maxima, so put all to zero
#     filtered[filtered < thresh*filtered.max()] = 0.
    
#     assume all value below min*threshold can not be maxima, so put all to zero
    filtered[filtered < filtered.min() + thresh * np.abs(filtered.min())] = 0.
    
    if show_locations:
        plt.figure(figsize = (8,8))
        plt.subplot(1,2,1)
        plt.imshow(image, origin='lower', norm=SymLogNorm(5))
        plt.title('Image')

        plt.subplot(1,2,2)
        plt.imshow(filtered, origin='lower', norm=SymLogNorm(5))
        plt.title('Filtered Image')
        plt.show()
    
    # find coordinates of local maxima
    #print(int(0.5 * min_size))
    max_idx_2d_small = peak_local_max(filtered, min_distance=0)
    max_idx_2d_large = peak_local_max(filtered, min_distance=1)
    
    x_list_small, y_list_small = max_idx_2d_small[:, 1], max_idx_2d_small[:, 0]
    x_list_large, y_list_large = max_idx_2d_large[:, 1], max_idx_2d_large[:, 0]
    
    im_center_x, im_center_y = len(image) / 2., len(image) / 2.
    
    R = np.sqrt((x_list_large - im_center_x)**2 + (y_list_large - im_center_y)**2)
    new_center_x, new_center_y = x_list_large[R < gal_rad], y_list_large[R < gal_rad]
    
    if (len(new_center_x) > 1) and (len(x_list_large[R == R.min()]) ==1 ): 
        new_center_x, new_center_y = x_list_large[R == R.min()], y_list_large[R == R.min()]
    elif (len(new_center_x) > 1) and (len(x_list_large[R == R.min()]) > 1 ): 
        new_center_x, new_center_y = im_center_x, im_center_y
    elif len(new_center_x) == 0: 
        new_center_x, new_center_y = im_center_x, im_center_y
        
        
    R_small = np.sqrt((x_list_small - new_center_x)**2 + (y_list_small - new_center_y)**2)
    R_large = np.sqrt((x_list_large - new_center_x)**2 + (y_list_large - new_center_y)**2)
    
    x_sats, y_sats = x_list_small[R_small > lens_rad], y_list_small[R_small > lens_rad]
    
    # show maxima on image for debug
    if show_locations:
        fig = plt.figure(figsize=(4, 4))
        #plt.imshow(image, origin='lower', cmap=cmap_flux, norm=LogNorm(1e-2))
        plt.imshow(image, origin='lower', norm=SymLogNorm(5))
        
        for i in range(len(x_sats)):
            plt.scatter([x_sats[i]], [y_sats[i]], c='red', s=60, marker='+')
#             plt.annotate(i+1, (x_list[i], y_list[i]), color='black')
        
#         for i in range(len(x_mask)):
#             plt.scatter([x_mask[i]], [y_mask[i]], c='red', s=100, marker='*')
#             plt.annotate(i+1, (x_mask[i], y_mask[i]), color='red')
        plt.scatter(new_center_x, new_center_y,c='red', s=100, marker='*')
        
        draw_lens_circle = Circle((new_center_x, new_center_y),lens_rad ,fill=False)
        draw_gal_circle = Circle((new_center_x, new_center_y),gal_rad, fill = False)
        plt.gcf().gca().add_artist(draw_lens_circle)
        plt.gcf().gca().add_artist(draw_gal_circle)
        plt.title('Detected Components')
        plt.text(1, 1, "detected components", color='red')
        fig.axes[0].get_xaxis().set_visible(True); fig.axes[0].get_yaxis().set_visible(True)
        plt.show()
    return (x_sats, y_sats), (new_center_x, new_center_y)




def mask_for_sat_old(image,deltaPix,lens_rad_arcsec = 5.0,lens_rad_ratio = 0.4, show_plot = False):
    
    gal_rad_ratio = 0.1
    min_size_arcsec= 0.7
    thresh = 1.4
    
    
    
    numPix = len(image)
    (x_sats, y_sats), (new_center_x, new_center_y) = find_components(image, deltaPix,lens_rad_arcsec = lens_rad_arcsec, 
                                                                     gal_rad_ratio = gal_rad_ratio, 
                                                                     min_size_arcsec= min_size_arcsec,
                                                                     lens_rad_ratio = lens_rad_ratio,
                                                                     thresh=thresh, show_locations=show_plot)
    satellites = [] 
    mask_final = np.ones([numPix,numPix])
    for i in range(len(x_sats)):
        satellites.append(np.zeros([numPix,numPix])) 

        for j in range(len(image)):
#             satellites[i][j] = mask_sphere(j,np.linspace(0,numPix - 1,numPix),y_sats[i],x_sats[i],2)
            satellites[i][j] = mask_center_2d(x_sats[i], y_sats[i], 2, np.linspace(0,numPix - 1,numPix), j)

#         mask_final[satellites[i] ==1] = 0
        mask_final[satellites[i] ==0] = 0

    #mask_list.append(mask_final)
    #mask_final = np.ones([numPix,numPix])
    #mask_final[mask_both == 1] = 0.
    
    return mask_final
 

def mask_for_lens_gal(image,deltaPix, gal_rad_ratio = 0.1, show_plot = False):
    
    lens_rad_arcsec = 3.0
    min_size_arcsec= 0.7
    thresh = 1.4
    lens_rad_ratio = 0.4
    
    gal_rad = int(len(image) * gal_rad_ratio)
    
    numPix = len(image)
    (x_sats, y_sats), (new_center_x, new_center_y) = find_components(image, deltaPix,lens_rad_arcsec = lens_rad_arcsec, 
                                                                     gal_rad_ratio = gal_rad_ratio, 
                                                                     min_size_arcsec= min_size_arcsec,
                                                                     lens_rad_ratio = lens_rad_ratio,
                                                                     thresh=thresh, show_locations=show_plot)
#         print(new_center_x, new_center_y)
    mask = np.zeros([numPix,numPix])
    for i in range(len(image)):
#         mask[i] =  mask_sphere(i,np.linspace(0,numPix - 1,numPix),new_center_y,new_center_x,gal_rad)
        lens_gal[i] =  mask_center_2d(new_center_x,new_center_y, gal_rad, np.linspace(0,numPix - 1,numPix), i)
        mask[lens_gal[i] == 0] = 1
    return mask



def find_lens_gal(image,deltaPix,show_plot=False,title=None):
    
    corners = np.zeros([4,5,5])
    corners[0] = image[0:5,0:5]
    corners[1] = image[-5:,0:5]
    corners[2] = image[0:5,-5:]
    corners[3] = image[-5:,-5:]
    means, medians, stds = [],[],[]
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
        medians.append(med)
        stds.append(s)
        
    mean_bg = np.mean(means)
    median_bg = np.mean(medians)
    std_bg = np.mean(stds)
#     print('means: {}, median: {}, std: {}'.format(means,median_bg,std_bg))
    
    thresh = std_bg / 4
    
    min_size_arcsec = 0.7
    min_size = int(min_size_arcsec / deltaPix)
    
    LoG = - gaussian_laplace(deepcopy(image), sigma = min_size, mode='constant', cval=0.)
    
    filtered = deepcopy(LoG)
    
    corners = np.zeros([4,5,5])
    corners[0] = LoG[0:5,0:5]
    corners[1] = LoG[-5:,0:5]
    corners[2] = LoG[0:5,-5:]
    corners[3] = LoG[-5:,-5:]
    means = []
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
    
    means = np.array(means)
    means_std = np.std(means)
    means_good = means[(means >= means.mean() - 1.0 * means_std) & (means <= means.mean() + 1.0 * means_std)]
    mean_bg = np.mean(means_good)
    
    filtered[filtered < mean_bg + thresh] = 0.
    
    max_idx_2d_large = peak_local_max(filtered, min_distance=1)
    
    x_list_large, y_list_large = max_idx_2d_large[:, 1], max_idx_2d_large[:, 0]
    
    gal_rad = 5.
    
    im_center_x, im_center_y = len(image) / 2., len(image) / 2.
    R = np.sqrt((x_list_large - im_center_x)**2 + (y_list_large - im_center_y)**2)
    
    
    new_center_x, new_center_y = deepcopy(x_list_large[R < gal_rad]), deepcopy(y_list_large[R < gal_rad])
    if (len(new_center_x) == 1):
        print('c1:')
        print(new_center_x[0], new_center_y[0])
    elif (len(new_center_x) > 1): 
        if (len(x_list_large[R == R.min()]) ==1 ): 
            new_center_x, new_center_y = x_list_large[R == R.min()], y_list_large[R == R.min()]
            print('c2:')
            print(new_center_x[0], new_center_y[0])
        elif (len(x_list_large[R == R.min()]) > 1):
            new_center_x, new_center_y = x_list_large[R == R.min()][0], y_list_large[R == R.min()][0]
            print('c3:')
            print(new_center_x[0], new_center_y[0])
    elif (len(new_center_x) == 0):
        gal_rad = 10
        new_center_x, new_center_y = x_list_large[R < gal_rad], y_list_large[R < gal_rad]
        if (len(new_center_x) > 1): 
            if (len(x_list_large[R == R.min()]) ==1 ): 
                new_center_x, new_center_y = x_list_large[R == R.min()], y_list_large[R == R.min()]
                print('c4:')
                print(new_center_x[0], new_center_y[0])
            elif (len(x_list_large[R == R.min()]) > 1):
                new_center_x, new_center_y = x_list_large[R == R.min()][0], y_list_large[R == R.min()][0]
                print('c5:')
                print(new_center_x[0], new_center_y[0])
        elif (len(new_center_x) == 0):
            new_center_x, new_center_y = im_center_x, im_center_y
            print('c6:')
            print(new_center_x[0], new_center_y[0])
            
    if show_plot:
        plt.figure(figsize=(8,6))
        plt.imshow(image,origin='lower',norm=SymLogNorm(5))
        circle = Circle((new_center_x, new_center_y),gal_rad, fill = False)
        plt.gcf().gca().add_artist(circle)
        plt.scatter(new_center_x, new_center_y,c='red', s=100, marker='*')
        plt.text(1, 1, "loc = ({},{})".format(new_center_x[0], new_center_y[0]),fontsize=30,fontweight='bold',color='red')
        plt.axis('off')   
        plt.title(title)
        
    
    return new_center_x[0], new_center_y[0]
    
    


def find_components(image,deltaPix,lens_rad_arcsec = 6.0,lens_rad_ratio = None,
                    center_x = None,center_y = None, gal_rad_ratio = 0.1,
                    min_size_arcsec=0.7,thresh=0.5, many_sources = True,
                    show_locations=False, title = None):
    """
    Detect multiple components in a pixelated model of the source and return their coordinates.
    min_size_arcsec: minimum size of features to be considered as individual components
    thresh: threshold all values below `tresh` times the max of the image after LoG filtering
    """

    # convert minimum component size in pixel units
    min_size = int(min_size_arcsec / deltaPix)
    
    #Convert lens radius and central galaxy radius to pixels
    if lens_rad_ratio == None:
        lens_rad = int(lens_rad_arcsec / deltaPix)
    else: lens_rad = int(len(image) * lens_rad_ratio)
    gal_rad = int(len(image) * gal_rad_ratio)
    
    
#     im2[im2 < im2.min() + 10.*thresh] = 0.
    
    # downscale source image to data resolution (for speed + easier for converting to data units)
    #down = image_util.re_size(image, factor=supersampling_factor_source)
    
    # apply laplacian of gaussian (LoG) filter to enhance maxima
    LoG = - gaussian_laplace(deepcopy(image), sigma = min_size, mode='constant', cval=0.) 
    
#     LoG = - gaussian_laplace(deepcopy(im2), sigma = 2., mode='constant', cval=0.)
    
    filtered = deepcopy(LoG)
    
#     print(LoG.min(),LoG.max(),np.abs(LoG.min()) + thresh )
    
#     print(type(filtered))
    
    corners = np.zeros([4,5,5])
    corners[0] = LoG[0:5,0:5]
    corners[1] = LoG[-5:,0:5]
    corners[2] = LoG[0:5,-5:]
    corners[3] = LoG[-5:,-5:]
    means = []
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
    
    means = np.array(means)
    means_std = np.std(means)
    means_good = means[(means >= means.mean() - 1.0 * means_std) & (means <= means.mean() + 1.0 * means_std)]
    mean_bg = np.mean(means_good)
#     print('LoG means: {}, Log means std: {}, Log means good: {}, LoG avg mean: {}'.format(means,means_std,means_good,mean_bg))
#     print('min: {}, max: {}, cut: {}'.format(LoG.min(),LoG.max(),mean_bg + thresh))
#     print(LoG.min(),LoG.max(),filtered.min() + thresh)
    
    
    # assume all value below max*threshold can not be maxima, so put all to zero
#     filtered[filtered < thresh*filtered.max()] = 0.
    
#     assume all value below min*threshold can not be maxima, so put all to zero
#     filtered[filtered < filtered.min() + thresh * np.abs(filtered.min())] = 0.
    filtered[filtered < mean_bg + thresh] = 0.
    
    # find coordinates of local maxima
    #print(int(0.5 * min_size))
    max_idx_2d_small = peak_local_max(filtered, min_distance=0)
    max_idx_2d_large = peak_local_max(filtered, min_distance=1)
    
    x_list_small, y_list_small = max_idx_2d_small[:, 1], max_idx_2d_small[:, 0]
    x_list_large, y_list_large = max_idx_2d_large[:, 1], max_idx_2d_large[:, 0]
    
    im_center_x, im_center_y = len(image) / 2., len(image) / 2.
    
    if (center_x == None) & (center_y == None):
        R = np.sqrt((x_list_large - im_center_x)**2 + (y_list_large - im_center_y)**2)
        new_center_x, new_center_y = x_list_large[R < gal_rad], y_list_large[R < gal_rad]

        if (len(new_center_x) > 1) and (len(x_list_large[R == R.min()]) ==1 ): 
            new_center_x, new_center_y = x_list_large[R == R.min()], y_list_large[R == R.min()]
        elif (len(new_center_x) > 1) and (len(x_list_large[R == R.min()]) > 1 ): 
            new_center_x, new_center_y = im_center_x, im_center_y
        elif len(new_center_x) == 0: 
            new_center_x, new_center_y = im_center_x, im_center_y
    else:
        new_center_x, new_center_y = center_x,center_y
           
    print(new_center_x,new_center_y)     
    R_small = np.sqrt((x_list_small - new_center_x)**2 + (y_list_small - new_center_y)**2)
    R_large = np.sqrt((x_list_large - new_center_x)**2 + (y_list_large - new_center_y)**2)
    
    x_sats, y_sats = x_list_small[R_small > lens_rad], y_list_small[R_small > lens_rad]
    
    if many_sources:
        x_lens, y_lens = deepcopy(x_list_small), deepcopy(y_list_small)
    else:
        x_lens, y_lens = deepcopy(x_list_large), deepcopy(y_list_large)
    
#     x_lens, y_lens = x_list_small[R_small <= lens_rad], y_list_small[R_small <= lens_rad]
    
    if (len(x_lens) == 0) & (len(y_lens) == 0):
        x_lens = [0,15]
        y_lens = [0,15]
    
    sources = QTable([x_lens, y_lens],names={'x_local_peak','y_local_peak'})
    
    # show maxima on image for debug
    if show_locations:
#         fig = plt.figure(figsize=(4, 4))
        #plt.imshow(image, origin='lower', cmap=cmap_flux, norm=LogNorm(1e-2))
    
        f, axes = plt.subplots(1, 5, figsize=(20,5), sharex=False, sharey=False)
#         plt.figure(figsize = (8,8))
#         plt.subplot(1,2,1)
        axes[0].imshow(image, origin='lower', norm=SymLogNorm(5))
        axes[0].set_title('Image')
        axes[0].set_axis_off()
        
        axes[1].imshow(LoG, origin='lower', norm=SymLogNorm(5))
        axes[1].set_title('LoG Filtered Image')
        axes[1].set_axis_off()

#         plt.subplot(1,2,2)
        axes[2].imshow(filtered, origin='lower', norm=SymLogNorm(5))
        axes[2].set_title('Final Filtered Image')
        axes[2].set_axis_off()
        
        axes[3].imshow(image, origin='lower', norm=SymLogNorm(5))
        for i in range(len(x_lens)):
            axes[3].scatter([x_lens[i]], [y_lens[i]], c='red', s=60, marker='+')
        axes[3].set_title('lens detections')
        axes[3].set_axis_off()
        
        axes[4].imshow(image, origin='lower', norm=SymLogNorm(5))
        
        for i in range(len(x_sats)):
            axes[4].scatter([x_sats[i]], [y_sats[i]], c='red', s=60, marker='+')
#             plt.annotate(i+1, (x_list[i], y_list[i]), color='black')
        
#         for i in range(len(x_mask)):
#             plt.scatter([x_mask[i]], [y_mask[i]], c='red', s=100, marker='*')
#             plt.annotate(i+1, (x_mask[i], y_mask[i]), color='red')
        axes[4].scatter(new_center_x, new_center_y,c='red', s=100, marker='*')
        
        draw_lens_circle = Circle((new_center_x, new_center_y),lens_rad ,fill=False)
        draw_gal_circle = Circle((new_center_x, new_center_y),gal_rad, fill = False)
#         plt.gcf().gca().add_artist(draw_lens_circle)
#         plt.gcf().gca().add_artist(draw_gal_circle)
        axes[4].add_patch(draw_lens_circle)
        axes[4].add_patch(draw_gal_circle)
        axes[4].set_title('Detected Components: \n Center = ({:.1f},{:.1f}) \n r = {:.3f}'.format(new_center_x, new_center_y,lens_rad_arcsec))
        axes[4].text(1, 1, "detected components", color='red')
        axes[4].set_axis_off()
        
        if title != None:
            f.suptitle(title, fontsize = 15)
#         plt.show()
    return (x_sats, y_sats), (new_center_x, new_center_y), sources


def estimate_radius_stat(image,deltaPix,center_x = None,center_y = None,show_plot=False, name = None):
    
    corners = np.zeros([4,5,5])
    corners[0] = image[0:5,0:5]
    corners[1] = image[-5:,0:5]
    corners[2] = image[0:5,-5:]
    corners[3] = image[-5:,-5:]
    means, medians, stds = [],[],[]
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
        medians.append(med)
        stds.append(s)
        
    mean_bg = np.mean(means)
    median_bg = np.mean(medians)
    std_bg = np.mean(stds)
#     print('means: {}, median: {}, std: {}'.format(means,median_bg,std_bg))
    
    thresh = std_bg / 4 
   
    numPix = len(image)
    
    #initial guesses of sizes
    lens_init_ratio = 0.5
    lens_init_arcsec = lens_init_ratio * numPix * deltaPix
    gal_init_ratio = 0.1 
    min_size_arcsec= 0.7
    
    _, (new_center_x, new_center_y), sources = find_components(image, deltaPix,lens_rad_arcsec = lens_init_arcsec, 
                                                               gal_rad_ratio = gal_init_ratio,
                                                               center_x = center_x,center_y = center_y,
                                                               min_size_arcsec= min_size_arcsec,
                                                               lens_rad_ratio = lens_init_ratio,
                                                               thresh=thresh,many_sources = True, 
                                                               show_locations=False,title = None)
    
    
    ## Estimate Einstein Radius from sources
    sources['difx'] = abs(sources['x_local_peak']-new_center_x)
    sources['dify'] = abs(sources['y_local_peak']-new_center_y)
    
    s = sources.to_pandas()
    s['md'] = s[['difx','dify']].mean(axis=1)
    s = s.sort_values(by=['md'])
    s = s.reset_index()	
    
#     print(s)
    if (len(s)==1):
#         print('d3')
        dst=distance.euclidean((25,25),(s['x_local_peak'].values[0],s['y_local_peak'].values[0]))
    elif (len(s)==2):
        if (s['md'][1]>12):
#             print('d4')
            dst=distance.euclidean((25,25),(s['x_local_peak'].values[0],s['y_local_peak'].values[0]))
        else:
#             print('d5')
            dst=distance.euclidean((25,25),(s['x_local_peak'].values[1],s['y_local_peak'].values[1]))
    elif (len(s) >= 3):
#         s_end = s[int(len(s) * 2./3.)-1:]
        s_end = s[s['md'] < 16.5]
#         print(s_end)
        
#         print(s_end)
        distances = []
        for l in range(len(s_end)):
            distances.append(distance.euclidean((25,25),(s_end['x_local_peak'].values[l],s_end['y_local_peak'].values[l])))
#         distances = np.array(distances)
        mean_dist = np.mean(distances)
        std_dist = np.std(distances)
        
        if (std_dist <= 1.0):
            if mean_dist < 3.0:
                dst = 3. * mean_dist + 10.* std_dist
            else:
                dst = mean_dist + 10.* std_dist
        elif (std_dist <= 3.0) & (std_dist > 1.0):
            dst = mean_dist + 6.* std_dist
        elif (std_dist <= 4.0) & (std_dist > 3.0):
            dst = mean_dist + 3.* std_dist
        elif (std_dist > 4.0) & (std_dist <= 5.0):
            dst = mean_dist + 2.* std_dist
        elif (std_dist > 5.0) & (std_dist <= 6.0):
            dst = mean_dist + 1.5* std_dist
        else:
            dst = mean_dist + 1.0* std_dist 
#         dst = distances[-1] 
                
    dst_arcsec = dst * deltaPix
    
    gal_rad_ratio = 0.1
    min_size_arcsec= 0.7
    
    if show_plot:
        (x_sats, y_sats), (new_center_x, new_center_y), sources = find_components(image, deltaPix,
                                                                              lens_rad_arcsec = dst_arcsec, 
                                                                              gal_rad_ratio = gal_rad_ratio, 
                                                                              min_size_arcsec= min_size_arcsec,
                                                                              lens_rad_ratio = None,
                                                                              center_x = center_x,
                                                                              center_y = center_y,
                                                                              thresh=thresh, 
                                                                              show_locations=show_plot,many_sources = True,
                                                                              title = '{} (mean: {:.2f}, std: {:.2f}, radius: {:.2f})'.format(name,mean_dist,std_dist,dst))
    
    return dst, dst_arcsec,distances

def estimate_radius(image,deltaPix, center_x = None,center_y = None,show_plot=False, name = None):
    
    corners = np.zeros([4,5,5])
    corners[0] = image[0:5,0:5]
    corners[1] = image[-5:,0:5]
    corners[2] = image[0:5,-5:]
    corners[3] = image[-5:,-5:]
    means, medians, stds = [],[],[]
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
        medians.append(med)
        stds.append(s)
        
    mean_bg = np.mean(means)
    median_bg = np.mean(medians)
    std_bg = np.mean(stds)
#     print('means: {}, median: {}, std: {}'.format(means,median_bg,std_bg))
    
    thresh = std_bg / 4 
   
    numPix = len(image)
    
    #initial guesses of sizes
    lens_init_ratio = 0.5
    lens_init_arcsec = lens_init_ratio * numPix * deltaPix
    gal_init_ratio = 0.1 
    min_size_arcsec= 0.7
    
    _, (new_center_x, new_center_y), sources = find_components(image, deltaPix,lens_rad_arcsec = lens_init_arcsec, 
                                                               gal_rad_ratio = gal_init_ratio,
                                                               center_x = center_x,center_y = center_y,
                                                               min_size_arcsec= min_size_arcsec,
                                                               lens_rad_ratio = lens_init_ratio,
                                                               thresh=thresh,many_sources = False, 
                                                               show_locations=False,title = None)
    
    
    ## Estimate Einstein Radius from sources
    sources['difx'] = abs(sources['x_local_peak']-new_center_x)
    sources['dify'] = abs(sources['y_local_peak']-new_center_y)
    
    s = sources.to_pandas()
    s['md'] = s[['difx','dify']].mean(axis=1)
    s = s.sort_values(by=['md'])
    s = s.reset_index()	
    
    print('number of sources: {}'.format(len(s)))
    
#     if (len(s)>1) and (s['md'][0]<3):
    if (len(s)>1):
        print('d1',s['x_local_peak'].values[1],s['y_local_peak'].values[1])
        dst=distance.euclidean((25,25),(s['x_local_peak'].values[1],s['y_local_peak'].values[1]))
        print(dst)
        if (s['md'][1]>12):
            print('d2')
            dst=distance.euclidean((25,25),(s['x_local_peak'].values[0],s['y_local_peak'].values[0])) 
            print(dst)
        dst += 8
        dst_arcsec = dst * deltaPix
        
        if (dst - 8.) <=3.0:
            print('d3')
            dst, dst_arcsec,distances = estimate_radius_stat(image,deltaPix,show_plot=False, name = None)
            print(dst)
    else:
        print('d4')
        dst, dst_arcsec,distances = estimate_radius_stat(image,deltaPix,show_plot=False, name = None)
        print(dst)

                
    
    
    gal_rad_ratio = 0.1
    min_size_arcsec= 0.7
    
    if show_plot:
        (x_sats, y_sats), (new_center_x, new_center_y), sources = find_components(image, deltaPix,
                                                                              lens_rad_arcsec = dst_arcsec, 
                                                                              gal_rad_ratio = gal_rad_ratio, 
                                                                              min_size_arcsec= min_size_arcsec,
                                                                              center_x = center_x,center_y = center_y,
                                                                              lens_rad_ratio = None,
                                                                              thresh=thresh, many_sources = True,
                                                                              show_locations=show_plot,
                                                                              title = '{} (r_pixel: {:.2f}, r_arcsec: {:.2f})'.format(name,dst,dst_arcsec))
    
    return dst, dst_arcsec


def mask_for_sat(image,deltaPix,lens_rad_arcsec = 5.0,lens_rad_ratio = 0.5, cov_rad = 2,center_x = None,center_y = None,show_plot = False,name = None):
    
    gal_rad_ratio = 0.1
    min_size_arcsec= 0.7
#     thresh = 1.2
    
    
    corners = np.zeros([4,5,5])
    corners[0] = image[0:5,0:5]
    corners[1] = image[-5:,0:5]
    corners[2] = image[0:5,-5:]
    corners[3] = image[-5:,-5:]
    means, medians, stds = [],[],[]
    for c in corners:
        mn,med,s = sigma_clipped_stats(c,sigma=3.0)
        means.append(mn)
        medians.append(med)
        stds.append(s)
        
    mean_bg = np.mean(means)
    median_bg = np.mean(medians)
    std_bg = np.mean(stds)
#     print('means: {}, median: {}, std: {}'.format(means,median_bg,std_bg))
    
    thresh = std_bg / 4 
#     thresh = 1.4 + std_bg /10.

      
    
    (x_sats, y_sats), (new_center_x, new_center_y), sources = find_components(image, deltaPix,
                                                                              lens_rad_arcsec = lens_rad_arcsec, 
                                                                              gal_rad_ratio = gal_rad_ratio,
                                                                              center_x = center_x,center_y = center_y,
                                                                              min_size_arcsec= min_size_arcsec,
                                                                              lens_rad_ratio = lens_rad_ratio,
                                                                              thresh=thresh, many_sources = True,
                                                                              show_locations=show_plot,
                                                                              title = name)
    numPix = len(image)
    satellites = [] 
    mask_final = np.ones([numPix,numPix])
    for i in range(len(x_sats)):
        satellites.append(np.zeros([numPix,numPix])) 

        for j in range(len(image)):
#             satellites[i][j] = mask_sphere(j,np.linspace(0,numPix - 1,numPix),y_sats[i],x_sats[i],2)
            satellites[i][j] = mask_center_2d(x_sats[i], y_sats[i], cov_rad, np.linspace(0,numPix - 1,numPix), j)

#         mask_final[satellites[i] ==1] = 0
        mask_final[satellites[i] ==0] = 0
      
    
    return mask_final




def df_2_kwargs_results(df,band_list,ignore_1st_line = False,includeShear = True):
    """
    
    Function that returns list of kwargs_results dictionaries from a pandas dataframe in the correct format to be passed 
    as kwargs_params argument in lenstronomy's modelPlot class. Intended for creating plots of results from dataframe of imported 
    csv file of modeling results (i.e. full_results.csv)
    :df: pandas dataframe of created from imported full_results.csv (or at least must have same column names as full_results.csv)
    :band_list: list of bands (strings) of image data (e.g. ['g','r','i'])
    :ignore_1st_line: bool, if the first line (index 0) in df is parameter names then set this to True
    :includeShear: bool, if shear is not included in the lens model list (e.g. model results from simulated images w/o shear), 
    then set to False
    
    Returns :kwargs_result: list of dictionaries, each of which contains all modeling results for that image
    """
    
    import pandas as pd
    
    kwargs_result = []
    
    for i in range(len(df)): 
        
        if (i == 0) and (ignore_1st_line):
            continue
            
        sie_data = []
        for sie in df.loc[i,'SIE_lens.theta_E':'SIE_lens.center_y']:
            sie_data.append(float(sie))

        sie_dict = {'theta_E': sie_data[0],
                   'e1': sie_data[1],
                   'e2': sie_data[2],
                   'center_x': sie_data[3],
                   'center_y': sie_data[4]}

        lens_dicts = [sie_dict]
        if includeShear == True:
            shear_data = []
            for sh in df.loc[i,'SHEAR_lens.gamma1':'SHEAR_lens.dec_0']:
                shear_data.append(float(sh))

            shear_dict = {'gamma1': shear_data[0],
                         'gamma2': shear_data[1],
                         'ra_0': shear_data[2],
                         'dec_0': shear_data[3]}

            lens_dicts.append(shear_dict)

        source_dicts = []
        lens_light_dicts = []
        for j,b in enumerate(band_list):
            sersic_data_source = []
            for s in df.loc[i,'{} Band: SERSIC_ELLIPSE_source.amp'.format(b):'{} Band: SERSIC_ELLIPSE_source.center_y'.format(b)]:
                sersic_data_source.append(float(s))
            sersic_dict_source = {'amp': sersic_data_source[0],
                                      'R_sersic': sersic_data_source[1],
                                      'n_sersic': sersic_data_source[2],
                                      'e1': sersic_data_source[3],
                                      'e2': sersic_data_source[4],
                                      'center_x': sersic_data_source[5],
                                      'center_y': sersic_data_source[6]}

            source_dicts.append(sersic_dict_source)

            sersic_data_lens_light = []
            for s in df.loc[i,'{} Band: SERSIC_ELLIPSE_lens_light.amp'.format(b):'{} Band: SERSIC_ELLIPSE_lens_light.center_y'.format(b)]:
                sersic_data_lens_light.append(float(s))
            sersic_dict_lens_light = {'amp': sersic_data_lens_light[0],
                                      'R_sersic': sersic_data_lens_light[1],
                                      'n_sersic': sersic_data_lens_light[2],
                                      'e1': sersic_data_lens_light[3],
                                      'e2': sersic_data_lens_light[4],
                                      'center_x': sersic_data_lens_light[5],
                                      'center_y': sersic_data_lens_light[6]}

            lens_light_dicts.append(sersic_dict_lens_light)

        kwargs = {'kwargs_lens': [], 'kwargs_source': [], 'kwargs_lens_light': [],
                        'kwargs_ps': [], 'kwargs_special': {}, 'kwargs_extinction': []}
        kwargs['kwargs_lens'] = deepcopy(lens_dicts)
        kwargs['kwargs_source'] = deepcopy(source_dicts)
        kwargs['kwargs_lens_light'] = deepcopy(lens_light_dicts)
        
        kwargs_result.append(kwargs)
    
    return kwargs_result



def df_2_dict(df,band_list,obj_name_location):
    """
    Function that creates dictionary out of dataframe of results.
        :df: pandas dataframe of created from imported full_results.csv (or at least must have same column names as 
            full_results.csv)
        :band_list: list of bands (strings) of image data (e.g. ['g','r','i'])
        :obj_name_location: location index (starting with 0) in image filename where object ID is located. 
                            (Ex: DES_11016024.fits has object ID at location 0, whereas PS1_candID178592236342949891_r.fits 
                             has ID at location 1) 
    
    Returns 
        :params_dict: Dictionary of all the parameters including q,phi converted from e1,e2 as well as gamma,theta converted from 
        gamma1,gamma2
    """
    
    import re
    from lenstronomy.Util.param_util import ellipticity2phi_q
    from lenstronomy.Util.param_util import shear_cartesian2polar
    
    IDs = []
    fn = df.loc[1:,'Unnamed: 1'].tolist()
    for f in fn:
        IDs.append(re.findall('\d+', f)[obj_name_location])
    
    #X_sq = deepcopy(df.loc[1:,'Unnamed: 2'].to_numpy(dtype='float32'))
    X_sq = np.array(deepcopy(df.loc[1:,'Unnamed: 2'].to_numpy(dtype='float32')))
    
    lens_dict = {}
    for col in df.loc[:,'SIE_lens':'SIE_lens.4']:
        lens_dict[df[col][0]] = deepcopy(df.loc[1:,col].to_numpy(dtype='float32'))
    
    shear_dict = {}
    for col in df.loc[:,'SHEAR_lens':'SHEAR_lens.1']:
        shear_dict[df[col][0]] = deepcopy(df.loc[1:,col].to_numpy(dtype='float32'))
    
    
    lens_dict['q'] = np.array([])
    lens_dict['phi'] = np.array([])
    shear_dict['gamma'] = np.array([])
    shear_dict['theta'] = np.array([])
    
    for i in range(len(IDs)):
        phi,q = ellipticity2phi_q(lens_dict['e1'][i],lens_dict['e2'][i])
        lens_dict['q'] = np.append(lens_dict['q'],q)
        lens_dict['phi'] = np.append(lens_dict['phi'],phi)
        
        theta,gamma = shear_cartesian2polar(shear_dict['gamma1'][i],shear_dict['gamma2'][i])
        shear_dict['gamma'] = np.append(shear_dict['gamma'],gamma)
        shear_dict['theta'] = np.append(shear_dict['theta'],theta)
        
    source_dict = {}
    lens_light_dict = {}
    for b in band_list:
        source_dict[b] = {}
        
        for col in df.loc[:,'{} Band: SERSIC_ELLIPSE_source'.format(b):'{} Band: SERSIC_ELLIPSE_source.6'.format(b)]:
            source_dict[b][df[col][0]] = deepcopy(df.loc[1:,col].to_numpy(dtype='float32'))
        
        lens_light_dict[b] = {}
        for col in df.loc[:,'{} Band: SERSIC_ELLIPSE_lens_light'.format(b):'{} Band: SERSIC_ELLIPSE_lens_light.6'.format(b)]:
            lens_light_dict[b][df[col][0]] = deepcopy(df.loc[1:,col].to_numpy(dtype='float32'))
    
        source_dict[b]['q'] = np.array([])
        source_dict[b]['phi'] = np.array([])
        lens_light_dict[b]['q'] = np.array([])
        lens_light_dict[b]['phi'] = np.array([])
        
        for i in range(len(IDs)):
            phi_src,q_src = ellipticity2phi_q(source_dict[b]['e1'][i],source_dict[b]['e2'][i])
            source_dict[b]['q'] = np.append(source_dict[b]['q'],q_src)
            source_dict[b]['phi'] = np.append(source_dict[b]['phi'],phi_src)
            
            phi_ll,q_ll = ellipticity2phi_q(lens_light_dict[b]['e1'][i],lens_light_dict[b]['e2'][i])
            lens_light_dict[b]['q'] = np.append(lens_light_dict[b]['q'],q_ll)
            lens_light_dict[b]['phi'] = np.append(lens_light_dict[b]['phi'],phi_ll)
            
        
    
    lens_source_disp = np.sqrt( (lens_dict['center_x'] - source_dict[band_list[0]]['center_x'])**2 +
                              (lens_dict['center_y'] - source_dict[band_list[0]]['center_y'])**2)
    
    params_dict = {'Object IDs': IDs, 'Reduced Chi^2': X_sq, 
                  'lens': lens_dict, 'shear': shear_dict, 
                   'source': source_dict, 'lens_light': lens_light_dict,
                  'lens_source_disp': lens_source_disp}
    
    return params_dict
