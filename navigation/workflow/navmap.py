#!/usr/bin/env python3
"""42 robot: packaged ROS tools + persistent named map workflow. No motion commands."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
SITE = Path('/opt/ros/jazzy/share/e_slam_bringup/sites/e_42.yaml')
CONFIG = Path('/opt/ros/jazzy/share/fast_lio/config/mid360.yaml')
WAYPOINTS = Path('/vla_infer/projects/kitt15_seatbelt/waypoints.yaml')
MAPS = Path('/kitt15_navi/src/slam/maps')
DESTINATION = MAPS / 'e_42'
SOURCE_SITE = Path('/kitt15_navi/src/bringup/e_slam_bringup/sites/e_42.yaml')
ACTIVATOR = Path('/usr/local/sbin/navmap-activate-e42')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def stamp():
    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def ros(tool, *args):
    run('ros2', 'run', 'e_slam_bringup', tool, *args)


def visualize(mode, dry=False):
    require(mode in ('mapping', 'navigation'), '未知 RViz 模式。')
    tool = 'visualize_' + mode
    require(Path('/opt/ros/jazzy/lib/e_slam_bringup', tool).is_file(),
            '缺少 deb 可视化入口；请安装 ros-jazzy-e-slam-bringup >= 2.0.3。')
    args = ['--restart', '--no-xterm', '--domain-id', '0', '--dds-profile',
            '/opt/ros/jazzy/share/e_slam_bringup/config/cyclonedds_chassis.xml']
    if dry:
        args.append('--dry-run')
    ros(tool, *args)
    if not dry:
        from web_links import show
        show()


def edit_map(grid, port):
    from web_links import remember_editor
    command = ['ros2', 'run', 'e_slam_bringup', 'edit_occupancy_map', '--map', str(grid), '--port', str(port)]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                             env={**os.environ, 'PYTHONUNBUFFERED': '1'})
    try:
        for line in child.stdout:
            print(line, end='', flush=True)
            match = re.search(r'http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+', line)
            if match:
                remember_editor(match.group())
        require(child.wait() == 0, '编辑器异常退出。')
    except KeyboardInterrupt:
        # Terminal Ctrl+C reaches the child as well; give HTTP server time to close.
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)
        raise


def idle():
    # Refuse, do not kill. Check actual executable argv, not our own arguments.
    names = {'fastlio_mapping', 'micro_nav_node', 'occupancy_grid_builder'}
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            argv = p.read_bytes().split(b'\0')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise RuntimeError('无法检查进程，拒绝换图；请由运维核实权限。')
        if argv and Path(os.fsdecode(argv[0])).name in names:
            raise RuntimeError('建图/定位/导航仍在运行；请先停稳、驻车并停止旧导航。建图必须 Ctrl+C 等保存完成。')


def packaged():
    require(SITE.is_file() and CONFIG.is_file(), '缺少本机 e_42 站点或 mid360 配置。')
    for package in ('fast_lio', 'e_slam_bringup', 'kitt15_micro_nav'):
        prefix = subprocess.check_output(['ros2', 'pkg', 'prefix', package], text=True).strip()
        require(prefix == '/opt/ros/jazzy', f'{package} 被源码 overlay 遮蔽：{prefix}')
    require('map_name' in (CONFIG.parent.parent / 'launch/mapping.launch.py').read_text(),
            'fast_lio deb 不支持 map_name，请安装配套版本。')


def valid_name(name):
    require(bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name)), '地图名用 1~80 位英文、数字、下划线、短横线；不要路径或扩展名。')
    return name


def paths(name):
    name = valid_name(name)
    directory = DATA / 'saved' / name
    require(not directory.is_symlink(), '地图目录不能是符号链接。')
    return directory, directory / f'{name}.pcd', directory / f'{name}.yaml'


def current():
    f = DATA / 'current.json'
    require(f.is_file(), '尚未选择地图；先 navmap new 地图名，或 navmap use 已有地图名。')
    return valid_name(json.loads(f.read_text())['name'])


def select(name):
    write_atomic(DATA / 'current.json', json.dumps({'name': valid_name(name)}, indent=2) + '\n')


def new(name):
    name = valid_name(name)
    directory, _, _ = paths(name)
    config = DATA / 'configs' / f'{name}.yaml'
    require(not directory.exists() and not config.exists(), '名称已存在；换名字，或 navmap use 该名字。')
    cfg = yaml.safe_load(CONFIG.read_text())
    params = cfg['/**']['ros__parameters']
    # Preserve the installed robot calibration; only change output locations.
    params['occupancy_builder']['output_directory'] = str(DATA / 'raw_grid')
    params['map_file_path'] = str(directory / f'{name}.pcd')
    write_atomic(config, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    select(name)
    print(f'已记住地图：{name}\n保存位置：{directory}\n尚未启动建图。')


def pair(name):
    directory, pcd, grid = paths(name)
    require(pcd.is_file() and pcd.stat().st_size > 0 and grid.is_file(), 'PCD/YAML 未完整保存；先等待建图正常退出。')
    with pcd.open('rb') as f:
        header = f.read(8192).split(b'\nDATA ', 1)[0]
    pts = re.search(rb'^POINTS\s+(\d+)', header, re.M)
    require(pts is not None and int(pts[1]) > 0, 'PCD 头无有效 POINTS。')
    cfg = yaml.safe_load(grid.read_text())
    image = (grid.parent / cfg['image']).resolve()
    require(image.is_relative_to(directory.resolve()) and image.is_file(), '栅格图片缺失或越出地图目录。')
    return directory, pcd, grid


def chosen_grid(name, original=False):
    directory, _, grid = pair(name)
    candidates = sorted((directory / 'edited').glob('edited_*/map.yaml'), key=lambda p: (p.stat().st_mtime_ns, str(p)))
    if original:
        selected = grid
    else:
        require(bool(candidates), '没有修图导出结果；先在网页点击导出。确定不用修图时加 --original。')
        selected = candidates[-1]
    require(selected.resolve().is_relative_to(directory.resolve()), '导出结果越出本次地图目录。')
    source = yaml.safe_load(grid.read_text())
    edited = yaml.safe_load(selected.read_text())
    for key in ('resolution', 'origin', 'negate', 'occupied_thresh', 'free_thresh'):
        require(source.get(key) == edited.get(key), f'修图前后 {key} 不一致；拒绝部署。')
    from PIL import Image
    image = (selected.parent / edited['image']).resolve()
    require(image.is_relative_to(directory.resolve()), '导出图片越出地图目录。')
    with Image.open(grid.parent / source['image']) as before, Image.open(image) as after:
        require(before.size == after.size and after.mode == 'L', '修图尺寸或图像模式变化。')
    return selected


def filtered(name):
    directory, pcd, _ = pair(name)
    out = directory / f'{name}_loc.pcd'
    meta = directory / 'filter.json'
    source_hash = digest(pcd)
    if out.exists():
        require(meta.is_file(), '已有滤波 PCD 但无本脚本记录；不要覆盖，改用新地图名。')
        record = json.loads(meta.read_text())
        require(record.get('source') == source_hash and record.get('output') == digest(out), '滤波输入/输出已改变；拒绝复用。')
    else:
        run('ros2', 'run', 'fast_lio', 'filter_saved_pcd', pcd, out, '0.05')
        require(out.is_file() and out.stat().st_size > 0, '滤波没有输出。')
        write_atomic(meta, json.dumps({'source': source_hash, 'output': digest(out)}, indent=2) + '\n')
    return out


def active_map():
    site = yaml.safe_load(SITE.read_text())
    pcd = Path(site['map_pcd'])
    grid = Path(site['map_yaml'])
    dst = pcd.parent
    require(pcd.is_absolute() and pcd.name == 'scans_loc.pcd' and grid == dst / 'scans_occ/scans_occ.yaml', '站点地图布局不匹配配套部署工具。')
    known_backup = dst.parent == MAPS / 'backups' and re.fullmatch(r'e_42_[A-Za-z0-9_]+', dst.name)
    require(dst == DESTINATION or known_backup, '当前地图既不是标准 e_42 目录，也不是本机 e_42 备份；拒绝猜测。')
    for path in (dst, pcd, grid):
        require(path.resolve() == path and not path.is_symlink(), '地图路径含符号链接或非规范路径，拒绝部署。')
    return dst


def destination():
    active_map()  # Validate the loading path, but never overwrite a backup.
    require(DESTINATION.resolve() == DESTINATION and not DESTINATION.is_symlink(), '标准地图目录不能是符号链接。')
    return DESTINATION


def standard_site(text):
    updated = text
    values = {'map_pcd': str(DESTINATION / 'scans_loc.pcd'),
              'map_yaml': str(DESTINATION / 'scans_occ/scans_occ.yaml')}
    for key, value in values.items():
        updated, count = re.subn(r'^' + key + r':[^\n]*', key + ': ' + value, updated, flags=re.M)
        require(count == 1, '站点配置必须各有一个顶层 map_pcd/map_yaml。')
    before, after = yaml.safe_load(text), yaml.safe_load(updated)
    expected = dict(before, **values)
    require(after == expected, '站点修改涉及地图路径以外字段，拒绝继续。')
    return updated


def prepare_site_updates():
    # This root-owned helper permits only these two fixed loading-path changes.
    # It cannot run arbitrary commands or accept arbitrary files from the user.
    require(ACTIVATOR.is_file(), '缺少 navmap-activate-e42 配套配置助手，请重新安装修复包。')
    run('sudo', '-n', ACTIVATOR, '--check')
    before = SITE.read_text()
    standard_site(before)
    source = None
    if SOURCE_SITE.exists():
        require(SOURCE_SITE.resolve() == SOURCE_SITE and not SOURCE_SITE.is_symlink(), '源码站点不能是符号链接。')
        require(os.access(SOURCE_SITE.parent, os.W_OK), '源码站点目录不可写，未改地图。')
        source = SOURCE_SITE.read_text()
        standard_site(source)
    return before, source


def activate_site(before, source):
    require(SITE.read_text() == before, '部署期间实际站点配置发生变化，未覆盖配置；请核对后重试。')
    if source is not None:
        require(SOURCE_SITE.read_text() == source, '部署期间源码站点配置发生变化，未覆盖配置。')
    run('sudo', '-n', ACTIVATOR, '--apply')
    require(yaml.safe_load(SITE.read_text()) == yaml.safe_load(standard_site(before)), '实际加载配置验证失败。')
    if source is not None:
        mode = SOURCE_SITE.stat().st_mode & 0o777
        write_atomic(SOURCE_SITE, standard_site(source))
        SOURCE_SITE.chmod(mode)


def deploy(name, original=False, dry=False):
    grid = chosen_grid(name, original)
    directory, pcd, _ = pair(name)
    dst = destination()
    active = active_map()
    print(f'地图：{name}\n原始 PCD：{pcd}\n栅格：{grid}\n导航数据目录：{dst}', flush=True)
    print(f'当前加载目录：{active}\n正式部署会备份旧地图/配置/点位，并将加载路径统一到：{dst}', flush=True)
    print(f'点云滤波：0.05 米 → {directory / (name + "_loc.pcd")}（已有结果仅在哈希一致时复用）', flush=True)
    print('栅格来源：' + ('原始栅格（已明确指定 --original）' if original else '最新修图导出；不会用原始栅格替代'), flush=True)
    if dry:
        print('仅预览：未滤波、未换图、未改点位、未启动导航。')
        return
    idle()
    before, source = prepare_site_updates()
    out = filtered(name)
    # Coordinates belong to the ACTIVE map, which may differ from canonical dst.
    new_coordinates = not (active / 'scans_loc.pcd').is_file() or digest(out) != digest(active / 'scans_loc.pcd')
    idle()  # Filtering may take time; refuse if navigation was started meanwhile.
    config_backup = DATA / 'deployment_backups' / stamp()
    config_backup.mkdir(parents=True, exist_ok=False)
    (config_backup / 'installed_e_42.yaml').write_text(before)
    if source is not None:
        (config_backup / 'source_e_42.yaml').write_text(source)
    if WAYPOINTS.exists():
        shutil.copy2(WAYPOINTS, config_backup / 'waypoints.yaml')
    write_atomic(config_backup / 'context.json', json.dumps({'previous_active': str(active),
                 'destination': str(dst), 'new_map': name}, indent=2) + '\n')
    print(f'配置/点位备份：{config_backup}', flush=True)
    backup = None
    if new_coordinates and WAYPOINTS.exists():
        backup = DATA / 'waypoint_backups' / f'waypoints_{stamp()}.yaml'
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WAYPOINTS, backup)
    # Fail closed: new coordinates must never retain old waypoint targets.
    if new_coordinates:
        write_atomic(WAYPOINTS, 'frame_id: map\n')
    had_destination = dst.exists()
    previous_pcd_hash = digest(dst / 'scans_loc.pcd') if (dst / 'scans_loc.pcd').is_file() else None
    try:
        ros('deploy_navigation_maps', '--pcd', out, '--grid', grid, '--destination', dst)
        require(digest(dst / 'scans_loc.pcd') == digest(out), '部署后点云校验失败。')
        grid_cfg = yaml.safe_load(grid.read_text())
        require(digest(dst / 'scans_occ/scans_occ.pgm') == digest(grid.parent / grid_cfg['image']), '部署后栅格校验失败。')
        deployed_cfg = yaml.safe_load((dst / 'scans_occ/scans_occ.yaml').read_text())
        require(deployed_cfg == dict(grid_cfg, image='scans_occ.pgm'), '部署后栅格YAML校验失败。')
        map_record = json.loads((dst / 'map_deployment.json').read_text())
        old_map = map_record.get('backup') if had_destination else None
        if had_destination:
            old_path = Path(old_map or '')
            require(old_path.is_absolute() and old_path.parent == MAPS / 'backups'
                    and old_path.resolve() == old_path and old_path.is_dir(), '原地图备份目录验证失败。')
            if previous_pcd_hash is not None:
                require(digest(old_path / 'scans_loc.pcd') == previous_pcd_hash, '原地图备份点云校验失败。')
        print(f'原标准目录地图备份：{old_map or "首次部署，无旧目录"}', flush=True)
        activate_site(before, source)
    except BaseException:
        print(f'部署未完整完成，未启动导航；不要直接运行导航。配置/点位备份：{config_backup}；旧地图备份见上方部署工具输出。', file=sys.stderr)
        raise
    write_atomic(DATA / 'last_deployment.json', json.dumps({
        'name': name, 'grid': str(grid), 'pcd': str(out), 'destination': str(dst),
        'waypoints_backup': str(backup) if backup else None, 'new_coordinates': new_coordinates,
        'previous_active': str(active), 'maps_backup': old_map, 'configuration_backup': str(config_backup),
        'time': stamp()}, indent=2) + '\n')
    if new_coordinates:
        print(f'新 PCD：旧点位已备份至 {backup}，点位已清空。定位正确后重新采点。')
    else:
        print('PCD 未变，仅更新栅格；保留现有点位，仍需核对通行区域。')
    print('部署完成；尚未启动定位/导航。请重新启动后核对 RViz。')


def status():
    try:
        name = current()
    except RuntimeError:
        print('尚未选择工作地图（现有导航地图未改动）。')
    else:
        directory, pcd, grid = paths(name)
        print(f'工作地图：{name}\n目录：{directory}\nPCD：{pcd} [{pcd.exists()}]\n栅格：{grid} [{grid.exists()}]')
    print('导航实际配置：' + str(SITE))
    site = yaml.safe_load(SITE.read_text())
    print('PCD：' + site['map_pcd'] + '\n栅格：' + site['map_yaml'])
    if (DATA / 'last_deployment.json').is_file():
        print('最近一次本工具部署：\n' + (DATA / 'last_deployment.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for action in ('new', 'use'):
        p = sub.add_parser(action)
        p.add_argument('name')
    for action in ('status', 'mapping', 'filter', 'links'):
        sub.add_parser(action)
    p = sub.add_parser('edit')
    p.add_argument('--port', type=int, default=8765)
    p = sub.add_parser('deploy')
    p.add_argument('--original', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('rviz')
    p.add_argument('mode', choices=['mapping', 'navigation'])
    p.add_argument('--dry-run', action='store_true', help='仅检查 deb 的 RViz/DDS 配置，不启动或重启桌面')
    args = parser.parse_args()
    if args.command == 'links':
        from web_links import show
        show()
        return
    packaged()
    if args.command == 'status':
        status()
        return
    if args.command == 'rviz':
        visualize(args.mode, args.dry_run)
        return
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / '.operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个建图/修图/换图命令正在运行；先完成该操作。')
        if args.command == 'new':
            new(args.name)
        elif args.command == 'use':
            pair(args.name)
            select(args.name)
            print('已选择工作地图：' + args.name + '（还未部署）')
        else:
            name = current()
            if args.command == 'mapping':
                idle()
                config = DATA / 'configs' / f'{name}.yaml'
                require(config.is_file(), '缺少该地图的建图配置。')
                require(not paths(name)[0].exists(), '同名地图目录已存在；请 new 新名字。')
                command = ['ros2', 'launch', 'fast_lio', 'mapping.launch.py', f'config_file:={config}',
                           f'map_name:={name}', 'use_rviz:=false', 'save_shutdown_timeout:=120.0']
                child = subprocess.Popen(command)
                try:
                    result = child.wait()
                except KeyboardInterrupt:
                    # Terminal Ctrl+C reaches launch too. Never kill it while saving.
                    print('\n正在等待地图保存；不要重复 Ctrl+C。', flush=True)
                    while child.poll() is None:
                        try:
                            child.wait()
                        except KeyboardInterrupt:
                            print('继续等待保存。', flush=True)
                    result = child.returncode
                require(result in (0, 130, -2), f'建图退出码 {result}，请检查日志；未自动部署。')
                pair(name)
                print('地图文件已保存：' + str(paths(name)[0]) + '；请检查地图质量。')
            elif args.command == 'edit':
                idle()
                edit_map(pair(name)[2], args.port)
            elif args.command == 'filter':
                idle()
                print(filtered(name))
            elif args.command == 'deploy':
                deploy(name, args.original, args.dry_run)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print('NAVMAP_FAILED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
