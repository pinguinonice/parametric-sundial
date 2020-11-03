# -*- coding: utf-8 -*-
"""
Created on Tue Nov  3 11:22:18 2020

@author: Philipp
"""


import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from sundial import generateSundial
# define the observers Point
lat0=48.7758
lon0=9.1829
alt0=500

# radius um scale
radius = 0.1 #meter

# offset if gnomon is to thick/thin
noonOffset=0*15


season='fall'#'spring'


minScale,hourScale,P0,P1,P,noonTick=generateSundial(lat0,lon0,alt0,radius,noonOffset,season)

np.savetxt("output/minScale.csv", minScale, delimiter=",")
np.savetxt("output/hourScale.csv", hourScale, delimiter=",")
np.savetxt("output/P0.csv", P0[0,:].transpose(), delimiter=",")
np.savetxt("output/P1.csv", P1[0,:].transpose(), delimiter=",")
np.savetxt("output/P.csv", P[0:182,:], delimiter=",")
np.savetxt("output/noonTick.csv", noonTick, delimiter=",")
