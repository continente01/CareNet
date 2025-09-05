from sklearn.cluster import KMeans
import numpy 
import requests
import json
import paho.mqtt.client as PahoMQTT
from datetime import *
# import cherrypy # not needed, will use mqtt for emergency messages
import uuid
from MQTT_base import *
from scipy import stats
import time
import threading

def generate_zscore(mean, measurement, stddev):
    if mean is None:
        print("TIME CONTROL: No normal values provided for z-score calculation")
        return None
    if measurement is None:
        print("TIME CONTROL: No measurement provided for z-score calculation")
        return None
    data= numpy.random.normal(loc=mean, scale=stddev, size=100)
    data = numpy.append(data, measurement)
    z_scores = stats.zscore(data)
    return z_scores[-1]  # Return the z-score of the measurement


class TimeControl:
    def __init__(self, settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if 'catalogURL' not in settings or 'ThingspeakAdaptorURL' not in settings or 'serviceInfo' not in settings or 'mqtt_data' not in settings or 'alarm_topic' not in settings:
            raise ValueError("Settings must contain catalogURL, ThingspeakAdaptorURL, serviceInfo, mqtt_data and alarm_topic")
        self.catalogURL = settings['catalogURL']
        self.ThingspeakAdaptorURL = settings['ThingspeakAdaptorURL']
        self.serviceInfo = settings['serviceInfo']
        self.alarm_topic = settings["alarm_topic"]
        if 'serviceName' not in settings['serviceInfo']:
            self.serviceInfo['serviceName'] = 'Time Control'
        self.pingInterval= settings.get("pingInterval", 10)
        if 'broker' not in settings["mqtt_data"] or 'port' not in settings["mqtt_data"] or 'mqtt_topic' not in settings["mqtt_data"]:
            raise ValueError("Settings must contain 'broker', 'port', and 'mqtt_topic' in 'mqtt_data'")
        self.broker = settings["mqtt_data"]["broker"]
        self.port = settings["mqtt_data"]["port"]
        self.topic = settings["mqtt_data"]["mqtt_topic"]
        self.clientID=str(uuid.uuid1())
        self.client=MQTT_base(self.clientID,self.broker,self.port,notifier=self)  # notifier is used to receive messages from the broker
        if 'thingspeak_fields' not in settings:
            self.thingspeak_fields = [
                "temperature",
                "acceleration",
                "heart_rate",
                "oxygen_saturation"
                ]
        else:
            self.thingspeak_fields = settings["thingspeak_fields"]
        if 'normal_values' not in settings:
            self.normal_values = {
                "temperature": 25,
                "acceleration": 9.81,
                "heart_rate": 70,
                "oxygen_saturation": 95
                }
        else:
            self.normal_values = settings["normal_values"]  # dictionary with the normal values for each sensor
        # check that all fields are present in normal_values
        for field in self.thingspeak_fields:
            if field not in self.normal_values.keys():
                raise ValueError(f"Missing normal value for field {field} in settings.")
        # Initialize state variables, with deafault values if missing or wrong
        self.acceleration_drop_patients= []
        self.fever_patients = []
        if "z_score_threshold" not in settings or settings["z_score_threshold"] is None or not isinstance(settings["z_score_threshold"], (int, float)):
            self.z_score_threshold = 2.5
        else:
            self.z_score_threshold = settings["z_score_threshold"]
        if "moving_average_window" not in settings or settings["moving_average_window"] is None or not isinstance(settings["moving_average_window"], int):
            self.moving_average_window = 100
        else:
            self.moving_average_window = settings["moving_average_window"]
        if "fall_detection_threshold" not in settings or settings["fall_detection_threshold"] is None or not isinstance(settings["fall_detection_threshold"], (int, float)):
            self.fall_detection_threshold = 5
        else:
            self.fall_detection_threshold = settings["fall_detection_threshold"]
        if "temperature_std" not in settings or settings["temperature_std"] is None or not isinstance(settings["temperature_std"], (int, float)):
            self.temperature_std = 0.5
        else:
            self.temperature_std = settings["temperature_std"]
        if "heart_rate_std" not in settings or settings["heart_rate_std"] is None or not isinstance(settings["heart_rate_std"], (int, float)):
            self.heart_rate_std = 7
        else:
            self.heart_rate_std = settings["heart_rate_std"]
        self.serviceID = None 
        self.serviceInfo['ID'] = self.assign_serviceID()
        self.serviceID = self.serviceInfo['ID']
        self.start()

    def start(self):
        self.registerService()
        self.client.start()
        self.client.subscribe(self.topic)
        print(f"Time Control started with ID {self.serviceInfo['ID']} on topic {self.topic}")

    def stop(self):
        self.client.stop()

 # function to register the service to the catalog
    def registerService(self):
        print(f"Registering service {self.serviceInfo['ID']} in catalog")
        registered = False
        while not registered:
            try:
                request=requests.post(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
            except requests.exceptions.RequestException:
                print(f"Failed request for registering service {self.serviceID} in catalog, retrying...")
                time.sleep(5)  # wait before retrying
            if request.status_code != 200:
                print(f"Failed to register service {self.serviceID} in catalog, retrying...")
                registered = False
                time.sleep(5) 
                self.serviceID = self.assign_serviceID()  # try to assign new id if old one is already used
                self.serviceInfo['ID'] = self.serviceID
            else:
                registered = True
        print(f"Service {self.serviceID} registered in catalog")

# assign an ID to the service   
    def assign_serviceID(self):
        # Loop until a valid service ID is obtained
        while True: 
            try:
                response = requests.get(f'{self.catalogURL}/services')
            except requests.exceptions.RequestException:
                print("Failed request for services from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"Failed to get services from catalog, status code {response.status_code}, retrying...")
                time.sleep(5)
                continue
            services = response.json()['services']
            # If serviceID is already assigned, check if it exists in the catalog
            if self.serviceID != None:  
                if not any(service['ID'] == self.serviceInfo['ID'] for service in services):
                    return self.serviceID
                else:
                    print(f"Service ID {self.serviceID} already used, assigning a new one")
                    # if the serviceID is already used, assign the next available service ID, or 1 if no services are present
                    if services != []:
                        return max(service['ID'] for service in services) + 1
                    else:
                        return 1
            else:
                # assign the next available service ID, or 1 if no services are present
                if services != []:
                    return max(service['ID'] for service in services) + 1
                else:
                    return 1     

# function to update the service to catalog
    def updateService(self):
        try:
            request=requests.put(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
        except requests.exceptions.RequestException:
            print(f"Failed request for updating service {self.serviceInfo['ID']} in catalog")
            return
        if request.status_code != 200:
            print(f"Failed to update service {self.serviceInfo['ID']} in catalog, registering again")
            self.registerService()  # If update fails, try to register the service again

# function to detect an anomaly value
    def detect_anomaly(self,sensorID, patientID, value, timestamp, field):
        if field not in self.normal_values:
            return
        # fall is detected when two consecutive values are one with smaller acceleration (free fall) and the other higher (impact)
        if field == 'acceleration':
            if patientID in self.acceleration_drop_patients:
                if value > self.normal_values[field] + self.fall_detection_threshold:
                    self.acceleration_drop_patients.remove(patientID)
                    return True
            else:
                if value < self.normal_values[field] - self.fall_detection_threshold:
                    self.acceleration_drop_patients.append(patientID)
                else:
                    self.acceleration_drop_patients.remove(patientID)
        # to check the temperature it is used the z-score of the last measurement
        if field == 'temperature':
            z_score = generate_zscore(self.normal_values[field], value, self.temperature_std)
            if z_score is None:
                print(f"TIME CONTROL: Error generating z-score for patient {patientID}")
                return
            # if the patient already has a fever, avoid to re-trigger the alarm
            if patientID in self.fever_patients:
                if abs(z_score) < self.z_score_threshold:
                    self.fever_patients.remove(patientID)
                    return False
            else:
                if abs(z_score) >= self.z_score_threshold:
                    self.fever_patients.append(patientID)
                    return True
                else:
                    return False
        # for oxygen saturation is used the moving average of the closest self.moving_average_window samples
        if field == 'oxygen_saturation':
            UrlToSend = f'{self.ThingspeakAdaptorURL}/{patientID}?field={field}&samples_number={self.moving_average_window}'
            try:
                response = requests.get(UrlToSend)
            except requests.exceptions.RequestException as e:
                print(f"TIME CONTROL: Error in request for field {field} from Thingspeak: {e}")
                return None
            if response.status_code != 200:
                print(f"TIME CONTROL: Error in response for field {field} from Thingspeak: {response.text}")
                return None
            if "feeds" not in response.json():
                print(f"TIME CONTROL: No feeds found for field {field} from Thingspeak")
                return None
            # Check the values in the feeds
            feeds = response.json()["feeds"]
            if not feeds:
                print(f"TIME CONTROL: No valid feeds found for field {field} from Thingspeak")
                return None
            # print(feeds)
            average = sum(float(feed['field']) for feed in feeds) / len(feeds)
            if abs(value - average) > self.moving_average_threshold:  # threshold of 10
                return True
            else:
                return False
        # to check the heart rate it is used the z-score of the last measurement
        if field == 'heart_rate' :
            # the check is done on the z_score of the measurement with respect to the value present in normal_values
            z_score = generate_zscore(self.normal_values[field], value, self.heart_rate_std)
            if z_score is None:
                print(f"TIME CONTROL: Error generating z-score for patient {patientID}")
                return
            # if the z_score is too high, send an alarm on alarm_topic
            if abs(z_score) >=self.z_score_threshold:
                return True
            else:
                return False

# time control is subscribed to the topics of the sensors
    def notify(self, topic, msg):
        # request device info to know what patientID is associated with the sensorID
        message = json.loads(msg)
        sensorID = message["bn"]
        field = message["e"][0]["n"]
        value = message["e"][0]["v"]
        timestamp = message["e"][0]["t"]
        try:
            response = requests.get(f'{self.catalogURL}/devices/{sensorID}')
            device_info = response.json()
        except requests.exceptions.RequestException as e:
            print(f"TIME CONTROL: Error in request device info for sensor {sensorID}: {e}")
            return
        if response.status_code == 404:
            print(f"TIME CONTROL: Device {sensorID} not found in catalog")
            return
        if response.status_code != 200:
            print(f"TIME CONTROL: catalog error getting device info for sensor {sensorID}, error: {response.text}")
            return
        print(device_info)
        if "patientID" not in device_info["device"] or device_info["device"]["patientID"] is None:
            print(f"TIME CONTROL: No patientID found in device info for sensor {sensorID}")
            return
        patientID = device_info["device"]["patientID"]
        if field not in self.thingspeak_fields:
            print(f"TIME CONTROL: field {field} for message {message} not in Thingspeak fields")
            return
        anomaly = self.detect_anomaly(sensorID, patientID, value, timestamp, field)
        if anomaly is None:
            return
        if not anomaly:
            print(f"TIME CONTROL: Normal value for patient {patientID} sensor {sensorID}, field {field}, value {value} at {timestamp}")
        else:
            print(f"TIME CONTROL: Warning for patient {patientID}, sensor {sensorID}, field {field}, value {value} at {timestamp}")
            message = {'alarmType': "time_control",
                            'patientID': patientID,
                            'sensorID': sensorID,
                            'field': field,
                            'value': value,
                            'timestamp': timestamp}
            self.client.publish(self.alarm_topic, message)

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Time Control...")
    if time_control is not None:
        time_control.stop()
    print("Time Control stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == "__main__":
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"TIME CONTROL: Error loading json settings")
        exit(1)
    except FileNotFoundError as e:
        print(f"TIME CONTROL: Error loading json settings file")
        exit(1)
    time_control = None
    try:
        time_control = TimeControl(settings)
        while True:
            time.sleep(time_control.pingInterval)
            time_control.updateService()
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down Time Control...")
        if time_control is not None:
            time_control.stop()
        print("Time Control stopped.")
        exit(0)