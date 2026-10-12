导航 deb 下载工具（机器人端运行；只下载，不安装）

将本目录放到机器人 /home/nvidia/nav_debs，Python3 标准库即可，无需 pip。
需要管理员提供真实 Nexus 地址和 APT 仓库名称；公开版没有内置真实地址。
下方 nexus.example.com / YOUR_REPOSITORY 均为示例，必须替换。服务器需允许读取。
下载模式需 Linux 与 dpkg-deb（Ubuntu 通常自带）。不用 sudo，不用启动任何 ROS 驱动。

核对版本是否齐全（不下载）：
bash /home/nvidia/nav_debs/download-nav-debs.sh --server https://nexus.example.com --repository YOUR_REPOSITORY --version 2.2.1-0noble --check

一次下载全部 9 个包：
bash /home/nvidia/nav_debs/download-nav-debs.sh --server https://nexus.example.com --repository YOUR_REPOSITORY --version 2.2.1-0noble

默认保存：/home/nvidia/nav_debs/downloads/2.2.1-0noble/arm64/
下次换版只改 --version 后面的版本号，不要省略 -0noble。
自定义下载根目录：在命令末尾加 --output /home/nvidia/navigation_packages

包括：ros-jazzy-livox-sdk2、ros-jazzy-livox-ros-driver2、ros-jazzy-fast-lio、
ros-jazzy-ndt-omp-ros2、ros-jazzy-lidar-localization-ros2、ros-jazzy-move、
ros-jazzy-nav2-kitt15、ros-jazzy-kitt15-micro-nav、ros-jazzy-e-slam-bringup。

先查询全部包精确版本/架构，缺包或重复匹配就停止，不悄悄换成别的版本。
下载后验证大小、仓库 SHA-256 及 deb 内部 Package/Version/Architecture。
重复执行会校验并跳过正确文件；已有文件校验失败时拒绝覆盖，检查后换一个输出目录。
下载中断可重跑，已完成文件保留，未完成文件重新下载；并非字节级断点续传。
成功后生成 SHA256SUMS 和 manifest.json。
当前仓库使用 HTTP，哈希能检测传输损坏，但不能代替签名或可信 HTTPS 的来源认证。
只包含截图指定的 9 个包，不是完整依赖镜像；安装前仍需单独核对依赖和配置备份。
脚本不安装包、不升级系统、不启动或停止容器/ROS/底盘，不覆盖机器人配置。
