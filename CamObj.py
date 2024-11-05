#
# CamObj.py
#
# This file is intended to be imported by webcam_recorder.py
#
# It contains the CamObj class, which helps manage independent USB cameras.
#
# On Raspberry Pi and Windows, this works without additional effort.
# On Windows Subsystem for Linux (WSL), need to first install usbipd-win:
# https://learn.microsoft.com/en-us/windows/wsl/connect-usb#prerequisites
# Then you might have to install kernel drivers:
# https://github.com/dorssel/usbipd-win/wiki/WSL-support
# https://github.com/dorssel/usbipd-win/wiki/WSL-support

from __future__ import annotations  # Need this for type hints to work on older Python versions

import _io
import queue
import tkinter.filedialog
import tkinter.messagebox

from typing import List
import os
import sys
import psutil  # This is used to obtain disk free space
import numpy as np
import math
import time
import datetime
import platform
import threading
import subprocess
from sys import gettrace
import configparser
from enum import Enum
from ast import literal_eval as make_tuple  # Needed to parse resolution string in config
from queue import Queue

from extra.get_hardware_info import get_cam_usb_port

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')
IS_PI = False
IS_PI4 = False
IS_PI5 = False

if IS_LINUX:

    try:
        # This method for determining if running on Pi is different from what is in get_hardware_info.py, since
        # that method doesn't work in WSL Linux, whereas this does.
        r1 = subprocess.run(['cat', '/proc/cpuinfo'], stdout=subprocess.PIPE)
        r2 = subprocess.run(['grep', 'Model'], stdout=subprocess.PIPE, input=r1.stdout)

        if len(r2.stdout) > 0:
            r3 = subprocess.run(['cut', '-d', ':', '-f', '2'], stdout=subprocess.PIPE, input=r2.stdout)

            model = r3.stdout
            # model will typically have a leading space. Use "in" to ignore that
            if b'Raspberry Pi' in model:
                IS_PI = True
                
            if b'Raspberry Pi 4' in model:
                IS_PI4 = True
            elif b'Raspberry Pi 5' in model:
                IS_PI5 = True
    except:
        pass

if IS_PI:
    #
    # Raspberry Pi will read GPIOs. All other platforms do not.
    #
    # Note that the standard RPi.GPIO library does NOT work on Pi5 (only Pi4).
    # On Pi5, please uninstall the standard library and install the following
    # drop-in replacement:
    #
    # sudo apt remove python3-rpi.gpio
    # sudo apt install python3-rpi-lgpio
    #

    # PyCharm intellisense gives warning on the next line, but it is fine.
    import RPi.GPIO as GPIO

os.environ[
    "OPENCV_LOG_LEVEL"] = "FATAL"  # Suppress warnings that occur when camera id not found. This statement must occur before importing cv2

# This returns true if you ran the program in debug mode from the IDE
DEBUG = gettrace() is not None

# OpenCV install instructions:
#
# Note that OpenCV doesn't yet work with numpy2, which was released March 2024.
# Recommend using Numpy 1.26.4, which was the last released numpy <2.0, on Feb 5, 2024.
#
# On Pi5, look here: https://qengineering.eu/install%20opencv%20on%20raspberry%20pi%205.html
#     This is what worked for me:
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

# If true, will print extra diagnostics, such as GPIO on/off times and consecutive TTL counter
VERBOSE = False

configParser = configparser.RawConfigParser()
configFilePath = r'config.txt'
configParser.read(configFilePath)

DATA_FOLDER = configParser.get('options', 'DATA_FOLDER', fallback='')

if not (DATA_FOLDER.endswith("/") or DATA_FOLDER.endswith("\\")):
    # Data folder doesn't end with either forward or backward slash
    if len(DATA_FOLDER) > 0 and DATA_FOLDER != ".":
        # Only append slash if data folder is not the empty string. Otherwise,
        # just leave the empty string as is, so that we can default to the program directory.
        DATA_FOLDER = DATA_FOLDER + "/"

# Native frame rate of camera(s). If not specified, will attempt to determine by profiling
NATIVE_FRAME_RATE: float = configParser.getfloat('options', 'NATIVE_FRAME_RATE', fallback=0)

# This is the targeted RECORD frame rate, which may be lower than the camera's NATIVE frame rate
RECORD_FRAME_RATE: float = configParser.getfloat('options', 'RECORD_FRAME_RATE', fallback=0)
if RECORD_FRAME_RATE == 0:
    # If the above is not found, then check old defunct config option
    RECORD_FRAME_RATE: float = configParser.getfloat('options', 'FRAME_RATE_PER_SECOND', fallback=30)

ResolutionString = configParser.get('options', 'RESOLUTION', fallback='')

if ResolutionString == '':
    HEIGHT = configParser.getint('options', 'HEIGHT', fallback=480)
    WIDTH = configParser.getint('options', 'WIDTH', fallback=640)
else:
    # Parse height and width from string of type (WIDTH, HEIGHT)
    tmp_r = make_tuple(ResolutionString)
    WIDTH = tmp_r[0]
    HEIGHT = tmp_r[1]

if platform.system() == "Linux":
    FOURCC = configParser.get('options', 'FOURCC', fallback='h264')
else:
    # Note: h264 codec comes with OpenCV on Linux/Pi, but not Windows. Will default to using mp4v on
    # Windows. If you really want h264, there is a .DLL here: https://github.com/cisco/openh264/releases
    # but it has poor compression ratio, and doesn't always install anyway.
    FOURCC = configParser.get('options', 'FOURCC', fallback='mp4v')

NUM_TTL_PULSES_TO_START_SESSION = configParser.getint('options', 'NUM_TTL_PULSES_TO_START_SESSION', fallback=2)
NUM_TTL_PULSES_TO_STOP_SESSION = configParser.getint('options', 'NUM_TTL_PULSES_TO_STOP_SESSION', fallback=3)
RECORD_COLOR: int = configParser.getint('options', 'RECORD_COLOR', fallback=1)

SHOW_RECORD_BUTTON: int = configParser.getint('options', 'SHOW_RECORD_BUTTON', fallback=1)
SHOW_SNAPSHOT_BUTTON: int = configParser.getint('options', 'SHOW_SNAPSHOT_BUTTON', fallback=0)
SHOW_ZOOM_BUTTON: int = configParser.getint('options', 'SHOW_ZOOM_BUTTON', fallback=0)
SAVE_ON_SCREEN_INFO: int = configParser.getint('options', 'SAVE_ON_SCREEN_INFO', fallback=1)

# Reading webcam using MJPG allows higher frame rates,
# possibly at slightly lower image quality.
USE_MJPG: int = configParser.getint('options', 'USE_MJPG', fallback=IS_PI)

# This option should be removed in future versions, it doesn't work well, and is always False now.
USE_CALLBACK_FOR_GPIO: int = configParser.getint('options', 'USE_CALLBACK_FOR_GPIO', fallback=0)

is_debug: int = configParser.getint('options', 'DEBUG', fallback=DEBUG)

# First camera ID number
FIRST_CAMERA_ID: int = configParser.getint('options', 'FIRST_CAMERA_ID', fallback=1)

DEBUG = DEBUG or is_debug == 1

# This makes an ENORMOUS text file that logs GPIO polling lag times. Because polling occurs
# at 1kHz, there will be 3600 lines per minute. This didn't turn out to be as useful as I thought,
# so this is now set to False.
MAKE_DEBUG_DIAGNOSTIC_GPIO_LAG_TEXT_FILE = False

# Binary 0/1 used to be 25/75ms, so threshold was 0.05s
# As of 8/7/2024, increased to 50/150ms, so threshold is .1
# Number of seconds to discriminate between binary 0 and 1
BINARY_BIT_PULSE_THRESHOLD = 0.1

# This allows font sizes to grow and shrink with camera resolution
FONT_SCALE = HEIGHT / 480


def get_date_string(include_time=True):
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    hour = '{:02d}'.format(now.hour)
    minute = '{:02d}'.format(now.minute)
    if include_time:
        return '{}-{}-{}_{}{}'.format(year, month, day, hour, minute)
    else:
        return '{}-{}-{}'.format(year, month, day)


def make_blank_frame(txt, resolution=None):
    if resolution is not None:
        w = resolution[0]
        h = resolution[1]
    else:
        w = WIDTH
        h = HEIGHT
    tmp = np.zeros((h, w, 3), dtype="uint8")
    cv2.putText(tmp, txt, (int(10 * FONT_SCALE), int(30 * FONT_SCALE)), cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE, (255, 255, 255),
                round(FONT_SCALE + 0.5))  # Line thickness
    return tmp


filename_log = DATA_FOLDER + get_date_string(include_time=False) + "_log.txt"

try:
    # Create text file for frame timestamps. Note 'a' for appending.
    fid_log = open(filename_log, 'a')
    print("Logging events to file: \'" + filename_log + "\'")
except:
    print(
        "Unable to create log file: \'" + filename_log + "\'.\n  Please make sure folder exists and that you have permission to write to it.")


# Write text to both log file and (optional) screen. Log file helps with retrospective troubleshooting
def printt(txt, omit_date_time=False, close_file=False, print_to_screen=True):
    # Get the current date and time
    if not omit_date_time:
        now = datetime.datetime.now()

        if DEBUG:
            s = now.strftime("%Y-%m-%d %H:%M:%S.%f: ") + txt
        else:
            s = now.strftime("%Y-%m-%d %H:%M:%S: ") + txt
    else:
        s = txt
    if print_to_screen:
        print(s, flush=True)
    try:
        fid_log.write(s + "\n")
        fid_log.flush()
        if close_file:
            fid_log.close()
    except:
        pass


def get_disk_free_space():
    path = DATA_FOLDER
    if path == "":
        path = "./"
    if os.path.exists(path):
        bytes_avail = psutil.disk_usage(path).free
        gigabytes_avail = bytes_avail / 1024 / 1024 / 1024
        return gigabytes_avail
    else:
        return None


# Tries to connect to a single camera based on ID. Returns a VideoCapture object if successful.
# If no camera found with that ID, will throw exception, which unfortunately is the only
# way to enumerate what devices are connected. The caller needs to catch the exception and
# handle it by excluding that ID from further consideration.
def setup_cam(id, width=WIDTH, height=HEIGHT):
    try:
        if platform.system() == "Windows":
            tmp = cv2.VideoCapture(id, cv2.CAP_DSHOW)  # On Windows, specifying CAP_DSHOW greatly speeds up detection
        else:
            if USE_MJPG:
                tmp = cv2.VideoCapture(id,
                                       cv2.CAP_V4L2)  # This is needed for MJPG mode to work, allowing higher frame rates
            else:
                tmp = cv2.VideoCapture(id)
    except Exception as ex:
        print(f"Error while attempting to connect camera")
        print("    Error type is: ", ex.__class__.__name__)
        return None, None

    if tmp.isOpened():
        if USE_MJPG:
            # Higher resolutions are limited by USB transfer speeds to use lower frame rates.
            # Changing to MJPG roughly doubles the max frame rate, at some cost of CPU cycles
            tmp.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        if not tmp.isOpened():
            print(f"MJPG not supported. Please edit code.")
        tmp.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        tmp.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        width2 = tmp.get(cv2.CAP_PROP_FRAME_WIDTH)
        height2 = tmp.get(cv2.CAP_PROP_FRAME_HEIGHT)
        
        if width2 != width or height2 != height:
            msg1 = f"Resolution {int(width)}x{int(height)} not supported by camera, try {int(width2)}x{int(height2)} instead."
            print(msg1)
            msg2 = f"Resolution {int(width)}x{int(height)} not supported by camera.\n\nTry {int(width2)}x{int(height2)} instead."
            tkinter.messagebox.showinfo("Warning", msg2)

        # fps readout does not seem to be reliable. On Linux, we always get 30fps, even if camera
        # is set to a high resolution that can't deliver that frame rate. On Windows, always seem to get 0.
        fps = tmp.get(cv2.CAP_PROP_FPS)
        if not tmp.isOpened():
            print(f"Resolution {int(width)}x{int(height)} not supported. Please change config.txt.")
    else:
        fps = 0

    return tmp, fps


def verify_directory():
    # get custom version of datetime for folder search/create
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    date = '{}-{}-{}'.format(year, month, day)

    target_path = os.path.join(DATA_FOLDER, date)

    if os.path.isdir(target_path):
        # check permissions
        m = os.stat(target_path).st_mode & 0o777
        if m != 0o777:
            # Now make read/write/executable by owner, group, and other.
            # This is necessary since these folders are often made by root, but accessed by others.
            # os.chmod(target_path, mode=0o777) # This fails if created by root and we are not root
            proc = subprocess.Popen(['sudo', 'chmod', '777', target_path])
    else:
        try:
            os.mkdir(target_path,
                 mode=0o777)  # Note linux umask is usually 755, which limits what permissions non-root can make
        except Exception as ex:
            print(f"Error while attempting to create folder {target_path}")
            print("    Error type is: ", ex.__class__.__name__)
            return ''  # This will force file to go to program folder

        if IS_LINUX:
            # Make writeable by all users on Linux (we need this because when running as root,
            # we need to make this folder accessible to non-root users also)
            subprocess.Popen(['chmod', '777', target_path])  # This should always work
        print("Folder was not found, but created at: ", target_path)
    return target_path


class CamObj:

    cam = None  # this is the opencv camera object
    id_num = -1  # ID number assigned by operating system. May be unpredictable.
    box_id = -1  # User-friendly camera ID. Will usually be USB port position/screen position, starting from 1
    status = -1  # True if camera is operational and connected
    frame = None  # Most recently obtained video frame. If camera lost connection, this will be a black frame with some text
    filename_video: str = "file_Video.avi"
    filename_timestamp = "file_Frames.txt"
    filename_timestamp_TTL = "file_TTLs.txt"

    IsRecording = False
    GPIO_pin = -1  # Which GPIO pin corresponds to this camera? First low-high transition will start recording.

    class TTL_type(Enum):
        Normal = 0
        Binary = 1
        Checksum = 2
        Debug = 3

    class PendingAction(Enum):
        Nothing = 0
        StartRecord = 1
        ForceStop = 2
        Exiting = 3

    # Class variables related to TTL handling
    TTL_num = -1  # Counts how many TTLs (usually indicating trial starts) have occurred in this session
    TTL_binary_bits = 0  # Ensures that we receive 16 binary bits
    current_animal_ID: [str | None] = None
    TTL_tmp_ID = 0  # Temporary ID while we are receiving bits
    TTL_mode = None
    TTL_debug_count = 0
    TTL_checksum = 0
    most_recent_gpio_rising_edge_time = -1
    most_recent_gpio_falling_edge_time = -1
    num_consec_TTLs = 0  # Use this to track double and triple pulses

    # PyCharm intellisense gives warning on the next line, but it is fine.
    codec = cv2.VideoWriter_fourcc(*FOURCC)  # What codec to use. Usually h264
    resolution: List[int] = (WIDTH, HEIGHT)

    lock = None  # This lock object is local to this instance
    global_lock = threading.RLock()  # This lock is global to ALL instances, and is used to generate unique filenames

    GPIO_active = 0  # Use this to add blue dot to frames when GPIO is detected
    pending_start_timer = 0  # Used to show dark red dot while waiting to see if double pulse is not a triple pulse

    def __init__(self, cam=None, id_num=-1, box_id=-1, GPIO_pin=-1):
        self.thread_consumer = None
        self.thread_producer = None
        self.last_frame_written: int = 0
        self.CPU_lag_frames = 0
        self.pending = self.PendingAction.Nothing
        self.cached_frame_time = None
        self.cached_frame = None
        self.stable_frame = None
        self.need_update_button_state_flag = None
        self.process = None  # This is used if calling FF_MPEG directly. Probably won't use this in the future.
        self.cam = cam
        self.id_num = id_num  # ID number assigned by operating system. We don't use this, as it is unpredictable.
        self.box_id = box_id  # This is a user-friendly unique identifier for each box.
        self.GPIO_pin = GPIO_pin
        self.lock = threading.RLock()  # Reentrant lock, so same thread can acquire more than once.
        self.TTL_mode = self.TTL_type.Normal
        self.q: Queue = Queue()

        # Various file writer objects
        self.Writer: [cv2.VideoWriter | None] = None  # Writer for video file
        self.fid: [_io.TextIOWrapper | None] = None  # Writer for timestamp file
        self.fid_TTL: [_io.TextIOWrapper | None] = None  # Writer for TTL timestamp file
        self.fid_diagnostic: [_io.TextIOWrapper | None] = None  # Writer for debugging info
        self.start_recording_time = time.time()  # Timestamp (in seconds) when session or recording started
        self.dropped_recording_frames = None
        self.last_frame_received_elapsed_time = 0
        self.frames_received = 0  # Number of frames received, even if later dropped
        self.frames_recorded = 0  # Number of frames recorded

        self.pending_stop_record_time = 0

        # Status string to show on GUI
        self.final_status_string = '--'

        # This becomes True after camera fps profiling is done, or determined not to be needed,
        # and process_frame() loop has started. This prevents GUI stuff from slowing down the profiling.
        self.IsReady = False

        if cam is None:
            # Use blank frame for this object if no camera object is specified
            self.frame = make_blank_frame(f"{box_id} - No camera found")

        self.thread_GPIO = None

        if GPIO_pin >= 0 and platform.system() == "Linux":
            if USE_CALLBACK_FOR_GPIO:
                # Start monitoring GPIO pin
                GPIO.add_event_detect(GPIO_pin, GPIO.BOTH, callback=self.GPIO_callback_both)
            else:
                self.thread_GPIO = threading.Thread(target=self.GPIO_thread)
                self.thread_GPIO.start()

        if cam is not None:
            self.frame = make_blank_frame(f"{self.box_id} Starting up ...")

    def start_read_thread(self):

        self.thread_producer = threading.Thread(target=self.read_camera_continuous)
        self.thread_producer.start()

    def GPIO_thread(self):

        # Implementing our own polling thread is much faster on the Pi, for
        # some reason. Out of 15,000 TTLs (each 100ms) one was missing (or
        # <10ms) and all the rest were between 60-120ms. So if we allow 50ms
        # leeway, then we should have >99.99% accuracy.

        g = self.GPIO_pin
        s = GPIO.input(g)
        t = time.time()

        while not self.pending == self.PendingAction.Exiting:

            if GPIO.input(g) != s:
                s = not s
                self.GPIO_active = 1 if s else 0
                if s:
                    self.GPIO_rising_edge(t)
                else:
                    self.GPIO_falling_edge(t)

            if DEBUG and self.fid_diagnostic is not None:
                
                t1 = time.time()
                lag1 = t1 - t    # Time spent reading GPIO signal. Also includes file write time from previous cycle
                time.sleep(0.001)
                t = time.time()
                lag2 = t - t1    # Time spent in 1ms sleep
                elapsed = t - self.start_recording_time
                try:
                    self.fid_diagnostic.write(f'{elapsed}\t{lag1}\t{lag2}\n')
                except:
                    self.fid_diagnostic.close()
                    self.fid_diagnostic = None
                    pass
            else:
                time.sleep(0.001)
                t = time.time()

    def GPIO_callback_both(self, param):

        # We no longer use callback to handle GPIO, since jitter is unacceptably high,
        # with about 1% of 100ms pulses being >50ms too long, and about 0.3% being >100ms
        # too long.
        
        if VERBOSE:
            printt(f'Cam {self.box_id} received GPIO on pin {param}')

        if GPIO.input(param):
            if VERBOSE:
                printt('GPIO on')
            self.GPIO_rising_edge()
        else:
            if VERBOSE:
                printt('GPIO off')
            self.GPIO_falling_edge()

    #
    # New GPIO pattern as of 6/22/2024
    #
    # Long high pulse (0.2s) starts binary mode, transmitting 16 bits of animal ID.
    #     In binary mode, 75ms pulse is 1, 25ms pulse is 0. Off duration between pulses is 25ms
    #     Binary mode ends with long low period (0.2ms) followed by short high pulse (0.01ms)
    # In regular mode, pulses are high for 0.1s, then low for 0.025-0.4s gaps (used to be long, but now much
    # shorter.)
    #     Single pulses indicate cue start
    #     Double pulses start session
    #     Triple pulses end session
    # As of 6/30/2024
    # Extra long high pulse (2.5s) starts DEBUG TTL mode, where TTL duration is recorded
    #     and warnings are printed for any deviation from expected 75ms/25ms on/off duty cycle.
    #     deviation has to exceed 10ms to be printed.
    #
    def GPIO_rising_edge(self, t=None):

        # Detected rising edge. Log the timestamp so that on falling edge we can see if this is a regular
        # pulse or a LONG pulse that starts binary mode
        if t is None:
            self.most_recent_gpio_rising_edge_time = time.time()
        else:
            self.most_recent_gpio_rising_edge_time = t

        elapsed_pause = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time

        # This is used to show blue dot on next frame.
        self.GPIO_active = 1

        if elapsed_pause > 0.1:
            # Burst TTLs should have 50ms gap. Allow 50ms leeway up to 100ms.
            self.num_consec_TTLs = 0
            if VERBOSE:
                printt(f'Rising edge, consec TTLs=0')

        if self.TTL_mode == self.TTL_type.Binary:
            # If already in binary mode, then inter-bit pauses are 0.05s (used to be .025s)
            # Long (0.2s) "off" pause switches to checksum mode for final pulse.
            # We give 50ms leeway in either direction, i.e. .15 to .25, then extend upper
            # boundary to .5 since there is no competing signal there. After .5, we still end
            # binary mode, but issue warning.
            if 0.15 < elapsed_pause < 0.5:
                if self.TTL_binary_bits != 16:
                    printt(f'Warning: in binary mode received {self.TTL_binary_bits} bits instead of 16')
                    self.current_animal_ID = "Unknown"

                if DEBUG:
                    printt('Binary mode now awaiting final checksum...')
                self.TTL_mode = self.TTL_type.Checksum
            elif elapsed_pause >= 0.25:
                printt(f'Box {self.box_id} detected very long pause of {elapsed_pause}s to end binary mode (should be 0.2s to switch to checksum)')
                self.TTL_mode = self.TTL_type.Normal
        elif self.TTL_mode == self.TTL_type.Debug:
            # In debug mode, all gaps should be 25ms
            elapsed_pause = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time
            if elapsed_pause > 1:
                # Cancel debug mode
                self.TTL_mode = self.TTL_type.Normal
                printt(f'Exiting DEBUG TTL mode with pause length {elapsed_pause}')
            elif elapsed_pause < 0.015 or elapsed_pause > 0.035:
                printt(f'{self.TTL_debug_count} off time {elapsed_pause}, expected 0.025')

        return

    def GPIO_falling_edge(self, t=None):

        # Detected falling edge
        if t is None:
            self.most_recent_gpio_falling_edge_time = time.time()
        else:
            self.most_recent_gpio_falling_edge_time = t

        # Cancel blue dot display on video
        self.GPIO_active = 0

        if self.most_recent_gpio_rising_edge_time < 0:
            # Ignore falling edge if no rising edge was detected, e.g. at program launch?
            return

        # Calculate pulse width
        on_time = time.time() - self.most_recent_gpio_rising_edge_time

        if on_time < 0.005:
            # Ignore very short pulses, which are probably mechanical switch bounce.
            # But: sometimes these are a result of pulses piling up in Windows, then getting sent all at once.
            printt(f'Cam {self.box_id} ignoring short TTL of duration {on_time}')
            return

        if self.TTL_mode == self.TTL_type.Normal:
            # In normal (not binary or checksum) mode, read the following types of pulses:
            # 0.1s on-time (range 0.01-0.2) indicates trial start, or session start/stop if doubled/tripled
            # 0.3s on time (range 0.2-0.4) initiates binary mode. USED TO BE 0.2.
            # 0.4s-2s ... ignored
            # 2.5s (range 2.4-2.6s) starts DEBUG TTL mode
            # >3s ... ignored
            if on_time < 0.2:
                self.num_consec_TTLs += 1
                self.handle_GPIO()
            elif on_time < 0.4:
                # Sometimes a 0.1s pulse will glitch and be perceived as longer than 0.15s.
                # So we moved range from .15-.25 to .2-.4
                # We also reduce the chance of this by only starting binary mode if not recording.
                if not self.IsRecording:
                    if DEBUG:
                        printt('Starting binary mode')
                    self.TTL_mode = self.TTL_type.Binary
                    self.current_animal_ID = "Pending"
                    self.TTL_tmp_ID = 0
                    self.TTL_binary_bits = 0
                    self.TTL_checksum = 0
                    self.num_consec_TTLs = 0
                else:
                    # Pulse duration is between .2 and .4, and we are not recording. Assume regular TTL?
                    # This should be extremely rare.
                    printt(f'Box {self.box_id} received TTL pulse longer than the usual 0.1s ({on_time}s)')
                    self.num_consec_TTLs += 1
                    self.handle_GPIO()
            elif 2.4 < on_time < 2.6 and DEBUG:
                # Extra long pulse starts debug testing mode
                self.TTL_mode = self.TTL_type.Debug
                printt(f'Entering DEBUG TTL mode with pulse length {on_time}s')
                self.TTL_debug_count = 0

            return

        elif self.TTL_mode == self.TTL_type.Checksum:
            # Final pulse of either 50ms or 150ms. Threshold is 100ms
            if on_time < BINARY_BIT_PULSE_THRESHOLD:
                checksum = 0
            elif on_time < BINARY_BIT_PULSE_THRESHOLD * 3:
                # 75ms pulse indicates ONE
                checksum = 1
            else:
                printt(
                    f"Received animal ID {self.TTL_tmp_ID} for box {self.box_id}, but checksum duration too long ({on_time} instead of 50 or 150ms).")
                self.current_animal_ID = "Checksum fail"
                self.TTL_mode = self.TTL_type.Normal
                return

            if self.TTL_checksum == checksum:
                # Successfully received TTL ID
                self.current_animal_ID = str(self.TTL_tmp_ID)
                printt(f'Received animal ID {self.current_animal_ID} for box {self.box_id}')
            else:
                printt(f"Received animal ID {self.TTL_tmp_ID} but checksum failed for box {self.box_id}")
                self.current_animal_ID = "Checksum fail"
            self.TTL_mode = self.TTL_type.Normal
        elif self.TTL_mode == self.TTL_type.Binary:
            # We are in TTL binary mode.
            # 25ms pulses indicate 0
            # 75ms pulses indicate 1
            # We use 50ms threshold to distinguish
            self.TTL_binary_bits += 1
            self.TTL_tmp_ID *= 2
            if BINARY_BIT_PULSE_THRESHOLD < on_time:
                # Pulse width between 0.5-0.1s indicates binary ONE
                self.TTL_checksum = 1 - self.TTL_checksum
                self.TTL_tmp_ID += 1
                if on_time > BINARY_BIT_PULSE_THRESHOLD * 2:
                    printt(f'Warning: Binary pulse width is longer than {BINARY_BIT_PULSE_THRESHOLD*2000}ms.')
                    # Should this abort binary mode? For now we treat long pulses as "1"
        elif self.TTL_mode == self.TTL_type.Debug:
            # Debug mode
            # Should receive continuous pulses of duration 75ms, with 25ms gap
            # Long pulse of >1s will cancel debug mode
            if on_time > 1:
                # Cancel debug mode
                self.TTL_mode = self.TTL_type.Normal
                printt(f'Exiting DEBUG TTL mode with pulse length {on_time}')
            elif True:  # on_time > .025:
                self.TTL_debug_count += 1
                if on_time < 0.065 or on_time > 0.085:
                    printt(f"{self.TTL_debug_count} Debug TTL on time is {on_time} (should be 0.075)")

    def delayed_start(self):

        # This will wait a second to make sure no additional GPIOs occurred, then
        # will start recording video

        # This timer is used to make sure no extra pulses come in between second and third pulse
        # Any gap >0.1s will cancel consecutive TTL count. However, we have to wait 50ms plus 100ms
        # to make sure we don't have a third pulse, i.e. have to wait 150ms. We extend this to 500ms just
        # in case.
        wait_interval_sec = 0.5

        # Calculate number of frames to show dark red "pending" dot
        self.pending_start_timer = int(RECORD_FRAME_RATE * wait_interval_sec + 1)

        time.sleep(wait_interval_sec)

        if self.num_consec_TTLs > NUM_TTL_PULSES_TO_START_SESSION:
            # If a third pulse has arrived, then don't start.
            # However, if count has reset to 0, that is OK, since it would mean that
            # additional pulse arrived too late to count as part of burst (>0.1s gap)
            return

        if not self.start_record():
            # Start recording failed, so don't record TTLs
            print(f"Unable to start recording camera {self.box_id} in response to GPIO input")
            return

        if not self.IsRecording:
            # Not recording video, so don't save TTL timestamps
            print("Hmmm, something seems wrong, GPIO recording didn't start after all. Please contact developer.")

    def handle_GPIO(self):

        # Detected normal GPIO pulse (i.e. not part of binary mode transmission of animal ID)
        # This function is called at falling edge of pulse.

        # Because this function is called from the GPIO callback thread, we need to
        # acquire lock to make sure main thread isn't also accessing the same variables.
        # For example, if the main thread is in the midst of starting a recording, we need to
        # wait for that to finish, or else we might start the recording twice (with very
        # unpredictable results).
        with self.lock:

            if not self.IsRecording:

                if self.num_consec_TTLs == NUM_TTL_PULSES_TO_START_SESSION:
                    # We have detected a double pulse. Start thread that makes sure this
                    # isn't just the beginning of a triple pulse, and if confirmed, will start session

                    t = threading.Thread(target=self.delayed_start)

                    t.start()

                # Not recording, and only detected a single TTL pulse. Just ignore.
                return

            else:
                # Calculate TTL timestamp relative to session start

                # Use rising edge time, since we don't get here until falling edge.
                # Note that time.time() returns number of seconds since 1970, as a floating point number.
                gpio_onset_time = self.most_recent_gpio_rising_edge_time - self.start_recording_time
                gpio_offset_time = self.most_recent_gpio_falling_edge_time - self.start_recording_time

                self.TTL_num += 1
                if self.fid_TTL is not None:
                    if 0 < self.pending_stop_record_time < self.most_recent_gpio_rising_edge_time:
                        # If stop_record has been issued, and TTL is later, then don't save
                        printt("TTL received after recording stop, won't save")
                    else:
                        # Only record TTL if stop has not been issued, or if stop time is later than this pulse
                        try:
                            self.fid_TTL.write(f"{self.TTL_num}\t{gpio_onset_time}\t{gpio_offset_time}\n")
                            self.fid_TTL.flush()
                        except:
                            printt(f"Unable to write TTL timestamp file for camera {self.box_id}")
                else:
                    # We shouldn't ever get here. If so, something usually has gone wrong with file system,
                    # e.g. USB drive has come unplugged.
                    if not DEBUG:
                        # In debug mode, we might be performing stress test, so skip warning
                        print(f"Missing TTL timestamp file for camera {self.box_id}")

        # By now lock has been released, and we are guaranteed to be recording.

        if self.num_consec_TTLs >= NUM_TTL_PULSES_TO_STOP_SESSION:
            # Triple pulses are pulses with about 0.5 seconds between rise times. They indicate
            # start and stop of session.
            self.stop_record()

    # Creates directory with current date in yyyy-mm-dd format.
    # Then verifies that directory exists, and if not, creates it

    def get_filename_prefix(self, animal_ID=None, add_date=True, join_path=True):
        
        path = verify_directory()

        if self.current_animal_ID is not None:
            prefix_ending = f"Box{self.box_id}_" + str(self.current_animal_ID)
        else:
            # No TTL-transmitted animal ID, just use box ID in filename
            prefix_ending = f"Box{self.box_id}"

        if add_date:
            filename = get_date_string() + "_" + prefix_ending
        else:
            filename = prefix_ending

        if join_path:
            return os.path.join(path, filename)
        else:
            return path, filename

    def start_record(self, animal_ID: str = None, stress_test_mode: bool = False):
        # If animal ID is not specified, will first look for TTL
        # transmission, and if that is also not present, will use camera
        # ID number.
        #
        # If stress_test_mode is True, will save to "stress_test_camX.avi" file
        # in top level of data folder, where X is the camera ID number.
        # In this mode, all animal ID info is ignored, and save file
        # location is the same regardless of date. This allows rapid
        # starting of all 4 cameras without having to enter an ID for each.

        if self.cam is None or not self.cam.isOpened():
            if DEBUG:
                print(f"Camera {self.box_id} is not available for recording.")
            return False

        # Camera reads occur on a dedicated thread for each cam object.
        # However, start_record is usually called from either the main GUI thread,
        # or the GPIO callback thread. So need to acquire locks to make sure
        # the three threads don't conflict.
        with self.lock:
            if not self.IsRecording:
                self.frames_received = 0
                self.frames_recorded = 0
                self.TTL_num = 0

                if stress_test_mode:
                    # Stress test saves to same location every time, ignoring date and animal ID.
                    prefix = os.path.join(DATA_FOLDER, f"stress_test_cam{self.box_id}")
                    self.current_animal_ID = "StressTest"
                else:
                    # Generate filename prefix, which will be date string plus animal ID (or box ID
                    # if no animal ID is available).
                    if animal_ID is not None:
                        # This will overwrite any TTL-derived ID value.
                        self.current_animal_ID = animal_ID
                    prefix = self.get_filename_prefix()

                prefix_unique = ""
                suffix_count = 0

                try:

                    with self.global_lock:
                        # Acquire global lock to make sure we get a filename that is not already in use
                        # and is also unique to all instances. Now that we have box ID number in filename
                        # this is less essential, as that will keep filename unique across all cameras.
                        while True:
                            # Iterate until we get a unique filename
                            if suffix_count > 0:
                                # After first pass, we append suffixes _1, _2, _3, ...
                                prefix_unique = f"_{suffix_count}"

                            self.filename_video = prefix + prefix_unique + "_Video.avi"

                            if stress_test_mode:
                                # In stress test mode, don't need to check if filename is unique,
                                # as we intend to overwrite previous files.
                                break

                            if not os.path.isfile(self.filename_video):
                                # We have now confirmed that file doesn't already exist, and can proceed
                                break

                            suffix_count += 1

                        # Create video file
                        self.Writer = cv2.VideoWriter(self.filename_video,
                                                      self.codec,
                                                      RECORD_FRAME_RATE,
                                                      self.resolution,
                                                      RECORD_COLOR == 1)
                except Exception as e:
                    # Strangely, failure to open file does NOT trigger exception.
                    str1 = f"ERROR: unable to create video file: '{self.filename_video}'"
                    printt(str1)
                    tkinter.messagebox.showinfo("Error", str1)
                    return False

                self.filename_timestamp = prefix + prefix_unique + "_Frames.txt"
                self.filename_timestamp_TTL = prefix + prefix_unique + "_TTLs.txt"

                if not self.Writer.isOpened():
                    # If codec is missing, we might get here. Usually OpenCV will have reported the error already.
                    # If lacking permission to write to folder, will also end up here. However, OpenCV will not report
                    # any error, it just won't do it.
                    str1 = f"ERROR: unable to create video file:\n\n'{self.filename_video}'\n\nMake sure you have permission to write file and that codec is installed."
                    printt(str1)
                    tkinter.messagebox.showinfo("Error", str1)
                    # return False

                try:
                    # Create text file for frame timestamps
                    self.fid = open(self.filename_timestamp, 'w')
                    if DEBUG:
                        self.fid.write('Frame_number\tTime_in_seconds\tQueue_lag\tcompression_lag\n')
                    else:
                        self.fid.write('Frame_number\tTime_in_seconds\n')
                except Exception as e:
                    str1 = f"ERROR while creating frame timestamp text file:\n\n{self.filename_timestamp}\n\n" + str(e)
                    printt(str1)

                    # Close the previously-created writer objects
                    self.Writer.release()
                    tkinter.messagebox.showinfo("Error", str1)
                    return False

                try:
                    # Create text file for TTL timestamps
                    self.fid_TTL = open(self.filename_timestamp_TTL, 'w')
                    self.fid_TTL.write('TTL_event_number\tONSET (seconds)\tOFFSET (seconds)\n')
                except Exception as e:
                    str1 = f"ERROR creating TTL text file:\n\n{self.filename_timestamp_TTL}\n\n" + str(e)
                    
                    printt(str1)

                    # Close the previously-created writer objects
                    self.fid.close()
                    self.Writer.release()
                    tkinter.messagebox.showinfo("Error", str1)
                    return False

                if DEBUG and MAKE_DEBUG_DIAGNOSTIC_GPIO_LAG_TEXT_FILE:
                    try:
                        # Create text file for diagnostic info

                        self.fid_diagnostic = open(prefix + prefix_unique + "_diagnostic.txt", 'w')
                        self.fid_diagnostic.write('Time\tGPIO_lag1\tGPIO_lag2\n')
                    except Exception as e:
                        str1 = "ERROR creating diagnostic text file:\n   " + str(e)
                        printt(str1)

                self.start_recording_time = time.time()
                self.dropped_recording_frames = 0

                # Set this flag last
                self.IsRecording = True

                printt(f"Started recording camera {self.box_id} to file '{self.filename_video}'")

                # This allows us to change button state
                self.need_update_button_state_flag = True

                return True

    def stop_record(self, force=False):

        with self.lock:
            if force:
                self.pending = self.PendingAction.ForceStop
            else:
                # Set time flag so that recording will stop when frame exceeds this value.
                # This allows already-queued frames to get recorded, even if not processed until later.
                self.pending_stop_record_time = time.time()
            # stop_record() overrides any pending starts.
            if self.pending == self.PendingAction.StartRecord:
                self.pending = self.PendingAction.Nothing

    def __stop_recording_now(self):

        # Close and release all file writers immediately.
        with self.lock:

            # Acquire lock to avoid starting a new recording
            # in the middle of stopping the old one.

            self.current_animal_ID = None

            if self.IsRecording:
                self.IsRecording = False
                self.final_status_string = self.get_elapsed_time_string()
                str1 = f"Stopped recording camera {self.box_id} after " + self.final_status_string
                if self.dropped_recording_frames > 0:
                    str1 += f", >= {self.dropped_recording_frames} dropped frames"
                printt(str1)

            self.need_update_button_state_flag = True
            self.frames_received = 0
            self.frames_recorded = 0

            if self.Writer is not None:
                try:
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

            if DEBUG:
                if self.fid_diagnostic is not None:
                    try:
                        self.fid_diagnostic.close()
                    except:
                        pass
                    self.fid_diagnostic = None

    def profile_fps(self):

        # First frame always takes longer to read, so get it out of the way
        # before conducting profiling
        status, frame = self.cam.read()
        
        if not status:
            # Even though camera was detected a few seconds earlier, read can still fail. For
            # example, if camera is connected to Pi through a passive extension cable, the connection
            # might be good enough to detect camera, but not good enough to receive data. In that case,
            # we will fail here. Solution there is to use an active extender (e.g. hub).
            printt(f"Unable to read cam {self.box_id} initial frame")
            return -1

        # Subsequent frames might actually read too fast, if they are coming
        # from internal memory buffer. So now clear out any frames in camera buffer
        old_time = time.time()
        time_limit = old_time + 5
        while True:
            status, frame = self.cam.read()
            if not status:
                printt(f"Unable to read cam {self.box_id} flushed frame")
                return -1
            new_time = time.time()
            elapsed = new_time - old_time
            old_time = new_time
            if elapsed > 0.01:
                # Buffered frames will return very quickly. We wait until
                # the return time is longer, indicating that buffer is now empty
                break

        old_time = time.time()
        start_time = old_time
        MAX_DURATION = 5.0
        MAX_FRAMES = 20
        FRAME_GROUP = 4
        target_time = old_time + MAX_DURATION  # When to stop profiling
        frame_count = 0
        min_elapsed4 = 1000

        # Read frames for 5 seconds or until 20 frames have been received, whichever comes first.
        # This is surprisingly tricky, since frames can arrive late, or occasionally early. To
        # reduce variance, we calculate interval between groups of 4 frames, then calculate rate
        # from the shortest interval.
        while time.time() < target_time:

            status, frame = self.cam.read()
            if not status:
                printt(f"Unable to read cam {self.box_id} to determine frame rate")
                return -1

            new_time = time.time()

            frame_count += 1
            if frame_count % FRAME_GROUP == 0:
                elapsed = new_time - old_time
                if elapsed > 0.06:
                    if elapsed < min_elapsed4:
                        # Finds minimum interval between any 4 frames
                        min_elapsed4 = elapsed
                old_time = new_time
                if frame_count == MAX_FRAMES:
                    break

        if min_elapsed4 < 1000:
            # Upper bound on frame rate
            estimated_frame_rate = FRAME_GROUP / min_elapsed4
            # Lower bound on frame rate
            estimated_frame_rate2 = frame_count
        else:
            # Frame rate might be very slow. Don't use 4-group averages, as there will likely only be
            # one measurement?
            printt("Frame rate could not be determined - might be < 1fps.")
            estimated_frame_rate = float(frame_count) / (new_time - start_time)

        printt(f'Box {self.box_id} estimated native frame rate {estimated_frame_rate:.3f}fps')

        # Sometimes will get value slightly lower or higher than real frame rate, e.g. 29.9 or 30.2 instead of 30
        if estimated_frame_rate > 55:
            estimated_frame_rate = 60
        elif estimated_frame_rate > 25:
            estimated_frame_rate = 30
        elif estimated_frame_rate > 18:
            estimated_frame_rate = 20
        elif estimated_frame_rate > 13:
            estimated_frame_rate = 15
        elif estimated_frame_rate > 8.5:
            estimated_frame_rate = 10
        elif estimated_frame_rate > 6.5:
            estimated_frame_rate = 7.5
        elif estimated_frame_rate > 4:
            estimated_frame_rate = 5
        elif estimated_frame_rate > .8:
            estimated_frame_rate = 1
        else:
            estimated_frame_rate = 1

        printt(f'Rounded frame rate to {estimated_frame_rate}')

        return estimated_frame_rate

    def read_camera_continuous(self):

        # This function implements a PRODUCER thread.
        # However, before entering the producer loop, it also starts the
        # CONSUMER thread (after possibly profiling camera fps).

        if self.cam is None or not self.cam.isOpened():
            # No camera connected
            if DEBUG:
                printt(f"Camera {self.box_id} not connected.")
            return

        if NATIVE_FRAME_RATE == 0:
            # Determine native frame rate by grabbing a few frames and measuring latency
            native_fps = self.profile_fps()
            if native_fps < 0:
                # Camera has become disconnected
                self.cam = None
                self.frame = make_blank_frame(f"{self.box_id} Camera lost connection")
                printt(f"Camera {self.box_id} not connected. Will not start producer or consumer threads.")
                return
        else:
            native_fps = NATIVE_FRAME_RATE

        count_cycle = 0
        count_sent_frames = 0

        # Downsampling interval. Must be integer, hence use of ceiling function
        count_interval = math.ceil(native_fps / RECORD_FRAME_RATE)
        
        if DEBUG:
            printt(f'Will save every {count_interval} frames')

        # Start CONSUMER thread that will process the frames sent by this loop.
        # This allows read_camera_continuous(), i.e. this thread, to
        # run at max speed.
        self.thread_consumer = threading.Thread(target=self.consumer_thread)
        self.thread_consumer.start()

        # This is here just to keep PyCharm from issuing warning at line 878
        frame = None
        frame_time = 0
        TTL_on = None

        self.IsReady = True
        nextRetry = 0
        last_dropped_frame_warning = time.time()

        while not self.pending == self.PendingAction.Exiting:

            if nextRetry > 0:
                if nextRetry > time.time():
                    # Time to retry connection
                    tmp, _ = setup_cam(self.id_num)
                    if tmp.isOpened():
                        # Successfully reconnected
                        self.cam = tmp
                        self.status = True
                        nextRetry = 0
  
                        if IS_PI:
                            # We reconnected using the camera's ID, not the actual USB port #. So
                            # we should now check that camera is plugged into the same port as
                            # before.
                            port = get_cam_usb_port(self.id_num)
                            old_port = self.box_id - FIRST_CAMERA_ID
                            if port != old_port:
                                st1 = f"Warning: Camera plugged into different USB port than before."
                                st2 = f"Was {old_port}, now {port}."
                                printt(st1)
                                printt(st2)
                                tkinter.messagebox.showinfo("Warning", st1 + "\n\n" + st2)
                    else:
                        # Wait 5 seconds until next retry
                        nextRetry = time.time() + 5
                else:
                    # Not yet time to retry connection
                    time.sleep(1)
                continue

            if self.cam is not None and self.cam.isOpened():
                try:
                    # Read frame if camera is available and open
                    self.status, frame = self.cam.read()
                    frame_time = time.time()
                    TTL_on = self.GPIO_active
                except:
                    # Set flag that will cause loop to exit shortly
                    self.status = False
            else:
                self.status = False

            if not self.status:

                if self.pending == self.PendingAction.Exiting:
                    break

                # Read failed. Remove this camera so we won't attempt to read it later.
                if self.IsRecording:
                    self.stop_record()  # Close file writers

                self.frame = make_blank_frame(f"{self.box_id} Camera lost connection")
                # Warn user that something is wrong.
                printt(
                    f"Unable to read box {self.box_id}'s camera. Did it come unplugged?")

                # Remove camera resources
                self.release()
                nextRetry = time.time() + 5
                continue

            count_cycle += 1

            if count_cycle == count_interval:
                count_cycle = 0
                count_sent_frames += 1
                if self.q.qsize() > 250:
                    if frame_time - last_dropped_frame_warning > 5:
                        # Only report to log file every 5 seconds
                        printt(f"DROPPING FRAME, box{self.box_id}, frame # {count_sent_frames}, time={frame_time - self.start_recording_time:.3f}s",
                               print_to_screen=False)
                        last_dropped_frame_warning = frame_time
                else:                
                    self.q.put((frame, frame_time, TTL_on, count_sent_frames))

        if DEBUG:
            printt(f"Box {self.box_id} exiting camera read (producer) thread.")

    def consumer_thread(self):

        now = time.time()
        last_warning_time = now
        prev_frames_received = 0
        reported_frame_size = False

        while not self.pending == self.PendingAction.Exiting:

            #
            try:
                frame, t, TTL, frame_count = self.q.get(timeout=0.5)
            except queue.Empty:
                # No frames received. Either camera is disconnected, or running slowly.
                # Either way, just keep going, and hope camera eventually reconnects.
                # Since timeout is 0.5 seconds, we will check twice a second until camera
                # is back online
                continue

            if not reported_frame_size:
                reported_frame_size = True
                res = np.shape(frame)
                printt(f"Camera {self.box_id} resolution is {res[1]} x {res[0]}")
            
            gap = frame_count - prev_frames_received
            prev_frames_received = frame_count
            
            if DEBUG and self.current_animal_ID == "StressTest":
                # Add massive flicker to truly stress out the recording and compression algorithm.
                # This will cause massive delays, and will crash the Pi in about 60 seconds unless
                # we start dropping frames
                if frame_count % 2 == 0:
                    frame = 1 - frame

            lag1 = time.time() - t
            self.CPU_lag_frames = lag1 * RECORD_FRAME_RATE

            if not self.IsRecording and lag1 > 2:
                # CPU is lagging, and we are not recording. Skip frame to help catch up.
                now = time.time()
                if now - last_warning_time > 5:
                    # Only report to log file every 5 seconds
                    printt(f"Warning: high CPU lag, box{self.box_id}, lag {lag1:.3f}s. Not recording so skipping frame",
                           print_to_screen=DEBUG)
                    last_warning_time = now
                continue

            self.process_one_frame(frame, t, TTL, gap=gap)

            lag2 = time.time() - t
            self.CPU_lag_frames = lag2 * RECORD_FRAME_RATE
                
            if lag2 > 2 or (DEBUG and frame_count % 300 == 0):
                now = time.time()
                if now - last_warning_time > 5:  # Only report every 2 seconds
                    # CPU lag (mostly from compression time) is theoretically harmless since queue size is infinite.
                    # However, if it exceeds 2 seconds then something is likely to be seriously
                    # wrong, and might not be recoverable.
                    printt(f"CPU lag, box{self.box_id}, frame # {self.frames_received}={t - self.start_recording_time:.3f}s, CPU lag {lag2:.2f}s={self.CPU_lag_frames:.1f} frames, processing time = {lag2 - lag1:.4f}s, queue size {self.q.qsize()}",
                           print_to_screen=DEBUG)
                    last_warning_time = now

        if DEBUG:
            printt(f"Box {self.box_id} exiting consumer thread.")

    def release(self):
        self.status = 0
        self.cam.release()
        self.cam = None

    def add_on_screen_info(self, frame):

        if self.current_animal_ID is not None:
            # Add animal ID to video
            # Location is (10,100) ... used to be at (10,90), but tended to overlap blue dot at (20,70)
            #   so I moved it down slightly to 10,100. Later moved to 60,30 to avoid overlapping cage.
            cv2.putText(frame, str(self.current_animal_ID),
                        (int(60 * FONT_SCALE), int(30 * FONT_SCALE)),
                        cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 128, 128),
                        round(FONT_SCALE + 0.5))  # Line thickness

        if self.frames_received > 0:
            # Add frame # to video. Scale down font to 70% since this number can be large.
            # Location was originally 10,140, now moved to (WIDTH/2)),30
            cv2.putText(frame, str(self.frames_received),
                        (int(WIDTH / 2), int(30 * FONT_SCALE)),
                        cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE * .7, (255, 128, 128),
                        round(FONT_SCALE + 0.5))  # Line thickness

    # Reads a single frame from CamObj class and writes it to file
    def process_one_frame(self, frame, timestamp, TTL_on, gap=1):

        with self.lock:

            if self.pending == self.PendingAction.ForceStop:
                self.pending = self.PendingAction.Nothing
                self.__stop_recording_now()
            if self.IsRecording and 0 < self.pending_stop_record_time < timestamp:
                self.pending_stop_record_time = 0
                self.__stop_recording_now()
            elif self.pending == self.PendingAction.StartRecord:
                self.pending = self.PendingAction.Nothing
                self.start_record()

            if self.cam is None or not self.cam.isOpened():
                return

            time_elapsed = timestamp - self.start_recording_time
            self.last_frame_received_elapsed_time = time_elapsed

            if self.IsRecording and time_elapsed >= 0:
                # Check if time_elapsed > 0, otherwise first couple of frames might be negative
                self.frames_received += gap
                if gap > 1:
                    self.dropped_recording_frames += (gap - 1)
                
            if self.IsRecording and time_elapsed >= 0:
                self.frames_recorded += 1

            if TTL_on:
                # Add blue dot to indicate that GPIO is active
                # Location is (20,70)
                cv2.circle(frame,
                           (int(20 * FONT_SCALE), int(70 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (255, 0, 0),  # Blue dot (color is in BGR order)
                           -1)  # -1 thickness fills circle

            if self.pending_start_timer > 0:
                # Add dark red dot to indicate that a start might be pending
                # Location is (20,50)
                self.pending_start_timer -= 1
                cv2.circle(frame,
                           (int(20 * FONT_SCALE), int(50 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (0, 0, 96),  # Dark red dot (color is in BGR order)
                           -1)  # -1 thickness fills circle

            if self.TTL_mode == self.TTL_type.Debug:
                # Green dot indicates we are in TTL DEBUG mode
                # Location is (20,160)
                cv2.circle(frame,
                           (int(20 * FONT_SCALE), int(160 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (0, 255, 0),  # color is in BGR order
                           -1)  # -1 thickness fills circle

            if SAVE_ON_SCREEN_INFO:
                # Add animal ID and frame number
                self.add_on_screen_info(frame)

            if RECORD_COLOR:
                self.frame = frame
            else:
                # Convert to grayscale
                self.frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if self.IsRecording and time_elapsed >= 0:
                if self.fid is not None:
                    try:
                        if DEBUG:
                            lag = time.time() - timestamp
                            self.fid.write(f"{self.frames_received}\t{time_elapsed}\t{lag}\n")
                        else:
                            self.fid.write(f"{self.frames_received}\t{time_elapsed}\n")
                    except Exception as e:
                        print(f'ERROR: {e}')
                        print(f"... while writing frame timestamp for camera {self.box_id}, frame {self.frames_received}. Will stop recording")
                        self.__stop_recording_now()
                        return

                try:
                    # Write frame to AVI video file if possible
                    if self.Writer is not None:
                        self.Writer.write(self.frame)
                        self.last_frame_written = self.frames_received
                except:
                    print(f"Unable to write video file for camera {self.box_id}. Will stop recording")
                    self.__stop_recording_now()

    def get_elapsed_time_string(self):

        elapsed_sec = self.last_frame_received_elapsed_time

        if elapsed_sec < 120:
            str1 = f"{elapsed_sec:.1f} s"
        else:
            elapsed_min = elapsed_sec / 60
            str1 = f"{elapsed_min:.2f} min"

        str1 += f", {self.frames_received} frames"

        if elapsed_sec > 5:
            fps1 = self.frames_received / elapsed_sec
            if abs(self.frames_received - self.frames_recorded) > 5:
                # Report fps for both received and recorded frames (latter will be slightly smaller)
                fps2 = self.frames_recorded / elapsed_sec
                str1 += f", {fps1:.2f}/{fps2:.2f} fps"
            else:
                # Report fps
                str1 += f", {fps1:.2f} fps"

        if self.Writer is not None:
            file_stats = os.stat(self.filename_video)
            file_size = file_stats.st_size
        else:
            file_size = 0

        str1 += f", {file_size / (1024 * 1024)}MB"

        if self.dropped_recording_frames > 0:
            str1 += f", >={self.dropped_recording_frames} dropped frames"

        return str1

    def take_snapshot(self):
        if self.cam is None or self.frame is None:
            return False
        if self.cam.isOpened():

            index = 1
            while True:
                # Snapshot prefix is usually just camera number
                # We also add a numerical suffix 1, 2, 3, ... to make every snapshot filename
                # unique
                fpath = self.get_filename_prefix(add_date=False) + "_" + str(index) + ".png"
                
                if not os.path.exists(fpath):
                    # Found a filename not already used
                    break

                index += 1

            d, f = os.path.split(fpath)
            fpath = tkinter.filedialog.asksaveasfilename(confirmoverwrite=True, initialfile=f, initialdir=d)

            if fpath == '' or fpath == ():
                # Windows returns zero-length string, while Pi returns empty tuple
                printt('User canceled save')
                return ''
            
            if not fpath.endswith('.png'):
                fpath = fpath + '.png'

            cv2.imwrite(fpath, self.frame)

            printt(f'Wrote snapshot to file {fpath}')
            return fpath
        else:
            return None

    def close(self):

        # Only call this when exiting program. Will stop all recordings, and release camera resources

        if self.IsRecording:
            self.stop_record(force=True)  # This will immediately stop recording. Queued frames may be lost.
            while self.IsRecording:
                time.sleep(0.1)

        self.pending = self.PendingAction.Exiting

        # Wait for all threads to exit.

        if self.thread_producer is not None:
            self.thread_producer.join()

        if self.thread_consumer is not None:
            self.thread_consumer.join()

        if self.thread_GPIO is not None:
            self.thread_GPIO.join()

        if self.cam is not None:
            try:
                # Release camera resources
                self.cam.release()
            except:
                pass
            self.cam = None

        self.status = -1
        self.frame = None

        if DEBUG:
            printt(f"Box {self.box_id} has closed.")


if __name__ == '__main__':
    print("CamObj.py is a helper file, intended to be imported from WEBCAM_RECORD.py, not run by itself")
