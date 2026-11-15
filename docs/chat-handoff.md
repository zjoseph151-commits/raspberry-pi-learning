# New Chat Handoff

This document is the starting point for a new Codex chat taking over the Raspberry Pi IoT platform work.

## Start Here

Read these files first:

1. `README.md`
2. `docs/service-layout.md`
3. `docs/platform-config.md`
4. `docs/device-onboarding.md`
5. `TODO.md`

Use `docs/current-state-architecture.md` as the historical pre-migration baseline. The current post-migration source layout is described by `docs/service-layout.md`.

## Current Repository Context

Development repository path in the current workstation chat:

```text
C:\Users\zjose\Documents\RaspberryPi\raspberry-pi-learning
```

Live Raspberry Pi project path:

```text
/home/zack/projects/raspberry-pi
```

The user makes commits manually. Do not commit, push, reset, or perform privileged deployment commands unless explicitly asked.

## Current Platform Shape

Current service-owned scripts:

```text
services/mqtt-listener/listener.py
services/health-monitor/health_monitor.py
services/health-monitor/device_status.py
services/dashboard/dashboard_server.py
```

Shared platform constants:

```text
config/platform.py
config/device_contract.py
```

Runtime data paths:

```text
data/logs/mqtt_messages.log
data/logs/mqtt_messages.jsonl
data/logs/mqtt_messages.csv
data/status/device_status.json
```

Reference systemd units:

```text
systemd/mqtt-listener.service
systemd/health-monitor.service
systemd/health-monitor.timer
systemd/iot-dashboard.service
```

Expected live service working directory:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

## Current Data Flow

```mermaid
flowchart LR
    Device["MQTT device"] --> Broker["Mosquitto localhost:1883"]
    Broker --> Listener["MQTT listener<br/>services/mqtt-listener/listener.py"]
    Listener --> TextLog["data/logs/mqtt_messages.log"]
    Listener --> JsonlLog["data/logs/mqtt_messages.jsonl"]
    Listener --> CsvLog["data/logs/mqtt_messages.csv"]
    CsvLog --> Health["Health monitor<br/>services/health-monitor/health_monitor.py"]
    JsonlLog --> Health
    TextLog --> Health
    Health --> StatusJson["data/status/device_status.json"]
    StatusJson --> Dashboard["Dashboard<br/>services/dashboard/dashboard_server.py"]
    Dashboard --> Browser["Browser<br/>http://localhost:8080"]
```

## Device Onboarding Summary

New devices should follow:

```text
home/devices/<device-id>/<message-type>
```

Current message types:

```text
status
availability
telemetry
commands
responses
```

Status and telemetry JSON must include a `device` that matches the canonical topic ID. Retained availability can also create device state without a heartbeat. The current CSV fields are:

```text
received_at
topic
device
type
count
uptime_ms
wifi_rssi
```

Plain-text retained availability messages are logged and projected into device state separately from heartbeat freshness. Declared sleepy devices use three publish intervals (up to one hour) as their freshness window.

## Known Important Caveats

- The platform currently has no SQLite database, device registry, MQTT authentication, per-device telemetry schema validation, or dedicated per-device dashboard pages.
- Canonical topics are parsed and validated; older noncanonical `home/#` topics retain legacy behavior.
- Canonical commands and responses are archived but never refresh heartbeat state. Invalid canonical JSON is retained in JSONL with a `validation_error` and excluded from device state.
- The dashboard can publish the four `birdfeeder-01` commands. A successful `record_now` reply means recording started, not that clip upload completed.
- The dashboard also supports the four `front-porch-camera-01` commands (`start_stream`, `stop_stream`, `stream_info`, `status_now`) and its port-80 MJPEG URL.
- Both device command panels are disabled on the ordinary LAN page. Use an authenticated SSH tunnel (`ssh -N -L 127.0.0.1:18080:127.0.0.1:8080 zack@<pi-ip>`) and open `http://127.0.0.1:18080` for actions. SSH login provides authentication; the dashboard has no separate password. Direct local Pi access can also act.
- The dashboard Services table reads the local Mosquitto, MQTT listener, health-monitor timer/service, and dashboard systemd units. It offers fixed restart actions on the SSH-tunneled page and `Run now` for the one-shot health monitor; the ordinary LAN page is read-only. Install `systemd/iot-dashboard-restarts.sudoers` on the Pi as `/etc/sudoers.d/iot-dashboard-restarts` (root-owned, mode `0440`) before using the buttons. A successful response means the systemd job was queued, not completed.
- ESP32 firmware version references are currently aligned to `0.2.1`; when changing firmware versions, update `src/main.cpp`, README examples, and firmware source-contract tests together.
- The default `python -m unittest discover` command does not find tests from the repository root in the current layout; use `python -m unittest discover -s tests -v`.

## Useful Verification Commands

Run the focused Pi platform test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_platform_config tests.test_device_contract tests.test_device_pipeline tests.test_legacy_entrypoints tests.test_mqtt_listener tests.test_device_status tests.test_health_monitor tests.test_dashboard_server -v
```

Run broader Python test discovery:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Check whitespace in tracked files:

```powershell
git diff --check
```

On the Raspberry Pi, check live services:

```bash
systemctl status mqtt-listener.service --no-pager
systemctl status health-monitor.timer --no-pager
systemctl status health-monitor.service --no-pager
systemctl status iot-dashboard.service --no-pager
```

## Generic Integration Prompt

Use this prompt in separate project chats when you want to prepare another project for integration into this IoT platform.

```text
I want to integrate this project into my Raspberry Pi IoT platform.

Important constraints:
- Treat the repository currently open in this chat as the source project to inspect.
- Do not modify, move, rename, refactor, delete, stage, commit, or push anything yet.
- Use the Raspberry Pi IoT platform repository and its documentation as a reference only.
- Do not change the Raspberry Pi IoT platform repository from this chat.
- Do not install packages or change system services unless I explicitly approve that later.
- First produce an integration inventory and plan only.

Reference platform context:
- Live Raspberry Pi platform path: /home/zack/projects/raspberry-pi
- Main platform docs to follow:
  - README.md
  - docs/service-layout.md
  - docs/platform-config.md
  - docs/device-onboarding.md
  - TODO.md
- Current MQTT broker target: localhost:1883 on the Raspberry Pi.
- Current listener subscription: home/#
- Preferred device topic contract:
  home/devices/<device-id>/<message-type>
- Supported message types:
  status, availability, telemetry, commands, responses
- Status and telemetry JSON must include a stable device field matching the canonical topic ID; commands may omit it.
- Common status/telemetry payload fields are:
  device, type, count, uptime_ms, wifi_rssi
- Extra telemetry fields are allowed, preserved in JSONL, and shown in expandable dashboard details.
- Plain-text retained availability messages are logged and shown separately from heartbeat freshness; they do not drive dashboard FRESH/STALE state.
- Sleepy devices should publish `sleepy:true` with `read_interval_ms` or `sleep_interval_seconds` in status so slow reporting stays fresh through three declared intervals.

Your task:
1. Inspect the current source project read-only.
2. Identify what the project does and how it runs today.
3. Identify all existing MQTT usage, topics, payloads, device IDs, network assumptions, secrets/configuration, dependencies, scripts, services, and hardware assumptions.
4. Compare the project against the IoT platform onboarding contract.
5. Propose the smallest safe changes needed to integrate it with the platform.
6. Identify what should happen in the source project versus what, if anything, should happen later in the platform repo.
7. Provide a manual verification plan using mosquitto_pub/mosquitto_sub, service logs, platform logs, health monitor output, and dashboard checks.
8. Clearly list risks, unknowns, and questions.

Do not implement the integration until I approve the plan.
```

If the target project chat cannot access the Raspberry Pi platform repository or docs, ask the user to provide the relevant files before inventing platform details.

## Recommended Next Work

Use `TODO.md` as the next-stage backlog. The most useful next step is usually to choose the first outside project to inventory, then decide whether that integration should stay plan-only or become the first real exercise of the onboarding contract.
