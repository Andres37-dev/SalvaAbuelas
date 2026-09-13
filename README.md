# Sentinel

An opensource edge AI project to give support to the care of the elderly and other dependent people.

This projects detects a person falling using two systems:

- A collar with a Nesso N1: a little device with a gyroscope and accelerometer.

- A camera analyzed with the deep learning MoveNet model.

It also supports a manual alert by pressing the button of the collar.

And all possible alerts can be cancelled by the user so that we prevent false positives from be considered real alerts.

A real alert can then be connected to any type of communication system like sending a message to a phone, so that someone can come to the rescue of the person in trouble.

## Motivation

Nobody can be 24/7 with a dependent person. Because we have a job to assist, or simply tasks to do such as shopping some groceries, we will need to leave those at risk alone for short or longer periods of time.

That is where Sentinel shines: it allows to detect emergencies and act in response to them.

## What you need

You need:

- 1 Arduino UNO Q board with Linux installed.

- A webcam such as the Logitech Brio 105.

- An Arduino Nesso N1. You will need to attach it to a collar. We recommend to unscrew the four screws and pass a thin collar through the two pieces of the Nesso.

- A USB-C hub that has one USB type A port and accepts power intake. This will let the Arduino control the camera while accepting power. We have used a UGREEN 6 in 1, similar to the one on [this link](https://eu.ugreen.com/es-es/products/ugreen-uno-6-in-1-usb-c-hub).

- Some way to give power to the Arduino and to charge the Nesso N1 from time to time. We recommend a phone charger exclusive for the Arduino, and using another phone charger for the Nesso N1 (this one can be your usual phone charger).

## Steps to set it up

1. Download Arduino App Lab.

2. Place all the necessary files into the Arduino, including the Python scripts, requirements and the MoveNet model.

3. Give power to your Arduino, make sure the Nesso has battery, and place the camera somewhere it can see a hole room, at a height between 1 and 2 meters.

## Some technical details

### Video

The camera stream is analyzed at a specified frame rate and processed by MoveNet, which is able to distinguish the key points of one person that appears in the image.

Then, the logic to detect a fall is straightforward. There are some various cases which are flagged as a fall, such as:

- A horizontal (or close to horizontal) torso.
- A torso too small in comparison with the distance between the shoulders.
- Legs that are too long with respect to the torso.
- The head being under other parts of the body (except hands or wrists).
- A sudden variation of both torso length and angle.

## Credits

To build our project we have used:

- [MoveNet model and code examples](https://www.tensorflow.org/hub/tutorials/movenet), under the s Creative Commons Attribution 4.0 License.

- The Arduino Python package.

