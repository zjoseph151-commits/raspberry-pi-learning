from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "services" / "telemetry-history" / "import_history.py"
spec = importlib.util.spec_from_file_location("telemetry_history", SCRIPT)
assert spec is not None and spec.loader is not None
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)

DEVICE = "esp32-c3-climate-01"
TOPIC = f"home/devices/{DEVICE}/telemetry"
TIMESTAMP = "2026-11-18T11:35:50-07:00"


def archive_line(**overrides):
    return json.dumps({
        "topic": TOPIC,
        "received_at": TIMESTAMP,
        "payload": {"device": DEVICE, "temperature_c": 22, "humidity_percent": 45},
        **overrides,
    }).encode("ascii") + b"\n"


class TelemetryHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.archive = Path(directory.name) / "messages.jsonl"
        self.database = Path(directory.name) / "history" / "telemetry.sqlite3"

    def import_history(self, **kwargs):
        return history.import_archive(self.archive, self.database, **kwargs)

    def query(self, sql):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(sql).fetchall()

    def append(self, data):
        with self.archive.open("ab") as archive:
            archive.write(data)

    def test_imports_only_valid_canonical_climate_telemetry(self):
        valid = archive_line()
        self.archive.write_bytes(b"".join((
            b"{broken\n", b"\xff\n", b"[]\n", b"\n",
            archive_line(topic=f"home/devices/{DEVICE}/status"),
            archive_line(topic="home/devices/soil-sensor-01/telemetry"),
            archive_line(validation_error="flagged"),
            archive_line(payload={"device": "another-device"}),
            archive_line(payload={"device": DEVICE, "type": "status"}),
            archive_line(received_at="2026-11-18T11:35:50"),
            valid,
        )))
        report = self.import_history()
        self.assertEqual(report.lines_scanned, 11)
        self.assertEqual(report.matched_events, 1)
        self.assertEqual(report.inserted_readings, 2)
        self.assertEqual(report.byte_offset, self.archive.stat().st_size)
        self.assertEqual(self.query(
            "SELECT device_id, metric, received_at_utc, value, quality "
            "FROM telemetry_readings ORDER BY metric"
        ), [
            (DEVICE, "humidity_percent", 1795026950, 45.0, "ok"),
            (DEVICE, "temperature_c", 1795026950, 22.0, "ok"),
        ])

    def test_preserves_explicit_failed_missing_and_invalid_values(self):
        payloads = (
            {"sensor_ok": False, "temperature_c": 22, "humidity_percent": 45},
            {"temperature_c": None},
            {"temperature_c": True, "humidity_percent": 101},
            {"temperature_c": float("inf"), "humidity_percent": "40"},
            {"temperature_c": 10 ** 400, "humidity_percent": -1},
        )
        self.archive.write_bytes(b"".join(
            archive_line(payload={"device": DEVICE, **payload}) for payload in payloads
        ))
        self.assertEqual(self.import_history().inserted_readings, 10)
        self.assertEqual(self.query(
            "SELECT quality, count(value), count(*) FROM telemetry_readings GROUP BY quality"
        ), [("invalid", 0, 6), ("missing", 0, 2), ("sensor_failed", 0, 2)])

    def test_resume_and_replay_keep_distinct_events_in_same_second(self):
        start = archive_line()
        self.archive.write_bytes(start)
        self.assertEqual(self.import_history().inserted_readings, 2)
        self.assertEqual(self.import_history().lines_scanned, 0)

        self.append(archive_line(received_at="2026-11-18T18:35:50Z", payload={
            "humidity_percent": 45, "temperature_c": 22, "device": DEVICE,
        }))
        self.append(archive_line(payload={"device": DEVICE, "temperature_c": 23, "humidity_percent": 45}))
        with patch.object(history, "BATCH_LINES", 1):
            report = self.import_history()
        self.assertEqual((report.lines_scanned, report.matched_events, report.inserted_readings), (2, 2, 2))
        report = self.import_history(replay=True)
        self.assertEqual((report.lines_scanned, report.inserted_readings), (3, 0))
        self.assertEqual(report.replay_reason, "explicit replay")
        self.assertEqual(self.query(
            "SELECT value FROM telemetry_readings WHERE metric = 'temperature_c' ORDER BY value"
        ), [(22.0,), (23.0,)])

    def test_leaves_partial_or_oversized_tail_until_line_is_complete(self):
        first = archive_line()
        self.archive.write_bytes(first + b"x" * 2000)
        with patch.object(history, "MAX_LINE_BYTES", 512):
            first_report = self.import_history()
            self.assertEqual(first_report.byte_offset, len(first))
            self.assertEqual(first_report.lines_scanned, 1)
            self.assertEqual(self.import_history().lines_scanned, 0)
            next_line = archive_line(received_at="2026-11-18T11:36:51-07:00")
            self.append(b"\n" + next_line[:-1])
            second_report = self.import_history()
            self.assertEqual(second_report.lines_scanned, 1)
            self.assertEqual(second_report.inserted_readings, 0)
            self.assertEqual(second_report.byte_offset, len(first) + 2001)
            self.append(b"\n")
            self.assertEqual(self.import_history().inserted_readings, 2)

    def test_replays_replacement_or_same_file_rewrite_without_duplicates(self):
        original = archive_line()
        self.archive.write_bytes(original)
        self.import_history()

        replacement = self.archive.with_suffix(".new")
        replacement.write_bytes(original)
        replacement.replace(self.archive)
        report = self.import_history()
        self.assertEqual(report.replay_reason, "archive was replaced")
        self.assertEqual(report.inserted_readings, 0)

        changed = archive_line(received_at="2026-11-18T11:36:51-07:00")
        self.assertEqual(len(changed), len(original))
        self.archive.write_bytes(changed)
        report = self.import_history()
        self.assertEqual(report.replay_reason, "archive was truncated or rewritten")
        self.assertEqual(report.inserted_readings, 2)

    def test_batch_and_cursor_roll_back_together_on_error(self):
        first = archive_line()
        self.archive.write_bytes(first)
        self.import_history()
        self.append(archive_line(received_at="2026-11-18T11:36:51-07:00"))
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("""
                CREATE TRIGGER fail_checkpoint BEFORE UPDATE ON import_cursors
                BEGIN SELECT RAISE(ABORT, 'test failure'); END
            """)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "test failure"):
                self.import_history()
            self.assertEqual(db.execute("SELECT count(*) FROM telemetry_readings").fetchone(), (2,))
            self.assertEqual(db.execute("SELECT byte_offset FROM import_cursors").fetchone(), (len(first),))
            db.execute("DROP TRIGGER fail_checkpoint")
        self.assertEqual(self.import_history().inserted_readings, 2)

    def test_missing_archive_and_unavailable_database_do_not_change_source(self):
        with self.assertRaises(FileNotFoundError):
            self.import_history()
        self.assertFalse(self.database.exists())

        data = archive_line()
        self.archive.write_bytes(data)
        self.database.parent.mkdir()
        self.database.write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.import_history()
        self.assertEqual(self.archive.read_bytes(), data)

        with self.assertRaises(ValueError):
            history.import_archive(self.archive, self.archive)
        self.assertEqual(self.archive.read_bytes(), data)

    def test_cli_runs_from_repository_root(self):
        self.archive.write_bytes(archive_line())
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--jsonl", str(self.archive), "--database", str(self.database),
        ], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertIn("matched 1 climate events, inserted 2 readings", result.stdout)


if __name__ == "__main__":
    unittest.main()
