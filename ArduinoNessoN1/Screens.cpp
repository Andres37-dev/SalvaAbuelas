#include "Screens.h"

void confirmationScreen(int score) {
  display.fillScreen(TFT_ORANGE);
  display.setTextColor(TFT_BLACK);

  display.setTextSize(3);
  display.setCursor(10, 20);
  display.println("ARE YOU OK?");
  
  display.setTextSize(2);
  display.setCursor(3, 50);
  display.println("Press the button if you're fine.");
  
  display.setCursor(3, 70);
  display.print("Cancel in: ");

  display.setCursor(3, SCREEN_HEIGHT - 10);
  display.print("Confidence: "); display.print(score); display.println("%");
}

void alarmScreen(int score) {
  display.fillScreen(TFT_RED);
  display.setTextColor(TFT_BLACK);

  display.setTextSize(3);
  display.setCursor(10, 20);
  display.println("FALL ALARM");
  
  display.setTextSize(2);
  display.setCursor(3, 64);
  display.println("Press the button to silence");
}

unsigned long updateConfirmationScreen(unsigned long confirmStartTime, int &lastDisplayedCountdown) {
  unsigned long elapsed = millis() - confirmStartTime;
  int secondsLeft = (int)((CONFIRMATION_GRACE_MS - elapsed) / 1000);
  if (secondsLeft < 0) secondsLeft = 0;
  if (secondsLeft != lastDisplayedCountdown) {
    lastDisplayedCountdown = secondsLeft;
    display.fillRect(138, 70, 40, 16, TFT_ORANGE);
    display.setTextColor(TFT_BLACK);
    display.setTextSize(2);
    display.setCursor(138, 70);
    display.print(secondsLeft);
    display.println("s");
  }
  return elapsed;
}

void batteryScreen() {
  display.fillScreen(TFT_BLACK);
  display.setTextSize(7);
  display.setTextColor((battery.getChargeStatus() == NessoBattery::CHARGING) ? TFT_YELLOW : TFT_WHITE);

  int textWidthBattery = display.textWidth(String(battery.getChargeLevel()).c_str());
  display.setCursor(SCREEN_WIDTH - 72 - textWidthBattery, 40);
  display.print(String(battery.getChargeLevel()).c_str()); display.println("%");
}
