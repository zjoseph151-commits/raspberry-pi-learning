# Runtime Data Migration

This stage moves active runtime paths from the old repository-root `logs/` directory into the permanent `data/` layout.

## New Runtime Paths

| Purpose | Old path | New path |
| --- | --- | --- |
| Plain MQTT log | `logs/mqtt_messages.log` | `data/logs/mqtt_messages.log` |
| JSON Lines MQTT log | `logs/mqtt_messages.jsonl` | `data/logs/mqtt_messages.jsonl` |
| CSV MQTT log | `logs/mqtt_messages.csv` | `data/logs/mqtt_messages.csv` |
| Latest device status | `logs/device_status.json` | `data/status/device_status.json` |

The systemd `WorkingDirectory` remains:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

No systemd unit change is required for this stage because all runtime paths remain repository-relative.

## Code Paths Updated

| Component | Path constant |
| --- | --- |
| `services/mqtt-listener/listener.py` | `data/logs/mqtt_messages.*` |
| `services/health-monitor/device_status.py` | `data/logs/mqtt_messages.csv` |
| `services/health-monitor/health_monitor.py` | `data/status/device_status.json` |
| `services/dashboard/dashboard_server.py` | `data/status/device_status.json` |

Legacy wrappers inherit these paths through the service-owned implementations.

## Manual Deployment

Stop the running services before copying existing runtime files so the listener does not write to the old path while files are being migrated:

```bash
cd /home/zack/projects/raspberry-pi

sudo systemctl stop iot-dashboard.service
sudo systemctl stop health-monitor.timer
sudo systemctl stop health-monitor.service
sudo systemctl stop mqtt-listener.service
```

Back up existing runtime files and copy them into the new layout:

```bash
mkdir -p data/logs data/status runtime-backups

cp -a logs runtime-backups/logs-before-data-migration-$(date +%Y%m%d-%H%M%S) \
  2>/dev/null || true

cp -a logs/mqtt_messages.log data/logs/mqtt_messages.log 2>/dev/null || true
cp -a logs/mqtt_messages.jsonl data/logs/mqtt_messages.jsonl 2>/dev/null || true
cp -a logs/mqtt_messages.csv data/logs/mqtt_messages.csv 2>/dev/null || true
cp -a logs/device_status.json data/status/device_status.json 2>/dev/null || true
```

After placing the updated source files on the Raspberry Pi, compile the changed Python files:

```bash
/home/zack/projects/raspberry-pi/.venv/bin/python \
  -m py_compile \
  services/mqtt-listener/listener.py \
  services/health-monitor/device_status.py \
  services/health-monitor/health_monitor.py \
  services/dashboard/dashboard_server.py \
  device_status.py \
  health_monitor.py \
  dashboard_server.py \
  mqtt_listener/listener.py
```

Start the services again:

```bash
sudo systemctl start mqtt-listener.service
sudo systemctl start health-monitor.timer
sudo systemctl start health-monitor.service
sudo systemctl start iot-dashboard.service
```

## Verification

Confirm services are running:

```bash
systemctl status mqtt-listener.service --no-pager
systemctl status health-monitor.timer --no-pager
systemctl status health-monitor.service --no-pager
systemctl status iot-dashboard.service --no-pager
```

Confirm new files are being used:

```bash
ls -l data/logs/mqtt_messages.log
ls -l data/logs/mqtt_messages.jsonl
ls -l data/logs/mqtt_messages.csv
ls -l data/status/device_status.json
```

Publish a test message:

```bash
mosquitto_pub -h localhost \
  -t 'home/devices/data-migration-test/status' \
  -m '{"device":"data-migration-test","type":"status","count":1,"uptime_ms":1000,"wifi_rssi":-50}'
```

Check the new logs:

```bash
tail -n 5 data/logs/mqtt_messages.log
tail -n 5 data/logs/mqtt_messages.jsonl
tail -n 5 data/logs/mqtt_messages.csv
```

Run the health monitor once and check the dashboard input:

```bash
sudo systemctl start health-monitor.service
cat data/status/device_status.json
```

Open the dashboard:

```text
http://localhost:8080
```

## Rollback

If the data-path migration fails, stop the services:

```bash
sudo systemctl stop iot-dashboard.service
sudo systemctl stop health-monitor.timer
sudo systemctl stop health-monitor.service
sudo systemctl stop mqtt-listener.service
```

Restore the previous source files from Git or from your pre-migration backup, then copy data back to the old `logs/` layout if needed:

```bash
mkdir -p logs
cp -a data/logs/mqtt_messages.log logs/mqtt_messages.log 2>/dev/null || true
cp -a data/logs/mqtt_messages.jsonl logs/mqtt_messages.jsonl 2>/dev/null || true
cp -a data/logs/mqtt_messages.csv logs/mqtt_messages.csv 2>/dev/null || true
cp -a data/status/device_status.json logs/device_status.json 2>/dev/null || true
```

Start services again:

```bash
sudo systemctl start mqtt-listener.service
sudo systemctl start health-monitor.timer
sudo systemctl start health-monitor.service
sudo systemctl start iot-dashboard.service
```

Do not delete the old `logs/` directory until the `data/` layout has been verified through normal listener traffic, health-monitor timer runs, dashboard refreshes, and at least one reboot.
