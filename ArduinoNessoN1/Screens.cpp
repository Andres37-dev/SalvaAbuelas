#include "Screens.h"

void drawVersionLabel(uint16_t color) {
  display.setTextSize(1);
  display.setTextColor(color);
  int textWidthFirmware = display.textWidth(FIRMWARE_VERSION);
  display.setCursor(240 - textWidthFirmware - 4, 135 - 10);
  display.print(FIRMWARE_VERSION);
  int textWidthBattery = display.textWidth(String(battery.getChargeLevel()).c_str());
  display.setCursor(240 - textWidthBattery - 4 - 6, 135 - 18);
  display.print(String(battery.getChargeLevel()).c_str());
  display.print("%");
}

void normalScreen(float lastFallScore) {
  display.fillScreen(TFT_BLACK);
  display.setTextColor(TFT_WHITE);
  display.setTextSize(1);

  display.setCursor(5, 5);
  display.println("Fall detector");
  display.setCursor(5, 20);
  display.println("Monitoring...");

  if (lastFallScore >= 0.0f) {
    display.setCursor(5, 40);
    display.print("Last event: ");
    display.print((int)lastFallScore);
    display.println("%");
  }

  drawVersionLabel(TFT_WHITE);
}

void confirmationScreen(int score) {
  display.fillScreen(TFT_ORANGE);
  display.setTextColor(TFT_BLACK);

  display.setTextSize(2);
  display.setCursor(10, 10);
  display.println("ARE YOU OK?");

  display.setTextSize(1);
  display.setCursor(10, 45);
  display.print("Confidence: "); display.print(score); display.println("%");

  display.setCursor(10, 85);
  display.println("Press KEY1 if you're fine");

  drawVersionLabel(TFT_BLACK);
}

void alarmScreen(int score) {
  display.fillScreen(TFT_RED);
  display.setTextColor(TFT_WHITE);

  display.setTextSize(2);
  display.setCursor(10, 10);
  display.println("FALL DETECTED!");

  display.setTextSize(1);
  display.setCursor(10, 50);
  display.print("Confidence: "); display.print(score); display.println("%");

  display.setCursor(10, 70);
  display.println("Press KEY1 to cancel");

  drawVersionLabel(TFT_WHITE);
}