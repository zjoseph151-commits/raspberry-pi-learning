import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATED_DASHBOARD_PATH = (
    PROJECT_ROOT / "services" / "dashboard" / "dashboard_server.py"
)


def load_migrated_dashboard():
    spec = importlib.util.spec_from_file_location(
        "migrated_dashboard_server",
        MIGRATED_DASHBOARD_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


dashboard_server = load_migrated_dashboard()

DashboardRequestHandler = dashboard_server.DashboardRequestHandler
build_dashboard_html = dashboard_server.build_dashboard_html
load_device_status = dashboard_server.load_device_status
make_handler = dashboard_server.make_handler


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


class DashboardServerTests(unittest.TestCase):
    def test_migrated_dashboard_module_loads_from_new_service_path(self):
        self.assertTrue(MIGRATED_DASHBOARD_PATH.exists())
        self.assertEqual(
            dashboard_server.STATUS_JSON_PATH,
            Path("data/status/device_status.json"),
        )
        self.assertEqual(dashboard_server.HOST, "0.0.0.0")
        self.assertEqual(dashboard_server.PORT, 8080)

    def test_load_device_status_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "data" / "status" / "device_status.json"

            status = load_device_status(status_path)

            self.assertEqual(
                status,
                {
                    "generated_at": "",
                    "devices": [],
                    "message": f"No device status file found at {status_path}.",
                },
            )

    def test_build_dashboard_html_renders_status_report(self):
        status = {
            "generated_at": "2026-07-05T12:00:00+00:00",
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
        }

        html = build_dashboard_html(status)
        parser = TitleParser()
        parser.feed(html)

        self.assertEqual(parser.title, "Pi IoT Dashboard")
        self.assertIn('<meta http-equiv="refresh" content="10">', html)
        self.assertIn("Generated at: 2026-07-05T12:00:00+00:00", html)
        self.assertIn("esp32-s3-test", html)
        self.assertIn("garage-sensor", html)
        self.assertIn('class="badge fresh">FRESH</span>', html)
        self.assertIn('class="badge stale">STALE</span>', html)
        self.assertIn('class="badge availability-unknown">UNKNOWN</span>', html)
        self.assertIn("<td>15s</td>", html)
        self.assertIn("<td>2m 0s</td>", html)
        self.assertIn('<td class="topic">home/esp32-s3/status</td>', html)
        self.assertIn("<td>heartbeat</td>", html)
        self.assertIn("<td>2</td>", html)
        self.assertIn("<td>10000</td>", html)
        self.assertIn("<td>-57</td>", html)
        self.assertIn("Device Details", html)

    def test_build_dashboard_html_renders_climate_device_details(self):
        status = {
            "generated_at": "2026-08-03T12:01:00+00:00",
            "devices": [
                {
                    "device": "esp32-c3-climate-01",
                    "status": "OFFLINE",
                    "received_at": "2026-08-03T12:00:00+00:00",
                    "topic": "home/devices/esp32-c3-climate-01/telemetry",
                    "type": "telemetry",
                    "count": "2",
                    "uptime_ms": "120000",
                    "wifi_rssi": "-55",
                    "availability": {
                        "state": "offline",
                        "received_at": "2026-08-03T12:00:01+00:00",
                        "topic": "home/devices/esp32-c3-climate-01/availability",
                        "fields": {
                            "device": "esp32-c3-climate-01",
                            "type": "availability",
                            "availability": "offline",
                        },
                    },
                    "latest_status": {
                        "received_at": "2026-08-03T12:00:00+00:00",
                        "topic": "home/devices/esp32-c3-climate-01/status",
                        "fields": {
                            "device": "esp32-c3-climate-01",
                            "type": "status",
                            "firmware_version": "0.4.0",
                            "sleepy": True,
                            "display_on": False,
                            "read_interval_ms": 60000,
                        },
                    },
                    "latest_telemetry": {
                        "received_at": "2026-08-03T12:00:00+00:00",
                        "topic": "home/devices/esp32-c3-climate-01/telemetry",
                        "fields": {
                            "device": "esp32-c3-climate-01",
                            "type": "telemetry",
                            "temperature_c": 22.0,
                            "temperature_f": 71.6,
                            "humidity_percent": 45.0,
                            "sensor_ok": True,
                            "source": "timer",
                        },
                    },
                }
            ],
        }

        html = build_dashboard_html(status)

        self.assertIn('class="badge stale">STALE</span>', html)
        self.assertIn('class="badge availability-offline">OFFLINE</span>', html)
        self.assertIn("<td>1m 0s</td>", html)
        self.assertIn("Latest Telemetry", html)
        self.assertIn("temperature_f", html)
        self.assertIn("71.6", html)
        self.assertIn("humidity_percent", html)
        self.assertIn("sensor_ok", html)
        self.assertIn(">true</dd>", html)
        self.assertIn("Latest Status", html)
        self.assertIn("firmware_version", html)
        self.assertIn("0.4.0", html)
        self.assertIn("display_on", html)
        self.assertIn(">false</dd>", html)
        self.assertIn("Availability Event", html)

    def test_build_dashboard_html_escapes_device_data(self):
        status = {
            "generated_at": "<now>",
            "devices": [
                {
                    "device": "<script>alert(1)</script>",
                    "status": "ONLINE",
                    "received_at": "",
                    "topic": "home/<bad>",
                    "type": "heartbeat",
                    "count": "",
                    "uptime_ms": "",
                    "wifi_rssi": "",
                },
            ],
        }

        html = build_dashboard_html(status)

        self.assertIn("&lt;now&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("home/&lt;bad&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_handler_serves_dashboard_html(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "data" / "status" / "device_status.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-05T12:00:00+00:00",
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
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            handler = make_handler(status_path, quiet=True)
            server = DashboardRequestHandler.create_test_server(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/")
                response = conn.getresponse()
                body = response.read().decode("utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/html; charset=utf-8")
            self.assertIn("Pi IoT Dashboard", body)
            self.assertIn("esp32-s3-test", body)


if __name__ == "__main__":
    unittest.main()
