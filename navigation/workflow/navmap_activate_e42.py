#!/usr/bin/python3
"""Root-owned fixed-scope helper: change only e_42 map_pcd/map_yaml, never start ROS."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import yaml

SITE = Path('/opt/ros/jazzy/share/e_slam_bringup/sites/e_42.yaml')
MAPS = Path('/kitt15_navi/src/slam/maps')
DST = MAPS / 'e_42'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def plain(path):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'Noncanonical or symlink path: ' + str(path))


def patched(text):
    before = yaml.safe_load(text)
    require(isinstance(before, dict), 'Invalid site YAML')
    active = Path(before['map_pcd']).parent
    known_backup = active.parent == MAPS / 'backups' and re.fullmatch(r'e_42_[A-Za-z0-9_]+', active.name)
    require(active == DST or known_backup, 'Site is not canonical e_42 or its backup')
    require(Path(before['map_pcd']) == active / 'scans_loc.pcd' and
            Path(before['map_yaml']) == active / 'scans_occ/scans_occ.yaml', 'Unexpected active map layout')
    for path in (SITE, active, Path(before['map_pcd']), Path(before['map_yaml']), DST):
        plain(path)
    expected = dict(before, map_pcd=str(DST/'scans_loc.pcd'), map_yaml=str(DST/'scans_occ/scans_occ.yaml'))
    result = text
    for key in ('map_pcd', 'map_yaml'):
        result, count = re.subn(r'^'+key+r':[^\n]*', key+': '+expected[key], result, flags=re.M)
        require(count == 1, 'Require one top-level ' + key)
    require(yaml.safe_load(result) == expected, 'Unexpected changes outside map paths')
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    require(argv in (['--check'], ['--apply']), 'Only --check / --apply are accepted; paths are fixed')
    text = SITE.read_text()
    result = patched(text)
    require(os.access(SITE.parent, os.W_OK), 'Cannot atomically update installed site')
    if argv == ['--check']:
        print('e_42 加载路径更新权限/格式检查通过（未修改配置）。')
        return
    for path in (DST/'scans_loc.pcd', DST/'scans_occ/scans_occ.yaml', DST/'scans_occ/scans_occ.pgm'):
        plain(path)
        require(path.is_file() and path.stat().st_size > 0, 'Canonical map is missing: ' + str(path))
    cfg = yaml.safe_load((DST/'scans_occ/scans_occ.yaml').read_text())
    require(cfg['image'] == 'scans_occ.pgm' and cfg['resolution'] > 0, 'Unexpected grid YAML')
    if result == text:
        print('加载路径已是标准 e_42 目录，无需改动。')
        return
    original_stat = SITE.stat()
    backup = SITE.with_name(SITE.name + '.navmap-backup-' + str(time.time_ns()))
    shutil.copy2(SITE, backup)
    fd, name = tempfile.mkstemp(prefix='.e_42.navmap-', dir=SITE.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, original_stat.st_mode & 0o777)
        os.chown(name, original_stat.st_uid, original_stat.st_gid)
        require(SITE.read_text() == text, 'Site changed during update; refusing overwrite')
        os.replace(name, SITE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('已更新实际加载路径；旧配置备份：' + str(backup))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('NAVMAP_SITE_FAILED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
