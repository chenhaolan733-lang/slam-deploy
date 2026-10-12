#!/usr/bin/python3
"""Selected BrainCo hand control. Preview reads only; no arm/body connection."""
import argparse
import math
import sys
import time
from pathlib import Path

EXPECTED_SERIAL = {'left': 'SET_LEFT_HAND_SERIAL', 'right': 'SET_RIGHT_HAND_SERIAL'}
NAMES = ['thumb', 'thumb_aux', 'index', 'middle', 'ring', 'pinky']
FINGER_INDICES = (0, 2, 3, 4, 5)  # thumb main, index, middle, ring, pinky

def trajectory(start, target, speed, period=.05):
    # Position-only commands work with this classic-CAN firmware; its combined
    # position/speed and SDK move_joints paths were accepted but did not move.
    # speed = percentage points of full stroke per second, not rated motor speed.
    count=max(1,math.ceil(max(abs(x-y) for x,y in zip(start,target))/(speed*period)))
    for i in range(1,count+1):
        yield [a+(b-a)*i/count for a,b in zip(start,target)]

def plan(current, joint=None, target=None, delta=None, targets=None, speed=5., fingers=None):
    current = list(current)
    if len(current) != 6 or not all(math.isfinite(v) and 0 <= v <= 100 for v in current):
        raise ValueError('当前反馈必须是 6 个有效的 0～100% 数值')
    if not math.isfinite(speed) or not .1 <= speed <= 100:
        raise ValueError('--speed-percent 必须在 0.1～100 范围内')
    if sum(v is not None for v in (target, delta, targets, fingers)) != 1:
        raise ValueError('只选一种目标设置方式')
    if fingers is not None:
        if joint is not None or len(fingers) != 5:
            raise ValueError('五指模式按拇指、食指、中指、无名指、小指输入 5 个值，不要指定 --joint')
        result = current.copy()
        for index, value in zip(FINGER_INDICES, fingers):
            result[index] = value
        # Thumb auxiliary motor retains the measured position; do not invent a
        # thumb coupling law for hardware whose opposition mapping is untested.
    elif targets is not None:
        if joint is not None or len(targets) != 6:
            raise ValueError('整手模式使用 6 个目标，不要同时指定 --joint')
        result = list(targets)
    else:
        if joint is None or not 1 <= joint <= 6:
            raise ValueError('单轴模式需要 --joint 1～6')
        result = current.copy()
        result[joint-1] = target if target is not None else current[joint-1]+delta
    if not all(math.isfinite(v) and 0 <= v <= 100 for v in result):
        raise ValueError('目标闭合程度必须在 0～100%，0 张开，100 闭合；不是角度')
    return result

def arguments(argv=None):
    p=argparse.ArgumentParser(description='默认只预览；--execute 才运动。位置单位是闭合百分比，不是角度。')
    p.add_argument('--hand', choices=['left','right'], required=True)
    p.add_argument('--joint',type=int)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--target-percent',type=float)
    g.add_argument('--delta-percent',type=float)
    g.add_argument('--fingers-percent',nargs=5,type=float,
                   metavar=('THUMB','INDEX','MIDDLE','RING','PINKY'),
                   help='推荐：五指目标闭合百分比，按拇、食、中、无名、小；拇指辅助轴保持当前位置')
    g.add_argument('--targets-percent',nargs=6,type=float,help='高级兼容模式：6 个电机轴，第二项是拇指辅助轴')
    p.add_argument('--speed-percent',type=float,default=5.,help='每秒最多改变的闭合百分点，默认 5；不是电机额定速度比例')
    p.add_argument('--timeout',type=float,default=30.)
    p.add_argument('--execute',action='store_true')
    a=p.parse_args(argv)
    if not math.isfinite(a.timeout) or not 0 < a.timeout <= 300:
        p.error('--timeout 必须大于 0 且不超过 300 秒')
    # Validate relative deltas separately: current position is not known yet.
    if a.delta_percent is not None:
        if not math.isfinite(a.delta_percent) or abs(a.delta_percent)>100:
            p.error('--delta-percent 必须是 -100～100 的有限数值')
        plan([50.]*6,a.joint,delta=0.,speed=a.speed_percent)
    else:
        plan([0.]*6,a.joint,a.target_percent,None,a.targets_percent,a.speed_percent,
             fingers=a.fingers_percent)
    return a

def sample(h):
    s=h.read_state()
    age=(time.monotonic_ns()-s.timestamp_ns)/1e9
    q=list(s.positions); v=list(s.velocities)
    lo=list(h.capabilities.min_position); hi=list(h.capabilities.max_position)
    if not 0 <= age < .5 or any(len(x)!=6 for x in (q,v,lo,hi)):
        raise RuntimeError('反馈过期或轴数错误')
    if not all(math.isfinite(x) for x in q+v+lo+hi) or any(b<=a for a,b in zip(lo,hi)):
        raise RuntimeError('反馈或限位数值无效')
    pos=[100*(x-a)/(b-a) for x,a,b in zip(q,lo,hi)]
    if any(x < 0 or x > 100 for x in pos):
        raise RuntimeError('反馈超出关节限位')
    return pos,v

def line(label, values):
    return label+' ['+', '.join(f'{x:.1f}' for x in values)+']'

def run(robot, a):
    h=robot.hand(a.hand+'_hand')
    attempted=False
    try:
        h.connect()
        h.refresh_identity()
        if h.info.serial_number != EXPECTED_SERIAL[a.hand]:
            raise RuntimeError('灵巧手序列号与已验设备不符，拒绝继续')
        if list(h.joint_names)!=NAMES:
            raise RuntimeError('SDK 轴顺序与已验设备不符')
        before,vel=sample(h)
        if max(abs(x) for x in vel)>.02:
            raise RuntimeError('手指尚在运动，拒绝继续')
        target=plan(before,a.joint,a.target_percent,a.delta_percent,a.targets_percent,a.speed_percent,
                    fingers=a.fingers_percent)
        def display(values):
            return [values[i] for i in FINGER_INDICES] if a.fingers_percent is not None else values
        order='，拇/食/中/无名/小' if a.fingers_percent is not None else ''
        print(line('运动前（闭合%'+order+'）：',display(before)),flush=True)
        print(line('运动后目标（闭合%'+order+'）：',display(target)),flush=True)
        if not a.execute: return
        if max(abs(x-y) for x,y in zip(before,target))<.1: return
        now,vel=sample(h)
        if max(abs(x-y) for x,y in zip(before,now))>1 or max(abs(x) for x in vel)>.02:
            raise RuntimeError('预览后位置改变或手指未停稳，请重新运行')
        attempted=True
        h.enable()
        deadline=time.monotonic()+a.timeout
        for waypoint in trajectory(before,target,a.speed_percent):
            if time.monotonic()>=deadline:
                raise RuntimeError('运动超时；可增大 --timeout，不会自动提高速度')
            now,vel=sample(h)
            if any(abs(x-old)>2 for x,old,goal in zip(now,before,target) if abs(goal-old)<.01):
                raise RuntimeError('非目标轴发生异常变化，停止')
            # Do not batch catch-up commands after a delay: maintain the rate bound.
            time.sleep(.05)
            h.set_positions_normalized([x/100 for x in waypoint])
        stable=None
        while time.monotonic()<deadline:
            now,vel=sample(h)
            if all(abs(x-y)<=1.5 for x,y in zip(now,target)) and max(abs(x) for x in vel)<.02:
                stable=time.monotonic() if stable is None else stable
                if time.monotonic()-stable>=.4:
                    print(line('运动后实测（闭合%'+order+'）：',display(now)),flush=True)
                    return
            else: stable=None
            time.sleep(.05)
        raise RuntimeError('未在超时前确认到位；已尝试停止，不代表动作成功')
    finally:
        errors=[]
        if attempted:
            for action in (h.stop,h.disable):
                try: action()
                except Exception as e: errors.append(str(e))
        try: robot.shutdown()
        except Exception as e: errors.append(str(e))
        if errors: raise RuntimeError('停止/下使能/断开异常，请现场检查：'+'; '.join(errors))
        if attempted: print('已调用停止、下使能并断开。',flush=True)

def main():
    a=arguments()
    import fcntl
    import signal
    def interrupt(*_): raise KeyboardInterrupt()
    for sig in (signal.SIGTERM,signal.SIGHUP): signal.signal(sig,interrupt)
    with open('/tmp/robotsdk-driver.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from anyverse.robot import Robot
        run(Robot.load(str(Path(__file__).resolve().parent/'config/hands-042.yaml')),a)

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('已中断，已尝试清理。',file=sys.stderr); sys.exit(130)
    except Exception as e: print('HAND_STEP_FAILED: '+str(e),file=sys.stderr); sys.exit(1)
