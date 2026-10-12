#!/bin/bash
set -euo pipefail
docker inspect -f 'container={{.Name}} running={{.State.Running}} image={{.Config.Image}}' robotsdk
docker exec robotsdk bash -c 'source /workspace/env.sh; timeout 8 ros2 lifecycle get /robotsdk/anyverse_robot_driver; ros2 topic list --no-daemon'
