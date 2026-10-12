#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PYTHONUNBUFFERED=1
exec /home/nvidia/robot_wakeup/.venv/bin/python ./hello_test.py "$@"
