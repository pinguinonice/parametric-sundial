#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov 16 22:58:16 2020

@author: philippschneider
"""

class gcode:  
    
    def __init__(self,save_path):
        self.save_path=save_path
        self.gcode=[]
        self.gcode.append(';GCODE starts here')
            
    def mm_mode(self):       
        self.gcode.append('G21 ; mm-mode')
             
    def move(self,x,y,feed_rate=1000):       
        self.gcode.append('G1 F'+str(feed_rate)+' X'+str(x)+' Y'+str(y)+' ; move xy')        

            
    def home(self,feed_rate=1000):
        self.gcode.append('G1 F'+str(feed_rate)+' X0 Y0 Z0 ; home')        
            
    def print_all(self):
        for line in self.gcode:
            print(line)
    
    def write_file(self):
            
        with open(self.save_path, 'w') as the_file:
            
            for line in self.gcode:
                the_file.write(line+'\n')
                    
    def pen_up(self):
        self.gcode.append('M3S255   ; Laser Off')
        self.gcode.append('G4 P0.5  ; Tool Off')     
        self.gcode.append('G0 Z0    ; tool up')   
   
    
    def pen_down(self,feed_rate=200):
        self.gcode.append('G1 F'+str(feed_rate)+' Z-10 ; move z down')
        self.gcode.append('M3S0     ; Laser On')     
        self.gcode.append('G4 P0.5  ; Tool On') 
        


        
        
        
        
        
# test

# G=gcode('abc.gcode')   
# G.mm_mode()
# #G.home()
# G.pen_up() 

# G.move(100, 150, 1000) 
# G.pen_down()
# G.move(100, 150, 1000)
# G.move(150, 150, 1000) 
# G.move(150, 100, 1000) 
# G.move(100, 150, 1000) 
# G.pen_up()


# G.move(140,  140, 1000) 
# G.pen_down()

# G.move(140,  145, 1000)
# G.move(145,  145, 1000) 
# G.move(145,  140, 1000) 
# G.move(140,  140, 1000) 

# G.pen_up()


# G.print_all()  

# G.write_file()
 