from __future__ import annotations   # Need this for type hints to work on older Python versions

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

from typing import List
import os
import psutil        # This is used to obtain disk free space
import numpy as np
import time
import datetime
import platform
import threading
import subprocess
from sys import gettrace
import configparser
from enum import Enum

USE_FFMPEG = False

if USE_FFMPEG:
    # Experimental feature ... I had hoped this would give more flexibility for saving greyscale to
    # reduce file sizes. But it doesn't seem to help, and doesn't install at all on Raspberry Pi.
    # Note also that ffmpeg-python is just a wrapper for ffmpeg, which must already be installed separately.
    import ffmpeg      # On Pycharm/Windows, install ffmpeg-python from Karl Kroening.
    

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_PI5 = False

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
    import RPi.GPIO as GPIO

os.environ["OPENCV_LOG_LEVEL"] = "FATAL"  # Suppress warnings that occur when camera id not found. This statement must occur before importing cv2

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

FRAME_RATE_PER_SECOND: float = configParser.getfloat('options', 'FRAME_RATE_PER_SECOND', fallback=10)
HEIGHT = configParser.getint('options', 'HEIGHT', fallback=480)
WIDTH = configParser.getint('options', 'WIDTH', fallback=640)
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

        if DEBUG:
            s = now.strftime("%Y-%m-%d %H:%M:%S.%f: ") + txt
        else:
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


class CamObj:
    cam = None   # this is the opencv camera object
    id_num = -1  # ID number assigned by operating system. May be unpredictable.
    box_id = -1  # User-friendly camera ID. Will usually be USB port position/screen position, starting from 1
    status = -1  # True if camera is operational and connected
    frame = None  # Most recently obtained video frame. If camera lost connection, this will be a black frame with some text
    filename_video: str = "Video.avi"
    filename_timestamp = "Timestamp.txt"
    filename_timestamp_TTL = "Timestamp_TTL.txt"

    # Various file writer objects
    Writer = None    # Writer for video file
    fid = None       # Writer for timestamp file
    fid_TTL = None   # Writer for TTL timestamp file

    start_time = -1  # Timestamp (in seconds) when recording started.
    IsRecording = False
    GPIO_pin = -1    # Which GPIO pin corresponds to this camera? First low-high transition will start recording.

    frame_num = -1   # Number of frames recorded so far.

    class TTL_type(Enum):
        Normal = 0
        Binary = 1
        Checksum = 2
        Debug = 3

    # Class variables related to TTL handling
    TTL_num = -1               # Counts how many TTLs (usually indicating trial starts) have occurred in this session
    TTL_binary_bits = 0        # Ensures that we receive 16 binary bits
    TTL_animal_ID = 0
    TTL_tmp_ID = 0             # Temporary ID while we are receiving bits
    TTL_mode = None
    TTL_debug_count = 0
    TTL_checksum = 0
    most_recent_gpio_rising_edge_time = -1
    most_recent_gpio_falling_edge_time = -1
    num_consec_TTLs = 0   # Use this to track double and triple pulses

    # PyCharm intellisense gives warning on the next line, but it is fine.
    codec = cv2.VideoWriter_fourcc(*FOURCC)  # What codec to use. Usually h264
    resolution: List[int] = (WIDTH, HEIGHT)
    
    helper_thread = None  # This is used to close files without blocking main thread

    lock = None

    frames_to_mark_GPIO = 0    # Use this to add blue dot to frames when GPIO is detected
    pending_start_timer = 0    # This is used to show dark red dot temporarily while we are waiting to check if double pulse is actually double (i.e. no third pulse)

    def __init__(self, cam, id_num, box_id, max_fps, GPIO_pin=-1):
        self.need_update_button_state_flag = None
        self.process = None   # This is used if calling FF_MPEG directly. Probably won't use this in the future.
        self.cam = cam
        self.id_num = id_num
        self.box_id = box_id   # This is a user-friendly unique identifier for each box.
        self.max_fps = max_fps   # This is stored from value obtained from camera. It does not seem to be reliable.
        self.GPIO_pin = GPIO_pin
        self.lock = threading.RLock()  # Reentrant lock, so same thread can acquire more than once.
        self.TTL_mode = self.TTL_type.Normal

        if cam is None:
            # Use blank frame for this object if no camera object is specified
            self.frame = make_blank_frame(f"{box_id} - No camera found")

        if GPIO_pin >= 0 and platform.system() == "Linux":
            # Start monitoring GPIO pin
            GPIO.add_event_detect(GPIO_pin, GPIO.BOTH, callback=self.GPIO_callback_both)

    def GPIO_callback_both(self, param):
    
        if GPIO.input(param):
            if VERBOSE:
                printt('GPIO on')
            self.GPIO_callback1(param)
        else:
            if VERBOSE:
                printt('GPIO off')
            self.GPIO_callback2(param)

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
    def GPIO_callback1(self, param):

        # Detected rising edge. Log the timestamp so that on falling edge we can see if this is a regular
        # pulse or a LONG pulse that starts binary mode
        self.most_recent_gpio_rising_edge_time = time.time()
        elapsed = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time
        
        if elapsed > 0.1:
            # Burst TTLs must have ~50ms gap.
            if 0.5 > elapsed > 0.3:
                # Note that old MedPC had 0.4s gap between 0.1s pulses.
                # Check for back-compatibility
                return
            self.num_consec_TTLs = 0
            if VERBOSE:
                printt(f'Num consec TTLs: 0')

        if self.TTL_mode == self.TTL_type.Binary:
            # If already in binary mode, then long (0.2s) "off" period switches to checksum mode for final pulse
            if 0.15 < elapsed < 0.5:
                if self.TTL_binary_bits != 16:
                    printt(f'Warning: in binary mode received {self.TTL_binary_bits} bits instead of 16')
                    self.TTL_animal_ID = -1
                
                if DEBUG:
                    printt('Binary mode now awaiting final checksum...')
                self.TTL_mode = self.TTL_type.Checksum
            elif elapsed >= 0.5:
                printt(f'Very long pause of {elapsed}s detected (max should be 0.2s to end binary mode)')
                self.TTL_mode = self.TTL_type.Normal
        elif self.TTL_mode == self.TTL_type.Debug:
            # In debug mode, all gaps should be 25ms
            elapsed = self.most_recent_gpio_rising_edge_time - self.most_recent_gpio_falling_edge_time
            if elapsed > 1:
                # Cancel debug mode
                self.TTL_mode = self.TTL_type.Normal
                printt(f'Exiting DEBUG TTL mode with pause length {elapsed}')
            elif elapsed < 0.015 or elapsed > 0.035:
                printt(f'{self.TTL_debug_count} off time {elapsed}, expected 0.025')
                
        return

    def GPIO_callback2(self, param):

        # Detected falling edge
        self.most_recent_gpio_falling_edge_time = time.time()

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
            # 0.1s on-time (range 0.01-0.15): indicates trial start, or session start/stop if doubled/tripled
            # 0.2s on time (range 0.15-0.25) initiates binary mode
            # 0.3s-2s ... ignored
            # 2.5s (range >2s) starts DEBUG TTL mode
            if on_time < 0.15:
                self.num_consec_TTLs += 1
                if VERBOSE:
                    printt(f'Num consec TTLs: {self.num_consec_TTLs}')
                self.handle_GPIO()
            elif on_time < 0.25:
                if DEBUG:
                    printt('Starting binary mode')
                self.TTL_mode = self.TTL_type.Binary
                self.TTL_animal_ID = 0
                self.TTL_tmp_ID = 0
                self.TTL_binary_bits = 0
                self.TTL_checksum = 0
            elif on_time > 2.0 and DEBUG:
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
                printt(f"Received animal ID {self.TTL_tmp_ID} for box {self.box_id}, but checksum duration too long ({on_time} instead of 0-0.075s).")
                self.TTL_animal_ID = -1
                self.TTL_mode = self.TTL_type.Normal
                return

            if self.TTL_checksum == checksum:
                # Successfully received TTL ID
                self.TTL_animal_ID = self.TTL_tmp_ID
                printt(f'Received animal ID {self.TTL_animal_ID} for box {self.box_id}')
            else:
                printt(f"Received animal ID {self.TTL_tmp_ID} but checksum failed for box {self.box_id}")
                self.TTL_animal_ID = -1

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
        self.pending_start_timer = int(FRAME_RATE_PER_SECOND * wait_interval_sec + 1)

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
        # This will actually be the falling edge of pulse.

        # Use rising edge time, since we don't get here until falling edge.
        # NOte that time.time() returns number of seconds since 1970, as a floating point number.
        gpio_time = self.most_recent_gpio_rising_edge_time

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
                    # We have detected a double pulse. Start thread that makes sure this
                    # isn't just the beginning of a triple pulse, and if confirmed, will start session

                    t = threading.Thread(target=self.delayed_start)

                    t.start()

                # Not recording, and only detected a single TTL pulse. Just ignore.
                return

            else:
                # Calculate TTL timestamp relative to session start
                gpio_time_relative = gpio_time - self.start_time

                self.TTL_num += 1
                if self.fid_TTL is not None:
                    try:
                        self.fid_TTL.write(f"{self.TTL_num}\t{gpio_time_relative}\n")
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

    #verifies that there is an appropriate directory to save the recording in. if there is not, create it and save that as location
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
                print("Folder was not found, but created at: ", target_path)
            return target_path
        except Exception as ex:
            print(f"Error while attempting to create folder {target_path}")
            print("    Error type is: ", ex.__class__.__name__)
            return ''    # This will force file to go to program folder

    def get_filename_prefix(self, animal_ID=None):
        path = self.verify_directory()

        if animal_ID is None or animal_ID == "":
            if self.TTL_animal_ID > 0:
                animal_ID = str(self.TTL_animal_ID)
            else:
                animal_ID = f"Cam{self.box_id}"

        filename = get_date_string() + "_" + animal_ID
        return os.path.join(path, filename)

    def save_video(self, saving_file_name, fps):

        process = (
            ffmpeg
            .input('pipe:', format='rawvideo', pix_fmt='rgb24', s='{}x{}'.format(WIDTH, HEIGHT))
            .output(saving_file_name, pix_fmt='yuv420p', vcodec='libx264', r=fps, crf=28)  # Lower CRF values give better quality. Valid range is 1-51
            .overwrite_output()
            .run_async(pipe_stdin=True)
        )

        return process

    def start_record(self, animal_ID=None, stress_test_mode=False):

        if self.cam is None or not self.cam.isOpened():
            print(f"Camera {self.box_id} is not available for recording.")
            return False

        # Because this function might be called from the GPIO callback thread, we need to
        # acquire lock to make sure it isn't also being called from the main thread.
        with self.lock:
            if not self.IsRecording:
                self.frame_num = 0
                self.TTL_num = 0

                if stress_test_mode:
                    prefix = os.path.join(DATA_FOLDER, f"stress_test_cam{self.box_id}")
                else:
                    prefix = self.get_filename_prefix(animal_ID)
                    
                self.filename_video = prefix + "_Video.avi"
                self.filename_timestamp = prefix + "_Frames.txt"
                self.filename_timestamp_TTL = prefix + "_TTLs.txt"

                try:
                    # Create video file
                    if USE_FFMPEG:
                        self.process = self.save_video(self.filename_video, FRAME_RATE_PER_SECOND)
                    else:
                        # PyCharm intellisense gives warning on next line, but it is fine.
                        self.Writer = cv2.VideoWriter(self.filename_video,
                                                      self.codec,
                                                      FRAME_RATE_PER_SECOND,
                                                      self.resolution,
                                                      RECORD_COLOR == 1)
                except:
                    print(f"Warning: unable to create video file: '{self.filename_video}'")
                    return False

                if not USE_FFMPEG:
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
                    self.fid_TTL.write('TTL_event_number\tTime_in_seconds\n')
                except:
                    print("Warning: unable to create text file for TTL timestamps")

                    # Close the previously-created writer objects
                    self.fid.close()
                    self.Writer.release()
                    return False

                self.IsRecording = True
                self.start_time = time.time()

                printt(f"Started recording camera {self.box_id} to file '{self.filename_video}'")

                # This allows us to change button state
                self.need_update_button_state_flag = True

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

            self.TTL_animal_ID = 0

            if self.IsRecording:
                self.IsRecording = False
                printt(f"Stopping recording camera {self.box_id} after " + self.get_elapsed_time_string())

                # Close Video file
                if USE_FFMPEG:
                    self.process.stdin.close()
                    self.process.wait()

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
        
        with self.lock:

            if self.cam is not None and self.cam.isOpened():

                if not self.read_one_frame():

                    # Read failed. Remove this camera so we won't attempt to read it later.
                    # Should we set a flag to try to periodically reconnect?

                    if self.IsRecording:
                        self.stop_record()  # Close file writers

                    self.frame = make_blank_frame(f"{self.box_id} Camera lost connection")
                    # Warn user that something is wrong.
                    printt(f"Unable to read video from camera with ID {self.box_id}. Will remove camera from available list, and stop any ongoing recordings.")

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

                if self.TTL_mode == self.TTL_type.Debug:
                    # Green dot indicates we are in TTL DEBUG mode
                    cv2.circle(self.frame,
                               (int(20 * FONT_SCALE), int(110 * FONT_SCALE)),  # x-y position
                               int(8 * FONT_SCALE),  # Radius
                               (0, 255, 0),     # color is in BGR order
                               -1)   # -1 thickness fills circle

                if self.TTL_animal_ID > 0:
                    # Add animal ID to video
                    cv2.putText(self.frame, str(self.TTL_animal_ID),
                                (int(10 * FONT_SCALE), int(90 * FONT_SCALE)),
                                cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 128, 128),
                                round(FONT_SCALE + 0.5))  # Line thickness
                elif self.TTL_animal_ID < 0:
                    # Animal ID checksum failed
                    cv2.putText(self.frame, "Unknown",
                                (int(10 * FONT_SCALE), int(90 * FONT_SCALE)),
                                cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 255, 255),
                                round(FONT_SCALE + 0.5))  # Line thickness

                if not RECORD_COLOR and self.frame is not None:
                    self.frame = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)

                if self.frame is not None and self.IsRecording:
                    if self.fid is not None and self.start_time > 0:
                        # Write timestamp to text file. Do this before writing AVI so that
                        # timestamp will not be delayed by latency required to compress video. This
                        # ensures most accurate possible timestamp.
                        try:
                            time_elapsed = time.time() - self.start_time
                            self.fid.write(f"{self.frame_num}\t{time_elapsed}\n")
                        except:
                            print(f"Unable to write text file for camera f{self.box_id}. Will stop recording")
                            self.stop_record()
                            return 0, None

                    self.frame_num += 1

                    if self.IsRecording:
                        try:
                            # Write frame to AVI video file if possible
                            if USE_FFMPEG:
                                if RECORD_COLOR:
                                    self.process.stdin.write(
                                        cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
                                        .astype(np.uint8)
                                        .tobytes()
                                    )
                                else:
                                    self.process.stdin.write(self.frame.astype(np.uint8).tobytes())
                            else:
                                if self.Writer is not None:
                                    self.Writer.write(self.frame)
                        except:
                            print(f"Unable to write video file for camera {self.box_id}. Will stop recording")
                            self.stop_record()

                return self.status, self.frame
            else:
                # Camera is not available.
                return 0, None

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

        elapsed_sec = time.time() - self.start_time
        
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
