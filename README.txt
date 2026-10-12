slam-deploy
===========

仅收录方便使用 SLAM deb 包的下载、部署和地图操作辅助脚本。
不包含 deb 包、SLAM 源码、机器人地图、业务代码或其他硬件模块。

目录
----
navigation/download/  下载指定版本的9个导航deb，校验SHA256和包元数据；只下载，不安装。
navigation/workflow/  navmap：保存地图名称/路径、建图、修图、滤波、备份部署、RViz与网页入口。
两个目录均包含使用说明和相应测试。

使用前提
--------
现有机器人推理容器、ROS 2 Jazzy、配套导航deb、站点配置与avla环境已部署。
这是配套操作工具，不是从空白系统开始的一键安装器。
公开版的下载服务器与SSH地址为示例，需要替换为现场地址。
路径 /vla_infer/customer_navigation、/kitt15_navi 和站点 e_42 沿用已部署机器的布局；其他机器需核实适配。
不要覆盖现场已有地图、点位和data目录。

下载deb（机器人宿主机）
----------------------
bash navigation/download/download-nav-debs.sh --server https://nexus.example.com --repository YOUR_REPOSITORY --version 2.2.1-0noble --check

替换服务器与仓库名。--check只核对包是否齐全；去掉后下载，不会安装或升级系统。
详细用法见 navigation/download/README.txt。
下载得到的deb仅保存在本地，不提交到Git。

地图操作（已部署的容器内）
------------------------
source /vla_infer/customer_navigation/env.sh
navmap new hall_YYYYMMDD
navmap mapping

结束建图时Ctrl+C一次，等待地图保存完成。

navmap edit

在网页修图并点击导出导航地图，再Ctrl+C退出编辑器。

navmap deploy --dry-run
navmap deploy

自动记住选中的地图，默认使用该地图最新一次修图导出结果；没有导出则拒绝，不静默使用原图。
正式部署包含0.05米点云滤波；已有结果仅在输入/输出哈希一致时复用。
替换前备份旧地图、加载配置及点位；坐标系改变时备份并清空旧点位，需重新定位、采点。
部署不会自动启动导航。操作前先停稳驻车并停止旧建图/定位/导航。
安装位置、权限助手、端口转发和完整操作见 navigation/workflow/README.txt。
地图部署修复说明见 navigation/workflow/NAVMAP_DEPLOY_FIX.txt。

提交范围
--------
仅提交上述SLAM deb配套脚本、说明与测试。
不提交deb、地图、运行日志、私有配置、密码、Token和私钥。
离线测试不替代现场建图、定位和导航验收。
