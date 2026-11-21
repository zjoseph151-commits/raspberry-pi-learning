# Telemetry History Plan

This plan records the direction for collecting and charting sensor history in the custom Pi platform. The pilot importer and manual Pi backfill are verified, and the read-only query API is tested locally. The History view, live API verification, and scheduled imports are still pending. `TODO.md` tracks the work.

## Direction

- Keep MQTT and the existing listener as the intake path. Keep JSONL as the raw-event archive and the current CSV-backed health snapshot and dashboard working during the rollout.
- Use SQLite on the Pi as a queryable history derived from validated telemetry, not as an immediate replacement for every log, device-state field, or service.
- Put a dedicated History view in the existing dashboard. Link to it from Device Details; add a compact trend there only after the full view works. The History view should not inherit the overview's full-page auto-refresh.
- Start with temperature in Celsius and relative humidity from `esp32-c3-climate-01`. Offer 24-hour and 7-day ranges. Treat failed or null sensor readings and missed reporting stretches as gaps, not zeroes or connected measurements.

## Live Pi Audit: 2026-11-18

Counts are from the active JSONL archive at the time of the read-only audit. The rolling windows end at audit time, not at the last sample from each device.

| Device | Observed archive coverage | Samples | Last 24h | Last 7d | Observed cadence |
| --- | --- | ---: | ---: | ---: | --- |
| `esp32-c3-climate-01` | Aug 3 to Nov 18, 2026 | 110,632 | 1,069 | 5,777 | Usually 61-62 seconds, declared 60 seconds |
| `soil-sensor-01` | Aug 30 to Nov 18, 2026 | 20,382 | 283 | 1,229 | Commonly 303-304 seconds, with many 67-second intervals; declared 300 seconds |

- The active logs total about 457 MiB: JSONL 216 MiB, text 195 MiB, and CSV 45 MiB. No rotated copies appeared in the audit listing. The logs live on the Pi's ext4 root filesystem (`/dev/mmcblk0p2`), with about 14 GiB available. An external USB disk is mounted separately; the pilot does not need to depend on it.
- The climate archive contains 44 samples explicitly marked `sensor_ok: false`, and 44 missing or invalid values for each of `temperature_c` and `humidity_percent`. The latest climate reading was several hours old when checked. Both explicit failures and missed reports should be represented, and sleep-related `offline` availability should not create gaps by itself.
- The soil sensor publishes `moisture_percent`, `battery_percent`, and `battery_voltage`. It is a good second device, but the audit does not establish the cause of its shorter intervals. Use actual receive times rather than inventing a regular sample grid.

## Pilot Storage

- Use one `telemetry_readings` table with `device_id`, `metric`, `received_at_utc` (Pi receive time as UTC epoch seconds), nullable numeric `value`, `quality` (`ok`, `sensor_failed`, `missing`, or `invalid`), and `source_event_key`. Define units in a small metric allowlist: `temperature_c` is Celsius and `humidity_percent` is percent relative humidity. Do not store Fahrenheit as a second series for the same measurement.
- Index `(device_id, metric, received_at_utc)` for time-range reads and enforce uniqueness on `(source_event_key, metric)` for replay. Use a deterministic fingerprint of the canonical topic, normalized receive time, and payload. Different payloads in the same second remain separate; exact repeats at that timestamp are treated as one event because the current archive cannot distinguish them reliably.
- Use the shared topic and payload validators and skip events already marked with a `validation_error`. For otherwise valid pilot events, keep an explicit null reading with its quality when the sensor reports failure or an individual measurement is missing or invalid.
- Start with a single independent importer and a one-time pass over the retained active JSONL. Then resume from the last committed byte offset using file identity and a content check. Commit the batch and cursor together, leave an incomplete last line for the next run, and report file replacement or truncation. Coordinate rotation separately so the importer can finish an outgoing file before it is removed. The dashboard should never rescan the archive to serve a chart.
- Keep the importer out of the MQTT listener and start it manually before scheduling it. Measure the database size and backfill time on the Pi before choosing retention or moving storage. Keep the runtime database and any journal files out of Git.

## Manual Pi Backfill

After syncing the importer to the Pi, run this from the repository root. It reads the active archive through the size observed when the run starts, commits batches, and creates `data/history/telemetry.sqlite3` if needed. It does not change the archive and does not require service restarts or `sudo`.

```bash
cd /home/zack/projects/raspberry-pi
time ./.venv/bin/python services/telemetry-history/import_history.py
./.venv/bin/python services/telemetry-history/import_history.py
du -h data/history/telemetry.sqlite3
```

On the first run, expect two readings per unique climate event. The second run should only process lines appended since the first run took its snapshot; if the archive has not grown, it scans zero lines. `--replay` explicitly rescans the archive but does not duplicate previously indexed readings. If the log is replaced or the checkpoint no longer matches, the importer reports the reason and rereads the active file. Keep the source append-only while the importer is running and do not rotate it until the old file has been fully indexed or preserved for a separate import.

To verify sample counts and time coverage by metric and quality (times below are UTC):

```bash
./.venv/bin/python - <<'PY'
import sqlite3
from contextlib import closing

with closing(sqlite3.connect('file:data/history/telemetry.sqlite3?mode=ro', uri=True)) as db:
    for row in db.execute('''
        SELECT metric, quality, count(*),
               datetime(min(received_at_utc), 'unixepoch'),
               datetime(max(received_at_utc), 'unixepoch')
        FROM telemetry_readings GROUP BY metric, quality ORDER BY metric, quality
    '''):
        print(*row, sep=' | ')
PY
```

The climate archive was still growing at audit time, so use the audit counts as a reference, not an exact expected total. A sensor-failure event contributes one `sensor_failed` row to each metric. Empty, malformed, and oversized lines (over 1 MiB including the line terminator) are not indexed, and a final line without a newline is retried on the next run. The importer reads only the file given to it (`--jsonl` overrides the active path); it does not automatically find rotated logs.

### Verified Pi Result: 2026-11-21

- The observed import scanned 43,671 lines, matched 491 climate events, and inserted 982 readings. An immediate rerun scanned and inserted zero, with the checkpoint unchanged at byte `237769620`.
- Each metric had 110,588 good readings and 44 failed reads, matching the audit's 110,632 climate events. The earliest stored event was `2026-08-03 23:03:50 UTC` and the latest was `2026-11-18 18:35:50 UTC`. All 44 failed reads occurred at the start of the archive.
- The latest stored reading predates the verification's 24-hour window. The history query should report an empty requested range and the actual latest reading time separately, without shifting the range or implying that the sensor's current state has been verified.

## History API

`GET /api/history` uses the same read-only LAN access as the overview. It accepts exactly one `device`, `metric`, and `range`. The pilot device is `esp32-c3-climate-01`, the metrics are `temperature_c` and `humidity_percent`, and the ranges are `24h` and `7d`. For example, after deploying the API:

```bash
curl 'http://localhost:8080/api/history?device=esp32-c3-climate-01&metric=temperature_c&range=7d'
```

- The response uses UTC epoch seconds and includes the requested `[start_utc, end_utc)` interval, units, and `latest` (the last recorded value and quality before `end_utc`, even if outside the chart window). A valid window with no readings returns an empty `points` array, not an error. If there are no earlier readings either, `latest` is null.
- A 24-hour window returns up to 1,500 raw points; denser windows use five-minute summaries instead of dropping samples. Seven-day windows use 15-minute summaries. Summaries are aligned to UTC boundaries and include the mean (`value`), minimum, maximum, and total and valid sample counts. Edge buckets only include data inside the requested window.
- For raw points, a failed or invalid reading has a null value and its original `quality`. For summaries, `has_gap` marks a bucket containing invalid readings or an internal interruption; keep those buckets isolated even if they have valid statistics. In either mode, `break_before` marks a new segment, including when consecutive readings are more than three minutes apart. Never insert zeros or shift a stale window to manufacture data.
- Unsupported parameters return `400`. An unreadable or unavailable database returns `503` without affecting the overview. This API does not ingest new events; until an import timer is installed, it only sees the most recent manual import.

## Rollout

1. Read-only audit on the live Pi: inventory actual device IDs, telemetry fields and units, timestamps, publish intervals, sensor-failure behavior, available history, log sizes, free space, and storage medium. Confirm the first metrics and useful time ranges before finalizing the schema.
2. Define a small history schema and import contract. Include device, metric, value, unit, Pi `received_at`, and enough event quality/source information to distinguish failed reads and replay safely. Decide how backfill and incremental import will resume after interruption and avoid duplicates. History still covered by retained JSONL must be rebuildable from it.
3. Backfill historical validated telemetry and begin incremental import without changing the existing health/status path. Skip invalid canonical events. Test missing data, malformed lines, restarts, replay, and an unavailable database before making charts depend on the new store.
4. Verify the bounded history query API on the Pi and add the History view. Label units and local display time clearly, and refresh chart data without replacing the page or losing the selected range.
5. Define raw-log and database retention, rotation, backup, restore, and rebuild procedures before considering history durable. Keep the SQLite database on local Pi storage. Only after this slice is stable should the health monitor's full-log scans and the broader database model be revisited.

## First Acceptance Checks

- Historical readings shown for the pilot sensor match archived JSONL samples, with no duplicate points after re-import.
- A failed sensor read creates a visible gap rather than a false zero or a line across missing data.
- The existing device summary, commands, services table, and health snapshot still work if history import or chart queries fail.
- The History view remains usable while new readings arrive, without the overview page's full reload interrupting chart interaction.
- A database backup can be restored; history still covered by retained JSONL can be rebuilt from that archive.

Retention periods, scheduling, and rotation still need validation. No Home Assistant, Grafana, or separate charting stack is planned for this first slice.
