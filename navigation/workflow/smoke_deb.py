#!/usr/bin/env python3
"""Exercise installed deb tools on disposable maps, without ROS/hardware nodes."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image
import yaml
from e_slam_bringup.edit_occupancy_map import MapDocument

with tempfile.TemporaryDirectory(prefix='navmap-deb-smoke-') as temporary:
    root = Path(temporary)
    spec = importlib.util.spec_from_file_location('packaged_mapping', '/opt/ros/jazzy/share/fast_lio/launch/mapping.launch.py')
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    pcd_parameters, grid_parameters = launch._named_map_overrides('smoke', {'occupancy_builder': {'output_directory': str(root / 'raw_grid')}})
    directory = root / 'saved/smoke'
    assert pcd_parameters['pcd_save.output_path'] == str(directory / 'smoke.pcd')
    assert grid_parameters['occupancy_builder.output_directory'] == str(directory)
    pcd = directory / 'smoke.pcd'
    points = [f'{x * 0.1} {y * 0.1} 0.0' for x in range(10) for y in range(10)]
    pcd.write_text('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 100\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 100\nDATA ascii\n' + '\n'.join(points) + '\n')
    out = directory / 'smoke_loc.pcd'
    subprocess.run(['ros2', 'run', 'fast_lio', 'filter_saved_pcd', str(pcd), str(out), '0.05'], check=True)
    assert out.stat().st_size > 0
    Image.new('L', (20, 20), 254).save(directory / 'smoke.pgm')
    grid = directory / 'smoke.yaml'
    grid.write_text(yaml.safe_dump({'image': 'smoke.pgm', 'resolution': 0.05, 'origin': [0.0, 0.0, 0.0], 'negate': 0, 'occupied_thresh': 0.65, 'free_thresh': 0.196}))
    # Read/export through installed editor class (no listening port).
    document = MapDocument(grid)
    print('EDITOR_CLASS_OK', document.width, document.height)
    exported = document.export({'map_id': document.map_id, 'pixels': base64.b64encode(document.pixels).decode()}, directory / 'edited')
    grid = Path(exported['yaml'])
    print('EDITOR_EXPORT_OK', grid.name)
    dst = root / 'active'
    subprocess.run(['ros2', 'run', 'e_slam_bringup', 'deploy_navigation_maps', '--pcd', str(out), '--grid', str(grid), '--destination', str(dst)], check=True)
    assert (dst / 'scans_loc.pcd').read_bytes() == out.read_bytes()
    assert (dst / 'scans_occ/scans_occ.pgm').read_bytes() == (directory / 'smoke.pgm').read_bytes()
    subprocess.run(['ros2', 'run', 'e_slam_bringup', 'deploy_navigation_maps', '--pcd', str(out), '--grid', str(grid), '--destination', str(dst)], check=True)
    assert list((root / 'backups').glob('active_*'))
    print('DEB_SMOKE_OK: named paths, PCD filter, editor load, paired deploy, backup; temporary data only.')
