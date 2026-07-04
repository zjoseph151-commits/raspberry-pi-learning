import csv
import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from mqtt_listener.listener import (
    CSV_PATH,
    JSONL_PATH,
    append_log_line,
    decode_payload,
    format_log_line,
    handle_message,
    parse_json_payload,
)


class FakeMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class MqttListenerTests(unittest.TestCase):
    def test_decode_payload_returns_text_for_utf8_bytes(self):
        self.assertEqual(decode_payload(b'{"status":"online"}'), '{"status":"online"}')

    def test_decode_payload_replaces_invalid_utf8_bytes(self):
        self.assertEqual(decode_payload(b"temperature:\xff"), "temperature:\ufffd")

    def test_parse_json_payload_returns_object_for_valid_json(self):
        parsed = parse_json_payload(
            '{"device":"esp32-s3-test","type":"heartbeat","count":7}'
        )

        self.assertEqual(
            parsed,
            {"device": "esp32-s3-test", "type": "heartbeat", "count": 7},
        )

    def test_parse_json_payload_returns_none_for_invalid_json(self):
        self.assertIsNone(parse_json_payload("not json"))

    def test_format_log_line_includes_structured_fields_for_valid_json(self):
        timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)
        payload = (
            b'{"device":"esp32-s3-test","type":"heartbeat","count":7,'
            b'"uptime_ms":12345,"wifi_rssi":-57}'
        )

        line = format_log_line(timestamp, "home/esp32-s3/status", payload)

        self.assertEqual(
            line,
            "2026-07-03T12:34:56+00:00 | "
            "topic=home/esp32-s3/status | device=esp32-s3-test | "
            'type=heartbeat | payload={"device":"esp32-s3-test",'
            '"type":"heartbeat","count":7,"uptime_ms":12345,"wifi_rssi":-57}',
        )

    def test_format_log_line_uses_raw_payload_for_invalid_json(self):
        timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)

        line = format_log_line(timestamp, "home/sensor/raw", b"not json")

        self.assertEqual(
            line,
            "2026-07-03T12:34:56+00:00 | "
            "topic=home/sensor/raw | payload=not json",
        )

    def test_append_log_line_creates_parent_folder_and_appends_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"

            append_log_line(log_path, "first")
            append_log_line(log_path, "second")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "first\nsecond\n")

    def test_handle_message_prints_and_logs_json_message_to_all_structured_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"
            jsonl_path = Path(temp_dir) / JSONL_PATH
            csv_path = Path(temp_dir) / CSV_PATH
            timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)
            payload = (
                b'{"device":"esp32-s3-test","type":"heartbeat","count":7,'
                b'"uptime_ms":12345,"wifi_rssi":-57}'
            )
            message = FakeMessage("home/esp32-s3/status", payload)
            output = io.StringIO()

            with redirect_stdout(output):
                handle_message(
                    message,
                    log_path,
                    lambda: timestamp,
                    jsonl_path=jsonl_path,
                    csv_path=csv_path,
                )

            expected = (
                "2026-07-03T12:34:56+00:00 | "
                "topic=home/esp32-s3/status | device=esp32-s3-test | "
                'type=heartbeat | payload={"device":"esp32-s3-test",'
                '"type":"heartbeat","count":7,"uptime_ms":12345,"wifi_rssi":-57}\n'
            )
            self.assertEqual(output.getvalue(), expected)
            self.assertEqual(log_path.read_text(encoding="utf-8"), expected)

            jsonl_records = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(jsonl_records), 1)
            self.assertEqual(
                json.loads(jsonl_records[0]),
                {
                    "received_at": "2026-07-03T12:34:56+00:00",
                    "topic": "home/esp32-s3/status",
                    "payload": {
                        "device": "esp32-s3-test",
                        "type": "heartbeat",
                        "count": 7,
                        "uptime_ms": 12345,
                        "wifi_rssi": -57,
                    },
                },
            )

            with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)
                fieldnames = reader.fieldnames

            self.assertEqual(
                fieldnames,
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
                rows,
                [
                    {
                        "received_at": "2026-07-03T12:34:56+00:00",
                        "topic": "home/esp32-s3/status",
                        "device": "esp32-s3-test",
                        "type": "heartbeat",
                        "count": "7",
                        "uptime_ms": "12345",
                        "wifi_rssi": "-57",
                    }
                ],
            )

    def test_handle_message_writes_blank_csv_values_for_missing_json_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"
            jsonl_path = Path(temp_dir) / JSONL_PATH
            csv_path = Path(temp_dir) / CSV_PATH
            timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)
            message = FakeMessage("home/esp32-s3/status", b'{"device":"esp32-s3-test"}')

            with redirect_stdout(io.StringIO()):
                handle_message(
                    message,
                    log_path,
                    lambda: timestamp,
                    jsonl_path=jsonl_path,
                    csv_path=csv_path,
                )

            with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

            self.assertEqual(
                rows,
                [
                    {
                        "received_at": "2026-07-03T12:34:56+00:00",
                        "topic": "home/esp32-s3/status",
                        "device": "esp32-s3-test",
                        "type": "",
                        "count": "",
                        "uptime_ms": "",
                        "wifi_rssi": "",
                    }
                ],
            )

    def test_handle_message_does_not_write_invalid_json_to_jsonl_or_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"
            jsonl_path = Path(temp_dir) / JSONL_PATH
            csv_path = Path(temp_dir) / CSV_PATH
            timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)
            message = FakeMessage("home/sensor/raw", b"not json")
            output = io.StringIO()

            with redirect_stdout(output):
                handle_message(
                    message,
                    log_path,
                    lambda: timestamp,
                    jsonl_path=jsonl_path,
                    csv_path=csv_path,
                )

            expected = (
                "2026-07-03T12:34:56+00:00 | "
                "topic=home/sensor/raw | payload=not json\n"
            )
            self.assertEqual(output.getvalue(), expected)
            self.assertEqual(log_path.read_text(encoding="utf-8"), expected)
            self.assertFalse(jsonl_path.exists())
            self.assertFalse(csv_path.exists())


if __name__ == "__main__":
    unittest.main()
