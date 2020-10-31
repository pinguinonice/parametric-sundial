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
        ele.append( get_altitude(lat0, lon0, date_single,alt0))
        azi.append( get_azimuth( lat0, lon0, date_single,alt0) )
        srange.append(150e9)
        
    
    print('Elevation=',ele)
    print('Azimuth=',azi)
    
    x_obs,y_obs,z_obs = pm.geodetic2ecef(lat0,lon0,alt0)
    x_sun,y_sun,z_sun = pm.aer2ecef(azi,ele,srange,lat0,lon0,alt0)
    
    
    return(x_obs,y_obs,z_obs,x_sun,y_sun,z_sun)

def zero2sun_enu(lat0, lon0, alt0, date):
    """
    This functions calculates the suns Euclidean coordinates (ecef) based on a time.
    It also returns the coordiantes of an observers in the same reference frame
    
    Input:
        lat0: latitude observers
        lon0: longitude observer
        alt0: hightAbove ellipsoid observer
        date: dateTime of interest
    Output:
        x_obs,y_obs,z_obs: enu coordinates of the observer = [0 0 0]
        x_sun,y_sun,z_sun: enu coordinates of the sun at dateTime       
    """
    from pysolar.solar import get_altitude,get_azimuth
    import pymap3d as pm
    import numpy as np
    
    ele=[]
    azi=[]
    srange=[]
    for date_single in date:
        ele.append( get_altitude(lat0, lon0, date_single,alt0))
        azi.append( get_azimuth( lat0, lon0, date_single,alt0) )
        srange.append(150e9)
        
    
    print('Elevation=',ele)
    print('Azimuth=',azi)
    
    e_obs,n_obs,u_obs = 0,0,0
    e_sun,n_sun,u_sun = pm.aer2enu(azi,ele,srange)
    
    
    return(e_obs,n_obs,u_obs,e_sun,n_sun,u_sun)


#  main code starts here 

import datetime
import pytz
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import time
import numpy as np

# define a dateTime
date_base = datetime.datetime.now(pytz.UTC)
date_base = datetime.datetime(2000, 3, 21,12,tzinfo=pytz.UTC)
date = [date_base + datetime.timedelta(days=i) for i in range(0,182)] # day steps
#date = [date_base + datetime.timedelta(hours=i) for i in range(0,12)] # hour steps


# define a observers Point
lat0=0#48.7758
lon0=0#9.1829
alt0=500


#x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun(lat0, lon0,alt0, date)
x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun_enu(lat0, lon0,alt0, date)


import math
import numpy as np
from scipy.spatial.transform import Rotation as R


# generate scale
radius = 0.3 #meter
Nmins=12*60 # number of minutes on scale
t=np.linspace(0, math.pi, num=Nmins) # create parameters
#paremetrize half a circle
x = radius*np.cos(t)
y = radius*np.sin(t)
z = np.zeros([Nmins,])


# generate gnomon
xg=np.array([0, 0])
yg=np.array([0, 0])
zg=np.array([0- radius, 0 + radius])

#transpose circle so the normal vec face polar star
r = R.from_euler('z',0, degrees=True)
xyz=r.apply(np.array([x,y,z]).transpose([1,0]))

r = R.from_euler('x',-(90-lat0), degrees=True)

xyzg=r.apply(np.array([xg,yg,zg]).transpose([1,0]))

xyz=r.apply(xyz)

# translate circle to observes position
xg=xyzg[:,0]+x_obs
yg=xyzg[:,1]+y_obs
zg=xyzg[:,2]+z_obs

x=xyz[:,0]+x_obs
y=xyz[:,1]+y_obs
z=xyz[:,2]+z_obs


# generate vectors between min on scale and the sun
min= int(np.floor(Nmins/2)) # reference minute

vectors=np.array([[x_sun-x[min]],[y_sun-y[min]],[z_sun-z[min]]])  # vector = X-X_sun

vectors /= np.linalg.norm(vectors[:,0,0]) # norm vector by deviding by length of first


# get x y z  of normed vector
nx=vectors[0,].flatten()
ny=vectors[1,].flatten()
nz=vectors[2,].flatten()




# plot everythin in 3d

fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
for i in range(0,nx.size-1):
    ax.plot([x[min], x[min]+radius*nx[i]],[y[min], y[min]+radius*ny[i]],[z[min], z[min]+radius*nz[i]],'-')
ax.plot(x,y,z,'.')

#draw gnomon
ax.plot(xg,yg,zg,'-')




# Create cubic bounding box to simulate equal aspect ratio
max_range = 0.3
Xb = 0.5*max_range*np.mgrid[-1:2:2,-1:2:2,-1:2:2][0].flatten() 
Yb = 0.5*max_range*np.mgrid[-1:2:2,-1:2:2,-1:2:2][1].flatten() 
Zb = 0.5*max_range*np.mgrid[-1:2:2,-1:2:2,-1:2:2][2].flatten() 
# Comment or uncomment following both lines to test the fake bounding box:
for xb, yb, zb in zip(Xb, Yb, Zb):
   ax.plot([xb], [yb], [zb], 'w')

ax.set_xlabel('East')
ax.set_ylabel('North')
ax.set_zlabel('Up')
ax.set_aspect('auto')
#print('sun=',x_sun,y_sun,z_sun)

# fig = plt.figure()
# ax = fig.add_subplot(111, projection='3d')
# ax.plot(np.array(x_sun),np.array(y_sun),np.array(z_sun))


