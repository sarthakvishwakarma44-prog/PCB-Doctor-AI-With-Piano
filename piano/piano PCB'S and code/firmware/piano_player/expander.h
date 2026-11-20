#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "board_map.h"

namespace reg {
constexpr uint8_t IODIR = 0x00;
constexpr uint8_t GPPU = 0x0C;
constexpr uint8_t GPIO = 0x12;
constexpr uint8_t OLAT = 0x14;
}

class Expander {
 public:
  explicit Expander(uint8_t address) : addr(address) {}

  bool present() {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
  }

  void write16(uint8_t r, uint16_t value) {
    Wire.beginTransmission(addr);
    Wire.write(r);
    Wire.write(value & 0xFF);
    Wire.write(value >> 8);
    Wire.endTransmission();
  }

  uint16_t read16(uint8_t r) {
    Wire.beginTransmission(addr);
    Wire.write(r);
    Wire.endTransmission(false);
    if (Wire.requestFrom(addr, (uint8_t)2) != 2) return 0xFFFF;
    uint16_t low = Wire.read();
    uint16_t high = Wire.read();
    return low | (high << 8);
  }

 private:
  uint8_t addr;
};

inline uint16_t keysToOutputBits(uint16_t keys) {
  uint16_t bits = 0;
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    if (keys & (1u << k)) bits |= 1u << (OUT_PORT[k] * 8 + OUT_BIT[k]);
  }
  return bits;
}

inline uint16_t inputBitsToKeys(uint16_t bits) {
  uint16_t keys = 0;
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    if (bits & (1u << (IN_PORT[k] * 8 + IN_BIT[k]))) keys |= 1u << k;
  }
  return keys;
}
