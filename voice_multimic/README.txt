四麦克风更新（42机，2026-10-12）

正式目录：/home/nvidia/robot_english_wake
修改：wake.py、asr_live.py、tour_demo.py；新增 test_multimic.py。
tour_route.py 复用 tour_demo.run，因此 A→F 真实业务也使用四麦克风。

AIUI 8路USB输入中，实际麦克风是零基通道2、3、4、5。
0/1 实测没有有效人声数据；6/7 是播放回声参考，不能送去识别人声。
四路分别使用VAD，分别可进入识别，ASR使用单工作线程、每路最多一个待处理任务，避免无限排队。
任一路接受指令后重建整组收音流、取消其余旧任务，避免同一句go on多次导航。
播放期/回声参考/播放锁/导航忙期间仍暂停接收业务指令，保持原有防回声逻辑。
没有改变唤醒词/同音词、go on词表、导航路线、驻车判断、音量、增益、VAD阈值。
四路增加计算量，也可能增加误唤醒机会；不能保证指定距离，需现场测试。

原命令不变；已运行的进程必须退出后重开才能加载新文件。
唤醒测试：/home/nvidia/robot_english_wake/wake.sh --debug
无底盘演示：/home/nvidia/robot_wakeup/.venv/bin/python /home/nvidia/robot_english_wake/tour_demo.py --debug
真实业务：仍用原来的 tour_route.py --live --confirm-clear-route --debug 命令；这条会按业务指令导航，不是单纯收音测试。
看到 ready 中 "mic_channels": [2, 3, 4, 5] 即为四麦克风版本。
health 的 mic_rms 现在是4个数值；业务 speech_checked 新增 mic_channel，方便查看哪一路识别。

备份：/home/nvidia/robot_english_wake_multimic_backup_20261012_V815pU
验证：8项多路/队列/过期任务测试 + 18项原路线/驻车测试，共26项；真实模型四路静音输入测试；实机5秒只收音验证通过。
距离改善尚未做现场对照验证，用户后续自行测试。

本汇总目录仅保存改动文件，不含原应用的音频、模型、vendor、桥接脚本及虚拟环境。
不能把它当成完整语音系统直接从零部署，更新时保留上述现有依赖和业务文件。
