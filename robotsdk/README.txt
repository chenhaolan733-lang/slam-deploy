KITT15-042 Robot SDK container (2026-10-11)

Container: robotsdk
Image: anyverse-robotsdk:0.33.0-kitt15-042
Base image is not distributed. Supply an approved compatible image using --build-arg BASE_IMAGE=... .
SDK / ROS adapter: 0.33.0. ROS control core 4.45.2, controllers 4.40.1.
ROS packages use the signed 2026-06-18 Jazzy snapshot, not the latest package set.

PUBLIC COPY: real robot.yaml is omitted; robot.example.yaml is deliberately non-operational.
Obtain the real, approved config locally before building. Do not guess stiffness/damping/calibration.
Historical deployment used left_arm (7), right_arm (7), waist (4), head (2).
No cameras, hands/grippers, chassis or navigation integration.
Host SDK and /etc/anyverse-robot/robot.yaml are preserved.

1. Enter the container; this does not start or enable motors:
   /home/nvidia/robotsdk/shell.sh

2. Start the driver in a separate robot terminal:
   /home/nvidia/robotsdk/start-driver.sh --enable
   WARNING: this configures AND activates the four groups (motor enable).
   Ensure robot/arms/waist are supported and people are clear first.
   Do not run host or production joint drivers at the same time.
   Do not start production-up just to use this SDK.
   Keep this terminal open. Ctrl+C shuts down and disables the driver.

3. Stop gracefully from another terminal:
   /home/nvidia/robotsdk/stop-driver.sh
   WARNING: motor disable can release support; secure waist/arms first.

4. Inspection without activation:
   /home/nvidia/robotsdk/start-driver.sh --inspect
   This starts an unconfigured lifecycle node. Inside the container:
   ros2 lifecycle set /robotsdk/anyverse_robot_driver configure
   ros2 lifecycle get /robotsdk/anyverse_robot_driver
   It should be inactive. Do NOT activate unless ready to enable motors.

5. Read a group directly with the SDK CLI (ONLY while ROS driver is stopped):
   /home/nvidia/robotsdk/shell.sh
   anyverse-robot joints left_arm
   anyverse-robot joints right_arm
   anyverse-robot joints waist
   anyverse-robot joints head
   Waist connection may take approximately 20 seconds.
   These CLI commands connect to hardware themselves; do not combine with a running driver.

ROS interface:
  Source /workspace/env.sh inside container (shell.sh does this automatically).
  ROS_DOMAIN_ID=142, localhost DDS, namespace /robotsdk.
  topics control mode; no ros2_control controllers or MoveIt/URDF launched.
  Driver /robotsdk/anyverse_robot_driver; use ros2 node info to inspect interfaces.
  No unrequested remote-machine ROS discovery is enabled.

Files:
  /home/nvidia/robotsdk/config/robot.yaml -> container /etc/anyverse-robot/robot.yaml (read-only)
  /home/nvidia/robotsdk -> container /workspace
  /home/nvidia/robotsdk/logs: validation and ROS logs
  create-container.sh: creates the runtime from the saved image if absent
  start-container.sh: starts an existing container WITHOUT starting its driver

Hardware permissions: host network, privileged device access, /dev bind,
rtprio=95, unlimited memlock. No host root filesystem/PID namespace or Docker socket mount.
Container is root, has no auto-restart and starts only an idle process.
The SDK image contains packages; the mounted workspace contains launchers/config/logs.

Verification boundary:
  Native CLI returned live data from all 20 joints.
  ROS lifecycle configure is tested without activation (see logs).
  Motor enable and physical motion are NOT tested by this deployment.
  A live controller process is not proof of successful motion; verify with an operator before use.
