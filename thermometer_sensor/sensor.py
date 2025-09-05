# to run mqtt,in terminal put:  docker run -it -p 1883:1883 eclipse-mosquitto       
import cherrypy
import requests
import json
import random
import time
import uuid
from MQTT_base import *
import threading

class Sensor(object):
    exposed = True

    def __init__(self, settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if 'mqtt_data' not in settings or 'catalogURL' not in settings or 'deviceInfo' not in settings:
            raise ValueError("Settings must contain 'mqtt_data', 'catalogURL', and 'deviceInfo' keys")
        self.catalogURL = settings['catalogURL']
        self.deviceInfo = settings['deviceInfo']
        if 'broker' not in settings["mqtt_data"] or 'port' not in settings["mqtt_data"] or 'mqtt_topic_publish' not in settings["mqtt_data"]:
            raise ValueError("mqtt_data must contain 'broker', 'port', and 'mqtt_topic_publish' keys")
        self.broker = settings["mqtt_data"]["broker"]
        self.port = settings["mqtt_data"]["port"]
        if 'patientID' not in settings['deviceInfo']:
            raise ValueError("deviceInfo must contain 'patientID' key")
        try:
            int(settings['deviceInfo']['patientID'])  # Ensure patientID is an integer
        except ValueError:
            raise ValueError("patientID must be an integer")
        self.patientID = settings['deviceInfo']['patientID'] # patientID is used to identify the patient the sensor belongs to
        self.deviceID = None
        self.deviceInfo['ID'] = self.assign_deviceID()
        self.deviceID = self.deviceInfo['ID']
        self.clientID=str(uuid.uuid1())
        self.client=MQTT_base(self.clientID,self.broker,self.port,None)
        self.time_interval= settings.get("time_interval", 60)  # time interval for publishing data, in seconds
        self.pingInterval = settings.get("pingInterval", 10)  # default ping interval for updating device in catalog, in seconds
        self.topic = settings["mqtt_data"]["mqtt_topic_publish"]+ f'/{self.patientID}/{self.deviceID}'
        # general message to be published
        self.message={'bn':f'{self.deviceID}','e':[{'n':'','v':'', 't':'','u':''}]} # SenML Dataformat
        
    
    def start(self):
        self.client.start()
        self.registerDevice()
        self.publish_thread = threading.Thread(target=self.publish_loop,daemon=True) # daemon=True allows the thread to exit when the main program exits
        self.update_thread = threading.Thread(target=self.update_loop,daemon=True)
        self.publish_thread.start()
        self.update_thread.start()

    def stop (self):
        self.client.stop()

# This function is called by the MQTT client to publish data
    def publish_loop(self):
        print(f"SENSOR: publishing data for device {self.deviceID} on topic {self.topic}")
        while True:
            try:
                self.publish()
                time.sleep(self.time_interval)
            except Exception as e:
                print(f"SENSOR: error in publishing data: {e}")

# this function assigns a device ID to the sensor
    def assign_deviceID(self):
        # Loop until a valid service ID is obtained
        while True: 
            try:
                response = requests.get(f'{self.catalogURL}/devices')
            except requests.exceptions.RequestException:
                print("Failed request for devices from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"Failed to get devices from catalog, status code {response.status_code}, retrying...")
                continue
            devices = response.json()['devices']
            # If deviceID is already assigned, check if it exists in the catalog
            if self.deviceID != None:  
                if not any(device['ID'] == self.deviceID for device in devices):
                    return self.deviceID
                else:
                    print(f"Device ID {self.deviceID} already used, assigning a new one")
                    # if the deviceID is already used, assign the next available device ID, or 1 if no devices are present
                    if devices != []:
                        return max(device['ID'] for device in devices) + 1
                    else:
                        return 1
            else:
                # assign the next available device ID, or 1 if no devices are present
                if devices != []:
                    return max(device['ID'] for device in devices) + 1
                else:
                    return 1  

# this function registers the device in the catalog    
    def registerDevice(self):
        registered = False
        while not registered:
            try:
                request=requests.post(f'{self.catalogURL}/devices',data=json.dumps(self.deviceInfo))
            except requests.exceptions.RequestException:
                print(f"SENSOR: failed request for registering device {self.deviceID} in catalog, retrying...")
                time.sleep(5)  # wait before retrying
            if request.status_code != 200:
                if request.status_code == 404:
                    print(f"SENSOR: patient not found, please check the patientID in settings.json or add it to the catalog using the telegram bot.")
                else:
                    print(f"SENSOR: failed to register device {self.deviceID} in catalog, retrying...")
                    self.deviceID = self.assign_deviceID() # try to assign new id if old one is already used
                    self.deviceInfo['ID'] = self.deviceID
                registered = False
                time.sleep(5) 
            else:
                print(f"SENSOR: device {self.deviceID} registered in catalog")
                registered = True

# this function is called to keep the device information updated in the catalog
    def update_loop(self):
        print(f"SENSOR: updating device {self.deviceID} in catalog every {self.pingInterval} seconds")
        while True:
            self.updateDevice()
            time.sleep(self.pingInterval)
            
    def updateDevice(self):
        try:
            request=requests.put(f'{self.catalogURL}/devices',data=json.dumps(self.deviceInfo))
        except requests.exceptions.RequestException:
            print(f"SENSOR: failed request for updating device {self.deviceInfo['ID']} in catalog")
            return
        if request.status_code != 200:
            print(f"SENSOR: failed to update device {self.deviceInfo['ID']} in catalog, registering again")
            self.registerDevice()  # If update fails, try to register the device again