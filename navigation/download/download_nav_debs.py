#!/usr/bin/env python3
"""Download one complete navigation deb release. Never installs or restarts anything."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

PACKAGES = (
    'ros-jazzy-livox-sdk2', 'ros-jazzy-livox-ros-driver2',
    'ros-jazzy-fast-lio', 'ros-jazzy-ndt-omp-ros2',
    'ros-jazzy-lidar-localization-ros2', 'ros-jazzy-move',
    'ros-jazzy-nav2-kitt15', 'ros-jazzy-kitt15-micro-nav',
    'ros-jazzy-e-slam-bringup',
)


class DownloadError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DownloadError('仓库返回重定向，拒绝跳转；请检查 --server 地址或仓库权限。')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def open_url(opener, url, timeout):
    try:
        return opener.open(Request(url, headers={'User-Agent': 'robot-nav-debs/1.0'}), timeout=timeout)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise DownloadError('仓库拒绝访问；当前脚本使用匿名只读下载，不在脚本中保存密码。') from exc
        raise DownloadError(f'仓库 HTTP 错误：{exc.code}') from exc


def resolve_release(opener, server, repository, version, arch, timeout=20):
    """Exact match + pagination. Resolve ALL packages before writing anything."""
    selected = []
    for name in PACKAGES:
        candidates = {}
        token = None
        seen = set()
        while True:
            query = dict(repository=repository, format='apt', name=name, version=version)
            if token:
                query['continuationToken'] = token
            with open_url(opener, server + '/service/rest/v1/search?' + urlencode(query), timeout) as response:
                payload = json.load(response)
            if not isinstance(payload.get('items'), list):
                raise DownloadError('Nexus 返回的搜索结果格式不正确。')
            for component in payload['items']:
                if (component.get('repository') != repository or component.get('format') != 'apt'
                        or component.get('name') != name or component.get('version') != version
                        or component.get('group') != arch):
                    continue
                filename = f'{name}_{version}_{arch}.deb'
                for asset in component.get('assets', []):
                    url = asset.get('downloadUrl', '')
                    parsed = urlsplit(url)
                    base = urlsplit(server)
                    path = unquote(parsed.path)
                    if Path(path).name != filename:
                        continue
                    if (parsed.scheme != base.scheme or parsed.netloc != base.netloc
                            or parsed.query or parsed.fragment or '..' in path.split('/')
                            or not path.startswith(base.path.rstrip('/') + '/repository/' + repository + '/')):
                        raise DownloadError(f'{name} 的下载地址不属于指定仓库，拒绝下载。')
                    digest = asset.get('checksum', {}).get('sha256', '')
                    size = asset.get('fileSize')
                    if not re.fullmatch('[a-fA-F0-9]{64}', digest) or not isinstance(size, int) or size <= 0:
                        raise DownloadError(f'{name} 缺少有效 SHA-256 或文件大小，拒绝下载。')
                    entry = dict(name=name, version=version, arch=arch, filename=filename,
                                 url=url, sha256=digest.lower(), size=size)
                    if url in candidates and candidates[url] != entry:
                        raise DownloadError(f'{name} 的仓库元数据冲突。')
                    candidates[url] = entry
            token = payload.get('continuationToken')
            if not token:
                break
            if token in seen or len(seen) >= 100:
                raise DownloadError('仓库分页异常，停止查询。')
            seen.add(token)
        if len(candidates) != 1:
            raise DownloadError(f'{name}: 找到 {len(candidates)} 个精确匹配，要求唯一的 {version}/{arch}；未开始下载。')
        selected.append(next(iter(candidates.values())))
    return selected


def verify_file(path, item):
    if path.is_symlink() or not path.is_file():
        raise DownloadError(f'{path.name} 不是普通文件。')
    if path.stat().st_size != item['size'] or sha256(path) != item['sha256']:
        raise DownloadError(f'{path.name} 大小或 SHA-256 不符；不会覆盖已有文件，请检查或换一个输出目录。')
    # Read package metadata only. dpkg-deb -f NEVER installs a package or runs maintainer scripts.
    result = subprocess.run(['dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture'],
                            check=True, capture_output=True, text=True, timeout=30)
    fields = dict(line.split(': ', 1) for line in result.stdout.splitlines() if ': ' in line)
    expected = {'Package': item['name'], 'Version': item['version'], 'Architecture': item['arch']}
    if any(fields.get(key) != value for key, value in expected.items()):
        raise DownloadError(f'{path.name} 的 deb 包名、版本或架构与仓库声明不符。')


def download_one(opener, directory, item, timeout=20, retries=3):
    destination = directory / item['filename']
    if destination.exists() or destination.is_symlink():
        verify_file(destination, item)
        return '已校验，跳过'
    fd, temporary = tempfile.mkstemp(prefix='.'+item['filename']+'.', suffix='.part', dir=directory)
    os.close(fd)
    part = Path(temporary)
    try:
        for attempt in range(retries):
            try:
                received = 0
                with open_url(opener, item['url'], timeout) as response, part.open('wb') as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        received += len(block)
                        if received > item['size']:
                            raise DownloadError('下载内容超出仓库声明的大小。')
                        output.write(block)
                verify_file(part, item)
                # Exclusive creation of the final filename, never overwrite an existing file.
                os.link(part, destination)
                return '下载并校验通过'
            except (URLError, TimeoutError, DownloadError) as exc:
                if attempt + 1 == retries:
                    raise DownloadError(f'{item["filename"]}: {exc}') from exc
                print(f'  第 {attempt+1} 次失败，重试……', flush=True)
                time.sleep(1)
    finally:
        part.unlink(missing_ok=True)


def write_metadata(directory, name, contents):
    fd, temporary = tempfile.mkstemp(prefix='.'+name+'.', dir=directory)
    path = Path(temporary)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(contents)
        path.replace(directory / name)
    finally:
        path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, help='精确版本，如 2.2.1-0noble；不会自动混用不同版本')
    parser.add_argument('--arch', choices=['arm64'], default='arm64')
    parser.add_argument('--server', required=True, help='Authorized Nexus base URL')
    parser.add_argument('--repository', required=True, help='APT repository name supplied by your administrator')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'downloads', help='下载根目录')
    parser.add_argument('--check', action='store_true', help='仅核对整套包是否齐全，不下载、不写文件')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+~_-]*', args.version):
        parser.error('版本只能包含字母、数字、点、加号、波浪号、下划线和减号')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.repository):
        parser.error('仓库名无效')
    server = args.server.rstrip('/')
    parsed = urlsplit(server)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('--server 必须是 Nexus 服务地址，不是带 #browse 的网页地址，也不能包含密码')
    # Internal LAN repository: avoid sending requests to machine-wide HTTP proxies.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    print(f'查询 {args.repository}: {args.version} / {args.arch}（9 个包）', flush=True)
    items = resolve_release(opener, server, args.repository, args.version, args.arch)
    for item in items:
        print(f'  {item["filename"]}  {item["size"]} bytes')
    print(f'整套齐全，总计 {sum(item["size"] for item in items)/1024/1024:.2f} MiB。', flush=True)
    if args.check:
        print('仅检查完成，未下载或安装。')
        return
    if sys.platform != 'linux' or shutil.which('dpkg-deb') is None:
        raise DownloadError('下载模式需在装有 Python3 和 dpkg-deb 的 Linux 机器人端执行；--check 可在其他电脑验证。')
    import fcntl
    directory = args.output.expanduser().resolve() / args.version / args.arch
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'.download.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DownloadError('同一版本目录已有下载任务，不能重复执行。') from exc
        required = sum(item['size'] for item in items if not (directory/item['filename']).exists())
        if shutil.disk_usage(directory).free < required + 16*1024*1024:
            raise DownloadError('磁盘剩余空间不足。')
        for i,item in enumerate(items,1):
            print(f'[{i}/9] {item["name"]}: {download_one(opener,directory,item)}', flush=True)
        for item in items:
            verify_file(directory/item['filename'], item)
        write_metadata(directory, 'SHA256SUMS', ''.join(f'{item["sha256"]}  {item["filename"]}\n' for item in items))
        manifest = dict(version=args.version, architecture=args.arch, repository=args.repository,
                        server=server, verified_at=datetime.now(timezone.utc).isoformat(), packages=items)
        write_metadata(directory, 'manifest.json', json.dumps(manifest,indent=2)+'\n')
    print(f'完成：9/9 个包校验通过。\n保存位置：{directory}\n仅下载，没有安装 deb、修改配置或重启服务。')


if __name__ == '__main__':
    try:
        main()
    except (DownloadError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('DOWNLOAD_FAILED: '+str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('已取消；已完成的包保留，下次执行会校验后跳过。', file=sys.stderr)
        sys.exit(130)
