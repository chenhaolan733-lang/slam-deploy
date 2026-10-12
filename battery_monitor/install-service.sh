#!/bin/bash
# Run as nvidia after installing the restricted reader/key and cached audio.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
test "$root" = /home/nvidia/robot_battery_monitor || { echo 'Install files at /home/nvidia/robot_battery_monitor first.' >&2; exit 1; }
test "$(id -un)" = nvidia
test -s "$root/keys/id_ed25519"
test -s "$root/keys/known_hosts"
python3 -c 'import sys;sys.path.insert(0,"/home/nvidia/robot_say");import say;say.check_wav("/home/nvidia/robot_battery_monitor/low_battery.wav")'
chmod 755 "$root/battery.sh"
sudo systemd-analyze verify "$root/robot-battery-monitor.service"
if [ -f /etc/systemd/system/robot-battery-monitor.service ]; then
  backup=$(mktemp -d "$root/backup_service_XXXXXX")
  cp /etc/systemd/system/robot-battery-monitor.service "$backup/"
fi
sudo install -m 644 "$root/robot-battery-monitor.service" /etc/systemd/system/robot-battery-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable robot-battery-monitor
sudo systemctl restart robot-battery-monitor
systemctl status robot-battery-monitor --no-pager
