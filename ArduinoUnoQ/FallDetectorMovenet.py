# FallDetectorMovenet.py
"""Self contained script to connect to a camera source and analyze the scene to detect someone falling,
using logic based on the body position thanks to MoveNet.

You can run this code in your PC or laptop provided that:
- You use a proper camera device and set it in CAMERA_DEVICE.
- You download the deep learning model and set the proper path in MODEL_PATH.
"""

import cv2
import numpy as np
import tensorflow as tf
import time

from collections import deque

# matplotlib
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection
import matplotlib.patches as patches

# Globals ______________________________________________________________________

# Enviornment config -----------------------------------------------------------

MODEL_PATH = "./models/movenet-tflite-singlepose-lightning-tflite-float16-v1.tflite"

CAMERA_DEVICE = 0 # 0 = default webcam

FPS = 3
"""Frame rate to process the image."""

WINDOW = 5 # 
"""Length of the window we analyze to detect a fall."""

FRAME_INTERVAL = 1.0 / FPS


# Decision making --------------------------------------------------------------

MIN_CONFIDENCE = 0.20
"""Minimum confidence needed to consider a person as detected.
This value must be between 0 and 1.
- The larger it is, the harder it is to detect someone. That could reduce false positives in exchange for false negatives."""


ANGLE_THRESHOLD = 30.0
"""How close the torso angle must be to horizontal to mark as a possible fall.
- The larger it is, the easier it is to find a fall, decreasing false negatives.
0°   = vertical torso
90°  = horizontal torso
"""

TORSO_TO_SHOULDERS_RATIO = 0.80
"""
A person standing normally will usually have a torso/shoulder ratio
comfortably above 0.80. Increase it only if we
are missing genuine falls.
"""

CHANGE_WINDOW = 3
"""Number of consecutive frames used to decide whether a change is real."""


SUDDEN_ANGLE_CHANGE = 25.0
"""
Minimum change in torso angle over CHANGE_WINDOW frames before we
consider it a genuine movement rather than pose-estimation noise.
"""

SUDDEN_LENGTH_CHANGE = 0.30
"""
Minimum relative change in torso length.

Example:
  old length = 0.20
  new length = 0.14

relative change = 0.30 -> 30%
# """

LEGS_TO_TORSO_RATIO = 3.0


# Helper functions for visualization ___________________________________________

# Dictionary that maps from joint names to keypoint indices.
KEYPOINT_DICT = {
    'nose': 0,
    'left_eye': 1,
    'right_eye': 2,
    'left_ear': 3,
    'right_ear': 4,
    'left_shoulder': 5,
    'right_shoulder': 6,
    'left_elbow': 7,
    'right_elbow': 8,
    'left_wrist': 9,
    'right_wrist': 10,
    'left_hip': 11,
    'right_hip': 12,
    'left_knee': 13,
    'right_knee': 14,
    'left_ankle': 15,
    'right_ankle': 16
}

# Maps bones to a matplotlib color name.
KEYPOINT_EDGE_INDS_TO_COLOR = {
    (0, 1): 'm',
    (0, 2): 'c',
    (1, 3): 'm',
    (2, 4): 'c',
    (0, 5): 'm',
    (0, 6): 'c',
    (5, 7): 'm',
    (7, 9): 'm',
    (6, 8): 'c',
    (8, 10): 'c',
    (5, 6): 'y',
    (5, 11): 'm',
    (6, 12): 'c',
    (11, 12): 'y',
    (11, 13): 'm',
    (13, 15): 'm',
    (12, 14): 'c',
    (14, 16): 'c'
}

def _keypoints_and_edges_for_display(keypoints_with_scores,
                                     height,
                                     width,
                                     keypoint_threshold=0.11):
  """Returns high confidence keypoints and edges for visualization.

  Args:
    keypoints_with_scores: A numpy array with shape [1, 1, 17, 3] representing
      the keypoint coordinates and scores returned from the MoveNet model.
    height: height of the image in pixels.
    width: width of the image in pixels.
    keypoint_threshold: minimum confidence score for a keypoint to be
      visualized.

  Returns:
    A (keypoints_xy, edges_xy, edge_colors) containing:
      * the coordinates of all keypoints of all detected entities;
      * the coordinates of all skeleton edges of all detected entities;
      * the colors in which the edges should be plotted.
  """
  keypoints_all = []
  keypoint_edges_all = []
  edge_colors = []
  num_instances, _, _, _ = keypoints_with_scores.shape
  for idx in range(num_instances):
    kpts_x = keypoints_with_scores[0, idx, :, 1]
    kpts_y = keypoints_with_scores[0, idx, :, 0]
    kpts_scores = keypoints_with_scores[0, idx, :, 2]
    kpts_absolute_xy = np.stack(
        [width * np.array(kpts_x), height * np.array(kpts_y)], axis=-1)
    kpts_above_thresh_absolute = kpts_absolute_xy[
        kpts_scores > keypoint_threshold, :]
    keypoints_all.append(kpts_above_thresh_absolute)

    for edge_pair, color in KEYPOINT_EDGE_INDS_TO_COLOR.items():
      if (kpts_scores[edge_pair[0]] > keypoint_threshold and
          kpts_scores[edge_pair[1]] > keypoint_threshold):
        x_start = kpts_absolute_xy[edge_pair[0], 0]
        y_start = kpts_absolute_xy[edge_pair[0], 1]
        x_end = kpts_absolute_xy[edge_pair[1], 0]
        y_end = kpts_absolute_xy[edge_pair[1], 1]
        line_seg = np.array([[x_start, y_start], [x_end, y_end]])
        keypoint_edges_all.append(line_seg)
        edge_colors.append(color)
  if keypoints_all:
    keypoints_xy = np.concatenate(keypoints_all, axis=0)
  else:
    keypoints_xy = np.zeros((0, 17, 2))

  if keypoint_edges_all:
    edges_xy = np.stack(keypoint_edges_all, axis=0)
  else:
    edges_xy = np.zeros((0, 2, 2))
  return keypoints_xy, edges_xy, edge_colors


def draw_prediction_on_image(
    image, keypoints_with_scores, crop_region=None, close_figure=False,
    output_image_height=None):
  """Draws the keypoint predictions on image.

  Args:
    image: A numpy array with shape [height, width, channel] representing the
      pixel values of the input image.
    keypoints_with_scores: A numpy array with shape [1, 1, 17, 3] representing
      the keypoint coordinates and scores returned from the MoveNet model.
    crop_region: A dictionary that defines the coordinates of the bounding box
      of the crop region in normalized coordinates (see the init_crop_region
      function below for more detail). If provided, this function will also
      draw the bounding box on the image.
    output_image_height: An integer indicating the height of the output image.
      Note that the image aspect ratio will be the same as the input image.

  Returns:
    A numpy array with shape [out_height, out_width, channel] representing the
    image overlaid with keypoint predictions.
  """
  height, width, channel = image.shape
  aspect_ratio = float(width) / height
  fig, ax = plt.subplots(figsize=(12 * aspect_ratio, 12))
  # To remove the huge white borders
  fig.tight_layout(pad=0)
  ax.margins(0)
  ax.set_yticklabels([])
  ax.set_xticklabels([])
  plt.axis('off')

  im = ax.imshow(image)
  line_segments = LineCollection([], linewidths=(4), linestyle='solid')
  ax.add_collection(line_segments)
  # Turn off tick labels
  scat = ax.scatter([], [], s=60, color='#FF1493', zorder=3)

  (keypoint_locs, keypoint_edges,
   edge_colors) = _keypoints_and_edges_for_display(
       keypoints_with_scores, height, width)

  if keypoint_edges.shape[0]:
    line_segments.set_segments(keypoint_edges)
    line_segments.set_color(edge_colors)
  if keypoint_locs.shape[0]:
    scat.set_offsets(keypoint_locs)

  if crop_region is not None:
    xmin = max(crop_region['x_min'] * width, 0.0)
    ymin = max(crop_region['y_min'] * height, 0.0)
    rec_width = min(crop_region['x_max'], 0.99) * width - xmin
    rec_height = min(crop_region['y_max'], 0.99) * height - ymin
    rect = patches.Rectangle(
        (xmin,ymin),rec_width,rec_height,
        linewidth=1,edgecolor='b',facecolor='none')
    ax.add_patch(rect)

  fig.canvas.draw()
  # Get the RGBA buffer from the canvas
  image_from_plot = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
  plt.close(fig)
  if output_image_height is not None:
    output_image_width = int(output_image_height / height * width)
    image_from_plot = cv2.resize(
        image_from_plot, dsize=(output_image_width, output_image_height),
         interpolation=cv2.INTER_CUBIC)
  return image_from_plot


# Model loading ________________________________________________________________

input_size = 192  # MoveNet Lightning input resolution

# Initialize the TFLite interpreter
interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()

def movenet(input_image):
    """Runs MoveNet SinglePose Lightning inference.

    Args:
        input_image: A tensor of shape [1, 192, 192, 3].

    Returns:
        A [1, 1, 17, 3] NumPy array containing keypoint coordinates and scores.
    """
    # The Float16 model still expects uint8 input
    input_image = tf.cast(input_image, dtype=tf.uint8)

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.set_tensor(input_details[0]["index"], input_image.numpy())

    # Run inference
    interpreter.invoke()

    # Get predictions
    keypoints_with_scores = interpreter.get_tensor(output_details[0]["index"])

    return keypoints_with_scores


# Image processing _____________________________________________________________

# Cropping Algorithm

# Confidence score to determine whether a keypoint prediction is reliable
MIN_CROP_KEYPOINT_SCORE = 0.2

def init_crop_region(image_height, image_width):
  """Defines the default crop region.

  The function provides the initial crop region (pads the full image from both
  sides to make it a square image) when the algorithm cannot reliably determine
  the crop region from the previous frame.
  """
  if image_width > image_height:
    box_height = image_width / image_height
    box_width = 1.0
    y_min = (image_height / 2 - image_width / 2) / image_height
    x_min = 0.0
  else:
    box_height = 1.0
    box_width = image_height / image_width
    y_min = 0.0
    x_min = (image_width / 2 - image_height / 2) / image_width

  return {
    'y_min': y_min,
    'x_min': x_min,
    'y_max': y_min + box_height,
    'x_max': x_min + box_width,
    'height': box_height,
    'width': box_width
  }


def torso_visible(keypoints):
  """Checks whether there are enough torso keypoints.

  This function checks whether the model is confident at predicting one of the
  shoulders/hips which is required to determine a good crop region.
  """
  return ((keypoints[0, 0, KEYPOINT_DICT['left_hip'], 2] >
           MIN_CROP_KEYPOINT_SCORE or
          keypoints[0, 0, KEYPOINT_DICT['right_hip'], 2] >
           MIN_CROP_KEYPOINT_SCORE) and
          (keypoints[0, 0, KEYPOINT_DICT['left_shoulder'], 2] >
           MIN_CROP_KEYPOINT_SCORE or
          keypoints[0, 0, KEYPOINT_DICT['right_shoulder'], 2] >
           MIN_CROP_KEYPOINT_SCORE))


def determine_torso_and_body_range(
    keypoints, target_keypoints, center_y, center_x):
  """Calculates the maximum distance from each keypoints to the center location.

  The function returns the maximum distances from the two sets of keypoints:
  full 17 keypoints and 4 torso keypoints. The returned information will be
  used to determine the crop size. See determineCropRegion for more detail.
  """
  torso_joints = ['left_shoulder', 'right_shoulder', 'left_hip', 'right_hip']
  max_torso_yrange = 0.0
  max_torso_xrange = 0.0
  for joint in torso_joints:
    dist_y = abs(center_y - target_keypoints[joint][0])
    dist_x = abs(center_x - target_keypoints[joint][1])
    if dist_y > max_torso_yrange:
      max_torso_yrange = dist_y
    if dist_x > max_torso_xrange:
      max_torso_xrange = dist_x

  max_body_yrange = 0.0
  max_body_xrange = 0.0
  for joint in KEYPOINT_DICT.keys():
    if keypoints[0, 0, KEYPOINT_DICT[joint], 2] < MIN_CROP_KEYPOINT_SCORE:
      continue
    dist_y = abs(center_y - target_keypoints[joint][0]);
    dist_x = abs(center_x - target_keypoints[joint][1]);
    if dist_y > max_body_yrange:
      max_body_yrange = dist_y

    if dist_x > max_body_xrange:
      max_body_xrange = dist_x

  return [max_torso_yrange, max_torso_xrange, max_body_yrange, max_body_xrange]


def determine_crop_region(
      keypoints, image_height,
      image_width):
  """Determines the region to crop the image for the model to run inference on.

  The algorithm uses the detected joints from the previous frame to estimate
  the square region that encloses the full body of the target person and
  centers at the midpoint of two hip joints. The crop size is determined by
  the distances between each joints and the center point.
  When the model is not confident with the four torso joint predictions, the
  function returns a default crop which is the full image padded to square.
  """
  target_keypoints = {}
  for joint in KEYPOINT_DICT.keys():
    target_keypoints[joint] = [
      keypoints[0, 0, KEYPOINT_DICT[joint], 0] * image_height,
      keypoints[0, 0, KEYPOINT_DICT[joint], 1] * image_width
    ]

  if torso_visible(keypoints):
    center_y = (target_keypoints['left_hip'][0] +
                target_keypoints['right_hip'][0]) / 2;
    center_x = (target_keypoints['left_hip'][1] +
                target_keypoints['right_hip'][1]) / 2;

    (max_torso_yrange, max_torso_xrange,
      max_body_yrange, max_body_xrange) = determine_torso_and_body_range(
          keypoints, target_keypoints, center_y, center_x)

    crop_length_half = np.amax(
        [max_torso_xrange * 1.9, max_torso_yrange * 1.9,
          max_body_yrange * 1.2, max_body_xrange * 1.2])

    tmp = np.array(
        [center_x, image_width - center_x, center_y, image_height - center_y])
    crop_length_half = np.amin(
        [crop_length_half, np.amax(tmp)]);

    crop_corner = [center_y - crop_length_half, center_x - crop_length_half];

    if crop_length_half > max(image_width, image_height) / 2:
      return init_crop_region(image_height, image_width)
    else:
      crop_length = crop_length_half * 2;
      return {
        'y_min': crop_corner[0] / image_height,
        'x_min': crop_corner[1] / image_width,
        'y_max': (crop_corner[0] + crop_length) / image_height,
        'x_max': (crop_corner[1] + crop_length) / image_width,
        'height': (crop_corner[0] + crop_length) / image_height -
            crop_corner[0] / image_height,
        'width': (crop_corner[1] + crop_length) / image_width -
            crop_corner[1] / image_width
      }
  else:
    return init_crop_region(image_height, image_width)


def crop_and_resize(image, crop_region, crop_size):
  """Crops and resize the image to prepare for the model input."""
  boxes=[[crop_region['y_min'], crop_region['x_min'],
          crop_region['y_max'], crop_region['x_max']]]
  output_image = tf.image.crop_and_resize(
      image, box_indices=[0], boxes=boxes, crop_size=crop_size)
  return output_image


def run_inference(movenet, image, crop_region, crop_size):
  """Runs model inferece on the cropped region.

  The function runs the model inference on the cropped region and updates the
  model output to the original image coordinate system.
  """
  image_height, image_width, _ = image.shape
  input_image = crop_and_resize(
    tf.expand_dims(image, axis=0), crop_region, crop_size=crop_size)
  # Run model inference.
  keypoints_with_scores = movenet(input_image)
  # Update the coordinates.
  for idx in range(17):
    keypoints_with_scores[0, 0, idx, 0] = (
        crop_region['y_min'] * image_height +
        crop_region['height'] * image_height *
        keypoints_with_scores[0, 0, idx, 0]) / image_height
    keypoints_with_scores[0, 0, idx, 1] = (
        crop_region['x_min'] * image_width +
        crop_region['width'] * image_width *
        keypoints_with_scores[0, 0, idx, 1]) / image_width
  return keypoints_with_scores


# Decision making ______________________________________________________________

def _get_torso_measurements(keypoints):
    """Return the torso angle, torso length and shoulder width.

    Coordinates are normalized (y, x).
    """

    left_shoulder = KEYPOINT_DICT["left_shoulder"]
    right_shoulder = KEYPOINT_DICT["right_shoulder"]
    left_hip = KEYPOINT_DICT["left_hip"]
    right_hip = KEYPOINT_DICT["right_hip"]

    # Confidence of the four torso points.
    confidence = min(
        keypoints[0, 0, left_shoulder, 2],
        keypoints[0, 0, right_shoulder, 2],
        keypoints[0, 0, left_hip, 2],
        keypoints[0, 0, right_hip, 2],
    )

    if confidence < MIN_CONFIDENCE:
        return None

    ls = keypoints[0, 0, left_shoulder, :2]
    rs = keypoints[0, 0, right_shoulder, :2]
    lh = keypoints[0, 0, left_hip, :2]
    rh = keypoints[0, 0, right_hip, :2]

    shoulder_center = (ls + rs) / 2
    hip_center = (lh + rh) / 2

    
    # Torso angle
    # 0°  = vertical
    # 90° = horizontal
    
    dy = shoulder_center[0] - hip_center[0]
    dx = shoulder_center[1] - hip_center[1]
    angle = np.degrees(np.arctan2(abs(dx), abs(dy)))

    torso_length = np.linalg.norm(shoulder_center - hip_center)

    shoulder_width = np.linalg.norm(ls - rs)

    # ------------------------------------------------------------------
    # Leg length
    #
    # Require all six leg keypoints to be confident. We don't want an
    # unreliable knee/ankle prediction to trigger this detector.
    # ------------------------------------------------------------------

    left_knee = KEYPOINT_DICT["left_knee"]
    right_knee = KEYPOINT_DICT["right_knee"]
    left_ankle = KEYPOINT_DICT["left_ankle"]
    right_ankle = KEYPOINT_DICT["right_ankle"]

    leg_indices = [
        left_hip,
        right_hip,
        left_knee,
        right_knee,
        left_ankle,
        right_ankle,
    ]

    legs_confident = all(
        keypoints[0, 0, index, 2] >= MIN_CONFIDENCE
        for index in leg_indices
    )

    legs_to_torso_ratio = None

    if legs_confident:
        lk = keypoints[0, 0, left_knee, :2]
        rk = keypoints[0, 0, right_knee, :2]
        la = keypoints[0, 0, left_ankle, :2]
        ra = keypoints[0, 0, right_ankle, :2]

        left_leg_length = (
            np.linalg.norm(lh - lk) +
            np.linalg.norm(lk - la)
        )

        right_leg_length = (
            np.linalg.norm(rh - rk) +
            np.linalg.norm(rk - ra)
        )

        average_leg_length = (
            left_leg_length + right_leg_length
        ) / 2

        legs_to_torso_ratio = (
            average_leg_length /
            (torso_length + 1e-6)
        )


    return {
        "angle": float(angle),
        "torso_length": float(torso_length),
        "shoulder_width": float(shoulder_width),
        "legs_to_torso_ratio": (
            float(legs_to_torso_ratio)
            if legs_to_torso_ratio is not None
            else None
        ),
        "torso_confidence": float(confidence),
    }



def _has_smooth_change(values, threshold):
    """Check for a clear monotonic change across several frames.

    We deliberately do NOT compare only the last two frames.

    For example:

        [10, 20, 35]  -> True
        [10, 35, 12]  -> False
        [10, 11, 12]  -> False if threshold is 5
        [10, 12, 35]  -> True

    The middle frame must move in the same direction as the complete
    change. This filters out isolated MoveNet prediction spikes.
    """

    if len(values) < CHANGE_WINDOW:
        return False

    values = values[-CHANGE_WINDOW:]

    total_change = values[-1] - values[0]

    # Not enough movement.
    if abs(total_change) < threshold:
        return False

    # Every step must have the same direction.
    direction = np.sign(total_change)

    for previous, current in zip(values[:-1], values[1:]):
        if np.sign(current - previous) != direction:
            return False

    return True


def _head_below_body(keypoints):
    """Return True if the head is clearly below another body part.

    Image coordinates use y increasing downward, so a larger y means
    lower in the image.

    Only reasonably confident body keypoints are considered.
    """

    nose_i = KEYPOINT_DICT["nose"]

    nose_confidence = keypoints[0, 0, nose_i, 2]

    if nose_confidence < MIN_CONFIDENCE:
        return False

    nose_y = keypoints[0, 0, nose_i, 0]

    body_parts = [
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    ]

    for part in body_parts:
        index = KEYPOINT_DICT[part]

        if keypoints[0, 0, index, 2] < MIN_CONFIDENCE:
            continue

        part_y = keypoints[0, 0, index, 0]

        if nose_y > part_y:
            return True

    return False


def analyze_keypoints(states: list) -> dict:
    """Detect a fall using torso orientation plus conservative temporal cues.

    A fall is detected when at least one of these conditions is met:

      1. The torso is approximately horizontal.
         This is the original detector.

      2. The torso is strongly foreshortened relative to the shoulders.
         This helps with falls toward/away from the camera.

      3. The torso angle changes substantially and consistently across
         several consecutive frames.

      4. The torso length changes substantially and consistently across
         several consecutive frames.

    The temporal checks intentionally require a monotonic evolution
    across multiple frames rather than reacting to one-frame noise.
    """

    # ------------------------------------------------------------------
    # Analyze the most recent frame.
    # ------------------------------------------------------------------

    current = _get_torso_measurements(states[-1])

    if current is None:
        return {
            "user_in_frame": False,
            "torso_angle": None,
            "torso_confidence": None,
            "torso_length": None,
            "torso_to_shoulders_ratio": None,
            "angle_change": None,
            "length_change": None,
            "fall_detected": False,
        }

    # Falls to the side
    horizontal_torso = (abs(90.0 - current["angle"]) <= ANGLE_THRESHOLD)

    # Falls towards or away

    torso_to_shoulders_ratio = (
        current["torso_length"] /
        (current["shoulder_width"] + 1e-6)
    )

    short_torso = (
        torso_to_shoulders_ratio <= TORSO_TO_SHOULDERS_RATIO
    )

    # ------------------------------------------------------------------
    # Temporal analysis
    #
    # We only need the last CHANGE_WINDOW frames. Since analyze_keypoints
    # is called on every processed frame, the same frames will naturally
    # be examined multiple times. That's something to make more efficient.
    # ------------------------------------------------------------------

    angle_change_detected = False
    length_change_detected = False

    angle_change = None
    length_change = None

    if len(states) >= CHANGE_WINDOW:

        recent_measurements = []

        for state in states[-CHANGE_WINDOW:]:
            measurement = _get_torso_measurements(state)

            if measurement is not None:
                recent_measurements.append(measurement)

        # Require all frames to contain a reliable torso.
        if len(recent_measurements) == CHANGE_WINDOW:

            angles = [
                measurement["angle"]
                for measurement in recent_measurements
            ]

            lengths = [
                measurement["torso_length"]
                for measurement in recent_measurements
            ]

            # ----------------------------------------------------------
            # Angle evolution
            # ----------------------------------------------------------

            angle_change = angles[-1] - angles[0]

            angle_change_detected = _has_smooth_change(
                angles,
                SUDDEN_ANGLE_CHANGE,
            )

            # ----------------------------------------------------------
            # Torso-length evolution
            # ----------------------------------------------------------

            length_change = lengths[-1] - lengths[0]

            # Normalize by the original length so that the threshold
            # does not depend strongly on how close the person is
            # to the camera.
            relative_length_change = abs(length_change) / (
                lengths[0] + 1e-6
            )

            length_change_detected = _has_smooth_change(
                lengths,
                lengths[0] * SUDDEN_LENGTH_CHANGE,
            )

    head_below_frames = sum(
        _head_below_body(state)
        for state in states
    )

    head_below_body = head_below_frames >= 2

    legs_too_long = (
        current["legs_to_torso_ratio"] is not None
        and current["legs_to_torso_ratio"] >= LEGS_TO_TORSO_RATIO
    )

    legs_too_long_frames = sum(
        measurement is not None
        and measurement["legs_to_torso_ratio"] is not None
        and measurement["legs_to_torso_ratio"] >= LEGS_TO_TORSO_RATIO
        for measurement in (
            _get_torso_measurements(state)
            for state in states
        )
    )

    fall_away = legs_too_long_frames >= 2


    # ------------------------------------------------------------------
    # Final decision
    # ------------------------------------------------------------------

    fall_reasons = []

    if horizontal_torso:
        fall_reasons.append("horizontal_torso")

    if short_torso:
        fall_reasons.append("short_torso")

    if angle_change_detected and length_change_detected:
        fall_reasons.append("sudden_angle_and_length_change")

    if head_below_body:
        fall_reasons.append("head_below_body")

    if fall_away:
        fall_reasons.append("legs_too_long_for_torso")

    fall_detected = len(fall_reasons) > 0


    return {
        "user_in_frame": True,

        # Current frame
        "torso_angle": round(current["angle"], 1),
        "torso_confidence": round(
            current["torso_confidence"], 2
        ),
        "torso_length": round(
            current["torso_length"], 3
        ),
        "torso_to_shoulders_ratio": round(
            torso_to_shoulders_ratio, 2
        ),

        # Temporal information
        "angle_change": (
            round(angle_change, 1)
            if angle_change is not None
            else None
        ),
        "length_change": (
            round(length_change, 3)
            if length_change is not None
            else None
        ),

        # Final decision
        "fall_detected": fall_detected,

        # Debug
        "fall_reasons": fall_reasons if fall_detected else None,
    }


# Main _________________________________________________________________________

def webcam_fall_detection():

    cap = cv2.VideoCapture(CAMERA_DEVICE)

    if not cap.isOpened():
        raise RuntimeError("Could not open webcam.")

    try:
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Could not read first frame.")

        image_height, image_width = frame.shape[:2]

        states = deque(maxlen=WINDOW)
        crop_region = init_crop_region(image_height, image_width)
        last_capture = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now = time.time()

            # Limit the FPS
            if now - last_capture < FRAME_INTERVAL:
                continue

            last_capture = now

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            tf_frame = tf.convert_to_tensor(rgb)

            keypoints_with_scores = run_inference(
                movenet,
                tf_frame,
                crop_region,
                crop_size=[input_size, input_size],
            )

            # Update crop region
            crop_region = determine_crop_region(
                keypoints_with_scores,
                image_height,
                image_width,
            )

            states.append(keypoints_with_scores)

            if len(states) >= 2:
                state = analyze_keypoints(list(states))
            else:
                state = {
                    "user_in_frame": False,
                    "fall_detected": False,
                }

            # Print fall reasons only when a fall is detected (debug on console)
            if state["fall_detected"]:
                print(
                    f"FALL DETECTED - reasons: "
                    f"{', '.join(state['fall_reasons'])}"
                )

            # Debug over the image ---------------------------------------------

            # This section displays the captured content with the inferenced keypoints and the state

            output = draw_prediction_on_image(
                rgb,
                keypoints_with_scores,
                crop_region=None,
                close_figure=True,
                output_image_height=image_height,
            )

            y = 40
            # We place each text a bit below the previous one

            for key, value in state.items():
                # Make the key more readable
                label = key.replace("_", " ")

                # Red for fall_detected=True, green otherwise
                color = (
                    (255, 30, 30) if key == "fall_detected" and value
                    else (50, 100, 255)
                )

                cv2.putText(
                    output,
                    f"{label}: {value}",
                    (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                )

                y += 30
              
            cv2.imshow(
                "Fall Detection",
                cv2.cvtColor(output.astype(np.uint8), cv2.COLOR_RGB2BGR),
            )

            # ----------------------------------------------------------------

            # Pressing 'q' stops the program
            if cv2.waitKey(1) == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
   webcam_fall_detection()
