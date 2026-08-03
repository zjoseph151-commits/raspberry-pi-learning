import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATED_HEALTH_MONITOR_PATH = (
    PROJECT_ROOT / "services" / "health-monitor" / "health_monitor.py"
)
MIGRATED_DEVICE_STATUS_PATH = (
    PROJECT_ROOT / "services" / "health-monitor" / "device_status.py"
)


def load_migrated_health_monitor():
    spec = importlib.util.spec_from_file_location(
        "migrated_health_monitor",
        MIGRATED_HEALTH_MONITOR_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


health_monitor = load_migrated_health_monitor()

CSV_COLUMNS = health_monitor.device_status.CSV_COLUMNS
build_status_report = health_monitor.build_status_report
parse_availability_log_line = health_monitor.parse_availability_log_line
run = health_monitor.run
write_status_report = health_monitor.write_status_report


class HealthMonitorTests(unittest.TestCase):
    def write_csv(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_migrated_health_monitor_module_loads_from_new_service_path(self):
        self.assertTrue(MIGRATED_HEALTH_MONITOR_PATH.exists())
        self.assertEqual(
            health_monitor.CSV_PATH,
            Path("data/logs/mqtt_messages.csv"),
        )
        self.assertEqual(
            health_monitor.STATUS_JSON_PATH,
            Path("data/status/device_status.json"),
        )
        self.assertEqual(
            health_monitor.JSONL_PATH,
            Path("data/logs/mqtt_messages.jsonl"),
        )
        self.assertEqual(
            health_monitor.LOG_PATH,
            Path("data/logs/mqtt_messages.log"),
        )
        self.assertEqual(
            Path(health_monitor.device_status.__file__).resolve(),
            MIGRATED_DEVICE_STATUS_PATH,
        )

    def test_build_status_report_uses_latest_message_per_device(self):
        now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            {
                "received_at": "2026-07-05T11:59:00+00:00",
                "topic": "home/esp32-s3/status",
                "device": "esp32-s3-test",
                "type": "heartbeat",
                "count": "1",
                "uptime_ms": "5000",
                "wifi_rssi": "-60",
            },
            {
                "received_at": "2026-07-05T11:59:45+00:00",
                "topic": "home/esp32-s3/status",
                "device": "esp32-s3-test",
                "type": "heartbeat",
                "count": "2",
                "uptime_ms": "10000",
                "wifi_rssi": "-57",
            },
            {
                "received_at": "2026-07-05T11:58:00+00:00",
                "topic": "home/garage/status",
                "device": "garage-sensor",
                "type": "heartbeat",
                "count": "9",
                "uptime_ms": "90000",
                "wifi_rssi": "-72",
            },
        ]

        source_path = Path("data/logs/mqtt_messages.csv")

        report = build_status_report(rows, now, source_path)

        self.assertEqual(
            report,
            {
                "generated_at": "2026-07-05T12:00:00+00:00",
                "source": str(source_path),
                "devices": [
                    {
                        "device": "esp32-s3-test",
                        "status": "ONLINE",
                        "received_at": "2026-07-05T11:59:45+00:00",
                        "topic": "home/esp32-s3/status",
                        "type": "heartbeat",
                        "count": "2",
                        "uptime_ms": "10000",
                        "wifi_rssi": "-57",
                    },
                    {
                        "device": "garage-sensor",
                        "status": "OFFLINE",
                        "received_at": "2026-07-05T11:58:00+00:00",
                        "topic": "home/garage/status",
                        "type": "heartbeat",
                        "count": "9",
                        "uptime_ms": "90000",
                        "wifi_rssi": "-72",
                    },
                ],
            },
        )

    def test_parse_availability_log_line_structures_legacy_text_log(self):
        record = parse_availability_log_line(
            "2026-08-03T12:00:01+00:00 | "
            "topic=home/devices/esp32-c3-climate-01/availability | "
            "payload=offline\n"
        )

        self.assertEqual(
            record,
            {
                "received_at": "2026-08-03T12:00:01+00:00",
                "topic": "home/devices/esp32-c3-climate-01/availability",
                "payload": {
                    "device": "esp32-c3-climate-01",
                    "type": "availability",
                    "availability": "offline",
                },
            },
        )

    def test_build_status_report_enriches_dashboard_details(self):
        now = datetime(2026, 8, 3, 12, 1, 0, tzinfo=timezone.utc)
        rows = [
            {
                "received_at": "2026-08-03T12:00:45+00:00",
                "topic": "home/devices/esp32-c3-climate-01/telemetry",
                "device": "esp32-c3-climate-01",
                "type": "telemetry",
                "count": "2",
                "uptime_ms": "120000",
                "wifi_rssi": "-55",
            },
        ]
        detail_records = [
            {
                "received_at": "2026-08-03T12:00:40+00:00",
                "topic": "home/devices/esp32-c3-climate-01/status",
                "payload": {
                    "device": "esp32-c3-climate-01",
                    "type": "status",
                    "count": 2,
                    "firmware_version": "0.4.0",
                    "sleepy": True,
                    "read_interval_ms": 60000,
                },
            },
            {
                "received_at": "2026-08-03T12:00:45+00:00",
                "topic": "home/devices/esp32-c3-climate-01/telemetry",
                "payload": {
                    "device": "esp32-c3-climate-01",
                    "type": "telemetry",
                    "count": 2,
                    "temperature_f": 71.6,
                    "humidity_percent": 45.0,
                    "sensor_ok": True,
                    "source": "timer",
                },
            },
            {
                "received_at": "2026-08-03T12:00:50+00:00",
                "topic": "home/devices/esp32-c3-climate-01/availability",
                "payload": {
                    "device": "esp32-c3-climate-01",
                    "type": "availability",
                    "availability": "offline",
                },
            },
        ]

        report = build_status_report(
            rows,
            now,
            Path("data/logs/mqtt_messages.csv"),
            detail_records=detail_records,
        )
        device = report["devices"][0]

        self.assertEqual(device["device"], "esp32-c3-climate-01")
        self.assertEqual(device["status"], "ONLINE")
        self.assertEqual(device["availability"]["state"], "offline")
        self.assertEqual(
            device["latest_status"]["fields"]["firmware_version"],
            "0.4.0",
        )
        self.assertTrue(device["latest_status"]["fields"]["sleepy"])
        self.assertEqual(
            device["latest_telemetry"]["fields"]["temperature_f"],
            71.6,
        )
        self.assertTrue(device["latest_telemetry"]["fields"]["sensor_ok"])

    def test_write_status_report_creates_parent_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "data" / "status" / "device_status.json"
            report = {
                "generated_at": "2026-07-05T12:00:00+00:00",
                "source": "data/logs/mqtt_messages.csv",
                "devices": [],
            }

            write_status_report(json_path, report)

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), report)

    def test_run_handles_missing_csv_and_writes_empty_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "data" / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "data" / "status" / "device_status.json"
            now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = run(csv_path, json_path, lambda: now)

            expected = {
                "generated_at": "2026-07-05T12:00:00+00:00",
                "source": str(csv_path),
                "devices": [],
                "message": f"No CSV log found at {csv_path}.",
            }
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), expected)
            self.assertEqual(json.loads(output.getvalue()), expected)

    def test_run_handles_empty_csv_and_writes_empty_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "data" / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "data" / "status" / "device_status.json"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text("", encoding="utf-8")
            now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = run(csv_path, json_path, lambda: now)

            expected = {
                "generated_at": "2026-07-05T12:00:00+00:00",
                "source": str(csv_path),
                "devices": [],
                "message": f"No device messages found in {csv_path}.",
            }
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), expected)
            self.assertEqual(json.loads(output.getvalue()), expected)

    def test_run_writes_and_prints_status_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "data" / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "data" / "status" / "device_status.json"
            self.write_csv(
                csv_path,
                [
                    {
                        "received_at": "2026-07-05T11:59:45+00:00",
                        "topic": "home/esp32-s3/status",
                        "device": "esp32-s3-test",
                        "type": "heartbeat",
                        "count": "2",
                        "uptime_ms": "10000",
                        "wifi_rssi": "-57",
                    },
                ],
            )
            now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = run(csv_path, json_path, lambda: now)

            written_report = json.loads(json_path.read_text(encoding="utf-8"))
            printed_report = json.loads(output.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(written_report, printed_report)
            self.assertEqual(written_report["devices"][0]["device"], "esp32-s3-test")
            self.assertEqual(written_report["devices"][0]["status"], "ONLINE")


if __name__ == "__main__":
    unittest.main()
