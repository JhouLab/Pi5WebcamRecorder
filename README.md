
# HOW TO USE:

First, make sure you are running this on a Raspberry Pi 5.
While the code will (sort of) work on a Pi 4, performance will be noticeably worse.

Hopefully you are working on a machine where someone has already installed all needed
files and libraries. If not, skip to the bottom "Installing on a new machine",
then come back here when you are done.

Locate the directory where the program resides. If not sure, look here first:
/home/jhoulab/Documents/github/Pi5WebcamRecorder

Now launch the program. There are three ways to do this:

    Method 1: For beginners. From command line, cd to the program directory, then type:
    python -m WEBCAM_RECORD

    Method 2: For intermediate users. Open Thonny (Pi's built-in Python IDE). Open
    WEBCAM_RECORD.py, then run it with the triangle "Run" button. Can also use the "Debug"
    button, which is helpful when coding.

    Method 3: For advanced users. Install PyCharm CE by first installing Pi-Apps, and using
    Pi-Apps to install PyCharm CE. This gives you a much more powerful debugger, albeit with
    a much steeper learning curve.

Upon launch, it will scan the system for up to 4 connected USB cameras, then display them
in a 2x2 grid. The position in the grid matches the position of the physical USB port.
For example, any camera plugged into the top-left USB port will show up in the top left of
the 2x2 grid. The cameras are numbered 0-3, in the following order:

    -------------
    |  0  |  1  |
    -------------
    |  2  |  3  |
    -------------

Once running, it will respond to the following keyboard keys:

    "Q":            Typing this stops any ongoing recordings, and quits the program
    Left cursor:    Cycles through cameras in descending order
    Right cursor:   Cycles through cameras in ascending order
    0-3:            Typing a camera number will manually start/stop recording of that camera.
                    A red dot appears in the corner to indicate ongoing recording.

This program also monitors GPIO pins 4-7. A low-to-high transition (i.e. from 0V to 3.3V)
on the following pins has the following effects:

    GPIO4:          Starts recording camera 0
    GPIO5:          Starts recording camera 1
    GPIO6:          Starts recording camera 2
    GPIO7:          Starts recording camera 3

(If you are wondering why I avoided GPIO pins 0-3, it is because they are used for I2C communications.)

Each recording generates 3 files: one for video, a second for timestamps of
individual video frames, and a third for timestamps of low-to-high GPIO transitions, which
indicate behavior cue onset times.

Each camera has completely separate files, and there is no data mixing between cameras/files.
Each filename begins with the date in YYYY-MM-DD_HHMM format, followed by the camera number.
For example, camera 0, recorded on June 9, 2024 at 5:38pm, generates these 3 files:

    2024-06-09_1738_Cam0_Video.avi              # Video file in H264 format
    2024-06-09_1738_Cam0_Timestamp.txt          # Text file with timestamps of each video frame
    2024-06-09_1738_Cam0_Timestamp_TTL.txt      # Text file with timestamps of low-to-high TTL transitions, representing trial cue onsets

Note there are separate text files for video frame timestamps and GPIO timestamps.

The H264 format achieves remarkably high compression ratios, with files typically <2MB per minute.
Some example estimated storage requirements are as follows (your mileage may vary):

    1 GB:     About 8 hours (or more) of continuous recording.
    1 TB:     About 3 months of continuous 24/7 recording from 4 cameras
    1 TB:     About 1 year of continuous 24/7 recording from 1 camera
    1 TB:     About 3 years when recording two 1-hour sessions per day from 4 animals (i.e. 8 total hours/day)

Basic video parameters are as follows:

    Frames per second: 10                # Set on line 19 of CamObj.py file
    Codec: h264                          # Set on line 21 of CamObj.py
    Pixel resolution: 640x480            # Set on lines 34-35 of CamObj.py file

Max resolution and frame rate are limited by the CPU's ability to compress to h264 format. If you need
more resolution or higher frame rate, you can switch from h264 to mp4v format (MPEG-4) which is faster, but
has poorer compression ratio and requires ~5x more disk space.

This program is intended to run on a Raspberry Pi 5. It will (sort of) run on a Pi 4, but performance is frustratingly
poor if you have more than 1 camera. This program also runs (sort of) under Windows, but it lacks the ability to
distinguish which USB port is which, meaning camera position will be somewhat random. Strangely, the Windows H264 encoder
(from Cisco systems, v1.8) also achieves much worse compression ratios than the Pi version.


# KNOWN SHORTCOMINGS:

1. There is currently no way to specify what folder to save files go. All files go to the
same folder as the program itself.

2. When launching, you will get a bunch of warnings: "libpng warning: iCCP: known incorrect sRGB profile".
I have no idea how to get rid of them, and I definitely tried.

3. Currently, GPIO pins can remotely start a recording, but they cannot stop it. You have to
manually stop the recording by typing the camera number.

4. The video frame timestamp is when the frame was READ by the Python code, but the actual pixel data was likely
CAPTURED from the camera sensor up to 70ms earlier. It is then stored in an internal buffer until the Pi reads
it. For more accurate timestamps, we need to subtract the delay from capture to read, but I haven't done this yet.


#  INSTALLING ON A NEW MACHINE:


Hopefully you are using a machine where someone has already installed everything for you. If not, please
follow these three steps:

### STEP 1: Clone the github repository.

  There are two ways to do this:

  #### Method 1: Easy, but you won't be able to upload changes to Github.
  Open a command prompt, then type:
    
    git clone https://github.com/JhouLab/Pi5WebcamRecorder

  Now go to STEP 2.

  #### Method 2: Harder, but gives you to ability to upload changes to the lab account
  This is essential to fix bugs or add features. First download Github Desktop for Raspberry Pi from these instructions:
  https://pi-apps.io/install-app/install-github-desktop-on-raspberry-pi/

  In a nutshell, you first need to install Pi-Apps using this command:

    wget -qO- https://raw.githubusercontent.com/Botspot/pi-apps/master/install | bash

  Then launch Pi-Apps, select "Programming", then "Github Desktop", which is the purple cat icon, and
  then click the button to install Github Desktop. Now launch it from the main Raspberry Pi menu, under
  "Accessories", then log into the lab github account with jhoulab1@gmail.com as username and standard password.

  Now, select "File", "Clone repository", then "Github.com", then JhouLab/Pi5WebcamRecorder

## STEP 2: Install OpenCV.
  Instructions for installing it on a Pi5 are here:
  https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html

  (I happened to use method #2 in the link above, but the others will likely work also)

## STEP 3: Install rpi-lpgio
  Annoyingly, the Pi5 uses different GPIO hardware than the Pi4, which is not compatible with the
  default GPIO library RPi.GPIO. There are several workarounds, but the simplest is to uninstall the
  standard library and install python3-rpi-lpgio, a drop-in replacement:

    sudo apt remove  python3-rpi.gpio
    sudo apt install python3-rpi-lgpio


After that, everything should run. If so, CONGRATULATIONS. If not, please email tjhou@som.umaryland.edu for help.
