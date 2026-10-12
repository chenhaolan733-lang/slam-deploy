#!/bin/bash
set -euo pipefail
# Reject competing SDK/legacy joint owners, including those outside this container.
if ps -eo comm=,args= | grep -E '^(anyverse_robot_|ros2_control_no|ethercat_main|marvin_driver|eyou_driver)' | grep -v grep; then
    echo 'A joint driver may already own the hardware. Stop its owning stack first; nothing was started.' >&2
    exit 1
fi
/home/nvidia/robotsdk/start-container.sh
if [[ -t 0 && -t 1 ]]; then
    exec docker exec -it robotsdk /workspace/run-driver.sh "${@}"
else
    exec docker exec -i robotsdk /workspace/run-driver.sh "${@}"
fi
