#
# This file is intended to be imported by webcam_recorder.py
#
# It mainly contains the CamObj class, which helps manage independent
# USB cameras.


import os
import numpy as np
import datetime
import time

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
    filename_timestamp = "Timestamp.avi"
    Writer = None
    fid = None
    start_time = -1  # Timestamp when recording started.
    IsRecording = False

    frame_num = -1  # Number of frames recorded so far.
    codec = cv2.VideoWriter_fourcc(*FOURCC)  # What codec to use. Usually h264
    resolution = (WIDTH, HEIGHT)

    def __init__(self, cam, id_num, order):
        self.cam = cam
        self.id_num = id_num
        self.order = order
        if cam is None:
            self.frame = make_blank_frame(str(order) + " - No camera found")

    def start_record(self):

        if self.cam is None or not self.cam.isOpened():
            print("Camera " + str(self.order) + " is not available for recording.")
            return False

        if not self.IsRecording:
            self.frame_num = 0

            self.filename = get_date_string() + "_Cam" + str(self.order) + "_Video.avi"
            self.filename_timestamp = get_date_string() + "_Cam" + str(self.order) + "_Timestamp.txt"

            try:
                # Create video file
                self.Writer = cv2.VideoWriter(self.filename, self.codec, FRAME_RATE_PER_SECOND, self.resolution)
            except:
                print("Warning: unable to create video and/or text file")
                return False

            if not self.Writer.isOpened():
                # If codec is missing, we might get here
                print("Warning: unable to create video and/or text file")
                return False

            try:
                # Create text file
                self.fid = open(self.filename_timestamp, 'w')
                self.fid.write('Frame\tTime_in_seconds\tInterval\n')
            except:
                print("Warning: unable to create text file")
                return False

            self.IsRecording = True
            self.start_time = time.time()
            return True

    def stop_record(self):

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

    # Reads a single frame from CamObj class
    def read(self):
        if self.cam is not None and self.cam.isOpened():
            try:
                old_status = self.status
                # Read frame if camera is available and open
                self.status, self.frame = self.cam.read()

                if not self.cam.isOpened():
                    self.frame = make_blank_frame(str(self.order) + " Camera lost connection")
                    print("Unable to read camera ID " + str(self.order) + ". Will stop recording and display.")
                    self.stop_record()
                    # Remove camera resources
                    self.cam.release()
                    self.cam = None

            except:
                # Read failed. Remove this camera so we won't attempt to read it later.
                # Should we set a flag to try to periodically reconnect?
                self.cam = None
                self.status = 0
                self.frame = make_blank_frame(str(self.order) + " Camera lost connection")

                # Warn user that something is wrong.
                print(
                    "Unable to read frames from camera ID #" + str(self.id_num) + ". Will stop recording and display.")

                # Warn user that something is wrong.
                print("Unable to read camera " + str(self.order) + ". Will stop recording and display.")

                self.stop_record()
                return

            if self.Writer is not None and self.frame is not None and self.IsRecording:
                if self.fid is not None and self.start_time > 0:
                    # Write timestamp to text file. Do this before writing AVI so that
                    # timestamp will not include latency required to compress video. This
                    # ensures most accurate possible timestamp.
                    try:
                        self.fid.write(str(self.frame_num) + "\t" + str(time.time() - self.start_time) + "\n")
                    except:
                        print("Unable to write text file for camera " + str(self.order) + ". Will stop recording")
                        self.stop_record()

                self.frame_num += 1

                try:
                    # Write frame to AVI video file if possible
                    self.Writer.write(self.frame)
                except:
                    print("Unable to write video file for camera " + str(self.order) + ". Will stop recording")
                    self.stop_record()

            return self.status, self.frame
        else:
            # Camera is not available.
            return 0, None

    def close(self):

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
