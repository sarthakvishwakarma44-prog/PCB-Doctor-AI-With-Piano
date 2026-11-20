#pragma once
#include <Arduino.h>

constexpr uint8_t KEY_COUNT = 15;

constexpr uint8_t PIN_SDA = 4;
constexpr uint8_t PIN_SCL = 5;
constexpr uint8_t PIN_RESET = 7;
constexpr uint8_t PIN_PLAY = 8;
constexpr uint8_t PIN_NEXT = 9;
constexpr uint8_t PIN_AUDIO = 14;
constexpr uint8_t PIN_SD_MISO = 16;
constexpr uint8_t PIN_SD_CS = 17;
constexpr uint8_t PIN_SD_SCK = 18;
constexpr uint8_t PIN_SD_MOSI = 19;

constexpr uint8_t ADDR_OUT = 0x20;
constexpr uint8_t ADDR_IN = 0x21;

constexpr uint8_t FIRST_NOTE = 60;
constexpr uint8_t MAX_POLY = 6;
constexpr uint16_t MAX_HOLD_MS = 2500;
constexpr uint16_t MIN_GAP_MS = 35;
constexpr uint16_t SENSE_PERIOD_MS = 2;
constexpr uint16_t FAULT_MS = 150;
constexpr uint16_t LOOKAHEAD_MS = 160;
constexpr uint16_t PREROLL_MS = 120;
constexpr uint16_t SONG_GAP_MS = 1500;
constexpr uint16_t DEBOUNCE_MS = 35;

constexpr int16_t LEAD_START_MS = 12;
constexpr int16_t LEAD_MIN_MS = 4;
constexpr int16_t LEAD_MAX_MS = 60;

constexpr bool SYNTH_ENABLED = true;
constexpr uint8_t MAX_SONGS = 48;
