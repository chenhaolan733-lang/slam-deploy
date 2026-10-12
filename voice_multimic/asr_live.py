#!/usr/bin/env python3
"""Local English phrase wake through the coffee_hmi interface; no motion/agent."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from pathlib import Path
import signal
import sys
import time

import numpy as np
import sherpa_onnx
import wake


class PhraseStream:
    def __init__(self, engine, channel=None):
        self.engine = engine
        self.channel = channel
        self.generation = engine.generation
        self.vad = sherpa_onnx.VoiceActivityDetector(engine.vad_config, buffer_size_in_seconds=10)
        self.buffer = np.empty(0, np.float32)
        self.hit = ''

    def accept_waveform(self, sample_rate, samples):
        if sample_rate != 16000:
            raise ValueError('Live input must be 16000 Hz')
        self.buffer = np.concatenate((self.buffer,np.asarray(samples,dtype=np.float32)))
        while len(self.buffer) >= 512:
            self.vad.accept_waveform(self.buffer[:512])
            self.buffer = self.buffer[512:]
            while not self.vad.empty():
                segment = np.asarray(self.vad.front.samples,dtype=np.float32).copy()
                self.vad.pop()
                if (self.generation == self.engine.generation
                        and self not in self.engine.pending
                        and len(self.engine.pending) < len(wake.MIC_CHANNELS)
                        and .3 <= len(segment)/16000 <= 7):
                    self.engine.pending[self] = self.engine.pool.submit(self.engine.recognize,segment)


class PhraseEngine:
    def __init__(self, debug=False):
        self.detector = wake.create_wake_word(dict(enabled=True,backend='whisper_phrase',
            model_dir=str(wake.ROOT/'models/whisper-base.en')))
        self.vad_config = sherpa_onnx.VadModelConfig()
        self.vad_config.silero_vad.model = str(wake.ROOT/'models/silero_vad.onnx')
        self.vad_config.silero_vad.threshold = .5
        self.vad_config.silero_vad.min_silence_duration = .55
        self.vad_config.silero_vad.min_speech_duration = .25
        self.vad_config.silero_vad.max_speech_duration = 6
        self.vad_config.sample_rate = 16000
        self.vad_config.num_threads = 1
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = {}
        self.generation = 0
        self.debug = debug

    def recognize(self, samples):
        started = time.monotonic()
        audio = np.clip(samples*32768,-32768,32767).astype(np.int16)
        text = self.detector.transcribe(audio)
        match = self.detector.match_details(text)
        matched = match is not None
        fields = dict(matched=matched, seconds=round(time.monotonic()-started,3))
        if match:
            fields['matched_alias'] = match['alias']
            fields['match_kind'] = match['kind']
        if self.debug:
            fields['recognized'] = text
        wake.emit('speech_checked',**fields)
        return 'HELLO_PORSCHE' if matched else ''

    def create_stream(self):
        return self.create_streams((None,))[0]

    def create_streams(self, channels):
        # A whole group shares the playback/cooldown boundary. Each physical mic
        # gets its own VAD and one bounded recognition job; don't cancel siblings
        # while constructing the group. Canceled/running old jobs cannot trigger
        # a later wake or a second navigation command after a reply.
        for job in self.pending.values():
            job.cancel()
        self.pending.clear()
        self.generation += 1
        return [PhraseStream(self, channel) for channel in channels]

    def is_ready(self, stream):
        job = self.pending.get(stream)
        return stream.generation == self.generation and job is not None and job.done()

    def decode_streams(self, streams):
        for stream in streams:
            if self.is_ready(stream):
                stream.hit = self.pending.pop(stream).result()  # failures propagate, never wake

    def get_result(self, stream):
        return stream.hit

    def reset_stream(self, stream):
        stream.hit = ''
        stream.vad.reset()
        stream.buffer = np.empty(0,np.float32)

    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)


def main():
    parser=argparse.ArgumentParser(description='Hello Porsche -> Hello, I am here. Local English ASR wake.')
    parser.add_argument('--seconds',type=float,default=0)
    parser.add_argument('--no-response',action='store_true')
    parser.add_argument('--debug',action='store_true',help='Print recognized short speech for diagnosis')
    args=parser.parse_args()
    if args.seconds < 0:
        parser.error('seconds must be nonnegative')
    args.backend='coffee_hmi:whisper_phrase'
    # All four verified physical microphones, never playback reference 6/7.
    wake.MIC_CHANNELS=(2, 3, 4, 5)
    with Path('/home/nvidia/robot_wakeup/.wake.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        engine=PhraseEngine(debug=args.debug)
        try:
            wake.live(engine,args)
        finally:
            engine.close()


if __name__=='__main__':
    signal.signal(signal.SIGINT,lambda *_: wake.STOP.set())
    signal.signal(signal.SIGTERM,lambda *_: wake.STOP.set())
    try:
        main()
    except Exception as exc:
        wake.emit('error',message=str(exc))
        sys.exit(1)
