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



def get_cam_usb_port(cam_id):
    
    # Prepare the external command to extract DEVPATCH
    p = subprocess.Popen('udevadm info --name=/dev/video{} | grep DEVPATH= | grep -E -o "/usb[0-9]+/[0-9]+-[0-9]+/[0-9]+-[.0-9]+"'.format(cam_id),
                         stdout=subprocess.PIPE, shell=True)

    # Run the command
    (output, err) = p.communicate()

    # Wait for it to finish
    p.status = p.wait()

    # Decode the output
    response = output.decode('utf-8')
    response = response.replace('\n', '')
    
    print("DEVPATH: \"" + response + "\"")
    
    s_table = ["/usb3/3-1",
               "/usb1/1-2",
               "/usb1/1-1",
               "/usb3/3-2"]
    
    for idx, s in enumerate(s_table):
        if response.startswith(s):
            return idx

    print("Warning: unable to identify USB port from DEVPATH string: \"" + response + "\"")
    return -1

# Set up a single camera based on ID. Returns a VideoCapture object
def detect_cam(id):
    tmp = cv2.VideoCapture(id)
    if tmp.isOpened():
        tmp.release()
        return True
    return False


for x in range(15):
    if detect_cam(x):
        print("ID#" + str(x) + ", USB port: " + str(get_cam_usb_port(x)))
