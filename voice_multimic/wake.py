#!/usr/bin/env python3
"""Shared English wake capture/playback loop. No agent or motion commands."""
from collections import deque
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'vendor'))
from coffee_pnp_hmi.wake_word import create_wake_word
SAY_LOCK = Path('/home/nvidia/robot_say/.play.lock')
RATE = 16000
MIC_CHANNELS = (2, 3, 4, 5)  # zero-based; 6,7 are playback references, NOT microphones
STOP = threading.Event()


def emit(event, **fields):
    print(json.dumps(dict(event=event, time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), **fields), ensure_ascii=False), flush=True)


def decode(kws, streams):
    hits = []
    ready = [s for s in streams if kws.is_ready(s)]
    while ready:
        kws.decode_streams(ready)
        for s in ready:
            word = kws.get_result(s)
            if word:
                hits.append(word)
                kws.reset_stream(s)
        ready = [s for s in streams if kws.is_ready(s)]
    return hits


def playback_busy():
    with SAY_LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
    return False


def live(kws, args):
    ack = ROOT/'ack_tour_fast.wav'
    if not args.no_response and not ack.is_file():
        raise ValueError('缺少本地应答音频 ack_tour_fast.wav')
    def new_streams():
        if hasattr(kws, 'create_streams'):
            return kws.create_streams(MIC_CHANNELS)
        return [kws.create_stream() for _ in MIC_CHANNELS]
    streams = new_streams()
    rec = response = None
    response_started = 0.0
    errors = deque(maxlen=8)
    began = last_frame = last_health = time.monotonic()
    hold_until = 0.0
    paused = False
    count = 0
    buf = bytearray()
    ready_announced = False
    try:
        if not args.no_response:
            with wave.open(str(ack), 'rb') as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (48000, 2, 2):
                    raise ValueError('Invalid reply format; require 48kHz stereo S16')
        rec = subprocess.Popen(['arecord','-q','-D','hw:AIUIUSBMC,0','-t','raw',
                                '-f','S16_LE','-r','16000','-c','8','--buffer-time=200000'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        def drain():
            for line in iter(rec.stderr.readline, b''):
                errors.append(line.decode(errors='replace').strip())
        threading.Thread(target=drain, daemon=True).start()
        selector = selectors.DefaultSelector()
        selector.register(rec.stdout, selectors.EVENT_READ)
        while not STOP.is_set():
            now = time.monotonic()
            if args.seconds and now-began >= args.seconds:
                break
            if rec.poll() is not None:
                raise RuntimeError('录音停止：'+'; '.join(errors))
            if response is not None and now-response_started > 20:
                raise RuntimeError('应答播放超过 20 秒，停止监听并清理播放进程')
            if response is not None and response.poll() is not None:
                if response.returncode:
                    emit('response_error', exit_code=response.returncode)
                response = None
                hold_until = max(hold_until, now+0.8)
            if not selector.select(timeout=0.25):
                if now-last_frame > 3:
                    raise RuntimeError('连续 3 秒没有麦克风数据')
                continue
            chunk = os.read(rec.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('麦克风数据流结束')
            buf.extend(chunk)
            # 20ms frames, 8 interleaved S16 channels.
            while len(buf) >= 5120:
                a = np.frombuffer(bytes(buf[:5120]), dtype='<i2').reshape(-1,8).astype(np.float32)
                del buf[:5120]
                now = last_frame = time.monotonic()
                if not ready_announced:
                    emit('ready', keyword='Hello Porsche', backend=getattr(args,'backend','coffee_hmi:sherpa_kws'),
                         mic_channels=list(MIC_CHANNELS), local_only=True)
                    ready_announced = True
                ref_rms = float(np.sqrt(np.mean(a[:,6:8]**2)))
                if ref_rms > 60 or playback_busy() or response is not None:
                    hold_until = max(hold_until, now+0.8)
                if now < hold_until:
                    if not paused:
                        streams = new_streams()
                    paused = True
                else:
                    paused = False
                    for s,c in zip(streams, MIC_CHANNELS):
                        s.accept_waveform(RATE, a[:,c]/32768)
                    hits = decode(kws, streams)
                    if hits:
                        count += 1
                        emit('wake', keyword=hits[0], count=count)
                        streams = new_streams()
                        hold_until = now+4.0
                        paused = True
                        if not args.no_response:
                            response = subprocess.Popen([sys.executable,str(ROOT/'play_ack.py')],
                                                        start_new_session=True)
                            response_started = now
                if now-last_health >= 10:
                    emit('health', mic_rms=[round(float(np.sqrt(np.mean(a[:,c]**2))),1) for c in MIC_CHANNELS],
                         reference_rms=round(ref_rms,1), paused=paused, wakes=count, capture_errors=list(errors))
                    last_health = now
    finally:
        for p in (response,rec):
            if p is not None and p.poll() is None:
                if p is response:
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if p is response:
                        os.killpg(p.pid, signal.SIGKILL)
                    else:
                        p.kill()
                    p.wait()
        emit('stopped', wakes=count)


if __name__ == '__main__':
    os.execv(sys.executable, [sys.executable, str(ROOT/'asr_live.py'), *sys.argv[1:]])
