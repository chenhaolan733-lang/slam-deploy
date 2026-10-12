#!/usr/bin/python3
"""Robot-side battery monitoring. No motion, charging, or battery control calls."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from policy import Policy

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
SAY_ROOT = Path('/home/nvidia/robot_say')
SERVICE = 'robot-battery-monitor.service'


def log(event, **details):
    print(json.dumps({'event': event, 'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **details}, ensure_ascii=False), flush=True)


def stop_process(proc):
    if proc is not None:
        # Kill the whole group, including aplay even if its parent exited.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=1)


def play():
    sys.path.insert(0, str(SAY_ROOT))
    import say
    with (SAY_ROOT / '.play.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        say.play(ROOT / 'low_battery.wav')
    return 0


def write_status(snapshot):
    snapshot.update(updated_unix=time.time(), pid=os.getpid())
    tmp = RUNTIME / 'status.tmp'
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(RUNTIME / 'status.json')


def show_status():
    path = RUNTIME / 'status.json'
    if not path.exists():
        print('没有监控数据；查看 systemctl status ' + SERVICE)
        return 1
    data = json.loads(path.read_text())
    age = time.time() - data['updated_unix']
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
    print('监控服务：' + ('运行中' if active else '未运行'))
    fresh = active and 0 <= age < 6 and data['state'] != 'NO_DATA'
    print('数据：' + ('实时' if fresh else '已过期/断线，以下仅为最后一次读数'))
    print('状态：' + (data['state'] if fresh else 'NO_DATA'))
    for row in data['batteries']:
        print(f"电池 {row['id']}：{row['energy']}%，充电={str(row['is_charging']).lower()}，在位={row['is_in_place']}，通信={row['is_connected']}，错误码={row['error_code']}")
    print('报警电池：' + str(data['alarming_ids'] if fresh else []))
    return 0 if fresh else 1


def run(interval):
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    with (RUNTIME / 'monitor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('监控已在运行，不能重复启动')
        return loop(interval)


def loop(interval, transport_cmd=None, playback_cmd=None):
    policy = Policy()
    running = True
    def shutdown(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    selector = selectors.DefaultSelector()
    stream = audio = None
    buffer = b''
    next_connect = next_alarm = 0.0
    audio_started = connected_at = last_write = 0.0
    previous = None
    ssh = ['ssh', '-T', '-i', str(ROOT / 'keys/id_ed25519'), '-o', 'BatchMode=yes',
           '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'UserKnownHostsFile=' + str(ROOT / 'keys/known_hosts'),
           '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=2',
           'sunrise@192.0.2.10']
    if transport_cmd is not None:
        ssh = transport_cmd
    player = playback_cmd or [sys.executable, str(ROOT / 'monitor.py'), '--play']
    log('started', threshold=20, interval_seconds=interval, text='电量低于20%请充电。')
    def disconnect(reason):
        nonlocal stream, buffer, next_connect
        if stream:
            selector.unregister(stream.stdout)
            stop_process(stream)
            stream.stdout.close()
        stream, buffer = None, b''
        next_connect = time.monotonic() + 5
        policy.disconnect()
        log('telemetry_disconnected', reason=reason)
    try:
        while running:
            now = time.monotonic()
            if stream is None and now >= next_connect:
                stream = subprocess.Popen(ssh, stdout=subprocess.PIPE, start_new_session=True)
                os.set_blocking(stream.stdout.fileno(), False)
                selector.register(stream.stdout, selectors.EVENT_READ)
                connected_at = now
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    disconnect('SSH closed')
                    break
                buffer += chunk
                if len(buffer) > 65536:
                    disconnect('telemetry buffer limit')
                    break
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        policy.update(json.loads(line), time.monotonic())
                    except (ValueError, TypeError, AttributeError) as exc:
                        disconnect('invalid telemetry: ' + str(exc)[:150])
                        break
            now = time.monotonic()
            if stream and now - (policy.last_received if policy.last_received is not None else connected_at) > 5:
                disconnect('no fresh battery data for 5 seconds')
            snapshot = policy.snapshot(now)
            changed = (snapshot['state'], tuple(snapshot['alarming_ids']), tuple(snapshot['fault_ids']))
            if changed != previous:
                log('state', **snapshot)
                previous = changed
            alarm = bool(snapshot['alarming_ids'])
            if audio is not None:
                result = audio.poll()
                if not alarm or now - audio_started > 45:
                    stop_process(audio)
                    log('playback_cancelled', reason='charging/fault/stale' if not alarm else 'timeout')
                    audio = None
                elif result is not None:
                    stop_process(audio)
                    log('playback_result', code=result)
                    audio = None
                    if result == 75:
                        next_alarm = now + 2
                    elif result != 0:
                        next_alarm = now + 10
            if not alarm:
                next_alarm = now
            elif audio is None and now >= next_alarm:
                audio = subprocess.Popen(player, start_new_session=True)
                audio_started = now
                next_alarm = now + interval
                log('playback_requested', battery_ids=snapshot['alarming_ids'])
            if now - last_write >= 1:
                write_status(snapshot)
                last_write = now
    finally:
        stop_process(audio)
        if stream:
            selector.unregister(stream.stdout)
            stop_process(stream)
            stream.stdout.close()
        selector.close()
        policy.disconnect()
        write_status(policy.snapshot(time.monotonic()))
        log('stopped')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--play', action='store_true', help='播放一次真实低电量提示音（测试）')
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    if args.status:
        return show_status()
    if args.play:
        return play()
    if not 10 <= args.interval <= 3600:
        parser.error('--interval must be 10..3600 seconds')
    return run(args.interval)


if __name__ == '__main__':
    sys.exit(main())
