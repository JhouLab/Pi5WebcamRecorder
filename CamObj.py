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
from sys import gettrace
import configparser

if platform.system() == "Linux":
    import RPi.GPIO as GPIO

os.environ["OPENCV_LOG_LEVEL"] = "FATAL"  # Suppress warnings that occur when camera id not found. This statement must occur before importing cv2

# This returns true if you ran the program in debug mode from the IDE
DEBUG = gettrace() is not None

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

configParser = configparser.RawConfigParser()
configFilePath = r'config.txt'
configParser.read(configFilePath)

DATA_FOLDER = configParser.get('options', 'DATA_FOLDER', fallback='')

if not (DATA_FOLDER.endswith("/") or DATA_FOLDER.endswith("\\")):
    DATA_FOLDER = DATA_FOLDER + "/"

FRAME_RATE_PER_SECOND = configParser.getint('options', 'FRAME_RATE_PER_SECOND', fallback=10)
HEIGHT = configParser.getint('options', 'HEIGHT', fallback=480)
WIDTH = configParser.getint('options', 'WIDTH', fallback=640)
if platform.system() == "Linux":
    FOURCC = configParser.get('options', 'FOURCC', fallback='h264')
else:
    # Note: h264 codec comes with OpenCV on Linux/Pi, but not Windows. Will default to using mp4v on
    # Windows. If you really want h264, there is a .DLL here: https://github.com/cisco/openh264/releases
    # but it has poor compression ratio, and doesn't always install anyway.
    FOURCC = configParser.get('options', 'FOURCC', fallback='mp4v')

MAX_INTERVAL_IN_TTL_BURST = configParser.getfloat('options', 'MAX_INTERVAL_IN_TTL_BURST', fallback=1.5)
NUM_TTL_PULSES_TO_START_SESSION = configParser.getint('options', 'NUM_TTL_PULSES_TO_START_SESSION', fallback=2)
NUM_TTL_PULSES_TO_STOP_SESSION = configParser.getint('options', 'NUM_TTL_PULSES_TO_STOP_SESSION', fallback=3)

FONT_SCALE = HEIGHT / 480


import datetime


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
    cv2.putText(tmp, txt, (int(10 * FONT_SCALE), int(30 * FONT_SCALE)), cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE, (255, 255, 255),
                round(FONT_SCALE + 0.5))   # Line thickness
    return tmp


class closer(threading.Thread):
    def __init__(self, cam_obj):
        threading.Thread.__init__(self)
        self.cam_obj = cam_obj

    def run(self):
        try:
            self.cam_obj.stop_record_thread()
        except:
            pass


filename_log = DATA_FOLDER + get_date_string() + "_log.txt"


try:
    # Create text file for frame timestamps
    fid_log = open(filename_log, 'w')
    print("Logging events to file: \'" + filename_log + "\'")
except:
    print("Unable to create log file: \'" + filename_log + "\'.\n  Please make sure folder exists and that you have permission to write to it.")


# Writes text to both screen and log file. The log file helps us retrospectively figure out what happened when debugging.
def printt(txt, omit_date_time=False, close_file=False):
    # Get the current date and time
    if not omit_date_time:
        now = datetime.datetime.now()

        s = now.strftime("%Y-%m-%d %H:%M:%S: ") + txt
    else:
        s = txt
    print(s)
    try:
        fid_log.write(s + "\n")
        fid_log.flush()
        if close_file:
            fid_log.close()
    except:
        pass



class CamObj:
    cam = None   # this is the opencv camera object
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
    num_consec_TTLs = 0   # Use this to track double and triple pulses

    codec = cv2.VideoWriter_fourcc(*FOURCC)  # What codec to use. Usually h264
    resolution = (WIDTH, HEIGHT)
    
    helper_thread = None  # This is used to close files without blocking main thread

    lock = None

    frames_to_mark_GPIO = 0    # Use this to add blue dot to frames when GPIO is detected
    pending_start_timer = 0    # This is used to show dark red dot temporarily while we are waiting to check if double pulse is actually double (i.e. no third pulse)

    def __init__(self, cam, id_num, order, GPIO_pin=-1):
        self.cam = cam
        self.id_num = id_num
        self.order = order
        self.GPIO_pin = GPIO_pin
        self.lock = threading.RLock()  # Reentrant lock, so same thread can acquire more than once.
        if cam is None:
            # Use blank frame for this object if no camera object is specified
            self.frame = make_blank_frame(f"{order} - No camera found")

        if GPIO_pin >= 0 and platform.system() == "Linux":
            # Start monitoring GPIO pin
            GPIO.add_event_detect(GPIO_pin, GPIO.RISING, callback=self.GPIO_callback)

    def GPIO_callback(self, param):

        self.handle_GPIO()

    def delayed_start(self):

        # This will wait a second to make sure no additional GPIOs occurred, then
        # will start recording video

        # This timer is used to temporarily show dark red dot while start is pending
        self.pending_start_timer = int(FRAME_RATE_PER_SECOND * 1.5)

        time.sleep(MAX_INTERVAL_IN_TTL_BURST)

        if self.num_consec_TTLs != NUM_TTL_PULSES_TO_START_SESSION:
            return

        if not self.start_record():
            # Start recording failed, so don't record TTLs
            print(f"Unable to start recording camera {self.order} in response to GPIO input")
            return

        if not self.IsRecording:
            # Not recording video, so don't save TTL timestamps
            print("Hmmm, something seems wrong, GPIO recording didn't start after all. Please contact developer.")

    def handle_GPIO(self):

        # Detected rising edge of GPIO

        # Record timestamp now, in case there are delays acquiring lock
        # time.time() returns number of seconds since 1970.
        gpio_time = time.time()

        # Calculate interval from previous pulse. This is used to detect double-pulses that indicate
        # session start/stop
        interval = gpio_time - self.most_recent_gpio_time

        if interval <= 0.001:
            # Ignore GPIOs less than 1ms apart. These are usually mechanical switch bounces, e.g. if
            # triggering manually by jumpering the GPIO pins.
            return

        if interval > MAX_INTERVAL_IN_TTL_BURST:
            # Long interval resets count of consecutive TTLs
            self.num_consec_TTLs = 1
        else:
            # Short interval increments count of consecutive TTLs
            self.num_consec_TTLs += 1
        
        self.most_recent_gpio_time = gpio_time

        # This is used to show blue dot on next frame. (Can increase this value to show on several frames)
        self.frames_to_mark_GPIO = 1

        # Because this function is called from the GPIO callback thread, we need to
        # acquire lock to make sure main thread isn't also accessing the same variables.
        # For example, if the main thread is in the midst of starting a recording, we need to
        # wait for that to finish, or else we might start the recording twice (with very
        # unpredictable results).
        with self.lock:

            if not self.IsRecording:

                if self.num_consec_TTLs == NUM_TTL_PULSES_TO_START_SESSION:

                    t = threading.Thread(target=self.delayed_start)

                    t.start()
                    
                    return

                # At this point, we originally were not recording, and we either attempted to start a session
                # or not, and we may or may not have succeeded.

                # Either way, we now return. The reason is that if we are not recording,
                # then there is no need to record timestamp. But if we did just start recording,
                # the very first TTL timestamp is also superfluous, and will have a negative value,
                # so we don't record that either.
                return

            # Calculate TTL timestamp relative to session start
            gpio_time_relative = gpio_time - self.start_time

            self.TTL_num += 1
            if self.fid_TTL is not None:
                try:
                    self.fid_TTL.write(f"{self.TTL_num}\t{gpio_time_relative}\n")
                except:
                    print(f"Unable to write TTL file for camera {self.order}")
            else:
                print(f"Unable to write TTL timestamp for camera {self.order}")

        # By now lock has been released, and we are guaranteed to be recording.

        if gpio_time_relative > 5.0 and self.num_consec_TTLs >= NUM_TTL_PULSES_TO_STOP_SESSION:
            # Double pulses are pulses with about 1.0 seconds between rise times. They indicate
            # start and stop of session.
            self.stop_record()

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

                prefix = DATA_FOLDER + self.get_filename_prefix()
                self.filename = prefix + "_Video.avi"
                self.filename_timestamp = prefix + "_Frames.txt"
                self.filename_timestamp_TTL = prefix + "_TTLs.txt"

                try:
                    # Create video file
                    self.Writer = cv2.VideoWriter(self.filename, self.codec, FRAME_RATE_PER_SECOND, self.resolution)
                except:
                    print(f"Warning: unable to create video file: '{self.filename}'")
                    return False

                if not self.Writer.isOpened():
                    # If codec is missing, we might get here. Usually OpenCV will have reported the error already.
                    print(f"Warning: unable to create video file: '{self.filename}'")
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

                printt(f"Started recording camera {self.order} to file '{self.filename}'")
                return True

    def stop_record(self):

        # Close and release all file writers
        # Do it on a separate thread to avoid dropping frames
        self.helper_thread = threading.Thread(target=self.stop_record_thread)
        self.helper_thread.start()

    def stop_record_thread(self):

        # Close and release all file writers
        with self.lock:

            # Acquire lock to avoid starting a new recording
            # in the middle of stopping the old one.

            if self.IsRecording:
                printt(f"Stopping recording camera {self.order} after " + self.get_elapsed_time_string())

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
                
            self.helper_thread = None

    def read_one_frame(self):
        try:
            # Read frame if camera is available and open
            self.status, self.frame = self.cam.read()
            return self.cam.isOpened() and self.status
        except:
            return False

    # Reads a single frame from CamObj class and writes it to file
    def read(self):

        if self.cam is not None and self.cam.isOpened():

            if not self.read_one_frame():

                # Read failed. Remove this camera so we won't attempt to read it later.
                # Should we set a flag to try to periodically reconnect?

                if self.IsRecording:
                    self.stop_record()  # Close file writers

                self.frame = make_blank_frame(f"{self.order} Camera lost connection")
                # Warn user that something is wrong.
                printt(f"Unable to read video from camera with ID {self.order}. Will remove camera from available list, and stop any ongoing recordings.")

                # Remove camera resources
                self.cam.release()
                self.cam = None
                self.status = 0
                return 0, self.frame

            if self.frames_to_mark_GPIO > 0:
                # Add blue dot to indicate that GPIO was recently detected
                self.frames_to_mark_GPIO -= 1
                cv2.circle(self.frame,
                           (int(20 * FONT_SCALE), int(70 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (255, 0, 0),     # Blue dot (color is in BGR order)
                           -1)   # -1 thickness fills circle

            if self.pending_start_timer > 0:
                # Add dark red dot to indicate that a start might be pending
                self.pending_start_timer -= 1
                cv2.circle(self.frame,
                           (int(20 * FONT_SCALE), int(50 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (0, 0, 96),     # Dark red dot (color is in BGR order)
                           -1)   # -1 thickness fills circle

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
                        return 0, None

                self.frame_num += 1

                if self.Writer is not None:
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

        str1 = f"   Camera {self.order} elapsed: " + self.get_elapsed_time_string()

    def get_elapsed_time_string(self):

        elapsed_sec = self.frame_num / FRAME_RATE_PER_SECOND
        if elapsed_sec < 120:
            str1 = f"{elapsed_sec:.0f} seconds"
        else:
            elapsed_min = elapsed_sec / 60
            str1 = f"{elapsed_min:.2f} minutes"
        return str1 + f", {self.frame_num} frames"

    def take_snapshot(self):
        if self.cam is None or self.frame is None:
            return
        if self.cam.isOpened():
            fname = self.get_filename_prefix() + "_snapshot.jpg"
            cv2.imwrite(fname, self.frame)

    def close(self):

        # Only call this when exiting program. Will stop all recordings, and release camera resources

        self.stop_record()  # This will run in a separate thread, and will close all files.
        
        if self.cam is not None:
            try:
                # Release camera resources
                self.cam.release()
            except:
                pass
            self.cam = None

        self.status = -1
        self.frame = None
        
        # Now wait for helper thread to finish
        with self.lock:
            # Acquiring lock will block while helper thread is running.
            # So by the time we acquire it, the helper thread will have
            # already ended, and the following is probably superfluous.
            if self.helper_thread is not None:
                # Wait for helper thread to stop
                self.helper_thread.join()
        
if __name__ == '__main__':
    print("CamObj.py is a helper file, intended to be imported from WEBCAM_RECORD.py, not run by itself")
