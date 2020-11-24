# mm-lithography (mm = Micro-Manager)
 Control software for automated lithography on an inverted microscope using the Micro-Manager API.

![GUI](static/gui-sreenshot.png)

Hope this piece of software might be of use for others as well. The file 
is currently in a very simple organization. A single Python file generates 
the logic and imports hardware settings. The hardware configuration file 
generated with the Micro-Manager setup wizard. 

Once "mm-gui.py" is running, you can choose a txt file to import the positions 
that you want to expose. The defined positions map is superimposed onto the 
acquired image to make sure the spots for exposure are aligned nicely with 
the actual features. Each point is then scanned sequentially with the 
installed XY stage and exposed with light for a user-specified duration.

+ Inverted microscope configured with the famous Micro-Manager 
+ Python-based control software
+ Arduino software

The software could be readily adapted for optogenetics and other light patterning
applications.

Necessary hardware:
-------------------
+ Microscope with motorized XY stage
+ Source of light exposure (here usually UV is transmitted from lamp, but not limited to it)
+ Shutter to control the exposure time

Optional hardware:
-------------------
+ Arduino that triggers an external shutter to control the light exposure. The Arduino is programmed with "micromanager.ino". 

