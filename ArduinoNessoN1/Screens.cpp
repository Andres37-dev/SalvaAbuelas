#include "Screens.h"

void drawVersionBatteryLabel(uint16_t color) {
  display.setTextSize(2);
  display.setTextColor(color);

  display.setCursor(0, SCREEN_HEIGHT - 32);
  display.print(String(battery.getChargeLevel()).c_str()); display.println("%");
  display.println(FIRMWARE_VERSION);
}

void normalScreen(float lastFallScore) {
  batteryScreen(); 
  return;
  // display.fillScreen(TFT_BLACK);
  // display.setTextColor(TFT_WHITE);
  // display.setTextSize(1);

  // display.setCursor(5, 5);
  // display.println("Fall detector");
  // display.setCursor(5, 20);
  // display.println("Monitoring...");

  // if (lastFallScore >= 0.0f) {
  //   display.setCursor(5, 40);
  //   display.print("Last event: ");
  //   display.print((int)lastFallScore);
  //   display.println("%");
  // }

  // drawVersionBatteryLabel(TFT_WHITE);
}

void confirmationScreen(int score) {
  display.setRotation(0);
  display.fillScreen(TFT_ORANGE);
  display.setTextColor(TFT_BLACK);

  display.setTextSize(2);
  display.setCursor(0, 10);
  display.println("ARE YOU OK?");

  display.setTextSize(1);
  display.setCursor(10, 45);
  display.print("Confidence: "); display.print(score); display.println("%");

  display.setCursor(0, 85);
  display.println("Press KEY1 if you're fine");

  drawVersionBatteryLabel(TFT_BLACK);
}

void alarmScreen(int score) {
  display.setRotation(0);
  display.fillScreen(TFT_RED);
  display.setTextColor(TFT_WHITE);

  display.setTextSize(2);
  display.setCursor(0, 10);
  display.println("FALL DETECTED!");

  display.setTextSize(1);
  display.setCursor(10, 50);
  display.print("Confidence: "); display.print(score); display.println("%");

  display.setCursor(0, 70);
  display.println("Press KEY1 to cancel");

  drawVersionBatteryLabel(TFT_WHITE);
}

unsigned long updateConfirmationScreen(unsigned long confirmStartTime, int &lastDisplayedCountdown) {
  unsigned long elapsed = millis() - confirmStartTime;
  int secondsLeft = (int)((CONFIRMATION_GRACE_MS - elapsed) / 1000);
  if (secondsLeft < 0) secondsLeft = 0;
  if (secondsLeft != lastDisplayedCountdown) {
    lastDisplayedCountdown = secondsLeft;
    display.fillRect(10, 65, 220, 16, TFT_ORANGE);
    display.setTextColor(TFT_BLACK);
    display.setTextSize(1);
    display.setCursor(10, 65);
    display.print("Cancel in: ");
    display.print(secondsLeft);
    display.println("s");
  }
  return elapsed;
}

void batteryScreen() {
  display.fillScreen(TFT_BLACK);
  display.setRotation(3);
  display.setTextSize(7);
  display.setTextColor((battery.getChargeStatus() == NessoBattery::CHARGING) ? TFT_YELLOW : TFT_WHITE);

  int textWidthBattery = display.textWidth(String(battery.getChargeLevel()).c_str());
  display.setCursor(240 - 72 - textWidthBattery, 40);
  display.print(String(battery.getChargeLevel()).c_str()); display.println("%");
}
