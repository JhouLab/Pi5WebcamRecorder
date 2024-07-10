from __future__ import annotations   # Need this for type hints to work on older Python versions
import tkinter
from typing import List
import time
import platform
import os

# On Raspberry pi, need to type:
# sudo apt-get install python3-pil.imagetk
from PIL import Image, ImageTk  # Need to import pillow from Jeffrey A. Clark
import numpy as np
import math
from CamObj import CamObj, WIDTH, HEIGHT, FRAME_RATE_PER_SECOND, make_blank_frame, FONT_SCALE, printt, DATA_FOLDER, get_disk_free_space
from get_hardware_info import *
import cv2
from sys import gettrace
from enum import Enum
from functools import partial

import tkinter as tk
from tkinter import messagebox as mb

# If true, will print extra diagnostics, such as a running frame count and FPS calculations
VERBOSE = False

# First camera ID number
FIRST_CAMERA_ID = 1

DEBUG = gettrace() is not None

if DEBUG:
    printt("Running in DEBUG mode. Can use keyboard 'd' to simulate TTLs for all 4 cameras.")

if platform.system() == "Linux":
    # Setup stuff that is specific to Raspberry Pi (as opposed to Windows):

    # Identify camera via USB port position, rather than ID number which is unpredictable.
    IDENTIFY_CAMERA_BY_USB_PORT = True

    #
    # Note that the standard RPi.GPIO library does NOT work on Pi5 (only Pi4).
    # On Pi5, please uninstall the standard library and install the following
    # drop-in replacement:
    #
    # sudo apt remove python3-rpi.gpio
    # sudo apt install python3-rpi-lgpio
    #
    import RPi.GPIO as GPIO

    GPIO.setmode(GPIO.BCM)  # Set's GPIO pins to BCM GPIO numbering
    INPUT_PIN_LIST = [4, 5, 6, 7]  # List of input pins for the four cameras
    for p in INPUT_PIN_LIST:
        try:
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # Set to be input, with internal pull-down resistor
        except RuntimeError:
            printt("Runtime Error: Unable to set up GPIO.")
            print("    If this is a Pi5, please replace the default gpio library as follows:")
            print("    sudo apt remove python3-rpi.gpio")
            print("    sudo apt install python3-rpi-lgpio")
            exit()
else:
    # Don't identify by USB port. Instead, use camera ID provided by operating system, which is unpredictable.
    IDENTIFY_CAMERA_BY_USB_PORT = False
    INPUT_PIN_LIST = [None] * 4  # List of input pins for the four cameras

if WIDTH > 1024:
    # Downsample large video frames to something more reasonable
    ratio = WIDTH / 1024
    SCREEN_RESOLUTION = (1024, int(HEIGHT / ratio))
    SCREEN_RESOLUTION_INSET = (512, SCREEN_RESOLUTION[1] >> 1)
elif WIDTH < 640:
    # Upsample small frames
    ratio = 640 / WIDTH
    SCREEN_RESOLUTION = (640, int(HEIGHT * ratio))
    SCREEN_RESOLUTION_INSET = (320, SCREEN_RESOLUTION[1] >> 1)
else:
    SCREEN_RESOLUTION = (WIDTH, HEIGHT)
    SCREEN_RESOLUTION_INSET = (WIDTH >> 1, HEIGHT >> 1)

# Reading from webcam using MJPG generally allows higher frame rates
USE_MJPG = (WIDTH > 640)
USE_MJPG = True

# Tries to connect to a single camera based on ID. Returns a VideoCapture object if successful.
# If not successful (i.e. if there is no camera plugged in with that ID), will throw exception,
# which unfortunately is the only way to enumerate what devices are connected. The caller needs
# to catch the exception and handle it by excluding that ID from further consideration.
def setup_cam(id):
    if platform.system() == "Windows":
        tmp = cv2.VideoCapture(id, cv2.CAP_DSHOW)  # On Windows, specifying CAP_DSHOW greatly speeds up detection
    else:
        if USE_MJPG:
            tmp = cv2.VideoCapture(id,
                                   cv2.CAP_V4L2)  # This is needed for MJPG mode to work, allowing higher frame rates
        else:
            tmp = cv2.VideoCapture(id)

    if tmp.isOpened():
        if USE_MJPG:
            # Higher resolutions are limited by USB transfer speeds to use lower frame rates.
            # Changing to MJPG roughly doubles the max frame rate, at some cost of CPU cycles
            tmp.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        if not tmp.isOpened():
            print(f"MJPG not supported. Please edit code.")
        tmp.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        tmp.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        fps = tmp.get(cv2.CAP_PROP_FPS)
        if not tmp.isOpened():
            print(f"Resolution {WIDTH}x{HEIGHT} not supported. Please change config.txt.")
    else:
        fps = 0
        
    return tmp, fps


def any_camera_recording(cam_list):
    # Returns true if any camera has an active recording in progress
    for c in cam_list:
        if c is None:
            continue
        if c.IsRecording:
            return True
    return False


def make_instruction_frame():
    # Frame with brief user-friendly instructions
    f = np.zeros((HEIGHT, WIDTH, 1), dtype="uint8")
    x = int(10 * FONT_SCALE)
    y = int(30 * FONT_SCALE)
    ydiff = int(40 * FONT_SCALE)
    line_thickness = round(FONT_SCALE)
    cv2.putText(f, "Video off. Recordings will continue.",
                (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 255, 255),
                line_thickness)
    cv2.putText(f, "Left-right cursor cycles cameras.",
                (x, y + ydiff),
                cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 255, 255),
                line_thickness)
    cv2.putText(f, "Q to quit, 0-3 to start/stop record.",
                (x, y + 2 * ydiff),
                cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 255, 255),
                line_thickness)

    f = cv2.resize(f, SCREEN_RESOLUTION)
    return f


# Highest camera ID to search when first connecting. Some sources
# recommend searching up to 99, but that takes too long and is usually
# unnecessary. So far, I have not needed to search above about 8, but we
# go to 15 just in case. Actually Pi4 freezes when we reach 15, so we now
# limit to 14.
MAX_ID = 14

INSTRUCTION_FRAME = make_instruction_frame()

DISPLAY_WINDOW_NAME = "Camera output"

cam_array: List[CamObj | None]

if IDENTIFY_CAMERA_BY_USB_PORT:
    # Array of subframes for 4x1 display
    # Each "None" will be replaced with an actual CamObj object if camera detected.
    cam_array = [None] * 4
else:
    # Array of camera objects, one for each discovered camera
    cam_array = []

# Make subframes that are blank. These are used for 2x2 grid display.
# Blank frames will be replaced by real ones if camera is found.
subframes = [None] * 4
for x in range(4):
    tmp = make_blank_frame(f"{FIRST_CAMERA_ID + x} no camera found")
    subframes[x] = cv2.resize(tmp, SCREEN_RESOLUTION_INSET)

if IDENTIFY_CAMERA_BY_USB_PORT:
    printt("Scanning for all available cameras by USB port. Please wait ...")
else:
    printt("Scanning for all available cameras. Please wait ...")

num_cameras_found = 0
min_fps = FRAME_RATE_PER_SECOND

# Scan IDs to find cameras
for cam_id in range(MAX_ID):
    tmp, fps = setup_cam(cam_id)
    print(".", end="", flush=True)
    if tmp.isOpened():
        if IDENTIFY_CAMERA_BY_USB_PORT:
            # Attempt to identify what USB port this camera is plugged into.
            # Method is very klugey, and I don't really understand why it works.
            # But it does. For now. I hope.
            port = get_cam_usb_port(cam_id)
            if port < 0:
                printt("Unable to identify USB port. Won't show camera. Please contact developer.")
                continue
            if port > 3:
                printt(f"Invalid USB port number (should be 0-3): {port}")
                continue

            if cam_array[port] is not None:
                # If we already found a camera in this position ...
                printt(f"Auto-detected more than one camera in USB port {port}, will only use first one detected")
                continue
            cam_array[port] = CamObj(tmp, cam_id,
                                     FIRST_CAMERA_ID + port, fps, GPIO_pin=INPUT_PIN_LIST[port])
            num_cameras_found += 1
        else:
            # If not using USB port number, then cameras are put into array
            # in the order they are discovered. This could be unpredictable, but at least
            # it will work, and won't crash. In this case, we also ignore GPIO pin list, since
            # recordings will need to be started and stopped manually.
            cam_array.append(CamObj(tmp, cam_id, FIRST_CAMERA_ID + len(cam_array), fps))
            num_cameras_found += 1
            

print()

if num_cameras_found == 0:
    printt("NO CAMERAS FOUND")
    exit()
else:
    printt(f"Found {num_cameras_found} cameras")

# Report what was discovered
for idx, cam_obj in enumerate(cam_array):
    if cam_obj is None:
        # No camera was found for this USB port position.
        # Create dummy camera object as placeholder, allowing a blank frame
        # to show.
        cam_array[idx] = CamObj(None, -1, FIRST_CAMERA_ID + idx, 0)
        continue

    if IDENTIFY_CAMERA_BY_USB_PORT:
        printt(
            f"Camera in USB port position {FIRST_CAMERA_ID + idx} has ID {cam_obj.id_num} and serial '{get_cam_serial(cam_obj.id_num)}'",
            omit_date_time=True)
    else:
        printt(f"Camera {FIRST_CAMERA_ID + idx} has ID {cam_obj.id_num}", omit_date_time=True)
        
    printt(f"    Frames per second: {cam_obj.max_fps}")
    if 0 < cam_obj.max_fps < min_fps:
        # Should issue warning here ...
        min_fps = cam_obj.max_fps

# Lower frame rate to whatever is the lowest of all 4 cameras.
FRAME_RATE_PER_SECOND = min_fps

print()
printt(f"Starting display. Frame rate for display and recording is {FRAME_RATE_PER_SECOND}")


class RECORDER:
    class PendingAction(Enum):
        Nothing = 0
        StartRecord = 1
        EndRecord = 2
        DebugMode = 4

    pendingActionVar = PendingAction.Nothing

    def onKeyPress(self, event):

        self.handle_keypress(event.char, event.keycode)

    def handle_keypress(self, key, keycode, CV2KEY=False):

        if CV2KEY:
            key2 = key >> 16  # On Windows, arrow keys are encoded here
            key1 = (key >> 8) & 0xFF  # This always seems to be 0
            key = key & 0xFF  # On Raspberry Pi, arrow keys are coded here along with all other keys

        print(key)
        if (not CV2KEY and (key == 'q')) or (CV2KEY and key == ord('q')):
            self.show_quit_dialog()
        elif (not CV2KEY and ("0" <= key <= "9")) or (CV2KEY and (ord('0') <= key <= ord('9'))):
            # Start/stop recording for specified camera
            cam_num = ord(key) - ord("0")
            cam_idx = cam_num - FIRST_CAMERA_ID
            if cam_idx < 0 or cam_idx >= len(self.cam_array):
                print(f"Camera number {cam_num} does not exist, won't record.")
            else:
                cam_obj = self.cam_array[cam_idx]
                if cam_obj is None:
                    print(f"Camera number {cam_num} not found, won't record.")
                else:
                    if not cam_obj.IsRecording:

                        self.show_start_record_dialog(cam_num)

                    else:
                        res = mb.askyesno('Stop?', f'Stop recording camera {cam_num}?')
                        if res:
                            cam_obj.stop_record()
        else:
            if CV2KEY:
                if platform.system() == "Linux":
                    # Raspberry Pi encodes arrow keys in lowest byte
                    isLeftArrow = key == 81
                    isRightArrow = key == 83
                elif platform.system() == "Windows":
                    # Windows encodes arrow keys in highest byte
                    isLeftArrow = keycode == 37
                    isRightArrow = keycode == 39
                else:
                    isLeftArrow = False
                    isRightArrow = False
            else:
                isLeftArrow = (keycode == 37 or keycode == 113)
                isRightArrow = (keycode == 39 or keycode == 114)

            if isLeftArrow:  # Left arrow key
                self.which_display -= 1
                if self.which_display < -2:
                    self.which_display = len(cam_array) - 1
                self.print_current_display_id()
            elif isRightArrow:  # Right arrow key
                self.which_display += 1
                if self.which_display >= len(cam_array):
                    self.which_display = -2
                self.print_current_display_id()
            elif DEBUG and self.pendingActionVar == self.PendingAction.DebugMode:
                # Special debugging keystroke that toggles DEBUG TTL measurement mode
                for cam_obj in cam_array:
                    if cam_obj is not None:
                        if cam_obj.TTL_mode == cam_obj.TTL_type.Normal:
                            cam_obj.TTL_mode = cam_obj.TTL_type.Debug
                            printt(f'Entering DEBUG TTL mode for camera {cam_obj.order}')
                        elif cam_obj.TTL_mode == cam_obj.TTL_type.Debug:
                            cam_obj.TTL_mode = cam_obj.TTL_type.Normal
                            printt(f'Exiting DEBUG TTL mode for camera {cam_obj.order}')

    pendingActionCamera = -1
    pendingActionID = ""

    def __init__(self, _cam_array):

        self.root = tk.Tk()
        self.root.bind('<KeyPress>', self.onKeyPress)
        self.root.protocol("WM_DELETE_WINDOW", self.show_quit_dialog)
        self.root.title("Pi5 Camera recorder control bar")

        # Frame1 holds entire control bar (status and control buttons)
        frame1 = tk.Frame(self.root)  # , borderwidth=1, relief="solid")
        frame1.pack(side=tk.BOTTOM, fill=tk.X)

        # Frame2 holds a vertical stack of up to 4 status labels
        frame2 = tk.Frame(frame1, borderwidth=1, relief="solid")
        frame2.pack(side=tk.LEFT, expand=1, fill=tk.X, padx=2, pady=2)

        # Add up to four status lines, one for each camera
        self.message_widget = [None] * 4
        for idx in range(len(_cam_array)):
            cam_obj = _cam_array[idx]
            if cam_obj is None or cam_obj.cam is None:
                continue
            f3 = tk.Frame(frame2)
            f3.pack(fill=tk.X)
            b = tk.Button(f3, text=f"Record cam #{FIRST_CAMERA_ID + idx}", command=partial(self.show_start_record_dialog, idx))
            b.pack(side=tk.LEFT, ipadx=2)
            b = tk.Button(f3, text="Stop", command=partial(self.show_stop_dialog, idx))
            b.pack(side=tk.LEFT, ipadx=10)
            self.message_widget[idx] = tk.Label(f3, text=f"", width=60, anchor=tk.W)
            self.message_widget[idx].pack(side=tk.LEFT, fill=tk.X)

        # Add disk free status line
        self.disk_free_label = tk.Label(frame1, text=f"Free disk space: {get_disk_free_space():.1f}GB")  # , borderwidth=1, relief="solid")
        self.disk_free_label.pack(side=tk.TOP, fill=tk.X, expand=True, pady=5)

        b_list = [
            ("         Close        ", self.show_quit_dialog),
            ("Browse data folder", self.browse_data_folder),
            ("Stop all recording", partial(self.show_stop_dialog, -1))
        ]

        for _b in b_list:
            # Using tk.RIGHT causes buttons to "stick" to the right edge, and won't get
            # squished if window is resized.
            tk.Button(frame1, text=_b[0], command=_b[1]).pack(side=tk.RIGHT, ipadx=5, ipady=5)

        self.cam_array = _cam_array

        self.frame_count = 0

        self.FRAME_INTERVAL = 1.0 / FRAME_RATE_PER_SECOND

        # Report status every 30 seconds
        self.STATUS_REPORT_INTERVAL = FRAME_RATE_PER_SECOND * 30

        # Which camera to display initially. User can change this later with arrow keys.
        #
        # -2 shows all 4 cameras in a 2x2 grid
        # -1 turns off display
        #  0-3 show the 4 cameras, by USB port position
        self.which_display = -2
        if num_cameras_found == 1:
            # If exactly one camera found, then show that one to start
            for c in _cam_array:
                if c is None or c.cam is None:
                    continue
                if c.order >= 0:
                    self.which_display = c.order - FIRST_CAMERA_ID
                    break

        # Force window to show, so we can get width/height
        self.root.update()

        # Set min window size, to prevent too much squashing of components
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())

        self.exiting = False
        
        self.update_image()

    def browse_data_folder(self):
        p = platform.system()
        if p == "Windows":
            os.startfile(DATA_FOLDER)
        elif p == "Linux":
            os.system("pcmanfm \"%s\"" % DATA_FOLDER)

    def confirm_quit(self, widget, value):
        widget.destroy()
        if value:
            self.root.after(0, self.cleanup)

    def show_quit_dialog(self):

        if not any_camera_recording(self.cam_array):
            self.root.after(0, self.cleanup)
            return

        w = tk.Toplevel(self.root)
        w.title("Are you sure?")

        w.resizable(False, False)  # Remove maximize button
        if platform.system() == "Windows":
            w.attributes("-toolwindow", True)  # Remove minimize button

        f = tk.Frame(w)  # , highlightbackground="black", highlightthickness=1, relief="flat", borderwidth=5)
        f.pack(side=tk.TOP, fill=tk.X, padx=15, pady=10)

        l1 = tk.Label(f, text="Camera(s) still recording. Quitting will end recordings.", anchor="e", justify=tk.RIGHT)
        l1.pack(side=tk.TOP)

        f1 = tk.Frame(w)
        f1.pack(side=tk.TOP)

        b = tk.Button(f1, text="   OK   ", command=partial(self.confirm_quit, w, True))
        b.pack(padx=5, pady=5, ipadx=10, ipady=5, side=tk.LEFT)
        b.focus_set()
        b = tk.Button(f1, text="Cancel", command=partial(self.confirm_quit, w, False))
        b.pack(padx=5, pady=5, ipadx=5, ipady=5, side=tk.LEFT)
        return

    def imshow(self, img):
        if img is not None:
            cv2.imshow(DISPLAY_WINDOW_NAME, img)
            
                # Check if any key has been pressed.
        if platform.system() == "Linux":
            return cv2.waitKey(1)
        elif platform.system() == "Windows":
            # wakeKeyEx can read cursor keys on Windows, whereas waitKey() can't
            return cv2.waitKeyEx(1)

    # Print message indicating which camera is displaying to screen.
    def print_current_display_id(self):
        if self.which_display == -1:
            print("TURNING OFF CAMERA DISPLAY.")
            self.imshow(INSTRUCTION_FRAME)
            return

        if self.which_display == -2:
            print("Multi-frame display")
            return

        cam = cam_array[self.which_display]
        cam_position = cam.order
        if cam is None or cam.cam is None:
            print(f"Camera in position {cam_position} is disconnected")
            if cam is not None:
                # Show the blank frame now, since it will not be updated in timer loop.
                # Otherwise we will see leftover image from last good camera
                self.imshow(cam.frame)
        else:
            print(f"Showing camera {cam_position}")

    def show_start_record_dialog(self, cam_num):

        cam_obj = self.cam_array[cam_num]

        if cam_obj is None:
            return

        if cam_obj.IsRecording:
            tk.messagebox.showinfo("Warning", f"Camera {FIRST_CAMERA_ID+cam_num} is already recording.")
            return

        w = tk.Toplevel(self.root)
        w.title("Start recording?")

        w.resizable(False, False)  # Remove maximize button
        if platform.system() == "Windows":
            w.attributes("-toolwindow", True)  # Remove minimize button

        f = tk.Frame(w)  # , highlightbackground="black", highlightthickness=1, relief="flat", borderwidth=5)
        f.pack(side=tk.TOP, fill=tk.X, padx=15, pady=10)

        l1 = tk.Label(f, text=f"Enter animal ID for camera #{cam_num + FIRST_CAMERA_ID}", anchor="e")
        l1.pack(side=tk.TOP)

        s = tk.StringVar(value=f"Cam{cam_num + FIRST_CAMERA_ID}")
        e = tk.Entry(f, textvariable=s)
        e.pack(side=tk.TOP)

        e.bind('<Return>', partial(self.confirm_start, w, cam_num, s, True))

        b = tk.Button(f, text="    OK    ", command=partial(self.confirm_start, w, cam_num, s, True, None))
        b.pack(padx=5, pady=5, ipadx=10, ipady=5, side=tk.LEFT)
        b.focus_set()
        b = tk.Button(f, text="Cancel", command=partial(self.confirm_start, w, cam_num, s, False, None))
        b.pack(padx=5, pady=5, ipadx=10, ipady=5, side=tk.LEFT)

    def confirm_start(self, widget, cam_num, animal_id_var, result, _event):
        # We ignore _event, which is there for compatibility with the bind('<Return>') statement
        # which mandates that we send that event
        widget.destroy()
        if not result:
            return

        self.pendingActionVar = self.PendingAction.StartRecord
        self.pendingActionID = animal_id_var.get()
        self.pendingActionCamera = cam_num

    def show_stop_dialog(self, cam_num):

        if cam_num < 0:
            if any_camera_recording(self.cam_array):
                res = mb.askyesno('Stop all recordings?', f'Stop recording all cameras?')
                if res:
                    for cam_obj in self.cam_array:
                        if cam_obj is not None:
                            cam_obj.stop_record()
            else:
                tk.messagebox.showinfo("Warning", "No cameras are recording")

        else:
            cam_obj = self.cam_array[cam_num]
            if cam_obj is not None and cam_obj.IsRecording:
                res = mb.askyesno('Stop?', f'Stop recording camera {FIRST_CAMERA_ID + cam_num}?')
                if res:
                    cam_obj.stop_record()
            else:
                tk.messagebox.showinfo("Warning", "Camera is not recording")

    def update_image(self):

        if self.exiting:
            return
        
        for idx, cam_obj in enumerate(self.cam_array):
            # Read camera frame
            cam_obj.read()

            if cam_obj.status:
                # Add text to top left to show camera number. This will NOT show in recording
                cv2.putText(cam_obj.frame, str(FIRST_CAMERA_ID + idx),
                            (int(10 * FONT_SCALE), int(30 * FONT_SCALE)),
                            cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 128, 128),
                            round(FONT_SCALE + 0.5))  # Line thickness
                if cam_obj.IsRecording:
                    # Add red circle if recording. Again, this does not show in recorded file.
                    cv2.circle(cam_obj.frame,
                               (int(20 * FONT_SCALE), int(50 * FONT_SCALE)),  # x-y position
                               int(8 * FONT_SCALE),  # Radius
                               (0, 0, 255),  # Red dot (color is in BGR order)
                               -1)  # -1 thickness fills circle

        if self.which_display >= 0:
            # Show just one of the 4 cameras
            cam_obj = self.cam_array[self.which_display]
            if cam_obj.status:
                if SCREEN_RESOLUTION[0] == WIDTH:
                    img = cam_obj.frame
                else:
                    img = cv2.resize(cam_obj.frame, SCREEN_RESOLUTION)
            else:
                img = None
        elif self.which_display == -2:
            # Show all 4 cameras on one screen (downsized 2x)
            for index, elt in enumerate(self.cam_array):
                if elt is not None and elt.frame is not None:
                    # Downsize
                    subframes[index] = cv2.resize(elt.frame, SCREEN_RESOLUTION_INSET)

            # Concatenate 4 images into 1
            im_top = cv2.hconcat([subframes[0], subframes[1]])
            im_bot = cv2.hconcat([subframes[2], subframes[3]])
            img = cv2.vconcat([im_top, im_bot])
        else:
            img = None

        key = self.imshow(img)

        if self.pendingActionVar == self.PendingAction.StartRecord:
            cam_num = self.pendingActionCamera
            cam_obj = self.cam_array[cam_num]
            if not cam_obj.start_record(self.pendingActionID):
                # Recording was attempted, but did not succeed. Usually this is
                # because of file error, or missing codec.
                print(f"Unable to start recording camera {cam_num + FIRST_CAMERA_ID}.")
            self.pendingActionVar = self.PendingAction.Nothing

        if self.frame_count == 0:
            # Now that the first frame is done, we can start timer and should get stable FPS readings
            # Another 40ms sleep to ensure frame is present
            time.sleep(.04)
            self.start = time.time()

            # This is actually target time for the frame AFTER the next, since the next one will be read immediately
            self.next_frame = self.start + self.FRAME_INTERVAL

        self.frame_count = self.frame_count + 1

        if self.frame_count % 10 == 0:
            # Print status periodically (frame # and frames per second)
            if VERBOSE:
                elapsed = time.time() - self.start
                fps = self.frame_count / elapsed
                print(f"Frame count: {self.frame_count}, frames per second = {fps}")

            if any_camera_recording(cam_array):
                for idx, cam in enumerate(cam_array):
                    # Print elapsed time for each camera that is actively recording.
                    msg = self.message_widget[idx]
                    if cam.IsRecording:
                        s = cam.get_elapsed_recording_time()
                        msg.config(text=s)
                    elif msg is not None:
                        msg.config(text="--")

                if self.frame_count % 50 == 0:
                    self.disk_free_label.config(text=f"Free disk space: {get_disk_free_space():.3f}GB")

        if key != -1:
            self.handle_keypress(key, key >> 16, CV2KEY=True)

        lag_ms = (time.time() - self.next_frame) * 1000
        if lag_ms > 50:
            # We are more than 20ms late for next frame. If recording, warn of possible missed frames.
            if any_camera_recording(cam_array):
                printt(
                    f"Warning: CPU lag {lag_ms:.2f} ms. Might drop up to {int(math.ceil(lag_ms / 100))} frame(s).")

            # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
            self.next_frame = time.time() + self.FRAME_INTERVAL
            if not self.exiting:
                self.root.after(0, self.update_image)
        else:
            # We are done with loop, but not ready to request next frame. Wait a bit.
            advance_ms = (self.next_frame - time.time()) * 1000

            # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
            self.next_frame += self.FRAME_INTERVAL

            if advance_ms < 0:
                advance_ms = 1

            if not self.exiting:
                self.root.after(int(advance_ms), self.update_image)

    def cleanup(self):

        self.exiting = True
        self.root.destroy()

        # All done. Close up windows and files
        cv2.destroyAllWindows()
        for cam_obj in self.cam_array:
            if cam_obj is None:
                continue
            cam_obj.stop_record()

        for cam_obj in self.cam_array:
            if cam_obj is None:
                continue
            cam_obj.close()

        printt("Exiting", close_file=True)


rec_obj = RECORDER(cam_array)
rec_obj.root.mainloop()
