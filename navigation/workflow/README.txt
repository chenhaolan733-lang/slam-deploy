42 机 deb 导航配套操作脚本（2026-10-11，RViz deb 2.0.3 版）

使用前提：现有 infer_kitt15_seatbelt 容器、42 机标定/站点、底盘通信及 avla 业务环境已经部署。
不是另一台机器的通用安装包；不修改厂家驱动，不包含任何 SSH 凭据。

电脑端不安装配套脚本，只需 SSH。另开电脑本地终端（不是机器人终端）执行：
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:6080:127.0.0.1:6080 -L 127.0.0.1:8765:127.0.0.1:8765 -L 127.0.0.1:8088:127.0.0.1:8088 nvidia@192.0.2.42
最后的用户名@IP 改成当前机器人的 SSH 目标，也可以用配置好的 SSH 别名。
不需要电脑网卡 IP；浏览器统一使用 127.0.0.1。保持转发终端开启，Ctrl+C 只断开转发，不会停车。
换网后改机器人 IP 并重跑命令；换电脑直接执行同一条命令，不用复制脚本。
机器人宿主机 SSH 终端可用 echo "$SSH_CONNECTION" 查看：客户端IP 客户端端口 服务器IP SSH端口。
容器内可能没有该变量；跳板/NAT 场景显示的是该 SSH 连接两端，不一定是电脑实际网卡地址。
端口被占用时先确认是否已有同一机器人的转发，不要盲目关闭其他进程。

容器内：
source /vla_infer/customer_navigation/env.sh
navmap status

新建地图：navmap new hall_20261011_01
建图：navmap mapping
建图视图（另一终端）：navmap rviz mapping
等价 deb 命令：ros2 run e_slam_bringup visualize_mapping --restart --no-xterm
结束：建图终端 Ctrl+C 一次，等保存结束。
修图：navmap edit（转发 8765，打开终端完整带 token 链接，导出后 Ctrl+C）
部署预览：navmap deploy --dry-run
部署：navmap deploy（自动滤波并选用本地图最后一次导出）
不修图：navmap deploy --original
切换工作地图：navmap use hall_20261011_01（只选中，不自动部署）
导航视图：navmap rviz navigation
等价 deb 命令：ros2 run e_slam_bringup visualize_navigation --restart --no-xterm
只检查配置、不启动桌面：navmap rviz mapping --dry-run
重新显示已启动网页链接：navmap links
转发建立后，Ctrl+单击机器人终端输出的完整网址；修图/调速链接不要省略 token。
修图使用 navmap edit；需要重新获取当次网址时执行 navmap links，不要把 token 发给无关人员。

每个新终端都 source env.sh。地图名和配置保存在 data/，不依赖上一个终端的变量。
new 只创建本地图配置，不启动建图；use 只选工作地图；deploy 才替换导航数据。
导航仍加载 e_42.yaml 中现有固定地图路径；这个旧路径名字带 src，但只作地图数据存储，不需要源码编译。
新地图：data/saved/地图名/，一组三件套 PCD、YAML、PGM。
点位备份：data/waypoint_backups/。
地图备份：现有地图数据父目录的 backups/（部署工具打印完整路径）。
换了定位 PCD 时会备份并清空旧点位，必须重采；相同 PCD 的栅格更新保留点位。
生产地图、点位和进程未在脚本安装/离线测试时修改。

navmap 调用已安装的 ros2 launch/run，不依赖 /kitt15_navi/scripts。
RViz/noVNC 使用 ros-jazzy-e-slam-bringup >= 2.0.3 自带入口和资源，不再自带 start_novnc_rviz.sh。
浏览器使用 SSH 转发，不要开放到公网。
该 RViz 命令会重启可视化进程，不会启动导航，但不要和其他人的 RViz 工作同时使用。
动态障碍绕行以当前站点配置为准；本机核对时关闭，现场路线必须清空并备好实体急停。

验证：env.sh 语法；9 项自动化测试；两个 deb RViz 入口 dry-run；临时地图调用 deb 滤波、编辑器读图/导出、部署、备份。
没有启动真实建图、修改当前地图、重启导航或执行底盘运动。新地图整流程仍需现场验收。

部署路径：宿主机 /home/nvidia/anyverse_vla_infer/customer_navigation
         容器内 /vla_infer/customer_navigation
交付时包含本目录文件和配套 deb、业务环境；data/ 为客户生成数据，升级脚本时不能覆盖。
