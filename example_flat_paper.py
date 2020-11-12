#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 12 00:38:46 2020

@author: philippschneider
"""





import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import datetime
import pytz
from timezonefinder import TimezoneFinder
from dateutil import tz 





from sundial import zero2sun
from sundial import LinePlaneCollision

# define the observers Point
lat0=48.7758
lon0=9.1829
alt0=500


tf = TimezoneFinder()

timeZone=tz.gettz(tf.timezone_at(lng=lon0, lat=lat0)) # returns 'Europe/Berlin'


# define a dateTime



date_base = datetime.datetime(2000, 6, 21,12,0,tzinfo=pytz.UTC)
    
date_base = date_base - timeZone.utcoffset(date_base)
# date = [date_base + datetime.timedelta(days=i) for i in range(0,182)] # day steps
#date = [date_base + datetime.timedelta(hours=i) for i in range(0,1)] # hour steps
#date = [date_base + datetime.timedelta(minutes=i) for i in range(0,12*60)] # minute steps


#all hours for half a year
date=[]

for i in range(0,60,10): # min
    date1=date_base + datetime.timedelta(minutes=i)
    for k in range(0,24): # hour steps
        date2=date1 + datetime.timedelta(hours=k)
        for j in range(0,365):
            newdate=date2 + datetime.timedelta(days=j)
            date.append(newdate ) #day steps


print("Sundial for lat:"+str(lat0)+" and  lon:"+ str(lon0)+" in timeZone "+str(timeZone.tzname(date_base)))






# get all sunpositions for all dates in ENU crs
x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun(lat0, lon0,alt0, date)


planeNormal = np.array([0, 0, 1])
planePoint = np.array([0, 0, 0]) #Any point on the plane
 
#Define ray
rayPoint = np.array([0, 0, 1]) #Any point along the ray
Psi_x=[]
Psi_y=[]

for i in range(0,len(x_sun)-1):
    rayDirection = np.array([x_sun[i],y_sun[i],z_sun[i]])-np.array([x_obs,y_obs,z_obs])
    psi=LinePlaneCollision(planeNormal, planePoint, rayDirection, rayPoint)
    if np.linalg.norm(psi) > 50:
        continue
    
    Psi_x.append(psi[0])
    Psi_y.append(psi[1])




fig, ax = plt.subplots()
ax.plot(Psi_x, Psi_y,marker='.',linestyle = '-')
plt.show()



 