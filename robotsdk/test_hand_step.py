import contextlib
import io
import math
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import hand_step as hs

class Hand:
    joint_names=hs.NAMES
    capabilities=NS(min_position=[0.]*6,max_position=[1.]*6)
    info=NS(serial_number=hs.EXPECTED_SERIAL['left'])
    def __init__(self): self.q=[.4,.39,.02,.01,.02,.01]; self.calls=[]
    def connect(self): self.calls.append('connect')
    def refresh_identity(self): self.calls.append('identity')
    def read_state(self): return NS(positions=self.q,velocities=[0.]*6,timestamp_ns=time.monotonic_ns())
    def enable(self): self.calls.append('enable')
    def set_positions_normalized(self,q): self.calls.append(('move',q)); self.q=q
    def stop(self): self.calls.append('stop')
    def disable(self): self.calls.append('disable')
class Robot:
    def __init__(self): self.h=Hand()
    def hand(self,role): self.role=role; return self.h
    def shutdown(self): self.h.calls.append('shutdown')
class TestHand(unittest.TestCase):
    def args(self,*more): return hs.arguments(['--hand','left','--joint','3','--target-percent','5',*more])
    def test_plan_subset(self): self.assertEqual(hs.plan([10]*6,joint=3,target=20),[10,10,20,10,10,10])
    def test_plan_all(self): self.assertEqual(hs.plan([10]*6,targets=[5]*6),[5]*6)
    def test_invalid(self):
        for x in [-1,101,math.nan,math.inf]:
            with self.assertRaises(ValueError): hs.plan([10]*6,joint=1,target=x)
        for x in [0,101,math.nan]:
            with self.assertRaises(ValueError): hs.plan([10]*6,joint=1,target=10,speed=x)
    def test_right_selected(self):
        a=hs.arguments(['--hand','right','--targets-percent',*['0']*6])
        r=Robot(); r.h.info=NS(serial_number=hs.EXPECTED_SERIAL['right'])
        with contextlib.redirect_stdout(io.StringIO()): hs.run(r,a)
        self.assertEqual(r.role,'right_hand')
        self.assertNotIn('enable',r.h.calls)
    def test_preview_readonly(self):
        r=Robot(); out=io.StringIO()
        with contextlib.redirect_stdout(out): hs.run(r,self.args())
        self.assertEqual(len(out.getvalue().splitlines()),2)
        self.assertEqual(r.h.calls,['connect','identity','shutdown'])
    def test_execute_cleanup(self):
        r=Robot()
        with contextlib.redirect_stdout(io.StringIO()): hs.run(r,self.args('--execute'))
        self.assertEqual(r.h.calls[-2:],['disable','shutdown'])
        moves=[x for x in r.h.calls if isinstance(x,tuple)]
        self.assertAlmostEqual(moves[-1][1][2],.05)
        self.assertEqual(len(moves),12)
    def test_command_failure_cleanup(self):
        r=Robot()
        with patch.object(r.h,'set_positions_normalized',side_effect=RuntimeError('send failed')):
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError): hs.run(r,self.args('--execute'))
        self.assertEqual(r.h.calls[-3:],['stop','disable','shutdown'])
    def test_wrong_identity(self):
        r=Robot(); r.h.info=NS(serial_number='unexpected')
        with self.assertRaises(RuntimeError): hs.run(r,self.args('--execute'))
        self.assertNotIn('enable',r.h.calls)
    def test_stale(self):
        h=Hand()
        with patch.object(h,'read_state',return_value=NS(timestamp_ns=0,positions=h.q,velocities=[0]*6)):
            with self.assertRaises(RuntimeError): hs.sample(h)
    def test_nan_feedback(self):
        h=Hand(); h.q[0]=math.nan
        with self.assertRaises(RuntimeError): hs.sample(h)
    def test_noop_no_enable(self):
        r=Robot(); a=self.args('--execute'); a.target_percent=2
        with contextlib.redirect_stdout(io.StringIO()): hs.run(r,a)
        self.assertNotIn('enable',r.h.calls)
    def test_trajectory_rate(self):
        prev=[40.,39.,2.,1.,2.,1.]
        target=[40.,39.,5.,1.,2.,1.]
        for q in hs.trajectory(prev,target,5):
            self.assertLessEqual(max(abs(x-y) for x,y in zip(q,prev)),.250001)
            prev=q
        self.assertEqual(prev,target)
    def test_five_finger_order_and_aux_held(self):
        self.assertEqual(hs.plan([40,39,2,1,2,1],fingers=[10,20,30,40,50]),[10,39,20,30,40,50])
    def test_five_finger_invalid(self):
        for targets in ([1]*4,[1]*6,[-1]*5,[101]*5,[math.nan]*5):
            with self.subTest(targets=targets),self.assertRaises(ValueError):
                hs.plan([0]*6,fingers=targets)
        with self.assertRaises(ValueError): hs.plan([0]*6,joint=3,fingers=[0]*5)
        with self.assertRaises(ValueError): hs.plan([0]*6,targets=[0]*6,fingers=[0]*5)
    def test_five_finger_preview_both_hands_no_commands(self):
        for side in ('left','right'):
            a=hs.arguments(['--hand',side,'--fingers-percent','10','20','30','40','50'])
            r=Robot();r.h.info=NS(serial_number=hs.EXPECTED_SERIAL[side]);out=io.StringIO()
            with contextlib.redirect_stdout(out): hs.run(r,a)
            self.assertEqual(r.role,side+'_hand')
            self.assertEqual(r.h.calls,['connect','identity','shutdown'])
            lines=out.getvalue().splitlines()
            self.assertEqual(len(lines),2)
            self.assertIn('[10.0, 20.0, 30.0, 40.0, 50.0]',lines[1])
    def test_five_finger_execute_mock_aux_retained_each_step(self):
        a=hs.arguments(['--hand','left','--fingers-percent','41','3','2','3','2','--execute'])
        r=Robot()
        with contextlib.redirect_stdout(io.StringIO()): hs.run(r,a)
        commands=[x for x in r.h.calls if isinstance(x,tuple)]
        self.assertTrue(commands)
        for command in commands: self.assertEqual(command[1][1],.39)
        for actual,target in zip(commands[-1][1],[.41,.39,.03,.02,.03,.02]):
            self.assertAlmostEqual(actual,target)
        self.assertEqual(r.h.calls[-3:],['stop','disable','shutdown'])
if __name__=='__main__': unittest.main()
