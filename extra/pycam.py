#
# Simple test of picamera on Raspberry Pi4
#

import time
from picamera2 import Picamera2, Preview

picam = Picamera2()

config = picam.create_preview_configuration()
picam.configure(config)

picam.start_preview(Preview.QTGL)

picam.start()

while True:
        time.sleep(1)

picam.capture_file("test-python.jpg")

picam.close()

