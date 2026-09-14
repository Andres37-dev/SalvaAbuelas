# Sentinel

An opensource edge AI project to give support to the care of the elderly and other dependent people.

This projects detects a person falling using two systems:

- A collar with a Nesso N1: a little device with a gyroscope and accelerometer.

- A camera analyzed with the deep learning MoveNet model.

It also supports a manual alert by pressing the button of the collar.

And all possible alerts can be cancelled by the user so that we prevent false positives from be considered real alerts.

A real alert can then be connected to any type of communication system like sending a message to a phone, so that someone can come to the rescue of the person in trouble.

Moreover, for monitoring the Nesso's battery you can know its charge by pressing the central button.

## Motivation

Nobody can be 24/7 with a dependent person. Because we have a job to assist, or simply tasks to do such as shopping some groceries, we will need to leave those at risk alone for prolonged periods of time.

That is where Sentinel shines: it allows responsables to detect emergencies and act in response to them.

## What you need

You need:

- 1 Arduino UNO Q board with Linux installed.

- A webcam such as the Logitech Brio 105 ([here](https://logitech.com/en-es/products/webcams/brio-105-business-webcam.html))

- An Arduino Nesso N1. You will need to attach it to a collar. We recommend to unscrew the four screws and pass a thin collar through the two pieces of the Nesso.

- A USB-C hub that has one USB type A port and accepts power intake. This will let the Arduino control the camera while accepting power. We have used a UGREEN 6 in 1, similar to the one on [this link](https://eu.ugreen.com/es-es/products/ugreen-uno-6-in-1-usb-c-hub).

- Some way to give power to the Arduino and to charge the Nesso N1 from time to time. We recommend a phone charger exclusive for the Arduino, and using another phone charger for the Nesso N1 (this one can be your usual phone charger).

## Steps to set it up

1. Download Arduino App Lab.

3. Configure arduino uno Q to set up a wifi connection with the help of arduino lab, and remember the assigned ip, also visible in the arduino lab.

2. Place all the necessary files into the Arduino, including the Python scripts, requirements and the MoveNet model.

3. Change the mqtt_server in Prgroam2.py, Config.h to the assigned ip. Do the same for the SERVERR_IP in Program1-new.py

4. By default we have made an example account that will send the email. Its recommended to change it. In Program1-new.py change the following to set up the email notification:
   EMAIL_FROM: the email that will send the alert
    EMAIL_PASSWORD = its password, if using a google account for the EMAIL_FROM, search its app password
    EMAIL_TO = the one who will receive the email
 

6. In Config.h change wifi_ssid to the same wifi name that the arduino uno Q, and set the wifi_password to the wifi password. 

7. SSH into the arduino uno Q, run:
    sudo apt update
    sudo apt install mosquitto
   
8. edit the /etc/mosquitto/mosquitto.conf, and add the two following lines:
   listener 0.0.0.0 1883  
   allow_anonymous true  
   
9. run the following command:
   sudo systemctl restart mosquitto.service

10. connect to the hub the arduino uno Q, the camera and the battery.

11. Give power to your Arduino, make sure the Nesso has battery, and place the camera somewhere it can see a whole room, at a height between 1 and 2 meters.

In case that the nesso doasn't show any type of display, it means that the connection to the arduino MQTT broker is not working correctly: make sure you followed the instructions correctly.

## Some technical details

### Video

The camera stream is analyzed at a specified frame rate and processed by MoveNet, which is able to distinguish the key points of one person that appears in the image.

Then, the logic to detect a fall is straightforward. There are some various cases which are flagged as a fall, such as:

- A horizontal (or close to horizontal) torso.
- A torso too small in comparison with the distance between the shoulders.
- Legs that are too long with respect to the torso.
- The head being under other parts of the body (except hands or wrists).
- A sudden variation of both torso length and angle.

### IMU (accelerometer + gyroscope)

The accelerometer and gyroscope are sampled continuously and filtered for noise, watching for anomalies. Then, the logic to flag a fall is also quite straightforward. A few signals are combined into a score, the strongest being:

- A sharp drop in acceleration (near weightlessness), followed by a hard impact within a fraction of a second.
- A large, sudden change in the device's orientation, from upright to roughly flat.
- A strong swing in acceleration measured along the direction of gravity specifically, rather than any direction.
- A burst of fast rotation.
- Stillness right after, instead of continued movement.

## Central Logic point
The arduino uno Q hosts a program that communicates through MQTT to the camera stream and the nesso stream. When either the nesso detects a fall, or the users triggers the alarm manually an email will be sent to the caregiver notifying of the fall.
However, when the camera is the one to detect that the person has fallen, it makes the nesso beep, waiting for a confirmation. If the user doasn't confirm in 15s the real alarm is sent.

## Credits

To build our project we have used:

- [MoveNet model and code examples](https://www.tensorflow.org/hub/tutorials/movenet), under the Creative Commons Attribution 4.0 License.

- The Arduino Python package.

- Arduino IDE
