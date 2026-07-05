import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from device_status import (
    CSV_COLUMNS,
    build_device_reports,
    print_health_report,
    run,
)


class DeviceStatusTests(unittest.TestCase):
    def write_csv(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_run_handles_missing_csv_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = run(csv_path)

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output.getvalue(),
                f"No CSV log found at {csv_path}.\n",
            )

    def test_run_handles_empty_csv_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text("", encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = run(csv_path)

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output.getvalue(),
                f"No device messages found in {csv_path}.\n",
            )

    def test_build_device_reports_uses_latest_message_per_device(self):
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
                "topic": "home/sensor/status",
                "device": "garage-sensor",
                "type": "heartbeat",
                "count": "9",
                "uptime_ms": "90000",
                "wifi_rssi": "-72",
            },
        ]

        reports = build_device_reports(rows, now)

        self.assertEqual(
            reports,
            [
                {
                    "device": "esp32-s3-test",
                    "received_at": "2026-07-05T11:59:45+00:00",
                    "topic": "home/esp32-s3/status",
                    "type": "heartbeat",
                    "count": "2",
                    "uptime_ms": "10000",
                    "wifi_rssi": "-57",
                    "status": "ONLINE",
                },
                {
                    "device": "garage-sensor",
                    "received_at": "2026-07-05T11:58:00+00:00",
                    "topic": "home/sensor/status",
                    "type": "heartbeat",
                    "count": "9",
                    "uptime_ms": "90000",
                    "wifi_rssi": "-72",
                    "status": "OFFLINE",
                },
            ],
        )

    def test_build_device_reports_uses_blank_values_for_missing_fields(self):
        now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            {
                "received_at": "2026-07-05T11:59:45+00:00",
                "topic": "home/esp32-s3/status",
                "device": "esp32-s3-test",
            },
        ]

        reports = build_device_reports(rows, now)

        self.assertEqual(reports[0]["type"], "")
        self.assertEqual(reports[0]["count"], "")
        self.assertEqual(reports[0]["uptime_ms"], "")
        self.assertEqual(reports[0]["wifi_rssi"], "")

    def test_print_health_report_outputs_simple_table(self):
        reports = [
            {
                "device": "esp32-s3-test",
                "received_at": "2026-07-05T11:59:45+00:00",
                "topic": "home/esp32-s3/status",
                "type": "heartbeat",
                "count": "2",
                "uptime_ms": "10000",
                "wifi_rssi": "-57",
                "status": "ONLINE",
            },
        ]
        output = io.StringIO()

        with redirect_stdout(output):
            print_health_report(reports)

        self.assertEqual(
            output.getvalue(),
            "Device Health Report\n"
            "device | status | received_at | topic | type | count | uptime_ms | wifi_rssi\n"
            "esp32-s3-test | ONLINE | 2026-07-05T11:59:45+00:00 | "
            "home/esp32-s3/status | heartbeat | 2 | 10000 | -57\n",
        )

    def test_run_reads_csv_and_prints_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "logs" / "mqtt_messages.csv"
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
                exit_code = run(csv_path, lambda: now)

            self.assertEqual(exit_code, 0)
            self.assertIn("esp32-s3-test | ONLINE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
