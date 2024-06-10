#
# This file is intended to be imported by webcam_recorder.py
#
# It mainly contains the CamObj class, which helps manage independent
# USB cameras.


import os
import numpy as np
import datetime
import time
import platform
import threading


if platform.system() == "Linux":
    import RPi.GPIO as GPIO

FRAME_RATE_PER_SECOND = 10

FOURCC = 'h264'  # Very efficient compression, but CPU intensive. Total frame rate across all cameras should not exceed about 50
# FOURCC = 'mp4v' # MPEG-4 compression is faster, allowing higher frame rates (>200fps across all cameras), but files will be 5-10x larger

#
# Note: h264 codec comes with OpenCV on Linux/Pi, but not Windows
# Under Windows, download .DLL file here: https://github.com/cisco/openh264/releases
# Note that if you have an older version of OpenCV, you may need an older h264 dll.
# As of 6/8/2024, current h264 dll is version 2.4, but on Windows we need version 1.8.
# Strangely, Windows h264 (version 1.8) is much less space efficient than Linux version
# (~4MB/min versus 1-2MB/min).
#

# Resolution
WIDTH = 640
HEIGHT = 480

os.environ["OPENCV_LOG_LEVEL"] = "FATAL"  # Suppress warnings when camera id not found

# Must install OpenCV.
#
# On Pi5, instructions for installing OpenCV are here:
#   https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html
#
#   The following two lines worked for me on Pi5:
#     sudo apt-get install libopencv-dev
#     sudo apt-get install python3-opencv
# 
# In Pycharm, install the following from Settings/<ProjectName>/Python interpreter:
#   opencv-python (github.com/opencv/opencv-python)
#
# In VSCode, install from terminal. If you have only one version of
#   python on your machine, you can use: py -m pip install opencv-python.
#   If multiple installations, must pick the correct one, e.g.:
#   c:/users/<user>/AppData/Local/Microsoft/WindowsApps/python3.11.exe -m pip install opencv-python 
import cv2


def get_date_string():
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    hour = '{:02d}'.format(now.hour)
    minute = '{:02d}'.format(now.minute)
    day_month_year = '{}-{}-{}_{}{}'.format(year, month, day, hour, minute)

    return day_month_year


def make_blank_frame(txt):
    tmp = np.zeros((HEIGHT, WIDTH, 3), dtype="uint8")
    cv2.putText(tmp, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
    return tmp


class CamObj:
    cam = None
    id_num = -1  # ID number assigned by operating system. May be unpredictable.
    order = -1  # User-friendly camera ID. Will usually be USB port position, and also position on screen
    status = -1  # True if camera is operational and connected
    frame = None  # Most recently obtained video frame. If camera lost connection, this will be a black frame with some text
    filename = "Video.avi"
    filename_timestamp = "Timestamp.txt"
    filename_timestamp_TTL = "Timestamp_TTL.txt"

    # Various file writer objects
    Writer = None    # Writer for video file
    fid = None       # Writer for timestamp file
    fid_TTL = None   # Writer for TTL timestamp file

    start_time = -1  # Timestamp when recording started.
    IsRecording = False
    GPIO_pin = -1    # Which GPIO pin corresponds to this camera? First low-high transition will start recording.

    frame_num = -1   # Number of frames recorded so far.
    TTL_num = -1
    most_recent_gpio_time = -1

    codec = cv2.VideoWriter_fourcc(*FOURCC)  # What codec to use. Usually h264
    resolution = (WIDTH, HEIGHT)

    lock = threading.RLock()  # Reentrant lock, so same thread can acquire more than once.

    def __init__(self, cam, id_num, order, GPIO_pin=-1):
        self.cam = cam
        self.id_num = id_num
        self.order = order
        self.GPIO_pin = GPIO_pin
        if cam is None:
            # Use blank frame for this object if no camera object is specified
            self.frame = make_blank_frame(f"{order} - No camera found")

        if GPIO_pin >= 0 and platform.system() == "Linux":
            # Start monitoring GPIO pin
            GPIO.add_event_detect(GPIO_pin, GPIO.RISING, callback=self.GPIO_callback)

    def GPIO_callback(self, param):

        # Detected rising edge of GPIO

        # Record timestamp now, in case there are delays acquirig lock
        gpio_time = time.time()
        if gpio_time - self.most_recent_gpio_time < 0.001:
            # Ignore GPIOs that are less than 1ms apart. These are usually mechanical switch bounces
            return
        
        self.most_recent_gpio_time = gpio_time

        # Because this function is called from the GPIO callback thread, we need to
        # acquire lock to make sure there aren't any main thread functions that are
        # also accessing the same variables being accessed here.
        with self.lock:

            if not self.IsRecording:
                # If not recording, then first TTL starts recording.
                if not self.start_record():
                    # Start recording failed, so don't record TTLs
                    print(f"Unable to start recording camera {self.order} in response to GPIO input")
                    return
                else:
                    print(f"Started recording camera {self.order} in response to GPIO input")

                if not self.IsRecording:
                    # Not recording video, so don't save TTL timestamps
                    print("Hmmm, something seems wrong, GPIO recording didn't start after all. Please contact developer.")

                # If we just started recording, don't record very first TTL timestamp, since it is superfluous
                # and will actually have a slightly negative value anyway
                return

            gpio_time_relative = gpio_time - self.start_time

            self.TTL_num += 1
            if self.fid_TTL is not None:
                try:
                    self.fid_TTL.write(f"{self.TTL_num}\t{gpio_time_relative}\n")
                except:
                    print(f"Unable to write TTL file for camera {self.order}")
            else:
                print(f"Unable to write TTL timestamp for camera {self.order}")

    def get_filename_prefix(self):
        return get_date_string() + f"_Cam{self.order}"

    def start_record(self):

        if self.cam is None or not self.cam.isOpened():
            print(f"Camera {self.order} is not available for recording.")
            return False

        # Because this function might be called from the GPIO callback thread, we need to
        # acquire lock to make sure it isn't also being called from the main thread.
        with self.lock: 
            if not self.IsRecording:
                self.frame_num = 0
                self.TTL_num = 0

                prefix = self.get_filename_prefix()
                self.filename = prefix + "_Video.avi"
                self.filename_timestamp = prefix + "_Timestamp.txt"
                self.filename_timestamp_TTL = prefix + "_Timestamp_TTL.txt"

                try:
                    # Create video file
                    self.Writer = cv2.VideoWriter(self.filename, self.codec, FRAME_RATE_PER_SECOND, self.resolution)
                except:
                    print("Warning: unable to create video file")
                    return False

                if not self.Writer.isOpened():
                    # If codec is missing, we might get here. Usually OpenCV will have reported the error already.
                    print("Warning: unable to create video file")
                    return False

                try:
                    # Create text file for frame timestamps
                    self.fid = open(self.filename_timestamp, 'w')
                    self.fid.write('Frame_number\tTime_in_seconds\n')
                except:
                    print("Warning: unable to create text file for frame timestamps")
                    
                    # Close the previously-created writer objects
                    self.Writer.release()
                    return False

                try:
                    # Create text file for TTL timestamps
                    self.fid_TTL = open(self.filename_timestamp_TTL, 'w')
                    self.fid_TTL.write('TTL_event_number\tTime_in_seconds\n')
                except:
                    print("Warning: unable to create text file for TTL timestamps")
                    
                    # Close the previously-created writer objects
                    self.fid.close()
                    self.Writer.release()
                    return False

                self.IsRecording = True
                self.start_time = time.time()
                return True

    def stop_record(self):

        # Close and release all file writers

        with self.lock:
            
            if self.IsRecording:
                print(f"Stopping recording camera {self.order}")
                self.print_elapsed()

                self.IsRecording = False
                
            if self.Writer is not None:
                try:
                    # Close Video file
                    self.Writer.release()
                except:
                    pass
                self.Writer = None
            if self.fid is not None:
                try:
                    # Close text timestamp file
                    self.fid.close()
                except:
                    pass
                self.fid = None
            if self.fid_TTL is not None:
                try:
                    # Close text timestamp file
                    self.fid_TTL.close()
                except:
                    pass
                self.fid_TTL = None


    # Reads a single frame from CamObj class
    def read(self):

        if self.cam is not None and self.cam.isOpened():
            try:
                # Read frame if camera is available and open
                self.status, self.frame = self.cam.read()

                if not self.cam.isOpened():

                    if self.IsRecording:
                        self.stop_record()  # Close file writers

                    self.frame = make_blank_frame(f"{self.order} Camera lost connection")
                    print(f"Unable to read video from camera with ID {self.order}. Will remove camera from available list.")

                    # Remove camera resources
                    self.cam.release()
                    self.cam = None

            except:
                # Read failed. Remove this camera so we won't attempt to read it later.
                # Should we set a flag to try to periodically reconnect?

                self.stop_record()  # Close file writers

                self.cam = None
                self.status = 0
                self.frame = make_blank_frame(f"{self.order} Camera lost connection")

                # Warn user that something is wrong.
                print(
                    f"Unable to read frames from camera ID #{self.id_num}. Will stop recording and display.")

                # Warn user that something is wrong.
                print(f"Unable to read camera {self.order}. Will stop recording and display.")

                return

            if self.Writer is not None and self.frame is not None and self.IsRecording:
                if self.fid is not None and self.start_time > 0:
                    # Write timestamp to text file. Do this before writing AVI so that
                    # timestamp will not be delayed by latency required to compress video. This
                    # ensures most accurate possible timestamp.
                    try:
                        time_elapsed = time.time() - self.start_time
                        self.fid.write(f"{self.frame_num}\t{time_elapsed}\n")
                    except:
                        print(f"Unable to write text file for camera f{self.order}. Will stop recording")
                        self.stop_record()

                self.frame_num += 1

                try:
                    # Write frame to AVI video file if possible
                    self.Writer.write(self.frame)
                except:
                    print(f"Unable to write video file for camera {self.order}. Will stop recording")
                    self.stop_record()

            return self.status, self.frame
        else:
            # Camera is not available.
            return 0, None

    def print_elapsed(self):
        elapsed_sec = self.frame_num / FRAME_RATE_PER_SECOND
        if elapsed_sec < 120:
            print(f"   Camera {self.order} elapsed: {elapsed_sec:.0f} seconds, {self.frame_num} frames")
        else:
            elapsed_min = elapsed_sec / 60
            print(f"   Camera {self.order} elapsed: {elapsed_min:.1f} minutes, {self.frame_num} frames")

    def take_shapeshot(self):
        if self.cam is None or self.frame is None:
            return
        if self.cam.isOpened():
            fname = self.get_filename_prefix() + "_snapshot.jpg"
            cv2.imwrite(fname, self.frame)

    def close(self):

        # Only call this when exiting program. Will stop all recordings, and release camera resources

        self.stop_record()
        if self.cam is not None:
            try:
                # Release camera resources
                self.cam.release()
            except:
                pass
            self.cam = None

        self.status = -1
        self.frame = None
        
if __name__ == '__main__':
    print("CamObj.py is a helper file, intended to be imported from WEBCAM_RECORD.py, not run by itself")
