"""Installed SDK dict-binding test; no connect/enable, loopback-only endpoints."""
import unittest
from anyverse.robot import Robot


class AllBindingTests(unittest.TestCase):
    def test_seven_named_targets_for_either_arm(self):
        for side in ('left','right'):
            with self.subTest(side=side):
                robot=Robot.load_from_string(f'''
robot: offline-all-arm-binding-test
devices:
  {side}_arm:
    profile: joint_group
    driver: marvin
    endpoint: 127.0.0.1
    side: {side}
    joints: 7
''')
                try:
                    arm=robot.joint_group(side+'_arm')
                    self.assertEqual(len(arm.joint_names),7)
                    targets={name:0. for name in arm.joint_names}
                    with self.assertRaises(Exception) as caught:
                        arm.move_joints(targets,velocity_scale=.05,acceleration_scale=.01,
                                        blocking=False,timeout=120.)
                    self.assertIn(type(caught.exception).__name__,('NotConnectedError','NotEnabledError'))
                finally:
                    robot.shutdown()


if __name__=='__main__':
    unittest.main()
