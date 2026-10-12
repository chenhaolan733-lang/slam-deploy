import math
import unittest
import io
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
from arm_step import make_plan, parse_args, run_session

class PlanTests(unittest.TestCase):
    def plan(self,**kw):
        return make_plan([0,0,0,math.radians(-3.9),0,0,0],[-math.pi]*7,[math.pi]*7,4,**kw)
    def test_toward_one_degree(self):
        self.assertAlmostEqual(self.plan(toward=0)['target_deg'],-2.9)
    def test_small_remaining_does_not_overshoot(self):
        self.assertAlmostEqual(self.plan(toward=-3.5)['target_deg'],-3.5)
    def test_percent(self):
        self.assertEqual(self.plan(delta=1,speed_percent=2)['velocity_scale'],.02)
    def test_default_slow(self):
        self.assertEqual(self.plan(delta=1)['velocity_scale'],.05)
    def test_negative_delta(self):
        self.assertAlmostEqual(self.plan(delta=-1)['target_deg'],-4.9)
    def test_large_target_allowed_within_hardware_limit(self):
        self.assertAlmostEqual(self.plan(target=90)['target_deg'],90)
    def test_nan_refused(self):
        with self.assertRaises(ValueError):self.plan(delta=float('nan'))
    def test_overspeed_refused(self):
        with self.assertRaises(ValueError):self.plan(delta=1,speed_percent=101)
    def test_above_old_speed_ceiling_allowed(self):
        self.assertEqual(self.plan(delta=1,speed_percent=10)['velocity_scale'],.1)
    def test_above_old_step_ceiling_allowed(self):
        self.assertAlmostEqual(self.plan(toward=90,step=10)['target_deg'],6.1)
    def test_limit_refused(self):
        with self.assertRaises(ValueError):self.plan(toward=181)
    def test_invalid_joint(self):
        with self.assertRaises(ValueError):make_plan([0]*7,[-3]*7,[3]*7,0,delta=1)

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.arm=Mock()
        self.robot=Mock()
        self.robot.joint_group.return_value=self.arm
        self.arm.capabilities=SimpleNamespace(min_position=[-3]*7,max_position=[3]*7)
        self.arm.joint_names=['shoulder_yaw','shoulder_pitch','upperarm_roll','elbow_pitch','forearm_roll','wrist_pitch','wrist_yaw']
        self.positions=[0.]*7
        self.arm.read_state.side_effect=lambda:SimpleNamespace(
            positions=self.positions.copy(),velocities=[0.]*7,timestamp_ns=time.monotonic_ns())
        self.args=parse_args(['--joint','4','--target-deg','10'])
    def test_preview_exactly_two_lines_and_no_enable_or_move(self):
        out=io.StringIO()
        with redirect_stdout(out),patch('builtins.input',side_effect=AssertionError('no prompts')):
            run_session(self.robot,self.args)
        self.assertEqual(len(out.getvalue().splitlines()),2)
        self.assertIn('运动前',out.getvalue())
        self.assertIn('运动后目标',out.getvalue())
        self.arm.enable.assert_not_called()
        self.arm.move_joints.assert_not_called()
        self.robot.shutdown.assert_called_once()
    def test_execute_no_prompts_and_automatic_shutdown(self):
        self.args.execute=True
        def move(targets,**kw):
            self.assertEqual(set(targets),{'elbow_pitch'})
            for name,position in targets.items():
                self.assertIsInstance(position,float)
                self.positions[self.arm.joint_names.index(name)]=position
        self.arm.move_joints.side_effect=move
        with redirect_stdout(io.StringIO()),patch('builtins.input',side_effect=AssertionError('no prompts')):
            run_session(self.robot,self.args)
        self.arm.enable.assert_called_once()
        self.arm.stop.assert_called_once()
        self.robot.shutdown.assert_called_once()
        self.assertEqual(self.arm.move_joints.call_args.kwargs['velocity_scale'],.05)
        self.assertEqual(self.arm.move_joints.call_args.kwargs['timeout'],120.)
    def test_third_axis_uses_upperarm_roll_name(self):
        self.args.joint=3
        self.args.execute=True
        self.args.target_deg=90.
        def move(targets,**kw):
            self.assertEqual(targets,{'upperarm_roll':math.pi/2})
            self.positions[2]=targets['upperarm_roll']
        self.arm.move_joints.side_effect=move
        with redirect_stdout(io.StringIO()):run_session(self.robot,self.args)
        self.robot.shutdown.assert_called_once()
    def test_motion_failure_still_stops_and_disables(self):
        self.args.execute=True
        self.arm.move_joints.side_effect=RuntimeError('motion rejected')
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'motion rejected'):
            run_session(self.robot,self.args)
        self.arm.stop.assert_called_once()
        self.robot.shutdown.assert_called_once()
    def test_enable_failure_still_cleans_up(self):
        self.args.execute=True
        self.arm.enable.side_effect=RuntimeError('enable failed')
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'enable failed'):
            run_session(self.robot,self.args)
        self.arm.move_joints.assert_not_called()
        self.robot.shutdown.assert_called_once()
    def test_cleanup_failure_is_not_success(self):
        self.robot.shutdown.side_effect=RuntimeError('bus failed')
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'下使能未确认'):
            run_session(self.robot,self.args)
    def test_noop_does_not_enable(self):
        self.args.execute=True
        self.args.target_deg=0.
        with redirect_stdout(io.StringIO()):run_session(self.robot,self.args)
        self.arm.enable.assert_not_called()
    def test_stale_feedback_no_enable(self):
        self.arm.read_state.side_effect=lambda:SimpleNamespace(timestamp_ns=0)
        with self.assertRaisesRegex(RuntimeError,'反馈不新鲜'):run_session(self.robot,self.args)
        self.arm.enable.assert_not_called()
        self.robot.shutdown.assert_called_once()
    def test_keyboard_interrupt_still_stops_and_disables(self):
        self.args.execute=True
        self.arm.move_joints.side_effect=KeyboardInterrupt()
        with redirect_stdout(io.StringIO()),self.assertRaises(KeyboardInterrupt):run_session(self.robot,self.args)
        self.arm.stop.assert_called_once()
        self.robot.shutdown.assert_called_once()

if __name__=='__main__':unittest.main()
