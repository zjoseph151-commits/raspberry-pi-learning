import unittest

from config.device_contract import parse_device_topic, validate_device_payload


class DeviceContractTests(unittest.TestCase):
    def test_parse_canonical_topics_only(self):
        self.assertEqual(
            parse_device_topic("home/devices/climate-01/telemetry"),
            ("climate-01", "telemetry"),
        )
        for topic in (
            "home/devices//status",
            "home/devices/climate-01/unknown",
            "home/devices/climate-01/status/extra",
            "home/legacy/status",
        ):
            self.assertIsNone(parse_device_topic(topic))

    def test_payload_identity_and_type_match_topic(self):
        topic = "home/devices/climate-01/status"
        self.assertIsNone(validate_device_payload(topic, {"device": "climate-01"}))
        self.assertEqual(validate_device_payload(topic, {"device": "other"}), "device_mismatch")
        self.assertEqual(validate_device_payload(topic, {"type": "status"}), "missing_device")
        self.assertEqual(
            validate_device_payload(topic, {"device": "climate-01", "type": "telemetry"}),
            "type_mismatch",
        )
        self.assertEqual(validate_device_payload(topic, []), "payload_not_object")
        self.assertEqual(
            validate_device_payload("home/devices/climate-01/unknown", {"device": "climate-01"}),
            "invalid_topic",
        )

    def test_commands_and_responses_have_distinct_minimums(self):
        command_topic = "home/devices/climate-01/commands"
        response_topic = "home/devices/climate-01/responses"
        self.assertIsNone(validate_device_payload(command_topic, {"command": "read_now"}))
        self.assertEqual(validate_device_payload(command_topic, {}), "missing_command")
        self.assertIsNone(
            validate_device_payload(
                response_topic,
                {"device": "climate-01", "command": "read_now", "success": True},
            )
        )
        self.assertEqual(
            validate_device_payload(
                response_topic, {"device": "climate-01", "command": "read_now"}
            ),
            "missing_success",
        )

    def test_legacy_topics_are_not_subject_to_canonical_validation(self):
        self.assertIsNone(
            validate_device_payload("home/old-device/status", {"device": "old-device"})
        )


if __name__ == "__main__":
    unittest.main()
