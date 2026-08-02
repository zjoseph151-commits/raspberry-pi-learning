from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

LEGACY_TARGET_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "mqtt-listener"
    / "listener.py"
)


def _load_target() -> ModuleType:
    """Load the service-owned MQTT listener."""
    spec = importlib.util.spec_from_file_location(
        "service_mqtt_listener_legacy_wrapper",
        LEGACY_TARGET_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_target = _load_target()

BROKER_HOST = _target.BROKER_HOST
BROKER_PORT = _target.BROKER_PORT
TOPIC_FILTER = _target.TOPIC_FILTER
LOG_PATH = _target.LOG_PATH
JSONL_PATH = _target.JSONL_PATH
CSV_PATH = _target.CSV_PATH
CSV_COLUMNS = _target.CSV_COLUMNS

current_timestamp = _target.current_timestamp
decode_payload = _target.decode_payload
parse_json_payload = _target.parse_json_payload
compact_json = _target.compact_json
format_log_line = _target.format_log_line
format_jsonl_record = _target.format_jsonl_record
format_csv_row = _target.format_csv_row
append_log_line = _target.append_log_line
append_jsonl_record = _target.append_jsonl_record
append_csv_row = _target.append_csv_row
handle_message = _target.handle_message
create_mqtt_client = _target.create_mqtt_client
run_listener = _target.run_listener

__all__ = [
    "LEGACY_TARGET_PATH",
    "BROKER_HOST",
    "BROKER_PORT",
    "TOPIC_FILTER",
    "LOG_PATH",
    "JSONL_PATH",
    "CSV_PATH",
    "CSV_COLUMNS",
    "current_timestamp",
    "decode_payload",
    "parse_json_payload",
    "compact_json",
    "format_log_line",
    "format_jsonl_record",
    "format_csv_row",
    "append_log_line",
    "append_jsonl_record",
    "append_csv_row",
    "handle_message",
    "create_mqtt_client",
    "run_listener",
]


if __name__ == "__main__":
    run_listener()
