#
# This file runs WEBCAM_RECORD as root (superuser),
# thereby allowing it to raise its own process priority
# for better latency performance.
#

import os
import platform

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')

if IS_WINDOWS:
    print("This script only works on Linux. Sorry.")
elif IS_LINUX:
    wd = os.getcwd()
    os.system("cd " + wd + "; sudo python -m WEBCAM_RECORD")
