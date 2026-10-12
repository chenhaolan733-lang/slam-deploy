#!/usr/bin/python3
"""Gracefully stop only the SDK launch inside this container, no forced kill."""
import os
from pathlib import Path
import select
import signal

targets=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        args=(p/'cmdline').read_bytes().split(b'\0')
        if (b'/opt/ros/jazzy/bin/ros2' in args and b'launch' in args
                and b'anyverse_robot_bringup' in args and b'bringup.launch.py' in args):
            targets.append(int(p.name))
    except (FileNotFoundError,PermissionError,ProcessLookupError):
        continue
if not targets:
    print('SDK launch is not running.')
for pid in targets:
    fd=os.pidfd_open(pid)
    try:
        signal.pidfd_send_signal(fd,signal.SIGINT)
        if not select.select([fd],[],[],20)[0]:
            raise SystemExit('SDK did not exit cleanly in 20 s. Inspect logs; do not force-kill unsupported joints.')
        print(f'SDK launch {pid} stopped cleanly.')
    finally:
        os.close(fd)
