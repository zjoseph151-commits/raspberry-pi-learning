# Device Onboarding Contract

This document defines how new MQTT devices publish to the current Raspberry Pi IoT platform.

The platform is ready for additional MQTT devices that follow this contract. Messages are logged in JSONL, while validated status and telemetry update the CSV-backed health snapshot and dashboard. Per-device schemas, registries, and long-term database storage are future stages.

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
- Valid canonical `status` and `telemetry` JSON objects produce fixed-column CSV rows in `data/logs/mqtt_messages.csv`. Canonical `commands`, `responses`, and `availability` do not refresh heartbeat state.
- Canonical JSON with a malformed topic, mismatched `device` or `type`, or missing command/response fields remains in JSONL with a `validation_error` but does not update CSV-backed device state.
- If the payload is retained plain-text `online` or `offline` on `home/devices/<device-id>/availability`, it is also normalized into `data/logs/mqtt_messages.jsonl` as a structured availability event.
- Other non-JSON payloads are kept in the text log only.

The health monitor reads the CSV, JSONL, and legacy availability text log, validates canonical history again, and writes a derived device-state snapshot to `data/status/device_status.json`. Archived MQTT payloads are not modified by this projection.

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

For canonical topics, the JSON payload `device` must match the `<device-id>` segment. The listener and health monitor enforce this. Older noncanonical topics under `home/#` remain accepted for compatibility.

## Topic Contract

New devices should use this topic shape:

```text
home/devices/<device-id>/<message-type>
```

Supported canonical message types:

| Message type | Topic | Payload shape | Notes |
| --- | --- | --- | --- |
| `status` | `home/devices/<device-id>/status` | JSON object | Device health and firmware/runtime information. |
| `telemetry` | `home/devices/<device-id>/telemetry` | JSON object | Sensor readings and measurement state. |
| `availability` | `home/devices/<device-id>/availability` | Plain text | Retained `online` or `offline`; usually paired with MQTT Last Will. |
| `commands` | `home/devices/<device-id>/commands` | JSON object | Commands sent to the device. |
| `responses` | `home/devices/<device-id>/responses` | JSON object | Command acknowledgements or errors from the device. |

The listener parses this topic shape for all five message types. The topic supplies the message type when `type` is omitted from a status or telemetry payload.

## JSON Payload Contract

Messages intended for structured logging and the dashboard should use valid UTF-8 JSON objects.

Minimum JSON fields for canonical topics:

| Topic | Required fields | Notes |
| --- | --- | --- |
| `status` | `device` (string) | Runtime fields such as `sleepy`, `read_interval_ms`, and `sleep_interval_seconds` are optional. |
| `telemetry` | `device` (string) | Measurements are device-specific; no universal measurement field is required. |
| `commands` | `command` (nonempty string) | `device` may be omitted, but must match the topic if present. |
| `responses` | `device` (string), `command` (nonempty string), `success` (boolean) | The device ID must match the topic. |

For these JSON topics, an optional `type` field must match the topic suffix. `availability` normally uses retained plain-text `online` or `offline`, not JSON.

Currently recognized health/dashboard fields:

| Field | Type | Purpose |
| --- | --- | --- |
| `device` | string | Device name shown in the dashboard. |
| `type` | string | Message category, such as `status` or `telemetry`. |
| `count` | integer | Optional heartbeat or message counter. |
| `uptime_ms` | integer | Optional device uptime in milliseconds. |
| `wifi_rssi` | integer | Optional Wi-Fi signal strength in dBm. |

Missing optional fields are written as blank values in CSV/dashboard output. Missing required fields on canonical topics are archived with a validation error and excluded from device state.

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

By default, heartbeat freshness is `ONLINE` when the latest valid status or telemetry was received within 30 seconds. The dashboard renders this as `FRESH` or `STALE`. A 10-15 second interval remains a good default for always-online devices. For a sleepy device, include `sleepy:true` and a positive integer `read_interval_ms` or `sleep_interval_seconds` in status. `read_interval_ms` takes precedence when both are present. The freshness window then becomes three declared intervals, with a 30-second floor and a one-hour cap. A 60-second cycle remains fresh for 180 seconds; a five-minute cycle remains fresh for 15 minutes.

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

Plain-text availability messages are logged to `data/logs/mqtt_messages.log`, normalized into JSONL, and treated as device state. They remain outside CSV so a retained `offline` does not refresh heartbeat freshness.

The dashboard shows a combined health label alongside heartbeat freshness and availability:

| Health | Meaning |
| --- | --- |
| `HEALTHY` | Recent heartbeat and availability `online` from a non-sleepy device. |
| `SLEEPING` | Recent heartbeat from a declared sleepy device, regardless of retained availability. |
| `OFFLINE` | Availability `offline` without a recent sleepy heartbeat. |
| `STALE` | Heartbeat missed its freshness window, without a definitive non-sleepy `offline`. |
| `RECENT` | Recent heartbeat with unknown availability. |
| `ONLINE` | Availability `online` but no heartbeat has been observed. |
| `UNKNOWN` | Neither heartbeat nor availability is known. |

A sleepy device that misses three cycles changes from `SLEEPING` to `STALE`; an expected clean disconnect alone does not mean failure. Availability remains visible separately, since some sleepy devices retain `online` while asleep.

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

The Raspberry Pi listener logs commands and responses but does not route them or manage capabilities. It validates the minimum canonical fields above and never uses command/response traffic as a heartbeat.

## Onboarding Checklist

Use this checklist when adding a new device:

1. Choose a stable lowercase hyphenated device ID.
2. Publish under `home/devices/<device-id>/...`.
3. Include `device` in every JSON payload that should appear in health reports.
4. Publish valid JSON `status` or `telemetry` at least every 30 seconds for default freshness, or declare `sleepy:true` with `read_interval_ms` or `sleep_interval_seconds` in status for a longer cycle.
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
- Per-device telemetry schemas and measurement validation.
- Automatic device provisioning.
- Fleet management.
- Rich telemetry visualizations.

Those are future platform stages after the basic onboarding contract remains stable.
