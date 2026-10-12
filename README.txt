slam-deploy
===========

基于 deb 的机器人部署与操作脚本，公开脱敏版。
主要内容为 SLAM 建图、修图、滤波、地图备份部署，也保留 RobotSDK、语音测距和电量监控辅助脚本。

重要边界
--------
这是现有已部署环境的操作工具，不是任意机器人一键安装器。
公开版本与现场部署版不是完全相同：内网地址、制品服务器、设备序列号和真实电机配置已移除。
192.0.2.*、example.com、SET_* 都是示例，必须由维护人员替换为已核实的现场设置。
不得直接覆盖机器上现有配置。机器人正在工作的私有配置与地图不在本仓库。
路径 /home/nvidia、/home/sunrise、/vla_infer、/kitt15_navi 以及 e_42 为脚本布局约定，部署到其他环境时需适配。

目录
----
navigation/download/  精确版本下载9个导航deb；校验SHA256和包元数据，只下载不安装。
navigation/workflow/  navmap：新建地图、建图、修图、0.05米点云滤波、备份部署、网页入口。
robotsdk/             容器和驱动启动脚本，机械臂/头颈/腰腿/灵巧手控制及离线测试。
voice_multimic/       四麦克风更新文件及hello距离测试；是已有语音应用的补充，不是完整应用。
battery_monitor/     双电池只读监控；低于20%循环播报，充电后解除；systemd开机启动。
diagnostics/         只读硬件诊断源码。相机序列号必须通过命令行明确指定。

SLAM 日常使用（已安装配套deb和配置的容器内）
------------------------------------------------
source /vla_infer/customer_navigation/env.sh
navmap new hall_YYYYMMDD
navmap mapping

完成建图后Ctrl+C，等待地图保存完成；不要反复中断。

navmap edit

网页修图完成后点击导出导航地图，再Ctrl+C退出编辑器。

navmap deploy --dry-run
navmap deploy

默认部署所选地图最新一次修图导出的栅格；没有导出结果则拒绝，不静默使用原图。
正式部署包含0.05米点云滤波，已有结果仅在输入/输出哈希一致时复用。
旧地图整目录、加载配置和点位都会备份；部署后核对PCD/PGM哈希和YAML。
坐标系发生变化会备份并清空旧点位，需重新定位、采点。
必须先停稳驻车并停止旧建图/定位/导航；脚本不会自动停止服务或发移动命令。
部署完成不会自动启动导航。
细节见 navigation/workflow/NAVMAP_DEPLOY_FIX.txt。

首次适配
--------
1. 由管理员提供匹配的平台、导航deb、RobotSDK及合法可用的基础镜像。
2. 将各模块放到对应说明指定位置；不要把Git仓库根目录当成已部署的运行目录。
3. 核实ROS域、DDS、容器挂载、设备型号/接线/限位、账户和所有固定路径。
4. navmap加载路径助手必须由root在推理容器内安装；仅开放两个固定路径修改动作。
5. SDK实际robot.yaml、hands-042.yaml在本地保存且gitignored；不发布电机整定参数。
6. 网络例子不能直接连接真实设备；电池SSH key必须重新生成并安装受限授权。

下载导航deb
-----------
bash navigation/download/download-nav-debs.sh --server https://nexus.example.com --repository YOUR_REPOSITORY --version 2.2.1-0noble --check

用管理员提供的真实地址/仓库替换示例。去掉 --check 才下载；不会安装或升级系统。

依赖与授权
----------
目标平台主要为Ubuntu 24.04 arm64 / ROS 2 Jazzy；电池订阅器示例在底盘ROS 2 Humble运行。
Python测试依赖PyYAML/Pillow；部分语音测试还依赖numpy、sherpa-onnx和本地模型。
RobotSDK示例对应0.33.0接口；SDK本体、厂商库、驱动deb、基础镜像需自行授权获取。
机器人地图、采集数据、SDK二进制、模型、音频、密码、Token和私钥均不在仓库中。
Docker构建需要显式 --build-arg BASE_IMAGE=已批准镜像，以及本地packages/和真实robot.yaml。
ros-snapshot-keyring.gpg为ROS公开验签公钥，不是私钥。
本仓库没有替任何第三方软件授予额外许可；不要自行假定SDK/厂商文件可以再分发。

验证与安全
----------
公开版的离线测试和静态检查不等于在任意机器人上验证成功。
运动脚本默认预览，--execute才执行；执行前核对设备身份和限位，清空工作区域并准备急停。
现有控制脚本不是通用碰撞规避系统。地图部署、服务启停与硬件使能应由现场人员监督。
禁止把私有现场配置、部署日志、token链接或地图提交到公开GitHub。
