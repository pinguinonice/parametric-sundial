#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Sep  9 23:16:15 2020

@author: philippschneider
"""



# definitition of functions

def zero2sun(lat0, lon0, alt0, date):
    """
    This functions calculates the suns Euclidean coordinates (ecef) based on a time.
    It also returns the coordiantes of an observers in the same reference frame
    
    Input:
        lat0: latitude observers
        lon0: longitude observer
        alt0: hightAbove ellipsoid observer
        date: dateTime of interest
    Output:
        x_obs,y_obs,z_obs: ecef coordinates of the observer
        x_sun,y_sun,z_sun: ecef coordinates of the sun at dateTime       
    """
    from pysolar.solar import get_altitude,get_azimuth
    import pymap3d as pm
    import numpy as np
    
    ele=[]
    azi=[]
    srange=[]
    for date_single in date:
        ele.append( get_altitude(lat0, lon0, date_single))
        azi.append( get_azimuth( lat0, lon0, date_single) )
        srange.append(150e6)
        
    
    print('Elevation=',ele)
    print('Azimuth=',azi)
    
    x_obs,y_obs,z_obs = pm.geodetic2ecef(lat0,lon0,alt0)
    x_sun,y_sun,z_sun = pm.aer2ecef(azi,ele,srange,lat0,lon0,alt0)
    
    
    return(x_obs,y_obs,z_obs,x_sun,y_sun,z_sun)



#  main code starts here 

import datetime
import pytz
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import time
import numpy as np

# define a dateTime
date_base = datetime.datetime.now(pytz.UTC)
date_base = datetime.datetime(2000, 12, 21,12,tzinfo=pytz.UTC)
date = [date_base + datetime.timedelta(days=i) for i in range(0,182)]

# define a observers Point
lat0=48.7758
lon0=9.1829
alt0=500


x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun(lat0, lon0,alt0, date)


import math
import numpy as np
from scipy.spatial.transform import Rotation as R

# generate scale
radius = 0.2 #meter
Nmins=12*60 # number of minutes on scale
t=np.linspace(0, math.pi, num=Nmins) # create parameters

#paremetrize half a circle
x = radius*np.cos(t)
y = radius*np.sin(t)
z = np.zeros([Nmins,])

#transpose circle so the normal vec face polar star
r = R.from_euler('y', lat0, degrees=True)
xyz=r.apply(np.array([x,y,z]).transpose([1,0]))

# translate circle to observes position
x=xyz[:,0]+x_obs
y=xyz[:,1]+y_obs
z=xyz[:,2]+z_obs


# generate vectors between min on scale and the sun
min=np.floor(Nmins/2) # reference minute

vectors=np.array([[x_sun-x[0]],[y_sun-y[0]],[z_sun-z[0]]])  # vector = X-X_sun

vectors /= np.sqrt((vectors ** 2).sum(-1))[..., np.newaxis] # norm vector


# get x y z  of normed vector
nx=vectors[0,].flatten()
ny=vectors[1,].flatten()
nz=vectors[2,].flatten()




# plot everythin in 3d

fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
for i in range(0,nx.size-1):
    ax.plot([x[0], x[0]+10*radius*nx[i]],[y[0], y[0]+10*radius*ny[i]],[z[0], z[0]+10*radius*nz[i]],'-')
ax.plot(x,y,z,'.')
ax.axis('auto')
#print('sun=',x_sun,y_sun,z_sun)

# fig = plt.figure()
# ax = fig.add_subplot(111, projection='3d')
# ax.plot(np.array(x_sun),np.array(y_sun),np.array(z_sun))


