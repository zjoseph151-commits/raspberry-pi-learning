from __future__ import annotations

import json
import sys
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.platform import DASHBOARD_HOST, DASHBOARD_PORT, DEVICE_STATUS_PATH

STATUS_JSON_PATH = DEVICE_STATUS_PATH
HOST = DASHBOARD_HOST
PORT = DASHBOARD_PORT


def load_device_status(status_path: Path = STATUS_JSON_PATH) -> dict[str, Any]:
    """Read the latest health monitor JSON snapshot, with safe fallbacks."""
    status_path = Path(status_path)

    if not status_path.exists():
        return {
            "generated_at": "",
            "devices": [],
            "message": f"No device status file found at {status_path}.",
        }

    try:
        with status_path.open("r", encoding="utf-8") as status_file:
            data = json.load(status_file)
    except (OSError, json.JSONDecodeError) as error:
        return {
            "generated_at": "",
            "devices": [],
            "message": f"Could not read {status_path}: {error}",
        }

    if not isinstance(data, dict):
        return {
            "generated_at": "",
            "devices": [],
            "message": f"{status_path} did not contain a JSON object.",
        }

    data.setdefault("generated_at", "")
    data.setdefault("devices", [])
    return data


def text(value: Any) -> str:
    """Return an HTML-safe string for report values."""
    return escape(str(value if value is not None else ""))


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO timestamps from health reports."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def age_seconds(generated_at: Any, received_at: Any) -> int | None:
    """Return age at report generation time."""
    generated = parse_timestamp(generated_at)
    received = parse_timestamp(received_at)

    if generated is None or received is None:
        return None

    return max(0, int((generated - received).total_seconds()))


def age_label(generated_at: Any, received_at: Any) -> str:
    """Render a compact age label for latest device data."""
    seconds = age_seconds(generated_at, received_at)

    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, remaining_seconds = divmod(seconds, 60)
        return f"{minutes}m {remaining_seconds}s"

    hours, remaining_seconds = divmod(seconds, 3600)
    minutes = remaining_seconds // 60
    return f"{hours}h {minutes}m"


def display_value(value: Any) -> str:
    """Render MQTT field values consistently for compact details."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value if value is not None else "")


def freshness_badge(status: Any) -> str:
    """Render heartbeat freshness separately from MQTT availability."""
    normalized = str(status or "UNKNOWN").upper()
    if normalized == "ONLINE":
        label = "FRESH"
        css_class = "fresh"
    elif normalized == "OFFLINE":
        label = "STALE"
        css_class = "stale"
    else:
        label = "UNKNOWN"
        css_class = "unknown"

    return f'<span class="badge {css_class}">{text(label)}</span>'


def status_badge(status: Any) -> str:
    """Compatibility wrapper for the previous dashboard helper name."""
    return freshness_badge(status)


def availability_state(device: dict[str, Any]) -> str:
    """Return the latest retained availability state for a device."""
    availability = device.get("availability")
    if not isinstance(availability, dict):
        return "UNKNOWN"

    state = availability.get("state")
    fields = availability.get("fields")
    if state is None and isinstance(fields, dict):
        state = fields.get("availability")

    normalized = str(state or "UNKNOWN").upper()
    return normalized if normalized in {"ONLINE", "OFFLINE"} else "UNKNOWN"


def availability_badge(device: dict[str, Any]) -> str:
    """Render retained MQTT availability as its own device state."""
    state = availability_state(device)
    css_class = f"availability-{state.lower()}"
    return f'<span class="badge {css_class}">{text(state)}</span>'


def render_field_list(fields: Any) -> str:
    """Render latest MQTT payload fields as a compact definition list."""
    if not isinstance(fields, dict):
        return '<p class="muted">No fields available.</p>'

    items = []
    for key, value in fields.items():
        if key == "device":
            continue

        items.append(
            f"<dt>{text(key)}</dt>"
            f"<dd>{text(display_value(value))}</dd>"
        )

    if not items:
        return '<p class="muted">No fields available.</p>'

    return f"<dl>{''.join(items)}</dl>"


def render_event_panel(title: str, event: Any) -> str:
    """Render one latest status, telemetry, or availability event."""
    if not isinstance(event, dict):
        return ""

    fields = event.get("fields", {})
    received_at = text(event.get("received_at", ""))
    topic = text(event.get("topic", ""))

    return (
        '<section class="detail-panel">'
        f"<h2>{text(title)}</h2>"
        f'<p class="detail-meta">{received_at}</p>'
        f'<p class="detail-topic">{topic}</p>'
        f"{render_field_list(fields)}"
        "</section>"
    )


def render_device_row(device: dict[str, Any], generated_at: Any = "") -> str:
    """Render one device row from the health monitor JSON shape."""
    return (
        "<tr>"
        f"<td>{text(device.get('device', ''))}</td>"
        f"<td>{freshness_badge(device.get('status', 'UNKNOWN'))}</td>"
        f"<td>{availability_badge(device)}</td>"
        f"<td>{text(device.get('received_at', ''))}</td>"
        f"<td>{text(age_label(generated_at, device.get('received_at', '')))}</td>"
        f'<td class="topic">{text(device.get("topic", ""))}</td>'
        f"<td>{text(device.get('type', ''))}</td>"
        f"<td>{text(device.get('count', ''))}</td>"
        f"<td>{text(device.get('uptime_ms', ''))}</td>"
        f"<td>{text(device.get('wifi_rssi', ''))}</td>"
        "</tr>"
    )


def render_device_detail_row(device: dict[str, Any]) -> str:
    """Render the expandable per-device detail row."""
    panels = [
        render_event_panel("Latest Telemetry", device.get("latest_telemetry")),
        render_event_panel("Latest Status", device.get("latest_status")),
        render_event_panel("Availability Event", device.get("availability")),
    ]
    panels_html = "".join(panel for panel in panels if panel)

    if not panels_html:
        panels_html = '<p class="muted">No expanded device data available.</p>'

    return (
        '<tr class="details-row">'
        '<td colspan="10">'
        "<details>"
        "<summary>Device Details</summary>"
        f'<div class="details-grid">{panels_html}</div>'
        "</details>"
        "</td>"
        "</tr>"
    )


def render_device_rows(device: dict[str, Any], generated_at: Any = "") -> str:
    """Render the main row and its expandable detail row."""
    return (
        f"{render_device_row(device, generated_at)}\n"
        f"{render_device_detail_row(device)}"
    )


def build_dashboard_html(status_report: dict[str, Any]) -> str:
    """Build a simple auto-refreshing dashboard page."""
    generated_at_value = status_report.get("generated_at", "")
    generated_at = text(generated_at_value)
    message = status_report.get("message", "")
    devices = status_report.get("devices", [])
    device_rows = ""

    if isinstance(devices, list) and devices:
        device_rows = "\n".join(
            render_device_rows(device, generated_at_value)
            for device in devices
            if isinstance(device, dict)
        )
    else:
        device_rows = (
            '<tr><td colspan="10" class="empty">No device status data available.</td></tr>'
        )

    message_html = f'<p class="message">{text(message)}</p>' if message else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="10">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pi IoT Dashboard</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 2rem;
      color: #1f2937;
      background: #f8fafc;
    }}
    h1 {{
      margin-bottom: 0.25rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 1rem;
      background: #ffffff;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 0.65rem;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #e5e7eb;
    }}
    .badge {{
      display: inline-block;
      min-width: 4.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 0.25rem;
      font-weight: bold;
      text-align: center;
    }}
    .fresh, .availability-online {{
      color: #065f46;
      background: #d1fae5;
    }}
    .stale, .availability-offline {{
      color: #991b1b;
      background: #fee2e2;
    }}
    .unknown, .availability-unknown {{
      color: #374151;
      background: #e5e7eb;
    }}
    .topic, .detail-topic {{
      overflow-wrap: anywhere;
    }}
    details {{
      margin: 0;
    }}
    summary {{
      cursor: pointer;
      font-weight: bold;
    }}
    .details-row td {{
      background: #f9fafb;
    }}
    .details-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
      gap: 1rem;
      margin-top: 0.75rem;
    }}
    .detail-panel {{
      border: 1px solid #d1d5db;
      border-radius: 0.25rem;
      padding: 0.75rem;
      background: #ffffff;
    }}
    .detail-panel h2 {{
      margin: 0 0 0.4rem;
      font-size: 1rem;
    }}
    .detail-meta, .detail-topic {{
      margin: 0.2rem 0;
      color: #4b5563;
      font-size: 0.9rem;
    }}
    dl {{
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 0.35rem 0.75rem;
      margin: 0.75rem 0 0;
    }}
    dt {{
      color: #4b5563;
      font-weight: bold;
    }}
    dd {{
      margin: 0;
    }}
    .message, .empty, .muted {{
      color: #6b7280;
    }}
  </style>
</head>
<body>
  <h1>Pi IoT Dashboard</h1>
  <p>Generated at: {generated_at}</p>
  {message_html}
  <table>
    <thead>
      <tr>
        <th>Device</th>
        <th>Heartbeat</th>
        <th>Availability</th>
        <th>Latest received_at</th>
        <th>Age</th>
        <th>Topic</th>
        <th>Message type</th>
        <th>Heartbeat count</th>
        <th>uptime_ms</th>
        <th>wifi_rssi</th>
      </tr>
    </thead>
    <tbody>
      {device_rows}
    </tbody>
  </table>
</body>
</html>
"""


def make_handler(status_path: Path = STATUS_JSON_PATH, quiet: bool = False):
    """Create a request handler bound to a specific status JSON path."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_error(404, "Not Found")
                return

            html = build_dashboard_html(load_device_status(status_path))
            body = html.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            """Keep request logging readable for a small terminal dashboard."""
            if quiet:
                return
            print(f"[Dashboard] {self.address_string()} - {format % args}")

    return DashboardHandler


class DashboardRequestHandler:
    """Tiny wrapper used by tests to create a server with a custom handler."""

    @staticmethod
    def create_test_server(address, handler):
        return ThreadingHTTPServer(address, handler)


def run_server(
    host: str = HOST,
    port: int = PORT,
    status_path: Path = STATUS_JSON_PATH,
) -> None:
    """Serve the dashboard until the process is stopped."""
    server = ThreadingHTTPServer((host, port), make_handler(status_path))
    print(f"Pi IoT Dashboard serving on http://{host}:{port}")
    print(f"Reading device health from {status_path}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()


def main() -> int:
    """CLI entrypoint for `python dashboard_server.py`."""
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
