import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LegacyEntrypointTests(unittest.TestCase):
    def test_device_status_wrapper_delegates_to_service_helper(self):
        module = load_module(
            "legacy_device_status_wrapper",
            PROJECT_ROOT / "device_status.py",
        )
        target_path = (
            PROJECT_ROOT / "services" / "health-monitor" / "device_status.py"
        )

        self.assertEqual(module.LEGACY_TARGET_PATH, target_path)
        self.assertEqual(module.CSV_PATH, Path("data/logs/mqtt_messages.csv"))
        self.assertEqual(module.ONLINE_THRESHOLD.total_seconds(), 30)
        self.assertEqual(
            Path(module.build_device_reports.__code__.co_filename).resolve(),
            target_path,
        )

    def test_health_monitor_wrapper_delegates_to_service_entrypoint(self):
        module = load_module(
            "legacy_health_monitor_wrapper",
            PROJECT_ROOT / "health_monitor.py",
        )
        target_path = (
            PROJECT_ROOT / "services" / "health-monitor" / "health_monitor.py"
        )
        helper_path = (
            PROJECT_ROOT / "services" / "health-monitor" / "device_status.py"
        )

        self.assertEqual(module.LEGACY_TARGET_PATH, target_path)
        self.assertEqual(module.CSV_PATH, Path("data/logs/mqtt_messages.csv"))
        self.assertEqual(
            module.STATUS_JSON_PATH,
            Path("data/status/device_status.json"),
        )
        self.assertEqual(Path(module.device_status.__file__).resolve(), helper_path)
        self.assertEqual(
            Path(module.build_status_report.__code__.co_filename).resolve(),
            target_path,
        )

    def test_mqtt_listener_wrapper_delegates_to_service_listener(self):
        module = load_module(
            "legacy_mqtt_listener_wrapper",
            PROJECT_ROOT / "mqtt_listener" / "listener.py",
        )
        target_path = (
            PROJECT_ROOT / "services" / "mqtt-listener" / "listener.py"
        )
        timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)

        self.assertEqual(module.LEGACY_TARGET_PATH, target_path)
        self.assertEqual(module.BROKER_HOST, "localhost")
        self.assertEqual(module.BROKER_PORT, 1883)
        self.assertEqual(module.TOPIC_FILTER, "home/#")
        self.assertEqual(module.LOG_PATH, Path("data/logs/mqtt_messages.log"))
        self.assertEqual(
            module.format_log_line(timestamp, "home/test", b'{"device":"test"}'),
            "2026-07-03T12:34:56+00:00 | topic=home/test | "
            'device=test | type= | payload={"device":"test"}',
        )
        self.assertEqual(
            Path(module.format_log_line.__code__.co_filename).resolve(),
            target_path,
        )

    def test_dashboard_wrapper_delegates_to_service_dashboard(self):
        module = load_module(
            "legacy_dashboard_wrapper",
            PROJECT_ROOT / "dashboard_server.py",
        )
        target_path = (
            PROJECT_ROOT / "services" / "dashboard" / "dashboard_server.py"
        )

        self.assertEqual(module.LEGACY_TARGET_PATH, target_path)
        self.assertEqual(
            module.STATUS_JSON_PATH,
            Path("data/status/device_status.json"),
        )
        self.assertEqual(module.HOST, "0.0.0.0")
        self.assertEqual(module.PORT, 8080)
        self.assertIn(
            "<title>Pi IoT Dashboard</title>",
            module.build_dashboard_html({"generated_at": "", "devices": []}),
        )
        self.assertEqual(
            Path(module.build_dashboard_html.__code__.co_filename).resolve(),
            target_path,
        )


if __name__ == "__main__":
    unittest.main()
