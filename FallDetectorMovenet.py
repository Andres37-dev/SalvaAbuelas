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

MIN_CONFIDENCE = 0.30
"""Minimum confidence needed to consider a person as detected.
This value must be between 0 and 1.
- The larger it is, the harder it is to detect someone. That could reduce false positives in exchange for false negatives."""


ANGLE_THRESHOLD = 30.0
"""How close the torso angle must be to horizontal to mark as a possible fall.
- The larger it is, the easier it is to find a fall, decreasing false negatives.
0°   = vertical torso
90°  = horizontal torso
"""


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

def analyze_keypoints_old(states: list) -> dict[str, bool | None]:
    """Detect a fall based on torso orientation.

    Uses the latest frame in `states`.
    A fall is detected when:
      - the torso keypoints have sufficient confidence
      - the torso is approximately horizontal

    Keypoint coordinates are normalized:
        keypoint[..., 0] = y
        keypoint[..., 1] = x
        keypoint[..., 2] = confidence
    """

    # We only need the most recent frame for this basic detector.
    keypoints = states[-1]

    # Get indices
    left_shoulder = KEYPOINT_DICT["left_shoulder"]
    right_shoulder = KEYPOINT_DICT["right_shoulder"]
    left_hip = KEYPOINT_DICT["left_hip"]
    right_hip = KEYPOINT_DICT["right_hip"]

    # Confidence scores
    shoulder_conf = min(
        keypoints[0, 0, left_shoulder, 2],
        keypoints[0, 0, right_shoulder, 2],
    )

    hip_conf = min(
        keypoints[0, 0, left_hip, 2],
        keypoints[0, 0, right_hip, 2],
    )

    # Check that all four torso keypoints are reliable.
    torso_confident = (
        shoulder_conf >= MIN_CONFIDENCE
        and hip_conf >= MIN_CONFIDENCE
    )

    if not torso_confident:
        return {
            "user_in_frame": False,
            "torso_angle": None,
            "torso_confidence": min(shoulder_conf, hip_conf),
            "fall_detected": False,
        }

    # Extract coordinates.
    # They are stored as (y, x).
    ls = keypoints[0, 0, left_shoulder, :2]
    rs = keypoints[0, 0, right_shoulder, :2]
    lh = keypoints[0, 0, left_hip, :2]
    rh = keypoints[0, 0, right_hip, :2]

    # Midpoint of shoulders.
    shoulder_center = (ls + rs) / 2

    # Midpoint of hips.
    hip_center = (lh + rh) / 2

    # Vector from hips to shoulders.
    dy = shoulder_center[0] - hip_center[0]
    dx = shoulder_center[1] - hip_center[1]

    # Angle relative to vertical.
    #
    # atan2(dx, -dy) gives:
    #   0°  -> torso pointing upward
    #   90° -> torso horizontal
    #   180° -> torso pointing downward
    angle = np.degrees(np.arctan2(abs(dx), abs(dy)))

    # Distance from horizontal (90°).
    horizontal_error = abs(90.0 - angle)

    fall_detected = horizontal_error <= ANGLE_THRESHOLD

    return {
        "user_in_frame": True,
        "torso_angle": float(angle),
        "torso_confidence": float(min(shoulder_conf, hip_conf)),
        "fall_detected": fall_detected,
    }


def _pose_features(keypoints):
    """Extract a small set of interpretable geometric features."""

    # ------------------------------------------------------------------
    # Keypoint indices
    # ------------------------------------------------------------------

    ls_i = KEYPOINT_DICT["left_shoulder"]
    rs_i = KEYPOINT_DICT["right_shoulder"]
    lh_i = KEYPOINT_DICT["left_hip"]
    rh_i = KEYPOINT_DICT["right_hip"]
    lk_i = KEYPOINT_DICT["left_knee"]
    rk_i = KEYPOINT_DICT["right_knee"]
    la_i = KEYPOINT_DICT["left_ankle"]
    ra_i = KEYPOINT_DICT["right_ankle"]
    nose_i = KEYPOINT_DICT["nose"]

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    torso_confidence = min(
        keypoints[0, 0, ls_i, 2],
        keypoints[0, 0, rs_i, 2],
        keypoints[0, 0, lh_i, 2],
        keypoints[0, 0, rh_i, 2],
    )

    if torso_confidence < MIN_CONFIDENCE:
        return None

    # ------------------------------------------------------------------
    # Main body points
    # ------------------------------------------------------------------

    ls = keypoints[0, 0, ls_i, :2]
    rs = keypoints[0, 0, rs_i, :2]
    lh = keypoints[0, 0, lh_i, :2]
    rh = keypoints[0, 0, rh_i, :2]

    shoulder_center = (ls + rs) / 2
    hip_center = (lh + rh) / 2

    # ------------------------------------------------------------------
    # 1. Torso angle
    #
    # 0°  = vertical
    # 90° = horizontal
    # ------------------------------------------------------------------

    torso_vector = shoulder_center - hip_center

    dy = torso_vector[0]
    dx = torso_vector[1]

    torso_angle = np.degrees(
        np.arctan2(abs(dx), abs(dy))
    )

    # ------------------------------------------------------------------
    # 2. Body bounding box
    #
    # Use all sufficiently confident keypoints.
    # ------------------------------------------------------------------

    points = []

    for i in range(17):
        if keypoints[0, 0, i, 2] >= MIN_CONFIDENCE:
            y, x = keypoints[0, 0, i, :2]
            points.append((x, y))

    if len(points) < 4:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    bbox_width = max(xs) - min(xs)
    bbox_height = max(ys) - min(ys)

    # Width / height.
    #
    # < 1  -> mostly vertical
    # > 1  -> mostly horizontal
    body_aspect_ratio = bbox_width / (bbox_height + 1e-6)

    # ------------------------------------------------------------------
    # 3. Foreshortening ratio
    #
    # Estimate actual body length from the skeleton, then compare it
    # with its projected height in the image.
    #
    # A person falling toward/away from the camera can have a short
    # projected body height even though their skeleton is still long.
    # ------------------------------------------------------------------

    def segment_length(i1, i2):
        p1 = keypoints[0, 0, i1, :2]
        p2 = keypoints[0, 0, i2, :2]

        if (keypoints[0, 0, i1, 2] < MIN_CONFIDENCE or
                keypoints[0, 0, i2, 2] < MIN_CONFIDENCE):
            return None

        return np.linalg.norm(p1 - p2)

    segments = [
        segment_length(ls_i, lh_i),
        segment_length(rs_i, rh_i),
        segment_length(lh_i, lk_i),
        segment_length(rh_i, rk_i),
        segment_length(lk_i, la_i),
        segment_length(rk_i, ra_i),
    ]

    if all(length is not None for length in segments):
        body_length = (
            (segments[0] + segments[1]) / 2 +
            (segments[2] + segments[3]) / 2 +
            (segments[4] + segments[5]) / 2
        )

        foreshortening_ratio = (
            body_length / (bbox_height + 1e-6)
        )
    else:
        body_length = None
        foreshortening_ratio = None

    # ------------------------------------------------------------------
    # 4. Hip position
    #
    # Used to detect rapid downward movement.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 5. Nose position
    #
    # Also useful as a simple indication of downward movement.
    # ------------------------------------------------------------------

    nose_y = None

    if keypoints[0, 0, nose_i, 2] >= MIN_CONFIDENCE:
        nose_y = float(keypoints[0, 0, nose_i, 0])

    return {
        "torso_angle": float(torso_angle),
        "body_aspect_ratio": float(body_aspect_ratio),
        "foreshortening_ratio": (
            float(foreshortening_ratio)
            if foreshortening_ratio is not None
            else None
        ),
        "hip_y": float(hip_center[0]),
        "nose_y": nose_y,
        "torso_confidence": float(torso_confidence),
    }


def analyze_keypoints(states: list) -> dict:
    """Detect a fall from body geometry and short-term motion.

    The detector intentionally uses a small number of interpretable
    features:

      - torso angle
      - body bounding-box aspect ratio
      - skeleton/body foreshortening
      - hip/head movement
      - persistence across recent frames

    The important distinction is between:

        "the person is lying"

    and:

        "the person has recently transitioned into a lying-like pose"

    The latter is treated as a fall candidate.
    """

    if len(states) < 2:
        return {
            "user_in_frame": False,
            "torso_angle": None,
            "torso_confidence": None,
            "body_aspect_ratio": None,
            "foreshortening_ratio": None,
            "fall_score": 0,
            "fall_detected": False,
        }

    # Extract features for the complete buffer.
    features = []

    for keypoints in states:
        pose = _pose_features(keypoints)

        if pose is not None:
            features.append(pose)

    # Not enough reliable frames.
    if len(features) < 2:
        return {
            "user_in_frame": False,
            "torso_angle": None,
            "torso_confidence": None,
            "body_aspect_ratio": None,
            "foreshortening_ratio": None,
            "fall_score": 0,
            "fall_detected": False,
        }

    current = features[-1]
    previous = features[-2]

    # ------------------------------------------------------------------
    # Current posture
    # ------------------------------------------------------------------

    horizontal_torso = current["torso_angle"] >= 60.0

    horizontal_body = (
        current["body_aspect_ratio"] >= 1.20
    )

    foreshortened = (
        current["foreshortening_ratio"] is not None
        and current["foreshortening_ratio"] >= 1.50
    )

    # ------------------------------------------------------------------
    # Temporal changes
    # ------------------------------------------------------------------

    # Compare with the oldest reliable frame in the buffer.
    first = features[0]

    aspect_change = (
        current["body_aspect_ratio"] -
        first["body_aspect_ratio"]
    )

    foreshortening_change = None

    if (
        current["foreshortening_ratio"] is not None
        and first["foreshortening_ratio"] is not None
    ):
        foreshortening_change = (
            current["foreshortening_ratio"] -
            first["foreshortening_ratio"]
        )

    # Hip movement toward the bottom of the image.
    hip_drop = current["hip_y"] - first["hip_y"]

    # Head movement toward the bottom of the image.
    head_drop = None

    if (
        current["nose_y"] is not None
        and first["nose_y"] is not None
    ):
        head_drop = current["nose_y"] - first["nose_y"]

    # ------------------------------------------------------------------
    # Did the person actually change posture?
    #
    # This is important. Someone who was already lying down should not
    # immediately be considered to have fallen.
    # ------------------------------------------------------------------

    posture_changed = (
        aspect_change >= 0.30
        or (
            foreshortening_change is not None
            and foreshortening_change >= 0.30
        )
        or horizontal_torso and first["torso_angle"] < 45.0
    )

    rapid_downward_motion = (
        hip_drop >= 0.10
        or (
            head_drop is not None
            and head_drop >= 0.10
        )
    )

    # ------------------------------------------------------------------
    # Score the current frame.
    #
    # Keep this deliberately simple so it is easy to tune.
    # ------------------------------------------------------------------

    fall_score = 0

    if horizontal_torso:
        fall_score += 2

    if horizontal_body:
        fall_score += 2

    if foreshortened:
        fall_score += 2

    if posture_changed:
        fall_score += 2

    if rapid_downward_motion:
        fall_score += 1

    # ------------------------------------------------------------------
    # Temporal confirmation.
    #
    # Require the current and previous frames to look suspicious.
    # At 3 FPS this corresponds to roughly 0.33 seconds of persistence.
    # ------------------------------------------------------------------

    previous_horizontal = (
        previous["torso_angle"] >= 60.0
        or previous["body_aspect_ratio"] >= 1.20
        or (
            previous["foreshortening_ratio"] is not None
            and previous["foreshortening_ratio"] >= 1.50
        )
    )

    fall_candidate = (
        fall_score >= 4
        and posture_changed
    )

    fall_confirmed = (
        fall_candidate
        and previous_horizontal
    )

    return {
        "user_in_frame": True,

        # Current geometric state
        "torso_angle": round(current["torso_angle"], 1),
        "torso_confidence": round(
            current["torso_confidence"], 2
        ),
        "body_aspect_ratio": round(
            current["body_aspect_ratio"], 2
        ),
        "foreshortening_ratio": (
            round(current["foreshortening_ratio"], 2)
            if current["foreshortening_ratio"] is not None
            else None
        ),

        # Temporal/debug information
        "aspect_change": round(aspect_change, 2),
        "hip_drop": round(hip_drop, 2),
        "fall_score": fall_score,

        "fall_detected": fall_confirmed,
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

            states.append(keypoints_with_scores)

            if len(states) >= 2:
                state = analyze_keypoints(list(states))
            else:
                state = {
                    "user_in_frame": False,
                    "fall_detected": False,
                }


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