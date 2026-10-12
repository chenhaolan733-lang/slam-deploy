#!/usr/bin/env python3
"""Print current browser URLs. Read-only HTTP probes; never starts a robot service."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parent
EDITOR = ROOT / 'runtime' / 'editor_link.json'


def reachable(url):
    try:
        with urlopen(url, timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def remap(url, ports):
    u = urlsplit(url)
    port = {6080: ports[0], 8765: ports[1], 8088: ports[2]}.get(u.port, u.port)
    return urlunsplit(('http', f'127.0.0.1:{port}', u.path, u.query, u.fragment))


def snapshot(ports=(6080, 8765, 8088)):
    result = []
    rviz = 'http://127.0.0.1:6080/vnc.html'
    result.append(('RViz', remap(rviz, ports) if reachable(rviz) else 'not started'))
    editor = None
    if EDITOR.is_file():
        try:
            editor = json.loads(EDITOR.read_text())['url']
            parsed = urlsplit(editor)
            if parsed.hostname != '127.0.0.1' or not reachable(editor):
                editor = None
        except (KeyError, ValueError, OSError):
            editor = None
    result.append(('Map editor', remap(editor, ports) if editor else 'not started by navmap edit; its own terminal prints the token URL'))
    speed = None
    token = Path.home() / '.config/kitt15/speed_panel.token'
    if token.is_file() and reachable('http://127.0.0.1:8088/'):
        value = token.read_text().strip()
        if value and all(c.isalnum() or c in '-_' for c in value):
            speed = 'http://127.0.0.1:8088/#token=' + value
    result.append(('Speed / Stop', remap(speed, ports) if speed else 'not started (normally starts with navigation)'))
    return result


def remember_editor(url):
    u = urlsplit(url)
    if u.hostname != '127.0.0.1' or u.scheme != 'http' or not u.query.startswith('token='):
        return
    EDITOR.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = EDITOR.with_name('editor_link.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'url': url}, stream)
    temp.replace(EDITOR)


def show(ports=(6080, 8765, 8088)):
    for name, url in snapshot(ports):
        print(f'[{name}]\n{url}\n', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--watch', action='store_true')
    p.add_argument('--local-ports', nargs=3, type=int, default=[6080, 8765, 8088])
    args = p.parse_args()
    if any(not 1 <= n <= 65535 for n in args.local_ports):
        p.error('Invalid local port')
    print('Navigation web links (Ctrl+click in terminal). Services are not started by this command.', flush=True)
    last = None
    while True:
        now = snapshot(args.local_ports)
        if now != last:
            for name, url in now:
                print(f'[{name}]\n{url}\n', flush=True)
            last = now
        if not args.watch:
            break
        time.sleep(2)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
