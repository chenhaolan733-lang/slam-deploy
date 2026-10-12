import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import download_nav_debs as d

BASE='http://nexus.example.com'
VERSION='2.2.1-0noble'


def component(name='ros-jazzy-fast-lio'):
    filename=f'{name}_{VERSION}_arm64.deb'
    return dict(repository='kitt15-apt',format='apt',name=name,version=VERSION,group='arm64',
                assets=[dict(downloadUrl=BASE+'/repository/kitt15-apt/pool/r/'+name+'/'+filename,
                             fileSize=3,checksum={'sha256':hashlib.sha256(b'abc').hexdigest()})])


class DownloadTests(unittest.TestCase):
    def search(self,pages):
        opener=SimpleNamespace(open=lambda *a,**kw:io.BytesIO(json.dumps(pages.pop(0)).encode()))
        return d.resolve_release(opener,BASE,'kitt15-apt',VERSION,'arm64')

    def test_complete_nine(self):
        result=self.search([{'items':[component(name)]} for name in d.PACKAGES])
        self.assertEqual(len(result),9)

    def test_pagination_exact_version_filter(self):
        wrong=component();wrong['version']='old'
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)):
            result=self.search([{'items':[wrong],'continuationToken':'next'}, {'items':[component()]}])
        self.assertEqual(len(result),1)

    def test_missing_package(self):
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)),self.assertRaises(d.DownloadError):
            self.search([{'items':[]}])

    def test_wrong_architecture(self):
        data=component();data['group']='amd64'
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)),self.assertRaises(d.DownloadError):
            self.search([{'items':[data]}])

    def test_reject_foreign_server(self):
        data=component();data['assets'][0]['downloadUrl']=data['assets'][0]['downloadUrl'].replace(BASE,'http://example.com')
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)),self.assertRaises(d.DownloadError):
            self.search([{'items':[data]}])

    def test_requires_sha256(self):
        data=component();data['assets'][0]['checksum']={}
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)),self.assertRaises(d.DownloadError):
            self.search([{'items':[data]}])

    def test_repeated_pagination_fails(self):
        page={'items':[],'continuationToken':'again'}
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)),self.assertRaises(d.DownloadError):
            self.search([page,page])

    def item(self):
        with patch.object(d,'PACKAGES',('ros-jazzy-fast-lio',)):
            return self.search([{'items':[component()]}])[0]

    def metadata(self,item):
        return SimpleNamespace(stdout=f'Package: {item["name"]}\nVersion: {VERSION}\nArchitecture: arm64\n')

    def test_download_checks_metadata_and_reuses_file(self):
        item=self.item()
        opener=SimpleNamespace(open=lambda *a,**kw:io.BytesIO(b'abc'))
        with tempfile.TemporaryDirectory() as tmp,patch.object(d.subprocess,'run',return_value=self.metadata(item)) as run:
            root=Path(tmp)
            d.download_one(opener,root,item,retries=1)
            self.assertEqual((root/item['filename']).read_bytes(),b'abc')
            self.assertFalse(list(root.glob('*.part')))
            opener.open=lambda *a,**kw:self.fail('Must skip download')
            d.download_one(opener,root,item,retries=1)
            self.assertTrue(all(call.args[0][:2]==['dpkg-deb','-f'] for call in run.call_args_list))

    def test_bad_download_not_promoted(self):
        item=self.item()
        opener=SimpleNamespace(open=lambda *a,**kw:io.BytesIO(b'bad'))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(d.DownloadError):d.download_one(opener,Path(tmp),item,retries=1)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_bad_existing_file_preserved(self):
        item=self.item()
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/item['filename'];target.write_bytes(b'bad')
            with self.assertRaises(d.DownloadError):d.download_one(None,Path(tmp),item,retries=1)
            self.assertEqual(target.read_bytes(),b'bad')

    def test_wrong_deb_metadata_rejected(self):
        item=self.item()
        with tempfile.TemporaryDirectory() as tmp,patch.object(d.subprocess,'run',return_value=SimpleNamespace(stdout='Package: wrong\n')):
            target=Path(tmp)/item['filename'];target.write_bytes(b'abc')
            with self.assertRaises(d.DownloadError):d.verify_file(target,item)

    def test_check_does_not_create_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(d,'resolve_release',return_value=[self.item()]),patch('sys.stdout',new_callable=io.StringIO):
            output=Path(tmp)/'absent'
            d.main(['--version',VERSION,'--server',BASE,'--repository','kitt15-apt','--check','--output',str(output)])
            self.assertFalse(output.exists())


if __name__=='__main__':
    unittest.main()
