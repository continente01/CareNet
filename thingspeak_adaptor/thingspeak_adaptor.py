# TO DO: change catalogURL to "http://catalog" when using in docker
# "catalogURL": "http://catalog",

import requests
import json
from MQTT_base import *
import random
import time
import uuid
import cherrypy
import threading

class Thingspeak_Adaptor:
    exposed = True  
    def __init__(self,settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if 'catalogURL' not in settings or 'serviceInfo' not in settings or 'ThingspeakURL' not in settings or 'mqtt_data' not in settings or 'UserAPIKey' not in settings:
            raise ValueError("Settings must contain 'catalogURL', 'serviceInfo', 'ThingspeakURL', 'mqtt_data' and 'UserAPIKey'")
        self.catalogURL=settings['catalogURL']
        self.serviceInfo=settings['serviceInfo']
        self.ThingspeakURL=settings["ThingspeakURL"]
        self.userAPIKey=settings['UserAPIKey']
        if 'port' not in settings['mqtt_data'] or 'broker' not in settings['mqtt_data'] or 'mqtt_topic' not in settings['mqtt_data']:
            raise ValueError("Settings must contain 'port' in 'mqtt_data'")
        self.broker = settings["mqtt_data"]["broker"]
        self.port = settings["mqtt_data"]["port"]
        self.topic = settings["mqtt_data"]["mqtt_topic"] # /# is added to indicate that all patients and sensors are read
        if 'pingInterval' not in settings:
            self.pingInterval = 10
        else:
            self.pingInterval = settings['pingInterval']
        self.clientID = str(uuid.uuid1())
        self.client = MQTT_base(self.clientID, broker=self.broker, port=self.port, notifier=self)
        if 'thingspeak_fields' not in settings:
            self.thingspeak_fields = [
                "temperature",
                "acceleration",
                "heart_rate",
                "oxygen_saturation"
                ]
        else:
            self.thingspeak_fields = settings["thingspeak_fields"]
        if 'apiPort' not in settings:
            self.api_port = 8081
        else:
            self.api_port = settings['apiPort']
        self.serviceID = None
        self.serviceInfo['ID'] = self.assign_serviceID()  # Assign service ID
        self.serviceID = self.serviceInfo['ID']
        self.start()

# one additional thread needed to update the service in the catalog
    def start(self):
        self.registerService()
        self.update_thread = threading.Thread(target=self.update_loop,daemon=True)
        self.update_thread.start()
        self.client.start()
        self.client.subscribe(self.topic)
        print(f"Thingspeak Adaptor started with ID {self.serviceInfo['ID']} on topic {self.topic}")

    def stop(self):
        self.client.stop()
        self.update_thread.join()

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

# register the service in the catalog
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

# update the service in the catalog every pingInterval seconds       
    def update_loop(self):
        print(f"THINGSPEAK: updating device {self.serviceID} in catalog every {self.pingInterval} seconds")
        while True:
            self.updateService()
            time.sleep(self.pingInterval)

    def updateService(self):
        try:
            request=requests.put(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
        except requests.exceptions.RequestException:
            print(f"THINGSPEAK: failed request for updating service {self.serviceInfo['ID']} in catalog, retrying...")
            return
        if request.status_code != 200:
            print(f"THINGSPEAK: failed to update service {self.serviceInfo['ID']} in catalog, registering again")
            self.registerService()  # If update fails, try to register the service again

# thingspeak adaptor is subscribed to all topics of the sensors, and sorts the messages to the right field and the right patient
    def notify(self,topic,payload): 
        #{'bn':f'SensorREST_MQTT_{self.deviceID}','e':[{'n':'','v':'', 't':'','u':''}]}
        message = json.loads(payload)
        print(f"THINGSPEAK: received message on topic {topic}: {message}")
        field_name = message["e"][0]["n"]
        deviceID = message["bn"]
        if field_name not in self.thingspeak_fields:
            print(f"THINGSPEAK: field '{field_name}' not in thingspeak_fields")
            return  
        else:
            field_number = self.thingspeak_fields.index(field_name) + 1
            print(f"\n{field_name} message")
            print(f'request: {self.catalogURL}/devices/{deviceID}')
            try:
                response = requests.get(f'{self.catalogURL}/devices/{deviceID}')
            except requests.exceptions.RequestException as e:
                print(f"THINGSPEAK: Error retrieving sensor information from catalog: {e}")
                return
            if response.status_code != 200:
                    print(f"THINGSPEAK: Catalog returned status {response.status_code}: {response.text}")
                    return
            print(response.json())
            sensor = response.json()
            print('uploading...')
            self.uploadThingspeak(patientID=sensor['device']['patientID'], field_number=field_number, field_value=message["e"][0]['v'])
        
# function to upload data to Thingspeak
    def uploadThingspeak(self,patientID,field_number,field_value):
        # THINGSPEAK HAS A TIME LIMIT FOR SAVING DATA; EVERY 15 SECONDS IT SEEMS; NEED TO LIMIT SENSORS

        #GET https://api.thingspeak.com/update?api_key=N7GEPLVRH3PP72BP&field1=0
        #baseURL -> https://api.thingspeak.com/update?api_key=
        #Channel API KEY -> N7GEPLVRH3PP72BP Particular value for each Thingspeak channel
        #fieldnumber -> depends on the field (type of measurement) we want to upload the information to
        urlToSend = f'{self.catalogURL}/patients/{patientID}'
        try:
            response = requests.get(urlToSend)
        except requests.exceptions.RequestException as e:
            print(f"THINGSPEAK: Error retrieving patient information from catalog: {e}")
            return
        if response.status_code == 404:
            print(f"THINGSPEAK: Patient with ID {patientID} not found in catalog")
            return
        if response.status_code != 200:
            print(f"THINGSPEAK: Catalog returned status {response.status_code}: {response.text}")
            return
        if 'patient' not in response.json():
            print(f"THINGSPEAK: No patient field found with ID in catalog response")
            return
        patient = response.json()['patient']
        if 'thingspeak_info' not in patient:
            print(f"THINGSPEAK: Patient with ID {patientID} is missing thingspeak_info")
            return False
        if 'channelID' not in patient['thingspeak_info'] or 'write_api_key' not in patient['thingspeak_info']:
            print(f"THINGSPEAK: Patient with ID {patientID} is missing channelID or write_api_key")
            return False
        channelID = patient['thingspeak_info']['channelID']
        channelWriteAPIkey = patient['thingspeak_info']['write_api_key']
        if not channelID or not channelWriteAPIkey:
            print(f"THINGSPEAK: Channel ID or Write API Key are empty for patientID {patientID}")
            return
        urlToSend=f'{self.ThingspeakURL}/update?api_key={channelWriteAPIkey}&field{field_number}={field_value}'
        try:
            r=requests.get(urlToSend)
        except requests.exceptions.RequestException as e:
            print(f"THINGSPEAK: Error uploading data to Thingspeak: {e}")
            return
        if r.status_code == 200:
            print(f"Data uploaded successfully")

# Create a new Thingspeak channel for the patientID
    def create_thingspeak_channel(self, patientID):
        data = {
            "api_key": self.userAPIKey,  
            "name": patientID,        # Use patientID as the channel name
        }
        urlToSend = f"{self.ThingspeakURL}/channels.json"
        headers = {"Content-Type": "application/json"}
        for i, field_name in enumerate(self.thingspeak_fields, start=1):
            data[f"field{i}"] = field_name
        try:
            data_json = json.dumps(data)
        except TypeError as e:
            print(f"JSON encoding error: {e}")
            return None
        print(self.userAPIKey)
        try:
            response = requests.post(urlToSend, headers=headers, data=data_json)
        except requests.exceptions.RequestException as e:
            print(f"THINGSPEAK: Exception while creating channel: {e}")
            return None
        if response.status_code == 200 or response.status_code == 201: # request was successful
            resp_json = response.json()
            channel_id = resp_json.get("id")
            write_api_key = None
            read_api_key = None
            # Find the write and read API keys
            for key in resp_json.get("api_keys", []):
                if key.get("write_flag", False):
                    write_api_key = key.get("api_key")
                else:
                    read_api_key = key.get("api_key")
            print(f"THINGSPEAK: Channel created: id={channel_id}, write_api_key={write_api_key}, read_api_key={read_api_key}")
            return {
                "channelID": channel_id,
                "write_api_key": write_api_key,
                "read_api_key": read_api_key
            }
        else:
            print("THINGSPEAK: Failed to create channel:", response.text)
            return None

# Delete a Thingspeak channel for the given patientID
    def delete_thingspeak_channel(self, patientID):
        # First, find the channel ID for the given patientID
        # This assumes you have a way to map patientID to channelID, e.g., in self.patients or via catalog
        # For this example, let's assume you have a method to get the channelID by patientID
        urlToSend = f"{self.catalogURL}/patients/{patientID}"
        try:
            response = requests.get(urlToSend)
        except Exception as e:
            print(f"THINGSPEAK: Exception while retrieving patient information: {e}")
            return False
        if response.status_code == 404:
            print(f"THINGSPEAK: Patient with ID {patientID} not found in catalog")
            return False
        if response.status_code != 200:
            print(f"THINGSPEAK: Catalog returned status {response.status_code}: {response.text}")
            return False
        try:
            patient = response.json()['patient']
        except json.JSONDecodeError as e:
            print(f"THINGSPEAK: Error decoding JSON response: {e}")
            return False
        if 'thingspeak_info' not in patient:
            print(f"THINGSPEAK: Patient with ID {patientID} is missing thingspeak_info")
            return False
        if 'channelID' not in patient['thingspeak_info'] or 'write_api_key' not in patient['thingspeak_info']:
            print(f"THINGSPEAK: Patient with ID {patientID} is missing channelID or write_api_key")
            return False
        if not patient['thingspeak_info']['channelID'] or not patient['thingspeak_info']['write_api_key']:
            print(f"THINGSPEAK: Channel ID or Write API Key are empty for patientID {patientID}")
            return False
        channelID = patient['thingspeak_info']['channelID']
        urlToSend = f"{self.ThingspeakURL}/channels/{channelID}.json"
        headers = {"Content-Type": "application/json"}
        data = { 
            "api_key": self.userAPIKey
        }
        try:
            response = requests.delete(urlToSend, headers=headers, data=json.dumps(data))
        except Exception as e:
            print(f"THINGSPEAK: Exception while deleting channel: {e}")
            return False
        if response.status_code == 200 or response.status_code == 202 or response.status_code == 204:
            print(f"THINGSPEAK: Channel {patient['thingspeak_info']['channelID']} for patientID {patientID} deleted successfully.")
            # remove information from catalog patient
            urlToSend = f"{self.catalogURL}/patients"
            patient['thingspeak_info'] = {}  # Clear thingspeak_info from patient data
            try:
                response = requests.put(urlToSend, json=patient)
            except Exception as e:
                print(f"THINGSPEAK: Exception while updating catalog patient: {e}")
                return False
            if response.status_code != 200:
                print(f"THINGSPEAK: Failed to update catalog patient {patientID} after deleting channel: {response.text}")
                return False    
            print(f"THINGSPEAK: Catalog patient {patientID} updated successfully.")
            return True
            # if the patient needs to be removed, will be done by the catalog

# get method used to retrieve past data from Thingspeak
    def GET(self, *uri, **params):
        field=None
        N=None
        if uri and uri[0]:
            patientID = uri[0]
        else:
            raise cherrypy.HTTPError(status=400, message='THINGSPEAK ADAPTOR: patientID is required')
        # if field specified in params, return only data from that field
        if params and 'field' in params:
            if params['field'] not in self.thingspeak_fields:
                raise cherrypy.HTTPError(status=400, message=f'THINGSPEAK ADAPTOR: field {field} not in thingspeak_fields')
            for i, field in enumerate(self.thingspeak_fields):
                if params['field'] == field:
                    field = f'field{i+1}'
                    break
        # if samples_number specified in params, return only that number of samples, otherwise return maximum (8000)
        if params and 'samples_number' in params:
            N = params['samples_number']
            if not N.isdigit() or int(N) <= 0:
                raise cherrypy.HTTPError(status=400, message=f'THINGSPEAK ADAPTOR: Invalid samples_number {N}')

        UrlToSend = f'{self.catalogURL}/patients/{patientID}'
        try:
            response = requests.get(UrlToSend)
        except requests.exceptions.RequestException as e:
            raise cherrypy.HTTPError(status=500, message=f'THINGSPEAK ADAPTOR: Error retrieving patient information from catalog: {e}')
        if response.status_code != 200:
            raise cherrypy.HTTPError(status=response.status_code, message=f'THINGSPEAK ADAPTOR: Failed to get patient {patientID} from catalog') # will be 404
        patient = response.json()["patient"]
        if not patient:
            raise cherrypy.HTTPError(status=404, message=f'THINGSPEAK ADAPTOR: Patient with ID {patientID} not found')
        channelID = patient['thingspeak_info']['channelID']
        channelReadAPIkey = patient['thingspeak_info']['read_api_key']
        urlToSend = f'{self.ThingspeakURL}/channels/{channelID}/feeds.json?api_key={channelReadAPIkey}&results=8000'
        try:
            request = requests.get(urlToSend)
        except requests.exceptions.RequestException as er:
            raise cherrypy.HTTPError(status=500, message=f'THINGSPEAK ADAPTOR: Error retrieving data from Thingspeak: {e}')
        if request.status_code != 200:
            raise cherrypy.HTTPError(status=request.status_code, message=f'THINGSPEAK ADAPTOR: Failed to get data for patientID {patientID} from Thingspeak: {request.text}')
        feeds = request.json().get('feeds', [])
        print
        output_feeds = []
        if field:
            for feed in feeds:
                if feed[field] is not None:
                    output_feeds.append({'field': feed[field], "created_at": feed["created_at"]})
        else:
            output_feeds = feeds
        if N:
            if len(output_feeds) > int(N):
                output_feeds = output_feeds[-int(N):]
        output ={'feeds': output_feeds}
        # print(output)
        return json.dumps(output)

# POST request http://localhost:8081/channels
# needs a JSON body with patientID to create a new channel
    def POST(self, *uri, **params):
        # POST request to create a new channel
        if len(uri)==0:
            raise cherrypy.HTTPError(status=400, message='THINGSPEAK: POST with empty URI')
        elif uri[0] == 'channels':
            json_body = cherrypy.request.body.read()
            if not json_body:
                raise cherrypy.HTTPError(status=400, message='THINGSPEAK: Empty request body')
            try:
                body = json.loads(json_body.decode('utf-8'))
            except Exception as e:
                raise cherrypy.HTTPError(status=400, message=f'THINGSPEAK: Invalid JSON: {e}')
            if not body or "patientID" not in body:
                raise cherrypy.HTTPError(status=400, message='THINGSPEAK: Missing patientID in request body')
            channel = self.create_thingspeak_channel(body["patientID"])
            if channel:
                return json.dumps(channel)
            else:
                raise cherrypy.HTTPError(status=500, message='THINGSPEAK: Failed to create channel')
        else:
            raise cherrypy.HTTPError(status=400, message='THINGSPEAK: POST URI not managed')

# no actual need for PUT in this context, but defining it for completeness
# could be added, but we assume that a patient is in care until they are removed
    def PUT(self, *uri, **params):
        pass

# DELETE request http://localhost:8081/channels/{patientID}
# needs parameter patientID to identify the channel to delete
    def DELETE(self, *uri, **params):
        if len(uri) == 0:
            raise cherrypy.HTTPError(status=400, message='THINGSPEAK: DELETE with empty URI')
        elif uri[0] == 'channels':
            if uri[1] == '':
                raise cherrypy.HTTPError(status=400, message='THINGSPEAK: Missing patientID in URI')
            patientID = uri[1]
            if self.delete_thingspeak_channel(patientID):
                output = f"THINGSPEAK: Channel for patientID {patientID} deleted successfully."
                return output
            else:
                raise cherrypy.HTTPError(status=500, message='THINGSPEAK: Failed to delete channel')
        else:
            raise cherrypy.HTTPError(status=400, message='THINGSPEAK: DELETE URI not managed')


def start_api(ts_adaptor, api_port):
    conf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_host': '0.0.0.0', 'server.socket_port': 80, 'engine.autoreload.on': False})
    # cherrypy.config.update({'server.socket_port': api_port})
    cherrypy.tree.mount(ts_adaptor, '/', conf)
    cherrypy.engine.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ts_adaptor.stop()
        cherrypy.engine.exit()
        print("Thingspeak Adaptor stopped.")


# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Thingspeak Adaptor...")
    if ts_adaptor is not None:
        ts_adaptor.stop()
    print("Thingspeak Adaptor stopped.")
    exit(0)

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == "__main__":
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"THINGSPEAK ADAPTOR: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"THINGSPEAK ADAPTOR: Json settings file not found")
        exit(1)
    ts_adaptor = None
    try:
        ts_adaptor = Thingspeak_Adaptor(settings)
        start_api(ts_adaptor, settings['apiPort'])
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down Thingspeak Adaptor...")
        if ts_adaptor is not None:
            ts_adaptor.stop()
        print("Thingspeak Adaptor stopped.")
        exit(0)

