import io
import math
import time
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
from arm_step import parse_args, run_session

NAMES={'head':['neck_yaw','head_pitch'],
       'waist':['waist_yaw','waist_pitch_upper','waist_pitch_mid','waist_pitch_lower']}

class BodyTests(unittest.TestCase):
    def setup_group(self, group, joint=1, execute=False):
        self.device=Mock()
        self.robot=Mock()
        self.robot.joint_group.return_value=self.device
        self.device.joint_names=NAMES[group]
        n=len(NAMES[group])
        self.positions=[0.]*n
        self.device.capabilities=SimpleNamespace(min_position=[-1.]*n,max_position=[1.]*n)
        self.device.read_state.side_effect=lambda:SimpleNamespace(
            positions=self.positions.copy(),velocities=[0.]*n,timestamp_ns=time.monotonic_ns())
        self.args=parse_args(['--joint',str(joint),'--target-deg','-1'],group)
        self.args.execute=execute
        def move(targets, **kwargs):
            self.assertEqual(targets,{NAMES[group][joint-1]:math.radians(-1)})
            self.assertEqual(kwargs['velocity_scale'],.05)
            self.positions[joint-1]=targets[NAMES[group][joint-1]]
        self.device.move_joints.side_effect=move

    def test_previews_exactly_two_lines_without_enable_or_disable(self):
        for group in NAMES:
            with self.subTest(group=group):
                self.setup_group(group)
                out=io.StringIO()
                with redirect_stdout(out):run_session(self.robot,self.args)
                self.assertEqual(len(out.getvalue().splitlines()),2)
                self.robot.joint_group.assert_called_once_with(group)
                self.device.enable.assert_not_called()
                self.device.disable.assert_not_called()
                self.device.move_joints.assert_not_called()
                self.robot.shutdown.assert_called_once()

    def test_every_axis_uses_real_name_and_disables(self):
        for group,names in NAMES.items():
            for joint in range(1,len(names)+1):
                with self.subTest(group=group,joint=joint):
                    self.setup_group(group,joint,True)
                    with redirect_stdout(io.StringIO()),patch('builtins.input',side_effect=AssertionError('no prompt')):
                        run_session(self.robot,self.args)
                    self.device.enable.assert_called_once()
                    self.device.stop.assert_called_once()
                    self.device.disable.assert_called_once()
                    self.robot.shutdown.assert_called_once()

    def test_invalid_axis_before_connect(self):
        for group in NAMES:
            for joint in (0,len(NAMES[group])+1):
                with self.assertRaises(ValueError):parse_args(['--joint',str(joint),'--target-deg','0'],group)

    def test_hardware_limit_is_enforced(self):
        self.setup_group('waist',4,True)
        self.device.capabilities.max_position[3]=0.
        self.args.target_deg=1.
        with self.assertRaisesRegex(ValueError,'限位'):run_session(self.robot,self.args)
        self.device.enable.assert_not_called()

    def test_failure_and_interrupt_disable_both_groups(self):
        for group in NAMES:
            for failure in (RuntimeError('failed'),KeyboardInterrupt()):
                self.setup_group(group,1,True)
                self.device.move_joints.side_effect=failure
                with redirect_stdout(io.StringIO()),self.assertRaises(type(failure)):
                    run_session(self.robot,self.args)
                self.device.disable.assert_called_once()
                self.robot.shutdown.assert_called_once()

    def test_stop_failure_still_attempts_disable(self):
        self.setup_group('waist',1,True)
        self.device.move_joints.side_effect=RuntimeError('move failed')
        self.device.stop.side_effect=RuntimeError('stop failed')
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'未确认'):
            run_session(self.robot,self.args)
        self.device.disable.assert_called_once()
        self.robot.shutdown.assert_called_once()

    def test_disable_failure_is_not_reported_as_success(self):
        self.setup_group('head',1,True)
        self.device.move_joints.side_effect=RuntimeError('move failed')
        self.device.disable.side_effect=RuntimeError('disable failed')
        out=io.StringIO()
        with redirect_stdout(out),self.assertRaisesRegex(RuntimeError,'disable failed'):
            run_session(self.robot,self.args)
        self.assertNotIn('已停止、下使能并断开',out.getvalue())
        self.robot.shutdown.assert_called_once()

if __name__=='__main__':unittest.main()
