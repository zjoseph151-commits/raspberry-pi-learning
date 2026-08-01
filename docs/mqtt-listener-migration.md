# MQTT Listener Migration Note

This stage starts the move from the learning-project layout to a cleaner home IoT platform layout while preserving the currently working MQTT listener behavior.

## Scope

Only the MQTT listener is copied into the new service layout during this stage.

Old live listener path:

```text
/home/zack/projects/raspberry-pi/mqtt_listener/listener.py
```

New listener path:

```text
/home/zack/projects/raspberry-pi/services/mqtt-listener/listener.py
```

The original listener file is intentionally retained for rollback until the migrated service has been verified.

## Runtime Behavior Preserved

The migrated listener preserves:

- Broker host: `localhost`
- Broker port: `1883`
- Subscription filter: `home/#`
- Plain text log output: `logs/mqtt_messages.log`
- JSON Lines output for valid JSON: `logs/mqtt_messages.jsonl`
- CSV output for valid JSON: `logs/mqtt_messages.csv`
- UTF-8 replacement behavior for invalid bytes
- Malformed JSON handling
- Console/journal output
- Paho MQTT reconnect behavior

## Working Directory

The systemd service must continue using:

```ini
WorkingDirectory=/home/zack/projects/raspberry-pi
```

The listener uses repository-relative runtime paths such as `logs/mqtt_messages.log`. Keeping the working directory at the repository root ensures runtime data continues to be written under:

```text
/home/zack/projects/raspberry-pi/logs/
```

Runtime data is not moved to `data/` in this stage.

## Updated systemd ExecStart

The repository-owned reference unit is:

```text
systemd/mqtt-listener.service
```

It updates only the script path:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/services/mqtt-listener/listener.py
```

## Manual Deployment

Review the repository-owned unit first, then deploy it manually on the Raspberry Pi:

```bash
cd /home/zack/projects/raspberry-pi

sudo cp systemd/mqtt-listener.service \
  /etc/systemd/system/mqtt-listener.service

sudo systemctl daemon-reload
sudo systemctl restart mqtt-listener.service
sudo systemctl status mqtt-listener.service --no-pager
```

Journal verification:

```bash
journalctl -u mqtt-listener.service -n 50 --no-pager
journalctl -u mqtt-listener.service -f
```

## Functional Verification

1. Confirm the service is active:

   ```bash
   systemctl status mqtt-listener.service --no-pager
   ```

2. Confirm `ExecStart` points to the migrated listener:

   ```bash
   systemctl show mqtt-listener.service -p ExecStart -p WorkingDirectory --no-pager
   ```

3. Publish a valid JSON MQTT message:

   ```bash
   mosquitto_pub -h localhost \
     -t 'home/devices/migration-test/status' \
     -m '{"device":"migration-test","type":"status","count":1,"uptime_ms":1000,"wifi_rssi":-50}'
   ```

4. Confirm the JSON message appears in:

   ```bash
   journalctl -u mqtt-listener.service -n 50 --no-pager
   tail -n 5 logs/mqtt_messages.log
   tail -n 5 logs/mqtt_messages.jsonl
   tail -n 5 logs/mqtt_messages.csv
   ```

5. Publish a plain-text availability-style message:

   ```bash
   mosquitto_pub -h localhost \
     -t 'home/devices/migration-test/availability' \
     -m 'online'
   ```

6. Confirm the plain-text message appears in the text log and does not crash the service:

   ```bash
   tail -n 5 logs/mqtt_messages.log
   systemctl status mqtt-listener.service --no-pager
   ```

7. Confirm health monitor and dashboard services remain unchanged and active:

   ```bash
   systemctl status HEALTH_MONITOR_UNIT_NAME --no-pager
   systemctl status DASHBOARD_UNIT_NAME --no-pager
   ```

Replace the placeholder unit names with the actual service names on the Raspberry Pi.

## Rollback

If the migrated service fails, restore the prior `ExecStart` path:

```bash
sudo cp /etc/systemd/system/mqtt-listener.service \
  /etc/systemd/system/mqtt-listener.service.migration-failed
```

Then edit `/etc/systemd/system/mqtt-listener.service` so `ExecStart` is:

```ini
ExecStart=/home/zack/projects/raspberry-pi/.venv/bin/python /home/zack/projects/raspberry-pi/mqtt_listener/listener.py
```

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart mqtt-listener.service
sudo systemctl status mqtt-listener.service --no-pager
```

Alternative rollback if you saved the previous unit file before deployment:

```bash
sudo cp /path/to/saved/mqtt-listener.service \
  /etc/systemd/system/mqtt-listener.service
sudo systemctl daemon-reload
sudo systemctl restart mqtt-listener.service
sudo systemctl status mqtt-listener.service --no-pager
```

Do not delete the original `mqtt_listener/listener.py` until the migrated service has been verified.
