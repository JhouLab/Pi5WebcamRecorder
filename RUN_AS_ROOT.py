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
    print("This script is only necessary on Linux. On Windows, it is easier to run WEBCAM_RECORD.py directly")
    os.system("python -m WEBCAM_RECORD")
elif IS_LINUX:
    wd = os.getcwd()
    # Now run WEBCAM_RECORD.py as superuser/root. The next instruction will block until user exits the program.
    # Note that we set XDG_RUNTIME_DIR to a root-appropriate folder so that GUI code doesn't issue warning.
    # We also save the current user's XDG_RUNTIME_DIR into XDG_TMP, so we can set it back when we "downgrade" to
    # a non-root user in the Browse Data Folder option (otherwise file manager won't show thumbnails, and
    # GUI programs like VLC will produce warnings). This is pretty hacky and I feel like there should be a
    # better way to do this but I haven't found it.
    os.system("cd " + wd + "; sudo XDG_RUNTIME_DIR=/tmp/runtime-root XDG_TMP=$XDG_RUNTIME_DIR python -m WEBCAM_RECORD")
    