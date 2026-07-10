# Raspberry Pi Learning

This repository documents my Raspberry Pi learning journey.

Goals:

- Learn Linux
- Learn Git
- Build an IoT server
- Build a cyberdeck

## ESP32-S3 MQTT Heartbeat

This repository includes a PlatformIO project for an ESP32-S3 that connects to Wi-Fi, connects to an MQTT broker on a Raspberry Pi, and publishes a compact JSON heartbeat every 5 seconds to `home/esp32-s3/status`.

The default PlatformIO target is `esp32-s3-devkitc-1`. If your ESP32-S3 board is a different model, update the `board` value in `platformio.ini`.

Configure these values at the top of `src/main.cpp` before uploading:

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `MQTT_BROKER_IP`
- `MQTT_PORT`
- `MQTT_TOPIC`

Heartbeat payloads use this compact JSON shape:

```json
{"device":"esp32-s3-test","type":"heartbeat","count":1,"uptime_ms":5000,"wifi_rssi":-57}
```

Useful PlatformIO commands:

```powershell
python -m platformio run
python -m platformio run --target upload
python -m platformio device monitor
```

## Raspberry Pi MQTT Listener

The Python listener connects to the MQTT broker running on the Raspberry Pi at `localhost:1883`, subscribes to `home/#`, prints every received message, and appends the same line to `logs/mqtt_messages.log`.

When a payload is valid JSON, the listener also appends a structured JSON Lines record to `logs/mqtt_messages.jsonl` and a CSV row to `logs/mqtt_messages.csv`. Database support is not included yet.

### Setup

Run these commands on the Raspberry Pi:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Make sure your MQTT broker is running locally. For Mosquitto, one quick check is:

```bash
systemctl status mosquitto
```

### Run

Start the listener from the repository root:

```bash
python -m mqtt_listener.listener
```

Valid JSON messages are printed with structured fields:

```text
2026-07-03T12:34:56-06:00 | topic=home/esp32-s3/status | device=esp32-s3-test | type=heartbeat | payload={"device":"esp32-s3-test","type":"heartbeat","count":1,"uptime_ms":5000,"wifi_rssi":-57}
```

Raw non-JSON messages are still printed and logged:

```text
2026-07-03T12:35:01-06:00 | topic=home/sensor/raw | payload=not json
```

The listener creates the `logs/` folder if needed, appends all messages to `logs/mqtt_messages.log`, and appends valid JSON messages to `logs/mqtt_messages.jsonl` as records with `received_at`, `topic`, and `payload`.

Valid JSON messages are also appended to `logs/mqtt_messages.csv`. The CSV header is created automatically when the file does not exist:

```csv
received_at,topic,device,type,count,uptime_ms,wifi_rssi
```

Missing JSON fields are written as blank CSV values.

### Device Health Report

After the listener has written `logs/mqtt_messages.csv`, run the device status utility from the repository root:

```bash
python device_status.py
```

The report groups messages by `device` and shows the latest `received_at`, `topic`, `type`, `count`, `uptime_ms`, and `wifi_rssi` for each device. A device is shown as `ONLINE` when its latest message was received within the last 30 seconds; otherwise it is shown as `OFFLINE`.

If `logs/mqtt_messages.csv` is missing or empty, the script prints a friendly message and exits without an error.

### Automated Health Monitor

Run the health monitor to write the latest device status snapshot to `logs/device_status.json` and print the same JSON report to the terminal:

```bash
python health_monitor.py
```

The monitor reads `logs/mqtt_messages.csv`, keeps the latest message per `device`, and marks devices `ONLINE` when the latest message is within 30 seconds. Missing or empty CSV input produces an empty `devices` list with a friendly `message` field.

### Web Dashboard

The dashboard serves a simple local webpage on port `8080` using only the Python standard library. It reads `logs/device_status.json`, so run the health monitor first whenever you want to refresh the status snapshot:

```bash
python health_monitor.py
python dashboard_server.py
```

Open the dashboard on the Raspberry Pi at:

```text
http://localhost:8080
```

From another computer on the same network, replace `localhost` with the Raspberry Pi IP address. The page auto-refreshes every 10 seconds and shows `ONLINE` and `OFFLINE` labels for each device.

If `logs/device_status.json` is missing, the dashboard still loads and shows a friendly empty-state message.
