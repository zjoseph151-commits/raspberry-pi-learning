# Legacy Entrypoint Retirement

This stage retires the old root-level implementations without deleting the old paths. Each legacy entrypoint is now a thin compatibility wrapper that delegates to the service-owned implementation.

## Wrappers

| Legacy path | Delegates to |
| --- | --- |
| `mqtt_listener/listener.py` | `services/mqtt-listener/listener.py` |
| `health_monitor.py` | `services/health-monitor/health_monitor.py` |
| `device_status.py` | `services/health-monitor/device_status.py` |
| `dashboard_server.py` | `services/dashboard/dashboard_server.py` |

## What This Preserves

- Old manual commands still work.
- Old imports still expose the same main constants and functions.
- Runtime paths follow the service-owned implementations, currently under repository-root `data/`.
- systemd units continue using the already-migrated `services/` paths.
- Runtime data location is controlled by the service-owned implementations.

## Current Direction

New development should use the service-owned paths directly. The wrappers are temporary compatibility shims, not the preferred implementation location.

## Verification

Run the local wrapper and platform tests:

```bash
python -m unittest \
  tests.test_legacy_entrypoints \
  tests.test_mqtt_listener \
  tests.test_device_status \
  tests.test_health_monitor \
  tests.test_dashboard_server -v
```

On the Raspberry Pi, confirm the live services still point directly into `services/`:

```bash
systemctl show mqtt-listener.service \
  -p ExecStart -p WorkingDirectory --no-pager
systemctl show health-monitor.service \
  -p ExecStart -p WorkingDirectory --no-pager
systemctl show iot-dashboard.service \
  -p ExecStart -p WorkingDirectory --no-pager
```

Optional compatibility checks:

```bash
/home/zack/projects/raspberry-pi/.venv/bin/python device_status.py
/home/zack/projects/raspberry-pi/.venv/bin/python health_monitor.py
```

Do not run the legacy dashboard or MQTT listener wrappers while the systemd services are already running, because those are long-running processes and may contend for the same port or duplicate MQTT logging.

## Rollback

If a wrapper causes a problem, restore the previous root-level implementation for that path from Git history or from the backup made before this stage. The live systemd services should not need rollback because they already point at the service-owned files.

Do not remove the wrappers until the old paths have been unused through normal reboots and timer cycles.
