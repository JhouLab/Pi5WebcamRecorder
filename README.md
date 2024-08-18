
# HOW TO USE:

Instructions version 1.5

Updated Aug 18, 2024.

For best results, run on a Raspberry Pi 5, which is much faster than the Pi 4. It
can handle 4 simultaneous cameras at 640x480 and 30 frames per second.

If you have problems, questions, or suggestions, please email jhoulab1@gmail.com

# GETTING STARTED:

On most JhouLab computers, the program is in the following folder:

    /home/jhoulab/Documents/github/Pi5WebcamRecorder

If you need to install on a new machine, skip to the botton section on this page: "Installing on a new machine"

Launch the program with one of the following methods:

    Method 1: From command line (must be in program folder):

      python -m RUN_AS_ROOT

    Method 2: From Thonny (Pi's pre-installed Python IDE).
      Click "Load", select RUN_AS_ROOT.py,
      then click "Run" (green button with white triangle).

Upon launch, program displays USB cameras in a 2x2 grid, where the grid position matches
the physical USB port position:

    -------------
    |  1  |  2  |
    -------------
    |  3  |  4  |
    -------------

You can start/stop recording from the GUI, from external 3.3V logic (see "GPIO PROTOCOL" seciont below),
or with keyboard shortcuts:

    1-4:            Typing a camera number will start/stop recording that camera.
    Left cursor:    Cycles through cameras in descending order
    Right cursor:   Cycles through cameras in ascending order
    "Q":            Quits program. (Any ongoing records will also be stopped).

By default, videos saved to the program directory, but it is recommended to
change this to an external drive, to avoid filling up your SD card. Specify drive path by editing config.txt
(see CONFIGURING section below). Default format is 640x480, 30fps, with h264 encoding. These can also be
changed in config.txt.

Each recording generates three files:

    YYYY-MM-DD_HHmm_CamX_AnimalID_Video.avi         # Video file in h264 format.
    YYYY-MM-DD_HHmm_CamX_AnimalID_Frames.txt        # Tab-delimited text file with timestamps of each video frame
    YYYY-MM-DD_HHmm_CamX_AnimalID_TTLs.txt          # Tab-delimited text file with timestamps of each TTL pulse

Where YYYY-MM-DD_HHmm is the date and time, X is the camera number, and AnimalID is entered
manually or transmitted via GPIO logic inputs.

# CONFIGURING:

Many default parameters can be changed using a "config.txt" file. I've included two working examples:

    config_example1     A detailed file with all possible configuration options
    config_example2     A bare-bones file with only the most commonly used options.

To use either file, open it in any text editor, rename it to "config.txt", then edit to suit your needs.
Changes to "config.txt" take effect only after restarting the program. Options include the following:

    RECORD_FRAME_RATE                      # Frame rate of recorded video. If not specified, defaults to camera's native frame rate, typically 30fps
    NATIVE_FRAME_RATE                      # Native frame rate of webcam. If not specified, will be auto-detected.
    DATA_FOLDER                            # Folder for saving. If not specified, defaults to program directory.
    RESOLUTION                             # A string of the form: (width,height), e.g. (640x480)
    FOURCC                                 # Recording codec. Default h264 which gives smallest file sizes. Can also use mp4v, which is less CPU intensive, but gives larger files


# GPIO TIMING PROTOCOL

Pi5WebcamRecorder monitors GPIO inputs 4 through 7, corresponding to the following cameras:

    GPIO4:          camera 1
    GPIO5:          camera 2
    GPIO6:          camera 3
    GPIO7:          camera 4

These are 3.3V inputs, so you must use a level shifter when connecting to 5V devices. In our lab, we
use Med-PC running on a Windows machine to generate TTLs. Since those are 28V signals, they require an additional
level shifter to convert from 28V to 5V.

Timing accuracy must be within 50ms. Since neither Windows nor Linux
are real-time operating systems, this technically cannot be guaranteed. However, Med-PC is generally accurate
to just a few milliseconds, while the Pi5Recorder runs in high priority in superuser mode, which also reduces
timing errors. So in practice, timing errors are not an issue, even though they could theoretically cause glitches.

A standard pulse should be 100ms long. A double pulse will start a recording, and consists of two standard
pulses with a 50ms pause in between:

    3.3V    100ms  100ms
             ___    ___      
            |   |  |   |    
    0V -----     --     --------
                50ms

Once a session is started, three consecutive pulses will stop the recording. (Again, pulses are 100ms with 50ms pauses).

If an animal IDs was transmitted prior to recording start, it will show up in the filename. ID transmission is graphically
represented below:

    3.3V    200ms    <16 binary bits, 50/150ms>     <Parity bit 50/150ms>
             ____   _   _   _                   _       _
            |    | | | | | | |    .. etc..     | |     | |
    0V -----      -   -   -   -               -   -----   ---------------
                 50ms low period between bits     200ms

The sequence of events is as follows:

1. 200ms high pulse
2. 16 binary bits, with least significant bit first, where 50ms duration indicates "0" and 150ms duration indicates "1". Gap between pulses is 50ms
3. 200ms low period
4. Checksum parity bit: 50ms duration if ID had an even number of "1"s, 150ms duration if odd



# KNOWN SHORTCOMINGS:

1. The last frame of video may not record. This appears to be a bug in FFMPEG, which OpenCV uses.

2. ImageJ/FIJI is a handy way to quickly view files on Windows, but this does not appear
   to work on the Raspberry Pi, again due to issues with FFMPEG. A cumbersome workaround is to decompress video using:
     
         ffmpeg input.avi -c:v rawvideo output.avi


#  INSTALLING ON RASPBERRY PI 5:

To install, follow these three steps:

### STEP 1: Clone the github repository.

  There are two ways to do this:

  #### Method 1: From command prompt, gives a read-only copy:
    
    git clone https://github.com/JhouLab/Pi5WebcamRecorder

  #### Method 2: Using Github Desktop: https://pi-apps.io/install-app/install-github-desktop-on-raspberry-pi/

  First install Pi-Apps:

    wget -qO- https://raw.githubusercontent.com/Botspot/pi-apps/master/install | bash

  Launch Pi-Apps, select "Programming", "Github Desktop" (the purple cat icon), and
  click "Install". It will take a couple of minutes. Then launch Github from the main Raspberry Pi menu,
  under "Accessories", then log into the lab github account. Then select "File",
  "Clone repository", "Github.com", "JhouLab/Pi5WebcamRecorder":

  Github Desktop only works on Pis running a 64-bit os. If you are running a 32-bit
  os, it may still install, but graphics will be weird and unusable.

## STEP 2: Install OpenCV.

  On the Pi5 command prompt, type the following:

    sudo apt-get install libopencv-dev
    sudo apt-get install python3-opencv

  As of 6/12/2024, this installs OpenCV version 4.6.0, which is slightly outdated (released 6/12/2022),
  but works well enough. For other ways to install OpenCV, see here:
  https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html

## STEP 3: Install rpi-lpgio
  Annoyingly, the Pi5 uses different GPIO hardware than the Pi4, but they didn't bother to update the
  default GPIO library. To work around this, unstall the standard library and install python3-rpi-lpgio,
  a drop-in replacement:

    sudo apt remove  python3-rpi.gpio
    sudo apt install python3-rpi-lgpio

