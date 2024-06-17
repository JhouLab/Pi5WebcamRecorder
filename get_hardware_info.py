#
#  This file contains functions that read low-level system files to determine
#  what Raspberry Pi version we are running on (4 vs 5) and to figure out which
#  USB port a camera is plugged into.
#
#  This functions only work on Linux/Pi systems. They will not work on Windows
#

import subprocess
import platform


def get_pi_version():
    if platform.system() != "Linux":
        print("This is not a Raspberry Pi/Linux system")
        return -1

    # Prepare the external command to extract serial number.
    p = subprocess.Popen('cat /sys/firmware/devicetree/base/model',
                         stdout=subprocess.PIPE, shell=True)

    (output, err) = p.communicate()
    p.status = p.wait()
    response = output.decode('utf-8')

    # Version string may be NULL terminated, which causes print() to behave strangely. So remove any null termination.
    response = response.replace("\x00", "")
    # Remove any possible newline
    response = response.replace('\n', '')

    if response.startswith('Raspberry Pi 3'):
        return 3
    elif response.startswith('Raspberry Pi 4'):
        return 4
    elif response.startswith('Raspberry Pi 5'):
        return 5

    # Probably not a Raspberry Pi
    return -1


# Figure out which USB port this camera is plugged into.
def get_cam_usb_port(cam_id) -> int:
    if platform.system() != "Linux":
        print("Function get_cam_usb_port only works on Raspberry Pi/Linux systems")
        return -1

    # Get DEVPATH variable, a string that seems to indicate USB port position.
    # Mapping of string to port position is odd, making me worry it will
    # act unpredictably in the future. For example, I have not tested this on
    # multiple Pi4s or Pi5s to see if mapping is always the same between different
    # devices of the same type/model. Please test with any new installation to
    # make sure it is working as expected.
    p = subprocess.Popen \
        ('udevadm info --name=/dev/video{} | grep DEVPATH= | grep -E -o "/usb[0-9]+/[0-9]+-[0-9]+/[0-9]+-[.0-9]+"'.format
         (cam_id), stdout=subprocess.PIPE, shell=True)

    # Run the command
    (output, err) = p.communicate()

    # Wait for it to finish
    p.status = p.wait()

    # Decode the output
    response = output.decode('utf-8')
    # For some reason, decoded variables always end in newline, so we remove it.
    response = response.replace('\n', '')

    # Optional: print the detected string
    print("DEVPATH: \"" + response + "\"")

    # As noted above, the mapping from USB port position to DEVPATH string
    # is weird. So I don't know how reliable this is, but it works for now.

    pi_version = get_pi_version()

    if pi_version == 5:
        # Py5 seems to have four distinct hubs?
        # How stable are these mappings across different devices?
        s_table = ["/usb3/3-1",  # 0 Top left USB port on Pi5 (USB2)
                   "/usb1/1-2",  # 1 Top right USB port       (USB2)
                   "/usb1/1-1",  # 2 Bottom left USB port     (USB3)
                   "/usb3/3-2"]  # 3 Bottom right USB port    (USB3)
    elif pi_version == 4:
        # Py4 seems to have just one hub, so the four ports are sub-hubs?
        # How stable are these mappings across different devices?
        s_table = ["/usb1/1-1/1-1.3",  # 0 Top left USB port on Pi4
                   "/usb1/1-1/1-1.1",  # 1 Top right USB port on Pi4
                   "/usb1/1-1/1-1.4",  # 2 Bottom left USB port on Pi4
                   "/usb1/1-1/1-1.2"]  # 3 Bottom right USB port on Pi4

    for idx, s in enumerate(s_table):
        if response.startswith(s):
            return idx

    print("Error: unable to identify USB port from DEVPATH string: \"" + response + "\"")
    return -1


def get_cam_serial(cam_id):
    if platform.system() != "Linux":
        print("Function get_cam_serial only works on Raspberry Pi/Linux systems")
        return None

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


if __name__ == '__main__':
    import sys
    import os
    os.environ["OPENCV_LOG_LEVEL"] = "FATAL"  # Suppress warnings that occur when camera id not found. This statement must occur before importing cv2
    import cv2
    
    pi = get_pi_version()
    if pi < 0:
        # Not a raspberry pi or Linux device
        sys.exit()
    print("Pi version: " + str(get_pi_version()))

    for id in range(24):
        if platform.system() == "Windows":
            tmp = cv2.VideoCapture(id, cv2.CAP_DSHOW)  # On Windows, specifying CAP_DSHOW greatly speeds up detection
        else:
            tmp = cv2.VideoCapture(id)

        if not tmp.isOpened():
            print(".", end="")
            continue
            
        s = get_cam_serial(id)
        if s is None or len(s) == 0:
            print(".", end=None)
            continue
        print(f"Camera id: {id} has serial: {s}")
        print(f"   and is plugged into USB port {get_cam_usb_port(id)}")

        
    

