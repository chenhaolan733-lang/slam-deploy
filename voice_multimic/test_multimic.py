import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import asr_live as a
import wake

class VAD:
    def __init__(self,*args,**kw): self.items=[]
    def accept_waveform(self,samples): self.items.append(SimpleNamespace(samples=np.zeros(4800,np.float32)))
    def empty(self): return not self.items
    @property
    def front(self): return self.items[0]
    def pop(self): self.items.pop(0)
    def reset(self): self.items=[]
class Pool:
    def __init__(self): self.jobs=[]
    def submit(self,*_):
        f=Future(); self.jobs.append(f); return f
class MultiMicTest(unittest.TestCase):
    def setUp(self):
        self.patch=patch.object(a.sherpa_onnx,'VoiceActivityDetector',VAD); self.patch.start()
        self.addCleanup(self.patch.stop)
        self.e=a.PhraseEngine.__new__(a.PhraseEngine)
        self.e.vad_config=None; self.e.pending={}; self.e.generation=0
        self.e.pool=Pool()
    def feed(self,streams):
        for s in streams: s.accept_waveform(16000,np.zeros(512,np.float32))
    def test_physical_channels_only(self): self.assertEqual(wake.MIC_CHANNELS,(2,3,4,5))
    def test_all_four_can_submit(self):
        streams=self.e.create_streams(wake.MIC_CHANNELS); self.feed(streams)
        self.assertEqual(len(self.e.pending),4)
        self.assertEqual([s.channel for s in streams],[2,3,4,5])
    def test_one_job_per_channel(self):
        streams=self.e.create_streams(wake.MIC_CHANNELS)
        for _ in range(20): self.feed(streams)
        self.assertEqual(len(self.e.pool.jobs),4)
    def test_first_mic_miss_does_not_discard_others(self):
        streams=self.e.create_streams(wake.MIC_CHANNELS); self.feed(streams)
        for s,result in zip(streams,['','','HELLO_PORSCHE','']): self.e.pending[s].set_result(result)
        self.assertEqual(wake.decode(self.e,streams),['HELLO_PORSCHE'])
        self.assertEqual(len(self.e.pending),0)
    def test_boundary_discards_running_and_queued_results(self):
        old=self.e.create_streams(wake.MIC_CHANNELS); self.feed(old)
        running=self.e.pending[old[0]]; running.set_running_or_notify_cancel()
        queued=self.e.pending[old[1]]
        new=self.e.create_streams(wake.MIC_CHANNELS)
        running.set_result('HELLO_PORSCHE')
        self.assertTrue(queued.cancelled())
        self.assertEqual(wake.decode(self.e,old),[])
        self.feed(old); self.assertEqual(len(self.e.pending),0)
        self.feed(new); self.assertEqual(len(self.e.pending),4)
    def test_all_hit_group_can_be_consumed_once(self):
        streams=self.e.create_streams(wake.MIC_CHANNELS); self.feed(streams)
        for f in self.e.pending.values(): f.set_result('HELLO_PORSCHE')
        self.assertEqual(len(wake.decode(self.e,streams)),4)
        self.e.create_streams(wake.MIC_CHANNELS)
        self.assertEqual(wake.decode(self.e,streams),[])
    def test_single_stream_compatibility(self):
        s=self.e.create_stream(); self.feed([s]); self.e.pending[s].set_result('go on')
        self.e.decode_streams([s]); self.assertEqual(self.e.get_result(s),'go on')
        self.e.reset_stream(s); self.assertEqual(s.hit,'')
    def test_error_is_not_a_wake(self):
        s=self.e.create_stream(); self.feed([s]); self.e.pending[s].set_exception(RuntimeError('bad ASR'))
        with self.assertRaises(RuntimeError): self.e.decode_streams([s])
        self.assertEqual(s.hit,'')
if __name__=='__main__': unittest.main()
