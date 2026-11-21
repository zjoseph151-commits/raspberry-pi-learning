from __future__ import annotations

from contextlib import closing
from math import isfinite
from pathlib import Path
import sqlite3
from time import monotonic, time
from typing import Any

from config.platform import HISTORY_CLIMATE_DEVICE_ID, HISTORY_CLIMATE_METRIC_UNITS

DAY_SECONDS = 86400
RANGE_SECONDS = {"24h": DAY_SECONDS, "7d": 7 * DAY_SECONDS}
RAW_POINT_LIMIT = 1500
DAILY_BUCKET_SECONDS = 300
WEEKLY_BUCKET_SECONDS = 900
GAP_SECONDS = 180
QUERY_TIMEOUT_SECONDS = 2


def reading_point(timestamp: int, value: float | None, quality: str) -> dict[str, Any]:
    return {"timestamp_utc": timestamp, "value": value, "quality": quality}


def raw_points(rows: list[tuple[int, float | None, str]]) -> list[dict[str, Any]]:
    points = []
    previous_at = None
    previous_missing = False
    for timestamp, value, quality in rows:
        point = reading_point(timestamp, value, quality)
        point["break_before"] = previous_at is not None and (
            previous_missing or value is None or timestamp - previous_at > GAP_SECONDS
        )
        points.append(point)
        previous_at, previous_missing = timestamp, value is None
    return points


def bucketed_points(
    db: sqlite3.Connection, device: str, metric: str,
    start: int, end: int, bucket_seconds: int,
) -> list[dict[str, Any]]:
    origin = start - start % bucket_seconds
    rows = db.execute(
        """WITH events AS (
               SELECT received_at_utc, value, (received_at_utc - :origin) / :bucket_seconds AS bucket,
                      lag(received_at_utc) OVER (ORDER BY received_at_utc, rowid) AS previous_at
               FROM telemetry_readings
               WHERE device_id = :device AND metric = :metric
                 AND received_at_utc >= :start AND received_at_utc < :end
           )
           SELECT bucket, min(received_at_utc), max(received_at_utc),
                  avg(value), min(value), max(value), count(*), count(value),
                  max(previous_at >= :origin + bucket * :bucket_seconds
                      AND received_at_utc - previous_at > :gap_seconds)
           FROM events GROUP BY bucket ORDER BY bucket""",
        {
            "device": device, "metric": metric, "start": start, "end": end, "origin": origin,
            "bucket_seconds": bucket_seconds, "gap_seconds": GAP_SECONDS,
        },
    )
    points = []
    previous_last = None
    previous_has_gap = False
    for bucket, first, last, mean, low, high, samples, valid, internal_gap in rows:
        if mean is not None and not isfinite(mean):
            mean = None
        has_gap = samples != valid or bool(internal_gap) or mean is None
        points.append({
            "timestamp_utc": max(start, origin + bucket * bucket_seconds),
            "value": mean,
            "min": low,
            "max": high,
            "samples": samples,
            "valid_samples": valid,
            "has_gap": has_gap,
            # A mixed bucket can show its stats, but may not connect on either side.
            "break_before": previous_last is not None and (
                has_gap or previous_has_gap or first - previous_last > GAP_SECONDS
            ),
        })
        previous_last, previous_has_gap = last, has_gap
    return points


def query_history(
    database_path: Path, device: str, metric: str, requested_range: str,
    *, end_utc: int | None = None,
) -> dict[str, Any]:
    """Return an indexed, bounded time range from a read-only SQLite snapshot."""
    if device != HISTORY_CLIMATE_DEVICE_ID or metric not in HISTORY_CLIMATE_METRIC_UNITS:
        raise ValueError("Unsupported device or metric")
    if requested_range not in RANGE_SECONDS:
        raise ValueError("Unsupported history range")

    end = int(time()) + 1 if end_utc is None else end_utc
    start = end - RANGE_SECONDS[requested_range]
    database_uri = database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True, timeout=1)) as db:
        deadline = monotonic() + QUERY_TIMEOUT_SECONDS
        db.set_progress_handler(lambda: monotonic() >= deadline, 1000)
        db.execute("BEGIN")
        latest = db.execute(
            """SELECT received_at_utc, value, quality FROM telemetry_readings
               WHERE device_id = ? AND metric = ? AND received_at_utc < ?
               ORDER BY received_at_utc DESC, rowid DESC LIMIT 1""",
            (device, metric, end),
        ).fetchone()

        rows = []
        if requested_range == "24h":
            rows = db.execute(
                """SELECT received_at_utc, value, quality FROM telemetry_readings
                   WHERE device_id = ? AND metric = ? AND received_at_utc >= ? AND received_at_utc < ?
                   ORDER BY received_at_utc, rowid LIMIT ?""",
                (device, metric, start, end, RAW_POINT_LIMIT + 1),
            ).fetchall()
            bucket_seconds = None if len(rows) <= RAW_POINT_LIMIT else DAILY_BUCKET_SECONDS
        else:
            bucket_seconds = WEEKLY_BUCKET_SECONDS

        if bucket_seconds is None:
            points = raw_points(rows)
        else:
            points = bucketed_points(db, device, metric, start, end, bucket_seconds)

    return {
        "ok": True,
        "device": device,
        "metric": metric,
        "unit": HISTORY_CLIMATE_METRIC_UNITS[metric],
        "range": requested_range,
        "start_utc": start,
        "end_utc": end,
        "latest": reading_point(*latest) if latest is not None else None,
        "bucket_seconds": bucket_seconds,
        "points": points,
    }
