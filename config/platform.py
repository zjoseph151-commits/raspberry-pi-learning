from __future__ import annotations

from pathlib import Path

# MQTT broker and subscription defaults.
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
MQTT_TOPIC_FILTER = "home/#"

# Runtime data paths. These remain relative to the repository root because the
# systemd units intentionally keep WorkingDirectory at the project root.
MQTT_LOG_PATH = Path("data/logs/mqtt_messages.log")
MQTT_JSONL_PATH = Path("data/logs/mqtt_messages.jsonl")
MQTT_CSV_PATH = Path("data/logs/mqtt_messages.csv")
DEVICE_STATUS_PATH = Path("data/status/device_status.json")

# Structured CSV fields written by the listener and read by the health monitor.
MQTT_CSV_COLUMNS = [
    "received_at",
    "topic",
    "device",
    "type",
    "count",
    "uptime_ms",
    "wifi_rssi",
]
DEVICE_REPORT_COLUMNS = [
    "device",
    "status",
    *MQTT_CSV_COLUMNS[:2],
    *MQTT_CSV_COLUMNS[3:],
]

# Device health behavior.
ONLINE_THRESHOLD_SECONDS = 30

# Local dashboard binding.
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8080
