from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

CSV_PATH = Path("logs/mqtt_messages.csv")
ONLINE_THRESHOLD = timedelta(seconds=30)
CSV_COLUMNS = [
    "received_at",
    "topic",
    "device",
    "type",
    "count",
    "uptime_ms",
    "wifi_rssi",
]
REPORT_COLUMNS = ["device", "status", *CSV_COLUMNS[:2], *CSV_COLUMNS[3:]]


def current_timestamp() -> datetime:
    """Return a local timezone-aware timestamp for status calculations."""
    return datetime.now().astimezone()


def parse_received_at(value: str) -> datetime | None:
    """Parse ISO timestamps from the MQTT CSV log, returning None if invalid."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=current_timestamp().tzinfo)
    return parsed


def read_csv_rows(csv_path: Path = CSV_PATH) -> list[dict[str, str]]:
    """Read CSV rows using only the standard library."""
    with Path(csv_path).open("r", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def normalize_row(row: dict[str, str], parsed_timestamp: datetime) -> dict[str, str]:
    """Keep the report fields stable even when some CSV values are missing."""
    normalized = {column: row.get(column, "") or "" for column in CSV_COLUMNS}
    normalized["_parsed_received_at"] = parsed_timestamp
    return normalized


def latest_rows_by_device(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Pick the newest parseable row for each device."""
    latest: dict[str, dict[str, str]] = {}

    for row in rows:
        device = (row.get("device") or "").strip()
        received_at = parse_received_at(row.get("received_at", ""))

        if not device or received_at is None:
            continue

        current = latest.get(device)
        if current is None or received_at > current["_parsed_received_at"]:
            latest[device] = normalize_row(row, received_at)

    return [latest[device] for device in sorted(latest)]


def status_for(received_at: datetime, now: datetime) -> str:
    """Return ONLINE when the latest message is within the threshold."""
    return "ONLINE" if now - received_at <= ONLINE_THRESHOLD else "OFFLINE"


def build_device_reports(
    rows: Iterable[dict[str, str]],
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Group CSV rows by device and build one health report per device."""
    now = now or current_timestamp()
    reports = []

    for row in latest_rows_by_device(rows):
        received_at = row["_parsed_received_at"]
        reports.append(
            {
                "device": row["device"],
                "status": status_for(received_at, now),
                "received_at": row["received_at"],
                "topic": row["topic"],
                "type": row["type"],
                "count": row["count"],
                "uptime_ms": row["uptime_ms"],
                "wifi_rssi": row["wifi_rssi"],
            }
        )

    return reports


def print_health_report(reports: Iterable[dict[str, str]]) -> None:
    """Print a simple SSH-friendly device health table."""
    print("Device Health Report")
    print(" | ".join(REPORT_COLUMNS))

    for report in reports:
        print(" | ".join(report.get(column, "") for column in REPORT_COLUMNS))


def run(
    csv_path: Path = CSV_PATH,
    clock: Callable[[], datetime] = current_timestamp,
) -> int:
    """Read the CSV log and print a device health report."""
    csv_path = Path(csv_path)

    if not csv_path.exists():
        print(f"No CSV log found at {csv_path}.")
        return 0

    rows = read_csv_rows(csv_path)
    reports = build_device_reports(rows, clock())

    if not reports:
        print(f"No device messages found in {csv_path}.")
        return 0

    print_health_report(reports)
    return 0


def main() -> int:
    """CLI entrypoint for `python device_status.py`."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
