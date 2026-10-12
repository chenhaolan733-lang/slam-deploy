import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import web_links as w


class WebTests(unittest.TestCase):
    def test_remap_preserves_access_token(self):
        self.assertEqual(w.remap('http://127.0.0.1:8765/?token=abc', [16080, 18765, 18088]),
                         'http://127.0.0.1:18765/?token=abc')
        self.assertEqual(w.remap('http://127.0.0.1:8088/#token=abc', [16080, 18765, 18088]),
                         'http://127.0.0.1:18088/#token=abc')

    def test_ready_and_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(w, 'EDITOR', root / 'runtime/editor_link.json'), patch.object(w.Path, 'home', return_value=root):
                w.remember_editor('http://127.0.0.1:8765/?token=test-only')
                self.assertEqual(json.loads(w.EDITOR.read_text())['url'], 'http://127.0.0.1:8765/?token=test-only')
                token = root / '.config/kitt15/speed_panel.token'
                token.parent.mkdir(parents=True)
                token.write_text('test-only')
                with patch.object(w, 'reachable', return_value=True):
                    result = dict(w.snapshot([16080,18765,18088]))
                    self.assertIn(':18765/?token=test-only', result['Map editor'])
                    self.assertIn(':18088/#token=test-only', result['Speed / Stop'])
                with patch.object(w, 'reachable', return_value=False):
                    self.assertTrue(all('http://' not in value for _, value in w.snapshot()))

    def test_reject_non_local_editor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(w, 'EDITOR', Path(directory) / 'link.json'):
            w.remember_editor('http://example.com/?token=bad')
            self.assertFalse(w.EDITOR.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
