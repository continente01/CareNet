# TO DO: change catalogURL to "http://catalog" when using in docker
# "catalogURL": "http://catalog",
import random
import time
from MQTT_base import *
from sensor import Sensor

class HeartRateSensor(Sensor):
    def __init__(self,settings):
        super().__init__(settings)
        self.deviceInfo['deviceType'] = 'heart_rate_sensor'
        self.deviceInfo['commands'] = ['heart_rate']
        self.deviceInfo['unit'] = 'bpm'  #  beats per minute
        self.message['e'][0]['u'] = 'bpm'
        self.message['e'][0]['n'] = 'heart_rate'
        self.start_time=0
        self.anomaly=0
        self.start()
        

    # simulation of heart rate measurement
    def read_heart_rate(self):
    # 70% chance normal heart rate, 15% low heart rate, 15% high heart rate
        if self.anomaly == 0:
            rand = random.random()
            if rand < 0.7:
                measurement = int(random.uniform(60, 80))
            elif rand < 0.85:
                measurement = int(random.uniform(40, 60))
                self.anomaly = 1  # set anomaly to low heart rate
                self.start_time = time.time()
            else:
                measurement = int(random.uniform(80, 100))
                self.anomaly = 2  # set anomaly to high heart rate
                self.start_time = time.time()
        
        elif self.anomaly == 1:  # low heart rate
            if time.time() - self.start_time > 300:  # 5 minutes
                self.anomaly = 0  # reset anomaly
            measurement = int(random.uniform(40, 60))

        else:  # high heart rate
            if time.time() - self.start_time > 300:  # 5 minutes
                self.anomaly = 0  # reset anomaly
            measurement = int(random.uniform(80, 100))

        return measurement

    def publish (self):
        message=self.message
        # simulating detection
        message['e'][0]['v']=self.read_heart_rate()
        message['e'][0]['t']=time.time()

        self.client.publish(f'{self.topic}/heart_rate/{self.deviceID}',message)
        print(f"published Message: \n {message}")

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Heart Rate Sensor...")
    if heart_rate_sensor is not None:
        heart_rate_sensor.stop()
    print("Heart Rate Sensor stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"HEART RATE SENSOR: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"HEART RATE SENSOR: Json settings file not found")
        exit(1)
    heart_rate_sensor = None
    try:
        heart_rate_sensor = HeartRateSensor(settings)
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("Shutting down sensor...")
        if heart_rate_sensor is not None:
            heart_rate_sensor.stop()
        print("Sensor stopped.")
        exit(0)
    