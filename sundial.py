# -*- coding: utf-8 -*-
"""
Created on Tue Nov  3 11:06:37 2020

@author: Philipp
"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Sep  9 23:16:15 2020

@author: philippschneider
"""



# definitition of functions



def zero2sun(lat, lon, alt, date):
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
        ele.append( get_altitude(lat, lon, date_single,alt))
        azi.append( get_azimuth( lat, lon, date_single,alt) )
        srange.append(150e9)
        
    
    #print('Elevation=',ele)
    #print('Azimuth=',azi)
    
    e_obs,n_obs,u_obs = 0,0,0
    e_sun,n_sun,u_sun = pm.aer2enu(azi,ele,srange)
    
    
    return(e_obs,n_obs,u_obs,e_sun,n_sun,u_sun)

def date2index(dates,Nmins):
    """
    This functions calculates the index of the Nmins on sundial scale (0 to 719) (6:00h to 18:00h) for each entry in date 
    
    Input:
        dates: list of dateTime
        Nmins: number of ticks
    Output:
        index: a list of index with length of date
              
    """
    import datetime
    
    index=[]

    for date in dates:
        
        
        
        i=int(Nmins-(date.minute + date.hour*60  )-1)
        index.append(i)
        if i<0:
            print('Time is not on scale: index < 0')
            break
        
    
    return index
    



def closestDistanceBetweenLines(a0,a1,b0,b1,clampAll=False,clampA0=False,clampA1=False,clampB0=False,clampB1=False):

    ''' Given two lines defined by numpy.array pairs (a0,a1,b0,b1)
        Return the closest points on each segment and their distance
    '''
    import numpy as np
    # If clampAll=True, set all clamps to True
    if clampAll:
        clampA0=True
        clampA1=True
        clampB0=True
        clampB1=True


    # Calculate denomitator
    A = a1 - a0
    B = b1 - b0
    magA = np.linalg.norm(A)
    magB = np.linalg.norm(B)
    
    _A = A / magA
    _B = B / magB
    
    cross = np.cross(_A, _B);
    denom = np.linalg.norm(cross)**2
    
    
    # If lines are parallel (denom=0) test if lines overlap.
    # If they don't overlap then there is a closest point solution.
    # If they do overlap, there are infinite closest positions, but there is a closest distance
    if not denom:
        d0 = np.dot(_A,(b0-a0))
        
        # Overlap only possible with clamping
        if clampA0 or clampA1 or clampB0 or clampB1:
            d1 = np.dot(_A,(b1-a0))
            
            # Is segment B before A?
            if d0 <= 0 >= d1:
                if clampA0 and clampB1:
                    if np.absolute(d0) < np.absolute(d1):
                        return a0,b0,np.linalg.norm(a0-b0)
                    return a0,b1,np.linalg.norm(a0-b1)
                
                
            # Is segment B after A?
            elif d0 >= magA <= d1:
                if clampA1 and clampB0:
                    if np.absolute(d0) < np.absolute(d1):
                        return a1,b0,np.linalg.norm(a1-b0)
                    return a1,b1,np.linalg.norm(a1-b1)
                
                
        # Segments overlap, return distance between parallel segments
        return None,None,np.linalg.norm(((d0*_A)+a0)-b0)
        
    
    
    # Lines criss-cross: Calculate the projected closest points
    t = (b0 - a0);
    detA = np.linalg.det([t, _B, cross])
    detB = np.linalg.det([t, _A, cross])

    t0 = detA/denom;
    t1 = detB/denom;

    pA = a0 + (_A * t0) # Projected closest point on segment A
    pB = b0 + (_B * t1) # Projected closest point on segment B


    # Clamp projections
    if clampA0 or clampA1 or clampB0 or clampB1:
        if clampA0 and t0 < 0:
            pA = a0
        elif clampA1 and t0 > magA:
            pA = a1
        
        if clampB0 and t1 < 0:
            pB = b0
        elif clampB1 and t1 > magB:
            pB = b1
            
        # Clamp projection A
        if (clampA0 and t0 < 0) or (clampA1 and t0 > magA):
            dot = np.dot(_B,(pA-b0))
            if clampB0 and dot < 0:
                dot = 0
            elif clampB1 and dot > magB:
                dot = magB
            pB = b0 + (_B * dot)
    
        # Clamp projection B
        if (clampB0 and t1 < 0) or (clampB1 and t1 > magB):
            dot = np.dot(_A,(pB-a0))
            if clampA0 and dot < 0:
                dot = 0
            elif clampA1 and dot > magA:
                dot = magA
            pA = a0 + (_A * dot)

    
    return pA,pB,np.linalg.norm(pA-pB)




def generateSundial(lat0,lon0,alt0,radius,noonOffset,season):
    """
    This functions generates the gnomon and the scale for a bernard's sundial 
    It takes in account the "Equation of time" for the observation point (lat0,lon0,alt0)
    
    
    https://de.wikipedia.org/wiki/Bernhardtsche_Walze
    
    
    Input:
        lat0: latitude of observation point
        lon0: longditude of observation point
        alt0: altitude of observation point
        radius: radius of the scale
        noonOffset: turns the scale so the "noon" tick gets into different position.
                    tweak here if the gnomon is to thick or to thin  
        season:'fall' generates gnomon for 21.6. - 21.12.
               'spring' generates gnomon for 21.12. - 21.6. 
                    
    Output:
        minScale: the Minute ticks in enu
        hourScale: the Hour ticks in enu
        noonTick: the 12:00h noon tick in enu
        P0: ray start points (first is gnomon axis) (coordinate referens system: east north up)
        P1: ray end points (first is gnomon axis) (coordinate referens system: east north up)
        P: gnomons points (crs: enu) each 182 block represents one hour over the year starting with "12:00h"
          
    """
    import math
    import numpy as np
    from scipy.spatial.transform import Rotation as R
    import datetime
    import pytz
    from timezonefinder import TimezoneFinder
    from dateutil import tz 


    tf = TimezoneFinder()

    timeZone=tz.gettz(tf.timezone_at(lng=lon0, lat=lat0)) # returns 'Europe/Berlin'
    
    
    # define a dateTime
    
    
    
    if season == 'spring':
        date_base = datetime.datetime(2000, 12, 21,12,0,tzinfo=pytz.UTC)
    if season == 'fall':
        date_base = datetime.datetime(2000, 6, 21,12,0,tzinfo=pytz.UTC)
        
    date_base = date_base - timeZone.utcoffset(date_base)
    # date = [date_base + datetime.timedelta(days=i) for i in range(0,182)] # day steps
    #date = [date_base + datetime.timedelta(hours=i) for i in range(0,1)] # hour steps
    #date = [date_base + datetime.timedelta(minutes=i) for i in range(0,12*60)] # minute steps
    
    
    #all hours for half a year
    date=[]
    
    for i in range(0,24): # day steps
            date1=date_base + datetime.timedelta(hours=i)
            for j in range(0,183):
                newdate=date1 + datetime.timedelta(days=j)
                date.append(newdate ) #hour steps
        
    
    print("Sundial for lat:"+str(lat0)+" and  lon:"+ str(lon0)+" in timeZone "+str(timeZone.tzname(date_base))+ " with "+season+" gnomon")


    
    
    
    
    # get all sunpositions for all dates in ENU crs
    x_obs,y_obs,z_obs,x_sun,y_sun,z_sun=zero2sun(lat0, lon0,alt0, date)
    
    
    # generate scale of sundial
    Nmins=24*60 # number of minutes on scale
    t=np.linspace(-math.pi/2, 3/2*math.pi, num=Nmins) # create parameters (minutes)
    
    
    #paremetrize half a circle [minutes]
    x = radius*np.cos(t)
    y = radius*np.sin(t)
    z = np.zeros([Nmins,])
    
    
    # generate gnomon
    xg=np.array([0, 0])
    yg=np.array([0, 0])
    zg=np.array([0- radius, 0 + radius])
    
    #transpose circle so the normal vec face polar star
    r = R.from_euler('z',noonOffset, degrees=True)
    xyz=r.apply(np.array([x,y,z]).transpose([1,0]))
    
    r = R.from_euler('x',-(90-lat0), degrees=True)
    
    xyzg=r.apply(np.array([xg,yg,zg]).transpose([1,0]))
    
    xyz=r.apply(xyz)
    
    # translate gnomon circle to observes position
    xg=xyzg[:,0]+x_obs
    yg=xyzg[:,1]+y_obs
    zg=xyzg[:,2]+z_obs
    
    x=xyz[:,0]+x_obs
    y=xyz[:,1]+y_obs
    z=xyz[:,2]+z_obs
    
    
    
    # calculate minute on scale index
    index=date2index(date,Nmins)
    
    
    # generate vectors between min on scale and the sun
    vectors=np.array([[x_sun-x[index]],[y_sun-y[index]],[z_sun-z[index]]])  # vector = X-X_sun
    vectors /= np.linalg.norm(vectors[:,0,0]) # norm vector by deviding by length of first
    
    
    # get x y z  of normed vector
    nx=vectors[0,].flatten()
    ny=vectors[1,].flatten()
    nz=vectors[2,].flatten()
    
    
    
    
    
    # genrate list of all lines
    P0=np.empty((0,3), float)
    P1=np.empty((0,3), float)
    
    P0=np.append(P0,np.array([[xg[0],yg[0],zg[0]]]),axis=0 )
    P1=np.append(P1,np.array([[xg[1],yg[1],zg[1]]]),axis=0 )
    
    # calculate closest point of each "sunray"(P0[1:end] to P1[1:end]) to gnomon (P0[0] to P1[0])
    for i in range(0,nx.size):
    
        P0=np.append(P0,np.array([[x[index[i]],y[index[i]],z[index[i]]]]),axis=0 )
        P1=np.append(P1,np.array([[x[index[i]]+1.2*radius*nx[i],y[index[i]]+1.2*radius*ny[i],z[index[i]]+1.2*radius*nz[i]]]),axis=0 )
    
    
    P=np.empty((0,3), float)
    
    for i in range(1,P0.shape[0]):
        pA,pB,dAB=closestDistanceBetweenLines(P0[0,:],P1[0,:],P0[i,:],P1[i,:])
        #p=intersect(P0[[0,i],:],P1[[0,i],:]).transpose()
        P=np.append(P,[pB.transpose()],axis=0)
        
    
    
    
    minScale=np.array([x,y,z]).transpose()
    hourScale=np.array([x[0::60],y[0::60],z[0::60]]).transpose()
    noonTick=minScale[index[0],:]
    
    
    return minScale,hourScale,P0,P1,P,noonTick




