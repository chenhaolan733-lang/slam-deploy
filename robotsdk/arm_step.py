#!/usr/bin/python3
"""Arm single/all-joint runner; head and waist remain single-joint. Preview by default."""
import argparse
import math
import sys
import time


def make_plan(current, lower, upper, joint, delta=None, target=None, toward=None,
              step=1., speed_percent=5., accel_percent=1.):
    values=list(current)
    if not 1 <= joint <= len(values):
        raise ValueError(f'轴号必须在 1～{len(values)} 内')
    if sum(x is not None for x in (delta,target,toward)) != 1:
        raise ValueError('必须选择一种角度设置方式')
    if not all(math.isfinite(x) for x in values+[step,speed_percent,accel_percent]+[x for x in (delta,target,toward) if x is not None]):
        raise ValueError('角度和速度必须是有限数值')
    if not 0.1 <= speed_percent <= 100 or not 0.1 <= accel_percent <= 100:
        raise ValueError('SDK 速度、加速度比例必须在 0.1～100% 范围内')
    if not 0 < step:
        raise ValueError('步长必须大于 0')
    i=joint-1
    now=math.degrees(values[i])
    desired=now+delta if delta is not None else target
    if toward is not None:
        desired=now+max(-step,min(step,toward-now))
    rad=math.radians(desired)
    if not lower[i] <= rad <= upper[i]:
        raise ValueError('目标超出该关节 SDK 限位')
    if toward is not None and not lower[i] <= math.radians(toward) <= upper[i]:
        raise ValueError('最终目标超出该关节 SDK 限位')
    return dict(index=i,current_deg=now,target_deg=desired,target_rad=rad,
                velocity_scale=speed_percent/100.,acceleration_scale=accel_percent/100.)


def fresh_state(arm):
    state=arm.read_state()
    age=(time.monotonic_ns()-state.timestamp_ns)/1e9
    if not 0 <= age < .5:
        raise RuntimeError(f'反馈不新鲜：{age:.3f} 秒，禁止继续')
    return state


def make_all_plan(current, lower, upper, targets, speed_percent=5., accel_percent=1.):
    if any(len(v) != 7 for v in (current, lower, upper, targets)):
        raise ValueError('整臂目标、反馈和 SDK 限位都必须包含 7 个轴')
    return [make_plan(current, lower, upper, i+1, target=float(value),
                      speed_percent=speed_percent, accel_percent=accel_percent)
            for i,value in enumerate(targets)]


def parse_args(argv=None, group='arm'):
    count={'arm':7,'head':2,'waist':4}[group]
    p=argparse.ArgumentParser(description='默认仅预览两行角度；--execute 直接运动，完成后自动下使能退出。')
    if group=='arm':
        p.add_argument('--arm',choices=['left','right'],default='left')
    p.add_argument('--joint',type=int,required=group!='arm',help=f'单轴模式的轴号 1～{count}')
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--delta-deg',type=float,help='相对当前位置增加多少度，可为负数')
    g.add_argument('--target-deg',type=float,help='绝对目标角度；必须在该关节限位内')
    g.add_argument('--toward-deg',type=float,help='朝此绝对角度靠近，每次只走 step-deg')
    p.set_defaults(targets_deg=None)
    if group=='arm':
        g.add_argument('--targets-deg',type=float,nargs=7,metavar='DEG',
                       help='整臂 7 轴绝对目标角度，按轴号 1～7 顺序，用空格分隔；不与 --joint 同用')
    p.add_argument('--step-deg',type=float,default=1.)
    p.add_argument('--speed-percent',type=float,default=5.,help='SDK 速度比例百分数，默认 5%%，非度/秒')
    p.add_argument('--accel-percent',type=float,default=1.,help='SDK 加速度比例百分数，默认 1%%')
    p.add_argument('--timeout',type=float,default=120.,help='运动反馈确认超时秒数，默认 120')
    p.add_argument('--execute',action='store_true',help='直接使能/运动，无输入确认；结束自动停止、下使能')
    args=p.parse_args(argv)
    args.group=args.arm+'_arm' if group=='arm' else group
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 1800:
        p.error('--timeout 必须大于 0 且不超过 1800 秒')
    # Validate input before any hardware connection.
    if args.targets_deg is not None:
        if args.joint is not None:
            p.error('--targets-deg 已指定全部 7 轴，不能同时使用 --joint')
        make_all_plan([0.]*count,[-math.inf]*count,[math.inf]*count,args.targets_deg,
                      args.speed_percent,args.accel_percent)
    else:
        if args.joint is None:
            p.error('单轴模式必须指定 --joint；整臂模式使用 --targets-deg')
        make_plan([0.]*count,[-math.inf]*count,[math.inf]*count,args.joint,
                  delta=0.,step=args.step_deg,speed_percent=args.speed_percent,accel_percent=args.accel_percent)
    return args


def degrees_line(label, positions):
    return label+' ['+', '.join(f'{math.degrees(float(v)):.3f}' for v in positions)+']'


def run_session(robot, args):
    arm=robot.joint_group(args.group)
    enable_attempted=False
    try:
        arm.connect()
        state=fresh_state(arm)
        if max(abs(float(v)) for v in state.velocities)>.02:
            raise RuntimeError('关节组尚未停稳，拒绝点动')
        original=[float(v) for v in state.positions]
        cap=arm.capabilities
        if args.targets_deg is not None:
            plans=make_all_plan(original,cap.min_position,cap.max_position,args.targets_deg,
                                args.speed_percent,args.accel_percent)
        else:
            plans=[make_plan(original,cap.min_position,cap.max_position,args.joint,
                             args.delta_deg,args.target_deg,args.toward_deg,args.step_deg,
                             args.speed_percent,args.accel_percent)]
        names=list(arm.joint_names)
        if len(names)!=len(original) or len(set(names))!=len(names):
            raise RuntimeError('SDK 关节名称与反馈数量不一致，禁止运动')
        indices={plan['index'] for plan in plans}
        expected=original.copy()
        for plan in plans:
            expected[plan['index']]=plan['target_rad']
        print(degrees_line('运动前（度）：',original),flush=True)
        print(degrees_line('运动后目标（度）：',expected),flush=True)
        if not args.execute:
            return
        if all(abs(plan['target_deg']-plan['current_deg'])<.02 for plan in plans):
            print('已经接近目标，不使能、不运动。'); return
        print(f'直接执行：速度比例 {args.speed_percent}%，加速度比例 {args.accel_percent}%；结束自动下使能。',flush=True)
        now=fresh_state(arm)
        if len(now.positions)!=len(original) or len(now.velocities)!=len(original):
            raise RuntimeError('SDK 反馈轴数变化，禁止运动')
        if max(abs(float(a)-b) for a,b in zip(now.positions,original))>math.radians(.2):
            raise RuntimeError('预览后姿态已改变，请重新读取并规划')
        if max(abs(float(v)) for v in now.velocities)>.02:
            raise RuntimeError('确认时关节组未停稳')
        enable_attempted=True
        arm.enable()
        # Python binding takes {joint_name: absolute_radians}; indices/positions
        # in the packaged docstring describe the C++ API, not this dict binding.
        # One named target dictionary for this arm, not seven sequential moves.
        arm.move_joints({names[p['index']]:p['target_rad'] for p in plans},
                        velocity_scale=plans[0]['velocity_scale'],acceleration_scale=plans[0]['acceleration_scale'],
                        blocking=False,timeout=args.timeout)
        deadline=time.monotonic()+args.timeout
        stable=None
        while time.monotonic()<deadline:
            now=fresh_state(arm)
            if len(now.positions)!=len(original) or len(now.velocities)!=len(original):
                raise RuntimeError('SDK 反馈轴数变化，停止并检查')
            for i,(a,b) in enumerate(zip(now.positions,original)):
                if i not in indices and abs(float(a)-b)>math.radians(1):
                    raise RuntimeError('非目标关节变化超过 1 度，停止并检查')
            if (all(abs(float(now.positions[p['index']])-p['target_rad'])<math.radians(.15) for p in plans)
                    and max(abs(float(v)) for v in now.velocities)<.02):
                stable=stable or time.monotonic()
                if time.monotonic()-stable>.5:
                    print(degrees_line('运动后实测（度）：',now.positions),flush=True)
                    break
            else:
                stable=None
            time.sleep(.05)
        else:
            raise RuntimeError(f'{args.timeout:g} 秒内未确认到达，停止并检查')
    finally:
        cleanup_error=None
        if enable_attempted:
            try:
                arm.stop()
            except Exception as exc:
                cleanup_error=exc
            # shutdown() only logs SDK failures. Explicit disable reports them.
            try:
                arm.disable()
            except Exception as exc:
                cleanup_error=exc
        try:
            robot.shutdown()
        except Exception as exc:
            cleanup_error=exc
        if cleanup_error is not None:
            raise RuntimeError('停止/下使能未确认，请现场检查，必要时使用实体急停：'+str(cleanup_error))
        if enable_attempted:
            print('已停止、下使能并断开。',flush=True)


def main(group='arm'):
    args=parse_args(group=group)
    import fcntl
    import signal
    def interrupted(signum,frame):
        raise KeyboardInterrupt(f'signal {signum}')
    for sig in (signal.SIGTERM,signal.SIGHUP):
        signal.signal(sig,interrupted)
    with open('/tmp/robotsdk-driver.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('ROS 驱动或其他点动程序正在占用；不要同时运行')
        from anyverse.robot import Robot
        run_session(Robot.load(),args)


def cli(group='arm'):
    try:
        main(group)
    except KeyboardInterrupt:
        print('已中断；已尝试停止并下使能。',file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(group.upper()+'_STEP_FAILED: '+str(exc),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':
    cli()
