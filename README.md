# solardial

a parametric sundial after Bernhardt's concept, based on lat, lon of observer
https://de.wikipedia.org/wiki/Bernhardtsche_Walze

3d printer file
![STL](https://github.com/pinguinonice/solardial/blob/master/docu/stl.PNG =250x250)


## Use

`minScale,hourScale,P0,P1,P,noonTick=generateSundial(lat0,lon0,alt0,radius,noonOffset,season)`

    This functions generates the gnomon and the scale for a bernard's sundial 
    It takes in account the "Equation of time" for the observation point (lat0,lon0,alt0)
    
       
    
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
          




## Example plots
For Stuttgart, Germany (with spring and fall gnomon):

![For Stuttgart Spring 21.12.-21.6.](https://github.com/pinguinonice/solardial/blob/master/docu/stuttgart.PNG)

![For Stuttgart Fall 21.6.-21.12.](https://github.com/pinguinonice/solardial/blob/master/docu/stuttgart_fall.PNG)

For Equator

![For equator](https://github.com/pinguinonice/solardial/blob/master/docu/equator.PNG)



For Pole

![For Pole](https://github.com/pinguinonice/solardial/blob/master/docu/pol.PNG)
