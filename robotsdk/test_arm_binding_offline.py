"""Test the installed binding with a disconnected loopback-only virtual config.

Never connect or enable; no real robot endpoint is configured.
"""
import unittest
from anyverse.robot import Robot

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.robot=Robot.load_from_string('''
robot: offline-binding-test
devices:
  left_arm:
    profile: joint_group
    driver: marvin
    endpoint: 127.0.0.1
    side: left
    joints: 7
''')
        self.arm=self.robot.joint_group('left_arm')

    def tearDown(self):
        self.robot.shutdown()

    def test_original_dict_is_rejected_by_python_binding(self):
        with self.assertRaises(Exception) as caught:
            self.arm.move_joints({'indices':[2],'positions':[0.]},blocking=False)
        self.assertIn("unknown joint name 'indices'",str(caught.exception))

    def test_named_scalar_dict_passes_binding_but_unconnected_robot_cannot_move(self):
        self.assertEqual(self.arm.joint_names[2],'upperarm_roll')
        with self.assertRaises(Exception) as caught:
            self.arm.move_joints({'upperarm_roll':0.},velocity_scale=.05,
                                 acceleration_scale=.01,blocking=False,timeout=120.)
        print('Binding accepted name/scalar; offline guard:',type(caught.exception).__name__,str(caught.exception))
        self.assertIn(type(caught.exception).__name__,('NotConnectedError','NotEnabledError'))

if __name__=='__main__':unittest.main()
