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
