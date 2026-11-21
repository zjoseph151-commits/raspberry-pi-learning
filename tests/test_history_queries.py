from contextlib import closing
import http.client
import json
from pathlib import Path
from runpy import run_path
import sqlite3
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from config.platform import HISTORY_CLIMATE_DEVICE_ID
from services.dashboard import dashboard_server, history_queries

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = run_path(str(ROOT / "services" / "telemetry-history" / "import_history.py"))["SCHEMA"]
DEVICE = HISTORY_CLIMATE_DEVICE_ID
METRIC = "temperature_c"
END = 1795251600
DAY = history_queries.DAY_SECONDS


class HistoryQueryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "telemetry #1.sqlite3"

    def seed(self, *readings):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript(SCHEMA)
            db.executemany(
                """INSERT INTO telemetry_readings
                   (device_id, metric, received_at_utc, value, quality, source_event_key)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    (DEVICE, METRIC, timestamp, value, quality, index.to_bytes(4, "big"))
                    for index, (timestamp, value, quality) in enumerate(readings)
                ),
            )

    def query(self, requested_range="24h"):
        return history_queries.query_history(self.database, DEVICE, METRIC, requested_range, end_utc=END)

    def test_empty_range_keeps_latest_reading_and_does_not_shift_window(self):
        stale = END - 3 * DAY
        self.seed((stale, 22, "ok"))
        daily = self.query()
        self.assertEqual(daily["points"], [])
        self.assertEqual((daily["start_utc"], daily["end_utc"]), (END - DAY, END))
        self.assertEqual(daily["latest"], {"timestamp_utc": stale, "value": 22, "quality": "ok"})
        self.assertEqual(daily["unit"], "C")
        weekly = self.query("7d")
        self.assertEqual(weekly["latest"], daily["latest"])
        self.assertEqual(len(weekly["points"]), 1)
        self.assertEqual(weekly["points"][0]["value"], 22)

    def test_raw_range_bounds_and_gap_flags(self):
        start = END - DAY
        self.seed(
            (start - 1, 10, "ok"), (start, 20, "ok"), (start + 60, 21, "ok"),
            (start + 120, None, "sensor_failed"), (start + 180, 22, "ok"),
            (start + 360, 23, "ok"), (start + 541, 24, "ok"), (END, 99, "ok"),
        )
        result = self.query()
        self.assertIsNone(result["bucket_seconds"])
        self.assertEqual([p["value"] for p in result["points"]], [20, 21, None, 22, 23, 24])
        self.assertEqual([p["break_before"] for p in result["points"]], [False, False, True, True, False, True])
        self.assertEqual(result["latest"]["timestamp_utc"], start + 541)
        self.assertEqual(result["points"][2]["quality"], "sensor_failed")

    def test_latest_can_be_an_explicit_failure(self):
        self.seed((END - 120, 22, "ok"), (END - 60, None, "sensor_failed"))
        self.assertEqual(self.query()["latest"], {
            "timestamp_utc": END - 60, "value": None, "quality": "sensor_failed",
        })

    def test_buckets_keep_stats_and_do_not_bridge_internal_or_cross_bucket_gaps(self):
        start = END - 7 * DAY
        self.seed(*(
            (start + seconds, value, quality) for seconds, value, quality in (
                (100, 20, "ok"), (160, 30, "ok"), (850, 40, "ok"),
                (930, 24, "ok"), (990, 26, "ok"),
                (1800, 26, "ok"), (1860, 28, "ok"), (1920, None, "invalid"),
                (2710, None, "sensor_failed"),
                (3620, 32, "ok"),
                (5400, 34, "ok"), (5460, 36, "ok"),
            )
        ))
        result = self.query("7d")
        points = result["points"]
        self.assertEqual(result["bucket_seconds"], 900)
        self.assertEqual([p["timestamp_utc"] - start for p in points], [0, 900, 1800, 2700, 3600, 5400])
        self.assertEqual([p["has_gap"] for p in points], [True, False, True, True, False, False])
        self.assertEqual([p["break_before"] for p in points], [False, True, True, True, True, True])
        self.assertEqual((points[0]["value"], points[0]["min"], points[0]["max"]), (30, 20, 40))
        self.assertEqual((points[2]["samples"], points[2]["valid_samples"], points[2]["value"]), (3, 2, 27))
        self.assertIsNone(points[3]["value"])

    def test_dense_daily_window_falls_back_to_buckets_instead_of_truncating(self):
        start = END - DAY
        count = history_queries.RAW_POINT_LIMIT + 1
        self.seed(*[(start + i, 20, "ok") for i in range(count)], (END - 1, 35, "ok"))
        result = self.query()
        self.assertEqual(result["bucket_seconds"], 300)
        self.assertLessEqual(len(result["points"]), DAY // 300)
        self.assertEqual(sum(p["samples"] for p in result["points"]), count + 1)
        self.assertEqual(result["points"][-1]["value"], 35)

    def test_partial_buckets_are_clipped_without_shifting_interior_buckets(self):
        origin = END - 7 * DAY
        self.seed(
            (origin + 10, 20, "ok"), (origin + 860, 21, "ok"),
            (origin + 920, 22, "ok"), (END + 5, 30, "ok"),
        )
        result = history_queries.query_history(self.database, DEVICE, METRIC, "7d", end_utc=END + 30)
        self.assertEqual([p["timestamp_utc"] for p in result["points"]], [origin + 30, origin + 900, END])
        self.assertEqual([p["value"] for p in result["points"]], [21, 22, 30])
        self.assertFalse(result["points"][1]["break_before"])

    def test_missing_database_is_not_created(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.query()
        self.assertFalse(self.database.exists())

    def test_read_only_http_route_and_invalid_parameters(self):
        self.seed((END - 60, 22, "ok"))
        handler = dashboard_server.make_handler(
            status_path=self.root / "missing-status.json",
            quiet=True,
            service_status_loader=lambda: {"units": []},
            history_path=self.database,
        )
        api = dashboard_server.HISTORY_API_PATH
        server = dashboard_server.DashboardRequestHandler.create_test_server(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def get(path):
            with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as connection:
                connection.request("GET", path)
                response = connection.getresponse()
                return response.status, response.getheader("Cache-Control"), response.read()

        params = {"device": DEVICE, "metric": METRIC, "range": "24h"}
        valid_path = api + "?" + urlencode(params)
        with patch.object(history_queries, "time", return_value=END - 1):
            status, cache, body = get(valid_path)
        self.assertEqual((status, cache), (200, "no-store"))
        self.assertEqual(json.loads(body)["points"][0]["value"], 22)
        for path in (
            api,
            valid_path + "&range=7d",
            api + "?" + urlencode({**params, "range": "30d"}),
            api + "?" + urlencode({**params, "metric": "temperature_f"}),
            api + "?" + urlencode({**params, "device": "soil-sensor-01"}),
        ):
            with self.subTest(path=path):
                self.assertEqual(get(path)[0], 400)

        self.database.unlink()
        status, _, body = get(valid_path)
        self.assertEqual(status, 503)
        self.assertFalse(json.loads(body)["ok"])
        self.assertFalse(self.database.exists())
        status, _, body = get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pi IoT Dashboard", body)


if __name__ == "__main__":
    unittest.main()
