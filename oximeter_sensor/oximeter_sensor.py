# TO DO: change catalogURL to "http://catalog" when using in docker
# "catalogURL": "http://catalog",
# TO DO: change duration of low oxigen to 10-20 minutes (more realistic)
import random
import time
from MQTT_base import *
from sensor import Sensor

class Oximeter(Sensor):
    def __init__(self, pi):
        super().__init__(pi)
        self.deviceInfo['deviceType'] = 'oximeter'
        self.deviceInfo['commands'] = ['oxygen_saturation']
        self.deviceInfo['unit'] = '%'  #  beats per minute
        self.message['e'][0]['u'] = '%'
        self.message['e'][0]['n'] = 'oxygen_saturation'
        self.start_time = 0
        self.anomaly = False
        self.start()

    def read_oxygen_saturation(self):
    # 85% chance normal oxygen saturation, 15% low oxygen saturation
        if not self.anomaly:
            rand = random.random()
            if rand < 0.85:
                measurement = int(random.uniform(95, 100))
            else:
                measurement = int(random.uniform(70, 95))
                self.anomaly = True
                self.start_time = time.time()

        else:  # low oxygen saturation
            measurement = int(random.uniform(70, 95))
            if time.time() - self.start_time > 600:  # 10 minutes
                self.anomaly = False
                
        return measurement
    
    def publish (self):
        message=self.message
        # simulating detection
        message['e'][0]['v']=self.read_oxygen_saturation()
        message['e'][0]['t']=time.time()

        self.client.publish(f'{self.topic}/{self.deviceID}/oxygen_saturation',message)
        print(f"published Message: \n {message}")

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Oximeter...")
    if oximeter is not None:
        oximeter.stop()
    print("Oximeter stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"OXIMETER: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"OXIMETER: Json settings file not found")
        exit(1)
    oximeter = None
    try:
        oximeter = Oximeter(settings)
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("Shutting down sensor...")
        if oximeter is not None:
            oximeter.stop()
        print("Sensor stopped.")
        exit(0)