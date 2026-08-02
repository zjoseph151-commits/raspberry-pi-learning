# Device Status Helper Migration Note

This stage makes the migrated health monitor self-contained by copying its `device_status.py` helper into the health-monitor service directory.

## Scope

Only the health/status helper used by the health monitor is copied during this stage.

Old helper path:

```text
/home/zack/projects/raspberry-pi/device_status.py
```

New helper path:

```text
/home/zack/projects/raspberry-pi/services/health-monitor/device_status.py
```

The original root-level `device_status.py` file is intentionally retained for rollback and future compatibility checks.

## Runtime Behavior Preserved

The migrated helper preserves:

- CSV input path: `logs/mqtt_messages.csv`
- CSV schema:
  - `received_at`
  - `topic`
  - `device`
  - `type`
  - `count`
  - `uptime_ms`
  - `wifi_rssi`
- ONLINE threshold: 30 seconds
- Latest-message-per-device grouping
- Blank handling for missing CSV fields
- Missing CSV handling
- Empty CSV handling
- Standard-library-only implementation

## Working Directory

No systemd working directory change is required.

The health monitor service should continue using:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

This keeps the helper reading:

```text
/home/zack/projects/raspberry-pi/logs/mqtt_messages.csv
```

Runtime data is not moved to `data/` in this stage.

## systemd Impact

No systemd unit change is required for this stage.

The live `health-monitor.service` should already run:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/services/health-monitor/health_monitor.py
```

The migrated `health_monitor.py` now prefers the service-local helper:

```text
/home/zack/projects/raspberry-pi/services/health-monitor/device_status.py
```

## Manual Deployment

Before replacing the deployed health monitor files, save the current migrated health monitor script:

```bash
cd /home/zack/projects/raspberry-pi

cp services/health-monitor/health_monitor.py \
  services/health-monitor/health_monitor.py.before-device-status-migration
```

After placing the updated files on the Raspberry Pi, run:

```bash
cd /home/zack/projects/raspberry-pi

/home/zack/projects/raspberry-pi/.venv/bin/python \
  -m py_compile \
  services/health-monitor/health_monitor.py \
  services/health-monitor/device_status.py

sudo systemctl start health-monitor.service
sudo systemctl status health-monitor.service --no-pager
journalctl -u health-monitor.service -n 50 --no-pager
```

No `systemctl daemon-reload` is needed because the unit file does not change.

## Functional Verification

1. Confirm the health monitor service exits successfully:

   ```bash
   sudo systemctl start health-monitor.service
   systemctl status health-monitor.service --no-pager
   ```

2. Confirm the status JSON is still written in the existing runtime location:

   ```bash
   ls -l logs/device_status.json
   cat logs/device_status.json
   ```

3. Confirm the timer remains active:

   ```bash
   systemctl status health-monitor.timer --no-pager
   ```

4. Confirm the dashboard still reads and displays the latest status:

   ```text
   http://localhost:8080
   ```

5. Confirm MQTT listener behavior remains unchanged:

   ```bash
   systemctl status mqtt-listener.service --no-pager
   ```

## Rollback

If the migrated helper causes a problem, restore the previous migrated health monitor script backup:

```bash
cp services/health-monitor/health_monitor.py.before-device-status-migration \
  services/health-monitor/health_monitor.py

sudo systemctl start health-monitor.service
sudo systemctl status health-monitor.service --no-pager
journalctl -u health-monitor.service -n 50 --no-pager
```

If no backup was created, restore the previous import bridge in `services/health-monitor/health_monitor.py` so it inserts the repository root into `sys.path` before importing `device_status.py`.

Do not delete the original root-level `device_status.py` until this migration has been verified over several timer runs.
