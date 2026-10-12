import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml
import navmap_activate_e42 as helper


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.maps = root / 'maps'
        self.dst = self.maps / 'e_42'
        self.site = root / 'e_42.yaml'
        active = self.maps / 'backups/e_42_20261011'
        self.original = ('# keep calibration\nmap_pcd: '+str(active / 'scans_loc.pcd')+
                         '\nmap_yaml: '+str(active / 'scans_occ/scans_occ.yaml')+'\nodom_scale: 1.15\n')
        self.site.write_text(self.original)
        for key, value in [('SITE', self.site), ('MAPS', self.maps), ('DST', self.dst)]:
            p = patch.object(helper, key, value)
            p.start()
            self.addCleanup(p.stop)

    def test_check_no_write_and_arbitrary_args_refused(self):
        helper.main(['--check'])
        self.assertEqual(self.site.read_text(), self.original)
        with self.assertRaises(RuntimeError):
            helper.main(['--apply', '/tmp/evil'])

    def test_missing_map_never_switches(self):
        with self.assertRaises(RuntimeError):
            helper.main(['--apply'])
        self.assertEqual(self.site.read_text(), self.original)

    def test_apply_preserves_other_settings_and_backups(self):
        (self.dst / 'scans_occ').mkdir(parents=True)
        (self.dst / 'scans_loc.pcd').write_text('pcd fixture')
        (self.dst / 'scans_occ/scans_occ.pgm').write_bytes(b'P5fixture')
        (self.dst / 'scans_occ/scans_occ.yaml').write_text('image: scans_occ.pgm\nresolution: 0.05\n')
        helper.main(['--apply'])
        expected = dict(yaml.safe_load(self.original), map_pcd=str(self.dst/'scans_loc.pcd'),
                        map_yaml=str(self.dst/'scans_occ/scans_occ.yaml'))
        self.assertEqual(yaml.safe_load(self.site.read_text()), expected)
        self.assertIn('# keep calibration', self.site.read_text())
        backups = list(self.site.parent.glob('*.navmap-backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.original)
        helper.main(['--apply'])
        self.assertEqual(len(list(self.site.parent.glob('*.navmap-backup-*'))), 1)


if __name__ == '__main__':
    unittest.main()
