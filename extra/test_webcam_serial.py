#
# This is a barebones script that tries to detect all cameras.
#
# It works by cycling through all possible IDs from 0 to 99 and seeing if they exist
# and if they do, tries to get info about it, such as serial number and USB port
# location. This will run under both Linux/Pi and Windows, but you'll get much more info
# on Linux/Pi.
#

import os
from get_hardware_info import *

os.environ["OPENCV_LOG_LEVEL"]="FATAL"  # Must place this before import cv2, to suppress warnings
import cv2


# Set up a single camera based on ID. Returns a VideoCapture object
def detect_cam(cam_id):

    if platform.system() == "Windows":
        tmp = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW) # On Windows, specifying CAP_DSHOW greatly speeds up detection
    else:
        tmp = cv2.VideoCapture(cam_id)

    if tmp.isOpened():
        tmp.release()
        return True
    return False


if platform.system() == "Linux":
    pi_version = get_pi_version()
    print("Pi version: " + str(pi_version))

print("Scanning cameras by ID number:")
for name in range(99):
    if detect_cam(name):
        print("\nCamera found with ID#: " + str(name) + "\n ")
        if platform.system() == "Linux":
            print("  Has serial #: " + get_cam_serial(name))
            print("  Has USB port: " + str(get_cam_usb_port(name)))
    else:
        # Print dot so we know progress is happening
        print(".", end="")

print()
print()

if platform.system() == "Windows":

    print("Now trying alternate Windows-specific method of enumerating cameras")

    # The following code is copied from:
    # https://stackoverflow.com/questions/73946689/get-usb-camera-id-with-open-cv2-on-windows-10
    import asyncio
    # Warning: the following will fail in DEBUG mode unless you comment out _winrt.init_apartment()
    # in the file: site-packages\winrt\__init__.py
    import winrt.windows.devices.enumeration as windows_devices
    from pprint import pprint

    async def get_camera_info():
        return await windows_devices.DeviceInformation.find_all_async(4)

    connected_cameras = asyncio.run(get_camera_info())
    names = [camera.name for camera in connected_cameras]

    for camera in connected_cameras:
        print("Camera found with name: " + camera.name + ", having id: " + str(camera.id))
#        pprint(dir(camera))  # Prints all fields of object camera

