from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

LEGACY_TARGET_PATH = (
    Path(__file__).resolve().parent
    / "services"
    / "health-monitor"
    / "health_monitor.py"
)


def _load_target() -> ModuleType:
    """Load the service-owned health monitor entrypoint."""
    spec = importlib.util.spec_from_file_location(
        "service_health_monitor_legacy_wrapper",
        LEGACY_TARGET_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_target = _load_target()

device_status = _target.device_status
STATUS_JSON_PATH = _target.STATUS_JSON_PATH
CSV_PATH = _target.CSV_PATH

build_status_report = _target.build_status_report
write_status_report = _target.write_status_report
print_status_report = _target.print_status_report
run = _target.run
main = _target.main

__all__ = [
    "LEGACY_TARGET_PATH",
    "device_status",
    "STATUS_JSON_PATH",
    "CSV_PATH",
    "build_status_report",
    "write_status_report",
    "print_status_report",
    "run",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
