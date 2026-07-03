from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# MQTT listener configuration
# The Raspberry Pi runs the broker locally, so the listener connects to
# localhost and subscribes to every topic under the home/ namespace.
# ---------------------------------------------------------------------------
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_FILTER = "home/#"
LOG_PATH = Path("logs/mqtt_messages.log")


def current_timestamp() -> datetime:
    """Return a local timezone-aware timestamp for each received message."""
    return datetime.now().astimezone()


def decode_payload(payload: bytes | str) -> str:
    """Convert MQTT payload bytes into printable text without crashing."""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


def format_log_line(timestamp: datetime, topic: str, payload: bytes | str) -> str:
    """Build the single line printed to stdout and appended to the log file."""
    return (
        f"{timestamp.isoformat(timespec='seconds')} | "
        f"topic={topic} | payload={decode_payload(payload)}"
    )


def append_log_line(log_path: Path, line: str) -> None:
    """Create the log folder if needed, then append one message line."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{line}\n")


def handle_message(
    message,
    log_path: Path = LOG_PATH,
    clock: Callable[[], datetime] = current_timestamp,
) -> None:
    """Print and persist one MQTT message received by paho-mqtt."""
    line = format_log_line(clock(), message.topic, message.payload)
    print(line, flush=True)
    append_log_line(log_path, line)


def create_mqtt_client(
    broker_host: str = BROKER_HOST,
    broker_port: int = BROKER_PORT,
    topic_filter: str = TOPIC_FILTER,
    log_path: Path = LOG_PATH,
):
    """Create and configure a paho-mqtt client for this listener.

    paho owns reconnect handling once loop_forever() is running. The callbacks
    below keep startup and reconnect status visible in the terminal.
    """
    from paho.mqtt import client as mqtt

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print(
                f"[MQTT] Connected to {broker_host}:{broker_port}; "
                f"subscribing to {topic_filter}",
                flush=True,
            )
            client.subscribe(topic_filter)
        else:
            print(f"[MQTT] Connection failed with code {reason_code}", flush=True)

    def on_disconnect(client, userdata, disconnect_flags=None, reason_code=None, properties=None):
        if reason_code is None:
            reason_code = disconnect_flags
        print(f"[MQTT] Disconnected with code {reason_code}; paho will reconnect.", flush=True)

    def on_subscribe(client, userdata, mid, reason_codes=None, properties=None):
        print(f"[MQTT] Subscription confirmed for {topic_filter}", flush=True)

    def on_message(client, userdata, message):
        handle_message(message, log_path)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    return client


def run_listener() -> None:
    """Connect to the local broker and process messages until interrupted."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = create_mqtt_client()

    print(
        f"[MQTT] Starting listener for {TOPIC_FILTER} on "
        f"{BROKER_HOST}:{BROKER_PORT}",
        flush=True,
    )
    print(f"[MQTT] Appending messages to {LOG_PATH}", flush=True)

    client.connect_async(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    run_listener()
