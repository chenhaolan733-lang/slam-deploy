ARG BASE_IMAGE
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY ros-snapshot-keyring.gpg /usr/share/keyrings/ros-snapshot-keyring.gpg
COPY ros2.list /etc/apt/sources.list.d/ros2.list
COPY policy-rc.d /usr/sbin/policy-rc.d
COPY anyverse-mw.conf /etc/ld.so.conf.d/anyverse-mw.conf
COPY config/robot.yaml /etc/anyverse-robot/robot.yaml
COPY packages/anyverse-robot_0.33.0_arm64.deb packages/anyverse-robot-ros2_0.33.0_arm64.deb /packages/
RUN set -eu; chmod 755 /usr/sbin/policy-rc.d; apt-get update; \
    mapfile -t controls < <(dpkg-query -W -f='${binary:Package}\t${Version}\n' 'ros-jazzy-*' | awk '$2 ~ /^(4\.42\.2|4\.36\.0)-/ {print $1}'); \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        /packages/anyverse-robot_0.33.0_arm64.deb /packages/anyverse-robot-ros2_0.33.0_arm64.deb \
        "${controls[@]}" ros-jazzy-realtime-tools ros-jazzy-control-toolbox; \
    ldconfig; apt-get check; anyverse-robot config validate
LABEL anyverse.sdk.version="0.33.0" anyverse.robot="kitt15-042"
ENTRYPOINT ["/bin/bash", "-c", "exec sleep infinity"]
