
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov 16 19:55:04 2020

@author: philippschneider
"""
import numpy as np
from mecode import G
g=G(outfile='output/form.gcode')

Tstart=0
Tend=100
Tn=1000
t=np.linspace(Tstart, Tend,Tn)



A1=100
f1=-6
p1=np.pi/6
d1=0.004

A2=100
f2=-6
p2=np.pi/2
d2=0.004

A3=100
f3=6
p3=np.pi/6
d3=0.004

A4=100
f4=4
p4=np.pi/2
d4=0.004

x=A1*np.sin(t*f1+p1)*np.exp(-d1*t)+A2*np.sin(t*f2+p2)*np.exp(-d2*t)

y=A3*np.sin(t*f3+p3)*np.exp(-d3*t)+A4*np.sin(t*f4+p4)*np.exp(-d4*t)

for i in range(0,len(t)-1):
    g.move(x[i],y[i])


g.view()

g.teardown()







