#!/bin/bash
set -euo pipefail
if docker inspect robotsdk >/dev/null 2>&1; then
    exec /home/nvidia/robotsdk/start-container.sh
fi
docker run -d --name robotsdk --hostname robotsdk-042 --network host \
    --privileged --ulimit rtprio=95 --ulimit memlock=-1:-1 \
    --restart=no --init -v /dev:/dev \
    -v /home/nvidia/robotsdk:/workspace \
    -v /home/nvidia/robotsdk/config/robot.yaml:/etc/anyverse-robot/robot.yaml:ro \
    -e ROS_DOMAIN_ID=142 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI=file:///workspace/config/cyclonedds.xml \
    -e ROS_LOCALHOST_ONLY=1 -e ROS_LOG_DIR=/workspace/logs/ros \
    --entrypoint /bin/bash anyverse-robotsdk:0.33.0-kitt15-042 \
    -c 'exec sleep infinity'
