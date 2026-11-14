# IoT Platform Finalization TODO

This checklist tracks future work for turning the Raspberry Pi IoT learning project into a durable home IoT platform. It is intentionally separate from the migration docs so future chats can quickly see what remains.

## Current Baseline

- [x] Create service-owned source layout under `services/`.
- [x] Migrate MQTT listener into `services/mqtt-listener/`.
- [x] Migrate health monitor into `services/health-monitor/`.
- [x] Migrate dashboard into `services/dashboard/`.
- [x] Retain legacy wrapper scripts during migration.
- [x] Move runtime data to `data/logs/` and `data/status/`.
- [x] Centralize shared Pi platform constants in `config/platform.py`.
- [x] Define the current device onboarding contract.

## Preserve Before Expanding

Live verification steps: `docs/preserve-before-expanding.md`.

- [x] Confirm the live Raspberry Pi repository has the latest documentation from this repo.
- [x] Confirm all live systemd units still point to the intended `services/` scripts.
- [x] Confirm `WorkingDirectory=/home/zack/projects/raspberry-pi` remains correct for live services.
- [x] Confirm reboot behavior for `mqtt-listener.service`, `health-monitor.timer`, and `iot-dashboard.service`.
- [x] Keep runtime data out of Git while preserving `data/logs/.gitkeep` and `data/status/.gitkeep`.

## Known Consistency Items

- [x] Keep ESP32 firmware version references aligned across `src/main.cpp`, README examples, and firmware source-contract tests.
- [x] Retain `docs/current-state-architecture.md` as the historical pre-migration baseline; use `docs/service-layout.md` for the current layout.
- [x] Label legacy `logs/` commands in the old migration docs as historical; current runtime paths are under `data/`.

## Device Model

- [x] Promote `home/devices/<device-id>/<message-type>` from documentation contract into parsed platform behavior.
- [x] Validate that JSON payload `device` matches the topic `<device-id>`.
- [x] Separate derived device state from raw MQTT event logging.
- [x] Treat retained availability messages as first-class device state.
- [x] Combine availability state and heartbeat freshness into a clearer health model.
- [x] Define minimum fields for `status`, `telemetry`, `commands`, and `responses`.
- [x] Use three declared publish intervals for sleepy devices instead of the fixed 30-second freshness window.

## Data Storage

- [ ] Decide when to introduce SQLite.
- [ ] Design database tables for raw MQTT events, latest device state, device registry, and telemetry.
- [ ] Define retention rules for text logs, JSONL, CSV, and future database data.
- [ ] Plan migration from CSV-backed health status to database-backed health status.
- [ ] Keep JSONL as an easy raw-event archive unless a better replacement is chosen.

## Dashboard

- [x] Add device detail pages or expandable rows.
- [x] Display selected telemetry fields beyond the fixed health columns.
- [x] Add timestamps and stale-data indicators that are easy to understand.
- [x] Show availability state separately from heartbeat freshness.
- [ ] Add simple charts after the storage model is stable.
- [ ] Keep the dashboard usable on the Raspberry Pi at `http://localhost:8080`.

## Configuration and Secrets

- [ ] Decide whether Pi services should keep fixed constants or support environment-variable overrides.
- [ ] Add a documented non-secret config pattern if settings need to vary by host.
- [ ] Keep Wi-Fi, MQTT, OTA, API keys, and other secrets out of Git.
- [ ] Add MQTT authentication only after the device onboarding path remains stable.

## Operations

- [ ] Add deployment notes for copying repository-owned systemd units into `/etc/systemd/system/`.
- [ ] Add a single service verification checklist for post-reboot checks.
- [ ] Add backup/restore notes for runtime data.
- [ ] Decide whether runtime data should eventually live outside the Git checkout.
- [ ] Add log rotation or retention management.

## Testing

- [ ] Add tests for the device onboarding contract constants and examples as the contract grows.
- [ ] Add tests for topic parsing when implemented.
- [ ] Add tests for availability-driven status when implemented.
- [ ] Add integration tests that can run against a local Mosquitto broker when available.
- [ ] Add documentation consistency checks for firmware version, paths, and service names.

## Project Integration

- [ ] Use `docs/chat-handoff.md` when starting a new Codex chat.
- [ ] Use the generic integration prompt in `docs/chat-handoff.md` for other project chats.
- [ ] For each outside project, inventory current MQTT topics, payloads, device IDs, scripts, services, secrets, and deployment assumptions before changing code.
- [ ] Align each project with `docs/device-onboarding.md` before adding platform-specific features.
- [ ] Add one project at a time and verify listener logs, health status, and dashboard behavior before moving to the next.

## Not Yet

- [ ] Do not add fleet-wide OTA management yet.
- [ ] Do not add MQTT-triggered firmware downloads yet.
- [ ] Do not add automatic update checking yet.
- [ ] Do not add a device registry until the device contract has been exercised by at least one additional project.
- [ ] Do not replace the working CSV/JSONL pipeline until a database migration plan exists.
