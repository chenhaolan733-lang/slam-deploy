#!/bin/bash
set -euo pipefail
echo 'Stopping the driver disables its motors. Ensure waist/arms are safely supported.'
exec docker exec robotsdk python3 /workspace/stop-driver.py
