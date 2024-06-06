import time
import datetime
import os
import subprocess
import platform
import numpy as np

MODE = 1   # Mode 1 is is standard. Mode 2 gives higher frame rate, but 10x larger file sizes

if MODE == 1:
    # Smallest file sizes (about 100MB/hour), but also lower frame rate (10fps)
    FRAME_RATE_PER_SECOND = 10
    FOURCC = 'h264'  # Very efficient compression, but also CPU intensive
elif MODE == 2:
    # Higher frame rate, but also much larger files sizes
    FRAME_RATE_PER_SECOND = 24
    FOURCC = 'mp4v'  # Uses MPEG-4 compression, which is faster, but achieves less compression

# Resolution from all cameras.
WIDTH = 640
HEIGHT = 480


os.environ["OPENCV_LOG_LEVEL"]="FATAL"   # Suppress warnings when camera id not found

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

# Highest camera ID to search when first connecting
MAX_ID = 15

# If True, then attempt to show all active cameras, each in a separate window. This does not work well.
# If False, then show only a single active camera, and use left-right cursor keys to cycle through cameras.
SHOW_ALL = False

# Frame to show for disabled cameras
BLACK_FRAME = np.zeros((HEIGHT, WIDTH, 1), dtype = "uint8")

BLACK_FRAME_SMALL = np.zeros((HEIGHT>>1, WIDTH>>1, 1), dtype = "uint8")


def get_date_string():
    now = datetime.datetime.now()
    year = '{:04d}'.format(now.year)
    month = '{:02d}'.format(now.month)
    day = '{:02d}'.format(now.day)
    hour = '{:02d}'.format(now.hour)
    minute = '{:02d}'.format(now.minute)
    day_month_year = '{}-{}-{}_{}{}'.format(year, month, day, hour, minute)

    return day_month_year


def get_cam_serial(cam_id):
    
    # Prepare the external command to extract serial number. 
    p = subprocess.Popen('udevadm info --name=/dev/video{} | grep ID_SERIAL= | cut -d "=" -f 2'.format(cam_id),
                         stdout=subprocess.PIPE, shell=True)

    # Run the command
    (output, err) = p.communicate()

    # Wait for it to finish
    p.status = p.wait()

    # Decode the output
    response = output.decode('utf-8')

    # The response ends with a new line so remove it
    return response.replace('\n', '')


class CamObj:
    cam = None
    id_num = -1
    status = -1
    frame = None
    filename = "Video.avi"
    filename_timestamp = "Timestamp.avi"
    Writer = None
    start_time = -1           # Timestamp when recording started.
    
    def __init__(self, cam, id_num):
        self.cam = cam
        self.id_num = id_num
        
        self.filename = get_date_string() + "_Video" + str(id_num) + ".avi"
        self.filename_timestamp = get_date_string() + "_Timestamp" + str(id_num) + ".txt"
        codec = cv2.VideoWriter_fourcc(*FOURCC)
        resolution = (WIDTH, HEIGHT)
        self.Writer = cv2.VideoWriter(self.filename, codec, FRAME_RATE_PER_SECOND, resolution)
        
        self.fid = open(self.filename_timestamp, 'w')
        self.fid.write('Relative timestamps\n')
        
    def start_record(self, id):
        
        pass
    
    # Reads a single frame from CamObj class
    def read(self):
        try:
            if self.cam is not None and self.cam.isOpened():
                # Read frame if camera is available and open
                self.status, self.frame = self.cam.read()
                
                if self.Writer is not None and self.frame is not None:
                    if self.fid is not None and self.start_time > 0:
                        # Write timestamp to text file. Do this before writing AVI so that
                        # timestamp will not include latency required to compress video. This
                        # ensures most accurate possible timestamp.
                        self.fid.write(str(time.time() - self.start_time) + "\n")
                    # Write frame to AVI video file if possible
                    self.Writer.write(self.frame)
                    
                return self.status, self.frame
            else:
                # Camera is not available.
                self.status = 0
                self.frame = None
                return 0, None
        except:
            # Read failed. Remove this camera so we won't attempt to read it later.
            # Should we set a flag to try to periodically reconnect?
            self.cam = None
            self.status = 0
            self.frame = None
            
            # Warn user that something is wrong.
            print("Unable to read frames from camera ID #" + str(self.id_num) + ". Will stop recording and display.")

    
    def close(self):
        if self.Writer is not None:
            try:
                # Close Video file
                self.Writer.release()
            except:
                pass
            self.Writer = None
        if self.cam is not None:
            try:
                # Release camera resources
                self.cam.release()
            except:
                pass
            self.cam = None
        if self.fid is not None:
            try:
                # Close text timestamp file
                self.fid.close()
            except:
                pass
            self.fid = None
            
        self.status = -1
        self.frame = None
        

# Set up a single camera based on ID. Returns a VideoCapture object
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

# Print update if user changes which camera is displaying to screen
def print_current_display_id():
    if which_display == -1:
        print("TURNING OFF CAMERA DISPLAY.")
        cv2.imshow("Out", BLACK_FRAME)
        return
    
    if which_display == -2:
        print("Multi-frame display")
        return
    
    cam = cam_array[which_display]
    if cam.cam is None:
        print("Camera with ID #" + str(cam_array[which_display].id_num) + " is disconnected")
    else:
        print("Showing camera with ID #" + str(cam_array[which_display].id_num))

# Array of camera objects, one for each discovered camera
cam_array = []

# Array of subframes for 4x1 display
subframes = [None] * 4

print("Scanning for all available cameras. Please wait ...")

# Scan IDs to find cameras
for cam_id in range(MAX_ID):
    tmp = setup_cam(cam_id)
    print(".", end="", flush=True)
    if tmp.isOpened():
        cam_array.append(CamObj(tmp, cam_id))

print()

if len(cam_array) == 0:
    print("NO CAMERAS FOUND")
    quit()
    
# Report what was discovered
for cam_obj in cam_array:
    print("Found camera ID: " + str(cam_obj.id_num))

# Which one to display
which_display = 0
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
    
    for cam_obj in cam_array:
        cam_obj.read()

    if SHOW_ALL:
        for cam_obj in cam_array:
            # Display to window
            if cam_obj.status:
                cv2.imshow("Out" + str(cam_obj.id_num), cam_obj.frame)
    else:
        if which_display >= 0:
            cam_obj = cam_array[which_display]
            if cam_obj.status:
                cv2.imshow("Out", cam_obj.frame)
            else:
                cv2.imshow("Out", BLACK_FRAME)
        elif which_display == -2:
            # Concatenate
            try:
                for index, elt in enumerate(cam_array):
                    if elt.frame is not None:
                        subframes[index] = cv2.resize(elt.frame, (320, 240))
                    else:
                        subframes[index] = BLACK_FRAME_SMALL
                im_top = cv2.hconcat([subframes[0], subframes[1]])
                im_bot = cv2.hconcat([subframes[2], subframes[3]])
                cv2.imshow("Out", cv2.vconcat([im_top, im_bot]))
            except:
                pass
                                 

    frame_count = frame_count + 1

    if frame_count < 0:
        # First couple of frames are slow due to launching of display window, so skip fps calculation.
        # Short 40ms sleep to force camera frames to sync up (camera requires 33ms to generate a new
        # frame, so this guarantees frame will be present when we next request it.)
        time.sleep(.04)
        continue
    
    if frame_count == 0:
        # Now that the first few frames are done, we can start timer and should get stable readings
        # Another 40ms sleep to ensure frame is present
        time.sleep(.04)
        start = time.time()
        for cam in cam_array:
            cam.start_time = start
        
        # This is actually target time for the frame AFTER the next, since the next one will be read immediately
        next_frame = start + FRAME_INTERVAL
        continue
    
    key = cv2.waitKey(1) & 0xFF
    # check for 'q' key-press
    if key == ord("q"):
        #if 'q' key-pressed break out
        break
    
    if key == 81:   # Left arrow key
        which_display -= 1  # which_display - 1
        if which_display < -2:
            which_display = len(cam_array) - 1
        print_current_display_id()
    elif key == 83:   # Right arrow key
        which_display = which_display + 1
        if which_display >= len(cam_array):
            which_display = -2
        print_current_display_id()
    elif key == ord("w"):
        # Write JPG images for each camera
        for cam_obj in cam_array:
            if cam_obj.cam.isOpened():
                cv2.imwrite("Image-" + str(cam_obj.id_num) + ".jpg", cam_obj.frame)
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
    if cam_obj.cam.isOpened():
        cam_obj.close()
