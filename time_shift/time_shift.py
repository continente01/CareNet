from sklearn.cluster import KMeans
import numpy 
import requests
import json
import paho.mqtt.client as PahoMQTT
from datetime import *
import uuid
from MQTT_base import *
import threading
import time
import cherrypy


# TO DO: time shift non usa mqtt, ma si connette a thingspeak per prendere i dati
# poi invia messaggi mqtt con gli orari anomali
# TO DO: the classifiers devono essere fatti per tutti i pazienti e per tutti i field, vanno prese le informazioni dei channel da thingspeak
# need to "pre-train" the classifier to have a classification between normal and abnormal values

class TimeShift:
    exposed = True
    def __init__(self, settings):
        if 'catalogURL' not in settings or 'serviceInfo' not in settings or 'mqtt_data' not in settings or 'alarm_topic' not in settings or 'ThingspeakAdaptorURL' not in settings:
            raise ValueError("Settings must contain catalogURL, serviceInfo, mqtt_data, ThingspeakAdaptorURL and alarm_topic")
        if 'broker' not in settings["mqtt_data"] or 'port' not in settings["mqtt_data"]:
            raise ValueError("Settings must contain 'broker', 'port' in 'mqtt_data'")
        self.broker=settings["mqtt_data"]["broker"]
        self.port=settings["mqtt_data"]["port"]
        self.catalogURL=settings['catalogURL']
        self.serviceInfo=settings['serviceInfo']
        self.ThingspeakAdaptorURL=settings["ThingspeakAdaptorURL"]
        self.alarm_topic = settings["alarm_topic"]  # topic to send alarms
        if 'serviceName' not in settings['serviceInfo']:
            self.serviceInfo['serviceName'] = 'Time Shift'
        if 'pingInterval' not in settings:
            self.pingInterval = 10
        else:
            self.pingInterval = settings['pingInterval']
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
        self.clientID=str(uuid.uuid1())
        self.client=MQTT_base(self.clientID,self.broker,self.port,None) # deve mandare, non ricevere
        self.serviceID = None  
        self.serviceInfo['ID'] = self.assign_serviceID()
        self.serviceID = self.serviceInfo['ID']
        self.start()
        
    def start(self):
        self.client.start()
        self.registerService()
        # two threads are needed, one to update to catalog, the other to send alarms if the current hour is an important time for one of the patients
        self.update_thread = threading.Thread(target=self.update_loop,daemon=True)
        self.update_thread.start()
        self.send_alarm_thread = threading.Thread(target=self.send_alarm_loop,daemon=True)
        self.send_alarm_thread.start()

    def stop(self):
        self.client.stop()
        self.update_thread.join()
        self.send_alarm_thread.join()

# loop to send alarms on alarm_topic if the current hour is an important time for one of the patients
    def send_alarm_loop(self):
        while True:
            now = time.localtime()
            # Calculate seconds until next hour
            seconds_until_next_hour = (60 - now.tm_min - 1) * 60 + (60 - now.tm_sec)
            time.sleep(seconds_until_next_hour)
            self.send_alarm()


    def send_alarm(self):
        hour=int(time.strftime('%H', time.localtime()))
        UrlToSend = f'{self.catalogURL}/patients'
        try:
            response = requests.get(UrlToSend)
        except requests.exceptions.RequestException as e:
            print(f"TIME SHIFT: Error retrieving patients from catalog: {e}")
            return
        if response.status_code != 200:
            print(f"TIME SHIFT: Failed to get patients from catalog")
            return
        patients = response.json()['patients']
        print(patients)
        # Get the data from Thingspeak for each field and create classifiers
        for patient in patients:
            patientID = patient['ID']
            channelID = patient['thingspeak_info']['channelID']
            channelReadAPIkey = patient['thingspeak_info']['read_api_key']
            # get all important time for the patient
            anomaly_times = self.get_anomaly_times(channelID, channelReadAPIkey)
            if anomaly_times:
                # check for each field if the current hour is an important time for that patient
                for field in anomaly_times.keys():
                    if str(hour) in anomaly_times[field]:
                        print(f"TIME SHIFT: Alarm sent since hour {hour}:00 is an anomaly time for {patientID} for field {field}")
                        # Send the anomaly time to the MQTT broker
                        message = {
                            'alarmType': 'time_shift',
                            'patientID': patientID,
                            'field': field,
                            'hour': hour
                        }
                        self.client.publish(self.alarm_topic, message)

# loop to update the service to the catalog
    def update_loop(self):
        while True:
            time.sleep(self.pingInterval)
            self.updateService()

    def updateService(self):
        try:
            request=requests.put(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
        except requests.exceptions.RequestException:
            print(f"TIME SHIFT: failed request for updating service {self.serviceInfo['ID']} in catalog")
            return
        if request.status_code != 200:
            print(f"TIME SHIFT: failed to update service {self.serviceInfo['ID']} in catalog, registering again")
            self.registerService()  # If update fails, try to register the service again

# Function register the service to the catalog
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

# using clustering on thingspeak data, creates a dictionary for each patient that contains all fields, and for each field a list of important times
    def get_anomaly_times(self, patientID): 
        # retrieve thingspeak data
        '''data is a list of dictionaries, each dictionary has the following structure:
        [
        {
        "created_at": "2018-01-26T13:34:48Z",
        "entry_id": 13633290,
        "field1": "160"
        },
        {
        "created_at": "2018-01-26T13:35:04Z",
        "entry_id": 13633291,
        "field1": "167"
        }
        ]'''
        # request to thingspeak adaptor
        UrlToSend = f'{self.ThingspeakAdaptorURL}/{patientID}'
        try:
            response = requests.get(UrlToSend)
        except requests.exceptions.RequestException as e:
            print(f"Failed to request data for patient {patientID}: {e}")
            return None
        if response.status_code != 200:
            print(f"Failed to get data from Thingspeak Adaptor for patient {patientID}")
            return None
        if 'feeds' not in response.json():
            print(f"Invalid response from Thingspeak Adaptor for patient {patientID}")
            return None
        fields_numbered = [f"field{i+1}" for i in range(len(self.thingspeak_fields))]
        database = {field: [] for field in self.thingspeak_fields}
        feeds = response.json().get('feeds', [])
        for feed in feeds:
            for field_numbered, field_name in zip(fields_numbered, self.thingspeak_fields):
                value = feed.get(field_numbered)
                if value is not None:
                    try:
                        value = float(value)
                    except ValueError:
                        continue
                    database[field_name].append({"value": value, "created_at": feed['created_at']})

        anomaly_times = {field: [] for field in self.thingspeak_fields}
        
        for field in self.thingspeak_fields:
            last_date = ''  
            last_hour = ''  # To track the last hour and day with anomaly found, to not consider data coming from probably the same episode for the same field
            hour_counts = {}
            points = [point['value'] for point in database[field]]
            if len(points) >= 2:  # Need at least 2 points to form clusters
                points_np = numpy.array(points, dtype=float).reshape(-1, 1)
                n_clusters = 2
                random_state = 0
                classifiers = KMeans(n_clusters=n_clusters, random_state=random_state).fit(points_np)
                print(f"TIME SHIFT: classifier for field {field} for patient {patientID} created")
                # get the label of the normal value and consider it as the "normal cluster" and the data in the other cluster as the anomalies
                normal_label = classifiers.predict(numpy.array(self.normal_values[field]).reshape(-1, 1))[0]
                for point in database[field]:
                    try:
                        label = classifiers.predict(numpy.array([[point['value']]]))[0]
                    except Exception as e:
                        print(f"TIME SHIFT: Error predicting label for field {field}: {e}")
                        continue
                    # if the point is not in the "normal" cluster, check the time at which the anomaly has been registered
                    if label != normal_label:
                        created_at = point['created_at']
                        if created_at:
                            try:
                                hour = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%H")
                                date = str(datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d"))
                            except Exception:
                                continue
                            if str(last_date) != str(date) and str(last_hour) != str(hour): # since the data is ordered by date, i can check if the date and hour is the same as the last one 
                                last_date = date
                                last_hour = hour
                                hour_counts[hour] = hour_counts.get(hour, 0) + 1 # i count the anomaly only if it is the first time i see it in that hour in that date
                for h in hour_counts:
                    if hour_counts[h] > 10:
                        anomaly_times[field].append(h)
            else:
                print(f"TIME SHIFT: Not enough data points for field {field} in patient {patientID} (need at least 2, got {len(points)})")
                anomaly_times[field] = []
        return anomaly_times
                            
    # only GET service is used to retrieve anomaly times
    def GET(self, *uri, **params):
        print(f"TIME SHIFT: GET request received with uri: {uri} and params: {params}")
        if uri and uri[0]:
            try:
                patientID = int(uri[0])
            except ValueError:
                raise cherrypy.HTTPError(status=400, message='TIME SHIFT: patientID must be an integer')
        else:
            raise cherrypy.HTTPError(status=400, message='TIME SHIFT: patientID is required')       
        anomaly_times = self.get_anomaly_times(patientID)
        if anomaly_times is None:
            raise cherrypy.HTTPError(status=500, message=f'TIME SHIFT: Error calculating anomaly times for patientID {patientID}')
        return json.dumps(anomaly_times)

    def POST(self, *uri, **params):
        pass
    def PUT(self, *uri, **params):
        pass
    def DELETE(self, *uri, **params):
        pass
    
def start_api(time_shift, api_port):
    conf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_host': '0.0.0.0', 'server.socket_port': 80, 'engine.autoreload.on': False})
    # cherrypy.config.update({'server.socket_port': api_port})
    cherrypy.config.update({'engine.autoreload.on': False})
    cherrypy.tree.mount(time_shift, '/', conf)
    cherrypy.engine.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        time_shift.stop()
        cherrypy.engine.exit()
        print("Time shift Stopped")   


import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Time Shift...")
    if time_shift is not None:
        time_shift.stop()
    print("Time Shift stopped.")
    exit(0)

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == "__main__":
    try:
        settings = json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"TIME SHIFT: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"TIME SHIFT: Json settings file not found")
        exit(1)
    time_shift = None
    try:
        time_shift = TimeShift(settings)
        start_api(time_shift, settings.get('apiPort', 8082))
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down Time Shift...")
        if time_shift is not None:
            time_shift.stop()
        print("Time Shift stopped.")
        exit(0)
