#!/bin/bash
set -eo pipefail
case "${1:---inspect}" in
    --enable) autostart=true; echo 'WARNING: activating 20 arm/waist/head joints; support the robot and keep clear.';;
    --inspect) autostart=false; echo 'Inspection mode: driver starts UNCONFIGURED, no activation or enable.';;
    *) echo 'Usage: start-driver.sh [--inspect|--enable]' >&2; exit 2;;
esac
source /workspace/env.sh
exec 9>/tmp/robotsdk-driver.lock
flock -n 9 || { echo 'robotsdk driver already running' >&2; exit 1; }
exec ros2 launch anyverse_robot_bringup bringup.launch.py \
    robot_yaml:=/etc/anyverse-robot/robot.yaml namespace:=robotsdk \
    control_mode:=topics publish_robot_state:=false start_cameras:=false \
    required_roles:=left_arm,right_arm,waist,head autostart:="$autostart" \
    dds_profile:=/workspace/config/cyclonedds.xml
