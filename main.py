#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Sep  9 23:16:15 2020

@author: philippschneider
"""





def zero2sun(lat0, lon0, date):
    """
    This function greets to
    the person passed in as
    a parameter
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




import datetime
import pytz
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import time
import numpy as np

date_base = datetime.datetime.now(pytz.UTC)

date_base = datetime.datetime(2000, 12, 21,12,tzinfo=pytz.UTC)
date = [date_base + datetime.timedelta(days=i) for i in range(0,182)]

lat0=48.7758
lon0=9.1829
alt0=500


x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun(lat0, lon0, date)


import math
import numpy as np
from scipy.spatial.transform import Rotation as R

radius = 0.1 #meter

t=np.linspace(math.pi/2, -math.pi/2, num=24*60)

x = radius*np.cos(t)
y = radius*np.sin(t)
z = np.zeros([24*60,])

r = R.from_euler('y', lat0, degrees=True)

xyz=r.apply(np.array([x,y,z]).transpose([1,0]))

x=xyz[:,0]+x_obs
y=xyz[:,1]+y_obs
z=xyz[:,2]+z_obs



vectors=np.array([[x_sun-x[0]],[y_sun-y[0]],[z_sun-z[0]]])

vectors /= np.sqrt((vectors ** 2).sum(-1))[..., np.newaxis]



nx=vectors[0,].flatten()
ny=vectors[1,].flatten()
nz=vectors[2,].flatten()






fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
for i in range(0,nx.size-1):
    ax.plot([x[0], x[0]+10*radius*nx[i]],[y[0], y[0]+10*radius*ny[i]],[z[0], z[0]+10*radius*nz[i]],'-')
ax.plot(x,y,z,'.')

#print('sun=',x_sun,y_sun,z_sun)

# fig = plt.figure()
# ax = fig.add_subplot(111, projection='3d')
# ax.plot(np.array(x_sun),np.array(y_sun),np.array(z_sun))


