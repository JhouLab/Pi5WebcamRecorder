import subprocess
import platform
import sys

from CamObj import *
import cv2


# If IDENTIFY_CAMERA_BY_USB_PORT is True, will try to identify camera via USB port position.
# This currently only works on the Raspberry Pi, and is not likely to work on any other platform.
if platform.system() == "Linux":
    IDENTIFY_CAMERA_BY_USB_PORT = True
else:
    # Don't identify by USB port. Instead, use camera ID provided by operating system, which is unpredictable.
    IDENTIFY_CAMERA_BY_USB_PORT = False

# Highest camera ID to search when first connecting. Some sources
# recommend searching up to 99, but that takes too long and is usually
# unnecessary. So far, I have not needed to search above about 8, but we
# go to 15 just in case.
MAX_ID = 15


# Tries to connect to a single camera based on ID. Returns a VideoCapture object if successful.
# If not successful (i.e. if there is no camera plugged in with that ID), will throw exception,
# which unfortunately is the only way to enumerate what devices are connected. The caller needs
# to catch the exception and handle it by excluding that ID from further consideration.
def setup_cam(id):
    if platform.system() == "Windows":
        tmp = cv2.VideoCapture(id, cv2.CAP_DSHOW) # On Windows, this is extremely show unless you specify DSHOW
    else:
        tmp = cv2.VideoCapture(id)
    if tmp.isOpened():
        tmp.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        tmp.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        tmp.set(cv2.CAP_PROP_FPS, 30)
    return tmp

def make_instruction_frame():
    # Frame with brief user-friendly instructions
    f = np.zeros((HEIGHT, WIDTH, 1), dtype = "uint8")
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

INSTRUCTION_FRAME = make_instruction_frame()

DISPLAY_WINDOW_NAME = "Camera output"

# Print update if user changes which camera is displaying to screen
# If user has switched to a non-working camera, show the appropriate blank frame
def print_current_display_id():
    if which_display == -1:
        print("TURNING OFF CAMERA DISPLAY.")
        cv2.imshow(DISPLAY_WINDOW_NAME, INSTRUCTION_FRAME)
        return
    
    if which_display == -2:
        print("Multi-frame display")
        return
    
    cam = cam_array[which_display]
    if cam is None or cam.cam is None:
        print("Camera in position " + str(cam_array[which_display].order) + " is disconnected")
        if cam is not None:
            # Show the blank frame now, since it will not be updated in timer loop.
            # Otherwise we will see leftover image from last good camera
            cv2.imshow(DISPLAY_WINDOW_NAME, cam.frame)
    else:
        print("Showing camera " + str(cam_array[which_display].order))

# Figure out which USB port this camera is plugged into.
def get_cam_usb_port(cam_id):
    
    # Prepare external command to extract DEVPATCH variable, which
    # encodes a string that seems to indicate USB port position.
    # Mapping of string to position is odd, making me worry it will
    # act unpredictably in the future. Please keep an eye on this function
    # to make sure it is working as expected.
    p = subprocess.Popen('udevadm info --name=/dev/video{} | grep DEVPATH= | grep -E -o "/usb[0-9]+/[0-9]+-[0-9]+/[0-9]+-[.0-9]+"'.format(cam_id),
                         stdout=subprocess.PIPE, shell=True)

    # Run the command
    (output, err) = p.communicate()

    # Wait for it to finish
    p.status = p.wait()

    # Decode the output
    response = output.decode('utf-8')
    # For some reason, decoded variables always end in newline, so we remove it.
    response = response.replace('\n', '')

    # Optional: print the detected string
#    print("DEVPATH: \"" + response + "\"")
  
    # As noted above, the mapping from USB port position to DEVPATH string
    # is weird. So I don't know how reliable this is, but it works for now.
    s_table = ["/usb3/3-1",   # Top left USB port on Pi5 (USB2)
               "/usb1/1-2",   # Top right USB port       (USB2)
               "/usb1/1-1",   # Bottom left USB port     (USB3)
               "/usb3/3-2"]   # Bottom right USB port    (USB3)
    
    for idx, s in enumerate(s_table):
        # We actually detect slightly more of the string than necessary, so
        # we use "startswith()" to match only the beginning part. The remainder
        # might be used in the future to detect if multiple cameras are plugged into
        # a single port via a hub device.
        if response.startswith(s):
            return idx

    print("Error: unable to identify USB port from DEVPATH string: \"" + response + "\"")
    return -1


# Array of camera objects, one for each discovered camera
if IDENTIFY_CAMERA_BY_USB_PORT:
    cam_array = [None] * 4
else:
    cam_array = []
    # Array of subframes for 4x1 display

# Make subframes that are blank. These are used for 2x2 grid display.
# Blank frames will be replaced by real ones if camera is found.
subframes = [None] * 4
for x in range(4):
    tmp = make_blank_frame(str(x) + " no camera found")
    subframes[x] = cv2.resize(tmp, (WIDTH>>1, HEIGHT>>1))


if IDENTIFY_CAMERA_BY_USB_PORT:
    print("Scanning for all available cameras by USB port. Please wait ...")
else:
    print("Scanning for all available cameras. Please wait ...")

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
                print("Can only show 4 cameras")
                continue
            cam_array[port] = CamObj(tmp, cam_id, port)
        else:
            # If not using USB port number, then cameras are put into array
            # in the order they are discovered. This could be unpredictable.
            cam_array.append(CamObj(tmp, cam_id, len(cam_array)))            

print()

if len(cam_array) == 0:
    print("NO CAMERAS FOUND")
    quit()

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
        cam_array[idx] = CamObj(None, -1, idx)
        continue
    
    if IDENTIFY_CAMERA_BY_USB_PORT:
        print("Camera in USB port position " + str(idx) + " has ID " + str(cam_obj.id_num))
    else:
        print("Camera " + str(idx) + " has ID " + str(cam_obj.id_num))

print_current_display_id()


# Negative numbers allows a few frames to collect before fps calculations begin. This is
# done because first few frames take longer.
frame_count = -5

FRAME_INTERVAL = 1.0 / FRAME_RATE_PER_SECOND

# infinite loop
# Camera frame is read at the very beginning of loop. At the end of the loop, is a timer
# that waits until 1/24 of a second after previous frame target. This forces all frames to
# synchronize together at 1/24 second intervals.
while True:
    
    for idx, cam_obj in enumerate(cam_array):
        if cam_obj is None:
            continue
        cam_obj.read()
        
        if cam_obj.status:
            # Show camera number in top left corner
            cv2.putText(cam_obj.frame, str(idx), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255))
            if cam_obj.IsRecording:
                # Add red circle if recording
                cv2.circle(cam_obj.frame, (20, 50), 8, (0,0,255), -1); # -1 thickness fills circle

    if which_display >= 0:
        cam_obj = cam_array[which_display]
        if cam_obj.status:
            cv2.imshow(DISPLAY_WINDOW_NAME, cam_obj.frame)
    elif which_display == -2:
        # Merge 4 frames into one, after downsizing 2x
        for index, elt in enumerate(cam_array):
            if elt is not None and elt.frame is not None:
                # Downsize
                subframes[index] = cv2.resize(elt.frame, (WIDTH>>1, HEIGHT>>1))

        im_top = cv2.hconcat([subframes[0], subframes[1]])
        im_bot = cv2.hconcat([subframes[2], subframes[3]])
        cv2.imshow(DISPLAY_WINDOW_NAME, cv2.vconcat([im_top, im_bot]))

    frame_count = frame_count + 1

    if frame_count < 0:
        # First couple of frames are slow due to launching of display window, so skip fps calculation.
        # Short 40ms sleep to force camera frames to sync up (camera requires 33ms to generate a new
        # frame, so this guarantees frame will be present when we next request it.)
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
    
    key = cv2.waitKeyEx(1) # & 0xFF

    if (key & 0xFF) != 255:
        key2 = key >> 16  # On Windows, arrow keys are encoded here
        key1 = (key >> 8) & 0xFF  # This always seems to be 0
        key = key & 0xFF          # On pi, arrow keys are coded here
        # check for 'q' key-press
        if key == ord("q"):
            #if 'q' key-pressed break out
            break

        if platform.system() == "Linux":
            isLeftArrow = key == 81
            isRightArrow = key == 83
        elif platform.system() == "Windows":
            isLeftArrow = key2 == 37
            isRightArrow = key2 == 39
        else:
            isLeftArrow = False
            isRightArrow = False

        if isLeftArrow:   # Left arrow key
            while True:
                which_display -= 1  # which_display - 1
                if which_display < -2:
                    which_display = len(cam_array) - 1
                if which_display >= 0 and cam_array[which_display] is None:
                    # If camera invalid, keep looking
                    continue
                else:
                    # Camera valid or we have negative number
                    break
            print_current_display_id()
        elif isRightArrow:   # Right arrow key
            while True:
                which_display = which_display + 1
                if which_display >= len(cam_array):
                    which_display = -2
                    break
                if which_display >= 0 and cam_array[which_display] is None:
                    # If camera is invalid, keep looking
                    continue
                else:
                    # Camera is valid, or we have negative value
                    break
            print_current_display_id()
        elif key == ord("w"):
            # Write JPG images for each camera
            for cam_obj in cam_array:
                if cam_obj.cam.isOpened():
                    cv2.imwrite("Image-" + str(cam_obj.id_num) + ".jpg", cam_obj.frame)
        elif key >= ord("0") and key <= ord("9"):
            cam_num = key - ord("0")
            if cam_num >= len(cam_array):
                print("Camera selected exceeds max value " + str(len(cam_array) - 1))
                continue
            cam_obj = cam_array[cam_num]
            if not cam_obj.IsRecording:
                if cam_obj.start_record():
                    print("Started recording camera " + str(cam_num))
                else:
                    print("Unable to start recording camera " + str(cam_num))
            else:
                cam_obj.stop_record()
                print("Stopped recording camera " + str(cam_num))

        elif key != 255:
            print("You pressed: " + str(key))

    if frame_count % 100 == 0:
        # Print status (frame # and frames per second) every 100 frames
        elapsed = time.time() - start
        fps = frame_count / elapsed
        print("Frame count: " + str(frame_count) + ", frames per second = " + str(fps))

    if time.time() > next_frame:
        # We are already too late for next frame. Oops. Report warning.
        lag_ms = (time.time() - next_frame) * 1000
        print("Warning: CPU is lagging at frame " + str(frame_count) + " by " + f"{lag_ms:.2f}" + " ms")
        
        # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
        next_frame = time.time() + FRAME_INTERVAL
    else:
        advance_ms = (next_frame - time.time()) * 1000
        # print("CPU is ahead by " + f"{advance_ms:.2f}" + " ms")
        # Wait until next frame interval has elapsed
        while time.time() < next_frame:
            pass
        
        # Next frame will actually be retrieved immediately. The following time is actually for the frame after that.
        next_frame += FRAME_INTERVAL


    
# All done. Close up windows and files
cv2.destroyAllWindows()
for cam_obj in cam_array:
    if cam_obj is None:
        continue
    cam_obj.close()
