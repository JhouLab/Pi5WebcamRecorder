import numpy as np
import cv2

import platform

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')

xsp=640
ysp=480
chan=3
# Define the codec and create VideoWriter object
if IS_WINDOWS:
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
elif IS_LINUX:
    fourcc = cv2.VideoWriter_fourcc(*'h264')

out = cv2.VideoWriter('output.avi', fourcc, 20.0, (xsp, ysp), True)
frame = np.zeros((ysp, xsp, chan), np.uint8)
for i in range(20):   # init frames
    out.write(frame)
out.release()
