from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable

SERVICE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.platform import (
    DEVICE_AVAILABILITY_VALUES,
    DEVICE_STATUS_PATH,
    DEVICE_TOPIC_ROOT,
    MQTT_JSONL_PATH,
    MQTT_LOG_PATH,
)


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

STATUS_JSON_PATH = DEVICE_STATUS_PATH
CSV_PATH = device_status.CSV_PATH
JSONL_PATH = MQTT_JSONL_PATH
LOG_PATH = MQTT_LOG_PATH
DEVICE_TOPIC_ROOT_PARTS = DEVICE_TOPIC_ROOT.split("/")
AVAILABILITY_VALUES = {value.lower() for value in DEVICE_AVAILABILITY_VALUES}


def parse_device_topic(topic: str) -> tuple[str, str] | None:
    """Return device ID and message type for `home/devices/<device>/<type>`."""
    parts = topic.split("/")
    expected_length = len(DEVICE_TOPIC_ROOT_PARTS) + 2

    if len(parts) != expected_length:
        return None

    if parts[: len(DEVICE_TOPIC_ROOT_PARTS)] != DEVICE_TOPIC_ROOT_PARTS:
        return None

    device_id = parts[-2].strip()
    message_type = parts[-1].strip()

    if not device_id or not message_type:
        return None

    return device_id, message_type


def read_jsonl_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Read valid JSON Lines records, skipping malformed lines."""
    jsonl_path = Path(jsonl_path)
    if not jsonl_path.exists():
        return []

    records = []
    with jsonl_path.open("r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(record, dict):
                records.append(record)

    return records


def parse_availability_log_line(line: str) -> dict[str, Any] | None:
    """Extract retained plain-text availability from the listener text log."""
    parts = line.rstrip("\n").split(" | ")
    if len(parts) < 3:
        return None

    received_at = parts[0]
    topic = ""
    payload = ""

    for index, part in enumerate(parts[1:], start=1):
        if part.startswith("topic="):
            topic = part.removeprefix("topic=")
        elif part.startswith("payload="):
            payload = " | ".join([part.removeprefix("payload="), *parts[index + 1 :]])
            break

    parsed_topic = parse_device_topic(topic)
    state = payload.strip().lower()

    if parsed_topic is None or state not in AVAILABILITY_VALUES:
        return None

    device_id, message_type = parsed_topic
    if message_type != "availability":
        return None

    return {
        "received_at": received_at,
        "topic": topic,
        "payload": {
            "device": device_id,
            "type": "availability",
            "availability": state,
        },
    }


def read_availability_log_records(log_path: Path) -> list[dict[str, Any]]:
    """Read availability events that predate structured availability JSONL."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []

    records = []
    with log_path.open("r", encoding="utf-8") as log_file:
        for line in log_file:
            record = parse_availability_log_line(line)
            if record is not None:
                records.append(record)

    return records


def event_device_and_type(record: dict[str, Any]) -> tuple[str, str]:
    """Resolve device ID and event type from payload first, then topic."""
    topic = str(record.get("topic", ""))
    payload = record.get("payload")
    payload_object = payload if isinstance(payload, dict) else {}
    parsed_topic = parse_device_topic(topic)
    topic_device, topic_type = parsed_topic or ("", "")

    device_id = str(payload_object.get("device") or topic_device).strip()
    message_type = str(payload_object.get("type") or topic_type).strip()

    return device_id, message_type


def event_summary(record: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one structured MQTT event for dashboard details."""
    received_at = str(record.get("received_at", ""))
    parsed_received_at = device_status.parse_received_at(received_at)
    payload = record.get("payload")

    if parsed_received_at is None or not isinstance(payload, dict):
        return None

    return {
        "received_at": received_at,
        "topic": str(record.get("topic", "")),
        "fields": payload,
        "_parsed_received_at": parsed_received_at,
    }


def public_event(summary: dict[str, Any]) -> dict[str, Any]:
    """Remove internal comparison fields before writing dashboard JSON."""
    return {
        key: value
        for key, value in summary.items()
        if not key.startswith("_")
    }


def latest_detail_records(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build latest status, telemetry, and availability details per device."""
    details: dict[str, dict[str, Any]] = {}
    event_keys = {
        "status": "latest_status",
        "telemetry": "latest_telemetry",
        "availability": "availability",
    }

    for record in records:
        device_id, message_type = event_device_and_type(record)
        event_key = event_keys.get(message_type)
        summary = event_summary(record)

        if not device_id or event_key is None or summary is None:
            continue

        if event_key == "availability":
            state = str(summary["fields"].get("availability", "")).lower()
            if state not in AVAILABILITY_VALUES:
                continue
            summary["state"] = state

        device_details = details.setdefault(device_id, {})
        current = device_details.get(event_key)

        if current is None or summary["_parsed_received_at"] > current["_parsed_received_at"]:
            device_details[event_key] = summary

    for device_details in details.values():
        for event_key, summary in list(device_details.items()):
            device_details[event_key] = public_event(summary)

    return details


def latest_detail_event(device_details: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return the newest enriched event for devices absent from the CSV report."""
    latest: tuple[str, dict[str, Any], datetime] | None = None

    for event_type, event in device_details.items():
        if not isinstance(event, dict):
            continue

        parsed_received_at = device_status.parse_received_at(
            str(event.get("received_at", ""))
        )
        if parsed_received_at is None:
            continue

        if latest is None or parsed_received_at > latest[2]:
            latest = (event_type, event, parsed_received_at)

    if latest is None:
        return None

    return latest[0], latest[1]


def merge_device_details(
    reports: Iterable[dict[str, str]],
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach richer MQTT event details while preserving fixed report fields."""
    merged: dict[str, dict[str, Any]] = {
        report["device"]: dict(report)
        for report in reports
        if report.get("device")
    }

    for device_id, device_details in details.items():
        report = merged.get(device_id)

        if report is None:
            latest = latest_detail_event(device_details)
            event_type, latest_event = latest or ("", {})
            fields = latest_event.get("fields", {}) if isinstance(latest_event, dict) else {}
            fields = fields if isinstance(fields, dict) else {}

            report = {
                "device": device_id,
                "status": "UNKNOWN",
                "received_at": str(latest_event.get("received_at", "")),
                "topic": str(latest_event.get("topic", "")),
                "type": str(fields.get("type", event_type.replace("latest_", ""))),
                "count": str(fields.get("count", "")),
                "uptime_ms": str(fields.get("uptime_ms", "")),
                "wifi_rssi": str(fields.get("wifi_rssi", "")),
            }
            merged[device_id] = report

        report.update(device_details)

    return [merged[device_id] for device_id in sorted(merged)]


def build_status_report(
    rows: Iterable[dict[str, str]],
    generated_at: datetime,
    source_path: Path,
    message: str | None = None,
    detail_records: Iterable[dict[str, Any]] | None = None,
) -> dict[str, object]:
    """Build the latest per-device status snapshot written by the monitor."""
    reports = device_status.build_device_reports(rows, generated_at)
    if detail_records is not None:
        reports = merge_device_details(reports, latest_detail_records(detail_records))

    report: dict[str, object] = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "source": str(source_path),
        "devices": reports,
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
    jsonl_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    """Read the MQTT CSV log, write JSON status, and print the result."""
    csv_path = Path(csv_path)
    jsonl_path = Path(jsonl_path) if jsonl_path is not None else csv_path.with_suffix(".jsonl")
    log_path = Path(log_path) if log_path is not None else csv_path.with_suffix(".log")
    generated_at = clock()
    detail_records = [
        *read_jsonl_records(jsonl_path),
        *read_availability_log_records(log_path),
    ]

    if not csv_path.exists():
        report = build_status_report(
            [],
            generated_at,
            csv_path,
            f"No CSV log found at {csv_path}.",
            detail_records,
        )
    else:
        rows = device_status.read_csv_rows(csv_path)
        report = build_status_report(rows, generated_at, csv_path, detail_records=detail_records)
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
