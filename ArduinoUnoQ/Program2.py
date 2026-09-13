# program 2_
import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCode
from collections.abc import Callable

import cv2
from collections import deque
import FallDetectorMovenet as fall_detector

from enum import Enum
import time


CAMERA_01_EVENTS = "Cameras/01/events"

class Messages(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    PREALERT = "ANOMALIA_DETECTADA"        
    CAMERA_FALL = "CAIDA_DETECTADA"   
    MESSAGE_CAMERA_ABSENCE = "AUSENCIA_PROLONGADA"   # provisional


# Config _______________________________________________________________________

PRESENCE_TIMEOUT = 12 * 3600    # "usuario no visto" -> tratado como anomalía propia

MQTT_SERVER = "IP_BROKER"
MQTT_PORT = 1883

# MQTT _______________________________________________________________________


class mqttHandler():
    client: mqtt.Client

    def __init__(self) -> None:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2, # type: ignore
                protocol=mqtt.MQTTv5,
            )
            self.client.reconnect_delay_set( # Curioso
                min_delay=1,
                max_delay=60,
            )
    
            self.client.on_disconnect = self.on_disconnect
            self.client.on_connect = self.on_connect

    def on_connect(self, client, userdata, flags, reason_code: ReasonCode, properties):
        print("connected successfully to the broker! ", reason_code)
        self.client.publish(CAMERA_01_EVENTS, Messages.ONLINE, qos=1, retain=True)        
            
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
        self.client.will_set(CAMERA_01_EVENTS, Messages.OFFLINE, qos=1, retain=True) 
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

    def publish(self, topic: str, payload: str):
        self.client.publish(topic, payload)

# Cámara ___________________________________________________________
class FallDetector:

    def __init__(self, camera_device=None):
        self.camera_device = (
            fall_detector.CAMERA_DEVICE
            if camera_device is None
            else camera_device
        )

        self.fps = fall_detector.FPS
        self.frame_interval = 1.0 / self.fps

        self.states = deque(maxlen=fall_detector.WINDOW)

        self.crop_region = None
        self.image_height = None
        self.image_width = None
        self.last_processed = 0.0

        # Evita publicar continuamente mientras la misma caída sigue siendo
        # detectada en varios frames consecutivos.
        self.previous_fall_detected = False

    def open(self):
        cap = cv2.VideoCapture(self.camera_device)

        if not cap.isOpened():
            raise RuntimeError(
                f"Could not open camera device {self.camera_device}"
            )

        ret, frame = cap.read()

        if not ret:
            cap.release()
            raise RuntimeError("Could not read first frame from camera")

        self.image_height, self.image_width = frame.shape[:2]

        self.crop_region = fall_detector.init_crop_region(
            self.image_height,
            self.image_width,
        )

        return cap, frame

    def process_frame(self, frame):
        """Lo mismo que en FallDetectorMovenet """
        now = time.time()

        if now - self.last_processed < self.frame_interval:
            return None, False

        self.last_processed = now

        # Por si la resolución de la cámara cambia.
        image_height, image_width = frame.shape[:2]

        if (
            self.image_height != image_height
            or self.image_width != image_width
            or self.crop_region is None
        ):
            self.image_height = image_height
            self.image_width = image_width
            self.crop_region = fall_detector.init_crop_region(
                image_height,
                image_width,
            )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tf_frame = fall_detector.tf.convert_to_tensor(rgb)

        keypoints_with_scores = fall_detector.run_inference(
            fall_detector.movenet,
            tf_frame,
            self.crop_region,
            crop_size=[fall_detector.input_size, fall_detector.input_size],
        )

        # Igual que en FallDetectorMovenet.py:
        self.crop_region = fall_detector.determine_crop_region(
            keypoints_with_scores,
            image_height,
            image_width,
        )

        self.states.append(keypoints_with_scores)

        if len(self.states) >= 2:
            state = fall_detector.analyze_keypoints(list(self.states))
        else:
            state = {
                "user_in_frame": False,
                "fall_detected": False,
            }

        return state, True

    def should_publish_anomaly(self, state):
        """
        Publica anomalía si detecta caída.

        Si el detector permanece varios frames con fall_detected=True,
        no se envía un mensaje MQTT por cada frame.
        """
        fall_detected = bool(state.get("fall_detected", False))

        new_anomaly = fall_detected and not self.previous_fall_detected

        self.previous_fall_detected = fall_detected

        return new_anomaly

    def reset(self):
        self.states.clear()
        self.crop_region = None
        self.previous_fall_detected = False

# Main _________________________________________________________________________

def main():
    mqtt_client = mqttHandler()
    mqtt_client.start(MQTT_SERVER, MQTT_PORT)

    detector = FallDetector()

    cap = None

    try:
        cap, first_frame = detector.open()

        # Procesamos el primer frame
        state, processed = detector.process_frame(first_frame)

        while True:
            # Mantener MQTT activo.
            mqtt_client.iteration()

            ret, frame = cap.read()

            if not ret:
                print("Could not read frame from camera")
                break

            state, processed = detector.process_frame(frame)

            if not processed:
                # No se hace inferencia en este frame porque todavía no
                # ha transcurrido 1/FPS segundos.
                continue

            
            if detector.should_publish_anomaly(state):
               
                mqtt_client.publish(CAMERA_01_EVENTS, Messages.PREALERT.value)

            # Debug opcional por consola.
            print(
                f"processed @ {detector.fps} FPS | "
                f"user_in_frame={state.get('user_in_frame')} | "
                f"fall_detected={state.get('fall_detected')} | "
                f"reasons={state.get('fall_reasons')}"
            )

    except Exception as e:
        print(f"Error: {e}")
       


if __name__ == "__main__":
    main()

