import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from pprint import pprint
import time
import paho.mqtt.client as PahoMQTT
import json
import requests
import uuid
from MQTT_base import MQTT_base
import threading

def read_json_file(file_name):
    try:
        with open(file_name , 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f" TELEGRAM BOT: Error: The file {file_name} does not exist, creating a empty one.")
        with open(file_name, 'w') as file:
            json.dump({}, file)
        return {}
    except json.JSONDecodeError:
        print(f" TELEGRAM BOT: Error: The file {file_name} is not a valid JSON file,creating a empty one.")
        with open(file_name, 'w') as file:
            json.dump({}, file)
        return {}
    

class TelegramBot:
    def __init__(self,settings):
        if settings is None:
            raise ValueError("Settings cannot be None")
        if 'pingInterval' not in settings:
            self.pingInterval = 10
        else:
            self.pingInterval = settings['pingInterval']
        if 'mqtt_data' not in settings or 'catalogURL' not in settings or 'serviceInfo' not in settings or 'telegramToken' not in settings or 'timeShiftUrl' not in settings:
            raise ValueError("Settings must contain 'mqtt_data', 'catalogURL', 'serviceInfo', 'telegramToken', and 'timeShiftUrl' keys")
        self.catalogURL = settings['catalogURL']
        self.serviceInfo = settings['serviceInfo']
        self.telegram_token = settings['telegramToken']
        self.timeShiftUrl = settings['timeShiftUrl']
        if 'serviceName' not in self.serviceInfo:
            self.serviceInfo['serviceName'] = "Telegram Bot"
        if 'broker' not in settings["mqtt_data"] or 'port' not in settings["mqtt_data"] or 'mqtt_topic' not in settings["mqtt_data"]:
            raise ValueError("Settings must contain 'broker', 'port', and 'mqtt_topic' in 'mqtt_data'")
        self.broker = settings["mqtt_data"]["broker"]
        self.port = settings["mqtt_data"]["port"]
        self.topic = settings["mqtt_data"]["mqtt_topic"]
        self.clientID = str(uuid.uuid1())
        self.client=MQTT_base(self.clientID,self.broker,self.port,self) 
        self.thingspeak_fields = settings["thingspeak_fields"]
        self.serviceID = None
        self.serviceInfo['ID'] = self.assign_serviceID()
        self.serviceID = self.serviceInfo['ID']
        try:
            self.bot=telepot.Bot(self.telegram_token)
            MessageLoop(self.bot, {'chat': self.on_chat_message,'callback_query': self.on_callback_query}).run_as_thread()
        except requests.exceptions.ConnectionError:
                print("Telegram connection refused")
                return
        self.start()

    def start (self):
        self.registerService()
        self.client.start()
        self.client.subscribe(self.topic)
        # two thread are needed, one for updating the service in catalog, the other to send notifications for medications
        self.update_thread = threading.Thread(target=self.update_loop,daemon=True)
        self.notification_thread = threading.Thread(target=self.notification_loop,daemon=True)
        self.update_thread.start()
        self.notification_thread.start()
        # when the Telegram bot becomes available, it sends a message to all registered chats
        chats = self.getchatIDs()
        keyboard_home = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='Return to Home', callback_data='home')],
            ])
        for chatID in chats:
            try:
                self.bot.sendMessage(chatID, "The Telegram bot is back on!", reply_markup=keyboard_home)
            except telepot.exception.TelegramError as e:
                print(f"TELEGRAM BOT: Error sending message to chat ID {chatID}: {e}")

    def stop (self):
        print("entered stop function")
        self.client.stop()
        chats = self.getchatIDs()
        print(chats)
        for chatID in chats:
            try:
                self.bot.sendMessage(chatID, "The Telegram bot is stopping, you will not receive any more notifications.")
            except telepot.exception.TelegramError as e:
                print(f"TELEGRAM BOT: Error sending message to chat ID {chatID}: {e}")
        try:
            self.update_thread.join()
        except Exception as e:
            print(f"TELEGRAM BOT: Error joining update thread: {e}")
        try:
            self.notification_thread.join()
        except Exception as e:
            print(f"TELEGRAM BOT: Error joining notification thread: {e}")

# gets chat IDs form catalog 
    def getchatIDs(self):
        try:
            response = requests.get(f'{self.catalogURL}/chats')
        except requests.exceptions.RequestException as e:
            print(f"TELEGRAM BOT: Error requesting chats from catalog: {e}")
            return []
        if response.status_code != 200:
            print(f"TELEGRAM BOT: Failed to get chats from catalog, status code {response.status_code}")
            return []
        if 'chats' not in response.json():
            print("TELEGRAM BOT: no field chats found in response")
            return []
        chats = response.json()["chats"]
        if not chats:
            print("TELEGRAM BOT: no chats found in catalog")
            return []
        return [chat['ID'] for chat in chats]

# loop to update service in catalog
    def update_loop(self):
        while True:
            time.sleep(self.pingInterval)
            self.updateService()

    def updateService(self):
        try:
            request=requests.put(f'{self.catalogURL}/services',data=json.dumps(self.serviceInfo))
        except requests.exceptions.RequestException:
            print(f"TELEGRAM BOT: failed request for updating service {self.serviceInfo['ID']} in catalog")
            return
        if request.status_code != 200:
            print(f"TELEGRAM BOT: failed to update service {self.serviceInfo['ID']} in catalog, registering again")
            self.registerService()  # If update fails, try to register the service again

# loop to send notifications for medications
# every hour, it checks the catalog for medications at that hour and sends notifications to registered chats
    def notification_loop(self):
        while True:
            now = time.localtime()
            # Calculate seconds until next hour
            if now.tm_min == 0:
                self.sendNotifications()
            time.sleep(30)

    def sendNotifications(self):
        print("TELEGRAM BOT: Checking for medication notifications...")
        try:
            response = requests.get(f'{self.catalogURL}/medications')
        except requests.exceptions.RequestException as e:
            print(f"TELEGRAM BOT: Error requesting medications: {e}")
            return
        if response.status_code != 200:
            print(f"TELEGRAM BOT: Failed to get medications from catalog, status code {response.status_code}")
            return
        if 'medications' not in response.json():
            print("TELEGRAM BOT: no field medications found in response")
            return
        medications = response.json()["medications"]
        chats = self.getchatIDs()
        
        hour = time.strftime("%H", time.localtime())
        # print(f'actual time: {hour}')
        for medication in medications:
            # print(f'medication hour: {medication['hour']}')
            if int(medication['hour']) == int(hour):
                for chatID in chats:
                    try:
                        self.bot.sendMessage(chatID, text=f"Reminder: it's time for the medication {medication['name']} for patient {medication['patientID']} at hour {medication['hour']}.")
                    except telepot.exception.TelegramError as e:
                        print(f"TELEGRAM BOT: Error sending notification to chat ID {chatID}: {e}")

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

# assign a patient ID, when a new patient is created
    def assign_patientID(self):
        while True: # Loop until a valid patient ID is obtained
            try:
                response = requests.get(f'{self.catalogURL}/patients')
            except requests.exceptions.RequestException:
                print("TELEGRAM BOT: failed request for patients from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"TELEGRAM BOT: failed to get patients from catalog, status code {response.status_code}")
                time.sleep(5)  # wait before retrying
                continue
            if 'patients' not in response.json():
                print("TELEGRAM BOT: no field patients found in response")
                time.sleep(5)  # wait before retrying
                continue
            patients = response.json()['patients']
            if patients != []:
                return max(patient['ID'] for patient in patients) + 1
            else:
                return 1

# assign a medication ID, when a new medication is created
    def assign_medicationID(self):
        while True: # Loop until a valid medication ID is obtained
            try:
                response = requests.get(f'{self.catalogURL}/medications')
            except requests.exceptions.RequestException:
                print("TELEGRAM BOT: failed request for medications from catalog, retrying...")
                time.sleep(5)
                continue
            if response.status_code != 200:
                print(f"TELEGRAM BOT: failed to get medications from catalog, status code {response.status_code}")
                return
            medications = response.json()['medications']
            if medications != []:
                return max(medication['ID'] for medication in medications) + 1
            else:
                return 1

# function to register service to the catalog
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


# Telegram bot is subscribed to topics where time shift and time control publish alarm messages
    def notify(self, topic, payload):
        if not payload:
            print("TELEGRAM BOT: received empty payload, skipping notification")
            return
        message = json.loads(payload)
        print(f"TELEGRAM BOT: received message on topic {topic}: {message}")
        if 'alarmType' not in message or message['alarmType'] not in ["time_shift", "time_control"]:
            print("TELEGRAM BOT: alarm not recognized, skipping notification")
            return
        if message['alarmType'] == "time_shift":
            '''
            message = {
                            'alarm_type': 'time_shift',
                            'patientID': patientID,
                            'field': field,
                            'hour': hour
                        }
            '''
            if 'patientID' not in message or 'field' not in message or 'hour' not in message:
                print("TELEGRAM BOT: missing fields in time_shift message, skipping notification")
                return
            chats = self.getchatIDs()
            for chatID in chats:
                try: 
                    self.bot.sendMessage(chatID, text=f"Alarm for patient {message['patientID']}:\n{message['hour']}:00 is an anomaly time for field {message['field']}.")
                except telepot.exception.TelegramError as e:
                    print(f"TELEGRAM BOT: Error sending notification to chat ID {chatID}: {e}")
                
        if message['alarmType'] == "time_control":
            '''
            message = {
                            'alarmType': "time_control",
                            'patientID': patientID,
                            'sensorID': sensorID,
                            'field': field,
                            'value': value,
                            'timestamp': timestamp}
            '''
            chats = self.getchatIDs()
            for chatID in chats:
                try:
                    actual_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(message['timestamp']))
                    self.bot.sendMessage(chatID, text=f"Alarm for patient {message['patientID']}:\nSensor {message['sensorID']} for {message['field']} value {round(message['value'])} at {actual_time}")
                except telepot.exception.TelegramError as e:
                    print(f"TELEGRAM BOT: Error sending notification to chat ID {chatID}: {e}")
    
    def check_integer(self, value):
        try:
            value = int(value)
            return value
        except ValueError as e:
            return None
                            
    def on_chat_message(self,msg):
        content_type, chat_type ,chat_ID = telepot.glance(msg)
        message=msg['text']
        # keyboard shown in "home page"
        keyboard_home = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='Return to Home', callback_data='home')],
            ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='Add a new patient', callback_data='create_patient')],
                    [InlineKeyboardButton(text='Add a new medication', callback_data='create_medication')],
                    [InlineKeyboardButton(text='Remove a patient', callback_data='remove_patient')],
                    [InlineKeyboardButton(text='Remove a medication', callback_data='remove_medication')],
                    [InlineKeyboardButton(text='View patients', callback_data='view_patients')],
                    [InlineKeyboardButton(text='View medications', callback_data='view_medications')],
                    [InlineKeyboardButton(text='View important times', callback_data='view_times')],
                    [InlineKeyboardButton(text='EXIT', callback_data='exit')],
                ])
        
        # needed to save the ID to send messages, it is set when the bot is started (with /start)
        if message=='/start':  
            try:
                response = requests.post(f'{self.catalogURL}/chats', data=json.dumps({"ID": chat_ID}))
            except requests.exceptions.RequestException as e:
                print(f"TELEGRAM BOT: Error registering chat ID {chat_ID} in catalog: {e}")
                self.bot.sendMessage(chat_ID, text="Error registering your chat ID, please try again later.")
                return
            if response.status_code != 200:
                if response.status_code == 401:
                    self.bot.sendMessage(chat_ID, text="Your chat ID is already registered.", reply_markup=keyboard_home)
                    return
                print(f"TELEGRAM BOT: Failed to register chat ID {chat_ID} in catalog, status code {response.status_code}")
                self.bot.sendMessage(chat_ID, text="Failed to register your chat ID, please try again later.")
                return
            print(f"TELEGRAM BOT: chat ID {chat_ID} registered in catalog")
            try:
                self.bot.sendMessage(chat_ID,text="Welcome to the Telegram Bot!\nFrom here you can add patients" \
                ", remove them and manage their medication. Here you will also receive " \
                "notifications about your patients, like health alarms and medication reminders.", reply_markup=keyboard)
            except telepot.exception.TelegramError as e:
                print(f"TELEGRAM BOT: Error sending welcome message to chat ID {chat_ID}: {e}")
            return
        # when any other message is received, check if the chatID is present in catalog, and update if it is
        else:
            URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
            try:
                response = requests.get(URLToSend)
            except requests.exceptions.RequestException as e:
                print(f"TELEGRAM BOT: Error retrieving chat ID {chat_ID} from catalog: {e}")
            if response.status_code == 404:
                print(f"TELEGRAM BOT: Chat ID {chat_ID} not found in catalog.")
                self.bot.sendMessage(chat_ID, text="Chat ID not found in catalog. Please start the bot with /start to register your chat ID.")
                return
            if response.status_code != 200:
                print(f"TELEGRAM BOT: Failed to retrieve chat ID {chat_ID} from catalog, status code {response.status_code}")
                self.bot.sendMessage(chat_ID, text="Failed to retrieve your chat ID, please try again later.")
                return
            else:
                URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
                try:
                    response = requests.put(URLToSend, data=json.dumps({"ID": chat_ID}))
                except requests.exceptions.RequestException as e:
                    print(f"TELEGRAM BOT: Error updating chat ID {chat_ID} in catalog: {e}")
                if response.status_code != 200:
                    print(f"TELEGRAM BOT: Failed to update chat ID {chat_ID} in catalog, status code {response.status_code}")
        # if /exit, /quit or /stop is sent, delete the chatID from the catalog
        if message=='/exit' or message=='/stop' or message=='/quit':
            self.bot.sendMessage(chat_ID,text="Exiting chat, thanks for using the Telegram Bot! You will not receive any more alarms.")
            URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
            try:
                response = requests.delete(URLToSend)
            except requests.exceptions.RequestException as e:
                print(f"TELEGRAM BOT: Error removing chat ID {chat_ID} from catalog: {e}")
                self.bot.sendMessage(chat_ID, text="Error removing your chat ID, please try again later.")
                return
            if response.status_code != 200:
                print(f"TELEGRAM BOT: Failed to remove chat ID {chat_ID} from catalog, status code {response.status_code}")
                self.bot.sendMessage(chat_ID, text="Failed to remove your chat ID, please try again later.")
                return
            print(f"TELEGRAM BOT: chat ID {chat_ID} removed from catalog")
            self.bot.sendMessage(chat_ID,text="Chat ID removed")
        # if /home is received, show the "home page"
        elif message == "/home":
            self.bot.sendMessage(chat_ID,text="From here you can add patients" \
            ", remove them and manage their medication. Here you will also receive " \
            "notifications about your patients, like health alarms and medication reminders.", reply_markup=keyboard)
        
        elif message.startswith('/create_patient '):
            try:
                _, name, surname, age = message.split(' ', 3)
                if not name or not surname or not age:
                    self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/create_patient <name> <surname> <age>`", reply_markup=keyboard_home)
                    return
                age = self.check_integer(age)
                if age is None:
                    try: 
                        self.bot.sendMessage(chat_ID, text=f"Age must be a number.")
                    except telepot.exception.TelegramError as e:
                        print(f"TELEGRAM BOT: Error sending notification to chat ID {chat_ID}: {e}")
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/create_patient <name> <surname> <age>`", reply_markup=keyboard_home)
                return
            patientID = self.assign_patientID()
            URLToSend = f"{self.catalogURL}/patients"
            patient_info = {
                    "name": name,
                    "surname": surname,
                    "age": age,
                    "ID": patientID
            }
            try:
                response = requests.post(URLToSend, data=json.dumps(patient_info))
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to create patient: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200:
                print(f"Error in catalog: {response.text}")
                return
            self.bot.sendMessage(chat_ID, text=f"Patient {name} {surname}, age {age} created successfully! "
                                                     f"The patient ID is {patient_info['ID']}. Remember to assign their "
                                                     f"sensors and medications to this ID.", reply_markup=keyboard_home)
        
        elif message.startswith('/remove_patient '):
            try:
                _, patient_id_str = message.split(' ', 1)
                patient_id = int(patient_id_str)
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/remove_patient <patient_id>`", reply_markup=keyboard_home)
                return
            URLToSend = f"{self.catalogURL}/patients/{patient_id}"
            try:
                response = requests.delete(URLToSend)
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to remove patient: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200:
                print(f"Error in catalog: {response.text}")
                self.bot.sendMessage(chat_ID, text=f"Error in catalog removing patient {patient_id}", reply_markup=keyboard_home)
                return
            self.bot.sendMessage(chat_ID, text=f"Patient {patient_id} removed successfully.", reply_markup=keyboard_home)

        elif message.startswith('/view_patient '):
            try:
                _, patient_id_str = message.split(' ', 1)
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/view_patient <patient_id>`", reply_markup=keyboard_home)
                return
            if patient_id_str.lower() == 'all':
                URLToSend = f"{self.catalogURL}/patients"
                try:
                    response = requests.get(URLToSend)
                except requests.exceptions.RequestException as e:
                    self.bot.sendMessage(chat_ID, text=f"Error making request to view all patients: {e}", reply_markup=keyboard_home)
                    return
                if response.status_code != 200:
                    print(f"Error in catalog: {response.text}")
                    return
                patients_info = response.json()
                if not patients_info['patients']:
                    self.bot.sendMessage(chat_ID, text="No patients found.", reply_markup=keyboard_home)
                else:
                    patient_list = "\n".join([f"ID: {p['ID']}, Name: {p['name']}, Surname: {p['surname']}, Age: {p['age']}\n" for p in patients_info['patients']])
                    self.bot.sendMessage(chat_ID, text=f"Patients:\n{patient_list}", reply_markup=keyboard_home)
            else:
                patient_id = int(patient_id_str)
                URLToSend = f"{self.catalogURL}/patients/{patient_id}"
                try:
                    response = requests.get(URLToSend)
                except requests.exceptions.RequestException as e:
                    self.bot.sendMessage(chat_ID, text=f"Error making request to view patient: {e}", reply_markup=keyboard_home)
                    return
                if response.status_code != 200:
                    print(f"Error in catalog: {response.text}")
                    return
                if 'patient' not in response.json():
                    self.bot.sendMessage(chat_ID, text=f"field patient not present in catalog response", reply_markup=keyboard_home)
                    return
                patient_info = response.json()['patient']
                self.bot.sendMessage(chat_ID, text=f"Patient Information:\n"
                                                f"ID: {patient_info['ID']}\n"
                                                f"Name: {patient_info['name']}\n"
                                                f"Surname: {patient_info['surname']}\n"
                                                f"Age: {patient_info['age']}", reply_markup=keyboard_home)
        
        elif message.startswith('/create_medication '):
            try:
                _, patient_id, medication_name, dosage, hour = message.split(' ', 4)
                if not patient_id or not medication_name or not dosage or not hour:
                    self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/create_medication <patient_id> <medication_name> <dosage> <hour>`", reply_markup=keyboard_home)
                    return
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/create_medication <patient_id> <medication_name> <dosage> <hour>`", reply_markup=keyboard_home)
                return
            patient_id = self.check_integer(patient_id)
            medication_name = medication_name.strip()
            hour = self.check_integer(hour)
            if patient_id is None or hour is None:
                try: 
                    self.bot.sendMessage(chat_ID, text=f"Patient ID must be a number.")
                except telepot.exception.TelegramError as e:
                    print(f"TELEGRAM BOT: Error sending notification to chat ID {chat_ID}: {e}")
                return
            if not (0 <= hour < 24):
                try:
                    self.bot.sendMessage(chat_ID, text="Hour must be a number between 0 and 23.", reply_markup=keyboard_home)
                except telepot.exception.TelegramError as e:
                    print(f"TELEGRAM BOT: Error sending notification to chat ID {chat_ID}: {e}")
                return
            
            # Check if patient exists
            URLToSend = f"{self.catalogURL}/patients?patientID={patient_id}"
            try:
                response = requests.get(URLToSend)
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to check patient: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200:
                print(f"Error in catalog: {response.text}")
                return
            ID = self.assign_medicationID()
            medication_info = {
                "patientID": patient_id,
                "name": medication_name,
                "dosage": dosage,
                "hour": hour,
                "ID": ID
            }
            URLToSend = f"{self.catalogURL}/medications"
            try:
                response = requests.post(URLToSend, json=medication_info)
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to create medication: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200 and response.status_code != 201:
                print(f"Error in catalog: {response.text}")
                self.bot.sendMessage(chat_ID, text=f"Error in catalog creating medication {medication_info['ID']}", reply_markup=keyboard_home)
                return
            self.bot.sendMessage(chat_ID, text=f"Medication {medication_name} for patient {patient_id} created successfully with ID {ID}.", reply_markup=keyboard_home)

        elif message.startswith('/remove_medication '):
            try:
                _, medication_id_str = message.split(' ', 1)
                medication_id = int(medication_id_str)
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/remove_medication <medication_id>`. Medication_id must be a number.", reply_markup=keyboard_home)
                return
            try:
                response = requests.delete(f"{self.catalogURL}/medications/{medication_id}")
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to remove medication: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200 and response.status_code != 204:
                print(f"Error in catalog: {response.text}")
                self.bot.sendMessage(chat_ID, text=f"Error in catalog removing medication {medication_id}", reply_markup=keyboard_home)
                return
            self.bot.sendMessage(chat_ID, text=f"Medication with ID {medication_id} removed successfully.", reply_markup=keyboard_home)

        elif message.startswith('/view_medication '):
            try:
                _, patient_id = message.split(' ', 1)
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/view_medication <patient_id>`", reply_markup=keyboard_home)
                return
            try:
                response = requests.get(f"{self.catalogURL}/medications")
            except requests.exceptions.RequestException as e:
                self.bot.sendMessage(chat_ID, text=f"Error making request to view medications: {e}", reply_markup=keyboard_home)
                return
            if response.status_code != 200:
                self.bot.sendMessage(chat_ID, text=f"Error retrieving medications: {response.text}", reply_markup=keyboard_home)
                return
            medications = response.json().get('medications', [])
            if patient_id.lower() == 'all':
                medication_list = "\n".join([f"Medication ID: {med['ID']}, Patient ID: {med['patientID']}, Name: {med['name']}, Dosage: {med['dosage']}, Hour: {med['hour']}" for med in medications])
                self.bot.sendMessage(chat_ID, text=f"All Medications:\n{medication_list}", reply_markup=keyboard_home)
            else:
                try:
                    patient_id = int(patient_id)
                except ValueError:
                    self.bot.sendMessage(chat_ID, text="PatientID must be a number.", reply_markup=keyboard_home)
                    return
                patient_medications = [med for med in medications if med['patientID'] == patient_id]
                if not patient_medications:
                    self.bot.sendMessage(chat_ID, text=f"No medications found for patient ID {patient_id}.", reply_markup=keyboard_home)
                    return
                medication_list = "\n".join([f"Name: {med['name']}, Dosage: {med['dosage']}, Hour: {med['hour']}, ID: {med['ID']} \n" for med in patient_medications])
                self.bot.sendMessage(chat_ID, text=f"Medications for Patient ID {patient_id}:\n{medication_list}", reply_markup=keyboard_home)
        
        elif message.startswith('/view_times'):
            try:
                _, patient_id = message.split(' ', 1)
            except ValueError:
                self.bot.sendMessage(chat_ID, text="Invalid format. Use: `/view_times <patient_id>`", reply_markup=keyboard_home)
                return
            if patient_id.lower() == 'all':
                URLToSend = f"{self.catalogURL}/patients"   
                try:
                    response = requests.get(URLToSend)  
                except requests.exceptions.RequestException as e:
                    self.bot.sendMessage(chat_ID, text=f"Error retrieving patients: {e}", reply_markup=keyboard_home)
                    return
                if response.status_code != 200:
                    self.bot.sendMessage(chat_ID, text=f"Error retrieving patients: {response.text}", reply_markup=keyboard_home)
                    return
                patients= response.json()['patients']
                if not patients:
                    self.bot.sendMessage(chat_ID, text="No patients found.", reply_markup=keyboard_home)
                    return
                for patient in patients:
                    patient_id = patient['ID']
                    self.get_anomaly_times_patient(patient_id, chat_ID, keyboard_home)
            else:
                self.get_anomaly_times_patient(patient_id, chat_ID, keyboard_home)
        
        else:
            self.bot.sendMessage(chat_ID, text="Unknown command. Please use the buttons to see the valid formats for commands.", reply_markup=keyboard_home)

# this function sends a request to time shift to receive the important times of a patient
    def get_anomaly_times_patient(self, patient_id, chat_ID, keyboard_home):
        patient_id = self.check_integer(patient_id)
        if patient_id is None:
            try:
                self.bot.sendMessage(chat_ID, text="Invalid patient ID. Please enter a valid number.", reply_markup=keyboard_home)
            except telepot.exception.TelegramError as e:
                print(f"TELEGRAM BOT: Error sending invalid patient ID message to chat ID {chat_ID}: {e}")
            return
        URLToSend = f"{self.timeShiftUrl}/{patient_id}"
        try:
            response=requests.get(URLToSend)
        except requests.exceptions.RequestException as e:
            self.bot.sendMessage(chat_ID, text=f"Error retrieving important times: {e}", reply_markup=keyboard_home)
            return
        if response.status_code == 404:
                    self.bot.sendMessage(chat_ID, text="Patient not found", reply_markup=keyboard_home)
                    return
        if response.status_code != 200:
            self.bot.sendMessage(chat_ID, text=f"Error retrieving important times: {response.text}", reply_markup=keyboard_home)
            return
        # print(response.json())
        anomaly_times = response.json()
        if not anomaly_times:
            self.bot.sendMessage(chat_ID, text=f"Error retrieving important times for patient {patient_id}.", reply_markup=keyboard_home)
            return
        message = f"Important times for patient {patient_id}:\n"
        for field in anomaly_times:
            if anomaly_times[field] == []:
                message = message + f"No important times found for field {field} of patient {patient_id}.\n"
            else:
                times_str = ":00, ".join(anomaly_times[field])+ ":00"
                message = message + f"Important times for field {field} of patient {patient_id}:\n{times_str}\n"
        self.bot.sendMessage(chat_ID, text=message, reply_markup=keyboard_home)

# management of the pressed buttons
    def on_callback_query(self,msg):
        query_id, chat_ID, query_data = telepot.glance(msg, flavor='callback_query')
        URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
        try:
            response = requests.get(URLToSend)
        except requests.exceptions.RequestException as e:
            print(f"TELEGRAM BOT: Error retrieving chat ID {chat_ID} from catalog: {e}")
        if response.status_code == 404:
            print(f"TELEGRAM BOT: Chat ID {chat_ID} not found in catalog.")
            self.bot.sendMessage(chat_ID, text="Chat ID not found in catalog. Please start the bot with /start to register your chat ID.")
            return
        URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
        try:
            response = requests.put(URLToSend, data=json.dumps({"ID": chat_ID}))
        except requests.exceptions.RequestException as e:
            print(f"TELEGRAM BOT: Error updating chat ID {chat_ID} in catalog: {e}")
        if response.status_code != 200:
            print(f"TELEGRAM BOT: Failed to update chat ID {chat_ID} in catalog, status code {response.status_code}")
        keyboard_home = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='Return to Home', callback_data='home')],
            ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='Add a new patient', callback_data='create_patient')],
                    [InlineKeyboardButton(text='Add a new medication', callback_data='create_medication')],
                    [InlineKeyboardButton(text='Remove a patient', callback_data='remove_patient')],
                    [InlineKeyboardButton(text='Remove a medication', callback_data='remove_medication')],
                    [InlineKeyboardButton(text='View patients', callback_data='view_patient')],
                    [InlineKeyboardButton(text='View medications', callback_data='view_medication')],
                    [InlineKeyboardButton(text='View important times', callback_data='view_times')],
                    [InlineKeyboardButton(text='EXIT', callback_data='exit')],
                ])
        if query_data == 'exit':
            self.bot.sendMessage(chat_ID, text="Exiting chat, thanks for using the Telegram Bot! You will not receive any more alarms.")
            URLToSend = f"{self.catalogURL}/chats/{chat_ID}"
            try:
                response = requests.delete(URLToSend)
            except requests.exceptions.RequestException as e:
                print(f"TELEGRAM BOT: Error removing chat ID {chat_ID} from catalog: {e}")
                self.bot.sendMessage(chat_ID, text="Error removing your chat ID, please try again later.")
            if response.status_code != 200:
                print(f"TELEGRAM BOT: Failed to remove chat ID {chat_ID} from catalog, status code {response.status_code}")
                self.bot.sendMessage(chat_ID, text="Error removing your chat ID, please try again later.")
                return
            self.bot.sendMessage(chat_ID, text="Chat ID removed")
            return
        elif query_data == 'home':
            self.bot.sendMessage(chat_ID, text="From here you can add patients" \
            ", remove them and manage their medication. Here you will also receive " \
            "notifications about your patients, like health alarms and medication reminders.", reply_markup=keyboard)
            return
        elif query_data == 'create_patient':
            self.bot.sendMessage(chat_ID, text="To create a new patient, please send a message with the following format:\n"
                                               "`/create_patient <name> <surname> <age>`. An ID will be assigned automatically.", reply_markup=keyboard_home)
            return
        elif query_data == 'create_medication':
            self.bot.sendMessage(chat_ID, text="To create a new medication, please send a message with the following format:\n"
                                               "`/create_medication <patient_id> <medication_name> <dosage> <hour>`", reply_markup=keyboard_home)
            return
        elif query_data == 'remove_patient':
            self.bot.sendMessage(chat_ID, text="You can remove a patient by sending the following format:\n"
                                               "`/remove_patient <patient_id>`", reply_markup=keyboard_home)
            return
        elif query_data == 'remove_medication':
            self.bot.sendMessage(chat_ID, text="You can remove a medication by sending the following format:\n"
                                               "`/remove_medication <medication_id>`", reply_markup=keyboard_home)
        elif query_data == 'view_patient':
            self.bot.sendMessage(chat_ID, text="You can view a patient by sending the following command:\n"
                                               "`/view_patient <patient_id>`\n If you want to see them all, write 'all' instead of <patient_id>", reply_markup=keyboard_home)
            return
        elif query_data == 'view_medication':
            self.bot.sendMessage(chat_ID, text="You can view all medications of a patient by sending the following command:\n"
                                               "`/view_medication <patient_id>`\n If you want to see them all, write 'all' instead of <patient_id>", reply_markup=keyboard_home)
            return
        elif query_data == 'view_times':
            self.bot.sendMessage(chat_ID, text="You can view the important times of a patient by sending the following command:\n"
                                               "`/view_times <patient_id>`\n If you want to see them all, write 'all' instead of <patient_id>", reply_markup=keyboard_home)
            return
# Signal handling for shutdown with stopping the container
import signal

def handle_stop(signum, frame):
    print("Received stop signal, shutting down Telegram Bot...")
    if bot is not None:
        bot.stop()
    print("Telegram Bot stopped.")

signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

if __name__=="__main__":
    settings = read_json_file('settings.json')
    if settings == {}:
        print("Settings file not found or empty, please fill the settings.json file with the required settings.")
        exit(1)
    bot = None
    try:
        bot = TelegramBot(settings)
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down Telegram Bot...")
        if bot is not None:
            bot.stop()
        print("Telegram Bot stopped.")
        exit(0)