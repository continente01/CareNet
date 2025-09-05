# wearable accelerometers for fall detection
# TO DO: change catalogURL to "http://catalog" when using in docker
# "catalogURL": "http://catalog",
import random
import time
from MQTT_base import *
from sensor import Sensor

class Accelerometer(Sensor):
    def __init__(self, pi):
        super().__init__(pi)
        self.deviceInfo['deviceType'] = 'accelerometer'
        self.deviceInfo['commands'] = ['y'] 
        self.deviceInfo['unit'] = 'm/s2'  # unit of acceleration m/s2
        self.message['e'][0]['u'] = 'm/s2'
        self.message['e'][0]['n'] = 'acceleration'
        self.fall=False
        self.start()

    def read_fall_detection(self):
        # 90% chance normal acceleration, 1% fall detection, 9% acceleration but no fall
        if not self.fall:
            rand = random.random()
            if rand < 0.90:
                measurement = random.uniform(9.81*0.9, 9.81*1.1)
            else:
                # fast deceleration, free fall
                measurement = random.uniform(0.5*9.81*0.9, 0.5*9.81*1.1)  
                if rand > 0.99:  # 1% chance to be a fall, in other cases false alarm
                    self.fall = True
        else: # fall impact, fast acceleration
            self.fall = False
            measurement = random.uniform(9.81*0.9*2, 9.81*1.1*2)  
        return measurement
    
    def publish (self):
        # read and publish fall detection measurement
        message=self.message
        # simulating detection
        message['e'][0]['v']=self.read_fall_detection()    
        message['e'][0]['t']=time.time()
        
        self.client.publish(f'{self.topic}/acceleration/{self.deviceID}',message)
        print(f"published Message: \n {message}")

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Accelerometer...")
    if accelerometer is not None:
        accelerometer.stop()
    print("Accelerometer stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"ACCELEROMETER: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"ACCELEROMETER: Json settings file not found")
        exit(1)
    accelerometer = None
    try:
        accelerometer = Accelerometer(settings)
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("Shutting down sensor...")
        if accelerometer is not None:
            accelerometer.stop()
        print("Sensor stopped.")
        exit(0)
    