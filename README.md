
# HOW TO USE:

Instructions version 1.2

Updated June 19, 2024.

For best results, run this on a Raspberry Pi 5, which can easily handle 4 simultaneous cameras,
whereas the Pi 4 seems to struggle with even 2 cameras.

Hopefully someone has already installed all files and libraries for you. If not, skip to the bottom
"Installing on a new machine", then come back here when you are done.

Locate the directory where the program resides. If not sure where that is, look here first:

    /home/jhoulab/Documents/github/Pi5WebcamRecorder

Now launch the program with one of the following methods:

    Method 1: From command line. Open command prompt, "cd" to program directory, then type:

      python -m WEBCAM_RECORD

    Method 2: From GUI. Open Thonny (Pi's built-in Python IDE). Open WEBCAM_RECORD.py,
    then hit the "Run" button (green circle with white triangle).


Upon launch, it will scan the system for up to 4 connected USB cameras, then display them
in a 2x2 grid. The position in the grid matches the position of the physical USB port.
The cameras are numbered 1-4, in the following order:

    -------------
    |  1  |  2  |
    -------------
    |  3  |  4  |
    -------------

Once running, it will respond to the following keyboard keys:

    "Q":            Stops any ongoing recordings, and quits program
    Left cursor:    Cycles through cameras in descending order
    Right cursor:   Cycles through cameras in ascending order
    1-4:            Typing a camera number will manually start/stop recording of that camera.
                    A red dot in the corner indicates ongoing recording.

This program also monitors GPIO pins 4-7. A low-to-high transition (i.e. from 0V to 3.3V)
on these pins has the following effects:

    Double pulse:   Starts recording when 2 pulses arrive <1.5 sec apart
    Triple pulse:   Stops recording
    Single pulse:   Saves timestamp in _TTL.txt file, and flashes blue dot in top-left corner of video

    GPIO4:          camera 1
    GPIO5:          camera 2
    GPIO6:          camera 3
    GPIO7:          camera 4

Each camera recording generates its own files, and there is no data mixing between cameras.
There are three recorded files for each session, as listed below. All filenames begin with the
date in YYYY-MM-DD-HHMM format, followed by camera number, and data type:

    2024-06-12_1738_Cam1_Frames.txt        # Tab-delimited text file with timestamps of each video frame
    2024-06-12_1738_Cam1_TTLs.txt          # Tab-delimited text file with timestamps of each TTL pulse
    2024-06-12_1738_Cam1_Video.avi         # Video file.

By default, the software records at 10 frames per second and 640x480 resolution, using
the H264 codec. To override the defaults, read the instructions in file "config_example1", which
explains how to create a "config.txt" file, or skip to the next section below, "CONFIGURING".

I have tested this program with the following two codecs. There may be others available but they
are not tested yet:

    H264:  makes small files (<2MB per minute) but is computationally demanding. May drop frames at higher fps.
    MP4V:  is computationally less demanding, allowing higher frame rates. But files are 2-5x larger

Estimated storage requirements for H264 files at 10fps are below. Obviously, if you use a higher
frame rate, or a less efficient codec, then storage requirements will increase.

    1 GB:     About 8 hours (or more) of continuous 24/7 recording.
    64 GB:    About 20 days of continuous recording
    1 TB:     About 3 months of continuous recording from 4 cameras
    1 TB:     About 1 year of continuous recording from 1 camera
    1 TB:     About 3 years when recording two 1-hour sessions per
              day from 4 animals (i.e. 8 total hours/day)


# CONFIGURING:

Most parameters (frame rate, codec, save directory) have reasonable defaults. You can
override any of these by creating a "config.txt" file. I've included two working examples of
such files called "config_example1" and "config_example2":

    config_example1      This lists of all configuration settings, along with brief
                         explanations of why you would choose one over the other
    config_example2      This is a bare-bones file with the most commonly used options 

To use these, open in any text editor, then "save as" and enter filename "config.txt".
You can then edit "config.txt" to your liking. The program will read this config file
whenever it starts up. The following options are available:

    FRAME_RATE_PER_SECOND                  # Frame rate of recorded video. Default 10
    FOURCC                                 # What codec to use. Default h264. Can change to mp4v
                                           # to achieve higher frame rates
    MAX_INTERVAL_IN_TTL_BURST              # Max number of seconds between TTLs in bursts. Default 1.5
    NUM_TTL_PULSES_TO_START_SESSION        # Number of pulses to start recording. Default 2
    NUM_TTL_PULSES_TO_STOP_SESSION         # Number of pulses to end recording. Default 3
    WIDTH                                  # X-resolution. Default 640
    HEIGHT                                 # Y-resolution. Default 480
    DATA_FOLDER                            # Folder for saving. Default /home/jhoulab/Videos/


# KNOWN SHORTCOMINGS:

1. When launching, you will get the following harmless warning. I don't know how to get rid of it,
and you can just ignore it:

    libpng warning: iCCP: known incorrect sRGB profile

2. Data captured from the camera sensor is buffered on the camera itself, and read via USB later.
So frame timestamps are likely offset by some constant delay, probably on the order of tens of
milliseconds. GPIO/TTL timestamps, on the other hand, should be accurate to within a couple of milliseconds.


#  INSTALLING ON A NEW MACHINE:

To install on a new machine, follow these three steps:

### STEP 1: Clone the github repository.

  There are two ways to do this:

  #### Method 1: Easy, but you won't be able to upload changes to Github.
  Open a command prompt, use "cd" to select a destination directory, then type:
    
    git clone https://github.com/JhouLab/Pi5WebcamRecorder

  Now go to STEP 2.

  #### Method 2: Harder, but gives you to ability to upload changes to the lab account
  Download Github Desktop from these instructions:
  https://pi-apps.io/install-app/install-github-desktop-on-raspberry-pi/

  In a nutshell, you first need to install Pi-Apps using this command:

    wget -qO- https://raw.githubusercontent.com/Botspot/pi-apps/master/install | bash

  Then launch Pi-Apps, select "Programming", then "Github Desktop" (the purple cat icon), and
  then click the button to install Github Desktop. Now launch it from the main Raspberry Pi menu, under
  "Accessories", then log into the lab github account with jhoulab1@gmail.com as username and standard password.

  Now, select "File", "Clone repository", "Github.com", then JhouLab/Pi5WebcamRecorder

## STEP 2: Install OpenCV.
  Instructions for installing it on a Pi5 are here:
  https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html

  I happened to use method #2 in the link above, which involves typing the following two commands:

    sudo apt-get install libopencv-dev
    sudo apt-get install python3-opencv

  As of 6/12/2024, the above installs OpenCV version 4.6.0, which was released 6/12/2022, whereas
  the latest version is 4.10. However, the old one seems to work well enough.

## STEP 3: Install rpi-lpgio
  Annoyingly, the Pi5 uses different GPIO hardware than the Pi4, which is not compatible with the
  default GPIO library RPi.GPIO. There are several workarounds. A simple one is to uninstall the
  standard library and install python3-rpi-lpgio, a drop-in replacement:

    sudo apt remove  python3-rpi.gpio
    sudo apt install python3-rpi-lgpio


After that, everything should run. If so, CONGRATULATIONS. If not, please email tjhou@som.umaryland.edu for help.
