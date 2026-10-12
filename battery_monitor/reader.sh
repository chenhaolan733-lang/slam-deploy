#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
source /home/sunrise/robot/bin/interface/install/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=/etc/ros/cyclonedds/cyclonedds.xml
export ROS_LOCALHOST_ONLY=0
exec /usr/bin/python3 -u /home/sunrise/battery_monitor/battery_reader.py
