# Device Onboarding Contract

This document defines how new MQTT devices should publish to the Raspberry Pi IoT platform today. It is a contract for the current platform shape, not a new feature implementation.

The platform is ready for additional basic MQTT devices now if they follow this contract. New devices will be logged, included in structured JSONL/CSV logs, processed by the health monitor, and shown in the current dashboard health table. Rich per-device dashboard cards, schemas, registries, and long-term database storage are future stages.

## Current Platform Behavior

The Raspberry Pi MQTT listener subscribes to:

```text
home/#
```

It connects to Mosquitto on:

```text
localhost:1883
```

For every received MQTT message:

- The payload is decoded as UTF-8 with replacement for invalid bytes.
- A human-readable line is printed and appended to `data/logs/mqtt_messages.log`.
- If the payload is valid JSON, the full payload is appended to `data/logs/mqtt_messages.jsonl`.
- If the payload is valid JSON, one fixed-column CSV row is appended to `data/logs/mqtt_messages.csv`.
- If the payload is retained plain-text `online` or `offline` on `home/devices/<device-id>/availability`, it is also normalized into `data/logs/mqtt_messages.jsonl` as a structured availability event.
- Other non-JSON payloads are kept in the text log only.

The health monitor reads `data/logs/mqtt_messages.csv`, groups rows by the JSON `device` field, enriches those rows with latest status/telemetry/availability details from JSONL and availability logs, and writes `data/status/device_status.json`.

The dashboard reads `data/status/device_status.json`, displays the fixed health/status summary columns, and provides expandable device details for latest status, telemetry, and availability fields.

## Device ID Rules

Each physical or logical device should have one stable device ID.

Recommended format:

- Lowercase letters, numbers, and hyphens.
- Unique across the home platform.
- Stable across firmware updates and reboots.
- No spaces.
- No slashes, because the ID is used inside MQTT topics.

Examples:

```text
esp32-c3-test
garage-temp-01
basement-humidity-01
water-softener-01
```

The JSON payload `device` value should match the `<device-id>` segment in the MQTT topic. The current Pi code does not enforce this yet, but future validation may.

## Topic Contract

New devices should use this topic shape:

```text
home/devices/<device-id>/<message-type>
```

Recommended message types:

| Message type | Topic | Payload shape | Notes |
| --- | --- | --- | --- |
| `status` | `home/devices/<device-id>/status` | JSON object | Device health and firmware/runtime information. |
| `telemetry` | `home/devices/<device-id>/telemetry` | JSON object | Sensor readings and measurement state. |
| `availability` | `home/devices/<device-id>/availability` | Plain text | Retained `online` or `offline`; usually paired with MQTT Last Will. |
| `commands` | `home/devices/<device-id>/commands` | JSON object | Commands sent to the device. |
| `responses` | `home/devices/<device-id>/responses` | JSON object | Command acknowledgements or errors from the device. |

The current listener parses this topic shape for retained availability events. Health grouping still relies on the JSON `device` field from status and telemetry payloads.

## JSON Payload Contract

Messages intended for structured logging and the dashboard should use valid UTF-8 JSON objects.

Required field:

| Field | Type | Purpose |
| --- | --- | --- |
| `device` | string | Stable device identifier used by the health monitor. |

Currently recognized health/dashboard fields:

| Field | Type | Purpose |
| --- | --- | --- |
| `device` | string | Device name shown in the dashboard. |
| `type` | string | Message category, such as `status` or `telemetry`. |
| `count` | integer | Optional heartbeat or message counter. |
| `uptime_ms` | integer | Optional device uptime in milliseconds. |
| `wifi_rssi` | integer | Optional Wi-Fi signal strength in dBm. |

Missing fields are handled gracefully and written as blank values in CSV/dashboard output.

Additional fields are allowed. They are preserved in `data/logs/mqtt_messages.jsonl` and shown in expandable dashboard details for latest status and telemetry payloads.

## Status Messages

Status messages should describe device/runtime health.

Recommended topic:

```text
home/devices/<device-id>/status
```

Example:

```json
{"device":"garage-temp-01","type":"status","count":1,"uptime_ms":1000,"wifi_rssi":-50}
```

For the current health monitor, heartbeat freshness is `ONLINE` when a device's latest valid CSV-backed JSON message was received within 30 seconds. The dashboard renders that as `FRESH`; otherwise it renders as `STALE`. To stay fresh, a device should publish a valid JSON status or telemetry message at least every 30 seconds. A 10-15 second interval is a good current default for always-online devices.

## Telemetry Messages

Telemetry messages should contain sensor readings.

Recommended topic:

```text
home/devices/<device-id>/telemetry
```

DHT-style example:

```json
{"device":"garage-temp-01","type":"telemetry","temperature_c":22.4,"humidity_percent":47.1,"sensor_ok":true,"uptime_ms":123456}
```

Generic sensor example:

```json
{"device":"water-softener-01","type":"telemetry","water_level_percent":82,"sensor_ok":true,"uptime_ms":123456}
```

If a sensor read fails, prefer a clear boolean such as `sensor_ok:false` and avoid publishing invalid numeric values. The current platform preserves these details in JSONL and shows them in expandable dashboard details.

## Availability Messages

Availability messages should use:

```text
home/devices/<device-id>/availability
```

Recommended payloads:

```text
online
offline
```

Availability messages should be retained. Devices that support MQTT Last Will should configure the broker to publish retained `offline` to the availability topic if the device disconnects unexpectedly, then publish retained `online` after MQTT reconnects.

Plain-text availability messages are shown separately from heartbeat freshness. They are logged to `data/logs/mqtt_messages.log`, normalized into JSONL for dashboard details, and intentionally kept out of CSV so retained `offline` does not make a sleepy device look like it stopped sending data for the wrong reason.

## Commands and Responses

Command topic:

```text
home/devices/<device-id>/commands
```

Response topic:

```text
home/devices/<device-id>/responses
```

Commands should be JSON objects. The current ESP32-C3 test node supports:

```json
{"command":"read_now"}
```

```json
{"command":"set_interval","interval_seconds":30}
```

Responses should include the device ID, command name, and success state:

```json
{"device":"esp32-c3-test","command":"set_interval","success":true,"interval_seconds":30}
```

```json
{"device":"esp32-c3-test","command":"set_interval","success":false,"error":"interval_out_of_range"}
```

The Raspberry Pi listener currently logs commands and responses. It does not route commands, enforce schemas, or manage device capabilities.

## Onboarding Checklist

Use this checklist when adding a new device:

1. Choose a stable lowercase hyphenated device ID.
2. Publish under `home/devices/<device-id>/...`.
3. Include `device` in every JSON payload that should appear in health reports.
4. Publish a valid JSON `status` or `telemetry` message at least every 30 seconds if the dashboard should show the device as `ONLINE`.
5. Use retained `online` and MQTT Last Will `offline` on the availability topic when supported by the device firmware.
6. Keep command handling optional until the device needs bidirectional control.
7. Verify text log, JSONL log, CSV log, health monitor output, and dashboard display.

## Manual Test Commands

Publish a JSON status message:

```bash
mosquitto_pub -h localhost \
  -t 'home/devices/garage-temp-01/status' \
  -m '{"device":"garage-temp-01","type":"status","count":1,"uptime_ms":1000,"wifi_rssi":-50}'
```

Publish DHT-style telemetry:

```bash
mosquitto_pub -h localhost \
  -t 'home/devices/garage-temp-01/telemetry' \
  -m '{"device":"garage-temp-01","type":"telemetry","temperature_c":22.4,"humidity_percent":47.1,"sensor_ok":true,"uptime_ms":123456}'
```

Publish retained availability:

```bash
mosquitto_pub -h localhost -r \
  -t 'home/devices/garage-temp-01/availability' \
  -m 'online'
```

Run the health monitor immediately instead of waiting for the timer:

```bash
/home/zack/projects/raspberry-pi/.venv/bin/python \
  /home/zack/projects/raspberry-pi/services/health-monitor/health_monitor.py
```

Check the generated files:

```bash
tail -n 5 data/logs/mqtt_messages.log
tail -n 5 data/logs/mqtt_messages.jsonl
tail -n 5 data/logs/mqtt_messages.csv
cat data/status/device_status.json
```

## What Is Not In This Contract Yet

This contract does not add:

- A device registry.
- Per-device display rules.
- Database storage.
- MQTT authentication.
- Schema validation.
- Automatic device provisioning.
- Fleet management.
- Rich telemetry visualizations.

Those are future platform stages after the basic onboarding contract remains stable.
