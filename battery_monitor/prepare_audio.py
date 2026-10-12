#!/usr/bin/python3
"""Run with robot_say/.venv/bin/python; prepares cached speech, never plays it."""
from pathlib import Path
import sys
sys.path.insert(0, '/home/nvidia/robot_say')
import say
audio = say.prepare('电量低于20%请充电。')
target = Path(__file__).resolve().parent / 'low_battery.wav'
temporary = target.with_name('low_battery.prepared.wav')
say.run(['sox', str(audio), str(temporary), 'gain', '-n', '-12'])
say.check_wav(temporary)
temporary.replace(target)
print('Cached warning:', target, 'seconds:', say.check_wav(target))
