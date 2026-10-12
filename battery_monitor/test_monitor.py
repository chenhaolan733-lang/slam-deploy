"""Offline Linux integration tests: subprocess pipes and dummy player, no SSH/ROS/audio."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'posix', 'Linux process groups and flock required')
class Integration(unittest.TestCase):
    def case(self, steps, seconds, player=None):
        transport = '''import json,time
steps = ''' + repr(steps) + '''
for energy,charging,duration in steps:
 end=time.monotonic()+duration
 while time.monotonic()<end:
  print(json.dumps({'schema':1,'event':'battery','sent_unix':time.time(),'source_age_seconds':0.01,
   'batteries':[{'id':1,'energy':energy,'is_charging':charging,'is_in_place':True,'is_connected':True,'error_code':0}]}),flush=True)
  time.sleep(0.1)
time.sleep(30)
'''
        player = player or 'import time; print("DUMMY_PLAYER_STARTED",flush=True); time.sleep(30)'
        with tempfile.TemporaryDirectory() as tmp:
            code = ('import monitor as m; from pathlib import Path; '
                    f'm.RUNTIME=Path({tmp!r}); m.loop(0.6, '
                    f'{[sys.executable, "-u", "-c", transport]!r}, '
                    f'{[sys.executable, "-u", "-c", player]!r})')
            proc = subprocess.Popen([sys.executable, '-u', '-c', code],
                                    cwd=Path(__file__).resolve().parent,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                out, _ = proc.communicate(timeout=seconds)
                self.fail('monitor exited prematurely: ' + out)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    out, _ = proc.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, _ = proc.communicate(timeout=2)
                    self.fail('monitor failed graceful shutdown: ' + out)
            self.assertEqual(proc.returncode, 0, out)
            self.assertIn('"event": "stopped"', out)
            status = json.loads((Path(tmp)/'status.json').read_text())
            self.assertEqual(status['state'], 'NO_DATA')
        return out

    def test_charge_cancels_current_audio(self):
        out = self.case([(19, False, 1.2), (19, True, 5)], 3)
        self.assertIn('DUMMY_PLAYER_STARTED', out)
        self.assertIn('"event": "playback_cancelled"', out)
        self.assertEqual(out.count('"event": "playback_requested"'), 1, out)

    def test_stale_data_cancels_audio(self):
        out = self.case([(19, False, 0.4)], 6.5)
        self.assertIn('no fresh battery data for 5 seconds', out)
        self.assertIn('"event": "playback_cancelled"', out)

    def test_high_battery_never_plays(self):
        out = self.case([(34, False, 4)], 1.8)
        self.assertNotIn('"event": "playback_requested"', out)

    def test_completed_audio_repeats(self):
        out = self.case([(19, False, 5)], 2.4, 'print("DUMMY_DONE",flush=True)')
        self.assertGreaterEqual(out.count('"event": "playback_requested"'), 2, out)

    def test_busy_speaker_backs_off(self):
        out = self.case([(19, False, 5)], 1.5, 'import sys;sys.exit(75)')
        self.assertIn('"code": 75', out)
        self.assertEqual(out.count('"event": "playback_requested"'), 1, out)


if __name__ == '__main__':
    unittest.main()
