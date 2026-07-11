import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_CPP = PROJECT_ROOT / "src" / "main.cpp"


class Esp32SensorNodeFoundationTests(unittest.TestCase):
    def setUp(self):
        self.source = MAIN_CPP.read_text(encoding="utf-8")

    def test_device_identity_and_topics_target_esp32_c3_foundation(self):
        self.assertIn('const char *DEVICE_ID = "esp32-c3-test";', self.source)
        self.assertIn('const char *FIRMWARE_VERSION = "0.1.0";', self.source)
        self.assertIn(
            'const char *STATUS_TOPIC = "home/devices/esp32-c3-test/status";',
            self.source,
        )
        self.assertIn(
            'const char *AVAILABILITY_TOPIC = "home/devices/esp32-c3-test/availability";',
            self.source,
        )
        self.assertIn(
            'const char *TELEMETRY_TOPIC = "home/devices/esp32-c3-test/telemetry";',
            self.source,
        )
        self.assertIn(
            'const char *COMMANDS_TOPIC = "home/devices/esp32-c3-test/commands";',
            self.source,
        )
        self.assertIn("String buildMqttClientId()", self.source)
        self.assertIn("ESP.getEfuseMac()", self.source)

    def test_payload_format_is_compact_valid_json_with_expected_fields(self):
        match = re.search(
            r'const char \*STATUS_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        self.assertIsNotNone(match, "STATUS_JSON_FORMAT constant is missing")

        format_string = bytes(match.group(1), "utf-8").decode("unicode_escape")
        sample_payload = format_string % (123456, -57, 180000)
        decoded = json.loads(sample_payload)

        self.assertEqual(
            decoded,
            {
                "device": "esp32-c3-test",
                "firmware_version": "0.1.0",
                "uptime_ms": 123456,
                "wifi_rssi": -57,
                "free_heap": 180000,
            },
        )
        self.assertNotIn(" ", sample_payload)
        self.assertNotIn("\n", sample_payload)

    def test_water_sensor_configuration_and_telemetry_topics_are_present(self):
        self.assertIn("const uint8_t WTR_PIN =", self.source)
        self.assertIn("pinMode(WTR_PIN, INPUT);", self.source)
        self.assertIn(
            'const char *TELEMETRY_TOPIC = "home/devices/esp32-c3-test/telemetry";',
            self.source,
        )
        self.assertIn("const unsigned long TELEMETRY_INTERVAL_MS = 15000;", self.source)

    def test_water_telemetry_payload_formats_are_compact_valid_json(self):
        success_match = re.search(
            r'const char \*WATER_TELEMETRY_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        failure_match = re.search(
            r'const char \*WATER_TELEMETRY_ERROR_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        self.assertIsNotNone(success_match, "WATER_TELEMETRY_JSON_FORMAT is missing")
        self.assertIsNotNone(failure_match, "WATER_TELEMETRY_ERROR_JSON_FORMAT is missing")

        success_format = bytes(success_match.group(1), "utf-8").decode("unicode_escape")
        failure_format = bytes(failure_match.group(1), "utf-8").decode("unicode_escape")
        success_payload = success_format % (72, 123456)
        failure_payload = failure_format % 123456

        self.assertEqual(
            json.loads(success_payload),
            {
                "device": "esp32-c3-test",
                "water_level_percent": 72,
                "sensor_ok": True,
                "uptime_ms": 123456,
            },
        )
        self.assertEqual(
            json.loads(failure_payload),
            {
                "device": "esp32-c3-test",
                "water_level_percent": None,
                "sensor_ok": False,
                "uptime_ms": 123456,
            },
        )
        self.assertNotIn(" ", success_payload)
        self.assertNotIn("\n", success_payload)
        self.assertNotIn("NaN", failure_payload)

    def test_water_sensor_reading_and_telemetry_publishing_are_separate_functions(self):
        self.assertIn("WaterLevelReading readWaterLevelSensor()", self.source)
        self.assertIn("bool buildWaterTelemetryPayload(", self.source)
        self.assertIn("void publishWaterTelemetry()", self.source)
        self.assertIn("void publishWaterTelemetryIfDue()", self.source)
        self.assertIn("mqttClient.publish(TELEMETRY_TOPIC, payload)", self.source)

    def test_mqtt_availability_lwt_and_command_subscription_are_configured(self):
        self.assertIn('AVAILABILITY_TOPIC, 1, true, "offline"', self.source)
        self.assertIn('mqttClient.publish(AVAILABILITY_TOPIC, "online", true)', self.source)
        self.assertIn("mqttClient.subscribe(COMMANDS_TOPIC)", self.source)
        self.assertIn("void handleMqttMessage(char *topic, byte *payload, unsigned int length)", self.source)

    def test_timing_is_non_blocking_and_status_interval_is_10_seconds(self):
        self.assertIn("const unsigned long STATUS_INTERVAL_MS = 10000;", self.source)
        self.assertIn("const unsigned long TELEMETRY_INTERVAL_MS = 15000;", self.source)
        self.assertNotIn("delay(", self.source)
        self.assertNotIn("while (!mqttClient.connected())", self.source)
        self.assertNotIn("while (WiFi.status() != WL_CONNECTED)", self.source)


if __name__ == "__main__":
    unittest.main()
