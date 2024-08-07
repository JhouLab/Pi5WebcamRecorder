from __future__ import annotations  # Need this for type hints to work on older Python versions

import configparser
import datetime
import math
import multiprocessing
import os
import platform
import queue
import subprocess
import threading
import time
from ast import literal_eval as make_tuple  # Needed to parse resolution string in config
from enum import Enum
from sys import gettrace
from typing import List

import numpy as np
import psutil  # This is used to obtain disk free space

import extra.shared_arrays


#
# This file is intended to be imported by webcam_recorder.py
#
# It mainly contains the CamObj class, which helps manage independent
# USB cameras.
#
# On Raspberry Pi and Windows, this just works.
#
# On Windows Subsystem for Linux (WSL), need to first install usbipd-win:
# https://learn.microsoft.com/en-us/windows/wsl/connect-usb#prerequisites
# Then you might have to install kernel drivers:
# https://github.com/dorssel/usbipd-win/wiki/WSL-support
# https://github.com/dorssel/usbipd-win/wiki/WSL-support

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')
IS_PI5 = False

USE_MULTI_PROCESS = True

if IS_LINUX:

    try:
        r = subprocess.run(['uname', '-m'], stdout=subprocess.PIPE)
        cpu_type = r.stdout
        IS_PI5 = cpu_type.startswith(b'aarch64')
    except:
        pass

if IS_PI5:
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

SHOW_ANIMAL_ID_ON_VIDEO: int = configParser.getint('options', 'SHOW_ANIMAL_ID_ON_VIDEO', fallback=1)
SHOW_FRAME_NUMBER_ON_VIDEO: int = configParser.getint('options', 'SHOW_FRAME_NUMBER_ON_VIDEO', fallback=1)

is_debug: int = configParser.getint('options', 'DEBUG', fallback=DEBUG)
DEBUG = is_debug == 1

# Number of seconds to discriminate between binary 0 and 1
BINARY_BIT_PULSE_THRESHOLD = 0.05

FONT_SCALE = HEIGHT / 480


def get_date_string():
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    hour = '{:02d}'.format(now.hour)
    minute = '{:02d}'.format(now.minute)
    day_month_year = '{}-{}-{}_{}{}'.format(year, month, day, hour, minute)

    return day_month_year


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


filename_log = DATA_FOLDER + get_date_string() + "_log.txt"

try:
    # Create text file for frame timestamps
    fid_log = open(filename_log, 'w')
    print("Logging events to file: \'" + filename_log + "\'")
except:
    print(
        "Unable to create log file: \'" + filename_log + "\'.\n  Please make sure folder exists and that you have permission to write to it.")


# Write text to both screen and log file. The log file helps retrospectively figure out what happened when debugging.
def printt(txt, omit_date_time=False, close_file=False):
    # Get the current date and time
    if not omit_date_time:
        now = datetime.datetime.now()

        if DEBUG:
            s = now.strftime("%Y-%m-%d %H:%M:%S.%f: ") + txt
        else:
            s = now.strftime("%Y-%m-%d %H:%M:%S: ") + txt
    else:
        s = txt
    print(s, flush=True)  # Child process needs explicit flush or else won't show right away
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


# Status codes in messages from camera
class CamReadStatus(Enum):
    FrameFailed = 1
    GPIO_detected = 2
    ReadyForOperation = 3  # This message indicates that profiling is done (or was not needed)


# Info that is shared between Source and Destination processes
class CamInfo:
    id_num = -1  # ID number assigned by operating system. May be unpredictable.
    box_id = -1  # User-friendly camera ID. Will usually be USB port position/screen position, starting from 1
    GPIO_pin = -1  # Which GPIO pin corresponds to this camera? First low-high transition will start recording.
    queue_status: multiprocessing.Queue = None
    shared_memory_queue_frames: extra.shared_arrays.TimestampedArrayQueue = None
    queue_commands: multiprocessing.Queue = None

    def __init__(self, id_num=-1, box_id=-1, GPIO_pin=-1,
                 shared_memory_queue_frames=None, queue_commands=None, queue_status=None):
        self.id_num = id_num
        self.box_id = box_id
        self.GPIO_pin = GPIO_pin
        self.queue_status = queue_status
        self.shared_memory_queue_frames = shared_memory_queue_frames
        self.queue_commands = queue_commands

    def make_copy(self, c: CamInfo):
        if c is not None:
            self.id_num = c.id_num
            self.box_id = c.box_id
            self.GPIO_pin = c.GPIO_pin
            self.queue_status = c.queue_status
            self.shared_memory_queue_frames = c.shared_memory_queue_frames
            self.queue_commands = c.queue_commands


class CamDestinationObj(CamInfo):

    status = 0  # 1 if camera is operational and connected, 0 if not

    frame = None  # Most recent video frame. If camera lost connection, this will be a black frame with some text
    filename_video: str = "Video.avi"
    filename_timestamp = "Timestamp.txt"
    filename_timestamp_TTL = "Timestamp_TTL.txt"

    # Various file writer objects
    Writer = None  # Writer for video file
    fid = None  # Writer for timestamp file
    fid_TTL = None  # Writer for TTL timestamp file

    start_recording_time = -1  # Timestamp (in seconds) when recording started.
    IsRecording = False

    frame_num = -1  # Number of frames recorded so far.

    class TTL_type(Enum):
        Normal = 0
        Binary = 1
        Checksum = 2
        Debug = 3

    class PendingAction(Enum):
        Nothing = 0
        StartRecord = 1
        EndRecord = 2
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

    def __init__(self, c: CamInfo):
        super().__init__()

        super().make_copy(c)

        self.has_cam = self.id_num >= 0
        self.CPU_lag_frames = 0
        self.pending = self.PendingAction.Nothing
        self.cam_lock = threading.RLock()
        self.need_update_button_state_flag = None
        self.lock = threading.RLock()  # Reentrant lock, so same thread can acquire more than once.
        self.TTL_mode = self.TTL_type.Normal

        # This becomes True after camera fps profiling is done, or determined not to be needed,
        # and process_frame() loop has started. This prevents GUI stuff from slowing down the profiling.
        self.IsReady = False

        # Use blank frame for this object if no camera object is specified
        self.frame = make_blank_frame(f"{self.box_id} - No camera connected")

        if self.GPIO_pin >= 0 and platform.system() == "Linux":
            # Start monitoring GPIO pin
            try:
                GPIO.setup(self.GPIO_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                GPIO.add_event_detect(self.GPIO_pin, GPIO.BOTH, callback=self.GPIO_callback)
                printt(f'Cam {self.box_id} monitoring GPIO pin {self.GPIO_pin}')
            except RuntimeError:
                printt("Runtime Error: Unable to set up GPIO.")
                print("    Please make sure there are no other processes using the GPIO hardware.")
                print("    If this is a Pi5, make sure you have replaced the default gpio library as follows:")
                print("    sudo apt remove python3-rpi.gpio")
                print("    sudo apt install python3-rpi-lgpio")
                exit()

    def start_consumer_thread(self):

        # Start thread that will process the frames sent by this loop.
        # This allows read_camera_continuous(), i.e. this thread, to
        # run at max speed.
        if self.shared_memory_queue_frames is not None:
            t = threading.Thread(target=self.process_loop)
            t.start()

    def GPIO_callback(self, param):

        t = time.time()
        v = GPIO.input(param)
        self.queue_commands.put((CameraCommands.GPIO, t, v))
        if v:
            self.GPIO_rising_edge(t)
        else:
            self.GPIO_falling_edge(t)

    # New GPIO pattern as of 6/22/2024
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
    def GPIO_rising_edge(self, timestamp):

        # Detected rising edge. Log the timestamp so that on falling edge we can see if this is a regular
        # pulse or a LONG pulse that starts binary mode
        self.most_recent_gpio_rising_edge_time = timestamp
        off_time = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time

        # This is used to show blue dot on next frame.
        self.GPIO_active = 1

        if off_time > 0.1:
            # Burst TTLs must have ~50ms gap.
            self.num_consec_TTLs = 0
            if VERBOSE:
                printt(f'Num consec TTLs: 0')

        if self.TTL_mode == self.TTL_type.Binary:
            # If already in binary mode, then long (0.2s) "off" period switches to checksum mode for final pulse
            if 0.15 < off_time < 0.5:
                if self.TTL_binary_bits != 16:
                    printt(f'Warning: in binary mode received {self.TTL_binary_bits} bits instead of 16')
                    self.current_animal_ID = "Unknown"

                if DEBUG:
                    printt('Binary mode now awaiting final checksum...')
                self.TTL_mode = self.TTL_type.Checksum
            elif off_time >= 0.5:
                printt(f'Very long pause of {off_time}s detected (max should be 0.2s to end binary mode)')
                self.TTL_mode = self.TTL_type.Normal
        elif self.TTL_mode == self.TTL_type.Debug:
            # In debug mode, all gaps should be 25ms
            off_time = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time
            if off_time > 1:
                # Cancel debug mode
                self.TTL_mode = self.TTL_type.Normal
                printt(f'Exiting DEBUG TTL mode with pause length {off_time}')
            elif off_time < 0.015 or off_time > 0.035:
                printt(f'{self.TTL_debug_count} off time {off_time}, expected 0.025')

        return

    def GPIO_falling_edge(self, timestamp):

        # Detected falling edge
        self.most_recent_gpio_falling_edge_time = timestamp

        # Cancel blue dot display on video
        self.GPIO_active = 0

        if self.most_recent_gpio_rising_edge_time < 0:
            # Ignore falling edge if no rising edge was detected. Is this even possible, e.g. at program launch?
            return

        # Calculate pulse width
        on_time = time.time() - self.most_recent_gpio_rising_edge_time

        if on_time < 0.01:
            # Ignore very short pulses, which are probably some kind of mechanical switch bounce
            # But: sometimes these are a result of pulses piling up in Windows, then getting sent all at once.
            return

        if self.TTL_mode == self.TTL_type.Normal:
            # In normal (not binary or checksum) mode, read the following types of pulses:
            # 0.1s on-time (range 0.01-0.2) indicates trial start, or session start/stop if doubled/tripled
            # 0.3s on time (range 0.2-0.4) initiates binary mode (USED TO BE 0.2s)
            # 0.4s-2s ... ignored
            # 2.5s (range 2.4-2.6s) starts DEBUG TTL mode
            # >3s ... ignored
            if on_time < 0.2:
                self.num_consec_TTLs += 1
                if VERBOSE:
                    printt(f'Num consec TTLs: {self.num_consec_TTLs}')
                self.handle_GPIO()
            elif on_time < 0.4:
                if DEBUG:
                    printt('Starting binary mode')
                self.TTL_mode = self.TTL_type.Binary
                self.current_animal_ID = "Pending"
                self.TTL_tmp_ID = 0
                self.TTL_binary_bits = 0
                self.TTL_checksum = 0
            elif 2.4 < on_time < 2.6 and DEBUG:
                # Extra long pulse starts debug testing mode
                self.TTL_mode = self.TTL_type.Debug
                printt(f'Entering DEBUG TTL mode with pulse length {on_time}s')
                self.TTL_debug_count = 0

            return

        elif self.TTL_mode == self.TTL_type.Checksum:
            # Final pulse of either 75 or 25ms to end binary mode.
            if on_time < BINARY_BIT_PULSE_THRESHOLD:
                checksum = 0
            elif on_time < 0.15:
                # 75ms pulse indicates ONE
                checksum = 1
            else:
                printt(
                    f"Received animal ID {self.TTL_tmp_ID} for box {self.box_id}, but checksum duration too long ({on_time} instead of 0-0.075s).")
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
            return

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
                if on_time > 0.1:
                    printt('Warning: Binary pulse width is longer than 100ms.')
                    # Pulse width over 0.1s is ERROR, and aborts binary mode?

            return
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
                    try:
                        self.fid_TTL.write(f"{self.TTL_num}\t{gpio_onset_time}\t{gpio_offset_time}\n")
                    except:
                        print(f"Unable to write TTL timestamp file for camera {self.box_id}")
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
    def verify_directory(self):
        # get custom version of datetime for folder search/create
        now = datetime.datetime.now()
        year = '{:04d}'.format(now.year)
        month = '{:02d}'.format(now.month)
        day = '{:02d}'.format(now.day)
        date = '{}-{}-{}'.format(year, month, day)

        target_path = os.path.join(DATA_FOLDER, date)
        try:
            if not os.path.isdir(target_path):
                os.mkdir(target_path)
                print("Created save folder at: ", target_path)
            return target_path
        except Exception as ex:
            print(f"Error while attempting to create folder {target_path}")
            print("    Error type is: ", ex.__class__.__name__)
            return ''  # This will force file to go to program folder

    def get_filename_prefix(self):
        path = self.verify_directory()

        if self.current_animal_ID is not None:
            prefix_ending = f"Box{self.box_id}_" + str(self.current_animal_ID)
        else:
            # No TTL-transmitted animal ID, just use box ID in filename
            prefix_ending = f"Box{self.box_id}"

        filename = get_date_string() + "_" + prefix_ending
        return os.path.join(path, filename)

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

        if not self.has_cam:
            print(f"Camera {self.box_id} is not available for recording.")
            return False

        # Camera reads occur on a dedicated thread for each cam object.
        # However, start_record is usually called from either the main GUI thread,
        # or the GPIO callback thread. So need to acquire locks to make sure
        # the three threads don't conflict.
        with self.lock:
            if not self.IsRecording:
                self.frame_num = 0
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

                prefix_extra = ""
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
                                prefix_extra = f"_{suffix_count}"

                            self.filename_video = prefix + prefix_extra + "_Video.avi"

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
                except:
                    print(f"Warning: unable to create video file: '{self.filename_video}'")
                    return False

                self.filename_timestamp = prefix + prefix_extra + "_Frames.txt"
                self.filename_timestamp_TTL = prefix + prefix_extra + "_TTLs.txt"

                if not self.Writer.isOpened():
                    # If codec is missing, we might get here. Usually OpenCV will have reported the error already.
                    print(f"Warning: unable to create video file: '{self.filename_video}'")
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
                    self.fid_TTL.write('TTL_event_number\tONSET (seconds)\tOFFSET (seconds)\n')
                except:
                    print("Warning: unable to create text file for TTL timestamps")

                    # Close the previously-created writer objects
                    self.fid.close()
                    self.Writer.release()
                    return False

                self.start_recording_time = time.time()

                # Set this flag last
                self.IsRecording = True

                printt(f"Started recording camera {self.box_id} to file '{self.filename_video}'")

                # This allows us to change button state
                self.need_update_button_state_flag = True

                return True

    def stop_record(self):

        # Set flag so that camera loop will stop recording on the next frame
        self.pending = self.PendingAction.EndRecord

    def __stop_recording_now(self):

        # Close and release all file writers immediately.
        with self.lock:

            # Acquire lock to avoid starting a new recording
            # in the middle of stopping the old one.

            self.current_animal_ID = None

            if self.IsRecording:
                self.IsRecording = False
                printt(f"Stopping recording camera {self.box_id} after " + self.get_elapsed_time_string())

            self.need_update_button_state_flag = True

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

    def process_loop(self):

        printt(f"Cam {self.box_id} consumer thread started.")

        last_warning_time = time.time()
        frame_count = 0
        loop_count = 0

        while self.pending != self.PendingAction.Exiting:

            loop_count += 1

            if loop_count % 5 == 0:

                try:
                    cmd, t, v = self.queue_status.get_nowait()

                except queue.Empty:

                    cmd = -1
                    t = -1
                    v = False

                if cmd != -1:
                    if DEBUG:
                        printt(f'Cam {self.box_id} received command {cmd}')

                    if cmd == CamReadStatus.ReadyForOperation.value:
                        self.IsReady = True
                        self.status = True
                    elif cmd == CamReadStatus.FrameFailed.value:
                        # Camera has become disconnected
                        self.status = False
                        self.has_cam = False
                        printt(f"Cam {self.box_id} has become disconnected.")
                        self.frame = make_blank_frame(f"Cam {self.box_id} is disconnected.")
                        time.sleep(0.1)
                        continue

            try:
                timestamp, self.frame, TTL_on = self.shared_memory_queue_frames.get(timeout=0.1)
            except queue.Empty:
                # If empty, then most likely we are shutting down.
                # Just spin every 0.1 seconds to handle Exiting flag
                continue

            self.process_frame(timestamp, TTL_on)

            lag = time.time() - timestamp
            self.CPU_lag_frames = lag * RECORD_FRAME_RATE

            if self.IsRecording and self.CPU_lag_frames > 4:
                now = time.time()
                if now - last_warning_time > 2.0:
                    # Warn at most every 2 seconds if CPU is lagging
                    printt(f"Warning: box{self.box_id} cpu lag approx {self.CPU_lag_frames:.1f} frames")
                    last_warning_time = now

            frame_count += 1
            if frame_count % (RECORD_FRAME_RATE * 5) == 0:
                if VERBOSE:
                    printt(f"Box {self.box_id} process loop is alive")

        try:
            while True:
                self.shared_memory_queue_frames.get(block=False)
        except queue.Empty:
            pass

        if DEBUG:
            printt(f"Box {self.box_id} consumer thread EXITING.")

        self.pending = self.PendingAction.Nothing

    # Reads a single frame from CamObj class and writes it to file
    def process_frame(self, timestamp, TTL_on):

        with self.lock:

            if self.pending == self.PendingAction.EndRecord:
                self.pending = self.PendingAction.Nothing
                self.__stop_recording_now()
            elif self.pending == self.PendingAction.StartRecord:
                self.pending = self.PendingAction.Nothing
                self.start_record()

            if TTL_on:
                # Add blue dot to indicate that GPIO is active
                # Location is (20,70)
                cv2.circle(self.frame,
                           (int(20 * FONT_SCALE), int(70 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (255, 0, 0),  # Blue dot (color is in BGR order)
                           -1)  # -1 thickness fills circle

            if self.pending_start_timer > 0:
                # Add dark red dot to indicate that a start might be pending
                # Location is (20,50)
                self.pending_start_timer -= 1
                cv2.circle(self.frame,
                           (int(20 * FONT_SCALE), int(50 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (0, 0, 96),  # Dark red dot (color is in BGR order)
                           -1)  # -1 thickness fills circle

            if self.TTL_mode == self.TTL_type.Debug:
                # Green dot indicates we are in TTL DEBUG mode
                # Location is (20,160)
                cv2.circle(self.frame,
                           (int(20 * FONT_SCALE), int(160 * FONT_SCALE)),  # x-y position
                           int(8 * FONT_SCALE),  # Radius
                           (0, 255, 0),  # color is in BGR order
                           -1)  # -1 thickness fills circle

            if self.current_animal_ID is not None and SHOW_ANIMAL_ID_ON_VIDEO:
                # Add animal ID to video
                # Location is (10,100) ... used to be at (10,90), but tended to overlap blue dot at (20,70)
                #   so I moved it down slightly to 10,100. Later moved to 60,30 to avoid overlapping cage.
                cv2.putText(self.frame, str(self.current_animal_ID),
                            (int(60 * FONT_SCALE), int(30 * FONT_SCALE)),
                            cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 128, 128),
                            round(FONT_SCALE + 0.5))  # Line thickness

            time_elapsed = timestamp - self.start_recording_time

            if self.IsRecording and time_elapsed >= 0 and SHOW_FRAME_NUMBER_ON_VIDEO:
                # Just checked if time_elapsed > 0, otherwise first couple of frames might be negative

                self.frame_num += 1

                # Add frame # to video. Scale down font to 70% since this number can be large.
                # Location was originally 10,140, now moved to (WIDTH/2)),30
                cv2.putText(self.frame, str(self.frame_num),
                            (int(WIDTH / 2), int(30 * FONT_SCALE)),
                            cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE * .7, (255, 128, 128),
                            round(FONT_SCALE + 0.5))  # Line thickness

            if not RECORD_COLOR and self.frame is not None:
                # Convert to grayscale
                self.frame = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)

            if self.IsRecording and time_elapsed >= 0:
                # Again, we only write frames if time_elapsed >= 0, since first couple of
                # frames might have negative values

                if self.fid is not None and self.start_recording_time > 0:
                    try:
                        self.fid.write(f"{self.frame_num}\t{time_elapsed}\n")
                    except:
                        print(f"Unable to write text file for camera f{self.box_id}. Will stop recording")
                        self.__stop_recording_now()
                        return

                try:
                    # Write frame to AVI video file if possible
                    if self.Writer is not None:
                        self.Writer.write(self.frame)
                except:
                    print(f"Unable to write video file for camera {self.box_id}. Will stop recording")
                    self.__stop_recording_now()

    def get_elapsed_recording_time(self, include_cam_num=False):

        if self.Writer is not None:
            file_stats = os.stat(self.filename_video)
            file_size = file_stats.st_size
        else:
            file_size = 0

        if include_cam_num:
            str1 = f"Camera {self.box_id} elapsed: {self.get_elapsed_time_string()}, {file_size / (1024 * 1024)}MB"
        else:
            str1 = f"Elapsed: {self.get_elapsed_time_string()}, {file_size / (1024 * 1024)}MB"
        return str1

    def get_elapsed_time_string(self):

        elapsed_sec = time.time() - self.start_recording_time

        if elapsed_sec < 120:
            str1 = f"{elapsed_sec:.1f} seconds"
        else:
            elapsed_min = elapsed_sec / 60
            str1 = f"{elapsed_min:.2f} minutes"

        str1 += f", {self.frame_num} frames"

        if elapsed_sec > 5:
            fps = self.frame_num / elapsed_sec
            return str1 + f", {fps:.2f} fps"
        else:
            return str1

    def take_snapshot(self):
        if self.has_cam:

            index = 1
            while True:
                fname = self.get_filename_prefix() + "_snapshot_" + str(index) + ".jpg"

                if not os.path.exists(fname):
                    break

                index += 1

            cv2.imwrite(fname, self.frame)

            printt(f'Wrote snapshot to file {fname}')
            return fname
        else:
            return None

    def close(self):

        # Only call this when exiting program. Will stop all recordings, and release camera resources

        if self.IsRecording:
                
            if DEBUG:
                printt(f"Box {self.box_id} consumer waiting for recording to end.")

            self.stop_record()  # This will set flag to be read by process_frame() thread
            while self.IsRecording:
                time.sleep(0.1)

        if self.has_cam:
            try:
                self.queue_commands.put((CameraCommands.Exit, 0, 0))
            except:
                pass
            self.has_cam = False

            # Wait for the camera read threads to exit
            time.sleep(0.1)

        self.pending = self.PendingAction.Exiting

        self.status = -1


# Commands that can be sent to the CameraRead process/threads
class CameraCommands(Enum):

    Exit = 1
    GPIO = 2


class CamReaderObj(CamInfo):

    t: threading.Thread | None = None
    cam: cv2.VideoCapture | None = None

    GPIO_active = False

    def __init__(self, c: CamInfo):
        super().__init__()
        
        super().make_copy(c)

        if platform.system() == "Windows":
            self.cam = cv2.VideoCapture(self.id_num,
                                        cv2.CAP_DSHOW)  # On Windows, CAP_DSHOW greatly speeds up detection
        else:
            self.cam = cv2.VideoCapture(self.id_num,
                                        cv2.CAP_V4L2)  # This makes MJPG mode work, allowing higher frame rates

        if self.cam.isOpened():
            self.t = threading.Thread(target=self.read_one_cam_continuous)
            self.t.start()
            printt(f"Camera {self.box_id} reader (producer) thread started.")
        else:
            self.cam = None
            # No camera connected
            if DEBUG:
                printt(f"Camera {self.box_id} not connected, won't profile or read.")
        
    def GPIO_callback(self, param):
        
        if DEBUG:
            printt(f'Cam {self.box_id} received GPIO on pin {param}')

        # Param is the pin number, value is either True or False, to indicate High/Low
        if GPIO.input(param):
            if VERBOSE or DEBUG:
                printt('GPIO on')
            self.GPIO_active = True
            self.queue_commands.put((CamReadStatus.GPIO_detected, time.time(), True))
        else:
            if VERBOSE or DEBUG:
                printt('GPIO off')
            self.GPIO_active = False
            self.queue_commands.put((CamReadStatus.GPIO_detected, time.time(), False))

    def profile_fps(self):

        # First frame always takes longer to read, so get it out of the way
        # before conducting profiling
        t1 = time.time()
        self.cam.read()

        t2 = time.time()
        if DEBUG:
            # Oddly, can take between .5 and .8 seconds to read first frame.
            print(f"Cam {self.box_id} first frame read elapsed {t2 - t1:.4f} sec")

        # Subsequent frames might actually read too fast, if they are coming
        # from internal memory buffer. So now clear out any frames in camera buffer
        old_time = time.time()
        num_pre_read = 0
        while True:
            self.cam.read()
            new_time = time.time()
            elapsed = new_time - old_time
            old_time = new_time
            num_pre_read += 1
            if elapsed > 0.01:
                # Buffered frames will return very quickly. We wait until
                # the return time is longer, indicating that buffer is now empty
                break

        if DEBUG:
            print(f"Cam {self.box_id} pre-read-count = {num_pre_read} frames, elapsed {new_time - t2:.4f} sec")

        old_time = time.time()
        target_time = old_time + 1.0  # When to stop profiling
        frame_count = 0
        min_elapsed4 = 1000

        # Read frames for 1 second to estimate frame rate
        while time.time() < target_time:

            self.cam.read()

            new_time = time.time()

            frame_count += 1
            if frame_count % 4 == 0:
                elapsed = new_time - old_time
                if elapsed > 0.06:
                    if elapsed < min_elapsed4:
                        # Finds minimum interval between any 4 frames
                        min_elapsed4 = elapsed
                old_time = new_time

        if min_elapsed4 < 1000:
            # Upper bound on frame rate
            estimated_frame_rate = 4.0 / min_elapsed4
            # Lower bound on frame rate
            estimated_frame_rate2 = frame_count
            printt(
                f'Box {self.box_id} estimated frame rate between {estimated_frame_rate2} and {estimated_frame_rate} fps')
        else:
            # Unable to determine frame rate
            printt("Unable to determine frame rate, defaulting to config setting")
            estimated_frame_rate = RECORD_FRAME_RATE

        # Sometimes will get value slightly lower or higher than real frame rate, e.g. 29.9 or 30.2 instead of 30
        if estimated_frame_rate > 55:
            estimated_frame_rate = 60
        elif estimated_frame_rate > 27:
            estimated_frame_rate = 30
        elif estimated_frame_rate > 22:
            estimated_frame_rate = 24
        elif estimated_frame_rate > 18:
            estimated_frame_rate = 20
        elif estimated_frame_rate > 13:
            estimated_frame_rate = 15
        elif estimated_frame_rate > 8.5:
            estimated_frame_rate = 10
        elif estimated_frame_rate > 6.5:
            estimated_frame_rate = 7.5
        else:
            estimated_frame_rate = 5

        printt(f'Rounded frame rate to {estimated_frame_rate}')

        return estimated_frame_rate

    def read_one_cam_continuous(self):

        if NATIVE_FRAME_RATE == 0:
            native_fps = self.profile_fps()
        else:
            native_fps = NATIVE_FRAME_RATE

        self.queue_status.put((CamReadStatus.ReadyForOperation.value, time.time(), True))

        count = 0
        frame_count = 0

        # Downsampling interval. Must be integer, hence use of ceiling function
        count_interval = math.ceil(native_fps / RECORD_FRAME_RATE)

        # This is here just to keep PyCharm from issuing warning at line 1196
        frame = None
        TTL_on = None

        while True:

            try:
                cmd, t, val = self.queue_commands.get(block=False)
                if cmd == CameraCommands.Exit:
                    break
                elif cmd == CameraCommands.GPIO:
                    self.GPIO_active = val
                    lag = time.time() - t
                    if DEBUG:
                        printt(f'Cam {self.box_id} TTL queue lag {lag:.4f}s')
            except queue.Empty:
                pass

            if self.cam is not None and self.cam.isOpened():
                try:
                    # Read frame if camera is available and open
                    status, frame = self.cam.read()
                    TTL_on = self.GPIO_active
                except:
                    # Set flag that will cause loop to exit shortly
                    status = False
            else:
                status = False
                time.sleep(0.05)

            if not status:
                # Read failed. Remove this camera so we won't attempt to read it later.
                # Should we set a flag to try to periodically reconnect?

                # Remove camera resources
                if self.cam is not None:
                    self.cam.release()
                    self.cam = None
                    if DEBUG:
                        printt(f"Unable to read camera in box {self.box_id}.")
                    self.queue_status.put((CamReadStatus.FrameFailed.value, time.time(), False))
                    break

            count += 1
            if count == count_interval:
                count = 0
                self.shared_memory_queue_frames.put(frame, TTL_on)

            frame_count += 1

        if DEBUG:
            printt(f"Box {self.box_id} producer thread EXITING.")


# SOURCE process, that is the source of frame data. This spawns up to 4
# threads, each of which reads a single camera and puts frames into a queue
# for consumption by the DESTINATION process.
def source_process(CamInfo_array: List[CamInfo]):
    #
    # This is a separate PROCESS that is dedicated to reading frames from
    # the USB ports, and also polling GPIO
    #
    # This has to be separate from the rest of the program, in order that
    # it can have a higher priority. This is an annoying limitation of Python,
    # that there is no way to set individual thread priorities separately, so
    # this has to be a separate process.
    #

    # This should be run AFTER the cam_obj array has been created, so that we don't
    # start producing frames until there is a handler that can process them.

    if IS_LINUX:
        try:
            os.nice(-20)
        except:
            print('Unable to raise priority. Please run as administrator for optimal performance')
    elif IS_WINDOWS:
        import win32api
        import win32process
        import win32con

        pid = win32api.GetCurrentProcessId()
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
        win32process.SetPriorityClass(handle, win32process.REALTIME_PRIORITY_CLASS)

    c: List[CamReaderObj] = []

    for idx, cam_info in enumerate(CamInfo_array):
        if cam_info is not None and cam_info.id_num >= 0:
            c.append(CamReaderObj(cam_info))
            # Short sleep so that cameras will finish in numerical order
            time.sleep(0.25)

    if DEBUG:
        printt("Child (source) process setup complete. Producer threads will run until program exits.")
        
    for cr in c:
        cr.t.join()
        
    if DEBUG:
        printt("Child process (producer) threads have all ended, child process itself will now exit")


if __name__ == '__main__':
    print("CamObj.py is a helper file, intended to be imported from WEBCAM_RECORD.py, not run by itself")
