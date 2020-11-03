
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from sundial import generateSundial
# define the observers Point
lat0=0#48.7758
lon0=9.1829
alt0=500

# radius um scale
radius = 0.1 #meter

# offset if gnomon is to thick/thin
noonOffset=0*15


season='fall'#'spring'


minScale,hourScale,P0,P1,P,noonTick=generateSundial(lat0,lon0,alt0,radius,noonOffset,season)




# plot everythin in 3d

fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
for i in range(0,182):
    #draw rays (1:end) and gnomon (0)
    ax.plot(  [P0[i,0],P1[i,0]], [P0[i,1],P1[i,1]], [P0[i,2],P1[i,2]],'-')


ax.plot(hourScale[:,0],hourScale[:,1],hourScale[:,2],'.r',markersize=10)
ax.plot(noonTick[0],noonTick[1],noonTick[2],'.b',markersize=10)

for i in range(1,24):
    ax.text(hourScale[i,0],hourScale[i,1],hourScale[i,2], str(i-1), color='red')


ax.plot(minScale[:,0],minScale[:,1],minScale[:,2],'.k',markersize=1)
# plot intersection points (gnomon)
ax.plot(P[:,0],P[:,1],P[:,2],'.')
# plot gnomon axis
ax.plot(  [P0[0,0],P1[0,0]], [P0[0,1],P1[0,1]], [P0[0,2],P1[0,2]],'-')




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



