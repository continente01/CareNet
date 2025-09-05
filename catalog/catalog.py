# CATALOG
# all IDs in the catalog are integers, out of the chat IDs. 
# Those are assigned by Telegram and are considered as strings

import cherrypy
import json
import time
import requests
import threading


# Function to get the catalog from a JSON file, with a backup option in case the file is corrupted or not found
def getCatalog(json_name, backup={}):
    try:
        with open(json_name, "r") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        if backup != {}:
            print(f"Catalog: File {json_name} not found, restoring from backup")
            catalog = backup
        else:
            print(f"Catalog: File {json_name} not found, creating a new one")
            catalog = {"devices": [], "services": [], "patients": [], "medications": [], "chats": []}
        with open(json_name, "w") as f:
            json.dump(catalog, f, indent=4)
    except json.JSONDecodeError:
        if backup != {}:
            print(f"Catalog: Json file corrupted, restoring from backup")
            catalog = backup
        else:
            print(f"Catalog: Json file corrupted, creating a new one")
            catalog = {"devices": [], "services": [], "patients": [], "medications": [], "chats": []}
        with open(json_name, "w") as f:
            json.dump(catalog, f, indent=4)
    # Ensure all keys are present in the catalog
    for key in ["devices", "services", "patients", "medications", "chats"]:
        if key not in catalog:
            if backup != {} and key in backup:
                print(f"Catalog: Key {key} not found, restoring from backup")
                catalog[key] = backup[key]
            else:
                print(f"Catalog: Key {key} not found, creating a new one")
                catalog[key] = []
    return catalog

# device management functions

def addDevice(catalog, device):
    device['last_update']=time.time()
    for patient in catalog["patients"]:
        if int(patient['ID']) == int(device['patientID']):
            if 'devices' not in patient:
                patient['devices'] = []
            for d in patient['devices']:
                if int(d['deviceID']) == int(device['ID']):
                    raise cherrypy.HTTPError(status=400, message=f"Catalog: Device with ID {device['ID']} already exists for patient with ID {device['patientID']}")
            patient['devices'].append({'deviceID': device['ID']})
            catalog["devices"].append(device)
            output = f"Device with ID {device['ID']} has been added to patient with ID {device['patientID']}"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Patient with ID {device['patientID']} not found for device with ID {device['ID']}")

def updateDevice(catalog, device):
    device['last_update'] = time.time()
    if 'devicetype' not in device or 'ID' not in device:
        raise cherrypy.HTTPError(status=400, message='Catalog: missing deviceType or ID in device update')
    for i, d in enumerate(catalog["devices"]):
        # Check if the device ID and device type match
        # This is to ensure that even if there are errors with the device IDs, 
        # only the correct device can update their information
        if d['ID'] == device['ID'] and d['deviceType'] == device['deviceType']:
            catalog["devices"][i] = device
    output = f"Device with ID {device['ID']} has been updated"
    return output

def removeDevice(catalog, deviceID):
    try:
        deviceID = int(deviceID)
    except ValueError:
        raise cherrypy.HTTPError(status=400, message='Catalog: Device ID must be an integer')
    for idx, device in enumerate(catalog["devices"]):
        if int(device['ID']) == int(deviceID):
            # Remove the device from the patient's devices list
            for patient in catalog["patients"]:
                if int(patient['ID']) == int(device['patientID']):
                    if 'devices' in patient:
                        for d in patient['devices']:
                            if int(d['deviceID']) == int(device['ID']):
                                patient['devices'].remove(d)
                                break
            # Remove the device from the catalog
            catalog["devices"].pop(idx)
            output = f"Device with ID {deviceID} has been removed"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Device with ID {deviceID} not found")

# service management functions

def addService(catalog, service):
    service['last_update']=time.time()
    catalog["services"].append(service)
    output = f"Service with ID {service['ID']} has been added"
    # print(output)
    return output

def updateService(catalog, service):
    service['last_update'] = time.time()
    if 'serviceName' not in service:
        raise cherrypy.HTTPError(status=400, message='Catalog: missing serviceName in service update')
    for i, s in enumerate(catalog["services"]):
        # Check if the service ID and service name match
        # This is to ensure that even if there are errors with the service IDs,
        # only the correct service can update their information
        if s['ID'] == service['ID'] and s['serviceName'] == service['serviceName']:
            catalog["services"][i] = service
    output = f"Service with ID {service['ID']} has been updated"
    return output

def removeService(catalog, serviceID):
    try:
        serviceID = int(serviceID)
    except ValueError:
        raise cherrypy.HTTPError(status=400, message='Catalog: Service ID must be an integer')
    for idx, service in enumerate(catalog["services"]):
        if int(service['ID']) == int(serviceID):
            catalog["services"].pop(idx)
            output = f"Service with ID {serviceID} has been removed"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Service with ID {serviceID} not found")

# patient management functions

# need to remember to add first the patient and then add the sensors or the medications
# assigned to the patient, otherwise they will not be added
def addPatient(catalog, patient, thingspeak_url):
    patient["last_update"] = time.time()
    channel_data = requests.post(f'{thingspeak_url}/channels', json={"patientID": patient['ID']}, headers={"Content-Type": "application/json"})# , headers={"Content-Type": "application/json"} vedere se si può togliere
    if channel_data.status_code == 200:
        patient['thingspeak_info'] = channel_data.json()
        patient['devices'] = []  # Initialize devices list for the patient
        patient['medications'] = []  # Initialize medications list for the patient
        catalog["patients"].append(patient)
        output = f"Patient with ID {patient['ID']} has been added"
    else:
        raise cherrypy.HTTPError(status=400, message=f"Error creating channel for patient with ID {patient['ID']}: {channel_data.text}")
    # print(output)
    return output

def updatePatient(catalog, patient):
    patient['last_update'] = time.time()
    for i, p in enumerate(catalog["patients"]):
        if p['ID'] == patient['ID']:
            catalog["patients"][i] = patient
    output = f"Patient with ID {patient['ID']} has been updated"
    return output

def removePatient(catalog, patientID, thingspeak_adaptor_url):
    try:
        patientID = int(patientID)
    except ValueError:
        raise cherrypy.HTTPError(status=400, message='Catalog: Patient ID must be an integer')
    try:
        response = requests.delete(f'{thingspeak_adaptor_url}/channels/{patientID}')
    except Exception as e:
        raise cherrypy.HTTPError(status=400, message=f"Error requesting Thingspeak deletion for patient {patientID}: {e}")
    if response.status_code != 200:
        raise cherrypy.HTTPError(status=400, message=f"Error deleting Thingspeak channel for patient {patientID}: {response.text}")
    for idx, patient in enumerate(catalog["patients"]):
        if int(patient['ID']) == int(patientID):
            # Remove all devices and medications assigned to this patient
            catalog["devices"] = [d for d in catalog["devices"] if int(d['patientID']) != int(patientID)] # not needed since we have catalog manager, but no problem if implemented
            catalog["medications"] = [m for m in catalog["medications"] if int(m['patientID']) != int(patientID)] # not needed since we have catalog manager, but no problem if implemented
            catalog["patients"].pop(idx)
            output = f"Patient with ID {patientID} has been removed with all associated devices and medications"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Patient with ID {patientID} not found")


# medication management functions

def addMedication(catalog, medication):
    for patient in catalog["patients"]:
        if int(patient['ID']) == int(medication['patientID']):
            medication['last_update'] = time.time()
            if 'medications' not in patient:
                patient['medications'] = []
            for m in patient['medications']:
                if int(m['medicationID']) == int(medication['ID']):
                    raise cherrypy.HTTPError(status=400, message=f"Catalog: Medication with ID {medication['ID']} already exists for patient with ID {medication['patientID']}")
            patient['medications'].append({'medicationID': medication['ID']})
            catalog["medications"].append(medication)
            output = f"Medication with ID {medication['ID']} has been added"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Patient with ID {medication['patientID']} not found for medication with ID {medication['ID']}")

def updateMedication(catalog, medication):  
    medication['last_update'] = time.time()
    for i, m in enumerate(catalog["medications"]):
        if m['ID'] == medication['ID']:
            catalog["medications"][i] = medication
    output = f"Medication with ID {medication['ID']} has been updated"
    return output

def removeMedication(catalog, medicationID):
    for i, m in enumerate(catalog["medications"]):
        if int(m['ID']) == int(medicationID):
            for patient in catalog["patients"]:
                if int(patient['ID']) == int(m['patientID']):
                    if 'medications' in patient:
                        for med in patient['medications']:
                            if int(med['medicationID']) == int(medicationID):
                                patient['medications'].remove(med)
                                break
            catalog["medications"].pop(i)
            output = f"Medication with ID {medicationID} has been removed"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Medication with ID {medicationID} not found")

# telegram chat management functions

def addChat(catalog, chat):
    chat['last_update'] = time.time()
    catalog["chats"].append(chat)
    output = f"Chat with ID {chat['ID']} has been added"
    # print(output)
    return output

def updateChat(catalog, chat):
    chat['last_update'] = time.time()
    for i, c in enumerate(catalog["chats"]):
        if str(c['ID']) == str(chat['ID']):
            catalog["chats"][i] = chat
    output = f"Chat with ID {chat['ID']} has been updated"
    return output

def removeChat(catalog, chatID):
    for i, chat in enumerate(catalog["chats"]):
        if str(chat['ID']) == str(chatID):
            catalog["chats"].pop(i)
            output = f"Chat with ID {chatID} has been removed"
            # print(output)
            return output
    raise cherrypy.HTTPError(status=404, message=f"Chat with ID {chatID} not found")

class Catalog(object):
    exposed = True

    def __init__(self,settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if "CatalogFileName" not in settings or "ThingspeakAdaptorURL" not in settings or "apiPort" not in settings:
            raise ValueError("Settings must contain 'CatalogFileName', 'ThingspeakAdaptorURL', and 'apiPort'")
        self.json_name=settings["CatalogFileName"]
        self.thingspeak_adaptor_url=settings["ThingspeakAdaptorURL"] 
        self.api_port=settings["apiPort"]
        self.backup = {}
        getCatalog(self.json_name)
        self.start()

    def start(self):
        backup_thread = threading.Thread(target=self.backupCatalog, daemon=True)
        backup_thread.start()

# function to create a backup copy of the catalog, called by second thread
    def backupCatalog(self):
        while True:
            time.sleep(60)
            try:
                self.backup = getCatalog(self.json_name, self.backup)
            except Exception as e:
                print(f"Catalog: Error during backup: {e}")
                

    def GET(self, *uri, **params):
        catalog=getCatalog(self.json_name, self.backup)
        if len(uri)==0:
            raise cherrypy.HTTPError(status=400, message='Catalog: GET with empty URI')
        elif uri[0]=='all':
            return json.dumps(catalog)
        elif uri[0]=='devices':
            if len(uri) > 1:
                try:
                    deviceID = int(uri[1])
                except ValueError:
                    raise cherrypy.HTTPError(status=400, message='Catalog: invalid deviceID')
                # print(f"Catalog: GET deviceID: {deviceID}")
                for device in catalog["devices"]:
                    if int(device['ID']) == int(deviceID):
                        return json.dumps({"device": device})
                raise cherrypy.HTTPError(status=404, message='Catalog: Device not found')
            return json.dumps({"devices":catalog["devices"]})
        elif uri[0]=='services':
            if len(uri) > 1:
                try:
                    serviceID = int(uri[1])
                except ValueError:
                    raise cherrypy.HTTPError(status=400, message='Catalog: invalid serviceID')
                # print(f"Catalog: GET serviceID: {serviceID}")
                for service in catalog["services"]:
                    if int(service['ID']) == int(serviceID):
                        return json.dumps({"service": service})
                raise cherrypy.HTTPError(status=404, message='Catalog: Service not found')
            return json.dumps({"services":catalog["services"]})
        elif uri[0]=='patients':
            if len(uri) > 1:
                try:
                    patientID = int(uri[1])
                except ValueError:
                    raise cherrypy.HTTPError(status=400, message='Catalog: invalid patientID')
                for patient in catalog["patients"]:
                    if int(patient['ID']) == int(patientID):
                        return json.dumps({"patient": patient})
                raise cherrypy.HTTPError(status=404, message='Catalog: Patient not found')
            return json.dumps({"patients":catalog["patients"]})
        elif uri[0]=='medications':
            if len(uri) > 1:
                try:
                    medicationID = int(uri[1])
                except ValueError:
                    raise cherrypy.HTTPError(status=400, message='Catalog: invalid medicationID')
                for medication in catalog["medications"]:
                    if int(medication['ID']) == int(medicationID):
                        return json.dumps({"medication": medication})
                raise cherrypy.HTTPError(status=404, message='Catalog: Medication not found')
            return json.dumps({"medications":catalog["medications"]})
        elif uri[0]=='chats':
            if len(uri) > 1:
                for chat in catalog["chats"]:
                    if str(chat['ID']) == str(uri[1]):
                        return json.dumps({"chat": chat})
                raise cherrypy.HTTPError(status=404, message='Catalog: Chat not found')
            return json.dumps({"chats":catalog["chats"]})
        else:
            raise cherrypy.HTTPError(status=400, message='Catalog: GET URI not managed')
        
    def POST(self,*uri,**params):
        catalog=getCatalog(self.json_name,self.backup)
        json_body = cherrypy.request.body.read()
        body = json.loads(json_body.decode('utf-8'))
        if 'ID' not in body:
            raise cherrypy.HTTPError(status=400, message='Catalog: missing ID in POST body')
        try:
            body['ID'] = int(body['ID'])
        except ValueError:
            raise cherrypy.HTTPError(status=400, message='Catalog: wrong ID in POST body, it must be an integer')
        if len(uri)==0:
            raise cherrypy.HTTPError(status=400, message='Catalog: POST with empty URI')
        elif uri[0]=='devices':
            if 'patientID' not in body:
                raise cherrypy.HTTPError(status=400, message='Catalog: missing patientID in POST body')
            if not any(int(d['ID']) == int(body['ID']) for d in catalog["devices"]):
                if not any(int(p['ID']) == int(body['patientID']) for p in catalog["patients"]):
                    raise cherrypy.HTTPError(status=404, message=f'Catalog: Patient not found for device')
                else:    
                    output=addDevice(catalog, body)
            else:
                raise cherrypy.HTTPError(status=400, message=f'Catalog: Device with ID {body["ID"]} already in catalog')
        elif uri[0]=='services':
            if not any(int(s['ID']) == int(body['ID']) for s in catalog["services"]):
                output=addService(catalog, body)
            else:
                raise cherrypy.HTTPError(status=400, message=f'Catalog: Service with ID {body["ID"]} already in catalog')
        elif uri[0]=='patients':
            print(f"Catalog: POST body: {body}",flush=True)
            if 'ID' not in body:
                raise cherrypy.HTTPError(status=400, message='Catalog: missing ID for patient')
            if not any(int(p['ID']) == int(body['ID']) for p in catalog["patients"]):
                output=addPatient(catalog, body,self.thingspeak_adaptor_url)
            else:
                raise cherrypy.HTTPError(status=400, message=f'Catalog: Patient with ID {body["ID"]} already in catalog')
        elif uri[0]=='medications':
            if 'patientID' not in body:
                raise cherrypy.HTTPError(status=400, message='Catalog: missing patientID in POST body')
            if 'ID' not in body:
                raise cherrypy.HTTPError(status=400, message='Catalog: missing ID for medication')
            if not any(int(m['ID']) == int(body['ID']) for m in catalog["medications"]):
                output=addMedication(catalog, body)
            else:
                raise cherrypy.HTTPError(status=400, message=f'Catalog: Medication with ID {body["ID"]} already in catalog')
        elif uri[0]=='chats':
            # print(f"Catalog: POST body: {body}",flush=True)
            if 'ID' not in body:
                raise cherrypy.HTTPError(status=400, message='Catalog: missing ID for chat')
            if not any(str(c['ID']) == str(body['ID']) for c in catalog["chats"]):
                output=addChat(catalog, body)
            else:
                raise cherrypy.HTTPError(status=401, message=f'Catalog: Chat with ID {body["ID"]} already in catalog')
        else:
            raise cherrypy.HTTPError(status=400, message='Catalog: POST URI not managed')
        try:
            json.dump(catalog,open(self.json_name,"w"),indent=4)
        except Exception as e:
            print(f"Catalog: Error saving catalog: {e}")
        print(output)
        return output
    
    def PUT(self,*uri,**params):
        catalog=getCatalog(self.json_name, self.backup)
        json_body = cherrypy.request.body.read()
        body = json.loads(json_body.decode('utf-8'))
        if len(uri)==0:
            raise cherrypy.HTTPError(status=400, message='Catalog: PUT with empty URI')
        if 'ID' not in body:
            raise cherrypy.HTTPError(status=400, message='Catalog: missing ID in PUT body')
        elif uri[0]=='devices':
            if not any(int(d['ID']) == int(body['ID']) for d in catalog["devices"]):
                raise cherrypy.HTTPError(status=400, message='Catalog: Device not found')
            else:
                output=updateDevice(catalog, body)
        elif uri[0]=='services':
            if not any(int(d['ID']) == int(body['ID']) for d in catalog["services"]):
                raise cherrypy.HTTPError(status=400, message='Catalog: Service not found')
            else:
                output=updateService(catalog, body)
        elif uri[0]=='patients':
            if not any(int(d['ID']) == int(body['ID']) for d in catalog["patients"]):
                raise cherrypy.HTTPError(status=400, message='Catalog: Patient not found')
            else:
                output=updatePatient(catalog, body)
        elif uri[0]=='medications':
            if not any(int(m['ID']) == int(body['ID']) for m in catalog["medications"]):
                raise cherrypy.HTTPError(status=400, message='Catalog: Medication not found')
            else:
                output=updateMedication(catalog, body)
        elif uri[0]=='chats':
            if not any(str(c['ID']) == str(body['ID']) for c in catalog["chats"]):
                raise cherrypy.HTTPError(status=400, message='Catalog: Chat not found')
            else:
                output=updateChat(catalog, body)
        else:
            raise cherrypy.HTTPError(status=400, message='Catalog: PUT URI not managed')
        try:
            json.dump(catalog,open(self.json_name,"w"),indent=4)
        except Exception as e:
            print(f"Catalog: Error saving catalog: {e}")
        return output
    

    def DELETE(self,*uri,**params):
        catalog=getCatalog(self.json_name, self.backup)
        if len(uri)==0:
            raise cherrypy.HTTPError(status=400, message='Catalog: DELETE with empty URI')
        if len(uri) < 2:
            raise cherrypy.HTTPError(status=400, message='Catalog: no ID provided for deletion')
        elif uri[0]=='devices':
            output=removeDevice(catalog,uri[1])
        elif uri[0]=='services':
            output=removeService(catalog,uri[1])
        elif uri[0]=='patients':
            output=removePatient(catalog, int(uri[1]), self.thingspeak_adaptor_url)
        elif uri[0]=='medications':
            output=removeMedication(catalog, int(uri[1]))
        elif uri[0]=='chats':
            output=removeChat(catalog, uri[1])
        else:
            raise cherrypy.HTTPError(status=400, message='Catalog: DELETE URI not managed')
        try:
            json.dump(catalog,open(self.json_name,"w"),indent=4)
        except Exception as e:
            print(f"Catalog: Error saving catalog: {e}")
        return output

    def stop(self):
        print("Stopping Catalog")
        self.update_thread.join()

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Catalog...")
    if catalog is not None:
        catalog.stop()
    cherrypy.engine.exit()
    print("Catalog REST server stopped.")
    exit(0)

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    # if previous devices are present and theyare not used anymore, 
    # they will be removed by the device manager
    try:
        with open('settings.json') as f:
            settings = json.load(f)
    except json.JSONDecodeError as e:
        print(f"CATALOG: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"CATALOG: Json settings file not found")
        exit(1)
    catalog = Catalog(settings)
    conf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_host': '0.0.0.0', 'server.socket_port': 80, 'engine.autoreload.on': False})
    # cherrypy.config.update({'server.socket_port': int(settings["apiPort"])})
    cherrypy.tree.mount(catalog, '/', conf)
    try:
        cherrypy.engine.start()
        cherrypy.engine.block()
    except (KeyboardInterrupt, SystemExit):
        catalog.stop()
        cherrypy.engine.exit()
        print("Catalog REST server stopped.")

