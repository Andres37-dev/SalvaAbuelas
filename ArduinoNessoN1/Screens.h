#ifndef SCREENS_H
#define SCREENS_H

#include <Arduino_Nesso_N1.h>
#include <math.h>
#include "Config.h"

void confirmationScreen(int score);
void alarmScreen(int score);
unsigned long updateConfirmationScreen(unsigned long confirmStartTime, int &lastDisplayedCountdown);
void batteryScreen();

#endif
