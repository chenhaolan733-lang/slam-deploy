#!/usr/bin/env python3
"""Temporary files only; never starts ROS nodes or changes actual maps."""
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import patch
import yaml
from PIL import Image
import navmap as n


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='navmap-test-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data = root / 'data'
        self.maps = root / 'maps'
        self.dst = self.maps / 'e_42'
        self.site = root / 'site.yaml'
        self.source_site = root / 'source_site.yaml'
        self.site.write_text(yaml.safe_dump({'map_pcd': str(self.dst / 'scans_loc.pcd'),
                                           'map_yaml': str(self.dst / 'scans_occ/scans_occ.yaml'),
                                           'keep_setting': 42}))
        self.source_site.write_bytes(self.site.read_bytes())
        self.cfg = root / 'mid360.yaml'
        self.cfg.write_text(yaml.safe_dump({'/**': {'ros__parameters': {
            'occupancy_builder': {'output_directory': '/old/scans_occ'},
            'mapping': {'extrinsic_T': [1, 2, 3]}}}}))
        self.wp = root / 'waypoints.yaml'
        self.wp.write_text('frame_id: map\npoint_a: {x: 1, y: 2, yaw: 0}\n')
        for name, value in [('DATA', self.data), ('CONFIG', self.cfg), ('WAYPOINTS', self.wp),
                            ('MAPS', self.maps), ('DESTINATION', self.dst), ('SITE', self.site), ('SOURCE_SITE', self.source_site)]:
            p = patch.object(n, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, replacement in [('prepare_site_updates', self.prepare), ('activate_site', self.activate)]:
            p = patch.object(n, name, side_effect=replacement)
            p.start()
            self.addCleanup(p.stop)

    def prepare(self):
        return self.site.read_text(), self.source_site.read_text()

    def activate(self, before, source):
        self.site.write_text(n.standard_site(before))
        self.source_site.write_text(n.standard_site(source))

    def fake_deployer(self, tool, *args):
        self.assertEqual(tool, 'deploy_navigation_maps')
        opts = dict(zip(args[::2], args[1::2]))
        dst = Path(opts['--destination'])
        old = self.maps / 'backups' / ('e_42_' + n.stamp())
        old.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.rename(old)
        (dst / 'scans_occ').mkdir(parents=True)
        shutil.copy2(opts['--pcd'], dst / 'scans_loc.pcd')
        grid = Path(opts['--grid'])
        cfg = yaml.safe_load(grid.read_text())
        shutil.copy2(grid.parent / cfg['image'], dst / 'scans_occ/scans_occ.pgm')
        cfg['image'] = 'scans_occ.pgm'
        (dst / 'scans_occ/scans_occ.yaml').write_text(yaml.safe_dump(cfg))
        (dst / 'map_deployment.json').write_text(json.dumps({'backup': str(old)}))

    def bundle(self, name='hall'):
        n.new(name)
        directory, pcd, grid = n.paths(name)
        directory.mkdir(parents=True)
        pcd.write_text('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n')
        Image.new('L', (8, 8), 254).save(directory / f'{name}.pgm')
        cfg = {'image': f'{name}.pgm', 'resolution': 0.05, 'origin': [0.0, 0.0, 0.0],
               'negate': 0, 'occupied_thresh': 0.65, 'free_thresh': 0.196}
        grid.write_text(yaml.safe_dump(cfg))
        return directory, pcd, grid, cfg

    def test_new_persists_and_preserves_calibration(self):
        n.new('hall')
        self.assertEqual(n.current(), 'hall')
        cfg = yaml.safe_load((self.data / 'configs/hall.yaml').read_text())['/**']['ros__parameters']
        self.assertEqual(cfg['mapping']['extrinsic_T'], [1, 2, 3])
        self.assertEqual(Path(cfg['occupancy_builder']['output_directory']).parent, self.data)
        with self.assertRaises(RuntimeError):
            n.new('hall')
        with self.assertRaises(RuntimeError):
            n.new('../escape')

    def test_grid_requires_export_and_checks_metadata(self):
        directory, _, grid, cfg = self.bundle()
        with self.assertRaises(RuntimeError):
            n.chosen_grid('hall')
        self.assertEqual(n.chosen_grid('hall', True), grid)
        e = directory / 'edited/edited_1'
        e.mkdir(parents=True)
        Image.new('L', (8, 8), 254).save(e / 'map.pgm')
        cfg['image'] = 'map.pgm'
        (e / 'map.yaml').write_text(yaml.safe_dump(cfg))
        self.assertEqual(n.chosen_grid('hall'), e / 'map.yaml')
        cfg['origin'][0] = 2
        (e / 'map.yaml').write_text(yaml.safe_dump(cfg))
        with self.assertRaises(RuntimeError):
            n.chosen_grid('hall')

    def test_dry_run_has_no_writes(self):
        self.bundle()
        before = self.wp.read_bytes()
        with patch.object(n, 'destination', return_value=self.dst), patch.object(n, 'filtered') as f, patch.object(n, 'ros') as ros:
            n.deploy('hall', original=True, dry=True)
            f.assert_not_called()
            ros.assert_not_called()
        self.assertEqual(self.wp.read_bytes(), before)
        self.assertFalse(self.dst.exists())

    def test_busy_refused_before_filter_or_waypoints(self):
        self.bundle()
        before = self.wp.read_bytes()
        with patch.object(n, 'destination', return_value=self.dst), patch.object(n, 'idle', side_effect=RuntimeError('busy')), patch.object(n, 'filtered') as f:
            with self.assertRaises(RuntimeError):
                n.deploy('hall', original=True)
            f.assert_not_called()
        self.assertEqual(self.wp.read_bytes(), before)

    def test_new_pcd_resets_waypoints_with_backup(self):
        _, pcd, _, _ = self.bundle()
        before = self.wp.read_bytes()
        with patch.object(n, 'destination', return_value=self.dst), patch.object(n, 'idle'), patch.object(n, 'filtered', return_value=pcd), patch.object(n, 'ros', side_effect=self.fake_deployer):
            n.deploy('hall', original=True)
        self.assertEqual(self.wp.read_text(), 'frame_id: map\n')
        backups = list((self.data / 'waypoint_backups').glob('*.yaml'))
        self.assertEqual(backups[0].read_bytes(), before)

    def test_same_pcd_keeps_waypoints(self):
        _, pcd, _, _ = self.bundle()
        self.dst.mkdir(parents=True)
        (self.dst / 'scans_loc.pcd').write_bytes(pcd.read_bytes())
        before = self.wp.read_bytes()
        with patch.object(n, 'destination', return_value=self.dst), patch.object(n, 'idle'), patch.object(n, 'filtered', return_value=pcd), patch.object(n, 'ros', side_effect=self.fake_deployer):
            n.deploy('hall', original=True)
        self.assertEqual(self.wp.read_bytes(), before)

    def test_filter_cache_rejects_tampering(self):
        directory, pcd, _, _ = self.bundle()
        output = directory / 'hall_loc.pcd'
        output.write_bytes(pcd.read_bytes())
        (directory / 'filter.json').write_text(json.dumps({'source': n.digest(pcd), 'output': n.digest(output)}))
        self.assertEqual(n.filtered('hall'), output)
        output.write_text('corrupt')
        with self.assertRaises(RuntimeError):
            n.filtered('hall')

    def select_backup(self, content=b'previous active pcd'):
        active = self.maps / 'backups/e_42_20261011_111707_692178'
        (active / 'scans_occ').mkdir(parents=True)
        (active / 'scans_loc.pcd').write_bytes(content)
        (active / 'scans_occ/scans_occ.yaml').write_text('image: scans_occ.pgm\n')
        self.site.write_text('# keep comment\nmap_pcd: ' + str(active / 'scans_loc.pcd') +
                             '\nmap_yaml: ' + str(active / 'scans_occ/scans_occ.yaml') + '\nkeep_setting: 42\n')
        self.source_site.write_bytes(self.site.read_bytes())
        return active

    def test_backup_loading_deploys_only_to_standard_path(self):
        active = self.select_backup()
        self.assertEqual(n.active_map(), active)
        self.assertEqual(n.destination(), self.dst)

    def test_backup_loading_dry_run_changes_nothing(self):
        self.bundle()
        self.select_backup()
        before = {p: p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        n.deploy('hall', original=True, dry=True)
        self.assertEqual(before, {p: p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()})
        n.prepare_site_updates.assert_not_called()

    def test_unknown_or_symlink_paths_rejected(self):
        self.site.write_text('map_pcd: /tmp/other/scans_loc.pcd\nmap_yaml: /tmp/other/scans_occ/scans_occ.yaml\n')
        with self.assertRaises(RuntimeError):
            n.destination()
        active = self.select_backup()
        self.dst.symlink_to(active, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            n.destination()

    def test_complete_backup_edited_grid_filter_and_path_switch(self):
        directory, pcd, _, cfg = self.bundle()
        active = self.select_backup()
        active_bytes = (active / 'scans_loc.pcd').read_bytes()
        self.dst.mkdir()
        (self.dst / 'scans_loc.pcd').write_bytes(pcd.read_bytes())
        (self.dst / 'keep_this.txt').write_text('original entire map directory')
        edit = directory / 'edited/edited_latest'
        edit.mkdir(parents=True)
        Image.new('L', (8, 8), 0).save(edit / 'map.pgm')
        cfg['image'] = 'map.pgm'
        (edit / 'map.yaml').write_text(yaml.safe_dump(cfg))
        before_site = self.site.read_text()
        with patch.object(n, 'idle'), patch.object(n, 'filtered', return_value=pcd) as filt, patch.object(n, 'ros', side_effect=self.fake_deployer):
            n.deploy('hall')
            filt.assert_called_once_with('hall')
        self.assertEqual((active / 'scans_loc.pcd').read_bytes(), active_bytes)
        self.assertEqual(n.active_map(), self.dst)
        self.assertEqual(n.digest(edit / 'map.pgm'), n.digest(self.dst / 'scans_occ/scans_occ.pgm'))
        record = json.loads((self.data / 'last_deployment.json').read_text())
        self.assertEqual(Path(record['grid']), edit / 'map.yaml')
        old = Path(record['maps_backup'])
        self.assertEqual((old / 'keep_this.txt').read_text(), 'original entire map directory')
        self.assertEqual((old / 'scans_loc.pcd').read_bytes(), pcd.read_bytes())
        saved = Path(record['configuration_backup'])
        self.assertEqual((saved / 'installed_e_42.yaml').read_text(), before_site)
        self.assertTrue((saved / 'waypoints.yaml').is_file())
        self.assertEqual(self.wp.read_text(), 'frame_id: map\n')  # Compare ACTIVE, not canonical PCD.
        self.assertIn('# keep comment', self.site.read_text())
        self.assertEqual(yaml.safe_load(self.site.read_text())['keep_setting'], 42)

    def test_permission_failure_before_point_mutation(self):
        self.bundle()
        before = self.wp.read_bytes()
        with patch.object(n, 'idle'), patch.object(n, 'prepare_site_updates', side_effect=RuntimeError('permission')), patch.object(n, 'ros') as ros:
            with self.assertRaises(RuntimeError):
                n.deploy('hall', original=True)
            ros.assert_not_called()
        self.assertEqual(before, self.wp.read_bytes())

    def test_deployer_failure_does_not_activate_site(self):
        _, pcd, _, _ = self.bundle()
        self.select_backup()
        before = self.site.read_bytes()
        with patch.object(n, 'idle'), patch.object(n, 'filtered', return_value=pcd), patch.object(n, 'ros', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                n.deploy('hall', original=True)
        n.activate_site.assert_not_called()
        self.assertEqual(before, self.site.read_bytes())
        self.assertEqual(self.wp.read_text(), 'frame_id: map\n')

    def test_filter_still_runs_at_five_centimeters(self):
        directory, pcd, _, _ = self.bundle()
        def fake_filter(*args):
            self.assertEqual(args[:4], ('ros2', 'run', 'fast_lio', 'filter_saved_pcd'))
            self.assertEqual(args[-1], '0.05')
            Path(args[-2]).write_bytes(pcd.read_bytes())
        with patch.object(n, 'run', side_effect=fake_filter) as run:
            result = n.filtered('hall')
            self.assertEqual(result, directory / 'hall_loc.pcd')
            n.filtered('hall')
            run.assert_called_once()

    @unittest.skipUnless(Path('/opt/ros/jazzy/lib/python3.12/site-packages/e_slam_bringup/deploy_navigation_maps.py').is_file(), 'Installed deb integration test')
    def test_real_deb_deployer_backs_up_full_old_directory(self):
        _, pcd, _, _ = self.bundle()
        self.select_backup()
        self.dst.mkdir()
        (self.dst / 'scans_loc.pcd').write_bytes(b'old map')
        (self.dst / 'old_grid_extra.txt').write_text('preserve entire old directory')
        def actual(tool, *args):
            self.assertEqual(tool, 'deploy_navigation_maps')
            subprocess.run(['/usr/bin/python3', '/opt/ros/jazzy/lib/python3.12/site-packages/e_slam_bringup/deploy_navigation_maps.py', *map(str, args)], check=True)
        with patch.object(n, 'idle'), patch.object(n, 'filtered', return_value=pcd), patch.object(n, 'ros', side_effect=actual):
            n.deploy('hall', original=True)
        record = json.loads((self.data / 'last_deployment.json').read_text())
        old = Path(record['maps_backup'])
        self.assertEqual((old / 'old_grid_extra.txt').read_text(), 'preserve entire old directory')
        self.assertEqual((old / 'scans_loc.pcd').read_bytes(), b'old map')

    def test_rviz_uses_deb_entry_and_dry_run(self):
        with patch.object(n.Path, 'is_file', return_value=True), patch.object(n, 'ros') as ros, patch('web_links.show'):
            n.visualize('mapping', dry=True)
            call = ros.call_args.args
            self.assertEqual(call[0], 'visualize_mapping')
            self.assertIn('--dry-run', call)
            self.assertIn('--restart', call)
            self.assertEqual(call[call.index('--domain-id') + 1], '0')
            n.visualize('navigation')
            self.assertEqual(ros.call_args.args[0], 'visualize_navigation')
            self.assertNotIn('--dry-run', ros.call_args.args)

    def test_missing_rviz_deb_does_not_fallback(self):
        with patch.object(n.Path, 'is_file', return_value=False), patch.object(n, 'ros') as ros:
            with self.assertRaises(RuntimeError):
                n.visualize('mapping')
            ros.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
