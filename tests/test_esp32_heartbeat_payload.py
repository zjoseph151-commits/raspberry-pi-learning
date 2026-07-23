import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_CPP = PROJECT_ROOT / "src" / "main.cpp"
PLATFORMIO_INI = PROJECT_ROOT / "platformio.ini"


class Esp32SensorNodeFoundationTests(unittest.TestCase):
    def setUp(self):
        self.source = MAIN_CPP.read_text(encoding="utf-8")
        self.platformio = PLATFORMIO_INI.read_text(encoding="utf-8")

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
        self.assertIn(
            'const char *RESPONSES_TOPIC = "home/devices/esp32-c3-test/responses";',
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

    def test_dht11_sensor_configuration_and_telemetry_topics_are_present(self):
        self.assertIn("#include <DHT.h>", self.source)
        self.assertIn("const uint8_t DHT_PIN = 3;", self.source)
        self.assertIn("const uint8_t DHT_TYPE = DHT11;", self.source)
        self.assertIn("DHT dht(DHT_PIN, DHT_TYPE);", self.source)
        self.assertIn("dht.begin();", self.source)
        self.assertIn("adafruit/DHT sensor library", self.platformio)
        self.assertIn(
            'const char *TELEMETRY_TOPIC = "home/devices/esp32-c3-test/telemetry";',
            self.source,
        )
        self.assertIn("const unsigned long TELEMETRY_INTERVAL_MS = 15000;", self.source)

    def test_dht11_telemetry_payload_formats_are_compact_valid_json(self):
        success_match = re.search(
            r'const char \*DHT_TELEMETRY_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        failure_match = re.search(
            r'const char \*DHT_TELEMETRY_ERROR_JSON_FORMAT =\s*"((?:\\.|[^"])*)";',
            self.source,
        )
        self.assertIsNotNone(success_match, "DHT_TELEMETRY_JSON_FORMAT is missing")
        self.assertIsNotNone(failure_match, "DHT_TELEMETRY_ERROR_JSON_FORMAT is missing")

        success_format = bytes(success_match.group(1), "utf-8").decode("unicode_escape")
        failure_format = bytes(failure_match.group(1), "utf-8").decode("unicode_escape")
        success_payload = success_format % (23.4, 56.7, 123456)
        failure_payload = failure_format % 123456

        self.assertEqual(
            json.loads(success_payload),
            {
                "device": "esp32-c3-test",
                "temperature_c": 23.4,
                "humidity_percent": 56.7,
                "sensor_ok": True,
                "uptime_ms": 123456,
            },
        )
        self.assertEqual(
            json.loads(failure_payload),
            {
                "device": "esp32-c3-test",
                "temperature_c": None,
                "humidity_percent": None,
                "sensor_ok": False,
                "uptime_ms": 123456,
            },
        )
        self.assertNotIn(" ", success_payload)
        self.assertNotIn("\n", success_payload)
        self.assertNotIn("NaN", failure_payload)

    def test_dht11_sensor_reading_and_telemetry_publishing_are_separate_functions(self):
        self.assertIn("DhtReading readDhtSensor()", self.source)
        self.assertIn("bool buildDhtTelemetryPayload(", self.source)
        self.assertIn("void publishDhtTelemetry()", self.source)
        self.assertIn("void publishDhtTelemetryIfDue()", self.source)
        self.assertIn("mqttClient.publish(TELEMETRY_TOPIC, payload)", self.source)

    def test_mqtt_availability_lwt_and_command_subscription_are_configured(self):
        self.assertIn('AVAILABILITY_TOPIC, 1, true, "offline"', self.source)
        self.assertIn('mqttClient.publish(AVAILABILITY_TOPIC, "online", true)', self.source)
        self.assertIn("mqttClient.subscribe(COMMANDS_TOPIC)", self.source)
        self.assertIn("void handleMqttMessage(char *topic, byte *payload, unsigned int length)", self.source)

    def test_bidirectional_command_handling_is_configured(self):
        self.assertIn("#include <ArduinoJson.h>", self.source)
        self.assertIn("bblanchon/ArduinoJson", self.platformio)
        self.assertIn('const char *COMMAND_READ_NOW = "read_now";', self.source)
        self.assertIn('const char *COMMAND_SET_INTERVAL = "set_interval";', self.source)
        self.assertIn("const unsigned long MIN_TELEMETRY_INTERVAL_SECONDS = 5;", self.source)
        self.assertIn("const unsigned long MAX_TELEMETRY_INTERVAL_SECONDS = 3600;", self.source)
        self.assertIn("unsigned long telemetryIntervalMs = TELEMETRY_INTERVAL_MS;", self.source)
        self.assertIn("bool parseCommandPayload(", self.source)
        self.assertIn("void executeCommand(", self.source)
        self.assertIn("bool publishCommandResponse(", self.source)
        self.assertIn("deserializeJson(", self.source)
        self.assertIn("serializeJson(", self.source)
        self.assertIn("publishDhtTelemetry();", self.source)
        self.assertIn("telemetryIntervalMs = request.intervalSeconds * 1000UL;", self.source)
        self.assertIn("mqttClient.publish(RESPONSES_TOPIC, responsePayload)", self.source)

    def test_timing_is_non_blocking_and_status_interval_is_10_seconds(self):
        self.assertIn("const unsigned long STATUS_INTERVAL_MS = 10000;", self.source)
        self.assertIn("const unsigned long TELEMETRY_INTERVAL_MS = 15000;", self.source)
        self.assertIn("telemetryIntervalMs", self.source)
        self.assertNotIn("delay(", self.source)
        self.assertNotIn("while (!mqttClient.connected())", self.source)
        self.assertNotIn("while (WiFi.status() != WL_CONNECTED)", self.source)


if __name__ == "__main__":
    unittest.main()
