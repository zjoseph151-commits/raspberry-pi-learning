from __future__ import annotations

from typing import Any

from config.platform import DEVICE_TOPIC_ROOT, DEVICE_TOPIC_SUFFIXES


def is_device_namespace_topic(topic: str) -> bool:
    return topic == DEVICE_TOPIC_ROOT or topic.startswith(f"{DEVICE_TOPIC_ROOT}/")


def parse_device_topic(topic: str) -> tuple[str, str] | None:
    """Parse a canonical topic into its device ID and message type."""
    parts = topic.split("/")
    root_parts = DEVICE_TOPIC_ROOT.split("/")
    if len(parts) != len(root_parts) + 2 or parts[: len(root_parts)] != root_parts:
        return None

    device_id, message_type = parts[-2:]
    if not device_id or message_type not in DEVICE_TOPIC_SUFFIXES:
        return None

    return device_id, message_type


def validate_device_payload(topic: str, payload: Any) -> str | None:
    """Return a validation code for canonical messages, or None when valid."""
    if not is_device_namespace_topic(topic):
        return None

    parsed_topic = parse_device_topic(topic)
    if parsed_topic is None:
        return "invalid_topic"
    if not isinstance(payload, dict):
        return "payload_not_object"

    device_id, message_type = parsed_topic
    payload_device = payload.get("device")
    if message_type != "commands" or payload_device is not None:
        if not isinstance(payload_device, str) or not payload_device:
            return "missing_device"
        if payload_device != device_id:
            return "device_mismatch"

    payload_type = payload.get("type")
    if payload_type is not None and payload_type != message_type:
        return "type_mismatch"

    if message_type in {"commands", "responses"}:
        if not isinstance(payload.get("command"), str) or not payload["command"]:
            return "missing_command"
    if message_type == "responses" and not isinstance(payload.get("success"), bool):
        return "missing_success"

    return None
