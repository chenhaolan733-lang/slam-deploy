#!/bin/bash
set -euo pipefail
if ps -eo comm=,args= | grep -E '^(anyverse_robot_|anyverse-robot |ros2_control_no|ethercat_main|marvin_driver|eyou_driver)' | grep -v grep; then
    echo '检测到关节驱动/SDK 占用。请先安全处理已有驱动，脚本不会自动停止它。' >&2
    exit 1
fi
/home/nvidia/robotsdk/start-container.sh >/dev/null
if [[ -t 0 && -t 1 ]]; then
    exec docker exec -it robotsdk python3 /workspace/arm_step.py "$@"
else
    exec docker exec -i robotsdk python3 /workspace/arm_step.py "$@"
fi
