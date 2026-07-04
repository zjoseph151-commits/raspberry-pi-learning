import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_CPP = PROJECT_ROOT / "src" / "main.cpp"


class Esp32HeartbeatPayloadTests(unittest.TestCase):
    def setUp(self):
        self.source = MAIN_CPP.read_text(encoding="utf-8")

    def test_status_topic_targets_esp32_s3_namespace(self):
        self.assertIn('const char *MQTT_TOPIC = "home/esp32-s3/status";', self.source)

    def test_payload_format_is_compact_valid_json_with_expected_fields(self):
        match = re.search(
            r'const char \*HEARTBEAT_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        self.assertIsNotNone(match, "HEARTBEAT_JSON_FORMAT constant is missing")

        format_string = bytes(match.group(1), "utf-8").decode("unicode_escape")
        sample_payload = format_string % (42, 123456, -57)
        decoded = json.loads(sample_payload)

        self.assertEqual(
            decoded,
            {
                "device": "esp32-s3-test",
                "type": "heartbeat",
                "count": 42,
                "uptime_ms": 123456,
                "wifi_rssi": -57,
            },
        )
        self.assertNotIn(" ", sample_payload)
        self.assertNotIn("\n", sample_payload)


if __name__ == "__main__":
    unittest.main()
