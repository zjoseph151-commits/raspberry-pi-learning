from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

LEGACY_TARGET_PATH = (
    Path(__file__).resolve().parent
    / "services"
    / "dashboard"
    / "dashboard_server.py"
)


def _load_target() -> ModuleType:
    """Load the service-owned dashboard server."""
    spec = importlib.util.spec_from_file_location(
        "service_dashboard_legacy_wrapper",
        LEGACY_TARGET_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_target = _load_target()

STATUS_JSON_PATH = _target.STATUS_JSON_PATH
HOST = _target.HOST
PORT = _target.PORT

load_device_status = _target.load_device_status
text = _target.text
age_label = _target.age_label
freshness_badge = _target.freshness_badge
status_badge = _target.status_badge
availability_badge = _target.availability_badge
render_device_row = _target.render_device_row
render_device_detail_row = _target.render_device_detail_row
render_device_rows = _target.render_device_rows
build_dashboard_html = _target.build_dashboard_html
make_handler = _target.make_handler
DashboardRequestHandler = _target.DashboardRequestHandler
run_server = _target.run_server
main = _target.main

__all__ = [
    "LEGACY_TARGET_PATH",
    "STATUS_JSON_PATH",
    "HOST",
    "PORT",
    "load_device_status",
    "text",
    "age_label",
    "freshness_badge",
    "status_badge",
    "availability_badge",
    "render_device_row",
    "render_device_detail_row",
    "render_device_rows",
    "build_dashboard_html",
    "make_handler",
    "DashboardRequestHandler",
    "run_server",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
