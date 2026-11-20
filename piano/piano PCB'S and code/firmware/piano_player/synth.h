#pragma once
#include <Arduino.h>
#include "hardware/gpio.h"
#include "hardware/pwm.h"
#include "pico/time.h"
#include "config.h"

namespace synth {

constexpr uint32_t PERIOD_US = 45;
constexpr float SAMPLE_RATE = 1000000.0f / PERIOD_US;

struct Voice {
  volatile uint32_t phase = 0;
  volatile uint32_t step = 0;
  volatile uint32_t level = 0;
  volatile bool held = false;
};

static Voice voices[KEY_COUNT];
static int8_t wave[256];
static repeating_timer_t timer;

static bool __not_in_flash_func(tick)(repeating_timer_t*) {
  int32_t mix = 0;
  for (uint8_t i = 0; i < KEY_COUNT; i++) {
    Voice& v = voices[i];
    uint32_t level = v.level;
    if (!level) continue;
    v.phase += v.step;
    mix += (int32_t)wave[v.phase >> 24] * (int32_t)(level >> 16);
    level -= level >> (v.held ? 15 : 10);
    v.level = level < 0x10000 ? 0 : level;
  }
  int32_t out = 128 + (mix >> 11);
  if (out < 0) out = 0;
  if (out > 255) out = 255;
  pwm_set_gpio_level(PIN_AUDIO, out);
  return true;
}

inline void begin() {
  float peak = 0;
  float raw[256];
  for (int i = 0; i < 256; i++) {
    float x = 2.0f * PI * i / 256.0f;
    raw[i] = 0.62f * sinf(x) + 0.24f * sinf(2 * x) + 0.10f * sinf(3 * x) + 0.04f * sinf(4 * x);
    if (fabsf(raw[i]) > peak) peak = fabsf(raw[i]);
  }
  for (int i = 0; i < 256; i++) wave[i] = (int8_t)(raw[i] / peak * 120.0f);
  gpio_set_function(PIN_AUDIO, GPIO_FUNC_PWM);
  uint slice = pwm_gpio_to_slice_num(PIN_AUDIO);
  pwm_set_wrap(slice, 255);
  pwm_set_gpio_level(PIN_AUDIO, 128);
  pwm_set_enabled(slice, true);
  add_repeating_timer_us(-(int32_t)PERIOD_US, tick, nullptr, &timer);
}

inline void noteOn(uint8_t key) {
  float hz = 440.0f * powf(2.0f, (FIRST_NOTE + key - 69) / 12.0f);
  Voice& v = voices[key];
  v.step = (uint32_t)(hz * 4294967296.0f / SAMPLE_RATE);
  v.phase = 0;
  v.held = true;
  v.level = 0xFFFFFF;
}

inline void noteOff(uint8_t key) {
  voices[key].held = false;
}

inline void silence() {
  for (uint8_t i = 0; i < KEY_COUNT; i++) {
    voices[i].held = false;
    voices[i].level = 0;
  }
}

}
