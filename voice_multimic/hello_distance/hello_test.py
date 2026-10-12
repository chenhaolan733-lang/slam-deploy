#!/usr/bin/env python3
"""HELLO-only, repeatable distance test. No business state, navigation or agent."""
import argparse
from collections import deque
import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import wake
from asr_live import PhraseEngine
from hello_match import matches_hello

ROOT = Path(__file__).resolve().parent
CHANNELS = (2, 3, 4, 5)
STOP = threading.Event()
LOG = None
LOG_LOCK = threading.Lock()
DISTANCE = ''


def emit(event, **fields):
    row = dict(event=event, time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), distance=DISTANCE, **fields)
    line = json.dumps(row, ensure_ascii=False)
    with LOG_LOCK:
        print(line, flush=True)
        if LOG:
            LOG.write(line + '\n')
            LOG.flush()


class HelloEngine(PhraseEngine):
    # Same model, four-microphone VAD and bounded per-channel jobs as production.
    # Only the phrase decision differs; production Porsche aliases are untouched.
    def recognize(self, samples):
        began = time.monotonic()
        audio = np.clip(samples * 32768, -32768, 32767).astype(np.int16)
        text = self.detector.transcribe(audio)
        hit = matches_hello(text)
        fields = dict(matched=hit, seconds=round(time.monotonic()-began, 3))
        if self.debug:
            fields['recognized'] = text
        emit('speech_checked', **fields)
        return 'HELLO' if hit else ''


def play_reply():
    from play_ack import check_reply, say
    audio = ROOT / 'hello_test_reply.wav'
    duration = check_reply(audio)
    with say.ROOT.joinpath('.play.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        say.run(['amixer', '-c', 'APE', 'cset', 'name=I2S1 BCLK Ratio', '2'])
        say.run(['aplay', '-q', '-D', 'hw:APE,0', str(audio)], timeout=duration+10)
    return 0


def cleanup(proc, group=False):
    if proc is None:
        return
    try:
        if group:
            os.killpg(proc.pid, signal.SIGTERM)
        elif proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=2)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        if group:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.wait(timeout=2)


def live(engine, args):
    from play_ack import check_reply
    if not args.no_response:
        check_reply(ROOT / 'hello_test_reply.wav')
    streams = engine.create_streams(CHANNELS)
    rec = reply = None
    selector = selectors.DefaultSelector()
    errors = deque(maxlen=8)
    buf = bytearray()
    began = last_frame = last_health = time.monotonic()
    hold_until = reply_started = 0.0
    paused = True
    ready = False
    count = 0
    try:
        rec = subprocess.Popen(['arecord', '-q', '-D', 'hw:AIUIUSBMC,0', '-t', 'raw',
                                '-f', 'S16_LE', '-r', '16000', '-c', '8', '--buffer-time=200000'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        def drain():
            for line in iter(rec.stderr.readline, b''):
                errors.append(line.decode(errors='replace').strip())
        threading.Thread(target=drain, daemon=True).start()
        selector.register(rec.stdout, selectors.EVENT_READ)
        while not STOP.is_set():
            now = time.monotonic()
            if args.seconds and now - began >= args.seconds:
                break
            if rec.poll() is not None:
                raise RuntimeError('麦克风退出：' + '; '.join(errors))
            if reply is not None:
                if now - reply_started > 15:
                    raise RuntimeError('测试应答播放超时')
                if reply.poll() is not None:
                    emit('reply_done', exit_code=reply.returncode)
                    cleanup(reply, group=True)
                    reply = None
                    hold_until = max(hold_until, now + 0.8)
            if not selector.select(timeout=0.2):
                if now - last_frame > 3:
                    raise RuntimeError('麦克风3秒无数据')
                continue
            chunk = os.read(rec.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('麦克风数据流结束')
            buf.extend(chunk)
            while len(buf) >= 5120:
                block = np.frombuffer(bytes(buf[:5120]), dtype='<i2').reshape(-1, 8).astype(np.float32)
                del buf[:5120]
                now = last_frame = time.monotonic()
                if not ready:
                    emit('ready', keyword='hello', mic_channels=list(CHANNELS),
                         backend='whisper-base.en', repeatable=True, cooldown_seconds=args.cooldown)
                    ready = True
                ref_rms = float(np.sqrt(np.mean(block[:, 6:8]**2)))
                if ref_rms > 60 or wake.playback_busy() or reply is not None:
                    hold_until = max(hold_until, now + 0.8)
                if now < hold_until:
                    if not paused:
                        streams = engine.create_streams(CHANNELS)
                    paused = True
                else:
                    if paused:
                        emit('listening', keyword='hello', wakes=count)
                    paused = False
                    for stream, channel in zip(streams, CHANNELS):
                        stream.accept_waveform(16000, block[:, channel] / 32768)
                    ready_streams = [s for s in streams if engine.is_ready(s)]
                    engine.decode_streams(ready_streams)
                    hits = [s for s in ready_streams if engine.get_result(s)]
                    if hits:
                        count += 1
                        emit('wake', keyword='HELLO', count=count, mic_channel=hits[0].channel)
                        streams = engine.create_streams(CHANNELS)
                        hold_until = now + args.cooldown
                        paused = True
                        if not args.no_response:
                            reply = subprocess.Popen([sys.executable, str(ROOT/'hello_test.py'), '--play-reply'],
                                                     start_new_session=True)
                            reply_started = now
                if now - last_health >= 5:
                    emit('health', mic_rms=[round(float(np.sqrt(np.mean(block[:, c]**2))), 1) for c in CHANNELS],
                         reference_rms=round(ref_rms, 1), paused=paused, wakes=count, capture_errors=list(errors))
                    last_health = now
    finally:
        cleanup(reply, group=True)
        cleanup(rec)
        selector.close()
        emit('stopped', wakes=count)


def main():
    global LOG, DISTANCE
    parser = argparse.ArgumentParser(description='独立 hello 唤醒距离测试，Ctrl+C 退出，无底盘动作。')
    parser.add_argument('--debug', action='store_true', help='显示识别文本')
    parser.add_argument('--no-response', action='store_true', help='只打印唤醒，不播音')
    parser.add_argument('--seconds', type=float, default=0, help='0表示持续测试')
    parser.add_argument('--cooldown', type=float, default=1, help='唤醒最短冷却秒数；播音结束另有0.8秒回声等待')
    parser.add_argument('--distance', default='', help='日志测距标签，例如3m；不是自动测距')
    parser.add_argument('--play-reply', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.play_reply:
        return play_reply()
    if not math.isfinite(args.seconds) or args.seconds < 0 or not math.isfinite(args.cooldown) or not 0.5 <= args.cooldown <= 10:
        parser.error('seconds需为非负数，cooldown需在0.5..10秒之间')
    DISTANCE = args.distance
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    # Same exclusive microphone lock as the real wake/tour programs.
    with Path('/home/nvidia/robot_wakeup/.wake.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('已有唤醒/业务程序占用麦克风。请在它的终端按Ctrl+C退出，再启动测试；本程序不会自动停它。')
        log_dir = ROOT / 'hello_test_logs'
        log_dir.mkdir(mode=0o700, exist_ok=True)
        log_path = log_dir / (time.strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid()) + '.jsonl')
        with log_path.open('x', encoding='utf-8') as logfile:
            LOG = logfile
            emit('starting', log_file=str(log_path))
            engine = HelloEngine(debug=args.debug)
            try:
                live(engine, args)
            finally:
                engine.close()
                LOG = None
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Log handle might already have closed while unwinding main().
        LOG = None
        emit('error', message=str(exc))
        sys.exit(1)
