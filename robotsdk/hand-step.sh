#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for arg in "$@"; do
  if [[ "$arg" = --help || "$arg" = -h ]]; then exec python3 "$root/hand_step.py" --help; fi
done
# Argument validation happens before starting a container or configuring CAN.
iface=$(python3 -c 'import sys; sys.path.insert(0,sys.argv.pop(1)); from hand_step import arguments; print({"left":"can1","right":"can3"}[arguments().hand])' "$root" "$@")
exec 8>"$root/.hand-step.lock"
flock -n 8 || { echo 'Another hand-step session is running.' >&2; exit 1; }
if pgrep -fa 'anyverse_robot_driver|hand_demo|hand_monitor|revo[12]_can|stark.*ctrl' | grep -vE 'pgrep|hand-step.sh'; then
  echo 'A possible hardware driver is running; stop it explicitly before using this script.' >&2
  exit 1
fi
"$root/start-container.sh" >/dev/null
setup=0
cleanup() { if [ "$setup" = 1 ]; then sudo -n ip link set "$iface" down; fi; }
trap cleanup EXIT
up=$(ip -j link show "$iface" | python3 -c 'import json,sys; print("UP" in json.load(sys.stdin)[0]["flags"])')
if [ "$up" = False ]; then
  sudo -n ip link set "$iface" type can bitrate 1000000 fd off restart-ms 0
  sudo -n ip link set "$iface" up
  setup=1
else
  ip -details -json link show "$iface" | python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; c=d["linkinfo"]["info_data"]; assert d["mtu"]==16 and c["bittiming"]["bitrate"]==1000000 and c["state"]=="ERROR-ACTIVE", "CAN settings/state mismatch"'
fi
docker exec -i robotsdk python3 /workspace/hand_step.py "$@"
