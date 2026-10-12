#!/usr/bin/python3
"""Bounded eight-channel microphone statistics; no audio files retained."""
import argparse
import array
import fcntl
import json
import math
import subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=int,default=5,choices=range(1,16))
    a=p.parse_args()
    with Path('/home/nvidia/robot_wakeup/.wake.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        r=subprocess.run(['arecord','-q','-D','hw:AIUIUSBMC,0','-t','raw','-f','S16_LE','-r','16000','-c','8','-d',str(a.seconds)],capture_output=True,timeout=a.seconds+5,check=True)
    samples=array.array('h',r.stdout)
    if len(samples)%8 or len(samples)<16000*8: raise RuntimeError('Incomplete audio data')
    for c in range(8):
        x=samples[c::8]; n=len(x); mean=sum(x)/n
        rms=math.sqrt(sum(v*v for v in x)/n)
        print(json.dumps(dict(channel=c,frames=n,rms=round(rms,1),dc=round(mean,1),peak=max(abs(v) for v in x),clipped=sum(abs(v)>=32760 for v in x),role='physical_mic' if 2<=c<=5 else 'playback_reference' if c>=6 else 'module_output_unverified')))
if __name__=='__main__': main()
