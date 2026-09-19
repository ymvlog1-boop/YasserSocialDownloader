import hashlib, io, json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from app.updater import latest_app_release, available_app_update, _safe_extract, _write_apply_script, UPDATE_ASSET, UPDATE_REPO

class AppUpdateTests(unittest.TestCase):
    def test_release_requires_official_asset_and_digest(self):
        meta={'tag_name':'v9.9.9','assets':[{'name':UPDATE_ASSET,'digest':'sha256:'+'a'*64,'browser_download_url':'https://github.com/'+UPDATE_REPO+'/releases/download/v9.9.9/'+UPDATE_ASSET}]}
        with patch('app.updater._github_json',return_value=meta):
            self.assertEqual(latest_app_release()[0],'9.9.9')
    def test_available_update_only_returns_newer_version(self):
        with patch('app.updater.latest_app_release',return_value=('9.9.9','url','digest')) as latest:
            self.assertEqual(available_app_update(),'9.9.9')
            latest.assert_called_once_with(timeout=8)
        with patch('app.updater.latest_app_release',return_value=('1.2.3','url','digest')):
            self.assertIsNone(available_app_update())
    def test_safe_extract_blocks_escape(self):
        with tempfile.TemporaryDirectory() as d:
            z=Path(d)/'x.zip'
            with zipfile.ZipFile(z,'w') as f:f.writestr('../evil.txt','x')
            with self.assertRaises(ValueError):_safe_extract(z,Path(d)/'out')
    def test_apply_script_mentions_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=_write_apply_script(Path(d)/'stage',Path(d)/'app',123,'YasserSocialDownloader.exe')
            text=p.read_text(encoding='utf-8')
            self.assertIn('robocopy',text.lower());self.assertIn('YasserSocialDownloader.exe',text)
            p.unlink(missing_ok=True)
