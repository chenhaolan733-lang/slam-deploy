#!/usr/bin/env python3
"""Scan tracked files only; never print matched credential contents."""
import ipaddress
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REJECT_SUFFIXES = {'.deb', '.wav', '.pcm', '.pcd', '.pgm', '.bag', '.db3', '.mcap', '.pem', '.key', '.log', '.pyc'}
PATTERNS = {
    'private key': r'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
    'GitHub credential': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})',
    'internal domain': r'\b[a-z0-9.-]+\.anyverse\.work\b',
    'device serial': r'\b(?:BCM[A-Z0-9]{10,}|LWJM[A-Z0-9]{10,})\b',
    'password argument': r'sshpass\s+-p\s+[^\s]+',
}
NETWORKS = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    problems = []
    count = 0
    for name in filter(None, paths):
        path = ROOT / name
        count += 1
        if path.suffix.lower() in REJECT_SUFFIXES or any(p in {'keys', '.runtime', 'data', 'logs', 'backups', 'models', '.venv', '__pycache__'} for p in path.relative_to(ROOT).parts):
            problems.append((name, 'excluded artifact'))
        if name in ('robotsdk/config/robot.yaml', 'robotsdk/config/hands-042.yaml'):
            problems.append((name, 'real hardware configuration'))
        if path.suffix == '.gpg':  # Public ROS signing key; manually verified, no secret packets.
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            problems.append((name, 'unexpected binary'))
            continue
        for kind, pattern in PATTERNS.items():
            if re.search(pattern, text):
                problems.append((name, kind))
        for address in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', text):
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            # This scanner's standard RFC1918 network definitions are not site addresses.
            if any(ip in net for net in NETWORKS) and not (name == 'tools/check_public.py' and any(ip == net.network_address for net in NETWORKS)):
                problems.append((name, 'internal address'))
    if problems:
        for name, kind in sorted(set(problems)):
            print(f'REVIEW_REQUIRED: {name}: {kind}')
        return 1
    print(f'PASS: {count} tracked files; no excluded artifacts or matched credential/internal-address patterns.')
    print('Pattern scanning supplements manual review; it is not a guarantee of complete secret detection.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
