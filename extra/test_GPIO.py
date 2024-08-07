#
# Simple test of GPIO pins on Raspberry Pi
#
# Will not run on Windows
#

import time
import RPi.GPIO as GPIO
import multiprocessing


class GPIO_tester:

    def __init__(self):
        self.GPIO_pin = 4
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.GPIO_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(self.GPIO_pin, GPIO.BOTH, callback=self.GPIO_callback)

    def GPIO_callback(self, param):

        print(f'Callback received GPIO on pin {param}, val is {GPIO.input(param)}', flush=True)


def source_process():

    gt = GPIO_tester()

    t = time.time()
    next_report = t+1
    while True:
        time.sleep(0)
        if time.time() > next_report:
            print(f'GPIO value {GPIO.input(4)}')
            next_report = next_report + 1
        if time.time() > t + 10:
            break
        
#        print(f'GPIO value {GPIO.input(4)}')

if __name__ == '__main__':
    
    if True:
        source_process()
        input('Press enter to quit')
    else:
        GPIO.cleanup()
        
        p1 = multiprocessing.Process(target=source_process)
        p1.start()
        
        input('Press enter to quit')
        
        p1.terminate()
else:
    import RPi.GPIO as GPIO

    
    
    

