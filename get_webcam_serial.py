import os
import subprocess

os.environ["OPENCV_LOG_LEVEL"]="FATAL"
import cv2

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


# Set up a single camera based on ID. Returns a VideoCapture object
def detect_cam(id):
    tmp = cv2.VideoCapture(id)
    if tmp.isOpened():
        tmp.release()
        return True
    return False


for x in range(15):
    if detect_cam(x):
        print("ID#" + str(x) + ", Serial: " + get_cam_serial(x))
