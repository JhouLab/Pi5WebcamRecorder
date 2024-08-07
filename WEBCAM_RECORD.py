from __future__ import annotations   # Need this for type hints to work on older Python versions

import subprocess
from typing import List
import time
import os
import sys
import multiprocessing
import extra.shared_arrays

# We no longer need PIL, since we are using OpenCV to render images, which is MUCH faster.
#
# If we ever had to bring it back, would have to install PIL on the PI this way:
#   sudo apt-get install python3-pil.imagetk
# from PIL import Image, ImageTk  # Import pillow from Jeffrey A. Clark

import numpy as np
from CamObj import CamDestinationObj, CamReaderObj, CamInfo, WIDTH, HEIGHT, \
    RECORD_FRAME_RATE, NATIVE_FRAME_RATE, make_blank_frame,\
    FONT_SCALE, printt, DATA_FOLDER, get_disk_free_space, IS_LINUX, IS_PI5, IS_WINDOWS, \
    SHOW_SNAPSHOT_BUTTON, SHOW_RECORD_BUTTON, SHOW_ZOOM_BUTTON, DEBUG, \
    source_process
from extra.get_hardware_info import *

import cv2
from enum import Enum
from functools import partial

# On WSL, install tkinter this way:
#   sudo apt install python3-tk
import tkinter as tk
from tkinter import messagebox


# If true, will print extra diagnostics, such as a running frame count and FPS calculations
VERBOSE = False

# Reading from webcam using MJPG generally allows higher frame rates
# This definitely works on PI5, not tested elsewhere.
# USE_MJPG = (WIDTH > 640)
USE_MJPG = IS_PI5

# OpenCV window buttons look weird (text only) when run as root. This flag hides them altogether.
HIDE_OPENCV_BUTTONS = True

# Tries to connect to a single camera based on ID. Returns a VideoCapture object if successful.
# If no camera found with that ID, will throw exception, which unfortunately is the only
# way to enumerate what devices are connected. The caller needs to catch the exception and
# handle it by excluding that ID from further consideration.
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

        # fps readout does not seem to be reliable. On Linux, we always get 30fps, even if camera
        # is set to a high resolution that can't deliver that frame rate. On Windows, always seem to get 0.
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


def get_key():
    # waitKey checks if any key has been pressed, and also runs cv2 message pump so that screen will update
    if platform.system() == "Linux":
        return cv2.waitKey(1)
    elif platform.system() == "Windows":
        # wakeKeyEx can read cursor keys on Windows, whereas waitKey() can't
        return cv2.waitKeyEx(1)


class RECORDER:
    class PendingAction(Enum):
        Nothing = 0
        StartRecord = 1
        EndRecord = 2
        Exiting = 3
        DebugMode = 4

    class CAM_VALS(Enum):
        PREV = -20
        NEXT = -10
        ALL = -2
        INSTRUCTIONS = -1

    pendingActionVar = PendingAction.Nothing

    class WidgetSet:

        StartButton: tk.Button = None
        StopButton: tk.Button = None
        StatusLabel: tk.Label = None

        def __init__(self):

            pass

    widget_array: List[WidgetSet]

    def onKeyPress(self, event):

        self.handle_keypress(event.char, event.keycode)

    def handle_keypress(self, key, keycode, CV2KEY=False):

        # On Raspberry Pi, CV2KEY will be True, and key will be a one-character string
        # On Windows machines, CV2KEY will be False, and key will be an integer

        if CV2KEY:
            key2 = key >> 16  # On Windows, arrow keys are encoded here
            key1 = (key >> 8) & 0xFF  # This always seems to be 0
            key = key & 0xFF  # On Raspberry Pi, arrow keys are coded here along with all other keys
        else:
            # On Windows machines, key is a single character, so must be converted to ASCII for consistency with Pi
            if len(key) > 0:
                key = ord(key)
            else:
                key = -1

        if DEBUG:
            print(f"Keypress: {key}")
        if key == ord('q'):
            self.show_quit_dialog()
        elif ord('0') <= key <= ord('9'):
            # Start/stop recording for specified camera
            cam_num = key - ord("0")
            cam_idx = cam_num - FIRST_CAMERA_ID
            if cam_idx < 0 or cam_idx >= len(self.cam_array):
                print(f"Camera number {cam_num} does not exist, won't record.")
            else:
                cam_obj = self.cam_array[cam_idx]
                if cam_obj is None:
                    print(f"Camera number {cam_num} not found, won't record.")
                else:
                    if not cam_obj.IsRecording:

                        self.show_start_record_dialog(cam_idx)

                    else:
                        res = messagebox.askyesno('Stop?', f'Stop recording camera {cam_num}?')
                        if res:
                            cam_obj.stop_record()
        else:
            if platform.system() == "Linux":
                # Raspberry Pi encodes arrow keys in lowest byte
                isLeftArrow = key == 81
                isRightArrow = key == 83
            elif platform.system() == "Windows":
                # Windows encodes arrow keys in highest byte
                isLeftArrow = (keycode == 37 or keycode == 113)
                isRightArrow = (keycode == 39 or keycode == 114)
            else:
                isLeftArrow = False
                isRightArrow = False

            if isLeftArrow:  # Left arrow key
                self.change_cam(self.CAM_VALS.PREV)
            elif isRightArrow:  # Right arrow key
                self.change_cam(self.CAM_VALS.NEXT)
            elif DEBUG and key == ord('g'):
                # Simulate GPIO toggle. This is for testing the blue dot ONLY. It will not simulate
                # GPIO signals for start/stop, or binary ID transmission.
                for cam_obj in cam_array:
                    if cam_obj is not None:
                        cam_obj.GPIO_active = not cam_obj.GPIO_active
            elif DEBUG and key == ord('d'):
                # Special debugging keystroke that toggles DEBUG TTL measurement mode
                for cam_obj in cam_array:
                    if cam_obj is not None:
                        if cam_obj.TTL_mode == cam_obj.TTL_type.Normal:
                            cam_obj.TTL_mode = cam_obj.TTL_type.Debug
                            printt(f'Entering DEBUG TTL mode for camera {cam_obj.box_id}')
                        elif cam_obj.TTL_mode == cam_obj.TTL_type.Debug:
                            cam_obj.TTL_mode = cam_obj.TTL_type.Normal
                            printt(f'Exiting DEBUG TTL mode for camera {cam_obj.box_id}')

    pendingActionCameraIdx: int = -1
    pendingActionID: str = ""

    def __init__(self, _cam_array: List[CamDestinationObj], root_window=None):

        self.cam_array = _cam_array
        self.cached_frames: List[np.ndarray | None] = [None] * len(_cam_array)

        while True:
            time.sleep(0.01)
            # Wait for all camera profiling to complete before creating GUI
            is_ready = True
            for c in _cam_array:
                if not c.has_cam:
                    continue
                if not c.IsReady:
                    is_ready = False
                    break
            if is_ready:
                break

        if DEBUG:
            printt("All cameras ready, will now create GUI")

        if root_window is None:
            self.top_window = tk.Tk()
            self.root_window = self.top_window
        else:
            self.top_window = tk.Toplevel()
            self.root_window = root_window

        self.top_window.bind('<KeyPress>', self.onKeyPress)
        self.top_window.protocol("WM_DELETE_WINDOW", self.show_quit_dialog)
        self.top_window.title("Pi5 Camera recorder control bar")

        self.widget_array = [self.WidgetSet() for _ in range(4)]

        # Frame1 holds entire control bar (status and control buttons)
        frame1 = tk.Frame(self.top_window)  # , borderwidth=1, relief="solid")
        frame1.pack(side=tk.BOTTOM, fill=tk.X)

        # Frame2 holds a vertical stack of up to 4 status labels
        frame2 = tk.Frame(frame1, borderwidth=1, relief="solid")
        frame2.pack(side=tk.LEFT, expand=1, fill=tk.X, padx=2, pady=2)

        # Add up to four status lines, one for each camera. Each line also has two buttons to start/stop recording.
        for idx, cam_obj in enumerate(_cam_array):

            w = self.widget_array[idx]

            if cam_obj is None or not cam_obj.has_cam:
                continue
            f3 = tk.Frame(frame2)
            f3.pack(fill=tk.X)
            
            if SHOW_RECORD_BUTTON:
                b = tk.Button(f3, text=f"Record cam #{FIRST_CAMERA_ID + idx}", command=partial(self.show_start_record_dialog, idx))
                b.pack(side=tk.LEFT, ipadx=2)
                w.StartButton = b

                # Add Stop button
                b = tk.Button(f3, text="Stop", command=partial(self.show_stop_dialog, idx))
                b.pack(side=tk.LEFT, ipadx=10)
                b["state"] = tk.DISABLED
                w.StopButton = b
            if SHOW_SNAPSHOT_BUTTON:
                b = tk.Button(f3, text=f"Snapshot cam #{FIRST_CAMERA_ID + idx}", command=partial(self.snapshot, idx))
                b.pack(side=tk.LEFT, ipadx=2)
                w.SnapshotButton = b
                
            l = tk.Label(f3, text=f"", width=60, anchor=tk.W)
            l.pack(side=tk.LEFT, fill=tk.X)
            w.StatusLabel = l

        # Add disk free status line
        self.disk_free_label = tk.Label(frame1, text=f"")  # , borderwidth=1, relief="solid")
        self.disk_free_label.pack(side=tk.TOP, fill=tk.X, expand=True, pady=5)

        self.show_disk_space()

        # frame3 holds top rows of buttons
        frame3 = tk.Frame(frame1)
        frame3.pack(side=tk.TOP, fill=tk.X, expand=True)
        frame3.columnconfigure("all", weight=1, uniform="1")

        b_list1 = [
            ("Show all cams", partial(self.change_cam, self.CAM_VALS.ALL)),
            ("Prev cam", partial(self.change_cam, self.CAM_VALS.PREV)),
            ("Next cam", partial(self.change_cam, self.CAM_VALS.NEXT)),
        ]

        if SHOW_ZOOM_BUTTON:
            b_list1.append(
                ("Zoom center", self.toggle_zoom),
            )

        for idx, _b in enumerate(b_list1):
            tk.Button(frame3, text=_b[0], command=_b[1]).grid(row=0, column=idx, ipadx=5, ipady=5, sticky="ew")

        # frame3b holds next rows of buttons
        b_list2 = [
            ("Stop all recording", partial(self.show_stop_dialog, -1)),
            ("Browse data folder", self.browse_data_folder),
            ("        Close        ", self.show_quit_dialog),
        ]

        for idx, _b in enumerate(b_list2):
            colspan = 1
            if idx == len(b_list2) - 1:
                colspan = len(b_list1) - len(b_list2) + 1
                if colspan <= 0:
                    colspan = 1
            tk.Button(frame3, text=_b[0], command=_b[1]).grid(row=1, column=idx, columnspan=colspan, ipadx=5, ipady=5, sticky="ew")

        if DEBUG:
            # Extra row of buttons in debug mode
            b_list_debug = [
                ("STRESS TEST (record all cams)", partial(self.show_start_record_dialog, self.CAM_VALS.ALL))
            ]

            for idx, _b in enumerate(b_list_debug):
                tk.Button(frame3, text=_b[0], command=_b[1], fg='blue').\
                    grid(row=2, column=idx, columnspan=len(b_list1), ipadx=5, ipady=5, sticky="ew")

        self.display_frame_count = 0

        self.FRAME_INTERVAL = 1.0 / MAX_DISPLAY_FRAMES_PER_SECOND

        # Which camera to display initially. User can change this later with arrow keys.
        #
        # -2 shows all 4 cameras in a 2x2 grid
        # -1 turns off display
        #  0-3 show the 4 cameras, by USB port position
        self.which_display = self.CAM_VALS.ALL.value
        if num_cameras_found == 1:
            # If exactly one camera found, then show that one to start
            for c in _cam_array:
                if c is None or not c.has_cam:
                    continue
                if c.box_id >= 0:
                    self.which_display = c.box_id - FIRST_CAMERA_ID
                    break

        # Place control bar in top left corner of screen
        self.top_window.geometry("+%d+%d" % (5, 35))

        # Force control bar window to show, so we can get width/height
        self.top_window.update()

        # Set min control bar size, to prevent too much squashing
        self.top_window.minsize(self.top_window.winfo_width(), self.top_window.winfo_height())

        if HIDE_OPENCV_BUTTONS:
            # This removes buttons from video window, which show up weirdly in superuser mode
            cv2.namedWindow(DISPLAY_WINDOW_NAME, cv2.WINDOW_GUI_NORMAL)

        blank_frame = make_blank_frame("", SCREEN_RESOLUTION)
        cv2.imshow(DISPLAY_WINDOW_NAME, blank_frame)  # Must show something or else moveWindow fails on Pi

        # Attempt to remove buttons, since they show up weird in superuser mode
        # cv2.namedWindow(DISPLAY_WINDOW_NAME, flags=cv2.WINDOW_GUI_NORMAL)
        # The following works, but also removes border, so window can't be moved (and is stuck at 0,0)
        # cv2.setWindowProperty(DISPLAY_WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

        cv2.waitKey(1)
        # Well, the following doesn't seem to work in Pi.
        # Apparently the Wayland display server doesn't support it.
        cv2.moveWindow(DISPLAY_WINDOW_NAME, 20, 220)  # Start video in top left, below control bar

        # Strangely, the normal GUI doesn't know how to size itself to fit array, so we have to remind it.
        # The following somehow fails when running as root, so need a second reminder later ...
        cv2.resizeWindow(DISPLAY_WINDOW_NAME, SCREEN_RESOLUTION[0], SCREEN_RESOLUTION[1])

        # WaitKey delay is in milliseconds. This forces GUI to catch up.
        cv2.waitKey(1)
        
        self.skipped_display_frames = 0
        self.zoom_center = False

        self.start = time.time()
        # This is actually target time for the frame AFTER the next, since the next one will be read immediately
        self.next_frame = self.start + self.FRAME_INTERVAL
        
        self.update_image()

    def browse_data_folder(self):
        p = platform.system()
        if p == "Windows":
            os.startfile(DATA_FOLDER)
        elif p == "Linux":
            # Open in the Pi's file manager, PCMan
            subprocess.Popen(f"pcmanfm \"{DATA_FOLDER}\"", shell=True)

    def toggle_zoom(self):

        self.zoom_center = not self.zoom_center

    def confirm_quit(self, widget, value):

        # We get here if user clicks "OK" on quit dialog, thereby confirming they really want to quit.

        widget.destroy()   # Close the quit dialog
        if value:
            self.pendingActionVar = self.PendingAction.Exiting

    def show_quit_dialog(self):

        if not any_camera_recording(self.cam_array):
            # If nothing is recording, then don't bother to ask for confirmation, just go ahead and set the quit flag
            self.pendingActionVar = self.PendingAction.Exiting
            return

        w = tk.Toplevel(self.top_window)
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

    def change_cam(self, cam_num):

        if isinstance(cam_num, self.CAM_VALS):
            if cam_num == self.CAM_VALS.NEXT:
                self.which_display += 1
                if self.which_display >= len(cam_info_array):
                    self.which_display = self.CAM_VALS.ALL.value
#                    self.which_display = self.CAM_VALS.INSTRUCTIONS.value
            elif cam_num == self.CAM_VALS.PREV:
                self.which_display -= 1
                if self.which_display < self.CAM_VALS.ALL.value:
                    self.which_display = len(cam_info_array) - 1
            else:
                # Convert from Enum type to integer
                self.which_display = cam_num.value
        else:
            self.which_display = cam_num

        self.print_current_display_id()

    # Print message indicating which camera is displaying to screen.
    def print_current_display_id(self):
        if self.which_display == self.CAM_VALS.INSTRUCTIONS.value:
            if VERBOSE:
                print("CAMERA DISPLAY OFF.")
            self.imshow(INSTRUCTION_FRAME)
            return

        if self.which_display == self.CAM_VALS.ALL.value:
            if VERBOSE:
                print("Multi-frame display")
            return

        cam = cam_array[self.which_display]
        cam_position = cam.box_id
        if cam is None or not cam.has_cam:
            if VERBOSE:
                print(f"Camera in position {cam_position} is not available")
            if cam is not None:
                # Show the blank frame now, since it will not be updated in timer loop.
                # Otherwise we will see leftover image from last good camera
                self.imshow(cam.frame)
        else:
            if VERBOSE:
                print(f"Showing camera {cam_position}")
                
    def snapshot(self, cam_num):
        
        cam_obj = self.cam_array[cam_num]
        fname = cam_obj.take_snapshot()
        if fname == None:
            tk.messagebox.showinfo("Error", "Failed to write snapshot file")
        else:
            tk.messagebox.showinfo("Success", f"Saved snapshot file: {fname}")

    def show_start_record_dialog(self, cam_idx: int):

        if cam_idx == self.CAM_VALS.ALL:
            self.pendingActionVar = self.PendingAction.StartRecord
            self.pendingActionCameraIdx = self.CAM_VALS.ALL.value
            return

        cam_obj = self.cam_array[cam_idx]

        if cam_obj is None:
            return

        if cam_obj.IsRecording:
            tk.messagebox.showinfo("Warning", f"Camera {FIRST_CAMERA_ID + cam_idx} is already recording.")
            return

        w = tk.Toplevel(self.top_window)
        w.title("Start recording?")

        w.resizable(False, False)  # Remove maximize button
        if platform.system() == "Windows":
            w.attributes("-toolwindow", True)  # Remove minimize button

        f = tk.Frame(w)  # , highlightbackground="black", highlightthickness=1, relief="flat", borderwidth=5)
        f.pack(side=tk.TOP, fill=tk.X, padx=15, pady=10)

        l1 = tk.Label(f, text=f"Enter animal ID for camera #{cam_idx + FIRST_CAMERA_ID}", anchor="e")
        l1.pack(side=tk.TOP)

        s = tk.StringVar(value=f"Box{cam_idx + FIRST_CAMERA_ID}")
        e = tk.Entry(f, textvariable=s)
        e.pack(side=tk.TOP)

        e.bind('<Return>', partial(self.confirm_start, w, cam_idx, s, True))

        b = tk.Button(f, text="    OK    ", command=partial(self.confirm_start, w, cam_idx, s, True, None))
        b.pack(padx=5, pady=5, ipadx=10, ipady=5, side=tk.LEFT)
        b.focus_set()
        b = tk.Button(f, text="Cancel", command=partial(self.confirm_start, w, cam_idx, s, False, None))
        b.pack(padx=5, pady=5, ipadx=10, ipady=5, side=tk.LEFT)

    def confirm_start(self, widget, cam_num, animal_id_var, result, _event):
        #
        # We get here if user clicks "OK" in the start dialog, thereby confirming that
        # session will indeed start.
        #
        # This will set a flag so that the next "update_image" call will start the session.
        #
        # We could probably simplify by directly starting recording here.
        #
        # We ignore _event, which is there for compatibility with the bind('<Return>') statement
        # which mandates that we send that event
        widget.destroy()
        if not result:
            return

        self.pendingActionVar = self.PendingAction.StartRecord
        self.pendingActionID = animal_id_var.get()
        self.pendingActionCameraIdx = cam_num

    def show_stop_dialog(self, cam_num):

        if cam_num < 0:
            if any_camera_recording(self.cam_array):
                res = messagebox.askyesno('Stop all recordings?', f'Stop recording all cameras?')
                if res:
                    for cam_obj in self.cam_array:
                        if cam_obj is not None:
                            cam_obj.stop_record()
            else:
                tk.messagebox.showinfo("Warning", "No cameras are recording")

        else:
            cam_obj = self.cam_array[cam_num]
            if cam_obj is not None and cam_obj.IsRecording:
                res = messagebox.askyesno('Stop?', f'Stop recording camera {FIRST_CAMERA_ID + cam_num}?')
                if res:
                    cam_obj.stop_record()
            else:
                tk.messagebox.showinfo("Warning", "Camera is not recording")

    def show_disk_space(self):
        disk_space = get_disk_free_space()
        if disk_space is not None:
            if any_camera_recording(self.cam_array):
                self.disk_free_label.config(text=f"Free disk space: {get_disk_free_space():.3f}GB")
            else:
                self.disk_free_label.config(text=f"Free disk space: {get_disk_free_space():.1f}GB")
        else:
            self.disk_free_label.config(text=f"Disk path \"{DATA_FOLDER}\" invalid.")

    def update_image(self):

        if self.pendingActionVar == self.PendingAction.Exiting:
            self.cleanup()
            return
        
        if self.display_frame_count == 2:
            # In root mode, window size is too small unless we fix it.
            cv2.resizeWindow(DISPLAY_WINDOW_NAME, SCREEN_RESOLUTION[0], SCREEN_RESOLUTION[1])
        
        CPU_lag_frames = 0
        num_cams_lag = 0

        for idx, cam_obj in enumerate(self.cam_array):
            
            if cam_obj.has_cam:
                CPU_lag_frames += cam_obj.CPU_lag_frames
                num_cams_lag += 1

            # Check if any updates are needed
            if cam_obj.need_update_button_state_flag:
                self.set_button_state_callback(idx)
                cam_obj.need_update_button_state_flag = False

            self.cached_frames[idx] = cam_obj.frame

            if cam_obj.status:
                # Add text to top left to show camera number. This will NOT show in recording
                cv2.putText(self.cached_frames[idx], str(FIRST_CAMERA_ID + idx),
                            (int(10 * FONT_SCALE), int(30 * FONT_SCALE)),
                            cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, (255, 128, 128),
                            round(FONT_SCALE + 0.5))  # Line thickness
                if cam_obj.IsRecording:
                    # Add red circle if recording. Again, this does not show in recorded file.
                    cv2.circle(self.cached_frames[idx],
                               (int(20 * FONT_SCALE), int(50 * FONT_SCALE)),  # x-y position
                               int(8 * FONT_SCALE),  # Radius
                               (0, 0, 255),  # Red dot (color is in BGR order)
                               -1)  # -1 thickness fills circle
        
        if num_cams_lag > 0:
            skip_display = (CPU_lag_frames / num_cams_lag) > 1 and self.display_frame_count % 10 != 0
        else:
            skip_display = False
        
        # When operated locally, Raspberry Pi5 takes about 10-15ms to show
        # frame to screen. When operated remotely, does this go up? Maybe to 20-25ms?
        # Also needs 2-5ms to print status updates (frame rate, file size).
        # So if CPU is lagging, we need to skip display
        
        if skip_display:
            # We are in danger of running late, so skip display.
            # Note that AVI/text files have already been written, so data is safe.
            
            # Checks if key is pressed. Also runs cv2 message pump, which keeps UI responsive.
            key = get_key()
            self.skipped_display_frames += 1
        else:
            # Timing is OK, go ahead and show video to screen
            if self.which_display >= 0:
                # Show just one of the 4 cameras
                cam_obj = self.cam_array[self.which_display]
                with cam_obj.cam_lock:
                    img = self.cached_frames[self.which_display]

                if cam_obj.status:
                    if self.zoom_center:
                        x1 = WIDTH >> 2
                        x2 = x1 * 3
                        y1 = HEIGHT >> 2
                        y2 = y1 * 3
                        img = img[y1:y2, x1:x2]
                        img = cv2.resize(img, [WIDTH, HEIGHT])
                if SCREEN_RESOLUTION[0] != WIDTH:
                    img = cv2.resize(img, SCREEN_RESOLUTION)
            elif self.which_display == self.CAM_VALS.ALL.value:
                # Show all 4 cameras on one screen (downsized 2x)
                for index, elt in enumerate(self.cam_array):
                    if elt is not None and elt.frame is not None:
                        # Downsize
                        subframes[index] = cv2.resize(self.cached_frames[index], SCREEN_RESOLUTION_INSET)

                # Concatenate 4 images into 1
                im_top = cv2.hconcat([subframes[0], subframes[1]])
                im_bot = cv2.hconcat([subframes[2], subframes[3]])
                img = cv2.vconcat([im_top, im_bot])
            else:
                img = None

            # This shows image to screen. Actual screen update won't happen until get_key() is called.
            self.imshow(img)
            
            # Checks if key is pressed. Also runs cv2 message pump, which keeps UI responsive and updates screen if needed
            key = get_key()

        if self.pendingActionVar == self.PendingAction.StartRecord:
            cam_idx = self.pendingActionCameraIdx
            if cam_idx == self.CAM_VALS.ALL:
                # Start stress-test on all 4 cameras
                for cam_obj in self.cam_array:
                    if cam_obj is None:
                        continue
                    cam_obj.start_record(stress_test_mode=True)
            else:
                # Start recording of a single camera
                cam_obj = self.cam_array[cam_idx]
                if cam_obj is None or not cam_obj.start_record(self.pendingActionID):
                    # Recording was attempted, but did not succeed. Usually this is
                    # because of file error, or missing codec.
                    print(f"Unable to start recording camera {cam_idx + FIRST_CAMERA_ID}.")
            self.pendingActionVar = self.PendingAction.Nothing

        self.display_frame_count = self.display_frame_count + 1
        
        # Now print status updates, such as elapsed recording time, file size.
        # This takes 2-5ms
        if self.display_frame_count % MAX_DISPLAY_FRAMES_PER_SECOND == 0:
            # Print status once per second
            
            if VERBOSE:
                print(f"Frame count: {self.display_frame_count}, CPU lag {CPU_lag_frames:.1f} frames, cumulative "
                      f"skipped frames {self.skipped_display_frames}.")

            if any_camera_recording(cam_array):
                for idx, cam in enumerate(cam_array):
                    if VERBOSE:
                        print(f"    Box {cam.box_id}, CPU load {cam.CPU_lag_frames:.3f}")

                    # Print elapsed time for each camera that is actively recording.
                    l = self.widget_array[idx].StatusLabel
                    if cam.IsRecording:
                        s = cam.get_elapsed_recording_time()
                        l.config(text=s)
                    elif l is not None:
                        l.config(text="--")

                if self.display_frame_count % (MAX_DISPLAY_FRAMES_PER_SECOND * 5) == 0:
                    # Show total remaining disk space
                    self.show_disk_space()
                    
                if key != -1:
                    self.handle_keypress(key, key >> 16, CV2KEY=True)
                    
                # Run get_key() again so status updates show to screen to make diagnostic timing info more accurate.
                key = get_key()                

        if key != -1:
            self.handle_keypress(key, key >> 16, CV2KEY=True)

        if self.pendingActionVar == self.PendingAction.Exiting:
            # Will this ever get executed? Only way would be if waitkey receives a character during self.imshow()
            self.cleanup()
            return
        
        self.top_window.after(int(self.FRAME_INTERVAL * 1000), self.update_image)

    def set_button_state_callback(self, cam_num):

        # This might be called from CamObj.stop_record_thread(), which is not the main
        # GUI thread. In that case, changing button state will pass a message back to main GUI
        # thread, so we have to make sure the GUI thread is not waiting for the lock object used
        # by stop_record_thread()

        if self.pendingActionVar == self.PendingAction.Exiting:
            # When exiting, the main GUI thread will be blocked in CamObj.close(), waiting for
            # thread to finish. So we need to avoid changing button state, as that will deadlock.
            return

        isRecording = self.cam_array[cam_num].IsRecording
        w = self.widget_array[cam_num]

        if w.StartButton is not None:
            w.StartButton["state"] = tk.DISABLED if isRecording else tk.NORMAL
        if w.StopButton is not None:
            w.StopButton["state"] = tk.NORMAL if isRecording else tk.DISABLED

    def cleanup(self):

        # Delete the OpenCV window (where video is shown)
        cv2.destroyAllWindows()

        for cam_obj in self.cam_array:
            if cam_obj is None:
                continue
            cam_obj.close()  # This stops recording, then closes camera

        # Destroy the tkinter window (control bar)
        if self.root_window is not None:
            self.root_window.destroy()


if __name__ == "__main__":

    # Create root now or else messagebox.showinfo() will do it for you, leaving an extra blank window floating around.
    root = tk.Tk()
    root.withdraw()

    if IS_LINUX:
        try:
            os.nice(-5)
        except PermissionError:
            res = messagebox.askquestion("Warning", "Unable to raise process priority.\n\n"
                                                    "Recommend running as root for optimal performance.\n\nProceed anyway?")
            if res == 'no':
                sys.exit()

    sys.setswitchinterval(0.001)
    interval = sys.getswitchinterval()

    # First camera ID number
    FIRST_CAMERA_ID = 1

    # Expand window for stereotaxic camera?
    # Isn't practical because window becomes too big.
    EXPAND_VIDEO = False

    if DEBUG:
        printt("Running in DEBUG mode. Can use keyboard 'd' to simulate TTLs for all 4 cameras.")

    MAX_DISPLAY_FRAMES_PER_SECOND = RECORD_FRAME_RATE

    if IS_PI5:
        # Setup stuff that is specific to Raspberry Pi (as opposed to Windows):
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BCM)

        # Identify camera via USB port position, rather than ID number which is unpredictable.
        IDENTIFY_CAMERA_BY_USB_PORT = True

        # Reduce display frame rate, to avoid overloading CPU on Pi
        MAX_DISPLAY_FRAMES_PER_SECOND = 10

        # GPIO.setmode(GPIO.BCM)  # Set's GPIO pins to BCM GPIO numbering
        INPUT_PIN_LIST = [4, 5, 6, 7]  # List of input pins for the four cameras
    else:
        # Don't identify by USB port. Instead, use camera ID provided by operating system, which is unpredictable.
        IDENTIFY_CAMERA_BY_USB_PORT = False
        INPUT_PIN_LIST = [None] * 4  # List of input pins for the four cameras

    if EXPAND_VIDEO:
        # This applies to the stereotax only
        # Upsample small frames to 640 width
        ratio = 1.5
        SCREEN_RESOLUTION = (int(WIDTH * ratio), int(HEIGHT * ratio))
    else:
        if WIDTH > 1024:
            # Downsample large video frames to 1024 width
            ratio = WIDTH / 1024
            SCREEN_RESOLUTION = (1024, int(HEIGHT / ratio))
            SCREEN_RESOLUTION_INSET = (512, SCREEN_RESOLUTION[1] >> 1)
        elif WIDTH < 640:
            # Upsample small frames to 640 width
            ratio = 640 / WIDTH
            SCREEN_RESOLUTION = (640, int(HEIGHT * ratio))
        else:
            SCREEN_RESOLUTION = (WIDTH, HEIGHT)

    SCREEN_RESOLUTION_INSET = (SCREEN_RESOLUTION[0] >> 1, SCREEN_RESOLUTION[1] >> 1)

    if not os.path.isdir(DATA_FOLDER):
        # Parent folder doesn't exist ... this could be due to USB drive being unplugged?
        # Default to program directory
        messagebox.showinfo(title="Warning",
                            message=f"Unable to find data folder:\n\n\"{DATA_FOLDER}\"\n\nWill save to program folder instead.")
        DATA_FOLDER = "."

    # Highest camera ID to search when first connecting. Some sources
    # recommend searching up to 99, but that takes too long and is usually
    # unnecessary. So far, I have not needed to search above about 8, but we
    # go to 15 just in case. Actually Pi4 freezes when we reach 15, so we now
    # limit to 14.
    MAX_ID = 14

    INSTRUCTION_FRAME = make_instruction_frame()

    DISPLAY_WINDOW_NAME = "Camera output"

    cam_info_array: List[CamInfo | None]

    if IDENTIFY_CAMERA_BY_USB_PORT:
        # Array of subframes for 4x1 display
        # Each "None" will be replaced with an actual CamObj object if camera detected.
        cam_info_array = [None] * 4
    else:
        # Array of camera objects, one for each discovered camera
        cam_info_array = []

    # Make subframes that are blank. These are used for 2x2 grid display.
    # Blank frames will be replaced by real ones if camera is found.
    subframes: [np.ndarray | None] = [None] * 4
    for x in range(4):
        tmp = make_blank_frame(f"{FIRST_CAMERA_ID + x} no camera found")
        subframes[x] = cv2.resize(tmp, SCREEN_RESOLUTION_INSET)

    if IDENTIFY_CAMERA_BY_USB_PORT:
        printt("Scanning for all available cameras by USB port. Please wait ...")
    else:
        printt("Scanning for all available cameras. Please wait ...")

    num_cameras_found = 0

    # Scan IDs to find cameras
    for cam_id in range(MAX_ID):
        tmp, _ = setup_cam(cam_id)
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

                if cam_info_array[port] is not None:
                    # If we already found a camera in this position ...
                    printt(f"Auto-detected more than one camera in USB port {port}, will only use first one detected")
                    continue
                cam_info_array[port] = CamInfo(cam_id,
                                               FIRST_CAMERA_ID + port,
                                               GPIO_pin=INPUT_PIN_LIST[port],
                                               queue_status=multiprocessing.Queue(),
                                               shared_memory_queue_frames=extra.shared_arrays.TimestampedArrayQueue(),
                                               queue_commands=multiprocessing.Queue())
            else:
                # If not using USB port number, then cameras are put into array
                # in the order they are discovered. This could be unpredictable, but at least
                # it will work, and won't crash. In this case, we also ignore GPIO pin list, since
                # recordings will need to be started and stopped manually.
                cam_info_array.append(CamInfo(cam_id,
                                              FIRST_CAMERA_ID + len(cam_info_array),
                                              -1,   # No GPIO if we don't know what USB port cam is plugged into
                                              extra.shared_arrays.TimestampedArrayQueue(),
                                              multiprocessing.Queue(),
                                              multiprocessing.Queue()))

            num_cameras_found += 1
            tmp.release()

    print()

    if num_cameras_found == 0:
        printt("NO CAMERAS FOUND")
        # exit()
    else:
        printt(f"Found {num_cameras_found} cameras")

    cam_array: List[CamDestinationObj | None] = [None] * len(cam_info_array)

    # Report what was discovered, and create camera RECEIVER objects
    for idx1, cam_info_obj1 in enumerate(cam_info_array):
        if cam_info_obj1 is None:
            cam_array[idx1] = CamDestinationObj(CamInfo(box_id=idx1 + FIRST_CAMERA_ID))
            continue
        else:
            # Start the DESTINATION threads that belong to the MAIN process
            cam_array[idx1] = CamDestinationObj(cam_info_obj1)
            cam_array[idx1].start_consumer_thread()

        if IDENTIFY_CAMERA_BY_USB_PORT:
            printt(
                f"Camera in USB port position {FIRST_CAMERA_ID + idx1} has ID {cam_info_obj1.id_num} and serial '{get_cam_serial(cam_info_obj1.id_num)}'",
                omit_date_time=True)
        else:
            printt(f"Camera {FIRST_CAMERA_ID + idx1} has ID {cam_info_obj1.id_num}")

    if MAX_DISPLAY_FRAMES_PER_SECOND > RECORD_FRAME_RATE:
        MAX_DISPLAY_FRAMES_PER_SECOND = RECORD_FRAME_RATE

    print()
    printt(f"Display frame rate is {MAX_DISPLAY_FRAMES_PER_SECOND}. This might be different from camera frame rate")

    # Now that DESTINATION threads are running, we can start SOURCE threads.

    # Start the SOURCE threads on a DIFFERENT PROCESS, which can be elevated to high priority.
    # If Python had the ability to set thread priority, we wouldn't need to jump through all these hoops. But alas,
    # it does not.
    p1 = multiprocessing.Process(target=source_process, args=(cam_info_array,))
    p1.start()

    if NATIVE_FRAME_RATE == 0:
        # messagebox.showinfo() causes an extraneous blank "root" window to show up in corner of screen if you haven't
        # already created it.
        tk.messagebox.showinfo("Warning",
                               "config.txt file does not specify native camera frame rate.\n\n"
                               "Will try to estimate it by profiling, but it is highly recommended "
                               "to add the true value to config.txt")

    rec_obj = RECORDER(cam_array, root_window=root)
    rec_obj.top_window.mainloop()

    if IS_PI5:
        GPIO.cleanup()

    if DEBUG:
        printt("Exiting main program.", close_file=True)
