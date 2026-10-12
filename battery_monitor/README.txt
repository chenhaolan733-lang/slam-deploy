机器人电量监控（kitt15-042）

已部署位置：/home/nvidia/robot_battery_monitor
底盘只读订阅：/home/sunrise/battery_monitor
systemd 服务：robot-battery-monitor.service

查看电量：
  /home/nvidia/robot_battery_monitor/battery.sh --status
查看服务：
  systemctl status robot-battery-monitor --no-pager
查看实时日志（Ctrl+C 只退出日志，不停止监控）：
  journalctl -u robot-battery-monitor -f
停止监控：
  sudo systemctl stop robot-battery-monitor
重新启动：
  sudo systemctl restart robot-battery-monitor
取消开机启动并停止：
  sudo systemctl disable --now robot-battery-monitor
恢复开机启动并立即运行：
  sudo systemctl enable --now robot-battery-monitor
测试播报一次（会真实出声，不伪造电池状态）：
  /home/nvidia/robot_battery_monitor/battery.sh --play

逻辑：
1. 只订阅底盘 /driver/battery/Data，sensor_data QoS，不控制充电/底盘/电机。
2. 分别检查每块电池。energy < 20、is_in_place=true、is_connected=true、
   error_code=0 且 is_charging=false 时触发。
3. 扬声器播报“电量低于20%请充电。”，每30秒尝试一次。
4. 报警触发后锁存，直到该电池 is_charging=true 才解除；电量在20%附近
   抖动不会频繁开关。若另一块低电量电池仍未充电，继续提醒。
5. 充电后再次拔掉充电器、且电量仍低于20%，会再次报警。
6. 数据超过5秒未更新、缺失、通信异常或电池故障时，该电池不进行电量播报，
   日志/status 显示 NO_DATA 或 BATTERY_FAULT；恢复可信数据后自动继续。
7. 与既有语音脚本共用 .play.lock；正在讲话时延后重试，不重叠播放。
   不自动改音量/DSP，沿用 say.py 已有播放方法和2秒前置静音。
8. 充电状态到达后，会中断正在播放的低电量提示；约1秒的订阅上报周期。
9. 开机由 systemd 启动，不依赖登录，不要在 .bashrc 再启动一份。

实现及限制：
- 机器人通过专用 SSH 密钥启动底盘只读订阅程序，NDJSON 传回机器人。
- key 仅允许192.0.2.100来访，强制执行 reader.sh，禁止PTY和转发。
- 机器人 keys/、.runtime/、low_battery.wav 为部署产物，不上传GitLab。
- 不保存SSH密码；底盘已有其他 authorized_keys 条目保留，并备份。
- 开机网络/驱动未就绪时自动每5秒重连，不启动或重启底盘驱动。
- 校验底盘消息时间戳和传输时间；双方系统时钟应同步。时钟差过大拒绝使用数据。
- 现场在线TTS返回403，因此部署的固定提示音改由Windows自带Huihui中文语音
  离线生成，内容“电量低于百分之二十，请充电。”，再用SoX转为48kHz/双声道/
  16bit、峰值-12dB（按要求比初版提高6dB）、前置2秒/后置1秒静音；运行不需要互联网。
  prepare_audio.py 保留为可选的在线再生成方法，需使用 robot_say 的venv。
- 停止监控不会删除脚本；服务只是提醒，不能替代电池保护电路。
- 尚未做真实低电量放电/充电切换及断电重启的端到端验收。

迁移部署（这是042现场配置，不是任意机器通用安装器）：
1. 核对底盘IP/机器人内网IP、ROS环境路径、消息字段和扬声器路由。
2. 机器人生成专用 keys/id_ed25519；不要提交私钥。
3. 把 reader.sh/battery_reader.py/install-reader.sh 和公钥上传到底盘，
   sunrise 执行 install-reader.sh。该脚本仅安装订阅器和受限密钥，不启动驱动。
4. 核实底盘SSH主机指纹，把已信任 known_hosts 记录保存到机器人 keys/known_hosts。
5. 使用 robot_say/.venv/bin/python prepare_audio.py 准备离线提示音。
6. python3 -m unittest discover -v；执行 bash install-service.sh 安装并启用服务。
   安装器只重启本监控服务，不重启底盘或语音业务。

2026-10-12验证：23项离线测试通过（18项策略+5项进程/模拟播放集成测试），
真实双电池遥测正常，systemd服务已启用并运行；固定音频试播命令成功返回。
是否现场听清尚待确认；没有人为放电到20%以下，也未重启整机。
