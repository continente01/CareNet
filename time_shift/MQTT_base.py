import paho.mqtt.client as PahoMQTT
import json
import requests
import random

class MQTT_base:
    def __init__(self, clientID, broker, port, notifier=None):
        self.broker = broker
        self.port = port
        self.notifier = notifier
        self.clientID = clientID
        self.topics = []
        self.mqttClient = PahoMQTT.Client(clientID,True)  
        # register the callback
        self.mqttClient.on_connect = self.onConnect
        self.mqttClient.on_message = self.onMessageReceived
        self.start()

    def onConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d" % (self.broker, rc))
        # Re-subscribe to all topics after (re)connect
        for topic in self.topics:
            self.mqttClient.subscribe(topic, 2)
            print(f"Re-subscribed to topic {topic}")

    def onMessageReceived (self, paho_mqtt , userdata, msg):
        print(f"[DEBUG] Message received on topic {msg.topic}: {msg.payload}")
        if self.notifier:
            try:
                self.notifier.notify(msg.topic, msg.payload)
            except Exception as e:
                print(f"[ERROR] Notifier failed: {e}")

    def publish (self, topic, msg):
        # publish a message with a certain topic
        self.mqttClient.publish(topic, json.dumps(msg), 2)
       
 
    def subscribe (self, topic): 
        if topic not in self.topics:
            self.topics.append(topic)
            self.mqttClient.subscribe(topic, 2)
        print ("subscribed to topic %s" % (topic))
 
    def start(self):
        self.mqttClient.connect(self.broker , self.port)
        self.mqttClient.loop_start()

    def unsubscribe(self,topic=None):
        if (self.topics): # if there are topics to unsubscribe from
            if topic is None: # if no topic is specified, unsubscribe from all topics
                for topic in self.topics:
                    self.mqttClient.unsubscribe(topic)
            elif(topic in self.topics): #if topic is specified and in list topics, unsubscribe from that topic
                self.mqttClient.unsubscribe(topic)
                self.topics.remove(topic)
            else:
                print(f"Topic {topic} not found in subscribed topics")
        else:
            print("No topics to unsubscribe from")
            
    def stop (self):
        self.unsubscribe()
        self.mqttClient.loop_stop()
        self.mqttClient.disconnect()
