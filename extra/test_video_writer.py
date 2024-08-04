#
# Test h264 codec bug
#
# It appears that when writing h264 video, the last frame is lost.
# From what I can tell online, this is a bug in FFMPEG.
#

import numpy as np
import cv2

import platform

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')

xsp=640
ysp=480
chan=3

USE_H264 = True

# Define the codec and create VideoWriter object
if IS_WINDOWS:
    # Windows lacks H264 codec
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
elif IS_LINUX:
    
    if USE_H264:
        fourcc = cv2.VideoWriter_fourcc(*'h264')
    else:       
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')

out = cv2.VideoWriter('output.avi', fourcc, 10.0, (xsp, ysp), True)
frame = np.zeros((ysp, xsp, chan), np.uint8)
frame[:, :, 2] = 128  # Make red frames
frame2 = np.zeros((ysp, xsp, chan), np.uint8)
frame2[:, :, 1] = 128  # Make green frames

for i in range(30):   # init frames
    out.write(frame)
    
out.write(frame2)
out.release()
