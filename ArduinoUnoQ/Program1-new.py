import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCode
from collections.abc import Callable

from enum import Enum
import time

class MQTTopics(str, Enum):
    NESSO_EVENTS = "Nesso/events"
    NESSO_COMMAND = "Nesso/command"
    NESSO_RESPONSE = "Nesso/response"
    
    CAMERA_01_EVENTS = "Cameras/01/events"

class Messages(str, Enum):
    PREALERT = "ANOMALIA_DETECTADA"        
    CANCEL_ALARM = "FALSA_ALARMA"
    MANUAL_PREALERT = "AYUDA_SOLICITADA"
    CAMERA_FALL = "CAIDA_DETECTADA"          # ajustar cuando se cierre el Programa 2
    CAMERA_HEARTBEAT = "CAMARA_OK"           # ajustar cuando se cierre el Programa 2

def get_timestamp():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5]
    )

class mqttHandler():
    client: mqtt.Client
    subscriptions:  dict[str, Callable[[mqtt.MQTTMessage], None]]
    def __init__(self) -> None:
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, # type: ignore
            protocol=mqtt.MQTTv5,
        )
        self.client.reconnect_delay_set( # Curioso
            min_delay=1,
            max_delay=60,
        )

        self.subscriptions = {}
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.on_connect = self.on_connect

    def on_connect(self, client, userdata, flags, reason_code: ReasonCode, properties):
        print("connected successfully to the broker! ", reason_code)
        for topic in self.subscriptions:
            self.client.subscribe(topic, 1)            
            
    def on_disconnect(self, client, userdata, disconnect_flags, reason_code: ReasonCode, properties):
        print("disconnected from the broker rc: ", reason_code)
        if reason_code.is_failure:
            while True:
                try:
                    print("trying to reconnect...")
                    self.client.reconnect()
                    break
                except OSError:
                    pass
    
    def start(self, server: str, port: int):
        tries = 0
        while tries < 3:
            try:
                print("trying to connect...")
                tries += 1
                self.client.connect(server, port, keepalive=5)
                break
            except OSError:
                print("Couldn't connect")
        if tries >= 3:
            print("Server down? :(")
            exit()
        print("connected successfully!")

    def iteration(self):
        self.client.loop(timeout=0.1)

    def loop(self):
        self.client.loop_forever()

    def on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        handler = self.subscriptions.get(msg.topic)
        if handler != None:
            handler(msg)
    
    def subscribe(self, topic: str, handler: Callable[[mqtt.MQTTMessage], None]):
        self.subscriptions[topic] = handler


class LogicHandler:
    MqttH = mqttHandler()
    def __init__(self) -> None:
        MqttH.subscribe(MQTTopics.CAMERA_01_EVENTS, test)
        MqttH.subscribe(MQTTopics.NESSO_RESPONSE, test2)
        MqttH.subscribe(MQTTopics.NESSO_EVENTS, test2)
        MqttH.start("localhost", 1883)


def test(msg: mqtt.MQTTMessage):
    print("message arribed (camera event): ", msg.payload)

def test2(msg: mqtt.MQTTMessage):
    print("message arribed (camera event): ", msg.payload)

MqttH = mqttHandler()
MqttH.subscribe(MQTTopics.CAMERA_01_EVENTS, test)
MqttH.subscribe(MQTTopics.NESSO_EVENTS, test2)
MqttH.start("localhost", 1883)
while True:
    MqttH.iteration()