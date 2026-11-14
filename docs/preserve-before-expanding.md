# Preserve Before Expanding: Live Pi Verification

Run these checks on the Raspberry Pi after deploying the current repository. Do not mark the live items in `TODO.md` complete based only on the reference files in `systemd/`.

## Deployed Documentation

From `/home/zack/projects/raspberry-pi`:

```bash
git rev-parse HEAD
git status --short -- README.md TODO.md docs
```

Compare the commit with the current local checkout. A matching commit and no documentation changes in `git status` confirm the tracked docs match. If the commits differ, compare or deploy the documentation before checking this item off.

## Active Unit Configuration

```bash
for unit in mqtt-listener.service health-monitor.service iot-dashboard.service; do
  systemctl show "$unit" -p FragmentPath -p ExecStart -p WorkingDirectory --no-pager
  systemctl cat "$unit" --no-pager
done
systemctl show health-monitor.timer -p FragmentPath -p Unit --no-pager
```

Confirm the effective `ExecStart` paths target `services/mqtt-listener/listener.py`, `services/health-monitor/health_monitor.py`, and `services/dashboard/dashboard_server.py`. Confirm each service has `WorkingDirectory=/home/zack/projects/raspberry-pi`. Inspect `systemctl cat` for overrides that could change the reference units.

## Reboot Behavior

Before rebooting, record the current state:

```bash
systemctl is-enabled mqtt-listener.service health-monitor.timer iot-dashboard.service
systemctl is-active mqtt-listener.service health-monitor.timer iot-dashboard.service
```

Reboot only during a suitable maintenance window. After the Pi is back and at least 90 seconds have elapsed, run:

```bash
systemctl is-active mqtt-listener.service health-monitor.timer iot-dashboard.service
systemctl list-timers health-monitor.timer --no-pager
systemctl status health-monitor.service --no-pager
journalctl -b -u mqtt-listener.service -u health-monitor.service -u iot-dashboard.service --no-pager -n 80
stat data/status/device_status.json
```

The listener, timer, and dashboard should be active. The oneshot `health-monitor.service` may be inactive between timer runs; its recent successful run and a refreshed status JSON are the important checks. Only then mark the reboot item complete.

## Runtime Data In Git

Repository-side verification completed: `.gitignore` ignores runtime files in `data/logs/` and `data/status/`, while `git ls-files data` lists only `data/logs/.gitkeep` and `data/status/.gitkeep`. On the Pi, also run `git status --short --ignored -- data` and confirm runtime files are ignored rather than staged or tracked.
