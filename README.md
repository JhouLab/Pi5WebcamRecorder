
# HOW TO USE:

Instructions version 1.4.1

Updated Aug 3, 2024.

For best results, run on a Raspberry Pi 5, which can handle 4 simultaneous cameras
at 640x480 and 10 frames per second, whereas the Pi 4 struggles with even 2 cameras.


# GETTING STARTED:

If not already installed, see instructions below: "Installing on a new machine"

By default, videos are saved to the program directory. On most JhouLab computers it
is the following (but your installation might be different):

    /home/jhoulab/Documents/github/Pi5WebcamRecorder

To change save folder (e.g. to external drive) specify that folder name in a
config.txt file. See instructions below under "CONFIGURING".

To launch the program, use one of the following methods:

    Method 1: From command line (must be in program folder):

      python -m WEBCAM_RECORD

    Method 2: From Thonny (Pi's pre-installed Python IDE).
      Click "Load", select WEBCAM_RECORD.py,
      then click "Run" (green button with white triangle).


Upon launch, program scans for USB cameras, then displays them in a 2x2 grid.
The position in the grid matches the the physical USB port position, as shown below:

    -------------
    |  1  |  2  |
    -------------
    |  3  |  4  |
    -------------

A control bar will appear in the top left corner of screen.
You can also use the following keyboard keys:

    "Q":            Quits program. (Any ongoing records will also be stopped).
    Left cursor:    Cycles through cameras in descending order
    Right cursor:   Cycles through cameras in ascending order
    1-4:            Typing a camera number will start/stop recording that camera.

This program also monitors GPIO pins 4-7, which can start/stop recording and also tabulate behavioral trial starts.
See details below under "GPIO PROTOCOL".

Each camera recording generates the following three files:

    YYYY-MM-DD_HHmm_CamX_AnimalID_Frames.txt        # Tab-delimited text file with timestamps of each video frame
    YYYY-MM-DD_HHmm_CamX_AnimalID_TTLs.txt          # Tab-delimited text file with timestamps of each TTL pulse
    YYYY-MM-DD_HHmm_CamX_AnimalID_Video.avi         # Video file.

Where YYYY-MM-DD_HHmm is the date and time, X is the camera number, and
AnimalID is a value entered manually or transmitted via Med-PC using the GPIO/TTL input.

By default, the software records at 30 frames per second and 640x480 resolution, using the H264 codec.
These can be changed in the config.txt file (see next section below, "CONFIGURING").


# CONFIGURING:

Most default parameters (frame rate, codec, save directory) can be overridden using
a "config.txt" file. I've included two working examples called "config_example1" and
"config_example2". You can use either of them by copying them to "config.txt" and editing
to suit your own needs.

    config_example1      Comprehensive list of all configuration settings, with brief explanations.
    config_example2      Bare-bones file with commonly used options.

Changes to "config.txt" take effect only after restarting the program. Options include the following:

    RECORD_FRAME_RATE                      # Frame rate of recorded video. Default 30
    DATA_FOLDER                            # Folder for saving. Default /home/jhoulab/Videos/
    RESOLUTION                             # A string of the form (width,height), e.g. (640x480)
    FOURCC                                 # Recording codec. Default h264. Change to mp4v if needed to reduce CPU load.
    NUM_TTL_PULSES_TO_START_SESSION        # Number of pulses to start recording. Default 2
    NUM_TTL_PULSES_TO_STOP_SESSION         # Number of pulses to end recording. Default 3

The codec (specified by "FOURCC") can be one of the following:

    H264:  makes small files (<2MB per minute at 10fps) but is computationally demanding.
    MP4V:  is computationally less demanding, but files are 2-5x larger.


# GPIO TIMING PROTOCOL

This program monitors GPIO inputs 4 through 7, which corresponds to the following cameras:

    GPIO4:          camera 1
    GPIO5:          camera 2
    GPIO6:          camera 3
    GPIO7:          camera 4

Note that these are 3.3V inputs, so you must use a level shifter when reading 5V inputs.

A standard pulse should be 100ms long. If doubled or tripled, the trough between pulses should be 50ms.

    3.3V    100ms
             ___      ___      
            |   |    |   |    
    0V -----     ----     --------
                 50ms

All pulse onset timestamps are saved in the _TTL.txt file.

A single pulse indicates trial start, a double pulse starts recording, while a triple pulse stops recording.

Med-PC can transmit a binary animal ID via the TTL line. This consists of 18 pulses, the first of which must be 200ms long,
followed by 16 binary bits, a 200ms pause, and a final checksum parity bit. All binary bits, have duration 25ms to indicate
binary 0, and 75ms to indicate binary 1:

    3.3V     0.2s   <16 binary bits, 25/75ms>    <Parity bit 25/75ms>
             ____   _   _   _               _       _
            |    | | | | | | |    etc      | |     | |
    0V -----      -   -   -   -           -   -----   ---------------
                  <25ms troughs between bits> 200ms


Note that Windows timing can jitter by a modest amount, usually under 10ms but occasionally more.
Python code allows for 25ms of error in timing of binary bits,
and 50-100ms error elsewhere.



# KNOWN SHORTCOMINGS:

1. When launching, you will get the following harmless warning, which you can ignore:

    libpng warning: iCCP: known incorrect sRGB profile

2. Occasionally the last frame of video is dropped.

3. h264 files can be viewed in Fiji/ImageJ using FFMPEG plugin. However, FFMPEG plugin does not work on Raspberry Pi.
     A cumbersome workaround is to decompress video using:
     
         ffmpeg input.avi -c:v rawvideo output.avi


#  INSTALLING ON A NEW MACHINE:

To install on a new machine, follow these three steps:

### STEP 1: Clone the github repository.

  There are two ways to do this:

  #### Method 1: Easy, but is read-only, i.e. you won't be able to upload changes to Github.
  Open a command prompt, use "cd" to select a destination directory, then type:
    
    git clone https://github.com/JhouLab/Pi5WebcamRecorder

  Now go to STEP 2.


  #### Method 2: Harder, but gives you to ability to upload changes to the lab account
  Download Github Desktop from these instructions:
  https://pi-apps.io/install-app/install-github-desktop-on-raspberry-pi/

  To summarize the above, first install Pi-Apps:

    wget -qO- https://raw.githubusercontent.com/Botspot/pi-apps/master/install | bash

  Launch Pi-Apps, select "Programming", then "Github Desktop" (the purple cat icon), and
  then click the "Install" button. When done, launch Github from the main Raspberry Pi menu, under
  "Accessories", then log into the lab github account.

  Now, select "File", "Clone repository", "Github.com", then JhouLab/Pi5WebcamRecorder

## STEP 2: Install OpenCV.
  Instructions for installing it on a Pi5 are here:
  https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html

  I happened to use method #2 in the link above, using the following commands:

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


After that, everything should run. If so, CONGRATULATIONS. If not, please email jhoulab1@gmail.com for help.
