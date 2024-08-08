#
# This file runs WEBCAM_RECORD.py as root (superuser),
# thereby allowing it to raise its own process priority
# for better latency performance.
#

import os
import platform

PLATFORM = platform.system().lower()
IS_LINUX = (PLATFORM == 'linux')
IS_WINDOWS = (PLATFORM == 'windows')

if IS_WINDOWS:
    print("This script is only necessary on Linux. If running on Windows, please run WEBCAM_RECORD.py directly")
elif IS_LINUX:
    wd = os.getcwd()
    # Now run WEBCAM_RECORD.py as superuser/root. The next instruction will block until user exits the program.
    os.system("cd " + wd + "; sudo python -m WEBCAM_RECORD")
