import importlib.util
from pathlib import Path
import unittest

from config import platform

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PlatformConfigTests(unittest.TestCase):
    def test_default_platform_config_values(self):
        self.assertEqual(platform.MQTT_BROKER_HOST, "localhost")
        self.assertEqual(platform.MQTT_BROKER_PORT, 1883)
        self.assertEqual(platform.MQTT_TOPIC_FILTER, "home/#")
        self.assertEqual(platform.MQTT_LOG_PATH, Path("data/logs/mqtt_messages.log"))
        self.assertEqual(
            platform.MQTT_JSONL_PATH,
            Path("data/logs/mqtt_messages.jsonl"),
        )
        self.assertEqual(platform.MQTT_CSV_PATH, Path("data/logs/mqtt_messages.csv"))
        self.assertEqual(
            platform.DEVICE_STATUS_PATH,
            Path("data/status/device_status.json"),
        )
        self.assertEqual(platform.ONLINE_THRESHOLD_SECONDS, 30)
        self.assertEqual(platform.DASHBOARD_HOST, "0.0.0.0")
        self.assertEqual(platform.DASHBOARD_PORT, 8080)

    def test_csv_and_report_columns_are_centralized(self):
        self.assertEqual(
            platform.MQTT_CSV_COLUMNS,
            [
                "received_at",
                "topic",
                "device",
                "type",
                "count",
                "uptime_ms",
                "wifi_rssi",
            ],
        )
        self.assertEqual(
            platform.DEVICE_REPORT_COLUMNS,
            [
                "device",
                "status",
                "received_at",
                "topic",
                "type",
                "count",
                "uptime_ms",
                "wifi_rssi",
            ],
        )

    def test_services_use_platform_config_aliases(self):
        listener = load_module(
            "config_test_listener",
            PROJECT_ROOT / "services" / "mqtt-listener" / "listener.py",
        )
        device_status = load_module(
            "config_test_device_status",
            PROJECT_ROOT / "services" / "health-monitor" / "device_status.py",
        )
        health_monitor = load_module(
            "config_test_health_monitor",
            PROJECT_ROOT / "services" / "health-monitor" / "health_monitor.py",
        )
        dashboard = load_module(
            "config_test_dashboard",
            PROJECT_ROOT / "services" / "dashboard" / "dashboard_server.py",
        )

        self.assertEqual(listener.BROKER_HOST, platform.MQTT_BROKER_HOST)
        self.assertEqual(listener.BROKER_PORT, platform.MQTT_BROKER_PORT)
        self.assertEqual(listener.TOPIC_FILTER, platform.MQTT_TOPIC_FILTER)
        self.assertEqual(listener.LOG_PATH, platform.MQTT_LOG_PATH)
        self.assertEqual(listener.JSONL_PATH, platform.MQTT_JSONL_PATH)
        self.assertEqual(listener.CSV_PATH, platform.MQTT_CSV_PATH)
        self.assertEqual(listener.CSV_COLUMNS, platform.MQTT_CSV_COLUMNS)

        self.assertEqual(device_status.CSV_PATH, platform.MQTT_CSV_PATH)
        self.assertEqual(
            device_status.ONLINE_THRESHOLD.total_seconds(),
            platform.ONLINE_THRESHOLD_SECONDS,
        )
        self.assertEqual(device_status.CSV_COLUMNS, platform.MQTT_CSV_COLUMNS)
        self.assertEqual(device_status.REPORT_COLUMNS, platform.DEVICE_REPORT_COLUMNS)

        self.assertEqual(health_monitor.CSV_PATH, platform.MQTT_CSV_PATH)
        self.assertEqual(health_monitor.STATUS_JSON_PATH, platform.DEVICE_STATUS_PATH)

        self.assertEqual(dashboard.STATUS_JSON_PATH, platform.DEVICE_STATUS_PATH)
        self.assertEqual(dashboard.HOST, platform.DASHBOARD_HOST)
        self.assertEqual(dashboard.PORT, platform.DASHBOARD_PORT)


if __name__ == "__main__":
    unittest.main()
