# CATALOG MANAGER
# deletes inactive devices, services and checks if any device or medication has been left while the
# their patient has been removed
# People are not checked, as they are only removed by the telegram bot command
# and not by the catalog manager.
import requests
import json
import time
import threading

class CatalogManager(object):
    def __init__(self, settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if 'catalogURL' not in settings or 'threshold' not in settings or 'controlInterval' not in settings or 'serviceInfo' not in settings:
            raise ValueError("Settings must contain 'catalogURL', 'threshold', 'controlInterval', 'serviceInfo', and 'pingInterval'")
        self.catalogURL = settings['catalogURL']
        self.threshold = settings['threshold']
        self.controlInterval = settings['controlInterval']
        self.serviceInfo = settings['serviceInfo']
        if 'serviceName' not in settings['serviceInfo']:
            self.serviceInfo['serviceName'] = 'Catalog Manager'
        if 'pingInterval' not in settings:
            self.pingInterval = 10
        else:
            self.pingInterval = settings['pingInterval']
        self.serviceID = None
        self.serviceInfo['ID'] = self.assign_serviceID()
        self.serviceID = self.serviceInfo['ID']
        
        self.start()

    def start(self):
        print('Starting Catalog Manager')
        self.registerService()
        self.update_thread = threading.Thread(target=self.update_loop,daemon=True)
        self.update_thread.start()
        while True:
            self.removeInactive()
            time.sleep(self.controlInterval)

    def stop(self):
        print('Stopping Catalog Manager')
        self.update_thread.join()

# This function runs in a separate thread to update the service information in the catalog   
    def update_loop(self):
        while True:
            self.updateService()
            time.sleep(self.pingInterval)

# register service catalog manager to the catalog
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

# update service catalog manager service in the catalog
    def updateService(self):
        try:
            request=requests.put(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
        except requests.exceptions.RequestException:
            print(f"CATALOG MANAGER: failed request for updating service {self.serviceInfo['ID']} in catalog")
            return
        if request.status_code != 200:
            print(f"CATALOG MANAGER: failed to update service {self.serviceInfo['ID']} in catalog, registering again")
            self.registerService()

# get the list of devices from the catalog
    def getDevices(self):
        while True:
            try:
                response = requests.get(f'{self.catalogURL}/devices')
            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException:
                print("CATALOG MANAGER: failed request for devices from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"CATALOG MANAGER: failed to get devices from catalog, status code {response.status_code}")
                continue
            print('List of available devices obtained')
            return response.json()['devices']

# get the list of services from the catalog
    def getServices(self):
        while True:
            try:
                response = requests.get(f'{self.catalogURL}/services')
            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException:
                print("CATALOG MANAGER: failed request for services from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"CATALOG MANAGER: failed to get services from catalog, status code {response.status_code}")
                continue
            print('List of available services obtained')
            return response.json()['services']

# get the list of medications from the catalog
    def getMedications(self):
        while True:
            try:
                response = requests.get(f'{self.catalogURL}/medications')
            except requests.exceptions.RequestException:
                print("CATALOG MANAGER: failed request for medications from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"CATALOG MANAGER: failed to get medications from catalog, status code {response.status_code}, retrying...")
                continue
            print('List of available medications obtained')
            return response.json()['medications']
    
# get the list of patients from the catalog
    def getPatients(self):
        while True:
            try:
                request=requests.get(f'{self.catalogURL}/patients')
            except requests.exceptions.RequestException:
                print("CATALOG MANAGER: failed request for patients from catalog, retrying...")
                time.sleep(5)
                continue
            if request.status_code != 200:
                print(f"CATALOG MANAGER: failed to get patients from catalog, status code {request.status_code}, retrying...")
                time.sleep(5)
                continue
            print('List of available patients obtained')
            return request.json()['patients']

# remove inactive devices, services and medications from the catalog
    def removeInactive(self):
        check= True
        devices=self.getDevices()
        if not devices:
            print('No devices to check')
        else:
            patients = self.getPatients()
            # if there are no patients, remove all devices
            if not patients:
                print('No patients, remove all devices')
                for device in devices:
                    try:
                        request=requests.delete(f'{self.catalogURL}/devices/{device["ID"]}')
                    except requests.exceptions.RequestException:
                        print(f"CATALOG MANAGER: failed request for removing device {device['ID']} from catalog")
                    if request.status_code == 200:
                        print(f'Device {device["ID"]} has been removed')
                    else:
                        # print(request.text)
                        print(f"CATALOG MANAGER: failed to remove device {device['ID']} from catalog")
            # if there are patients, check if the devices are still associated with them and are updated
            else:
                for device in devices:
                    # check if the device's patient is still in the catalog
                    if int(device['patientID']) not in [int(patient['ID']) for patient in patients]:
                        try:
                            request=requests.delete(f'{self.catalogURL}/devices/{device["ID"]}')
                        except requests.exceptions.RequestException:
                            print(f"CATALOG MANAGER: failed request for removing device {device['ID']} from catalog")
                        if request.status_code == 200:
                            print(f'Device {device["ID"]} has been removed since its patient has been removed')
                        else:
                            print(request.text)
                            print(f"CATALOG MANAGER: failed to remove device {device['ID']} from catalog")
                        check = False
                    # check if the device has not been updated for a long time
                    if time.time()-device['last_update'] > self.threshold:
                        try:
                            request=requests.delete(f'{self.catalogURL}/devices/{device["ID"]}')
                        except requests.exceptions.RequestException:
                            print(f"CATALOG MANAGER: failed request for removing device {device['ID']} from catalog")
                        if request.status_code == 200:
                            print(f'Device {device["ID"]} has been removed')
                        else:
                            print(request.text)
                            print(f"CATALOG MANAGER: failed to remove device {device['ID']} from catalog")
                        check = False
                if check:
                    print('No devices to remove')

        check = True
        services = self.getServices()
        if not services:
            print('No services to check')
        else:
            for service in services:
                # check if the service has not been updated for a long time
                if time.time()-service['last_update'] > self.threshold:
                    try:
                        request=requests.delete(f'{self.catalogURL}/services/{service["ID"]}')
                    except requests.exceptions.RequestException:
                        print(f"CATALOG MANAGER: failed request for removing service {service['ID']} from catalog")
                    if request.status_code == 200:
                        print(f'Service {service["ID"]} has been removed')
                    else:
                        print(request.text)
                        print(f"CATALOG MANAGER: failed to remove service {service['ID']} from catalog")
                    check = False
            if check:
                print('No services to remove')
        
        check = True
        medications = self.getMedications()
        if not medications:
            print('No medications to check')
        else:
            patients = self.getPatients()
            # if there are no patients, remove all medications
            if not patients:
                print('No patients, remove all medications')
                for medication in medications:
                    try:
                        request=requests.delete(f'{self.catalogURL}/medications/{medication["ID"]}')
                    except requests.exceptions.RequestException:
                        print(f"CATALOG MANAGER: failed request for removing medication {medication['ID']} from catalog")
                    if request.status_code == 200:
                        print(f'Medication {medication["ID"]} has been removed since its patient has been removed')
                    else:
                        # print(request.text)
                        print(f"CATALOG MANAGER: failed to remove medication {medication['ID']} from catalog")
            else:
                # if there are patients, check if the medications are still associated with them 
                for medication in medications:
                    if int(medication['patientID']) not in [int(patient['ID']) for patient in patients]:
                        try:
                            request=requests.delete(f'{self.catalogURL}/medications/{medication["ID"]}')
                        except requests.exceptions.RequestException:
                            print(f"CATALOG MANAGER: failed request for removing medication {medication['ID']} from catalog")
                        if request.status_code == 200:
                            print(f'Medication {medication["ID"]} has been removed since its patient has been removed')
                        else:
                            print(request.text)
                            print(f"CATALOG MANAGER: failed to remove medication {medication['ID']} from catalog")
                        check = False
                if check:
                    print('No medications to remove')

# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    
    print("Received stop signal, shutting down Catalog Manager...")
    if manager is not None:
        manager.stop()
    print("Catalog Manager stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__ == '__main__':
    try:
        settings= json.load(open('settings.json'))
    except json.JSONDecodeError as e:
        print(f"CATALOG MANAGER: Error loading json settings: {e}")
        exit(1)
    except FileNotFoundError as e:
        print(f"CATALOG MANAGER: Json settings file not found")
        exit(1)
    manager = None
    try:
        manager = CatalogManager(settings)
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down Catalog Manager...")
        if manager is not None:
            manager.stop()
        print("Catalog Manager stopped.")
        exit(0)