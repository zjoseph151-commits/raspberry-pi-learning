import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from device_status import CSV_COLUMNS
from health_monitor import build_status_report, run, write_status_report


class HealthMonitorTests(unittest.TestCase):
    def write_csv(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

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

        source_path = Path("logs/mqtt_messages.csv")

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

    def test_write_status_report_creates_parent_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "logs" / "device_status.json"
            report = {
                "generated_at": "2026-07-05T12:00:00+00:00",
                "source": "logs/mqtt_messages.csv",
                "devices": [],
            }

            write_status_report(json_path, report)

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), report)

    def test_run_handles_missing_csv_and_writes_empty_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "logs" / "device_status.json"
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
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "logs" / "device_status.json"
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
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
            json_path = Path(temp_dir) / "logs" / "device_status.json"
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
