# thermometers for body temperature
# TO DO: change catalogURL to "http://catalog" when using in docker
# "catalogURL": "http://catalog",
import random
import time
from MQTT_base import *
from sensor import Sensor

class Thermometer(Sensor):
    def __init__(self, pi):
        super().__init__(pi)
        self.deviceInfo['deviceType'] = 'thermometer'
        self.deviceInfo['commands'] = ['temperature']
        self.deviceInfo['unit'] = 'cel'  #  beats per minute
        self.message['e'][0]['u'] = 'cel'
        self.message['e'][0]['n'] = 'temperature'
        self.start_time=0
        self.fever = False
        self.start()
        

    def read_temperature(self):
        # 90% chance normal temperature, 10% fever
        if not self.fever:
            rand = random.random()
            if rand < 0.90:
                measurement = random.uniform(35, 37)
            else:
                measurement = random.uniform(38, 40)
                self.fever = True
                self.start_time = time.time()
        else:  # fever
            measurement = random.uniform(38, 40)
            if time.time() - self.start_time > 86400:  # 24 hours
                self.fever = False
        return round(measurement, 1)

    def publish(self):
        message=self.message
        # simulating detection
        message['e'][0]['v']=self.read_temperature()
        message['e'][0]['t']=time.time()

        self.client.publish(f'{self.topic}/temperature',message)
        print(f"published Message: \n {message} on topic {self.topic}/temperature")

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Thermometer...")
    if thermometer is not None:
        thermometer.stop()
    print("Thermometer stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"THERMOMETER: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"THERMOMETER: Json settings file not found")
        exit(1)
    thermometer = None
    try:
        thermometer = Thermometer(settings)
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("Shutting down sensor...")
        if thermometer is not None:
            thermometer.stop()
        print("Sensor stopped.")
        exit(0)