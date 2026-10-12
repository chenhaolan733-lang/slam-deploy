#!/bin/bash
# Run INSIDE the inference container as root; fixed-scope helper only.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root inside the inference container.' >&2; exit 1; }
base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
test -f /opt/ros/jazzy/share/e_slam_bringup/sites/e_42.yaml
visudo -cf "$base/navmap-e42.sudoers"
if [ -e /usr/local/sbin/navmap-activate-e42 ] || [ -e /etc/sudoers.d/navmap-e42 ]; then
  backup=$(mktemp -d /var/backups/navmap-helper-XXXXXX)
  if [ -e /usr/local/sbin/navmap-activate-e42 ]; then cp -a /usr/local/sbin/navmap-activate-e42 "$backup/"; fi
  if [ -e /etc/sudoers.d/navmap-e42 ]; then cp -a /etc/sudoers.d/navmap-e42 "$backup/"; fi
  printf 'Helper backup: %s\n' "$backup"
fi
install -o root -g root -m 755 "$base/navmap_activate_e42.py" /usr/local/sbin/navmap-activate-e42
install -o root -g root -m 440 "$base/navmap-e42.sudoers" /etc/sudoers.d/navmap-e42
visudo -cf /etc/sudoers.d/navmap-e42
/usr/local/sbin/navmap-activate-e42 --check
