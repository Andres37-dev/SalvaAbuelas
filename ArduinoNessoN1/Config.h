#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino_Nesso_N1.h>
#include <WiFi.h>
#include <PubSubClient.h>

#define FIRMWARE_VERSION "v5.0.1"
#define SERIAL_ENABLED true

#ifndef BEEP_PIN // just in case since it once gave me problems
#define BEEP_PIN 11
#endif

extern NessoBattery battery;
extern NessoDisplay display;

extern WiFiClient wifiClient;
extern PubSubClient mqttClient;


constexpr const char* wifi_ssid     = "...";
constexpr const char* wifi_password = "...";

constexpr const char* MQTT_BROKER    = "?????";
constexpr const int   MQTT_PORT      = 1883;
constexpr const char* MQTT_CLIENT_ID = "Nesso";

constexpr const char* MQTT_TOPIC_STATUS  = "Nesso/status";
constexpr const char* MQTT_TOPIC_COMMAND = "Nesso/command";
constexpr const char* MQTT_TOPIC_EVENTS  = "Nesso/events";


const unsigned int SCREEN_ROTATION = 3; // {0..3} 0 vertical KEY1 on the button, keeps rotating 90º to the right
const unsigned int SCREEN_HEIGHT = (SCREEN_ROTATION % 2 == 0) ? 240 : 135;
const unsigned int SCREEN_WIDTH  = (SCREEN_ROTATION % 2 == 1) ? 135 : 240;


// ---- Constants ----
// --- Entry thresholds: what counts as "something unusual just happened", worth opening an evidence-gathering episode.
//     These are intentionally loose -- a loose entry condition costs nothing (it just starts collecting data), all the
//     real decision-making happens in the scoring step below.
const float FREE_FALL_ENTRY_G    = 0.60f;  // unloading / near weightlessness
const float IMPACT_SPIKE_ENTRY_G = 1.80f;  // catches a hard spike even with no free-fall phase first (e.g. a stumble, not a drop)
const float GYRO_ENTRY_DPS       = 200.0f; // rotation burst; high enough to avoid triggering on ordinary rotation

// --- Evidence-gathering window: how long we watch after entry before checking for stillness. Elderly falls (grabbing at
//     furniture, a slow stumble) can take longer to resolve than a clean fast fall.
const unsigned long EVENT_WINDOW_MS = 1500;

// How soon after the free-fall trough the impact spike must land to count as ONE coherent fall event (drop, then hit) rather than two unrelated accel
// excursions that happened to land inside the same evidence window. Real falls from standing/seated height land well inside this
const unsigned long FALL_IMPACT_WINDOW_MS = 600;

// When free-fall + impact don't correlate in time (or only one of them happened at all), orientation/vswing scoring -- the two heaviest-weighted
// signals -- gets scaled down by this factor instead of full strength. Doesn't zero them out: a fall broken by grabbing furniture can still show
// impact without a clean free-fall trough.
const float UNCORRELATED_EVIDENCE_FACTOR = 0.5f;

// --- Stillness detection. We track the LONGEST CONTINUOUS streak of "quiet" samples rather than averaging over a fixed window,
//     so a brief post-impact thrash doesn't poison the measurement.
const float QUIET_ACCEL_BAND_G = 0.12f;  // |accel - 1g| under this = quiet
const float QUIET_GYRO_DPS     = 15.0f;  // gyro under this = quiet
const unsigned long STILLNESS_REQUIRED_MS = 500;   // streak needed for full credit
const unsigned long STILLNESS_MAX_WAIT_MS = 4000;  // give up waiting after this

// --- Scoring ranges: (no-credit value, full-credit value, max points)
//     Values are interpolated linearly between the two bounds and
//     clamped to [0, max points]. Direction doesn't matter --
//     free-fall intentionally runs "backwards" (lower g = more score).
//
//     Rotation rate and "did it eventually go still" are both CHEAP signals -- rotating the device by hand and setting it back down
//     produces a fast gyro spike and, once you stop, guaranteed stillness, with no fall involved at all. VERTICAL_SWING is the
//     strongest signal we have (see below) and carries the most weight; orientation change is the next most reliable. Raw
//     accel magnitude (free-fall/impact) and rotation are kept only as weak supporting signals now.
const float FREEFALL_FLOOR_G   = 0.80f, FREEFALL_CEIL_G   = 0.30f, FREEFALL_MAX_PTS   = 10.0f;
const float IMPACT_FLOOR_G     = 1.50f, IMPACT_CEIL_G     = 3.20f, IMPACT_MAX_PTS     = 10.0f;

// A large orientation change is useful evidence ONLY when there is also a real acceleration anomaly. This prevents a pure rotation from being
// scored as a fall just because it ended in a still orientation.
const float FALL_FREEFALL_GATE_G = 0.65f;
const float FALL_IMPACT_GATE_G   = 1.50f;
const float ROTATION_FLOOR_DPS = 80.0f, ROTATION_CEIL_DPS = 500.0f, ROTATION_MAX_PTS  = 5.0f;
const float ORIENT_FLOOR_DEG   = 15.0f, ORIENT_CEIL_DEG   = 70.0f, ORIENT_MAX_PTS     = 30.0f;
const float STILLNESS_MAX_PTS  = 15.0f;

// --- Vertical swing: the strongest fall-specific signal.
//     Raw accelerometer readings are in the SENSOR's local frame, which rotates with the device -- so a fast hand-twist can look like a
//     big acceleration event even though the device never actually moved through space. To fix that, we use the roll/pitch we're
//     already tracking to work out which way "down" currently points, and project the raw reading onto THAT axis instead of a fixed
//     sensor axis. The result stays near zero for any motion that's pure rotation (twisting in your hand), because the projection
//     rotates right along with the device. A real fall is different:
//     during the drop this reads close to -1g (falling, unloaded), and the impact that stops the fall registers as a strong
//     positive spike, because a real impact IS aligned with gravity (the ground is what stops you falling). We track the full swing
//     (highest minus lowest value seen) across the episode, since a real fall shows both ends of that range and a rotation shows
//     neither.
const float VSWING_FLOOR_G = 0.30f, VSWING_CEIL_G = 2.50f, VSWING_MAX_PTS = 30.0f;

// --- The single decision threshold. At or above this score, the confirmation grace period ALWAYS activates. Below it, the
//     episode is ignored. Lower catches more soft falls but nags more often; higher does the opposite.
const float CONFIRMATION_THRESHOLD_PCT = 55.0f;

// How long the "are you OK?" grace period lasts before auto-escalating.
const unsigned long CONFIRMATION_GRACE_MS = 20000;

// Buzzer behavior. BEEP_PIN (GPIO11) comes from the Nesso N1 board definition, not this sketch.
const unsigned int CONFIRM_BEEP_FREQ_HZ    = 2000;
const unsigned int CONFIRM_BEEP_DURATION_MS = 150;
const unsigned long CONFIRM_BEEP_INTERVAL_MS = 500;

const unsigned int ALARM_BEEP_FREQ_HZ     = 1000;
const unsigned int ALARM_BEEP_DURATION_MS = 1000;
const unsigned long ALARM_BEEP_INTERVAL_MS = 1200;

const unsigned long KEY_DEBOUNCE_MS     = 40;
const unsigned int KEY_BEEP_FREQ_HZ     = 500;
const unsigned int KEY_BEEP_DURATION_MS = 100;

const unsigned long MANUAL_ALARM_MS = 3000; // time needed to trigger manual alarm


#endif
