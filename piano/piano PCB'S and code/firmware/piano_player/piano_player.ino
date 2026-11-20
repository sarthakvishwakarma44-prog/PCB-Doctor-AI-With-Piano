#include <SPI.h>
#include <SD.h>
#include <Wire.h>
#include "config.h"
#include "board_map.h"
#include "expander.h"
#include "synth.h"

enum class Kind : uint8_t { SolOn, SolOff, SynOn, SynOff };

struct Action {
  int32_t at;
  uint8_t key;
  Kind kind;
};

struct Song {
  String path;
  String title;
};

Expander outputs(ADDR_OUT);
Expander inputs(ADDR_IN);

Song songs[MAX_SONGS];
uint8_t songCount = 0;
uint8_t songIndex = 0;

File track;
uint32_t eventsLeft = 0;
bool haveEvent = false;
uint32_t eventTime = 0;
uint16_t eventMask = 0;
uint16_t previousMask = 0;

Action queue[96];
uint8_t queued = 0;

bool playing = false;
bool paused = false;
uint32_t startedAt = 0;
uint32_t pausedAt = 0;

uint16_t driven = 0;
uint16_t blocked = 0;
uint32_t pressedAt[KEY_COUNT];
uint32_t releasedAt[KEY_COUNT];
bool contactSeen[KEY_COUNT];
bool faultShown[KEY_COUNT];
int16_t lead[KEY_COUNT];
uint32_t nextSense = 0;
uint32_t faults = 0;

uint32_t buttonChange[2];
bool buttonHeld[2];

int32_t songClock() {
  return (int32_t)(millis() - startedAt);
}

uint8_t countBits(uint16_t v) {
  uint8_t n = 0;
  while (v) {
    n += v & 1;
    v >>= 1;
  }
  return n;
}

void writeDrivers() {
  outputs.write16(reg::OLAT, keysToOutputBits(driven));
}

void releaseAll() {
  driven = 0;
  writeDrivers();
  synth::silence();
  uint32_t now = millis();
  for (uint8_t k = 0; k < KEY_COUNT; k++) releasedAt[k] = now;
}

void pushAction(int32_t at, uint8_t key, Kind kind) {
  if (queued >= sizeof(queue) / sizeof(queue[0])) return;
  uint8_t i = queued;
  while (i > 0 && queue[i - 1].at > at) {
    queue[i] = queue[i - 1];
    i--;
  }
  queue[i] = {at, key, kind};
  queued++;
}

void pressKey(uint8_t key, int32_t at) {
  uint16_t bit = 1u << key;
  if ((driven & bit) || (blocked & bit)) return;
  if (countBits(driven) >= MAX_POLY) return;
  uint32_t now = millis();
  if (now - releasedAt[key] < MIN_GAP_MS) {
    pushAction(at + 4, key, Kind::SolOn);
    return;
  }
  driven |= bit;
  pressedAt[key] = now;
  contactSeen[key] = false;
  faultShown[key] = false;
  writeDrivers();
}

void liftKey(uint8_t key) {
  uint16_t bit = 1u << key;
  blocked &= ~bit;
  if (!(driven & bit)) return;
  driven &= ~bit;
  releasedAt[key] = millis();
  writeDrivers();
}

void runAction(const Action& a) {
  switch (a.kind) {
    case Kind::SolOn: pressKey(a.key, a.at); break;
    case Kind::SolOff: liftKey(a.key); break;
    case Kind::SynOn: if (SYNTH_ENABLED) synth::noteOn(a.key); break;
    case Kind::SynOff: if (SYNTH_ENABLED) synth::noteOff(a.key); break;
  }
}

bool readEvent() {
  if (eventsLeft == 0) return false;
  uint8_t raw[6];
  if (track.read(raw, 6) != 6) return false;
  eventTime = raw[0] | (raw[1] << 8) | (raw[2] << 16) | ((uint32_t)raw[3] << 24);
  eventMask = raw[4] | (raw[5] << 8);
  eventsLeft--;
  return true;
}

void expandEvent() {
  uint16_t rising = eventMask & ~previousMask;
  uint16_t falling = previousMask & ~eventMask;
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    uint16_t bit = 1u << k;
    if (rising & bit) {
      pushAction((int32_t)eventTime - lead[k], k, Kind::SolOn);
      pushAction((int32_t)eventTime, k, Kind::SynOn);
    }
    if (falling & bit) {
      pushAction((int32_t)eventTime, k, Kind::SolOff);
      pushAction((int32_t)eventTime, k, Kind::SynOff);
    }
  }
  previousMask = eventMask;
}

void stopSong() {
  playing = false;
  paused = false;
  if (track) track.close();
  queued = 0;
  haveEvent = false;
  previousMask = 0;
  blocked = 0;
  releaseAll();
  digitalWrite(LED_BUILTIN, LOW);
}

bool startSong(uint8_t index) {
  stopSong();
  track = SD.open(songs[index].path.c_str(), FILE_READ);
  if (!track) return false;
  uint8_t head[10];
  if (track.read(head, 10) != 10 || memcmp(head, "PNO1", 4) != 0 || (head[4] | (head[5] << 8)) != KEY_COUNT) {
    Serial.println("bad song file");
    track.close();
    return false;
  }
  eventsLeft = head[6] | (head[7] << 8) | (head[8] << 16) | ((uint32_t)head[9] << 24);
  haveEvent = readEvent();
  startedAt = millis() + PREROLL_MS;
  playing = true;
  Serial.print("playing ");
  Serial.println(songs[index].title);
  return true;
}

void pausePlayback() {
  paused = true;
  pausedAt = millis();
  queued = 0;
  previousMask = 0;
  releaseAll();
}

void resumePlayback() {
  startedAt += millis() - pausedAt;
  paused = false;
}

void feedQueue() {
  int32_t now = songClock();
  while (haveEvent && (int32_t)eventTime - (int32_t)LOOKAHEAD_MS <= now && queued < 60) {
    expandEvent();
    haveEvent = readEvent();
  }
}

void dispatchQueue() {
  int32_t now = songClock();
  while (queued > 0 && queue[0].at <= now) {
    Action a = queue[0];
    for (uint8_t i = 1; i < queued; i++) queue[i - 1] = queue[i];
    queued--;
    runAction(a);
  }
}

void guardHolds() {
  uint32_t now = millis();
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    uint16_t bit = 1u << k;
    if ((driven & bit) && now - pressedAt[k] > MAX_HOLD_MS) {
      liftKey(k);
      blocked |= bit;
    }
  }
}

void readSensors() {
  uint32_t now = millis();
  if (now < nextSense) return;
  nextSense = now + SENSE_PERIOD_MS;
  uint16_t closed = inputBitsToKeys(~inputs.read16(reg::GPIO));
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    uint16_t bit = 1u << k;
    if (driven & bit) {
      if (!contactSeen[k] && (closed & bit)) {
        contactSeen[k] = true;
        int16_t measured = (int16_t)(now - pressedAt[k]);
        int16_t target = constrain(measured + lead[k] / 2, LEAD_MIN_MS, LEAD_MAX_MS);
        lead[k] = (lead[k] * 3 + target) / 4;
      } else if (!contactSeen[k] && !faultShown[k] && now - pressedAt[k] > FAULT_MS) {
        faultShown[k] = true;
        faults++;
        Serial.print("no contact on key ");
        Serial.println(k + 1);
      }
    }
  }
}

bool buttonEdge(uint8_t slot, uint8_t pin) {
  bool down = digitalRead(pin) == LOW;
  uint32_t now = millis();
  if (down != buttonHeld[slot] && now - buttonChange[slot] > DEBOUNCE_MS) {
    buttonHeld[slot] = down;
    buttonChange[slot] = now;
    return down;
  }
  return false;
}

void scanSongs() {
  songCount = 0;
  File root = SD.open("/");
  while (songCount < MAX_SONGS) {
    File entry = root.openNextFile();
    if (!entry) break;
    String name = entry.name();
    bool isDir = entry.isDirectory();
    entry.close();
    String lower = name;
    lower.toLowerCase();
    if (!isDir && lower.endsWith(".pno") && !name.startsWith(".")) {
      songs[songCount].path = "/" + name;
      songs[songCount].title = name;
      songCount++;
    }
  }
  root.close();
  for (uint8_t i = 1; i < songCount; i++) {
    Song s = songs[i];
    int j = i - 1;
    while (j >= 0 && songs[j].title > s.title) {
      songs[j + 1] = songs[j];
      j--;
    }
    songs[j + 1] = s;
  }
}

void blinkForever(uint16_t period) {
  while (true) {
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    delay(period);
  }
}

void selfTest() {
  Serial.println("self test");
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    driven = 1u << k;
    writeDrivers();
    delay(140);
    uint16_t closed = inputBitsToKeys(~inputs.read16(reg::GPIO));
    driven = 0;
    writeDrivers();
    Serial.print("key ");
    Serial.print(k + 1);
    Serial.println((closed & (1u << k)) ? " ok" : " no contact");
    delay(250);
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_PLAY, INPUT_PULLUP);
  pinMode(PIN_NEXT, INPUT_PULLUP);
  pinMode(PIN_RESET, OUTPUT);
  digitalWrite(PIN_RESET, LOW);
  delay(5);
  digitalWrite(PIN_RESET, HIGH);
  delay(5);

  Serial.begin(115200);
  Wire.setSDA(PIN_SDA);
  Wire.setSCL(PIN_SCL);
  Wire.begin();
  Wire.setClock(1000000);

  if (!outputs.present() || !inputs.present()) {
    Serial.println("expander missing");
    blinkForever(120);
  }
  outputs.write16(reg::OLAT, 0);
  outputs.write16(reg::IODIR, 0x0000);
  inputs.write16(reg::IODIR, 0xFFFF);
  inputs.write16(reg::GPPU, 0xFFFF);

  for (uint8_t k = 0; k < KEY_COUNT; k++) lead[k] = LEAD_START_MS;
  synth::begin();

  if (digitalRead(PIN_PLAY) == LOW) {
    selfTest();
    while (digitalRead(PIN_PLAY) == LOW) delay(10);
  }

  SPI.setRX(PIN_SD_MISO);
  SPI.setTX(PIN_SD_MOSI);
  SPI.setSCK(PIN_SD_SCK);
  if (!SD.begin(PIN_SD_CS, SPI)) {
    Serial.println("sd card not found");
    blinkForever(400);
  }
  scanSongs();
  Serial.print(songCount);
  Serial.println(" songs");
  if (songCount == 0) blinkForever(800);
}

void loop() {
  if (buttonEdge(0, PIN_PLAY)) {
    if (!playing) {
      startSong(songIndex);
    } else if (paused) {
      resumePlayback();
    } else {
      pausePlayback();
    }
  }
  if (buttonEdge(1, PIN_NEXT)) {
    songIndex = (songIndex + 1) % songCount;
    startSong(songIndex);
  }

  readSensors();

  if (playing && !paused) {
    digitalWrite(LED_BUILTIN, HIGH);
    feedQueue();
    dispatchQueue();
    guardHolds();
    if (!haveEvent && queued == 0 && driven == 0 && songClock() > 0) {
      stopSong();
      delay(SONG_GAP_MS);
      songIndex = (songIndex + 1) % songCount;
      startSong(songIndex);
    }
  } else if (playing && paused) {
    digitalWrite(LED_BUILTIN, (millis() / 400) & 1);
  }
}
