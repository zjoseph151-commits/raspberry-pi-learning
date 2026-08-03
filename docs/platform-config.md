# Platform Configuration

The Raspberry Pi IoT platform uses a centralized Python configuration module:

```text
config/platform.py
```

This is the current source of truth for shared constants used by the service-owned scripts.

## Current Defaults

| Setting | Value |
| --- | --- |
| MQTT broker host | `localhost` |
| MQTT broker port | `1883` |
| MQTT topic filter | `home/#` |
| Plain MQTT log | `data/logs/mqtt_messages.log` |
| JSON Lines MQTT log | `data/logs/mqtt_messages.jsonl` |
| CSV MQTT log | `data/logs/mqtt_messages.csv` |
| Device status JSON | `data/status/device_status.json` |
| Online threshold | `30` seconds |
| Dashboard host | `0.0.0.0` |
| Dashboard port | `8080` |

## Device Onboarding Constants

The shared config also records the current device onboarding contract:

| Setting | Value |
| --- | --- |
| Device topic root | `home/devices` |
| Device topic template | `home/devices/{device_id}/{message_type}` |
| Topic suffixes | `status`, `availability`, `telemetry`, `commands`, `responses` |
| Availability values | `online`, `offline` |
| Required JSON field | `device` |
| Current health fields | `device`, `type`, `count`, `uptime_ms`, `wifi_rssi` |

The listener still subscribes to `home/#`; these constants define the preferred topic and payload shape for new devices and future platform code.

## Centralized Columns

The MQTT listener writes these CSV columns:

```text
received_at
topic
device
type
count
uptime_ms
wifi_rssi
```

The health monitor adds `status` when building device reports.

## Import Behavior

The systemd units run service scripts by absolute path while keeping:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

Each service script adds the repository root to `sys.path` before importing `config.platform`. This keeps systemd unit files unchanged while making the shared config importable from service subdirectories.

## What Is Not Added Yet

This stage does not add:

- Environment-variable overrides
- `.env` files
- MQTT authentication
- Device registry
- Per-device schemas
- Database storage

Those can be added later after the basic service layout remains stable.

## Device Readiness

New MQTT devices can be added now if they publish valid JSON under `home/#` and include a `device` field:

```json
{"device":"example-device","type":"status","count":1,"uptime_ms":1000,"wifi_rssi":-50}
```

The current platform will log the message, include valid JSON in JSONL, write fixed CSV fields, and show the device in the health dashboard after the health monitor runs. Extra status and telemetry fields appear in expandable dashboard details.

For the complete onboarding contract, see `docs/device-onboarding.md`. Rich charts, dedicated per-device pages, per-device display rules, and a registry remain future platform stages.
