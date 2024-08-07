#
# Simple test of GPIO pins on Raspberry Pi
#
# Will not run on Windows
#

import time
from RPi.GPIO import GPIO


class GPIO_tester:

    def __int__(self):
        self.GPIO_pin = 4
        GPIO.setup(self.GPIO_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(self.GPIO_pin, GPIO.BOTH, callback=self.GPIO_callback_both)

    def GPIO_callback_both(self, param):

        print(f'Received GPIO on pin {param}')


if __name__ == '__main__':

    gt = GPIO_tester()

    while True:
        time.sleep(.1)