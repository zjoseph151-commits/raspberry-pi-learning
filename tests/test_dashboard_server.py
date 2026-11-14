import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    def test_load_service_status_distinguishes_timer_and_oneshot(self):
        output = "\n\n".join(
            (
                "Id=mosquitto.service\nLoadState=loaded\nActiveState=active\nSubState=running\n"
                "ActiveEnterTimestamp=Sat 2026-11-14 12:00:00 MST",
                "Id=mqtt-listener.service\nLoadState=loaded\nActiveState=failed\n"
                "SubState=failed\nResult=exit-code",
                "Id=health-monitor.timer\nLoadState=loaded\nActiveState=active\n"
                "SubState=waiting\nLastTriggerUSec=Sat 2026-11-14 12:00:00 MST\n"
                "NextElapseUSecRealtime=n/a\n"
                "NextElapseUSecMonotonic=Sat 2026-11-14 12:01:00 MST",
                "Id=health-monitor.service\nLoadState=loaded\nActiveState=inactive\n"
                "SubState=dead\nResult=success\n"
                "ExecMainExitTimestamp=Sat 2026-11-14 12:00:03 MST",
                "Id=iot-dashboard.service\nLoadState=loaded\nActiveState=active\n"
                "SubState=running\nActiveEnterTimestamp=Sat 2026-11-14 11:00:00 MST",
            )
        )
        with patch.object(
            dashboard_server.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=output, returncode=0),
        ) as run:
            report = dashboard_server.load_service_status()

        self.assertEqual(len(report["units"]), 5)
        self.assertEqual(report["units"][1]["state"], "Failed")
        self.assertEqual(report["units"][1]["result"], "exit-code")
        self.assertEqual(report["units"][2]["state"], "Active")
        self.assertEqual(report["units"][2]["next_run"], "Sat 2026-11-14 12:01:00 MST")
        self.assertEqual(report["units"][3]["state"], "Succeeded")
        self.assertEqual(report["units"][3]["tone"], "ok")
        args, kwargs = run.call_args
        self.assertEqual(args[0][:3], ["systemctl", "show", "--no-pager"])
        self.assertEqual(kwargs["timeout"], 2)
        self.assertFalse(kwargs["check"])

    def test_load_service_status_handles_missing_systemctl(self):
        with patch.object(
            dashboard_server.subprocess, "run", side_effect=FileNotFoundError
        ):
            report = dashboard_server.load_service_status()

        self.assertEqual(report["units"], [])
        self.assertEqual(report["error"], "Service status unavailable")

    def test_load_service_status_handles_unreachable_systemd(self):
        with patch.object(
            dashboard_server.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", returncode=1),
        ):
            report = dashboard_server.load_service_status()

        self.assertEqual(report["units"], [])
        self.assertEqual(report["error"], "Service status unavailable")

    def test_render_service_status_escapes_output_and_has_no_actions(self):
        html = build_dashboard_html(
            {"devices": []},
            {
                "checked_at": "2026-11-14 12:00 MST",
                "units": [{
                    "name": "MQTT <broker>",
                    "unit": "mosquitto.service",
                    "state": "Active",
                    "tone": "ok",
                    "detail": "<running>",
                    "last_activity": "Sat 2026-11-14 12:00 MST",
                    "next_run": "-",
                }],
            },
        )

        self.assertIn("<h2>Services</h2>", html)
        self.assertIn("<th>Last result</th>", html)
        self.assertIn('<h2 class="devices-heading">Devices</h2>', html)
        self.assertIn("MQTT &lt;broker&gt;", html)
        self.assertIn("&lt;running&gt;", html)
        self.assertNotIn("<running>", html)
        self.assertNotIn("data-service-action", html)

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
                    "device": "esp32-s3-sensor",
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
        self.assertIn("var refreshAfter = Date.now() + 10000", html)
        self.assertIn('src="/assets/birdfeeder-controls.js"', html)
        self.assertIn('src="/assets/front-porch-controls.js"', html)
        self.assertIn("Generated at: 2026-07-05T12:00:00+00:00", html)
        self.assertIn("esp32-s3-sensor", html)
        self.assertIn("garage-sensor", html)
        self.assertIn("<th>Health</th>", html)
        self.assertIn('class="table-scroll"', html)
        self.assertIn('class="badge health-unknown">UNKNOWN</span>', html)
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
        self.assertIn('data-device-details-key="esp32-s3-sensor"', html)
        self.assertIn('data-device-details-key="garage-sensor"', html)
        self.assertIn('storageKey = "pi-iot-dashboard-open-details"', html)
        self.assertIn("localStorage.setItem(storageKey", html)

    def test_build_dashboard_html_hides_old_test_devices(self):
        status = {
            "devices": [
                {"device": "esp32-c3-test", "latest_status": {"fields": {"note": "old-c3"}}},
                {"device": "esp32-s3-test"},
                {"device": "migration-test"},
                {"device": "esp32-c3-climate-01"},
            ],
        }

        html = build_dashboard_html(status)

        for device_id in ("esp32-c3-test", "esp32-s3-test", "migration-test"):
            self.assertNotIn(device_id, html)
        self.assertNotIn("old-c3", html)
        self.assertIn('data-device-details-key="esp32-c3-climate-01"', html)

    def test_birdfeeder_controls_render_only_for_birdfeeder(self):
        html = build_dashboard_html(
            {
                "devices": [
                    {
                        "device": "birdfeeder-01",
                        "latest_status": {
                            "fields": {"ip": "10.0.0.132", "stream_active": False}
                        },
                    },
                    {"device": "climate-01"},
                ]
            }
        )

        for command in ("record_now", "stay_awake", "sleep_now", "stream_on"):
            self.assertIn(
                f'<button type="button" data-birdfeeder-command="{command}">',
                html,
            )
        self.assertIn('data-stream-url="http://10.0.0.132:81/stream"', html)
        self.assertIn("http://10.0.0.132:81/stream</code>", html)
        self.assertEqual(html.count('class="detail-panel birdfeeder-controls"'), 1)

    def test_birdfeeder_stream_url_rejects_untrusted_addresses(self):
        valid = dashboard_server.birdfeeder_stream_url
        self.assertEqual(
            valid("http://10.0.0.132:81/stream"),
            "http://10.0.0.132:81/stream",
        )
        for url in (
            "javascript:alert(1)",
            "http://example.com:81/stream",
            "http://127.0.0.1:81/stream",
            "http://10.0.0.132:80/stream",
            "http://10.0.0.132:81/other",
            "http://[bad:81/stream",
        ):
            self.assertEqual(valid(url), "")

    def test_porch_controls_render_only_for_front_porch_camera(self):
        html = build_dashboard_html(
            {
                "devices": [
                    {
                        "device": "front-porch-camera-01",
                        "latest_status": {
                            "received_at": "2026-11-14T12:00:00+00:00",
                            "fields": {
                                "ip": "10.0.0.133",
                                "stream_url": "http://10.0.0.133/stream",
                                "stream_active": True,
                                "stream_remaining_seconds": 95,
                            },
                        },
                    },
                    {"device": "climate-01"},
                ]
            }
        )

        for command in ("start_stream", "stop_stream", "stream_info", "status_now"):
            self.assertIn(
                f'<button type="button" data-porch-command="{command}">', html
            )
        self.assertIn('data-stream-url="http://10.0.0.133/stream"', html)
        self.assertIn('data-stream-active="true"', html)
        self.assertIn('data-stream-remaining="95"', html)
        self.assertEqual(html.count('class="detail-panel porch-controls"'), 1)
        self.assertEqual(html.count('class="detail-panel birdfeeder-controls"'), 0)

    def test_porch_stream_url_accepts_only_private_camera_endpoint(self):
        valid = dashboard_server.porch_stream_url
        self.assertEqual(
            valid("http://10.0.0.133:80/stream"), "http://10.0.0.133/stream"
        )
        for url in (
            "javascript:alert(1)",
            "http://example.com/stream",
            "http://127.0.0.1/stream",
            "http://10.0.0.133:81/stream",
            "http://10.0.0.133/other",
            "http://[bad/stream",
        ):
            self.assertEqual(valid(url), "")

    def test_send_porch_command_uses_camera_response_fields(self):
        class FakeClient:
            def connect(self, host, port, keepalive):
                self.connection = (host, port, keepalive)

            def loop_start(self):
                self.on_connect(self, None, None, 0, None)

            def subscribe(self, topic):
                self.subscription = topic
                self.on_subscribe(
                    self, None, 1, [SimpleNamespace(is_failure=False)], None
                )
                return 0, 1

            def publish(self, topic, payload, qos, retain):
                self.published = (topic, json.loads(payload), qos, retain)
                response = {
                    "device": "front-porch-camera-01",
                    "type": "responses",
                    "command": "start_stream",
                    "success": True,
                    "stream_url": "http://10.0.0.133/stream",
                    "stream_active": True,
                    "stream_remaining_seconds": 120,
                }
                self.on_message(
                    self,
                    None,
                    SimpleNamespace(
                        topic=self.subscription,
                        payload=json.dumps(response).encode("utf-8"),
                    ),
                )
                return SimpleNamespace(rc=0)

            def disconnect(self):
                pass

            def loop_stop(self):
                pass

        client = FakeClient()
        with patch("paho.mqtt.client.Client", return_value=client):
            response = dashboard_server.send_porch_command("start_stream", 120)

        self.assertEqual(client.connection, ("localhost", 1883, 15))
        self.assertEqual(client.subscription, "home/devices/front-porch-camera-01/responses")
        self.assertEqual(
            client.published,
            (
                "home/devices/front-porch-camera-01/commands",
                {
                    "device": "front-porch-camera-01",
                    "command": "start_stream",
                    "duration_seconds": 120,
                },
                0,
                False,
            ),
        )
        self.assertEqual(response["message"], "Stream started")
        self.assertEqual(response["stream_url"], "http://10.0.0.133/stream")
        self.assertTrue(response["stream_active"])
        self.assertEqual(response["stream_remaining_seconds"], 120)

    def test_porch_command_rejects_bad_duration_before_mqtt(self):
        for duration in (9, 601, True, "120"):
            with self.assertRaises(ValueError):
                dashboard_server.send_porch_command("start_stream", duration)
        with self.assertRaises(ValueError):
            dashboard_server.send_porch_command("stop_stream", 120)

    def test_post_porch_command_validates_and_returns_camera_state(self):
        calls = []

        def send_command(command, duration_seconds):
            calls.append((command, duration_seconds))
            return {
                "ok": True,
                "command": command,
                "message": "Stream started",
                "stream_url": "http://10.0.0.133/stream",
                "stream_active": True,
                "stream_remaining_seconds": 120,
            }

        handler = make_handler(
            Path("missing-status.json"), quiet=True, porch_command_sender=send_command
        )
        server = DashboardRequestHandler.create_test_server(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def request(path, payload, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request(
                "POST", path, body=json.dumps(payload),
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            return response.status, body

        try:
            path = dashboard_server.PORCH_COMMAND_PATH
            status, body = request(path, {"command": "start_stream", "duration_seconds": 120})
            self.assertEqual(status, 200)
            self.assertTrue(body["stream_active"])
            self.assertEqual(calls, [("start_stream", 120)])

            status, _ = request(path, {"command": "stream_info"})
            self.assertEqual(status, 200)
            self.assertEqual(calls[-1], ("stream_info", None))

            for invalid in (
                {"command": "reboot"},
                {"command": "start_stream", "duration_seconds": 9},
                {"command": "start_stream", "duration_seconds": 601},
                {"command": "start_stream", "duration_seconds": True},
                {"command": "stop_stream", "duration_seconds": 120},
            ):
                status, _ = request(path, invalid)
                self.assertEqual(status, 400)
            status, _ = request(path, {"command": "status_now"}, {"Origin": "http://evil.example"})
            self.assertEqual(status, 403)
            self.assertEqual(len(calls), 2)

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/assets/front-porch-controls.js")
            response = connection.getresponse()
            script = response.read().decode("utf-8")
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn("data-porch-controls", script)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_send_birdfeeder_command_publishes_without_retain_and_uses_response(self):
        class FakeClient:
            def __init__(self):
                self.published = None

            def connect(self, host, port, keepalive):
                self.connection = (host, port, keepalive)

            def loop_start(self):
                self.on_connect(self, None, None, 0, None)

            def subscribe(self, topic):
                self.subscription = topic
                self.on_subscribe(
                    self, None, 1, [SimpleNamespace(is_failure=False)], None
                )
                return 0, 1

            def publish(self, topic, payload, qos, retain):
                self.published = (topic, json.loads(payload), qos, retain)
                response = {
                    "device": "birdfeeder-01",
                    "type": "responses",
                    "command": "stream_on",
                    "success": True,
                    "message": "stream_started",
                    "stream_url": "http://10.0.0.132:81/stream",
                }
                self.on_message(
                    self,
                    None,
                    SimpleNamespace(
                        topic=self.subscription,
                        payload=json.dumps(response).encode("utf-8"),
                    ),
                )
                return SimpleNamespace(rc=0)

            def disconnect(self):
                pass

            def loop_stop(self):
                pass

        client = FakeClient()
        with patch("paho.mqtt.client.Client", return_value=client):
            response = dashboard_server.send_birdfeeder_command("stream_on", 120)

        self.assertEqual(client.connection, ("localhost", 1883, 15))
        self.assertEqual(
            client.published,
            (
                "home/devices/birdfeeder-01/commands",
                {"device": "birdfeeder-01", "command": "stream_on", "duration_seconds": 120},
                0,
                False,
            ),
        )
        self.assertEqual(response["stream_url"], "http://10.0.0.132:81/stream")
        self.assertTrue(response["ok"])

    def test_post_birdfeeder_command_validates_and_returns_acknowledgement(self):
        calls = []

        def send_command(command, duration_seconds):
            calls.append((command, duration_seconds))
            return {
                "ok": True,
                "command": command,
                "message": "recording_started",
                "stream_url": "",
                "duration_seconds": 0,
            }

        handler = make_handler(Path("missing-status.json"), quiet=True, command_sender=send_command)
        server = DashboardRequestHandler.create_test_server(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def request(path, payload, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request(
                "POST", path, body=json.dumps(payload),
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            return response.status, body

        try:
            path = dashboard_server.BIRDFEEDER_COMMAND_PATH
            status, body = request(path, {"command": "record_now"})
            self.assertEqual(status, 200)
            self.assertEqual(body["message"], "recording_started")
            self.assertEqual(calls, [("record_now", None)])

            status, _ = request(path, {"command": "stream_on", "duration_seconds": 180})
            self.assertEqual(status, 200)
            self.assertEqual(calls[-1], ("stream_on", 180))

            for invalid in (
                {"command": "reboot"},
                {"command": []},
                {"command": "stream_on", "duration_seconds": 181},
                {"command": "sleep_now", "duration_seconds": 60},
            ):
                status, _ = request(path, invalid)
                self.assertEqual(status, 400)
            status, _ = request(
                path, {"command": "record_now"}, {"Origin": "http://evil.example"}
            )
            self.assertEqual(status, 403)
            status, _ = request("/api/devices/other/commands", {"command": "record_now"})
            self.assertEqual(status, 404)
            self.assertEqual(len(calls), 2)

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/assets/birdfeeder-controls.js")
            response = connection.getresponse()
            script = response.read().decode("utf-8")
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn("data-birdfeeder-controls", script)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_post_birdfeeder_timeout_is_reported_without_mqtt(self):
        def timeout(command, duration_seconds):
            raise TimeoutError("No acknowledgement; the command may have run")

        handler = make_handler(Path("missing-status.json"), quiet=True, command_sender=timeout)
        server = DashboardRequestHandler.create_test_server(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request(
                "POST", dashboard_server.BIRDFEEDER_COMMAND_PATH,
                body='{"command":"record_now"}',
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 504)
            self.assertIn("may have run", body["message"])
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_build_dashboard_html_shows_empty_state_when_only_hidden_devices_exist(self):
        html = build_dashboard_html({"devices": [{"device": "migration-test"}]})

        self.assertNotIn('data-device-details-key="migration-test"', html)
        self.assertIn("No device status data available.", html)

    def test_build_dashboard_html_renders_climate_device_details(self):
        status = {
            "generated_at": "2026-08-03T12:01:00+00:00",
            "devices": [
                {
                    "device": "esp32-c3-climate-01",
                    "status": "ONLINE",
                    "health_state": "SLEEPING",
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

        self.assertIn('class="badge health-sleeping">SLEEPING</span>', html)
        self.assertIn('class="badge fresh">FRESH</span>', html)
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
        self.assertIn('data-device-details-key="esp32-c3-climate-01"', html)

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
                                "device": "esp32-s3-sensor",
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
            handler = make_handler(
                status_path,
                quiet=True,
                service_status_loader=lambda: {
                    "checked_at": "2026-11-14 12:00 MST",
                    "units": [{
                        "name": "Dashboard",
                        "unit": "iot-dashboard.service",
                        "state": "Active",
                        "tone": "ok",
                        "detail": "running",
                        "last_activity": "Sat 2026-11-14 12:00 MST",
                        "next_run": "-",
                    }],
                },
            )
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
            self.assertIn("esp32-s3-sensor", body)
            self.assertIn("iot-dashboard.service", body)


if __name__ == "__main__":
    unittest.main()
