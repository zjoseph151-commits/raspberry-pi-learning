from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from typing import BinaryIO, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.device_contract import parse_device_topic, validate_device_payload
from config.platform import (
    HISTORY_CLIMATE_DEVICE_ID,
    HISTORY_CLIMATE_METRIC_UNITS,
    MQTT_JSONL_PATH,
    TELEMETRY_HISTORY_PATH,
)

BATCH_LINES = 1000
MAX_LINE_BYTES = 1024 * 1024
CURSOR_CHECK_BYTES = 4096

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_readings (
    device_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    received_at_utc INTEGER NOT NULL,
    value REAL,
    quality TEXT NOT NULL CHECK (quality IN ('ok', 'sensor_failed', 'missing', 'invalid')),
    source_event_key BLOB NOT NULL,
    CHECK ((quality = 'ok') = (value IS NOT NULL)),
    PRIMARY KEY (source_event_key, metric)
);
CREATE INDEX IF NOT EXISTS telemetry_readings_by_time
    ON telemetry_readings (device_id, metric, received_at_utc);
CREATE TABLE IF NOT EXISTS import_cursors (
    source_path TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    byte_offset INTEGER NOT NULL,
    anchor BLOB NOT NULL
);
"""

Reading = tuple[str, str, int, float | None, str, bytes]


class Cursor(NamedTuple):
    file_id: str
    byte_offset: int
    anchor: bytes


class ImportReport(NamedTuple):
    lines_scanned: int
    matched_events: int
    inserted_readings: int
    byte_offset: int
    replay_reason: str | None


def measurement(payload: dict, metric: str) -> tuple[float | None, str]:
    if payload.get("sensor_ok") is False:
        return None, "sensor_failed"
    raw = payload.get(metric)
    if raw is None:
        return None, "missing"
    if type(raw) not in (int, float):
        return None, "invalid"
    try:
        value = float(raw)
    except OverflowError:
        return None, "invalid"
    if not math.isfinite(value) or (metric == "humidity_percent" and not 0 <= value <= 100):
        return None, "invalid"
    return value, "ok"


def readings_from_line(line: bytes) -> list[Reading]:
    try:
        event = json.loads(line)
        if not isinstance(event, dict) or "validation_error" in event:
            return []
        topic = event.get("topic")
        if not isinstance(topic, str) or parse_device_topic(topic) != (
            HISTORY_CLIMATE_DEVICE_ID, "telemetry"
        ):
            return []
        payload = event.get("payload")
        received_at = event.get("received_at")
        if validate_device_payload(topic, payload) is not None or not isinstance(received_at, str):
            return []
        if received_at.endswith("Z"):
            received_at = received_at[:-1] + "+00:00"
        timestamp = datetime.fromisoformat(received_at)
        if timestamp.tzinfo is None:
            return []
        utc = timestamp.astimezone(timezone.utc)
        epoch = math.floor(utc.timestamp())
        canonical = json.dumps([topic, utc.isoformat(), payload], sort_keys=True, separators=(",", ":"))
        key = sha256(canonical.encode("ascii")).digest()
    except (ValueError, OverflowError, RecursionError):
        return []

    return [
        (HISTORY_CLIMATE_DEVICE_ID, metric, epoch, *measurement(payload, metric), key)
        for metric in HISTORY_CLIMATE_METRIC_UNITS
    ]


def read_archive_line(source: BinaryIO, end: int) -> bytes | None:
    line = source.readline(min(end - source.tell(), MAX_LINE_BYTES))
    if line.endswith(b"\n"):
        return line
    # Consume oversized lines without loading them into memory or advancing past a partial line.
    while line and source.tell() < end:
        line = source.readline(min(end - source.tell(), MAX_LINE_BYTES))
        if line.endswith(b"\n"):
            return b""
    return None


def cursor_anchor(source: BinaryIO, offset: int) -> bytes:
    length = min(offset, CURSOR_CHECK_BYTES)
    source.seek(offset - length)
    anchor = source.read(length)
    if len(anchor) != length:
        raise OSError("Archive was truncated during import")
    return sha256(anchor).digest()


def load_cursor(db: sqlite3.Connection, source_path: str) -> Cursor | None:
    row = db.execute(
        "SELECT file_id, byte_offset, anchor FROM import_cursors WHERE source_path = ?",
        (source_path,),
    ).fetchone()
    return Cursor(*row) if row is not None else None


def commit_batch(
    db: sqlite3.Connection,
    source_path: str,
    previous: Cursor | None,
    cursor: Cursor,
    readings: list[Reading],
) -> int:
    with db:
        db.execute("BEGIN IMMEDIATE")
        if load_cursor(db, source_path) != previous:
            raise RuntimeError("Another importer advanced this archive; retry")
        before = db.total_changes
        db.executemany(
            """INSERT INTO telemetry_readings
               (device_id, metric, received_at_utc, value, quality, source_event_key)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (source_event_key, metric) DO NOTHING""",
            readings,
        )
        inserted = db.total_changes - before
        db.execute(
            """INSERT INTO import_cursors (source_path, file_id, byte_offset, anchor)
               VALUES (?, ?, ?, ?) ON CONFLICT (source_path) DO UPDATE SET
               file_id = excluded.file_id, byte_offset = excluded.byte_offset, anchor = excluded.anchor""",
            (source_path, *cursor),
        )
    return inserted


def import_archive(source_path: Path, database_path: Path, *, replay: bool = False) -> ImportReport:
    source_path = source_path.resolve()
    database_path = database_path.resolve()
    if source_path == database_path or (
        database_path.exists() and source_path.exists() and source_path.samefile(database_path)
    ):
        raise ValueError("Archive and database must be different files")

    with source_path.open("rb") as source:
        stat = os.fstat(source.fileno())
        end = stat.st_size
        file_id = f"{stat.st_dev}:{stat.st_ino}"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as db:
            db.executescript(SCHEMA)
            stored = load_cursor(db, str(source_path))
            offset = 0
            reason = None
            if replay:
                reason = "explicit replay"
            elif stored is not None:
                if stored.file_id != file_id:
                    reason = "archive was replaced"
                elif stored.byte_offset > end or cursor_anchor(source, stored.byte_offset) != stored.anchor:
                    reason = "archive was truncated or rewritten"
                else:
                    offset = stored.byte_offset

            lines_scanned = matched_events = inserted = 0
            while offset < end:
                batch_start = offset
                source.seek(offset)
                readings = []
                partial_line = False
                for _ in range(BATCH_LINES):
                    if offset >= end:
                        break
                    line = read_archive_line(source, end)
                    if line is None:
                        partial_line = True
                        break
                    offset = source.tell()
                    lines_scanned += 1
                    rows = readings_from_line(line)
                    matched_events += bool(rows)
                    readings.extend(rows)

                if offset == batch_start:
                    break
                cursor = Cursor(file_id, offset, cursor_anchor(source, offset))
                inserted += commit_batch(db, str(source_path), stored, cursor, readings)
                stored = cursor
                if partial_line:
                    break

    return ImportReport(lines_scanned, matched_events, inserted, offset, reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import climate telemetry from JSONL into SQLite.")
    parser.add_argument("--jsonl", type=Path, default=MQTT_JSONL_PATH, help="source JSONL archive")
    parser.add_argument("--database", type=Path, default=TELEMETRY_HISTORY_PATH, help="history database")
    parser.add_argument("--replay", action="store_true", help="rescan the archive without duplicating readings")
    args = parser.parse_args(argv)
    try:
        report = import_archive(args.jsonl, args.database, replay=args.replay)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"History import failed: {exc}", file=sys.stderr)
        return 1
    if report.replay_reason:
        print(f"Rescanned from start: {report.replay_reason}")
    print(
        f"Scanned {report.lines_scanned} lines, matched {report.matched_events} climate events, "
        f"inserted {report.inserted_readings} readings; next byte {report.byte_offset}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
