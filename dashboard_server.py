from __future__ import annotations

import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

STATUS_JSON_PATH = Path("logs/device_status.json")
HOST = "0.0.0.0"
PORT = 8080


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


def status_badge(status: Any) -> str:
    """Render a clear ONLINE/OFFLINE status label."""
    normalized = str(status or "UNKNOWN").upper()
    css_class = "online" if normalized == "ONLINE" else "offline"
    return f'<span class="status {css_class}">{text(normalized)}</span>'


def render_device_row(device: dict[str, Any]) -> str:
    """Render one device row from the health monitor JSON shape."""
    return (
        "<tr>"
        f"<td>{text(device.get('device', ''))}</td>"
        f"<td>{status_badge(device.get('status', 'UNKNOWN'))}</td>"
        f"<td>{text(device.get('received_at', ''))}</td>"
        f"<td>{text(device.get('topic', ''))}</td>"
        f"<td>{text(device.get('type', ''))}</td>"
        f"<td>{text(device.get('count', ''))}</td>"
        f"<td>{text(device.get('uptime_ms', ''))}</td>"
        f"<td>{text(device.get('wifi_rssi', ''))}</td>"
        "</tr>"
    )


def build_dashboard_html(status_report: dict[str, Any]) -> str:
    """Build a simple auto-refreshing dashboard page."""
    generated_at = text(status_report.get("generated_at", ""))
    message = status_report.get("message", "")
    devices = status_report.get("devices", [])
    device_rows = ""

    if isinstance(devices, list) and devices:
        device_rows = "\n".join(
            render_device_row(device)
            for device in devices
            if isinstance(device, dict)
        )
    else:
        device_rows = (
            '<tr><td colspan="8" class="empty">No device status data available.</td></tr>'
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
    }}
    th {{
      background: #e5e7eb;
    }}
    .status {{
      display: inline-block;
      min-width: 4.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 0.25rem;
      font-weight: bold;
      text-align: center;
    }}
    .online {{
      color: #065f46;
      background: #d1fae5;
    }}
    .offline {{
      color: #991b1b;
      background: #fee2e2;
    }}
    .message, .empty {{
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
        <th>Status</th>
        <th>Latest received_at</th>
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
