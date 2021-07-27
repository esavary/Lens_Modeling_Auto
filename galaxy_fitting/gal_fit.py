from Lens_Modeling_Auto.auto_modeling_functions import prepareFit
from Lens_Modeling_Auto.auto_modeling_functions import runFit
from lenstronomy.Workflow.fitting_sequence import FittingSequence
from Lens_Modeling_Auto.auto_modeling_functions import find_components
from Lens_Modeling_Auto.auto_modeling_functions import mask_for_sat
from Lens_Modeling_Auto.auto_modeling_functions import mask_for_lens_gal


####################### Initial Params #######################
# lens_light_sersic_fixed = {}
# lens_light_sersic_init = {'R_sersic': 1.0, 'n_sersic': 2.,'e1': 0., 'e2': 0., 'center_x': 0., 'center_y': 0}
# lens_light_sersic_sigma = {'R_sersic': 0.1, 'n_sersic': 1.0,'e1': 0.5, 'e2': 0.5,  'center_x': 0.01, 'center_y': 0.01}
# lens_light_sersic_lower = {'R_sersic': 0.001, 'n_sersic': 1.0,'e1': -0.5, 'e2': -0.5, 'center_x': -1.5, 'center_y': -1.5}
# lens_light_sersic_upper = {'R_sersic': 5., 'n_sersic': 10.,'e1': 0.5, 'e2': 0.5, 'center_x': 1.5, 'center_y': 1.5}

lens_light_sersic_fixed = [{},{}]
lens_light_sersic_init = [{'R_sersic': 0.5, 'n_sersic': 4.,'e1': 0., 'e2': 0., 'center_x': 0., 'center_y': 0},
                         {'R_sersic': 1.5, 'n_sersic': 1.,'e1': 0., 'e2': 0., 'center_x': 0., 'center_y': 0}]

lens_light_sersic_sigma = [{'R_sersic': 0.1, 'n_sersic': 1.0,'e1': 0.5, 'e2': 0.5,  'center_x': 0.01, 'center_y': 0.01},
                          {'R_sersic': 0.1, 'n_sersic': 1.0,'e1': 0.5, 'e2': 0.5,  'center_x': 0.01, 'center_y': 0.01}]

lens_light_sersic_lower = [{'R_sersic': 0.001, 'n_sersic': 1.,'e1': -0.5, 'e2': -0.5, 'center_x': -1.5, 'center_y': -1.5},
                          {'R_sersic': 0.001, 'n_sersic': 0.1,'e1': -0.5, 'e2': -0.5, 'center_x': -1.5, 'center_y': -1.5}]

lens_light_sersic_upper = [{'R_sersic': 5., 'n_sersic': 10.,'e1': 0.5, 'e2': 0.5, 'center_x': 1.5, 'center_y': 1.5},
                          {'R_sersic': 5., 'n_sersic': 10.,'e1': 0.5, 'e2': 0.5, 'center_x': 1.5, 'center_y': 1.5}]

# source_sersic_fixed = {}
# source_sersic_init = {'R_sersic': 1.0, 'n_sersic': 1.,'e1': 0., 'e2': 0., 'center_x': 0., 'center_y': 0}
# source_sersic_sigma = {'R_sersic': 0.1, 'n_sersic': 0.5,'e1': 0.5, 'e2': 0.5,  'center_x': 0.01, 'center_y': 0.01}
# source_sersic_lower = {'R_sersic': 0.001, 'n_sersic': 0.1,'e1': -0.5, 'e2': -0.5, 'center_x': -1.5, 'center_y': -1.5}
# source_sersic_upper = {'R_sersic': 5., 'n_sersic': 10.,'e1': 0.5, 'e2': 0.5, 'center_x': 1.5, 'center_y': 1.5}


# lens_sie_fixed = {}  
# lens_sie_init = {'theta_E': 1.5, 'e1': 0., 'e2': 0., 'center_x': 0., 'center_y': 0.}
# lens_sie_sigma = {'theta_E': .3, 'e1': 0.5, 'e2': 0.5, 'center_x': 0.1, 'center_y': 0.1}
# lens_sie_lower = {'theta_E': 0.1, 'e1': -1, 'e2': -1, 'center_x': -1.5, 'center_y': -1.5}
# lens_sie_upper = {'theta_E': 5.0, 'e1': 1, 'e2': 1, 'center_x': 1.5, 'center_y': 1.5}


# lens_shear_fixed = {'ra_0': 0, 'dec_0': 0}
# lens_shear_init = {'ra_0': 0, 'dec_0': 0,'gamma1': 0., 'gamma2': 0.0}
# lens_shear_sigma = {'gamma1': 0.1, 'gamma2': 0.1}
# lens_shear_lower = {'gamma1': -0.5, 'gamma2': -0.5}
# lens_shear_upper = {'gamma1': 0.5, 'gamma2': 0.5}

# if includeShear == True:
#     lens_initial_params = deepcopy([[lens_sie_init,lens_shear_init],
#                                     [lens_sie_sigma,lens_shear_sigma],
#                                     [lens_sie_fixed,lens_shear_fixed],
#                                     [lens_sie_lower,lens_shear_lower],
#                                     [lens_sie_upper,lens_shear_upper]])
# else:
#     lens_initial_params = deepcopy([[lens_sie_init],
#                                     [lens_sie_sigma],
#                                     [lens_sie_fixed],
#                                     [lens_sie_lower],
#                                     [lens_sie_upper]])


lens_light_initial_params = deepcopy([lens_light_sersic_init, 
                                      lens_light_sersic_sigma, 
                                      lens_light_sersic_fixed, 
                                      lens_light_sersic_lower, 
                                      lens_light_sersic_upper])

# source_initial_params = deepcopy([[source_sersic_init], 
#                                   [source_sersic_sigma], 
#                                   [source_sersic_fixed], 
#                                   [source_sersic_lower], 
#                                   [source_sersic_upper]])



########################################## Model Lens Light ##########################################

print('I will first model lens light with two SERSIC_ELLIPSE profiles')
print('------------------------------------------------------------------------------')
#Model Lists
lens_model_list = [] 
source_model_list = [] 
lens_light_model_list = ['SERSIC_ELLIPSE','SERSIC_ELLIPSE']


gal_mask_list = []
mask_list = []

for data in kwargs_data: 
    gal_mask_list.append(mask_for_lens_gal(data['image_data'],deltaPix))
    if use_mask:
        mask_list.append(mask_for_sat(data['image_data'],deltaPix))
    else: mask_list = None


#prepare fitting kwargs
kwargs_likelihood, kwargs_model, kwargs_data_joint, multi_band_list,kwargs_constraints = prepareFit(kwargs_data, kwargs_psf,
                                                                                 lens_model_list, source_model_list,
                                                                                 lens_light_model_list, 
                                                                                 image_mask_list = mask_list)   

###prepare kwarg_params

lens_light_params = [[],[],[],[],[]]

for j,f in enumerate(lens_light_params):
    for i in range(len(kwargs_data)):
        f.extend(deepcopy(lens_light_initial_params[j]))


source_params = [[],[],[],[],[]]


lens_params = [[],[],[],[],[]]

kwargs_params = {'lens_model': deepcopy(lens_params),
                'source_model': deepcopy(source_params),
                 'lens_light_model': deepcopy(lens_light_params)}

kwargs_fixed = {'kwargs_lens': deepcopy(lens_params[2]), 
                 'kwargs_source': deepcopy(source_params[2]), 
                 'kwargs_lens_light': deepcopy(lens_light_params[2])}

print('The lens, source, and lens light modeling parameters are')
print('lens model: ', kwargs_params['lens_model'])
print('\n')
print('source model: ', kwargs_params['source_model'])
print('\n')
print('lens light model: ', kwargs_params['lens_light_model'])
print('\n')
print('-------------------------------------------------------------------')
print('\n')
print('I will now begin the PSO:')


# fitting_kwargs_list = [['PSO', {'sigma_scale': 1., 'n_particles': 50, 'n_iterations': 100,'threadCount': 1}]]

chain_list, kwargs_result = runFit(fitting_kwargs_list, kwargs_params, 
                                   kwargs_likelihood, kwargs_model,
                                   kwargs_data_joint, kwargs_constraints = kwargs_constraints) 


print('\n')
print('##########################################################################')
print('\n')
