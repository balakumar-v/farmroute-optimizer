# ESP32 + DHT22 (3-pin) room sensor

`farmroute_esp32/farmroute_esp32.ino` posts the DHT22 reading to `POST /sensors/reading` under pool id `room`.
Every plan compute uses the latest `room` reading from the last 5 minutes as the plan's "Current temperature"
(shown with the previous plan's value). With no recent reading it falls back to the simulated feed.

Wiring: module `+` -> 3V3, `OUT` -> GPIO4, `-` -> GND. Power the board over USB-C.

1. Edit WIFI_SSID, WIFI_PASS, API_HOST (laptop LAN IP) and, if the backend has ADMIN_TOKEN set, ADMIN_TOKEN in the sketch.
2. Run the backend with `uvicorn main:app --host 0.0.0.0 --port 8000` and allow port 8000 through the firewall.
3. Upload, open Serial Monitor at 115200; expect `HTTP 200`. Then click Compute plan.

Optional: `pool 4:2` in the Serial Monitor sends per-vehicle readings for the Map tab's Live sensors panel instead.
