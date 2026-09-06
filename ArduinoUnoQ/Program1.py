# Program 1 

import network
import time

from umqtt.simple import MQTTClient


# Config _______________________________________________________________________

MQTT_POLL_INTERVAL = 0.1
PREALERT_DURATION = 15
MQTT_DRAIN_MAX = 10
CAMERA_HEARTBEAT_TIMEOUT = 90   # seconds - if C1 stops publishing anything, that's itself a fault

PRIORITY = {"manual": 0, "nesso": 1, "camera": 2}

SSID = "NOM_WIFI"
PASSWORD = "CONTRASENA_WIFI"

MQTT_SERVER = "IP_BROKER"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ArduinoUnoQ_Central"


NESSO_TOPIC = b"Nesso/events"
NESSO_ASK_TOPIC = b"Nesso/command"
NESSO_ANSW_TOPIC = b"Nesso/response"

CAMERA_01_TOPIC = b"Cameras/01/events"

# Messages
MESSAGE_PREALERT = "ANOMALIA_DETECTADA"        
MESSAGE_CANCEL_ALARM = "FALSA_ALARMA"
MESSAGE_MANUAL_PREALERT = "AYUDA_SOLICITADA"
MESSAGE_CAMERA_FALL = "CAIDA_DETECTADA"          # ajustar cuando se cierre el Programa 2
MESSAGE_CAMERA_HEARTBEAT = "CAMARA_OK"           # ajustar cuando se cierre el Programa 2


# Global state _________________________________________________________________

active_sources = set()      # subset of {"nesso", "camera", "manual"}
prealert_active = False
alert_sent = False
confirmation_chrono = 0.0

last_camera_heartbeat = 0.0

client = None

wifi = network.WLAN(network.STA_IF)
wifi.active(True)


# Helpers ______________________________________________________________________

def get_timestamp():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5]
    )


# Wi-Fi ________________________________________________________________________

def ensure_wifi_connection() -> bool:
    if wifi.isconnected():
        return True

    print("Connecting to Wi-Fi...")
    wifi.connect(SSID, PASSWORD)

    for _ in range(15):
        if wifi.isconnected():
            print("Connected. IP:", wifi.ifconfig()[0])
            return True

        if wifi.status() == network.STAT_WRONG_PASSWORD:
            print("Error: wrong password.")
            return False

        time.sleep(1)

    print("Error: wifi timeout. Status:", wifi.status())
    return False


# MQTT _________________________________________________________________________

def mqtt_update_states(topic: bytes, payload: bytes) -> None:
    """Callback invoked synchronously from within check_msg()."""

    global prealert_active, confirmation_chrono, alert_sent, last_camera_heartbeat

    tw_thread = payload.decode("utf-8")

    if topic == NESSO_TOPIC:
        if  tw_thread == MESSAGE_PREALERT:
            active_sources.add("nesso")
            print("MQTT: Nesso fall message received.")
        elif tw_thread == MESSAGE_MANUAL_PREALERT:
            active_sources.add("manual")
            print("MQTT: Nesso manual alert received.")
        else:
            print("MQTT: unexpected message on Nesso/events:", tw_thread)

    elif topic == NESSO_ANSW_TOPIC:
        if tw_thread == MESSAGE_CANCEL_ALARM:
            if prealert_active:
                print("MQTT: alarm cancelled by explicit user confirmation.")
                active_sources.clear()
                prealert_active = False
                alert_sent = False
                protocol_cancelled_alarm()
            else:
                print("MQTT: cancel received with no active prealert - ignored.")
        else:
            print("MQTT: unexpected message on Nesso/response:", tw_thread)

    elif topic == CAMERA_01_TOPIC:
        last_camera_heartbeat = time.time()
        if tw_thread == MESSAGE_CAMERA_FALL:
            active_sources.add("camera")
            print("MQTT: camera fall message received.")
        elif tw_thread == MESSAGE_CAMERA_HEARTBEAT:
            pass
        else:
            print("MQTT: unexpected message on Cameras/01/events:", tw_thread)

    else:
        print("MQTT: message on unsubscribed topic:", topic)


def drain_mqtt() -> None:
    """Function that process up to MQTT_DRAIN_MAX messages per loop"""
    for _ in range(MQTT_DRAIN_MAX):
        client.check_msg()


def connect_mqtt() -> bool:
    global client

    print("Connecting to MQTT broker...")

    for attempt in range(1, 6):
        try:
            client = MQTTClient(MQTT_CLIENT_ID, MQTT_SERVER, port=MQTT_PORT)
            client.set_callback(mqtt_update_states)
            client.connect()

            client.subscribe(NESSO_TOPIC)
            client.subscribe(NESSO_ANSW_TOPIC)
            client.subscribe(CAMERA_01_TOPIC)
            print("MQTT connected and subscribed.")
            return True

        except Exception as e:
            print(f"MQTT connection failed (attempt {attempt}/5):", e)
            if attempt < 5:
                time.sleep(2)

    print("Could not connect to MQTT broker.")
    return False


# Setup ________________________________________________________________________

def setup() -> bool:
    print("Setting up...")
    ok = ensure_wifi_connection() and connect_mqtt()
    if ok:
        print("Setup done.")
    return ok


def ensure_connections() -> None:
    if not wifi.isconnected():
        print("Wi-Fi link down, reconnecting...")
        while not setup():
            print("Retrying connections in 5s (device stays alive)...")
            time.sleep(5)


def check_camera_heartbeat(now: float) -> None:
    """Function to check if the camera is publishing actively """

    if last_camera_heartbeat == 0.0:
        return  

    if time.time() - last_camera_heartbeat > CAMERA_HEARTBEAT_TIMEOUT:
        print(f"WARNING: no message from camera in over {CAMERA_HEARTBEAT_TIMEOUT}s.")
        # TODO: decide how this should surface — separate "system fault" alert
        # to the caregiver, distinct from a user fall/distress alert.

# Nesso interaction ____________________________________________________________

def protocol_possible_alarm(alarm_message: str) -> None:
    print(alarm_message)
    client.publish(NESSO_ASK_TOPIC, b"INICIAR_VIBRACION", qos=1)


def protocol_cancelled_alarm() -> None:
    client.publish(NESSO_ASK_TOPIC, b"DETENER_VIBRACION", qos=1)


def send_definitive_alert(alarm_message: str) -> None:
    """TODO: replace with the real notification to the caregiver."""
    print(f"DEFINITIVE ALERT: {alarm_message} (sent at {get_timestamp()})")


# Decision logic _______________________________________________________________

_SOURCE_LABELS = {
    "manual": "Alarm triggered manually",
    "camera": "Fall detected by the camera",
    "nesso": "Fall detected by the Nesso",
}


def build_alarm_message() -> str:
    """Ahora mismo está puesto que la prioridad de mensajes sea
    1. alerta manual
    2. alerta nesso
    3. alerta cámara"""

    timestamp = get_timestamp()
    if len(active_sources) > 1:
        ordered = sorted(active_sources, key=lambda s: PRIORITY.get(s, 99))
        return f"Multiple triggers {ordered} at {timestamp}"
    source = next(iter(active_sources))
    return f"{_SOURCE_LABELS[source]} at {timestamp}"


# Main loop ____________________________________________________________________

def loop() -> None:
    global prealert_active, alert_sent, confirmation_chrono

    ensure_connections()

    try:
        drain_mqtt()
    except Exception as e:
        print("MQTT error:", e)
        setup()

    now = time.time()

    check_camera_heartbeat(now)

    if active_sources and not prealert_active:
        prealert_active = True
        confirmation_chrono = now
        protocol_possible_alarm(build_alarm_message())

    if prealert_active and not alert_sent:
        if now - confirmation_chrono >= PREALERT_DURATION:
            send_definitive_alert(build_alarm_message())
            alert_sent = True


# Main _________________________________________________________________________

while not setup():
    print("Initial setup failed, retrying in 5s...")
    time.sleep(5)

while True:
    loop()
    time.sleep(MQTT_POLL_INTERVAL)