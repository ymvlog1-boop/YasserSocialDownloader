import tempfile,json,hashlib,unittest,io
from unittest.mock import patch
from pathlib import Path
from app.updater import updated_engine,UpdateWorker,SOURCES

class UpdateTests(unittest.TestCase):
    def test_trusted_manifest_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'engines';folder.mkdir();exe=folder/'test.exe';exe.write_bytes(b'fixture')
            manifest=folder/'current.json';manifest.write_text(json.dumps({'video':{'path':str(exe),'sha256':hashlib.sha256(b'fixture').hexdigest()}}))
            self.assertEqual(updated_engine(root,'video'),str(exe));exe.write_bytes(b'changed');self.assertIsNone(updated_engine(root,'video'))
    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'engines';folder.mkdir();exe=root/'outside.exe';exe.write_bytes(b'fixture')
            (folder/'current.json').write_text(json.dumps({'video':{'path':str(exe),'sha256':hashlib.sha256(b'fixture').hexdigest()}}))
            self.assertIsNone(updated_engine(root,'video'))
    def transaction(self,bad_digest=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        (root/'engines').mkdir();manifest=root/'engines'/'current.json';manifest.write_text('{}');old=manifest.read_bytes()
        payload=b'test release bytes';digest=hashlib.sha256(payload).hexdigest()
        def response(request,timeout=None):
            url=request.full_url if hasattr(request,'full_url') else request
            if 'api.github.com' in url:
                kind='video' if SOURCES['video']['repo'] in url else 'gallery'
                repo=SOURCES[kind]['repo'];name=SOURCES[kind]['asset']
                value={'tag_name':'2099.1.1','assets':[{'name':name,'digest':'sha256:'+('0'*64 if bad_digest and kind=='gallery' else digest),'browser_download_url':'https://github.com/'+repo+'/releases/download/2099.1.1/'+name}]}
                return io.BytesIO(json.dumps(value).encode())
            return io.BytesIO(payload)
        worker=UpdateWorker(root);events=[];worker.result.connect(lambda ok,message:events.append(ok))
        with patch('app.updater.urllib.request.urlopen',side_effect=response),patch('app.updater.subprocess.run') as run:
            run.return_value.returncode=0;run.return_value.stdout=b'2099.1.1';worker.run()
        return root,manifest,old,events
    def test_transaction_success(self):
        root,manifest,old,events=self.transaction()
        self.assertEqual(events,[True]);self.assertTrue(updated_engine(root,'video'));self.assertTrue(updated_engine(root,'gallery'))
    def test_bad_second_asset_preserves_previous_manifest(self):
        root,manifest,old,events=self.transaction(True)
        self.assertEqual(events,[False]);self.assertEqual(manifest.read_bytes(),old);self.assertEqual(list((root/'engines').glob('*.exe')),[])
