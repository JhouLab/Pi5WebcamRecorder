#
# This file runs WEBCAM_RECORD as root (superuser),
# thereby allowing it to raise its own process priority
# for better latency performance.
#

import os

wd = os.getcwd()
os.system("cd " + wd + "; sudo python -m WEBCAM_RECORD")
