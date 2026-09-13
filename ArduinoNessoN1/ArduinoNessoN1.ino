#include <Arduino_Nesso_N1.h>
#include <math.h>
#include <algorithm>
#include "Config.h"
#include "Screens.h"


NessoBattery battery;
NessoDisplay display;
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);


#if SERIAL_ENABLED
  #define DBG_BEGIN(...)   Serial.begin(__VA_ARGS__)
  #define DBG_PRINT(...)   Serial.print(__VA_ARGS__)
  #define DBG_PRINTLN(...) Serial.println(__VA_ARGS__)
#else
  #define DBG_BEGIN(...)
  #define DBG_PRINT(...)
  #define DBG_PRINTLN(...)
#endif


void startEvent();
void trackEpisodeExtremes(float accelMag, float gyroMag, float verticalAccel);
void enterStillnessWait();
void resolveEpisode();
void startConfirmation(float score);
void triggerAlarm(float score);
void resetToNormal();
bool keyPressed(ExpanderPin key);
void drawVersionLabel(uint16_t color);

enum FallState {
  NORMAL,            // watching for anything unusual
  EVENT_DETECTED,     // unusual motion seen, gathering evidence
  STILLNESS_WAIT,     // evidence window done, watching for the person to settle
  CONFIRMING,         // score reached threshold -- grace period, KEY1 cancels
  ALARM               // grace period expired unconfirmed -- full alarm
};

FallState state = NORMAL;

bool confirmationFromMQTT = false;
bool alreadyConfirming = false;

unsigned long batteryScreenStartTime = 0;
bool nonBatteryScreenOn = false;
bool batteryScreenOn = false;

// Emergency button press
unsigned long firstButtonPress = 0;
bool buttonStillPressed = false;
bool manualTriggerFiredThisHold = false;

// Orientation (complementary filter), updated every loop regardless of state
float roll = 0.0f;
float pitch = 0.0f;
unsigned long previousMicros = 0;

// Latest sensor samples. Accel and gyro become available somewhat
// independently on this hardware (separate data-ready flags), so we
// keep the last known value of each and update whichever is fresh.
float ax = 0.0f, ay = 0.0f, az = 1.0f;
float gx = 0.0f, gy = 0.0f, gz = 0.0f;

// Episode evidence (reset at the start of each EVENT_DETECTED)
unsigned long episodeStartTime = 0;
unsigned long stillnessWaitStart = 0;
unsigned long quietStreakStart = 0;
unsigned long longestQuietStreakMs = 0;
float episodeMinAccel = 1.0f;
float episodeMaxAccel = 1.0f;
float episodeMaxGyro = 0.0f;
float episodeMinVerticalAccel = 0.0f;
float episodeMaxVerticalAccel = 0.0f;
float initialRoll = 0.0f;
float initialPitch = 0.0f;

// Result of the most recently resolved episode (shown on the idle screen)
float lastFallScore = -1.0f;

// Confirmation ("are you OK?") state
unsigned long confirmStartTime = 0;
unsigned long lastConfirmBeep = 0;
int lastDisplayedCountdown = -1;

// Alarm re-beep state
unsigned long lastAlarmBeep = 0;

// KEY1 debounce state
bool key1LastRaw = HIGH;
unsigned long key1LastChangeTime = 0;

float accelMagHistory[3] = {1.0f, 1.0f, 1.0f};
float gyroMagHistory[3]  = {0.0f, 0.0f, 0.0f};

unsigned long episodeMinAccelTime = 0;
unsigned long episodeMaxAccelTime = 0;


// ============================================================
// Utility functions
// ============================================================
float vectorMagnitude(float x, float y, float z) {
  return sqrtf(x * x + y * y + z * z);
}

// Keep angle between -180 and +180 degrees
float normalizeAngle(float angle) {
  while (angle > 180.0f) angle -= 360.0f;
  while (angle < -180.0f) angle += 360.0f;
  return angle;
}

// Linear interpolation between floorVal (0 points) and ceilingVal (max
// points), clamped. ceilingVal may be less than floorVal for signals
// where a LOWER reading means MORE evidence (e.g. free-fall).
float scoreFromRange(float value, float floorVal, float ceilingVal, float maxPoints) {
  float t;
  if (ceilingVal >= floorVal) {
    t = (value - floorVal) / (ceilingVal - floorVal);
  } else {
    t = (floorVal - value) / (floorVal - ceilingVal);
  }
  if (t < 0.0f) t = 0.0f;
  if (t > 1.0f) t = 1.0f;
  return t * maxPoints;
}

// Median-of-3 filter: kills a single noisy IMU sample before it can set a
// bogus episode extreme (or open an episode that shouldn't exist at all).
// Adds ~2 samples of lag, negligible next to EVENT_WINDOW_MS.
float medianOf3(float a, float b, float c) {
  return std::max(std::min(a, b), std::min(std::max(a, b), c));
}

float filterAccelMagnitude(float raw) {
  accelMagHistory[0] = accelMagHistory[1];
  accelMagHistory[1] = accelMagHistory[2];
  accelMagHistory[2] = raw;
  return medianOf3(accelMagHistory[0], accelMagHistory[1], accelMagHistory[2]);
}

float filterGyroMagnitude(float raw) {
  gyroMagHistory[0] = gyroMagHistory[1];
  gyroMagHistory[1] = gyroMagHistory[2];
  gyroMagHistory[2] = raw;
  return medianOf3(gyroMagHistory[0], gyroMagHistory[1], gyroMagHistory[2]);
}

// Aux func to make key1 readings easier (debounce + flanc asc + pito)
bool keyPressed(ExpanderPin key) {
  bool raw = digitalRead(key);
  bool justPressed = false;

  if (raw != key1LastRaw) {
    if (millis() - key1LastChangeTime > KEY_DEBOUNCE_MS) {
      if (raw == LOW && key1LastRaw == HIGH) { // flanc asc
        justPressed = true;
        //tone(BEEP_PIN, KEY_BEEP_FREQ_HZ, KEY_BEEP_DURATION_MS);
      }
      key1LastRaw = raw;
      key1LastChangeTime = millis();
    }
  }
  return justPressed;
}

// ============================================================
// Calculate orientation from accelerometer
// ============================================================
void calculateAccelerometerAngles(float accX, float accY, float accZ, float &newRoll, float &newPitch) {
  newRoll = atan2f(accY, accZ) * 180.0f / PI;
  newPitch = atan2f(-accX, sqrtf(accY * accY + accZ * accZ)) * 180.0f / PI;
}


// ============================================================
// Complementary filter
// ============================================================
void updateOrientation(float accX, float accY, float accZ, float gyrX, float gyrY, float dt) {
  float accelRoll, accelPitch;
  calculateAccelerometerAngles(accX, accY, accZ, accelRoll, accelPitch);

  float gyroRoll = roll + gyrX * dt;
  float gyroPitch = pitch + gyrY * dt;

  // Gyroscope: good short-term response.
  // Accelerometer: corrects long-term drift.
  const float alpha = 0.98f;
  roll = alpha * gyroRoll + (1.0f - alpha) * accelRoll;
  pitch = alpha * gyroPitch + (1.0f - alpha) * accelPitch;
}


// ============================================================
// How much has orientation moved since the episode started?
// Returns the larger of the roll/pitch swings, in degrees.
// ============================================================
float orientationChangeDegrees() {
  float rollChange = fabsf(normalizeAngle(roll - initialRoll));
  float pitchChange = fabsf(normalizeAngle(pitch - initialPitch));
  return std::max(rollChange, pitchChange);
}


// ============================================================
// Vertical (gravity-aligned) acceleration component. See the
// VSWING_* comment above the tunable constants for the reasoning.
// Uses the CURRENT fused roll/pitch, so it tracks "down" as the
// device rotates instead of reading a fixed sensor axis.
// ============================================================
float verticalAccelComponent(float accX, float accY, float accZ, float rollDeg, float pitchDeg) {
  float r = rollDeg * PI / 180.0f;
  float p = pitchDeg * PI / 180.0f;

  // Reference "at-rest" direction (what the accelerometer reads at 1g)
  // reconstructed from the current orientation estimate.
  float refX = -sinf(p);
  float refY = sinf(r) * cosf(p);
  float refZ = cosf(r) * cosf(p);

  return (accX * refX + accY * refY + accZ * refZ) - 1.0f;
}


// ============================================================
// Episode lifecycle
// ============================================================
void startEvent() {
  state = EVENT_DETECTED;
  episodeStartTime = millis();

  initialRoll = roll;
  initialPitch = pitch;

  episodeMinAccel = 1.0f;
  episodeMaxAccel = 1.0f;
  episodeMaxGyro = 0.0f;
  episodeMinVerticalAccel = 0.0f;
  episodeMaxVerticalAccel = 0.0f;

  episodeMinAccelTime = 0;
  episodeMaxAccelTime = 0;

  DBG_PRINTLN();
  DBG_PRINTLN(">>> EVENT DETECTED - gathering evidence");
  DBG_PRINT("Initial orientation: roll=");
  DBG_PRINT(initialRoll);
  DBG_PRINT(" pitch=");
  DBG_PRINTLN(initialPitch);
}

// Called every sample during EVENT_DETECTED / STILLNESS_WAIT and just before starting the event in NORMAL 
void trackEpisodeExtremes(float accelMag, float gyroMag, float verticalAccel) {
  unsigned long now = millis();
  if (accelMag < episodeMinAccel) { episodeMinAccel = accelMag; episodeMinAccelTime = now; }
  if (accelMag > episodeMaxAccel) { episodeMaxAccel = accelMag; episodeMaxAccelTime = now; }
  episodeMaxGyro = std::max(episodeMaxGyro, gyroMag);
  episodeMinVerticalAccel = std::min(episodeMinVerticalAccel, verticalAccel);
  episodeMaxVerticalAccel = std::max(episodeMaxVerticalAccel, verticalAccel);
}

void enterStillnessWait() {
  state = STILLNESS_WAIT;
  stillnessWaitStart = millis();
  quietStreakStart = 0;
  longestQuietStreakMs = 0;
  DBG_PRINTLN(">>> Evidence window complete, watching for stillness...");
}

// Compute the final 0-100% score and decide what to do about it.
void resolveEpisode() {
  float orientationChangeDeg = orientationChangeDegrees();

  float freeFallScore  = scoreFromRange(episodeMinAccel, FREEFALL_FLOOR_G, FREEFALL_CEIL_G, FREEFALL_MAX_PTS);
  float impactScore    = scoreFromRange(episodeMaxAccel, IMPACT_FLOOR_G, IMPACT_CEIL_G, IMPACT_MAX_PTS);
  float rotationScore  = scoreFromRange(episodeMaxGyro, ROTATION_FLOOR_DPS, ROTATION_CEIL_DPS, ROTATION_MAX_PTS);
  float stillnessScore = scoreFromRange((float)longestQuietStreakMs, 0.0f, (float)STILLNESS_REQUIRED_MS, STILLNESS_MAX_PTS);
  float verticalSwing  = episodeMaxVerticalAccel - episodeMinVerticalAccel;

  bool hasFreefall = episodeMinAccel < FALL_FREEFALL_GATE_G;
  bool hasImpact   = episodeMaxAccel > FALL_IMPACT_GATE_G;

  // The textbook fall signature: unloading, THEN a hard stop, close enough
  // together in time to be the same event rather than two coincidental
  // accel excursions inside the same evidence window.
  bool freefallThenImpact = hasFreefall && hasImpact && episodeMaxAccelTime > episodeMinAccelTime &&
      (episodeMaxAccelTime - episodeMinAccelTime) <= FALL_IMPACT_WINDOW_MS;

  bool hasFallAccelerationEvidence = hasFreefall || hasImpact;

  // full credit for the two heaviest-weighted signals only goes to
  // a correlated freefall->impact pair. A lone excursion, or two that don't
  // line up in time, still counts as evidence -- just at reduced strength.
  float evidenceConfidence = freefallThenImpact ? 1.0f : UNCORRELATED_EVIDENCE_FACTOR;
  
  float orientationScore = 0.0f;
  float vswingScore = 0.0f;

  if (hasFallAccelerationEvidence) {
    orientationScore = scoreFromRange(orientationChangeDeg, ORIENT_FLOOR_DEG, ORIENT_CEIL_DEG, ORIENT_MAX_PTS) * evidenceConfidence;
    vswingScore = scoreFromRange(verticalSwing, VSWING_FLOOR_G, VSWING_CEIL_G, VSWING_MAX_PTS) * evidenceConfidence;
  }

  float total = freeFallScore + impactScore + rotationScore + orientationScore + stillnessScore + vswingScore;
  if (total > 100.0f) total = 100.0f;
  if (total < 0.0f) total = 0.0f;

  lastFallScore = total;

  DBG_PRINTLN(); DBG_PRINTLN("Episode analysis:");
  DBG_PRINT("  min accel="); DBG_PRINT(episodeMinAccel, 2); DBG_PRINT("g ("); DBG_PRINT(freeFallScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  max accel="); DBG_PRINT(episodeMaxAccel, 2); DBG_PRINT("g ("); DBG_PRINT(impactScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  max gyro=");  DBG_PRINT(episodeMaxGyro, 1); DBG_PRINT(" dps ("); DBG_PRINT(rotationScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  orientation change="); DBG_PRINT(orientationChangeDeg, 1); DBG_PRINT(" deg ("); DBG_PRINT(orientationScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  longest quiet streak="); DBG_PRINT(longestQuietStreakMs); DBG_PRINT("ms ("); DBG_PRINT(stillnessScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  vertical swing="); DBG_PRINT(verticalSwing, 2); DBG_PRINT("g ("); DBG_PRINT(vswingScore, 1); DBG_PRINTLN(" pts)");
  DBG_PRINT("  freefall->impact gap=");
  if (episodeMaxAccelTime > episodeMinAccelTime) { DBG_PRINT(episodeMaxAccelTime - episodeMinAccelTime); DBG_PRINTLN("ms"); }
  else { DBG_PRINTLN("n/a"); }
  DBG_PRINT("  correlated="); DBG_PRINT(freefallThenImpact ? "YES" : "NO"); DBG_PRINT(" (confidence x"); DBG_PRINT(evidenceConfidence, 2); DBG_PRINTLN(")");
  DBG_PRINT("  TOTAL SCORE: "); DBG_PRINT(total, 0); DBG_PRINTLN("%");

  if (total >= CONFIRMATION_THRESHOLD_PCT) {
    if (!alreadyConfirming) {
      alreadyConfirming = true;
      startConfirmation(total);
    }
  } else {
    DBG_PRINTLN(">>> Below confirmation threshold - resuming normal monitoring.");
    resetToNormal();
  }
}


// ============================================================
// Confirmation ("Are you OK?") grace period
// ============================================================
void startConfirmation(float score) {
  state = CONFIRMING;
  confirmStartTime = millis();
  lastConfirmBeep = 0;
  lastDisplayedCountdown = -1;

  DBG_PRINT(">>> POSSIBLE FALL ("); DBG_PRINT(score, 0); DBG_PRINTLN("%) - awaiting confirmation");

  display.wakeup();
  nonBatteryScreenOn = true;
  confirmationScreen((int) score);
}


// ============================================================
// Trigger fall alarm
// ============================================================
void triggerAlarm(float score) {
  mqttClient.publish(MQTT_TOPIC_EVENTS, "ANOMALIA_DETECTADA");

  state = ALARM;
  lastAlarmBeep = 0;

  DBG_PRINTLN();
  DBG_PRINTLN("================================");
  DBG_PRINT("   FALL DETECTED! ("); DBG_PRINT(score, 0); DBG_PRINTLN("%)");
  DBG_PRINTLN("================================");

  display.wakeup();
  nonBatteryScreenOn = true;
  alarmScreen((int) score);
}


// ============================================================
// Reset detector to idle / monitoring
// ============================================================
void resetToNormal() {
  state = NORMAL;
  noTone(BEEP_PIN);

  nonBatteryScreenOn = batteryScreenOn = false;
  display.sleep();

  DBG_PRINTLN(">>> RESET -> NORMAL");
}


// ============================================================
// MQTT helpers
// ============================================================
void ensureMqttConnected() {
  mqttClient.loop();

  if (!mqttClient.connected()) {
    static unsigned long lastReconnectAttempt = 0;
    if (millis() - lastReconnectAttempt > 2000) {   // don't retry more than every 2s
      lastReconnectAttempt = millis();
      if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_TOPIC_STATUS, 0, true, "OFFLINE")) {
        mqttClient.publish(MQTT_TOPIC_STATUS, "ONLINE", true);
        mqttClient.subscribe(MQTT_TOPIC_COMMAND);
      }
    }
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  if (String(topic) == MQTT_TOPIC_COMMAND) {
    if (msg == "START_VIBRATE") {
      confirmationFromMQTT = true; 
      if (!alreadyConfirming) {
        alreadyConfirming = true;
        startConfirmation(100);
      }
    }
    else if (msg == "STOP_VIBRATE") noTone(BEEP_PIN);
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  DBG_BEGIN(115200);
  delay(1000);

  battery.begin();
  display.begin();

  DBG_PRINTLN();
  DBG_PRINTLN("==============================");
  DBG_PRINT("Nesso N1 Fall Detector "); DBG_PRINTLN(FIRMWARE_VERSION);
  DBG_PRINTLN("==============================");

  pinMode(BEEP_PIN, OUTPUT);
  pinMode(KEY1, INPUT_PULLUP);

  if (!IMU.begin()) {
    DBG_PRINTLN("ERROR: IMU not available!");
    display.fillScreen(TFT_BLACK);
    display.setTextColor(TFT_RED);
    display.setTextSize(2);
    display.setCursor(10, 10);
    display.println("IMU ERROR!");
    while (true) {
      delay(100);
    }
  }
  DBG_PRINTLN("BMI270 IMU detected.");

  WiFi.begin(wifi_ssid, wifi_password);
  int tries = 0; bool tryInfinitely = true;
  while (WiFi.status() != WL_CONNECTED && (tryInfinitely || (tries < 200 && !tryInfinitely))) { 
    delay(200); 
    DBG_PRINT("."); 
    tries++;
  }
  if (tries < 200) { 
    DBG_PRINTLN("WiFi connected.");
  } 
  else { 
    DBG_PRINTLN("!!! WiFi not connected !!!");
  }

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  resetToNormal();
  previousMicros = micros();
  delay(500);
}


// ============================================================
// LOOP
// ============================================================
void loop() {
  bool haveNewAccel = false;

  if (IMU.accelerationAvailable()) {
    IMU.readAcceleration(ax, ay, az);
    haveNewAccel = true;
  }
  if (IMU.gyroscopeAvailable()) {
    IMU.readGyroscope(gx, gy, gz);
  }

  if (!haveNewAccel) {
    return;  // wait for the next fresh accelerometer sample
  }

  float accelerationMagnitude = filterAccelMagnitude(vectorMagnitude(ax, ay, az));
  float gyroMagnitude = filterGyroMagnitude(vectorMagnitude(gx, gy, gz));

  unsigned long nowMicros = micros();
  float dt = (nowMicros - previousMicros) / 1000000.0f;
  previousMicros = nowMicros;

  if (dt <= 0.0f || dt > 0.1f) dt = 0.01f;

  updateOrientation(ax, ay, az, gx, gy, dt);

  // Gravity-relative vertical acceleration -- see the VSWING_* comment
  // near the tunable constants. Needs the JUST-updated roll/pitch, so
  // it's computed right after updateOrientation().
  float verticalAccel = verticalAccelComponent(ax, ay, az, roll, pitch);

  bool key1JustPressed = keyPressed(KEY1);
  
  if (key1JustPressed && !nonBatteryScreenOn && !batteryScreenOn) { // do not show the screen if another is on
    batteryScreenStartTime = millis();
    batteryScreenOn = true;
    batteryScreen();
    display.wakeup();
  }
  if (batteryScreenOn && millis() - batteryScreenStartTime >= 5000) { // after 10min, turn off the screen
    batteryScreenOn = false;
    if (!nonBatteryScreenOn) display.sleep(); // only sleep if this is the only screen on
  }

  // manual trigger
  if (digitalRead(KEY1) == LOW) {
    if (!buttonStillPressed) {
      firstButtonPress = millis();
      buttonStillPressed = true;
      manualTriggerFiredThisHold = false;
    } else {
      if (!manualTriggerFiredThisHold && millis() - firstButtonPress >= MANUAL_ALARM_MS) {
        DBG_PRINTLN("ALARM TRIGGERED MANUALLY");
        triggerAlarm(100);
        manualTriggerFiredThisHold = true;
      }
    }
  } 
  else buttonStillPressed = manualTriggerFiredThisHold = false;
  
  static unsigned long lastMqttCheck = 0;
  if (millis() - lastMqttCheck > 1000) {
    lastMqttCheck = millis();
    ensureMqttConnected();
  }

  // ========================================================
  // STATE MACHINE
  // ========================================================
  switch (state) {
    // NORMAL: watch for anything unusual
    case NORMAL: {
      bool lowAccel  = accelerationMagnitude < FREE_FALL_ENTRY_G;
      bool highSpike = accelerationMagnitude > IMPACT_SPIKE_ENTRY_G;
      bool highGyro  = gyroMagnitude > GYRO_ENTRY_DPS;

      if (lowAccel || highSpike || highGyro) {
        startEvent();
        trackEpisodeExtremes(accelerationMagnitude, gyroMagnitude, verticalAccel);
      }
      break;
    }

    // EVENT_DETECTED: collect evidence for EVENT_WINDOW_MS
    case EVENT_DETECTED: {
      trackEpisodeExtremes(accelerationMagnitude, gyroMagnitude, verticalAccel);

      if (millis() - episodeStartTime >= EVENT_WINDOW_MS) {
        enterStillnessWait();
      }
      break;
    }

    // STILLNESS_WAIT: watch for the person to settle, then score
    case STILLNESS_WAIT: {
      trackEpisodeExtremes(accelerationMagnitude, gyroMagnitude, verticalAccel);

      bool quietNow = (fabsf(accelerationMagnitude - 1.0f) < QUIET_ACCEL_BAND_G) && (gyroMagnitude < QUIET_GYRO_DPS);

      if (quietNow) {
        if (quietStreakStart == 0) quietStreakStart = millis();
        unsigned long streak = millis() - quietStreakStart;
        longestQuietStreakMs = std::max(longestQuietStreakMs, streak);
      } else {
        quietStreakStart = 0;
      }

      bool reachedStillness = longestQuietStreakMs >= STILLNESS_REQUIRED_MS;
      bool timedOut = millis() - stillnessWaitStart >= STILLNESS_MAX_WAIT_MS;

      if (reachedStillness || timedOut) {
        resolveEpisode();
      }
      break;
    }

    // CONFIRMING: "Are you OK?" grace period -- always entered once the score reaches CONFIRMATION_THRESHOLD_PCT.
    case CONFIRMING: {
      if (key1JustPressed) {
        DBG_PRINTLN("KEY1 pressed - user cancelled, false alarm.");
        
        if (confirmationFromMQTT) mqttClient.publish(MQTT_TOPIC_EVENTS, "FALSA_ALARMA");
        confirmationFromMQTT = alreadyConfirming = false;

        noTone(BEEP_PIN);
        resetToNormal(); // TODO: enviar per MQTT que s'ha cancelat
        break;
      }

      // Nagging periodic beep so the grace period is hard to miss.
      if (millis() - lastConfirmBeep > CONFIRM_BEEP_INTERVAL_MS) {
        lastConfirmBeep = millis();
        tone(BEEP_PIN, CONFIRM_BEEP_FREQ_HZ, CONFIRM_BEEP_DURATION_MS);
      }

      // Update the on-screen countdown once per second, not every loop.
      unsigned long elapsed = updateConfirmationScreen(confirmStartTime, lastDisplayedCountdown);

      if (elapsed >= CONFIRMATION_GRACE_MS) {
        DBG_PRINTLN("No response during grace period - escalating to full alarm.");
        confirmationFromMQTT = alreadyConfirming = false;
        triggerAlarm(lastFallScore);
      }
      break;
    }

    // ALARM: stay active, re-beeping, until KEY1 cancels
    case ALARM: {
      if (key1JustPressed) {
        DBG_PRINTLN("KEY1 pressed - fall alarm cancelled by user.");
        noTone(BEEP_PIN);
        resetToNormal();
        break;
      }

      if (millis() - lastAlarmBeep > ALARM_BEEP_INTERVAL_MS) {
        lastAlarmBeep = millis();
        tone(BEEP_PIN, ALARM_BEEP_FREQ_HZ, ALARM_BEEP_DURATION_MS);
      }
      break;
    }
  }

  if (SERIAL_ENABLED) {
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint > 200) {
      lastPrint = millis();

      DBG_PRINT("A="); DBG_PRINT(accelerationMagnitude, 2);
      DBG_PRINT("  G="); DBG_PRINT(gyroMagnitude, 1);
      DBG_PRINT("  VA="); DBG_PRINT(verticalAccel, 2);
      DBG_PRINT("  Roll="); DBG_PRINT(roll, 1);
      DBG_PRINT("  Pitch="); DBG_PRINT(pitch, 1);
      
      DBG_PRINT("  State=");
      switch (state) {
        case NORMAL:          DBG_PRINT("NORMAL"); break;
        case EVENT_DETECTED:  DBG_PRINT("EVENT_DETECTED"); break;
        case STILLNESS_WAIT:  DBG_PRINT("STILLNESS_WAIT"); break;
        case CONFIRMING:      DBG_PRINT("CONFIRMING"); break;
        case ALARM:           DBG_PRINT("ALARM"); break;
      }
      
      // While an episode is active, show the running evidence too --
      // useful for tuning the thresholds above.
      if (state == EVENT_DETECTED || state == STILLNESS_WAIT) {
        DBG_PRINT("  [min="); DBG_PRINT(episodeMinAccel, 2);
        DBG_PRINT(" max="); DBG_PRINT(episodeMaxAccel, 2);
        DBG_PRINT(" maxG="); DBG_PRINT(episodeMaxGyro, 0);
        DBG_PRINT(" VAmin="); DBG_PRINT(episodeMinVerticalAccel, 2);
        DBG_PRINT(" VAmax="); DBG_PRINT(episodeMaxVerticalAccel, 2);
        DBG_PRINT(" quiet="); DBG_PRINT(longestQuietStreakMs); DBG_PRINT("ms]");
      }
      
      DBG_PRINTLN();
    }
  }
}
