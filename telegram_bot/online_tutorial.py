import telepot
from telepot.loop import MessageLoop
from pprint import pprint
import time
import paho.mqtt.client as PahoMQTT
import json
import requests

class TelegramBot:
    def __init__(self,token,broker,port,topic_publish,topic_subscribe):
        self.clientID="telegramBot"
        try:
            self.token=token
            self.bot=telepot.Bot(self.token)
        # catalog token
        # self.token=requests.get("http://catalogIP/teegram_token").json()["telegramToken"]
            MessageLoop(self.bot, {'chat': self.on_chat_message,'callback_query': self.on_callback_query}).run_as_thread()
        except requests.exceptions.ConnectionError:
                print("Connection refused")
        self.chat_ID=None
        self.__message={'bn':"telegramBot",'e':[{'n':'switch','v':'', 't':'','u':'bool'}]} # SenML Dataformat
        

        self.broker=broker
        self.port=port
        self.topic_subscribe=topic_subscribe
        self.topic_publish=topic_publish
        self.client=PahoMQTT.Client(self.clientID, True)
        self.client.on_connect = self.onConnect
        self.client.on_message = self.onMqttMsgReceived
        self.start()
        

    def start (self):
        #manage connection to broker
        self.client.connect(self.broker, 1883)
        self.client.loop_start()
        # subscribe for a topic
        self.client.subscribe(self.topic_subscribe, 2)

    def stop (self):
        self.client.unsubscribe(self.topic_subscribe)
        self.client.loop_stop()
        self.client.disconnect()

    def onConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d" % (self.broker, rc))

    def onMqttMsgReceived (self, paho_mqtt , userdata, msg):
        # A new message is received
        if  self.chat_ID:
            message=json.loads(msg.payload)
            self.bot.sendMessage(self.chat_ID, text="You received:\n"+str(message["status"])) # to be changed, only to try
    
    def publish(self, topic, message):
        # publish a message with a certain topic
        self.client.publish(topic, message, 2)
            
    def on_callback_query(self,msg):
        query_ID , chat_ID , query_data = telepot.glance(msg,flavor='callback_query')
        payload = self.__message.copy()
        payload['e'][0]['v'] = query_data
        payload['e'][0]['t'] = time.time()
        self.client.publish(self.topic_publish, payload)
        self.bot.sendMessage(chat_ID, text=f"Led switched {query_data}")
    
    

    def on_chat_message(self,msg):
        content_type, chat_type ,chat_ID = telepot.glance(msg)
        message=msg['text']
        if message=='/helloworld':
            self.bot.sendMessage(chat_ID,text="Command Hello World 🤓 ")
        elif message=='/save':  # needed to save the ID to send messages, it can be set when the bot is started (with /start)
            self.chat_ID=chat_ID
            self.bot.sendMessage(chat_ID,text="Chat ID saved")
        elif message=='/exit':
            self.bot.sendMessage(chat_ID,text="Chat ID removed")
            self.chat_ID=None
        else:
            self.publish(self.topic_publish,message)
            self.bot.sendMessage(chat_ID,text="You sent:\n"+str(message))



if __name__=="__main__":
    configuration=json.load(open('config.json'))
    token_bot=configuration['token']
    mqtt_broker=configuration['mqtt_broker']
    mqtt_port=configuration['mqtt_port']
    topic_publish=configuration['topic_publish']
    topic_subscribe=configuration['topic_subscribe']
    telegrambot=TelegramBot(token_bot,mqtt_broker,mqtt_port,topic_publish,topic_subscribe)
    while True:
        time.sleep(3)