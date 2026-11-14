import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


listener = load_module(
    "pipeline_listener", PROJECT_ROOT / "services" / "mqtt-listener" / "listener.py"
)
monitor = load_module(
    "pipeline_monitor", PROJECT_ROOT / "services" / "health-monitor" / "health_monitor.py"
)
dashboard = load_module(
    "pipeline_dashboard", PROJECT_ROOT / "services" / "dashboard" / "dashboard_server.py"
)


class Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class DevicePipelineTests(unittest.TestCase):
    def test_sleepy_state_and_invalid_identity_through_log_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data = Path(temp_dir) / "data"
            log_path = data / "logs" / "mqtt_messages.log"
            jsonl_path = data / "logs" / "mqtt_messages.jsonl"
            csv_path = data / "logs" / "mqtt_messages.csv"
            status_path = data / "status" / "device_status.json"
            events = (
                (
                    "2026-08-03T12:00:00+00:00",
                    "home/devices/climate-01/status",
                    b'{"device":"climate-01","sleepy":true,"read_interval_ms":60000}',
                ),
                (
                    "2026-08-03T12:00:01+00:00",
                    "home/devices/climate-01/telemetry",
                    b'{"device":"climate-01","temperature_c":22.0}',
                ),
                (
                    "2026-08-03T12:00:02+00:00",
                    "home/devices/climate-01/availability",
                    b"offline",
                ),
                (
                    "2026-08-03T12:01:59+00:00",
                    "home/devices/climate-01/telemetry",
                    b'{"device":"ghost","temperature_c":99.0}',
                ),
                (
                    "2026-08-03T12:02:00+00:00",
                    "home/devices/climate-01/commands",
                    b'{"command":"read_now"}',
                ),
            )

            with redirect_stdout(io.StringIO()):
                for received_at, topic, payload in events:
                    listener.handle_message(
                        Message(topic, payload),
                        log_path,
                        lambda value=received_at: datetime.fromisoformat(value),
                        jsonl_path=jsonl_path,
                        csv_path=csv_path,
                    )
                monitor.run(
                    csv_path,
                    status_path,
                    lambda: datetime(2026, 8, 3, 12, 2, 30, tzinfo=timezone.utc),
                    jsonl_path=jsonl_path,
                    log_path=log_path,
                )

            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(len(status["devices"]), 1)
            device = status["devices"][0]
            self.assertEqual(device["device"], "climate-01")
            self.assertEqual(device["status"], "ONLINE")
            self.assertEqual(device["health_state"], "SLEEPING")
            self.assertEqual(device["stale_after_seconds"], 180)
            self.assertEqual(device["latest_telemetry"]["fields"]["temperature_c"], 22.0)
            html = dashboard.build_dashboard_html(status)
            self.assertIn('class="badge health-sleeping">SLEEPING</span>', html)
            self.assertIn('class="badge fresh">FRESH</span>', html)
            self.assertIn('class="badge availability-offline">OFFLINE</span>', html)
            self.assertNotIn("ghost", html)

            archived = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(archived), len(events))
            self.assertEqual(archived[3]["validation_error"], "device_mismatch")
            self.assertEqual(archived[3]["payload"]["device"], "ghost")


if __name__ == "__main__":
    unittest.main()
