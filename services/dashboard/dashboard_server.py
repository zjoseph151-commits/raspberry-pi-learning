from __future__ import annotations

import json
import subprocess
import sys
from ipaddress import IPv4Address, AddressValueError, ip_address
from threading import Event, Lock
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.device_contract import validate_device_payload
from config.platform import (
    DASHBOARD_HIDDEN_DEVICE_IDS,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DEVICE_STATUS_PATH,
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
)

STATUS_JSON_PATH = DEVICE_STATUS_PATH
HOST = DASHBOARD_HOST
PORT = DASHBOARD_PORT
BIRDFEEDER_DEVICE_ID = "birdfeeder-01"
BIRDFEEDER_COMMAND_PATH = f"/api/devices/{BIRDFEEDER_DEVICE_ID}/commands"
BIRDFEEDER_COMMAND_TOPIC = f"home/devices/{BIRDFEEDER_DEVICE_ID}/commands"
BIRDFEEDER_RESPONSE_TOPIC = f"home/devices/{BIRDFEEDER_DEVICE_ID}/responses"
BIRDFEEDER_COMMANDS = frozenset({"record_now", "stay_awake", "sleep_now", "stream_on"})
BIRDFEEDER_STREAM_DURATIONS = frozenset({60, 120, 180})
BIRDFEEDER_COMMAND_LOCK = Lock()
BIRDFEEDER_SCRIPT_PATH = Path(__file__).with_name("birdfeeder_controls.js")
PORCH_DEVICE_ID = "front-porch-camera-01"
PORCH_COMMAND_PATH = f"/api/devices/{PORCH_DEVICE_ID}/commands"
PORCH_COMMANDS = frozenset({"start_stream", "stop_stream", "stream_info", "status_now"})
PORCH_COMMAND_LOCK = Lock()
PORCH_SCRIPT_PATH = Path(__file__).with_name("front_porch_controls.js")
SERVICE_UNITS = (
    ("MQTT broker", "mosquitto.service", "service"),
    ("MQTT listener", "mqtt-listener.service", "service"),
    ("Health monitor timer", "health-monitor.timer", "timer"),
    ("Health monitor", "health-monitor.service", "oneshot"),
    ("Dashboard", "iot-dashboard.service", "service"),
)
SERVICE_ACTION_PATH = "/api/services/actions"
SERVICE_ACTIONS = {
    "mosquitto.service": "restart",
    "mqtt-listener.service": "restart",
    "health-monitor.timer": "restart",
    "health-monitor.service": "start",
    "iot-dashboard.service": "restart",
}
SERVICE_ACTION_LOCK = Lock()
SERVICE_SCRIPT_PATH = Path(__file__).with_name("service_controls.js")
SERVICE_PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "Result",
    "ActiveEnterTimestamp", "StateChangeTimestamp", "ExecMainExitTimestamp",
    "LastTriggerUSec", "NextElapseUSecRealtime", "NextElapseUSecMonotonic",
)


def is_loopback_peer(address: str) -> bool:
    try:
        return ip_address(address).is_loopback
    except ValueError:
        return False


def is_local_host(host: str) -> bool:
    try:
        parsed = urlsplit(f"http://{host}")
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and (port is None or port > 0)
        and parsed.netloc == host
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


def load_service_status() -> dict[str, Any]:
    """Read a fixed set of local systemd units without invoking a shell."""
    checked_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    command = [
        "systemctl", "show", "--no-pager",
        f"--property={','.join(SERVICE_PROPERTIES)}",
        *(unit for _, unit, _ in SERVICE_UNITS),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"checked_at": checked_at, "error": "Service status unavailable", "units": []}

    units: dict[str, dict[str, str]] = {}
    for section in completed.stdout.strip().split("\n\n"):
        properties = dict(
            line.split("=", 1) for line in section.splitlines() if "=" in line
        )
        if properties.get("Id"):
            units[properties["Id"]] = properties
    if not units:
        return {"checked_at": checked_at, "error": "Service status unavailable", "units": []}

    rows = []
    for name, unit, kind in SERVICE_UNITS:
        properties = units.get(unit, {})
        load_state = properties.get("LoadState", "")
        active_state = properties.get("ActiveState", "")
        result = properties.get("Result", "")
        if not properties or load_state == "not-found":
            state, tone = "Not found", "unknown"
        elif load_state != "loaded":
            state, tone = load_state.replace("-", " ").capitalize(), "unknown"
        elif active_state == "failed":
            state, tone = "Failed", "error"
        elif kind == "oneshot":
            if result not in ("", "success"):
                state, tone = "Failed", "error"
            elif active_state in ("activating", "active"):
                state, tone = "Running", "ok"
            elif properties.get("ExecMainExitTimestamp") not in (None, "", "n/a"):
                state, tone = "Succeeded", "ok"
            else:
                state, tone = "Not run", "unknown"
        elif active_state == "active":
            state, tone = "Active", "ok"
        elif active_state == "activating":
            state, tone = "Starting", "unknown"
        else:
            state, tone = "Inactive", "error"

        if kind == "oneshot":
            last_activity = properties.get("ExecMainExitTimestamp", "")
        elif kind == "timer":
            last_activity = properties.get("LastTriggerUSec", "")
        else:
            timestamp = "ActiveEnterTimestamp" if active_state == "active" else "StateChangeTimestamp"
            last_activity = properties.get(timestamp, "")
        next_run = ""
        if kind == "timer":
            next_run = next(
                (
                    value for key in ("NextElapseUSecRealtime", "NextElapseUSecMonotonic")
                    if (value := properties.get(key, "")) not in ("", "n/a")
                ),
                "",
            )
        rows.append({
            "name": name,
            "unit": unit,
            "state": state,
            "tone": tone,
            "detail": properties.get("SubState", "") if load_state == "loaded" else load_state,
            "result": result if result else "-",
            "last_activity": last_activity if last_activity not in ("", "n/a") else "-",
            "next_run": next_run if next_run not in ("", "n/a") else "-",
        })

    error = "" if completed.returncode == 0 else "Some service status may be unavailable"
    return {"checked_at": checked_at, "error": error, "units": rows}


def run_service_action(unit: str, action: str) -> dict[str, Any]:
    if SERVICE_ACTIONS.get(unit) != action:
        raise ValueError("Unsupported service action")
    try:
        completed = subprocess.run(
            ["sudo", "-n", "/usr/bin/systemctl", "--no-block", action, unit],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Service action timed out") from error
    if completed.returncode != 0:
        raise OSError("Service action rejected; check the dashboard sudoers rule")
    verb = "Run" if action == "start" else "Restart"
    return {"ok": True, "message": f"{verb} requested for {unit}"}


def private_stream_url(value: Any, port: int) -> str:
    """Accept only a private-LAN MJPEG endpoint on the expected port."""
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        address = IPv4Address(parsed.hostname or "")
        actual_port = parsed.port
    except (AddressValueError, ValueError):
        return ""
    if (
        parsed.scheme != "http"
        or actual_port not in ((None, 80) if port == 80 else (port,))
        or parsed.path != "/stream"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not address.is_private
        or address.is_loopback
        or address.is_unspecified
    ):
        return ""
    suffix = "" if port == 80 else f":{port}"
    return f"http://{address}{suffix}/stream"


def birdfeeder_stream_url(value: Any) -> str:
    return private_stream_url(value, 81)


def porch_stream_url(value: Any) -> str:
    return private_stream_url(value, 80)


def birdfeeder_status_stream_url(device: dict[str, Any]) -> str:
    latest_status = device.get("latest_status")
    fields = latest_status.get("fields") if isinstance(latest_status, dict) else None
    address = fields.get("ip") if isinstance(fields, dict) else None
    return birdfeeder_stream_url(f"http://{address}:81/stream") if address else ""


def porch_status_stream_url(device: dict[str, Any]) -> str:
    latest_status = device.get("latest_status")
    fields = latest_status.get("fields") if isinstance(latest_status, dict) else None
    if not isinstance(fields, dict):
        return ""
    url = porch_stream_url(fields.get("stream_url"))
    if url:
        return url
    address = fields.get("ip")
    return porch_stream_url(f"http://{address}/stream") if address else ""


def publish_command_and_wait(
    device_id: str, command: str, duration_seconds: int | None
) -> dict[str, Any]:
    """Publish one non-retained command after subscribing to its response topic."""
    from paho.mqtt import client as mqtt

    command_topic = f"home/devices/{device_id}/commands"
    response_topic = f"home/devices/{device_id}/responses"
    subscribed = Event()
    answered = Event()
    result: dict[str, Any] = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            result["error"] = "Could not connect to MQTT broker"
            subscribed.set()
            return
        subscribe_result, _ = client.subscribe(response_topic)
        if subscribe_result != mqtt.MQTT_ERR_SUCCESS:
            result["error"] = "Could not subscribe to device responses"
            subscribed.set()

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            result["error"] = "Device response subscription was rejected"
        subscribed.set()

    def on_message(client, userdata, message):
        if message.topic != response_topic:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if (
            validate_device_payload(response_topic, payload) is None
            and payload.get("command") == command
        ):
            result["response"] = payload
            answered.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    payload: dict[str, Any] = {"device": device_id, "command": command}
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds

    try:
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=15)
        client.loop_start()
        if not subscribed.wait(3):
            raise TimeoutError("MQTT response subscription timed out")
        if result.get("error"):
            raise ConnectionError(result["error"])
        published = client.publish(
            command_topic,
            json.dumps(payload, separators=(",", ":")),
            qos=0,
            retain=False,
        )
        if published.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("Could not publish device command")
        if not answered.wait(8):
            raise TimeoutError("No acknowledgement; the command may have run")
    finally:
        client.disconnect()
        client.loop_stop()

    return result["response"]


def send_birdfeeder_command(command: str, duration_seconds: int | None = None) -> dict[str, Any]:
    if command not in BIRDFEEDER_COMMANDS:
        raise ValueError("Unsupported command")
    if command == "stream_on":
        if duration_seconds not in BIRDFEEDER_STREAM_DURATIONS:
            raise ValueError("Unsupported stream duration")
    elif duration_seconds is not None:
        raise ValueError("Duration is only valid for stream_on")

    response = publish_command_and_wait(BIRDFEEDER_DEVICE_ID, command, duration_seconds)
    success = response["success"]
    return {
        "ok": success,
        "command": command,
        "message": str(response.get("message") or "")[:160],
        "stream_url": (
            birdfeeder_stream_url(response.get("stream_url"))
            if success and command == "stream_on"
            else ""
        ),
        "duration_seconds": (
            duration_seconds if success and command == "stream_on" else 0
        ),
    }


def send_porch_command(command: str, duration_seconds: int | None = None) -> dict[str, Any]:
    if command not in PORCH_COMMANDS:
        raise ValueError("Unsupported command")
    if command == "start_stream":
        if type(duration_seconds) is not int or not 10 <= duration_seconds <= 600:
            raise ValueError("Unsupported stream duration")
    elif duration_seconds is not None:
        raise ValueError("Duration is only valid for start_stream")

    response = publish_command_and_wait(PORCH_DEVICE_ID, command, duration_seconds)
    success = response["success"]
    active = response.get("stream_active") is True
    remaining = response.get("stream_remaining_seconds")
    if type(remaining) is not int or remaining < 0:
        remaining = 0
    messages = {
        "start_stream": "Stream started",
        "stop_stream": "Stream stopped",
        "stream_info": "Stream active" if active else "Stream idle",
        "status_now": "Status published",
    }
    return {
        "ok": success,
        "command": command,
        "message": messages[command] if success else str(response.get("error") or "Command failed")[:160],
        "stream_url": porch_stream_url(response.get("stream_url")),
        "stream_active": active,
        "stream_remaining_seconds": remaining,
    }


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


def detail_key(device: dict[str, Any]) -> str:
    """Return a stable key for preserving each device detail row state."""
    key = str(device.get("device") or "").strip()
    if key:
        return key

    return str(device.get("topic") or "unknown-device").strip()


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


def health_badge(device: dict[str, Any]) -> str:
    """Render the monitor's combined availability and freshness state."""
    state = str(device.get("health_state") or "UNKNOWN").upper()
    if state not in {"HEALTHY", "SLEEPING", "OFFLINE", "STALE", "RECENT", "UNKNOWN"}:
        state = "UNKNOWN"
    return f'<span class="badge health-{state.lower()}">{text(state)}</span>'


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


def render_birdfeeder_controls(
    device: dict[str, Any], actions_available: bool = True
) -> str:
    if device.get("device") != BIRDFEEDER_DEVICE_ID:
        return ""

    stream_url = birdfeeder_status_stream_url(device)
    disabled = ' disabled title="Actions require an SSH tunnel"' if not actions_available else ""
    return (
        '<section class="detail-panel birdfeeder-controls" '
        f'data-birdfeeder-controls data-stream-url="{text(stream_url)}">'
        "<h2>Controls</h2>"
        '<div class="birdfeeder-actions">'
        f'<button type="button" data-birdfeeder-command="record_now"{disabled}>Record now</button>'
        f'<button type="button" data-birdfeeder-command="stay_awake"{disabled}>Stay awake</button>'
        f'<button type="button" data-birdfeeder-command="sleep_now"{disabled}>Sleep now</button>'
        '<label for="birdfeeder-stream-duration">Stream duration</label>'
        f'<select id="birdfeeder-stream-duration" data-stream-duration{disabled}>'
        '<option value="60">60s</option>'
        '<option value="120">120s</option>'
        '<option value="180">180s</option>'
        "</select>"
        f'<button type="button" data-birdfeeder-command="stream_on"{disabled}>Stream on</button>'
        "</div>"
        '<p class="birdfeeder-result" data-command-result role="status" aria-live="polite"></p>'
        '<div class="birdfeeder-stream">'
        '<strong>Stream URL</strong>'
        f'<code data-stream-address>{text(stream_url) or "Unavailable"}</code>'
        '<a data-stream-link href="#" target="_blank" rel="noopener noreferrer" hidden>Open stream</a>'
        '<span data-stream-state>Inactive</span>'
        "</div>"
        "</section>"
    )


def render_porch_controls(
    device: dict[str, Any], actions_available: bool = True
) -> str:
    if device.get("device") != PORCH_DEVICE_ID:
        return ""

    latest_status = device.get("latest_status")
    fields = latest_status.get("fields") if isinstance(latest_status, dict) else None
    fields = fields if isinstance(fields, dict) else {}
    stream_url = porch_status_stream_url(device)
    active = fields.get("stream_active") is True
    remaining = fields.get("stream_remaining_seconds")
    remaining = remaining if type(remaining) is int and remaining > 0 else 0
    received_at = latest_status.get("received_at", "") if isinstance(latest_status, dict) else ""
    disabled = ' disabled title="Actions require an SSH tunnel"' if not actions_available else ""
    return (
        '<section class="detail-panel porch-controls" '
        f'data-porch-controls data-stream-url="{text(stream_url)}" '
        f'data-stream-active="{str(active).lower()}" '
        f'data-stream-remaining="{remaining}" '
        f'data-status-at="{text(received_at)}">'
        "<h2>Controls</h2>"
        '<div class="porch-actions">'
        '<label for="porch-stream-duration">Stream duration</label>'
        f'<select id="porch-stream-duration" data-stream-duration{disabled}>'
        '<option value="10">10s</option>'
        '<option value="30">30s</option>'
        '<option value="60">60s</option>'
        '<option value="120" selected>120s</option>'
        '<option value="300">5m</option>'
        '<option value="600">10m</option>'
        "</select>"
        f'<button type="button" data-porch-command="start_stream"{disabled}>Start stream</button>'
        f'<button type="button" data-porch-command="stop_stream"{disabled}>Stop stream</button>'
        f'<button type="button" data-porch-command="stream_info"{disabled}>Stream info</button>'
        f'<button type="button" data-porch-command="status_now"{disabled}>Status now</button>'
        "</div>"
        '<p class="porch-result" data-command-result role="status" aria-live="polite"></p>'
        '<div class="porch-stream">'
        '<strong>Stream URL</strong>'
        f'<code data-stream-address>{text(stream_url) or "Unavailable"}</code>'
        '<a data-stream-link href="#" target="_blank" rel="noopener noreferrer" hidden>Open stream</a>'
        '<span data-stream-state>Inactive</span>'
        "</div>"
        "</section>"
    )


def render_device_row(device: dict[str, Any], generated_at: Any = "") -> str:
    """Render one device row from the health monitor JSON shape."""
    return (
        "<tr>"
        f"<td>{text(device.get('device', ''))}</td>"
        f"<td>{health_badge(device)}</td>"
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


def render_device_detail_row(
    device: dict[str, Any], actions_available: bool = True
) -> str:
    """Render the expandable per-device detail row."""
    panels = [
        render_event_panel("Latest Telemetry", device.get("latest_telemetry")),
        render_event_panel("Latest Status", device.get("latest_status")),
        render_event_panel("Availability Event", device.get("availability")),
        render_birdfeeder_controls(device, actions_available),
        render_porch_controls(device, actions_available),
    ]
    panels_html = "".join(panel for panel in panels if panel)

    if not panels_html:
        panels_html = '<p class="muted">No expanded device data available.</p>'

    return (
        '<tr class="details-row">'
        '<td colspan="11">'
        f'<details data-device-details-key="{text(detail_key(device))}">'
        "<summary>Device Details</summary>"
        f'<div class="details-grid">{panels_html}</div>'
        "</details>"
        "</td>"
        "</tr>"
    )


def render_device_rows(
    device: dict[str, Any], generated_at: Any = "", actions_available: bool = True
) -> str:
    """Render the main row and its expandable detail row."""
    return (
        f"{render_device_row(device, generated_at)}\n"
        f"{render_device_detail_row(device, actions_available)}"
    )


def render_service_status(report: dict[str, Any], actions_available: bool = True) -> str:
    units = report.get("units", [])
    if not units:
        return (
            '<section class="services">'
            "<h2>Services</h2>"
            f'<p class="message">{text(report.get("error") or "Service status unavailable")}</p>'
            "</section>"
        )

    rows = []
    for unit in units:
        tone = unit.get("tone") if unit.get("tone") in {"ok", "error", "unknown"} else "unknown"
        unit_id = unit.get("unit", "")
        action = SERVICE_ACTIONS.get(unit_id)
        action_html = ""
        if action:
            label = "Run now" if action == "start" else "Restart"
            disabled = ' disabled title="Actions require an SSH tunnel"' if not actions_available else ""
            action_html = (
                f'<button type="button" data-service-action="{action}" '
                f'data-service-unit="{text(unit_id)}"{disabled}>'
                f'{label}</button>'
            )
        rows.append(
            "<tr>"
            f'<td><strong>{text(unit.get("name", ""))}</strong>'
            f'<small>{text(unit.get("unit", ""))}</small></td>'
            f'<td><span class="service-state service-{tone}">{text(unit.get("state", ""))}</span></td>'
            f'<td>{text(unit.get("detail", ""))}</td>'
            f'<td>{text(unit.get("result", "-"))}</td>'
            f'<td>{text(unit.get("last_activity", "-"))}</td>'
            f'<td>{text(unit.get("next_run", "-"))}</td>'
            f'<td>{action_html}</td>'
            "</tr>"
        )
    error_html = f'<p class="message">{text(report["error"])}</p>' if report.get("error") else ""
    return (
        '<section class="services">'
        '<div class="services-heading"><h2>Services</h2>'
        f'<span>Checked {text(report.get("checked_at", ""))}</span></div>'
        f"{error_html}"
        '<p class="service-result" data-service-result role="status" aria-live="polite"></p>'
        '<div class="table-scroll"><table>'
        '<thead><tr><th>Service</th><th>State</th><th>Detail</th><th>Last result</th>'
        '<th>Last activity</th><th>Next run</th><th>Action</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def build_dashboard_html(
    status_report: dict[str, Any],
    service_report: dict[str, Any] | None = None,
    actions_available: bool = True,
) -> str:
    """Build a simple auto-refreshing dashboard page."""
    generated_at_value = status_report.get("generated_at", "")
    generated_at = text(generated_at_value)
    message = status_report.get("message", "")
    devices = status_report.get("devices", [])
    visible_devices = (
        [
            device
            for device in devices
            if isinstance(device, dict)
            and device.get("device") not in DASHBOARD_HIDDEN_DEVICE_IDS
        ]
        if isinstance(devices, list)
        else []
    )
    device_rows = ""

    if visible_devices:
        device_rows = "\n".join(
            render_device_rows(device, generated_at_value, actions_available)
            for device in visible_devices
        )
    else:
        device_rows = (
            '<tr><td colspan="11" class="empty">No device status data available.</td></tr>'
        )

    message_html = f'<p class="message">{text(message)}</p>' if message else ""
    services_html = render_service_status(service_report or {}, actions_available)
    access_html = '<p class="access-note">Read-only connection</p>' if not actions_available else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
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
      min-width: 72rem;
      border-collapse: collapse;
      margin-top: 1rem;
      background: #ffffff;
    }}
    .table-scroll {{
      overflow-x: auto;
    }}
    .services {{
      margin: 1.5rem 0 2rem;
    }}
    .access-note {{
      color: #92400e;
      font-size: 0.9rem;
      margin: 0.5rem 0 0;
    }}
    .services-heading {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 0.75rem;
    }}
    .services-heading h2 {{
      margin: 0;
      font-size: 1.2rem;
    }}
    .devices-heading {{
      margin: 0 0 0.5rem;
      font-size: 1.2rem;
    }}
    .services-heading span, .services small {{
      color: #4b5563;
      font-size: 0.8rem;
    }}
    .services table {{
      min-width: 50rem;
      margin-top: 0.5rem;
    }}
    .services button {{
      min-height: 2.25rem;
      border: 1px solid #9ca3af;
      border-radius: 4px;
      background: #ffffff;
      color: #1f2937;
      padding: 0.35rem 0.65rem;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }}
    .services button:hover:not(:disabled) {{
      background: #e5e7eb;
    }}
    .services button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}
    .service-result {{
      margin: 0.5rem 0;
      font-size: 0.9rem;
    }}
    .service-result.error {{
      color: #991b1b;
    }}
    .services small {{
      display: block;
      margin-top: 0.2rem;
    }}
    .service-state {{
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border-radius: 0.25rem;
      font-weight: bold;
      white-space: nowrap;
    }}
    .service-ok {{
      color: #065f46;
      background: #d1fae5;
    }}
    .service-error {{
      color: #991b1b;
      background: #fee2e2;
    }}
    .service-unknown {{
      color: #374151;
      background: #e5e7eb;
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
    .health-healthy {{
      color: #065f46;
      background: #d1fae5;
    }}
    .health-sleeping {{
      color: #92400e;
      background: #fef3c7;
    }}
    .health-offline {{
      color: #991b1b;
      background: #fee2e2;
    }}
    .health-stale {{
      color: #9a3412;
      background: #ffedd5;
    }}
    .health-recent {{
      color: #1e40af;
      background: #dbeafe;
    }}
    .health-unknown {{
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
    .details-row details {{
      width: min(100%, calc(100vw - 5.5rem));
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
    .birdfeeder-controls, .porch-controls {{
      grid-column: 1 / -1;
    }}
    .birdfeeder-actions, .birdfeeder-stream, .porch-actions, .porch-stream {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}
    .birdfeeder-actions button, .birdfeeder-actions select,
    .porch-actions button, .porch-actions select {{
      min-height: 2.4rem;
      border: 1px solid #9ca3af;
      border-radius: 4px;
      background: #ffffff;
      color: #1f2937;
      padding: 0.45rem 0.7rem;
      font: inherit;
    }}
    .birdfeeder-actions button, .porch-actions button {{
      cursor: pointer;
    }}
    .birdfeeder-actions button:hover:not(:disabled),
    .porch-actions button:hover:not(:disabled) {{
      background: #e5e7eb;
    }}
    .birdfeeder-actions button:disabled, .porch-actions button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}
    .birdfeeder-actions button[data-birdfeeder-command="record_now"] {{
      background: #fef2f2;
      border-color: #fca5a5;
    }}
    .birdfeeder-actions button[data-birdfeeder-command="stream_on"],
    .porch-actions button[data-porch-command="start_stream"] {{
      background: #ecfdf5;
      border-color: #6ee7b7;
    }}
    .birdfeeder-actions label, .birdfeeder-stream, .birdfeeder-result,
    .porch-actions label, .porch-stream, .porch-result {{
      font-size: 0.9rem;
    }}
    .birdfeeder-result, .porch-result {{
      min-height: 1.2rem;
      margin: 0.7rem 0;
    }}
    .birdfeeder-result.error, .porch-result.error {{
      color: #991b1b;
    }}
    .birdfeeder-stream code, .porch-stream code {{
      overflow-wrap: anywhere;
    }}
    .birdfeeder-stream a[hidden], .porch-stream a[hidden] {{
      display: none;
    }}
    .detail-meta, .detail-topic {{
      margin: 0.2rem 0;
      color: #4b5563;
      font-size: 0.9rem;
    }}
    dl {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 0.35rem 0.75rem;
      margin: 0.75rem 0 0;
    }}
    dt {{
      color: #4b5563;
      font-weight: bold;
      overflow-wrap: anywhere;
    }}
    dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .message, .empty, .muted {{
      color: #6b7280;
    }}
  </style>
  <script>
    (function () {{
      var storageKey = "pi-iot-dashboard-open-details";
      var refreshAfter = Date.now() + 10000;

      window.dashboardDeferRefresh = function (delayMs) {{
        refreshAfter = Math.max(refreshAfter, Date.now() + delayMs);
      }};

      setInterval(function () {{
        if (Date.now() >= refreshAfter) {{
          window.location.reload();
        }}
      }}, 1000);

      function readOpenKeys() {{
        try {{
          return new Set(JSON.parse(localStorage.getItem(storageKey) || "[]"));
        }} catch (error) {{
          return new Set();
        }}
      }}

      function writeOpenKeys(openKeys) {{
        try {{
          localStorage.setItem(storageKey, JSON.stringify(Array.from(openKeys)));
        }} catch (error) {{
        }}
      }}

      document.addEventListener("DOMContentLoaded", function () {{
        var openKeys = readOpenKeys();
        var detailRows = document.querySelectorAll("details[data-device-details-key]");

        detailRows.forEach(function (details) {{
          var key = details.dataset.deviceDetailsKey;
          if (openKeys.has(key)) {{
            details.open = true;
          }}

          details.addEventListener("toggle", function () {{
            if (details.open) {{
              openKeys.add(key);
            }} else {{
              openKeys.delete(key);
            }}
            writeOpenKeys(openKeys);
          }});
        }});
      }});
    }})();
  </script>
  <script src="/assets/birdfeeder-controls.js" defer></script>
  <script src="/assets/front-porch-controls.js" defer></script>
  <script src="/assets/service-controls.js" defer></script>
</head>
<body>
  <h1>Pi IoT Dashboard</h1>
  <p>Generated at: {generated_at}</p>
  {access_html}
  {message_html}
  {services_html}
  <h2 class="devices-heading">Devices</h2>
  <div class="table-scroll">
  <table>
    <thead>
      <tr>
        <th>Device</th>
        <th>Health</th>
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
  </div>
</body>
</html>
"""


def make_handler(
    status_path: Path = STATUS_JSON_PATH,
    quiet: bool = False,
    command_sender: Callable[[str, int | None], dict[str, Any]] = send_birdfeeder_command,
    porch_command_sender: Callable[[str, int | None], dict[str, Any]] = send_porch_command,
    service_status_loader: Callable[[], dict[str, Any]] = load_service_status,
    service_action_runner: Callable[[str, str], dict[str, Any]] = run_service_action,
):
    """Create a request handler bound to a specific status JSON path."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def is_local_request(self) -> bool:
            return is_loopback_peer(self.client_address[0])

        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            script_path = {
                "/assets/birdfeeder-controls.js": BIRDFEEDER_SCRIPT_PATH,
                "/assets/front-porch-controls.js": PORCH_SCRIPT_PATH,
                "/assets/service-controls.js": SERVICE_SCRIPT_PATH,
            }.get(self.path)
            if script_path is not None:
                try:
                    body = script_path.read_bytes()
                except OSError:
                    self.send_error(500, "Could not load dashboard controls")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path not in ("/", "/index.html"):
                self.send_error(404, "Not Found")
                return

            html = build_dashboard_html(
                load_device_status(status_path),
                service_status_loader(),
                actions_available=self.is_local_request(),
            )
            body = html.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            is_service_action = self.path == SERVICE_ACTION_PATH
            if self.path == BIRDFEEDER_COMMAND_PATH:
                commands = BIRDFEEDER_COMMANDS
                stream_command = "stream_on"
                stream_default = 60
                duration_valid = lambda value: value in BIRDFEEDER_STREAM_DURATIONS
                sender = command_sender
                command_lock = BIRDFEEDER_COMMAND_LOCK
            elif self.path == PORCH_COMMAND_PATH:
                commands = PORCH_COMMANDS
                stream_command = "start_stream"
                stream_default = 120
                duration_valid = lambda value: 10 <= value <= 600
                sender = porch_command_sender
                command_lock = PORCH_COMMAND_LOCK
            elif not is_service_action:
                self.send_json(404, {"ok": False, "message": "Not Found"})
                return

            if not self.is_local_request():
                self.send_json(403, {"ok": False, "message": "Actions require an SSH tunnel"})
                return

            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            fetch_site = self.headers.get("Sec-Fetch-Site")
            if (
                not is_local_host(host)
                or origin != f"http://{host}"
                or fetch_site not in (None, "same-origin", "none")
                or self.headers.get("X-Dashboard-Action") != "1"
            ):
                self.send_json(403, {"ok": False, "message": "Cross-origin request rejected"})
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(415, {"ok": False, "message": "JSON request required"})
                return

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if not 0 < length <= 256:
                self.send_json(400, {"ok": False, "message": "Invalid request size"})
                return
            try:
                request = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(400, {"ok": False, "message": "Invalid JSON"})
                return
            if not isinstance(request, dict):
                self.send_json(400, {"ok": False, "message": "JSON object required"})
                return

            if is_service_action:
                unit = request.get("unit")
                action = request.get("action")
                if (
                    set(request) != {"unit", "action"}
                    or not isinstance(unit, str)
                    or not isinstance(action, str)
                    or SERVICE_ACTIONS.get(unit) != action
                ):
                    self.send_json(400, {"ok": False, "message": "Unsupported service action"})
                    return
                if not SERVICE_ACTION_LOCK.acquire(blocking=False):
                    self.send_json(409, {"ok": False, "message": "Another service action is in progress"})
                    return
                try:
                    response = service_action_runner(unit, action)
                except TimeoutError as error:
                    self.send_json(504, {"ok": False, "message": str(error)})
                    return
                except (ConnectionError, OSError) as error:
                    self.send_json(503, {"ok": False, "message": str(error)})
                    return
                finally:
                    SERVICE_ACTION_LOCK.release()
                self.send_json(202, response)
                return

            command = request.get("command")
            if not isinstance(command, str) or command not in commands:
                self.send_json(400, {"ok": False, "message": "Unsupported command"})
                return
            duration_seconds = None
            if command == stream_command:
                duration_seconds = request.get("duration_seconds", stream_default)
                if (
                    type(duration_seconds) is not int
                    or not duration_valid(duration_seconds)
                    or set(request) not in (
                        {"command"},
                        {"command", "duration_seconds"},
                    )
                ):
                    self.send_json(400, {"ok": False, "message": "Invalid stream duration"})
                    return
            elif set(request) != {"command"}:
                self.send_json(400, {"ok": False, "message": "Unexpected command fields"})
                return

            if not command_lock.acquire(blocking=False):
                self.send_json(409, {"ok": False, "message": "Another command is in progress"})
                return
            try:
                response = sender(command, duration_seconds)
            except TimeoutError as error:
                self.send_json(504, {"ok": False, "message": str(error)})
                return
            except (ConnectionError, OSError) as error:
                self.send_json(503, {"ok": False, "message": str(error)})
                return
            finally:
                command_lock.release()
            self.send_json(200, response)

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
