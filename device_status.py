from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

LEGACY_TARGET_PATH = (
    Path(__file__).resolve().parent
    / "services"
    / "health-monitor"
    / "device_status.py"
)


def _load_target() -> ModuleType:
    """Load the service-owned device status helper."""
    spec = importlib.util.spec_from_file_location(
        "service_health_monitor_device_status_legacy_wrapper",
        LEGACY_TARGET_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_target = _load_target()

CSV_PATH = _target.CSV_PATH
ONLINE_THRESHOLD = _target.ONLINE_THRESHOLD
CSV_COLUMNS = _target.CSV_COLUMNS
REPORT_COLUMNS = _target.REPORT_COLUMNS

current_timestamp = _target.current_timestamp
parse_received_at = _target.parse_received_at
read_csv_rows = _target.read_csv_rows
normalize_row = _target.normalize_row
latest_rows_by_device = _target.latest_rows_by_device
status_for = _target.status_for
build_device_reports = _target.build_device_reports
print_health_report = _target.print_health_report
run = _target.run
main = _target.main

__all__ = [
    "LEGACY_TARGET_PATH",
    "CSV_PATH",
    "ONLINE_THRESHOLD",
    "CSV_COLUMNS",
    "REPORT_COLUMNS",
    "current_timestamp",
    "parse_received_at",
    "read_csv_rows",
    "normalize_row",
    "latest_rows_by_device",
    "status_for",
    "build_device_reports",
    "print_health_report",
    "run",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
