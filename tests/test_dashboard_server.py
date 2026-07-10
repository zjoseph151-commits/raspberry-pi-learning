import http.client
import json
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path

from dashboard_server import (
    DashboardRequestHandler,
    build_dashboard_html,
    load_device_status,
    make_handler,
)


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
    def test_load_device_status_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "logs" / "device_status.json"

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
        self.assertIn('class="status online">ONLINE</span>', html)
        self.assertIn('class="status offline">OFFLINE</span>', html)
        self.assertIn("<td>home/esp32-s3/status</td>", html)
        self.assertIn("<td>heartbeat</td>", html)
        self.assertIn("<td>2</td>", html)
        self.assertIn("<td>10000</td>", html)
        self.assertIn("<td>-57</td>", html)

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
            status_path = Path(temp_dir) / "logs" / "device_status.json"
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
