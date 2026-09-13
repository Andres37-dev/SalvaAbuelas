import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCode
from collections.abc import Callable

from enum import Enum
import time


class MQTTopics():
    NESSO_EVENTS = "Nesso/events"
    NESSO_STATUS = "Nesso/status"           # FUTURE IMPLEMENTATION

    NESSO_COMMAND = "Nesso/command"
    NESSO_RESPONSE = "Nesso/response"

    CAMERA_01_EVENTS = "Cameras/01/events"  
    CAMERA_01_STATUS = "Cameras/01/status"  # FUTURE IMPLEMENTATION

class Messages():
    NESSO_FALL = "ANOMALIA_DETECTADA"        
    CAMERA_FALL = "CAIDA_DETECTADA"          # ajustar cuando se cierre el Programa 2
    FALSE_ALARM = "FALSA_ALARMA"
    MANUAL_ALARM = "AYUDA_SOLICITADA"

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"

class NessoCommands():
    START_VIBRATE = "START_VIBRATE"
    STOP_VIBRATE = "STOP_VIBRATE"

class Conf():
    TIME_TO_CONFIRM = 15
    SERVER_IP = "localhost"
    SERVER_PORT = 1883

    

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
            self.client.subscribe(topic, qos=1)            
            
    def on_disconnect(self, client, userdata, disconnect_flags, reason_code: ReasonCode, properties):
        print("disconnected from the broker rc: ", reason_code)
        if reason_code.is_failure:
            while True:
                try:
                    print("trying to reconnect...")
                    self.client.reconnect()
                    break
                except OSError:
                    time.sleep(3)
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
            raise ConnectionError("Could not connect to MQTT broker")
        print("connected successfully!")

    def iteration(self):
        self.client.loop(timeout=0.1)

    def loop(self):
        self.client.loop_forever()

    def on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        handler = self.subscriptions.get(msg.topic)
        if handler != None:
            handler(msg)
        else:
            print("topico no conocido")
    
    def subscribe(self, topic: str, handler: Callable[[mqtt.MQTTMessage], None]):
        self.subscriptions[topic] = handler
        if self.client.is_connected():
            self.client.subscribe(topic, qos=1)

    def publish(self, topic: str, payload: str):
        self.client.publish(topic, payload)


class Sources(str, Enum):
    NESSO = "NESSO"
    CAMERA = "CAMERA"
    MANUAL = "MANUAL"

class LogicHandler:
    MqttH: mqttHandler
    sources: set 

    waitingConfirmation: bool 
    sentConfirmationAt: float 

    alarmSent: bool

    def __init__(self) -> None:
        self.MqttH: mqttHandler = mqttHandler()
        self.sources: set = set()
        self.waitingConfirmation: bool = False
        self.sentConfirmationAt: float = 0.0
        self.alarmSent: bool = False
        
        self.MqttH.subscribe(MQTTopics.CAMERA_01_EVENTS, self.cameraEventMSG)
        self.MqttH.subscribe(MQTTopics.NESSO_EVENTS, self.nessoEventMSG)
        self.MqttH.subscribe(MQTTopics.NESSO_RESPONSE, self.nessoResponseMSG)

        self.MqttH.subscribe(MQTTopics.NESSO_STATUS, self.checkStatus)
        self.MqttH.subscribe(MQTTopics.CAMERA_01_STATUS, self.checkStatus)

        self.MqttH.start(Conf.SERVER_IP, Conf.SERVER_PORT)

    # DONE
    def nessoEventMSG(self, msg: mqtt.MQTTMessage):
        text = msg.payload.decode()

        if text == Messages.NESSO_FALL: 
            self.sources.add(Sources.NESSO)
            print("Nesso fall message received.")

        elif text == Messages.MANUAL_ALARM:
            self.sources.add(Sources.MANUAL)
            print("Manual fall message received.")
        else:
            self._invalidMSG(msg)

    # DONE
    def nessoResponseMSG(self, msg: mqtt.MQTTMessage):
        text = msg.payload.decode()
        if text == Messages.FALSE_ALARM:
            if self.waitingConfirmation:
                print("alarm cancelled by explicit user confirmation")
                self.sources.clear()
                self.waitingConfirmation = False
                self.MqttH.publish(MQTTopics.NESSO_COMMAND, NessoCommands.STOP_VIBRATE)
            else:
                print("alarm cancellation received when no waiting confirmation -- ignored")
        else:
            self._invalidMSG(msg)

    # DONE
    def cameraEventMSG(self, msg: mqtt.MQTTMessage):
        text = msg.payload.decode()
        if text == Messages.CAMERA_FALL:
            self.sources.add(Sources.CAMERA)
            print("Camera fall message received.")
        else:
            self._invalidMSG(msg)

    def checkStatus(self, msg: mqtt.MQTTMessage):
        text = msg.payload.decode()
        if msg.topic == MQTTopics.NESSO_STATUS:
            if text == Messages.OFFLINE:
                print("Nesso is offline. check its connection")
            elif text == Messages.ONLINE:
                print("Nesso is online")
            else:
                self._invalidMSG(msg)

        if msg.topic == MQTTopics.CAMERA_01_STATUS:
            if text == Messages.OFFLINE:
                print("Camera is offline. check its connection")
            elif text == Messages.ONLINE:
                print("Camera is online")
            else:
                self._invalidMSG(msg)

    def sendRealAlarm(self):
        print(f"REAL ALARM has been sent at {get_timestamp()}")

    def _invalidMSG(self, msg: mqtt.MQTTMessage):
        print("invalid message received at topic: ", msg.topic)
        print("payload: ", msg.payload)


    def main(self):
        while True:
            self.MqttH.iteration()
            now = time.time()

            # a source is telling about a fall and no confirmation has been sent?
            if self.sources and not self.waitingConfirmation:
                self.waitingConfirmation = True
                self.sentConfirmationAt = now
                self.MqttH.publish(MQTTopics.NESSO_COMMAND, NessoCommands.START_VIBRATE)
                print(f"confirmation has been sent at {get_timestamp()}")

            # a confirmation has been sent and after TIME_TO_CONFIRM seconds no respone? while no real alarm has been sent?
            if self.waitingConfirmation and not self.alarmSent and now - self.sentConfirmationAt >= Conf.TIME_TO_CONFIRM:
                self.alarmSent = True
                self.sendRealAlarm()

                # LIMPIAR ESTADO para continuar funcionando
                self.sources.clear()
                self.waitingConfirmation = False
                self.alarmSent = False
Program = LogicHandler()
Program.main()
# comprobado que las cosas de abajo funcionan
