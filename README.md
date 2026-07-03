# Raspberry Pi Learning

This repository documents my Raspberry Pi learning journey.

Goals:

- Learn Linux
- Learn Git
- Build an IoT server
- Build a cyberdeck

## ESP32-S3 MQTT Heartbeat

This repository includes a PlatformIO project for an ESP32-S3 that connects to Wi-Fi, connects to an MQTT broker on a Raspberry Pi, and publishes a heartbeat every 5 seconds.

The default PlatformIO target is `esp32-s3-devkitc-1`. If your ESP32-S3 board is a different model, update the `board` value in `platformio.ini`.

Configure these values at the top of `src/main.cpp` before uploading:

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `MQTT_BROKER_IP`
- `MQTT_PORT`
- `MQTT_TOPIC`

Useful PlatformIO commands:

```powershell
python -m platformio run
python -m platformio run --target upload
python -m platformio device monitor
```

## Raspberry Pi MQTT Listener

The Python listener connects to the MQTT broker running on the Raspberry Pi at `localhost:1883`, subscribes to `home/#`, prints every received message, and appends the same line to `logs/mqtt_messages.log`.

The listener intentionally only logs messages to a text file for now. Database support is not included yet.

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

Each received message is printed like this:

```text
2026-07-03T12:34:56-06:00 | topic=home/esp32/status | payload={"status":"online"}
```

The listener creates the `logs/` folder if needed and appends messages to `logs/mqtt_messages.log`.
