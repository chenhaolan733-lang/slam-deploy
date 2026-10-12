#!/usr/bin/env python3
"""English tour demo. MOCK navigation only; no ROS, motion, or agent calls."""
import argparse
from collections import deque
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parent
SAY_ROOT = Path('/home/nvidia/robot_say')
ASSETS = ROOT / 'tour_demo_audio'
TEXTS = {
    'opening': "Hello, I'm Porsche Tour Assistant. Next, I'll take you on a tour.",
    'arrival': 'We have arrived at the collaborative robot workstation. Say go on when you are ready.',
    'station': 'This is our collaborative robot workstation. Here, we will introduce the robot and demonstrate a simple example of human and robot collaboration. This is a short demonstration of the tour workflow. Thank you for listening.',
}
GO_ON = {('go', 'on'), ('please', 'go', 'on'), ('okay', 'go', 'on'),
         ('ok', 'go', 'on'), ('yes', 'go', 'on'), ('go', 'on', 'please'),
         ('go', 'home')}  # Observed ASR alias for continue; never a return-home command.
# Exact whole phrases only, consumed exclusively by WAIT_GO_ON states.
# Do not accept generic acknowledgements (yes/okay) or substring matches:
# "do not continue" must never start navigation.
GO_ON.update(tuple(phrase.split()) for phrase in (
    'continue', 'please continue', 'continue please',
    'continue the tour', 'please continue the tour',
    "let's continue", 'let us continue',
    'go ahead', 'please go ahead', 'go ahead please',
    'proceed', 'please proceed', 'proceed please',
    'move on', 'please move on',
    'next stop', 'next stop please',
    'next station', 'next station please',
))

# Route prompts deliberately avoid every accepted navigation phrase, so the
# microphone can reopen as soon as playback has fully exited.
POST_PLAYBACK_ECHO_GUARD_SECONDS = 0.0


def audio_info(path):
    with wave.open(str(path), 'rb') as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getcomptype()) != (48000, 2, 2, 'NONE'):
            raise ValueError('Expected 48 kHz stereo S16 PCM: ' + str(path))
        duration = w.getnframes() / 48000
    if not .5 <= duration <= 240:
        raise ValueError('Unexpected audio duration')
    return duration


def prepare(texts=TEXTS, assets=ASSETS):
    # Run using robot_say/.venv/bin/python. Text-only cloud TTS; never opens audio devices.
    sys.path.insert(0, str(SAY_ROOT))
    import say
    assets.mkdir(mode=0o700, exist_ok=True)
    for label, text in texts.items():
        source = say.prepare(text)
        with wave.open(str(source), 'rb') as w:
            params = w.getparams()
            data = w.readframes(w.getnframes())
        start, end = 86400 * 4, len(data) - 48000 * 4
        for padding in (data[:start], data[end:]):
            if any(abs(x[0]) > 1 for x in struct.iter_unpack('<h', padding)):
                raise ValueError('Refusing to trim non-silent padding')
        temporary = assets / (label + '.building.wav')
        with wave.open(str(temporary), 'wb') as w:
            w.setparams(params)
            w.writeframes(data[start:end])
        audio_info(temporary)
        temporary.replace(assets / (label + '.wav'))
    manifest = {label: {'text': text, 'sha256': hashlib.sha256((assets / (label + '.wav')).read_bytes()).hexdigest()}
                for label, text in texts.items()}
    temporary = assets / 'manifest.building.json'
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(assets / 'manifest.json')
    print('Prepared all demo audio. No recording or playback performed.')


def validate_assets(texts=TEXTS, assets=ASSETS):
    manifest = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
    for label, text in texts.items():
        path = assets / (label + '.wav')
        audio_info(path)
        if manifest[label]['text'] != text or manifest[label]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Audio/text mismatch; run --prepare again')


def play(label, assets=ASSETS):
    path = assets / (label + '.wav')
    duration = audio_info(path)
    with (SAY_ROOT / '.play.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run(['amixer', '-c', 'APE', 'cset', 'name=I2S1 BCLK Ratio', '2'],
                       check=True, capture_output=True, timeout=5)
        subprocess.run(['aplay', '-q', '-D', 'hw:APE,0', str(path)], check=True, timeout=duration + 10)


class TourFlow:
    """Pure state machine. Navigation success is explicitly simulated after opening."""
    def __init__(self, matcher, emit):
        self.matcher, self.emit = matcher, emit
        self.state = 'WAIT_WAKE'

    def transition(self, state):
        self.state = state
        self.emit('state', state=state)

    def heard(self, text):
        from coffee_pnp_hmi.wake_word.phrase_aliases import words
        if self.state == 'WAIT_WAKE' and self.matcher.matches(text):
            self.transition('OPENING')
            return 'opening'
        if self.state == 'WAIT_GO_ON' and words(text) in GO_ON:
            self.transition('STATION_INTRO')
            return 'station'
        return None

    def playback_done(self):
        if self.state == 'OPENING':
            self.transition('WAIT_ARRIVAL')
            # Replace this MOCK event with a validated navigation callback in the future.
            return self.navigation_result('success', simulated=True)
        if self.state in ('ARRIVAL', 'STATION_INTRO'):
            self.transition('WAIT_GO_ON')
        return None

    def navigation_result(self, status, *, simulated):
        if self.state != 'WAIT_ARRIVAL':
            return None
        self.emit('navigation_result', status=status, simulated=simulated, station='collaborative_robot')
        if status != 'success':
            self.transition('NAVIGATION_FAILED')
            return None
        self.transition('ARRIVAL')
        return 'arrival'


def run(debug, *, flow_factory=TourFlow, navigator=None, assets=ASSETS,
        script=None, log_path=None, validate=validate_assets):
    import numpy as np
    import wake
    from asr_live import PhraseEngine

    validate()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with (log_path or ROOT / 'tour-demo.log').open('a', encoding='utf-8') as logfile:
        def emit(event, **fields):
            line = json.dumps(dict(event=event, time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), **fields), ensure_ascii=False)
            print(line, flush=True)
            logfile.write(line + '\n')
            logfile.flush()

        class TextEngine(PhraseEngine):
            def recognize(self, samples):
                # Return text only. The main thread decides which commands the current state accepts.
                return self.detector.transcribe(np.clip(samples * 32768, -32768, 32767).astype(np.int16))

        with Path('/home/nvidia/robot_wakeup/.wake.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            engine = TextEngine()
            flow = flow_factory(engine.detector.matcher, emit)
            streams = engine.create_streams(wake.MIC_CHANNELS)
            rec = response = selector = None
            errors = deque(maxlen=8)
            hold_until = 0.0
            paused = False
            last_health = last_frame = time.monotonic()
            ready = False
            response_deadline = 0.0

            def start_reply(label):
                nonlocal response, response_deadline, streams, paused
                streams = engine.create_streams(wake.MIC_CHANNELS)
                paused = True
                if label.startswith('nav:'):
                    if navigator is None:
                        raise RuntimeError('No navigation adapter configured')
                    navigator.start(label[4:])
                    emit('navigation_started', point=label[4:], simulated=navigator.simulated)
                    return
                response = subprocess.Popen([sys.executable, str(script or Path(__file__).resolve()), '--play', label], start_new_session=True)
                response_deadline = time.monotonic() + audio_info(assets / (label + '.wav')) + 15
                emit('playback_started', label=label)

            try:
                if navigator is not None:
                    navigator.open()
                rec = subprocess.Popen(['arecord', '-q', '-D', 'hw:AIUIUSBMC,0', '-t', 'raw',
                    '-f', 'S16_LE', '-r', '16000', '-c', '8', '--buffer-time=200000'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                def drain():
                    for line in iter(rec.stderr.readline, b''):
                        errors.append(line.decode(errors='replace').strip())
                threading.Thread(target=drain, daemon=True).start()
                selector = selectors.DefaultSelector()
                selector.register(rec.stdout, selectors.EVENT_READ)
                buffer = bytearray()
                while not stop.is_set():
                    now = time.monotonic()
                    if navigator is not None:
                        result = navigator.poll()
                        if result is not None:
                            emit('navigation_result', **result)
                            label = flow.navigation_done(result)
                            hold_until = now + POST_PLAYBACK_ECHO_GUARD_SECONDS
                            if label:
                                start_reply(label)
                    if rec.poll() is not None:
                        raise RuntimeError('Capture stopped: ' + '; '.join(errors))
                    if response is not None:
                        code = response.poll()
                        if code is not None:
                            response = None
                            if code:
                                raise RuntimeError('Playback failed, exit ' + str(code))
                            emit('playback_finished')
                            label = flow.playback_done()
                            hold_until = now + POST_PLAYBACK_ECHO_GUARD_SECONDS
                            if label:
                                start_reply(label)
                        elif now > response_deadline:
                            raise RuntimeError('Playback timeout')
                    if not selector.select(timeout=.25):
                        if now - last_frame > 3:
                            raise RuntimeError('No microphone data for 3 seconds')
                        continue
                    chunk = os.read(rec.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError('Microphone EOF')
                    buffer.extend(chunk)
                    while len(buffer) >= 5120 and not stop.is_set():
                        frame = np.frombuffer(bytes(buffer[:5120]), dtype='<i2').reshape(-1, 8).astype(np.float32)
                        del buffer[:5120]
                        now = last_frame = time.monotonic()
                        if not ready:
                            ready = True
                            emit('ready', state=flow.state, navigation=(
                                'LIVE_NAVIGATION' if navigator is not None and not navigator.simulated
                                else 'MOCK_SUCCESS_NO_MOVEMENT'), mic_channels=list(wake.MIC_CHANNELS))
                        reference = float(np.sqrt(np.mean(frame[:, 6:8] ** 2)))
                        if response is not None or (navigator is not None and navigator.busy) or reference > 60 or wake.playback_busy():
                            hold_until = now + POST_PLAYBACK_ECHO_GUARD_SECONDS
                        busy = response is not None or now < hold_until
                        if busy:
                            if not paused:
                                streams = engine.create_streams(wake.MIC_CHANNELS)
                            paused = True
                        else:
                            if paused:
                                streams = engine.create_streams(wake.MIC_CHANNELS)
                                emit('listening', state=flow.state, command=(
                                    'Hello Porsche' if flow.state == 'WAIT_WAKE' else
                                    'go on' if flow.state.startswith('WAIT_GO_ON') else 'none'))
                            paused = False
                            for stream, channel in zip(streams, wake.MIC_CHANNELS):
                                stream.accept_waveform(16000, frame[:, channel] / 32768)
                            for stream in streams:
                                if not engine.is_ready(stream):
                                    continue
                                engine.decode_streams([stream])
                                text = engine.get_result(stream)
                                engine.reset_stream(stream)
                                before = flow.state
                                label = flow.heard(text)
                                fields = dict(state=before, accepted=label is not None,
                                              mic_channel=stream.channel)
                                if debug:
                                    fields['recognized'] = text
                                emit('speech_checked', **fields)
                                if label:
                                    start_reply(label)
                                    break  # same utterance on other mics must not advance twice
                        if now - last_health >= 10:
                            emit('health', state=flow.state, paused=paused,
                                 mic_channels=list(wake.MIC_CHANNELS),
                                 mic_rms=[round(float(np.sqrt(np.mean(frame[:, c] ** 2))), 1)
                                          for c in wake.MIC_CHANNELS],
                                 capture_errors=list(errors))
                            last_health = now
            finally:
                if navigator is not None:
                    navigator.close()
                for child in (response, rec):
                    if child is not None and child.poll() is None:
                        if child is response:
                            os.killpg(child.pid, signal.SIGTERM)
                        else:
                            child.terminate()
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            if child is response:
                                os.killpg(child.pid, signal.SIGKILL)
                            else:
                                child.kill()
                            child.wait()
                if selector is not None:
                    selector.close()
                engine.close()
                emit('stopped', state=flow.state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--prepare', action='store_true', help='Generate cached speech only; no recording/playback')
    group.add_argument('--check', action='store_true', help='Validate assets only; no recording/playback')
    group.add_argument('--play', choices=tuple(TEXTS), help=argparse.SUPPRESS)
    parser.add_argument('--debug', action='store_true', help='Include recognized text in console and tour-demo.log')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.check:
        validate_assets()
        print('Audio assets valid; no recording or playback performed.')
    elif args.play:
        play(args.play)
    else:
        run(args.debug)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('TOUR_DEMO_FAILED: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
