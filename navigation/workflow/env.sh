#!/usr/bin/env bash
# Source this file in each container terminal. No services are started.
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///opt/ros/jazzy/share/e_slam_bringup/config/cyclonedds_chassis.xml
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NAVMAP_TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
navmap() { /usr/bin/python3 "$NAVMAP_TOOLS/navmap.py" "$@"; }
