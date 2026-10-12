"""Real-model synthetic fixture regression; no speaker/capture/ROS used."""
from pathlib import Path
import time
import unittest
import wave
import numpy as np
from hello_test import HelloEngine, CHANNELS


class EngineTests(unittest.TestCase):
    def test_repeatable_four_mic_streams(self):
        with wave.open(str(Path(__file__).parent/'hello_fixture_16k.wav'), 'rb') as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)/32768
        samples = np.concatenate([np.zeros(8000, np.float32), samples, np.zeros(24000, np.float32)])
        engine = HelloEngine(debug=True)
        try:
            for attempt in range(2):
                streams = engine.create_streams(CHANNELS)
                for stream in streams:
                    stream.accept_waveform(16000, samples)
                deadline = time.monotonic()+15
                hits = []
                while time.monotonic() < deadline:
                    ready = [s for s in streams if engine.is_ready(s)]
                    engine.decode_streams(ready)
                    hits += [s.channel for s in ready if engine.get_result(s) == 'HELLO']
                    if not engine.pending:
                        break
                    time.sleep(0.02)
                self.assertEqual(sorted(hits), list(CHANNELS), f'attempt={attempt}, hits={hits}')
                old = streams
                engine.create_streams(CHANNELS)
                self.assertFalse(any(engine.is_ready(s) for s in old))
        finally:
            engine.close()


if __name__ == '__main__':
    unittest.main()
