#
# Please run this, and NOT the file WEBCAM_RECORD.py, since
# this raises process priority to avoid competing with other
# user processes.
#

import os

wd = os.getcwd()
os.system("cd " + wd + "; sudo nice -n -20 python -m WEBCAM_RECORD")
