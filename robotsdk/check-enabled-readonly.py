import json
import time
import rclpy
from rclpy.qos import qos_profile_sensor_data
from diagnostic_msgs.msg import DiagnosticArray
from anyverse_robot_msgs.msg import JointGroupState
from sensor_msgs.msg import JointState

rclpy.init()
n=rclpy.create_node('sdk_readonly_enable_check')
data={};counts={};first={}
def save(k,m):
    data[k]=(time.monotonic(),m)
    counts[k]=counts.get(k,0)+1
    first.setdefault(k,m)
subs=[n.create_subscription(DiagnosticArray,'/diagnostics',lambda m:save('diagnostics',m),10),
      n.create_subscription(JointState,'/robotsdk/joint_states',lambda m:save('aggregate',m),qos_profile_sensor_data)]
for role in ['left_arm','right_arm','waist','head']:
    subs.append(n.create_subscription(JointGroupState,'/robotsdk/'+role+'/joint_group_state',lambda m,k=role:save(k,m),qos_profile_sensor_data))
end=time.monotonic()+8
while time.monotonic()<end:
    rclpy.spin_once(n,timeout_sec=.1)
out={'counts':counts,'age_seconds':{k:round(time.monotonic()-v[0],3) for k,v in data.items()}}
for k,(_,m) in data.items():
    if k=='diagnostics':
        out[k]=[{'name':s.name,'level':s.level[0] if isinstance(s.level,bytes) else int(s.level),'message':s.message,'values':{v.key:v.value for v in s.values}} for s in m.status]
    else:
        out[k]={'joints':len(m.name),'names':list(m.name),'position':list(m.position),'velocity':list(m.velocity),
                'max_change_rad':max((abs(a-b) for a,b in zip(m.position,first[k].position)),default=0)}
        if k!='aggregate':
            out[k]['monotonic_delta_ns']=m.monotonic_timestamp_ns-first[k].monotonic_timestamp_ns
print(json.dumps(out,indent=2))
n.destroy_node();rclpy.shutdown()
