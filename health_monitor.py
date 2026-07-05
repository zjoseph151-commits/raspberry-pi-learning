from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from device_status import CSV_PATH, build_device_reports, current_timestamp, read_csv_rows

STATUS_JSON_PATH = Path("logs/device_status.json")


def build_status_report(
    rows: Iterable[dict[str, str]],
    generated_at: datetime,
    source_path: Path,
    message: str | None = None,
) -> dict[str, object]:
    """Build the latest per-device status snapshot written by the monitor."""
    report: dict[str, object] = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "source": str(source_path),
        "devices": build_device_reports(rows, generated_at),
    }

    if message:
        report["message"] = message

    return report


def write_status_report(json_path: Path, report: dict[str, object]) -> None:
    """Create the logs folder if needed and write the latest JSON snapshot."""
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(report, json_file, indent=2)
        json_file.write("\n")


def print_status_report(report: dict[str, object]) -> None:
    """Print the same JSON report that is written to disk."""
    json.dump(report, sys.stdout, indent=2)
    print()


def run(
    csv_path: Path = CSV_PATH,
    json_path: Path = STATUS_JSON_PATH,
    clock: Callable[[], datetime] = current_timestamp,
) -> int:
    """Read the MQTT CSV log, write JSON status, and print the result."""
    csv_path = Path(csv_path)
    generated_at = clock()

    if not csv_path.exists():
        report = build_status_report(
            [],
            generated_at,
            csv_path,
            f"No CSV log found at {csv_path}.",
        )
    else:
        rows = read_csv_rows(csv_path)
        report = build_status_report(rows, generated_at, csv_path)
        if not report["devices"]:
            report["message"] = f"No device messages found in {csv_path}."

    write_status_report(json_path, report)
    print_status_report(report)
    return 0


def main() -> int:
    """CLI entrypoint for `python health_monitor.py`."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
