"""No hardware: argument validation, all-axis planning and mocked lifecycle."""
import io
import math
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch
from arm_step import parse_args, make_all_plan, run_session


class AllArmTests(unittest.TestCase):
    def setUp(self):
        self.names=['shoulder_yaw','shoulder_pitch','upperarm_roll','elbow_pitch',
                    'forearm_roll','wrist_pitch','wrist_yaw']
        self.positions=[0.]*7
        self.robot=Mock()
        self.arm=self.robot.joint_group.return_value
        self.arm.joint_names=self.names
        self.arm.capabilities=SimpleNamespace(min_position=[-math.pi]*7,max_position=[math.pi]*7)
        self.arm.read_state.side_effect=lambda:SimpleNamespace(
            positions=self.positions.copy(),velocities=[0.]*7,timestamp_ns=time.monotonic_ns())
        self.args=parse_args(['--arm','left','--targets-deg','10','-20','30','-40','50','-60','70'])
        self.output=io.StringIO()

    def run_it(self):
        with redirect_stdout(self.output),patch('builtins.input',side_effect=AssertionError('No prompt')):
            run_session(self.robot,self.args)

    def move_immediately(self,targets,**kwargs):
        self.assertEqual(list(targets),self.names)
        for name,target in targets.items():
            self.positions[self.names.index(name)]=target

    def test_preview_two_lines_without_enable(self):
        self.run_it()
        self.assertEqual(len(self.output.getvalue().splitlines()),2)
        self.assertIn('10.000, -20.000, 30.000, -40.000, 50.000, -60.000, 70.000',self.output.getvalue())
        self.arm.enable.assert_not_called()
        self.arm.disable.assert_not_called()
        self.arm.move_joints.assert_not_called()
        self.robot.shutdown.assert_called_once()

    def test_all_seven_targets_single_sdk_call(self):
        self.args.execute=True
        self.arm.move_joints.side_effect=self.move_immediately
        self.run_it()
        self.arm.move_joints.assert_called_once()
        targets=self.arm.move_joints.call_args.args[0]
        self.assertEqual(targets,dict(zip(self.names,map(math.radians,self.args.targets_deg))))
        self.assertEqual(self.arm.move_joints.call_args.kwargs['velocity_scale'],.05)
        self.assertEqual(self.arm.move_joints.call_args.kwargs['acceleration_scale'],.01)
        self.arm.stop.assert_called_once()
        self.arm.disable.assert_called_once()
        self.robot.shutdown.assert_called_once()
        self.assertIn('运动后实测',self.output.getvalue())

    def test_right_arm_only_and_custom_speed(self):
        self.args=parse_args(['--arm','right','--targets-deg','1','2','3','4','5','6','7',
                             '--speed-percent','8','--accel-percent','2','--execute'])
        self.arm.move_joints.side_effect=self.move_immediately
        self.run_it()
        self.robot.joint_group.assert_called_once_with('right_arm')
        self.assertEqual(self.arm.move_joints.call_args.kwargs['velocity_scale'],.08)
        self.assertEqual(self.arm.move_joints.call_args.kwargs['acceleration_scale'],.02)

    def test_bad_axis_count_arguments(self):
        for count in (0,6,8):
            with self.subTest(count=count),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(['--targets-deg']+['0']*count)

    def test_conflicting_modes(self):
        for suffix in (['--joint','1'],['--target-deg','0'],['--delta-deg','1'],['--toward-deg','2']):
            with self.subTest(suffix=suffix),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(['--targets-deg']+['0']*7+suffix)

    def test_single_axis_still_requires_joint(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            parse_args(['--target-deg','0'])

    def test_head_and_waist_do_not_accept_all_arm_option(self):
        for group in ('head','waist'):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(['--targets-deg']+['0']*7,group)

    def test_nonfinite_target_before_connect(self):
        for value in ('nan','inf'):
            with self.assertRaises(ValueError):
                parse_args(['--targets-deg',value]+['0']*6)

    def test_bad_speed_before_connect(self):
        for value in ('nan','0','101'):
            with self.assertRaises(ValueError):
                parse_args(['--targets-deg']+['0']*7+['--speed-percent',value])

    def test_any_joint_limit_refuses_whole_move(self):
        self.args.execute=True
        self.arm.capabilities.max_position[6]=math.radians(69)
        with self.assertRaisesRegex(ValueError,'限位'):
            self.run_it()
        self.arm.enable.assert_not_called()
        self.arm.move_joints.assert_not_called()
        self.robot.shutdown.assert_called_once()

    def test_feedback_and_limit_shape(self):
        for changed in range(4):
            arrays=[[0.]*7,[-3.]*7,[3.]*7,[0.]*7]
            arrays[changed]=arrays[changed][:-1]
            with self.assertRaises(ValueError):make_all_plan(*arrays)

    def test_already_at_all_targets_never_enables(self):
        self.args.execute=True
        self.positions=list(map(math.radians,self.args.targets_deg))
        self.run_it()
        self.arm.enable.assert_not_called()

    def test_one_axis_not_arrived_is_not_success(self):
        self.args.execute=True
        self.args.timeout=.1
        def incomplete(targets,**kwargs):
            self.move_immediately(targets,**kwargs)
            self.positions[6]=0.
        self.arm.move_joints.side_effect=incomplete
        with self.assertRaisesRegex(RuntimeError,'未确认到达'):self.run_it()
        self.assertNotIn('运动后实测',self.output.getvalue())
        self.arm.stop.assert_called_once()
        self.arm.disable.assert_called_once()

    def test_failure_or_interrupt_disables(self):
        for failure in (RuntimeError('rejected'),KeyboardInterrupt()):
            self.setUp()
            self.args.execute=True
            self.arm.move_joints.side_effect=failure
            with self.assertRaises(type(failure)):self.run_it()
            self.arm.stop.assert_called_once()
            self.arm.disable.assert_called_once()
            self.robot.shutdown.assert_called_once()

    def test_invalid_joint_names_no_enable(self):
        self.args.execute=True
        self.arm.joint_names=['same']*7
        with self.assertRaisesRegex(RuntimeError,'关节名称'):self.run_it()
        self.arm.enable.assert_not_called()


if __name__=='__main__':
    unittest.main()
