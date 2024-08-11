
# HOW TO USE:

Instructions version 1.4.1

Updated Aug 3, 2024.

For best results, run on a Raspberry Pi 5, which can handle 4 simultaneous cameras
at 640x480 and 30 frames per second.


# GETTING STARTED:

If not already installed, see instructions below: "Installing on a new machine"

On most JhouLab computers, program will install in the following folder:

    /home/jhoulab/Documents/github/Pi5WebcamRecorder

By default, videos are saved to the program directory, but it is highly recommended
you change this to something larger, like an external drive. You can specify this
by editing config.txt (see CONFIGURING section below).

To launch the program, use one of the following methods:

    Method 1: From command line (must be in program folder):

      python -m RUN_AS_ROOT

    Method 2: From Thonny (Pi's pre-installed Python IDE).
      Click "Load", select RUN_AS_ROOT.py,
      then click "Run" (green button with white triangle).


Upon launch, program scans for USB cameras, then displays them in a 2x2 grid.
The position in the grid matches the the physical USB port position, as shown below:

    -------------
    |  1  |  2  |
    -------------
    |  3  |  4  |
    -------------

The program is controlled from the control bar at the top of the screen. You can
also use keyboard shortcuts:

    "Q":            Quits program. (Any ongoing records will also be stopped).
    Left cursor:    Cycles through cameras in descending order
    Right cursor:   Cycles through cameras in ascending order
    1-4:            Typing a camera number will start/stop recording that camera.

This program also monitors GPIO pins 4, 5, 6, and 7. TTL pulses on these pins can
start/stop recording, transmit the animal ID, and also timestamp behavioral events.
See details below under "GPIO PROTOCOL".

Each camera recording generates the following three files:

    YYYY-MM-DD_HHmm_CamX_AnimalID_Frames.txt        # Tab-delimited text file with timestamps of each video frame
    YYYY-MM-DD_HHmm_CamX_AnimalID_TTLs.txt          # Tab-delimited text file with timestamps of each TTL pulse
    YYYY-MM-DD_HHmm_CamX_AnimalID_Video.avi         # Video file.

In these files, YYYY-MM-DD_HHmm is the date and time, X is the camera number, and
AnimalID is entered manually or transmitted via GPIO/TTL inputs.

By default, video is recorded at 30 frames per second and 640x480 resolution, using the H264 codec.
These can be changed in the config.txt file (see next section below, "CONFIGURING").


# CONFIGURING:

Most default parameters (frame rate, codec, save directory) can be overridden using
a "config.txt" file. I've included two working examples:

    config_example1     This is a detailed file listing all possible configuration options
    config_example2     A bare-bones file that has only the most commonly used options.

You can use either of them by copying them to "config.txt" and editing to suit your own needs.
Changes to "config.txt" take effect only after restarting the program. Options include the following:

    RECORD_FRAME_RATE                      # Frame rate of recorded video. If not specified, defaults to camera's native frame rate
    NATIVE_FRAME_RATE                      # Native frame rate of webcam. If not specified, will be auto-detected.
    DATA_FOLDER                            # Folder for saving. If not specified, defaults to program directory.
    RESOLUTION                             # A string of the form (width,height), e.g. (640x480)
    FOURCC                                 # Recording codec. Default h264 which gives smallest file sizes. Change to mp4v if needed to reduce CPU load.
    NUM_TTL_PULSES_TO_START_SESSION        # Number of consecutive TTL pulses to start recording. Default 2
    NUM_TTL_PULSES_TO_STOP_SESSION         # Number of consecutive TTL pulses to end recording. Default 3


# GPIO TIMING PROTOCOL

This program monitors GPIO inputs 4 through 7, which corresponds to the following cameras:

    GPIO4:          camera 1
    GPIO5:          camera 2
    GPIO6:          camera 3
    GPIO7:          camera 4

These are 3.3V inputs, so you must use a level shifter when connecting to 5V devices.
A standard pulse should be 100ms long. To deliver consecutive pulses (to start or stop recordings),
the pause between pulses should be no longer than 50ms. For example, the following pulse sequence
will initiate a recording:

    3.3V    100ms  100ms
             ___    ___      
            |   |  |   |    
    0V -----     --     --------
                50ms

Pulse onset/offset timestamps are saved to the *_TTL.txt file.

Med-PC can transmit a binary animal ID via the TTL line. This consists of the following sequence of events:

1. 200ms high pulse to initiate binary ID transmission
2. 16 binary bits. Least significant bit is first. 50ms duration indicates "0", 150ms duration indicates "1". 50ms low period between each bit
3. 200ms low period
4. final checksum parity bit: 50ms duration if there are an odd number of "1"s in ID, 150ms duration if odd number

Graphically, this looks like the following:

    3.3V    200ms    <16 binary bits, 50/150ms>     <Parity bit 50/150ms>
             ____   _   _   _                   _       _
            |    | | | | | | |    .. etc..     | |     | |
    0V -----      -   -   -   -               -   -----   ---------------
                 50ms low period between bits     200ms


Python code allows for 50ms of error in timing of binary bits. In practice, errors this large are
rare if program is run as root (which allows program to elevate its own priority above most other
processes on the Raspberry Pi).



# KNOWN SHORTCOMINGS:

1. The last frame of video may not record. This appears to be a bug in FFMPEG, which is used by
   OpenCV.

2. ImageJ/FIJI is a handy way to quickly view files on Windows, provided you install the
   FFMPEG plugin. But on the Raspberry Pi does not appear able to correctly use this plugin.
   A cumbersome way to use is to decompress video using:
     
         ffmpeg input.avi -c:v rawvideo output.avi


#  INSTALLING ON RASPBERRY PI 5:

To install, follow these three steps:

### STEP 1: Clone the github repository.

  There are two ways to do this:

  #### Method 1: Easy, but is read-only, i.e. you won't be able to upload changes to Github.
  Open a command prompt, use "cd" to select a destination directory, then type:
    
    git clone https://github.com/JhouLab/Pi5WebcamRecorder

  #### Method 2: Harder, but gives you to ability to upload changes to the lab account
  Download Github Desktop from these instructions:
  https://pi-apps.io/install-app/install-github-desktop-on-raspberry-pi/

  To summarize the above, first install Pi-Apps:

    wget -qO- https://raw.githubusercontent.com/Botspot/pi-apps/master/install | bash

  Launch Pi-Apps, select "Programming", then "Github Desktop" (the purple cat icon), and
  then click "Install". When it's done, launch Github from the main Raspberry Pi menu, under
  "Accessories", then log into the lab github account.

  Now, select "File", "Clone repository", "Github.com", then JhouLab/Pi5WebcamRecorder

  Github Desktop only works correctly on Pis running 64-bit os. If you are running a 32-bit
  os, it may still install, but graphics will be weird and unusable.

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


If the above does not work, please email jhoulab1@gmail.com for help.

