"""Actual SDK binding tests. Never connect or enable any device."""
import unittest
from anyverse.robot import Robot

class BodyBindingTests(unittest.TestCase):
    def test_head_and_waist_named_targets(self):
        robot=Robot.load_from_string('''
robot: offline-body-binding-test
devices:
  head:
    profile: joint_group
    driver: eyou
    bus: can254
    joints: 2
  waist:
    profile: joint_group
    driver: tongchuan
    bus: ethercat0
    joints: 4
    max_velocity: "0.8,0.8,0.8,0.8"
''')
        try:
            for group in ('head','waist'):
                device=robot.joint_group(group)
                for name in device.joint_names:
                    with self.subTest(group=group,joint=name):
                        with self.assertRaises(Exception) as caught:
                            device.move_joints({name:0.},velocity_scale=.05,
                                acceleration_scale=.01,blocking=False,timeout=120.)
                        self.assertIn(type(caught.exception).__name__,('NotConnectedError','NotEnabledError'))
        finally:
            robot.shutdown()

if __name__=='__main__':unittest.main()
