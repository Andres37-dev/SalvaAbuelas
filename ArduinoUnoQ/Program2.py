# program 2_

import network
import time

from umqtt.simple import MQTTClient

# TODO: import de tu SDK de Edge Impulse cuando lo tengas listo
# from edge_impulse import EIClassifier


# Config _______________________________________________________________________

MQTT_POLL_INTERVAL = 0.1
CAMERA_CHECK_INTERVAL = 5.0     # cada cuánto se procesa una imagen
HEARTBEAT_INTERVAL = 30.0       # cada cuánto se avisa "sigo vivo"
PRESENCE_TIMEOUT = 12 * 3600    # "usuario no visto" -> tratado como anomalía propia

SSID = "NOM_WIFI"
PASSWORD = "CONTRASENA_WIFI"

MQTT_SERVER = "IP_BROKER"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ArduinoUnoQ_Camera01"

CAMERA_01_TOPIC = b"Cameras/01/events"

MESSAGE_CAMERA_FALL = "CAIDA_DETECTADA"
MESSAGE_CAMERA_HEARTBEAT = "CAMARA_OK"
MESSAGE_CAMERA_ABSENCE = "AUSENCIA_PROLONGADA"   # provisional


# Global state _________________________________________________________________

client = None
last_camera_check = 0.0
last_heartbeat_sent = 0.0
last_time_seen = 0.0   # última vez que el usuario apareció en cuadro

wifi = network.WLAN(network.STA_IF)
wifi.active(True)


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

def connect_mqtt() -> bool:
    global client

    print("Connecting to MQTT broker...")

    for attempt in range(1, 6):
        try:
            client = MQTTClient(MQTT_CLIENT_ID, MQTT_SERVER, port=MQTT_PORT)
            client.connect()

            return True

        except Exception as e:
            print(f"MQTT connection failed (attempt {attempt}/5):", e)
            if attempt < 5:
                time.sleep(2)

    print("Could not connect to MQTT broker.")
    return False


# Setup ________________________________________________________________________

def setup() -> bool:
    print("Setting up (C1)...")
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


# Cámara / Edge Impulse _________________________________________________________

def capture_frame():
    """TODO: capturar un frame de la cámara conectada por el hub. ANGEL"""



def run_anomaly_detection(frame) -> dict:
    """TODO: pasar el frame por el modelo de Edge Impulse. ANGEL
    Debe devolver algo como {"user_in_frame": bool, "fall_detected": bool}.
    Implementado así para el posible añadimiento de confianza """


def process_frame(now: float) -> None:
    global last_time_seen

    frame = capture_frame()
    result = run_anomaly_detection(frame)

    if result["user_in_frame"]:
        last_time_seen = now
        if result["fall_detected"]:
            publish(MESSAGE_CAMERA_FALL)
    else:
        if now - last_time_seen >= PRESENCE_TIMEOUT:
            publish(MESSAGE_CAMERA_ABSENCE)


def publish(message: str) -> None:
    client.publish(CAMERA_01_TOPIC, message.encode("utf-8"), qos=1)
    print("C1 publish:", message)


# Main loop ____________________________________________________________________

def loop() -> None:
    global last_camera_check, last_heartbeat_sent

    ensure_connections()

    now = time.time()

    if now - last_camera_check >= CAMERA_CHECK_INTERVAL:
        try:
            process_frame(now)
        except Exception as e:
            print("Camera processing error:", e)
        last_camera_check = now

    if now - last_heartbeat_sent >= HEARTBEAT_INTERVAL:
        publish(MESSAGE_CAMERA_HEARTBEAT)
        last_heartbeat_sent = now


# Main _________________________________________________________________________

while not setup():
    print("Initial setup failed, retrying in 5s...")
    time.sleep(5)

while True:
    loop()
    time.sleep(MQTT_POLL_INTERVAL)