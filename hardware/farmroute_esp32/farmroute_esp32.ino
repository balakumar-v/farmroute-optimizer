/*
 * Farmroute Optimizer - ESP32 room/cargo temperature node (DHT22, 3-pin module)
 * ----------------------------------------------------------------------------
 * Reads a DHT22 and POSTs the reading to the Farmroute backend every POST_INTERVAL_MS:
 *
 *   POST http://<LAPTOP_IP>:8000/sensors/reading
 *   {"pool_id":"room","temperature":28.4,"humidity":61.2,"timestamp":0.0123}
 *
 * pool_id "room" is special: every time a plan is computed the backend uses the LATEST room reading that arrived in
 * the last 5 minutes as the plan's "Current temperature" (and falls back to a simulated value if there is none).
 * You can instead set a per-vehicle id from the Map tab, e.g. "4:2" (plan 4, vehicle 2), with the serial command below;
 * those readings only show in the Map tab's Live sensors panel and do not feed the plan.
 *
 * "timestamp" is just hours since this board booted (the backend stamps the arrival time itself).
 * Readings are NOT buffered while the link is down: an old reading re-sent later would look fresh to the planner.
 *
 * Power: plug the board into a USB-C power source (laptop, phone charger, or a power bank) - nothing else is needed.
 *
 * Wiring (3-pin DHT22 module, pins are printed on the board):
 *   module "+" / VCC  -> ESP32 3V3        module "OUT" / DATA -> ESP32 GPIO4        module "-" / GND -> ESP32 GND
 *
 * Arduino IDE: board "ESP32 Dev Module" (package "esp32" by Espressif); libraries "DHT sensor library" (Adafruit) and
 * "Adafruit Unified Sensor". Serial Monitor 115200 baud, line ending "Newline".
 *
 * Serial commands:
 *   pool room     send as the plan-feeding room sensor (default)
 *   pool 4:2      send as plan 4, vehicle 2 (saved to flash)
 *   status        print settings
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include "DHT.h"

// ---------- EDIT THESE ----------
const char* WIFI_SSID  = "YOUR_WIFI_NAME";        // must be a 2.4 GHz network
const char* WIFI_PASS  = "YOUR_WIFI_PASSWORD";
const char* API_HOST   = "192.168.1.50";          // the laptop's LAN IP running the backend, NOT localhost
const int   API_PORT   = 8000;
const char* ADMIN_TOKEN = "";                     // same value as the backend's ADMIN_TOKEN; leave "" if it is not set
const char* DEFAULT_POOL_ID = "room";
const float TEMP_OFFSET_C  = 0.0f;                // calibration offset (ice-water test)
const float HUM_OFFSET_PCT = 0.0f;
const unsigned long POST_INTERVAL_MS = 15000;     // must stay >= 2000 (DHT22 limit) and well under 300000 (freshness window)
// --------------------------------

#define DHT_PIN  4
#define DHT_TYPE DHT22
#ifdef LED_BUILTIN
  #define LED_PIN LED_BUILTIN
#else
  #define LED_PIN 2
#endif

DHT dht(DHT_PIN, DHT_TYPE);
Preferences prefs;
String poolId;
unsigned long lastPostMs = 0;

void blink(int n, int ms = 80) {
  for (int i = 0; i < n; i++) { digitalWrite(LED_PIN, HIGH); delay(ms); digitalWrite(LED_PIN, LOW); delay(ms); }
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi: connecting to %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) { delay(400); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) Serial.printf(" OK, ESP32 IP %s\n", WiFi.localIP().toString().c_str());
  else Serial.println(" FAILED (will retry)");
}

bool postReading(float t, float h) {
  if (WiFi.status() != WL_CONNECTED) return false;
  char url[96], body[160];
  snprintf(url, sizeof(url), "http://%s:%d/sensors/reading", API_HOST, API_PORT);
  snprintf(body, sizeof(body),
           "{\"pool_id\":\"%s\",\"temperature\":%.2f,\"humidity\":%.2f,\"timestamp\":%.4f}",
           poolId.c_str(), t, h, millis() / 3600000.0f);
  HTTPClient http;
  http.setTimeout(5000);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (strlen(ADMIN_TOKEN) > 0) http.addHeader("Authorization", String("Bearer ") + ADMIN_TOKEN);
  int code = http.POST((uint8_t*)body, strlen(body));
  http.end();
  Serial.printf("POST %s -> HTTP %d\n", body, code);
  return code == 200;
}

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.startsWith("pool ")) {
    poolId = line.substring(5); poolId.trim();
    prefs.putString("pool", poolId);
    Serial.printf("pool_id set to %s\n", poolId.c_str());
  } else if (line == "status") {
    Serial.printf("pool=%s api=%s:%d wifi=%d interval=%lu ms token=%s\n", poolId.c_str(), API_HOST, API_PORT,
                  WiFi.status() == WL_CONNECTED, POST_INTERVAL_MS, strlen(ADMIN_TOKEN) ? "set" : "none");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  dht.begin();
  prefs.begin("farmroute", false);
  poolId = prefs.getString("pool", DEFAULT_POOL_ID);
  Serial.printf("\nFarmroute sensor node. pool=%s\n", poolId.c_str());
  connectWifi();
}

void loop() {
  handleSerial();
  if (lastPostMs != 0 && millis() - lastPostMs < POST_INTERVAL_MS) return;
  lastPostMs = millis();

  connectWifi();
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) { Serial.println("DHT22 read failed - check wiring (DATA on GPIO4, VCC on 3V3)"); blink(5, 40); return; }
  if (postReading(t + TEMP_OFFSET_C, h + HUM_OFFSET_PCT)) blink(1); else blink(2, 200);
}
