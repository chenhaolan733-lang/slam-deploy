#!/usr/bin/python3
"""Chassis read-only sensor_data subscriber; fresh telemetry only, to stdout."""
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from driver.msg import BatteriesData


class Reader(Node):
    def __init__(self):
        super().__init__('battery_monitor_readonly')
        self.last_stamp = None
        self.last_emit = -1e20
        self.create_subscription(BatteriesData, '/driver/battery/Data', self.receive, qos_profile_sensor_data)

    def receive(self, msg):
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds - stamp) / 1e9
        now = time.monotonic()
        if stamp <= 0 or stamp == self.last_stamp or not -2 <= age <= 5 or now - self.last_emit < 0.8:
            return
        self.last_stamp, self.last_emit = stamp, now
        rows = [{key: getattr(row, key) for key in
                 ('id', 'energy', 'health', 'is_in_place', 'is_charging', 'is_connected',
                  'error_code', 'voltage', 'current', 'temperature')} for row in msg.data]
        print(json.dumps({'schema': 1, 'event': 'battery', 'source_stamp_ns': stamp,
                          'sent_unix': time.time(),
                          'source_age_seconds': round(age, 3), 'batteries': rows}), flush=True)


if __name__ == '__main__':
    rclpy.init()
    node = Reader()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
