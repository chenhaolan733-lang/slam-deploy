#!/bin/bash
source /opt/anyverse-robot/ros2/setup.bash
export ROS_DOMAIN_ID=142
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///workspace/config/cyclonedds.xml
export ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR=/workspace/logs/ros
export RCUTILS_LOGGING_BUFFERED_STREAM=1
