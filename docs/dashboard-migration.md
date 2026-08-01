# Dashboard Migration Note

This stage continues the move from the learning-project layout to the cleaner home IoT platform layout while preserving the currently working dashboard behavior.

## Scope

Only the dashboard service script is copied into the new service layout during this stage.

Old live dashboard path:

```text
/home/zack/projects/raspberry-pi/dashboard_server.py
```

New dashboard path:

```text
/home/zack/projects/raspberry-pi/services/dashboard/dashboard_server.py
```

The original root-level `dashboard_server.py` file is intentionally retained for rollback until the migrated service has been verified on the Raspberry Pi.

## Runtime Behavior Preserved

The migrated dashboard preserves:

- Service name: `iot-dashboard.service`
- HTTP host binding: `0.0.0.0`
- HTTP port: `8080`
- Local access URL: `http://localhost:8080`
- Status input path: `logs/device_status.json`
- Auto-refresh interval: 10 seconds
- Existing HTML output and ONLINE/OFFLINE labels
- Existing missing or invalid status-file handling
- Existing request logging behavior
- Existing restart behavior: `Restart=always`, `RestartSec=5`

## Working Directory

The systemd service must continue using:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

The dashboard reads repository-relative runtime data. Keeping the working directory at the repository root ensures it continues to read:

```text
/home/zack/projects/raspberry-pi/logs/device_status.json
```

Runtime data is not moved to `data/` in this stage.

## Updated systemd ExecStart

The repository-owned reference unit is:

```text
systemd/iot-dashboard.service
```

The service updates only the script path:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/services/dashboard/dashboard_server.py
```

The service still starts after:

```ini
After=network-online.target health-monitor.service
Wants=network-online.target
```

## Manual Deployment

Review the repository-owned unit first, then deploy it manually on the Raspberry Pi:

```bash
cd /home/zack/projects/raspberry-pi

sudo cp /etc/systemd/system/iot-dashboard.service \
  /etc/systemd/system/iot-dashboard.service.before-migration

sudo cp systemd/iot-dashboard.service \
  /etc/systemd/system/iot-dashboard.service

sudo systemctl daemon-reload
sudo systemctl restart iot-dashboard.service
sudo systemctl status iot-dashboard.service --no-pager
```

Journal verification:

```bash
journalctl -u iot-dashboard.service -n 50 --no-pager
```

Live monitoring:

```bash
journalctl -u iot-dashboard.service -f
```

## Functional Verification

1. Confirm the service is active:

   ```bash
   systemctl status iot-dashboard.service --no-pager
   ```

2. Confirm `ExecStart` points to the migrated dashboard and the working directory remains the repository root:

   ```bash
   systemctl show iot-dashboard.service \
     -p ExecStart -p WorkingDirectory -p User -p Restart -p RestartSec --no-pager
   ```

3. Confirm the dashboard is listening on port 8080:

   ```bash
   ss -ltnp | grep ':8080'
   ```

4. Open the dashboard locally:

   ```text
   http://localhost:8080
   ```

5. Confirm the page shows `Pi IoT Dashboard`, the latest `generated_at` timestamp, and any known devices.

6. Confirm the dashboard still reads the existing status file:

   ```bash
   ls -l logs/device_status.json
   ```

7. Confirm MQTT listener and health monitor behavior remain unchanged:

   ```bash
   systemctl status mqtt-listener.service --no-pager
   systemctl status health-monitor.timer --no-pager
   systemctl status health-monitor.service --no-pager
   ```

## Rollback

If the migrated dashboard fails, restore the saved unit file:

```bash
sudo cp /etc/systemd/system/iot-dashboard.service.before-migration \
  /etc/systemd/system/iot-dashboard.service

sudo systemctl daemon-reload
sudo systemctl restart iot-dashboard.service
sudo systemctl status iot-dashboard.service --no-pager
```

If a backup was not created, restore the prior service `ExecStart` path:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/dashboard_server.py
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart iot-dashboard.service
sudo systemctl status iot-dashboard.service --no-pager
```

Do not delete the original `dashboard_server.py` until the migrated service has been verified.
