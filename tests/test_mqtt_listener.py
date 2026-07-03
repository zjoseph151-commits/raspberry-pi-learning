import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from mqtt_listener.listener import (
    append_log_line,
    decode_payload,
    format_log_line,
    handle_message,
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

    def test_format_log_line_includes_timestamp_topic_and_payload(self):
        timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)

        line = format_log_line(timestamp, "home/esp32/status", b"online")

        self.assertEqual(
            line,
            "2026-07-03T12:34:56+00:00 | topic=home/esp32/status | payload=online",
        )

    def test_append_log_line_creates_parent_folder_and_appends_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"

            append_log_line(log_path, "first")
            append_log_line(log_path, "second")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "first\nsecond\n")

    def test_handle_message_prints_and_logs_same_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "mqtt_messages.log"
            timestamp = datetime(2026, 7, 3, 12, 34, 56, tzinfo=timezone.utc)
            message = FakeMessage("home/esp32/status", b"online")
            output = io.StringIO()

            with redirect_stdout(output):
                handle_message(message, log_path, lambda: timestamp)

            expected = (
                "2026-07-03T12:34:56+00:00 | "
                "topic=home/esp32/status | payload=online\n"
            )
            self.assertEqual(output.getvalue(), expected)
            self.assertEqual(log_path.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
