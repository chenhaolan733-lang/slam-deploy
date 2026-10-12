#!/bin/bash
# Run on chassis as sunrise, with this directory containing the reader and public key.
set -euo pipefail
stage="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
test "$(id -un)" = sunrise
test -r /home/sunrise/robot/bin/interface/install/setup.bash
install -d -m 755 /home/sunrise/battery_monitor
if [ -f /home/sunrise/battery_monitor/battery_reader.py ]; then
  backup=$(mktemp -d /home/sunrise/battery_monitor/backup_XXXXXX)
  cp -a /home/sunrise/battery_monitor/battery_reader.py /home/sunrise/battery_monitor/reader.sh "$backup/"
fi
install -m 644 "$stage/battery_reader.py" /home/sunrise/battery_monitor/battery_reader.py
install -m 755 "$stage/reader.sh" /home/sunrise/battery_monitor/reader.sh
install -d -m 700 /home/sunrise/.ssh
# Structured, idempotent authorized_keys update; preserves all unrelated entries.
python3 - "$stage/id_ed25519.pub" <<'PY'
from pathlib import Path
import sys, os, shutil, time
pub = Path(sys.argv[1]).read_text().strip()
assert pub.startswith('ssh-ed25519 ') and len(pub.splitlines()) == 1
key = pub.split()[1]
target = Path('/home/sunrise/.ssh/authorized_keys')
old = target.read_text() if target.exists() else ''
if target.exists():
    shutil.copy2(target, target.with_name('authorized_keys.battery-backup-' + str(time.time_ns())))
lines = [line for line in old.splitlines() if key not in line.split()]
options = 'from="192.0.2.100",restrict,command="/home/sunrise/battery_monitor/reader.sh"'
lines.append(options + ' ' + pub)
tmp = target.with_name('authorized_keys.battery-next')
tmp.write_text('\n'.join(lines) + '\n')
tmp.chmod(0o600)
os.replace(tmp, target)
print('Installed restricted read-only battery key; existing keys preserved.')
PY
