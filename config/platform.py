from __future__ import annotations

from pathlib import Path

# MQTT broker and subscription defaults.
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
MQTT_TOPIC_FILTER = "home/#"

# Device onboarding contract. The listener still subscribes to `home/#`;
# canonical device topics are parsed and validated before updating state.
DEVICE_TOPIC_ROOT = "home/devices"
DEVICE_TOPIC_TEMPLATE = f"{DEVICE_TOPIC_ROOT}/{{device_id}}/{{message_type}}"
DEVICE_TOPIC_SUFFIXES = [
    "status",
    "availability",
    "telemetry",
    "commands",
    "responses",
]
DEVICE_AVAILABILITY_VALUES = [
    "online",
    "offline",
]

# Runtime data paths. These remain relative to the repository root because the
# systemd units intentionally keep WorkingDirectory at the project root.
MQTT_LOG_PATH = Path("data/logs/mqtt_messages.log")
MQTT_JSONL_PATH = Path("data/logs/mqtt_messages.jsonl")
MQTT_CSV_PATH = Path("data/logs/mqtt_messages.csv")
DEVICE_STATUS_PATH = Path("data/status/device_status.json")
TELEMETRY_HISTORY_PATH = Path("data/history/telemetry.sqlite3")
HISTORY_CLIMATE_DEVICE_ID = "esp32-c3-climate-01"
HISTORY_CLIMATE_METRIC_UNITS = {"temperature_c": "C", "humidity_percent": "% RH"}

# Structured JSON/CSV fields used by the listener, health monitor, and
# dashboard. Status and telemetry require `device`; commands may omit it.
DEVICE_REQUIRED_JSON_FIELDS = [
    "device",
]
DEVICE_HEALTH_FIELDS = [
    "device",
    "type",
    "count",
    "uptime_ms",
    "wifi_rssi",
]
MQTT_CSV_COLUMNS = [
    "received_at",
    "topic",
    *DEVICE_HEALTH_FIELDS,
]
DEVICE_REPORT_COLUMNS = [
    "device",
    "status",
    *MQTT_CSV_COLUMNS[:2],
    *MQTT_CSV_COLUMNS[3:],
]

# Device health behavior.
ONLINE_THRESHOLD_SECONDS = 30
SLEEPY_STALE_AFTER_INTERVALS = 3
MAX_SLEEPY_STALE_AFTER_SECONDS = 3600

# Local dashboard binding.
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8080
DASHBOARD_HIDDEN_DEVICE_IDS = frozenset({
    "esp32-c3-test",
    "esp32-s3-test",
    "migration-test",
})
