# mm-lithography (mm = Micro-Manager)
 Control software for automated lithography on an inverted microscope using the Micro-Manager API.

![GUI](https://github.com/FerdinandGreiss/mm-lithography/blob/main/static/gui-screenshot.png)

Hope this piece of software might be of use for others as well. The file 
is currently in a very simple organization. A single Python file generates 
the logic and imports hardware settings. The hardware configuration file 
is generated with the Micro-Manager setup wizard. 

Once *mm-gui.py* is running, you can choose a txt file to import the positions 
that you want to expose. The defined positions map is superimposed onto the 
acquired image to make sure the spots for exposure are aligned nicely with 
the actual features. Each point is then scanned sequentially with the 
installed XY stage and exposed with light for a user-specified duration.

The txt file can be generated with any software (also by hand). For two examples,
check the provided text files in the */static* folder. Additionally, there is also a 
lisp script that can extract positions from AutoCAD files and save them as a text 
file with the correct formatting.

Main corners in project:
+ Inverted microscope configured with the famous Micro-Manager 
+ Python-based control software
+ Arduino software

The software could also be readily adapted for optogenetics and other light patterning
applications.

For a potential application, check out the corresponding publication:
Greiss, F., Daube, S.S., Noireaux, V. et al. From deterministic to fuzzy decision-making in artificial cells. Nat Commun 11, 5648 (2020). https://doi.org/10.1038/s41467-020-19395-4

Necessary hardware:
-------------------
+ Microscope with motorized XY stage
+ Source of light exposure (here usually UV is transmitted from lamp, but not limited to it)
+ Pinhole (here 200 µm was used)
+ Shutter to control the exposure time

Optional hardware:
-------------------
+ Arduino that triggers an external shutter to control the light exposure. The Arduino is programmed with *micromanager.ino*. 

TODO or potential improvements:
----
+ Threading for exposure
+ Save config file from Python (Spot illumination, Step-to-µm conversion, ...) and load automatically

