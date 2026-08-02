# Health Monitor Migration Note

This stage continues the move from the learning-project layout to the cleaner home IoT platform layout while preserving the currently working health monitor behavior.

## Scope

Only the health monitor service script is copied into the new service layout during this stage.

Old live health monitor path:

```text
/home/zack/projects/raspberry-pi/health_monitor.py
```

New health monitor path:

```text
/home/zack/projects/raspberry-pi/services/health-monitor/health_monitor.py
```

The original root-level `health_monitor.py` file is intentionally retained for rollback until the migrated timer/service has been verified on the Raspberry Pi.

## Runtime Behavior Preserved

The migrated health monitor preserves:

- CSV input path: `logs/mqtt_messages.csv`
- JSON status output path: `logs/device_status.json`
- Console/journal JSON report output
- Missing CSV handling
- Empty CSV handling
- Existing latest-message-per-device status calculation
- Existing ONLINE threshold of 30 seconds
- Existing dependency on the root-level `device_status.py` helper at the time of this migration stage
- Existing timer schedule: 30 seconds after boot, then 60 seconds after each run

Follow-up note: a later migration copies `device_status.py` into `services/health-monitor/` so the health monitor service can become self-contained while preserving the same runtime paths and behavior.

## Working Directory

The systemd service must continue using:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

The health monitor uses repository-relative runtime paths. Keeping the working directory at the repository root ensures it continues to read and write:

```text
/home/zack/projects/raspberry-pi/logs/mqtt_messages.csv
/home/zack/projects/raspberry-pi/logs/device_status.json
```

Runtime data is not moved to `data/` in this stage.

## Updated systemd ExecStart

The repository-owned reference units are:

```text
systemd/health-monitor.service
systemd/health-monitor.timer
```

The service updates only the script path:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/services/health-monitor/health_monitor.py
```

## Import Compatibility

The migrated script adds the repository root to `sys.path` before importing `device_status.py`. This is the minimum compatibility adjustment needed because systemd runs the script by absolute path from inside `services/health-monitor/` while the shared helper still lives at the repository root.

Follow-up note: after the device-status helper migration, the script instead prefers the helper copied beside it in `services/health-monitor/`.

## Manual Deployment

Review the repository-owned units first, then deploy them manually on the Raspberry Pi:

```bash
cd /home/zack/projects/raspberry-pi

sudo cp /etc/systemd/system/health-monitor.service \
  /etc/systemd/system/health-monitor.service.before-migration
sudo cp /etc/systemd/system/health-monitor.timer \
  /etc/systemd/system/health-monitor.timer.before-migration

sudo cp systemd/health-monitor.service \
  /etc/systemd/system/health-monitor.service
sudo cp systemd/health-monitor.timer \
  /etc/systemd/system/health-monitor.timer

sudo systemctl daemon-reload
sudo systemctl restart health-monitor.timer
sudo systemctl start health-monitor.service
sudo systemctl status health-monitor.service --no-pager
sudo systemctl status health-monitor.timer --no-pager
```

Journal verification:

```bash
journalctl -u health-monitor.service -n 50 --no-pager
journalctl -u health-monitor.timer -n 50 --no-pager
```

Live monitoring:

```bash
journalctl -u health-monitor.service -f
```

## Functional Verification

1. Confirm the timer is active:

   ```bash
   systemctl status health-monitor.timer --no-pager
   ```

2. Confirm `ExecStart` points to the migrated health monitor and the working directory remains the repository root:

   ```bash
   systemctl show health-monitor.service \
     -p ExecStart -p WorkingDirectory -p User -p Type --no-pager
   ```

3. Trigger one health monitor run manually:

   ```bash
   sudo systemctl start health-monitor.service
   ```

4. Confirm the service exits successfully:

   ```bash
   systemctl status health-monitor.service --no-pager
   journalctl -u health-monitor.service -n 50 --no-pager
   ```

5. Confirm the status file is still written under the existing runtime logs directory:

   ```bash
   ls -l logs/device_status.json
   cat logs/device_status.json
   ```

6. Confirm the timer schedule remains present:

   ```bash
   systemctl list-timers --all | grep health-monitor
   ```

7. Confirm MQTT listener and dashboard behavior remain unchanged.

## Rollback

If the migrated health monitor fails, restore the saved unit files:

```bash
sudo cp /etc/systemd/system/health-monitor.service.before-migration \
  /etc/systemd/system/health-monitor.service
sudo cp /etc/systemd/system/health-monitor.timer.before-migration \
  /etc/systemd/system/health-monitor.timer

sudo systemctl daemon-reload
sudo systemctl restart health-monitor.timer
sudo systemctl start health-monitor.service
sudo systemctl status health-monitor.service --no-pager
sudo systemctl status health-monitor.timer --no-pager
```

If a backup was not created, restore the prior service `ExecStart` path:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/health_monitor.py
```

Then reload and restart the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl restart health-monitor.timer
sudo systemctl start health-monitor.service
sudo systemctl status health-monitor.service --no-pager
```

Do not delete the original `health_monitor.py` until the migrated timer/service has been verified.
