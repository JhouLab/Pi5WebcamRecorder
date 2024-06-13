import time
import numpy as np
import math
from CamObj import CamObj, WIDTH, HEIGHT, FRAME_RATE_PER_SECOND, make_blank_frame
from get_hardware_info import *
import cv2
from sys import gettrace


# If true, will print extra diagnostics, such as a running frame count and FPS calculations
VERBOSE = False

# First camera ID number
FIRST_CAMERA_ID = 1


DEBUG = gettrace() is not None


if DEBUG:
    print("Running in DEBUG mode. Can use keyboard letter 'd' to test TTL for camera 1")

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
    INPUT_PIN_LIST = [4, 5, 6, 7]   # List of input pins for the four cameras
    for p in INPUT_PIN_LIST:
        try:
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Set to be input, with internal pull-up but not pull-down
        except RuntimeError:
            print("Unable to set up GPIO. If this is a Pi5, please replace the default gpio library as follows:")
            print("    sudo apt remove python3-rpi.gpio")
            print("    sudo apt install python3-rpi-lgpio")
            exit()
else:
    # Don't identify by USB port. Instead, use camera ID provided by operating system, which is unpredictable.
    IDENTIFY_CAMERA_BY_USB_PORT = False
    INPUT_PIN_LIST = [None] * 4   # List of input pins for the four cameras


# Tries to connect to a single camera based on ID. Returns a VideoCapture object if successful.
# If not successful (i.e. if there is no camera plugged in with that ID), will throw exception,
# which unfortunately is the only way to enumerate what devices are connected. The caller needs
# to catch the exception and handle it by excluding that ID from further consideration.
def setup_cam(id):
    if platform.system() == "Windows":
        tmp = cv2.VideoCapture(id, cv2.CAP_DSHOW)  # On Windows, specifying CAP_DSHOW greatly speeds up detection
    else:
        tmp = cv2.VideoCapture(id)

    if tmp.isOpened():
        tmp.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        tmp.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return tmp


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
    cv2.putText(f, "Video off. Recordings will continue.",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
    cv2.putText(f, "Left-right cursor cycles cameras.",
                (10, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
    cv2.putText(f, "Q to quit, 0-3 to start/stop record.",
                (10, 110),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
    return f


# Print message indicating which camera is displaying to screen.
def print_current_display_id():
    if which_display == -1:
        print("TURNING OFF CAMERA DISPLAY.")
        cv2.imshow(DISPLAY_WINDOW_NAME, INSTRUCTION_FRAME)
        return

    if which_display == -2:
        print("Multi-frame display")
        return

    cam = cam_array[which_display]
    cam_position = cam.order
    if cam is None or cam.cam is None:
        print(f"Camera in position {cam_position} is disconnected")
        if cam is not None:
            # Show the blank frame now, since it will not be updated in timer loop.
            # Otherwise we will see leftover image from last good camera
            cv2.imshow(DISPLAY_WINDOW_NAME, cam.frame)
    else:
        print(f"Showing camera {cam_position}")


# Highest camera ID to search when first connecting. Some sources
# recommend searching up to 99, but that takes too long and is usually
# unnecessary. So far, I have not needed to search above about 8, but we
# go to 15 just in case. Actually Pi4 freezes when we reach 15, so we now
# limit to 14.
MAX_ID = 14

INSTRUCTION_FRAME = make_instruction_frame()

DISPLAY_WINDOW_NAME = "Camera output"

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
    subframes[x] = cv2.resize(tmp, (WIDTH >> 1, HEIGHT >> 1))

if IDENTIFY_CAMERA_BY_USB_PORT:
    print("Scanning for all available cameras by USB port. Please wait ...")
else:
    print("Scanning for all available cameras. Please wait ...")

num_cameras_found = 0

# Scan IDs to find cameras
for cam_id in range(MAX_ID):
    tmp = setup_cam(cam_id)
    print(".", end="", flush=True)
    if tmp.isOpened():
        if IDENTIFY_CAMERA_BY_USB_PORT:
            # Attempt to identify what USB port this camera is plugged into.
            # Method is very klugey, and I don't really understand why it works.
            # But it does. For now. I hope.
            port = get_cam_usb_port(cam_id)
            if port < 0:
                print("Unable to identify USB port. Won't show camera. Please contact developer.")
                continue
            if port > 3:
                print(f"Invalid USB port number (should be 0-3): {port}")
                continue

            if cam_array[port] is not None:
                # If we already found a camera in this position ...
                print(f"Auto-detected more than one camera in USB port {port}, will only use first one detected")
                continue
            cam_array[port] = CamObj(tmp, cam_id,
                                     FIRST_CAMERA_ID + port, GPIO_pin=INPUT_PIN_LIST[port])
            num_cameras_found += 1
        else:
            # If not using USB port number, then cameras are put into array
            # in the order they are discovered. This could be unpredictable, but at least
            # it will work, and won't crash. In this case, we also ignore GPIO pin list, since
            # recordings will need to be started and stopped manually.
            cam_array.append(CamObj(tmp, cam_id, FIRST_CAMERA_ID + len(cam_array)))
            num_cameras_found += 1

print()

if len(cam_array) == 0:
    print("NO CAMERAS FOUND")
    quit()
else:
    print(f"Found {num_cameras_found} cameras")

# Which camera to display initially. User can change this later with arrow keys.
#
# -2 shows all 4 cameras in a 2x2 grid
# -1 turns off display
#  0 shows whatever is plugged into top left USB port
#  1 shows top right USB port camera
#  2 shows bottom left USB port camera
#  3 shows bottom right USB port camera
which_display = -2

# Report what was discovered
for idx, cam_obj in enumerate(cam_array):
    if cam_obj is None:
        # No camera was found for this USB port position.
        # Create dummy camera object as placeholder, allowing a blank frame
        # to show.
        cam_array[idx] = CamObj(None, -1, FIRST_CAMERA_ID + idx)
        continue

    if IDENTIFY_CAMERA_BY_USB_PORT:
        print(f"Camera in USB port position {FIRST_CAMERA_ID + idx} has ID {cam_obj.id_num}")
    else:
        print(f"Camera {FIRST_CAMERA_ID + idx} has ID {cam_obj.id_num}")

print_current_display_id()

frame_count = -1

FRAME_INTERVAL = 1.0 / FRAME_RATE_PER_SECOND

# Report status every 30 seconds
STATUS_REPORT_INTERVAL = FRAME_RATE_PER_SECOND * 30

# infinite loop
# Camera frame is read at the very beginning of loop. At the end of the loop, is a timer
# that waits until 1/FRAME_RATE_PER_SECOND seconds after previous frame target, forcing all
# cameras to sync up at this interval.
while True:

    for idx, cam_obj in enumerate(cam_array):
        # Read camera frame
        cam_obj.read()

        if cam_obj.status:
            # Add text to top left to show camera number
            cv2.putText(cam_obj.frame, str(FIRST_CAMERA_ID + idx), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
            if cam_obj.IsRecording:
                # Add red circle if recording
                cv2.circle(cam_obj.frame, (20, 50), 8, (0, 0, 255), -1)   # -1 thickness fills circle

    if which_display >= 0:
        # Show just one of the 4 cameras
        cam_obj = cam_array[which_display]
        if cam_obj.status:
            cv2.imshow(DISPLAY_WINDOW_NAME, cam_obj.frame)
    elif which_display == -2:
        # Show all 4 cameras on one screen (downsized 2x)
        for index, elt in enumerate(cam_array):
            if elt is not None and elt.frame is not None:
                # Downsize
                subframes[index] = cv2.resize(elt.frame, (WIDTH >> 1, HEIGHT >> 1))

        # Concatenate 4 images into 1
        im_top = cv2.hconcat([subframes[0], subframes[1]])
        im_bot = cv2.hconcat([subframes[2], subframes[3]])
        cv2.imshow(DISPLAY_WINDOW_NAME, cv2.vconcat([im_top, im_bot]))

    frame_count = frame_count + 1

    if frame_count < 0:
        # First couple of frames are slow due to launching of display window, so skip fps calculation.
        # Short 40ms sleep to force camera frames to sync up. Camera requires 33ms to generate new
        # frame, so this guarantees frame will be present when we next request it.
        time.sleep(.04)
        continue

    if frame_count == 0:
        # Now that the first few frames are done, we can start timer and should get stable FPS readings
        # Another 40ms sleep to ensure frame is present
        time.sleep(.04)
        start = time.time()

        # This is actually target time for the frame AFTER the next, since the next one will be read immediately
        next_frame = start + FRAME_INTERVAL
        continue

    # Check if any key has been pressed. Note use of waitKeyEx(), which
    # is compatible with cursor keys on Windows whereas waitKey() is not.
    key = cv2.waitKeyEx(1)

    if (key & 0xFF) != 255:
        key2 = key >> 16  # On Windows, arrow keys are encoded here
        key1 = (key >> 8) & 0xFF  # This always seems to be 0
        key = key & 0xFF  # On Raspberry Pi, arrow keys are coded here along with all other keys

        # check for 'q' key-press
        if key == ord("q"):
            # if 'q' key-pressed break out
            break

        if platform.system() == "Linux":
            # Raspberry Pi encodes arrow keys in lowest byte
            isLeftArrow = key == 81
            isRightArrow = key == 83
        elif platform.system() == "Windows":
            # Windows encodes arrow keys in highest byte
            isLeftArrow = key2 == 37
            isRightArrow = key2 == 39
        else:
            isLeftArrow = False
            isRightArrow = False

        if isLeftArrow:  # Left arrow key
            which_display -= 1
            if which_display < -2:
                which_display = len(cam_array) - 1
            print_current_display_id()
        elif isRightArrow:  # Right arrow key
            which_display += 1
            if which_display >= len(cam_array):
                which_display = -2
            print_current_display_id()
        elif DEBUG and key == ord("d"):
            # Special debugging keystroke that simulates TTL input in regards to camera 1
            for cam_obj in cam_array:
                if cam_obj is not None:
                    cam_obj.handle_GPIO()
        elif key == ord("w"):
            # Write JPG images for each camera
            for cam_obj in cam_array:
                if cam_obj.cam.isOpened():
                    cam_obj.take_snapshot()
        elif key >= ord("0") and key <= ord("9"):
            # Start/stop recording for specified camera
            cam_num = key - ord("0")
            cam_idx = cam_num - FIRST_CAMERA_ID
            if cam_idx >= len(cam_array):
                print(f"Camera number {cam_num} does not exist, won't record.")
            else:
                cam_obj = cam_array[cam_idx]
                if cam_obj is None:
                    print(f"Camera number {cam_num} not found, won't record.")
                else:
                    if not cam_obj.IsRecording:
                        if cam_obj.start_record():
                            # Successfully started recording.
#                            print(f"Started recording camera {cam_num}")
                            pass  # We now notify user within the start_record() function itself.
                        else:
                            # Recording was attempted, but did not succeed. Usually this is
                            # because of file error, or missing codec.
                            print(f"Unable to start recording camera {cam_num}.")
                    else:
                        cam_obj.stop_record()

        elif DEBUG and key != 255:
            print(f"You pressed: {key}")

    if frame_count % STATUS_REPORT_INTERVAL == 0:
        # Print status periodically (frame # and frames per second)
        if VERBOSE:
            elapsed = time.time() - start
            fps = frame_count / elapsed
            print(f"Frame count: {frame_count}, frames per second = {fps}")

            if any_camera_recording(cam_array):
                print("Camera recording status:")
                for x in cam_array:
                    # Print elapsed time for each camera that is actively recording.
                    if x is not None and x.cam is not None:
                        if x.IsRecording:
                            x.print_elapsed()

    if time.time() > next_frame:
        # We are already too late for next frame. Oops. Report warning if any recording is ongoing, as there might be missed frames
        lag_ms = (time.time() - next_frame) * 1000
        if any_camera_recording(cam_array):
            print(f"Warning: CPU is lagging at frame {frame_count} by {lag_ms:.2f} ms. Might experience up to {int(math.ceil(lag_ms/100))} dropped frame(s).")

        # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
        next_frame = time.time() + FRAME_INTERVAL
    else:
        # We are done with loop, but not ready to request next frame. Wait a bit.
        advance_ms = (next_frame - time.time()) * 1000
        # print("CPU is ahead by " + f"{advance_ms:.2f}" + " ms")
        # Wait until next frame interval has elapsed
        while time.time() < next_frame:
            if next_frame - time.time() > 0.005:
                # Sleep in 5ms increments to reduce CPU usage. Otherwise this
                # loop will hog close to 100% CPU
                time.sleep(0.005)
            pass

        # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
        next_frame += FRAME_INTERVAL
        

# All done. Close up windows and files
cv2.destroyAllWindows()
for cam_obj in cam_array:
    if cam_obj is None:
        continue
    cam_obj.stop_record()

for cam_obj in cam_array:
    if cam_obj is None:
        continue
    cam_obj.close()

print("Exiting")

