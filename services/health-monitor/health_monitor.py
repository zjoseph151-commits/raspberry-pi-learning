from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterable

SERVICE_DIR = Path(__file__).resolve().parent


def _load_service_device_status() -> ModuleType:
    """Load the helper beside this script without depending on import order."""
    module_path = SERVICE_DIR / "device_status.py"
    spec = importlib.util.spec_from_file_location(
        "service_health_monitor_device_status",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


device_status = _load_service_device_status()

STATUS_JSON_PATH = Path("logs/device_status.json")
CSV_PATH = device_status.CSV_PATH


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
        "devices": device_status.build_device_reports(rows, generated_at),
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
    clock: Callable[[], datetime] = device_status.current_timestamp,
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
        rows = device_status.read_csv_rows(csv_path)
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
