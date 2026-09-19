import tempfile,unittest,time,sys,codecs
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QEvent
from app.core import Store,new_task
from app.manager import DownloadManager

APP=QCoreApplication.instance() or QCoreApplication([])
def wait(predicate,seconds=8):
    end=time.time()+seconds
    while time.time()<end:
        APP.processEvents()
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Timed out')

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.manager=DownloadManager(self.store)
    def tearDown(self):
        self.manager.shutdown();self.manager.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);self.store.db.close();self.temp.cleanup()
    def task(self):return new_task('https://x.com/a/status/1',self.temp.name,media='video')
    def test_completion_and_duplicate(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','print(\'YPROGRESS:{"downloaded_bytes":50,"total_bytes":100}\');print("YFILE:C:/test.mp4")'],'video')):
            self.manager.pump();wait(lambda:t['state']=='completed')
        self.assertEqual(t['progress'],100);self.assertEqual(t['files'],['C:/test.mp4'])
        file=Path(self.temp.name)/'test.mp4';file.write_bytes(b'test');t['files']=[str(file)]
        u=self.task();self.manager.add(u);self.assertEqual(u['state'],'skipped')
        file.unlink();v=self.task();self.manager.add(v);self.assertEqual(v['state'],'queued')
    def test_failure_does_not_close(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','import sys;print("HTTP 403 login required");sys.exit(1)'],'video')):
            self.manager.pump();wait(lambda:t['state']=='failed')
        self.assertIn('كوكيز',t['message']);self.assertFalse(self.manager.active)
    def test_pause_restart_persistence(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','import time;time.sleep(30)'],'video')):
            self.manager.pump();wait(lambda:bool(self.manager.active));self.manager.stop(t);wait(lambda:t['state']=='paused')
        self.assertEqual(self.store.tasks()[0]['state'],'paused');self.manager.retry(t);self.assertEqual(t['state'],'queued');self.manager.stop(t,'cancelled');self.assertEqual(t['state'],'cancelled')
    def test_profile_failure_does_not_switch_to_video_engine(self):
        t=new_task('https://x.com/example',self.temp.name,media='auto');self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','import sys;sys.exit(1)'],'gallery')):
            self.manager.pump();wait(lambda:t['state']=='failed')
        self.assertEqual(t['attempt'],1);self.assertEqual(t['engine'],'gallery');self.assertNotIn('fallback',t)
    def test_empty_is_not_success(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','pass'],'video')):
            self.manager.pump();wait(lambda:t['state']=='empty')
        self.assertEqual(t['progress'],0)
    def test_empty_instagram_profile_runs_bounded_gallery_multipass_only(self):
        t=new_task('https://www.instagram.com/example/',self.temp.name,media='auto');self.manager.add(t)
        calls=[]
        def fake_command(task,store,cookie_path=None):
            calls.append((task.get('phase','primary'),'gallery'))
            return [sys.executable,'-c','pass'],'gallery'
        with patch('app.manager.command',side_effect=fake_command):
            self.manager.pump();wait(lambda:t.get('phase')=='instagram_reels' and t['state']=='queued')
            self.manager.pump();wait(lambda:t['state']=='empty')
        self.assertEqual(calls,[('primary','gallery'),('instagram_reels','gallery')])
        self.assertEqual(t['attempt'],2);self.assertEqual(t['engine'],'gallery')
    def test_archive_skip(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([sys.executable,'-c','print("YSKIP:old.png")'],'gallery')):
            self.manager.pump();wait(lambda:t['state']=='skipped')
        self.assertEqual(t['skipped_count'],1)
    def test_utf8_split_and_last_line(self):
        t=self.task();self.manager.add(t);self.manager.decoders[t['id']]=codecs.getincrementaldecoder('utf-8')('replace')
        raw='YFILE:C:/وسائط/صورة.png'.encode('utf-8')
        for byte in raw:self.manager.feed(t,bytes([byte]))
        self.assertEqual(t['files'],[])
        self.manager.feed(t,b'',final=True)
        self.assertEqual(t['files'],['C:/وسائط/صورة.png']);self.assertEqual(self.store.tasks()[0]['files'],t['files'])
        self.manager.stop(t)
    def test_invalid_progress_does_not_crash(self):
        t=self.task()
        for line in ['null','[]','{"total_bytes":null,"downloaded_bytes":null}','{"total_bytes":"bad"}']:
            self.manager.parse_line(t,'YPROGRESS:'+line)
    def test_cookie_original_unchanged_and_cleanup(self):
        original=Path(self.temp.name)/'cookies.txt'
        data='# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t2147483647\tauth_token\tTEST_VALUE\n'
        original.write_text(data);self.store.set('cookie_twitter',str(original))
        t=self.task();t['cookies']=True;self.manager.add(t);captured=[]
        def fake_command(task,store,cookie_path=None):
            captured.append(cookie_path)
            script='from pathlib import Path;import sys;Path(sys.argv[1]).write_text("changed")'
            return [sys.executable,'-c',script,cookie_path],'video'
        with patch('app.manager.command',side_effect=fake_command):
            self.manager.pump();wait(lambda:t['state']=='empty')
        self.assertEqual(original.read_text(),data);self.assertNotEqual(captured[0],str(original));self.assertFalse(Path(captured[0]).exists())
    def test_failed_start_releases_slot(self):
        t=self.task();self.manager.add(t)
        with patch('app.manager.command',return_value=([str(Path(self.temp.name)/'missing.exe')],'video')):
            self.manager.pump();wait(lambda:t['state']=='failed')
        self.assertFalse(self.manager.active)

    def test_facebook_profile_runs_gallery_then_discovery_engine(self):
        t=new_task('https://www.facebook.com/example',self.temp.name,media='auto');self.manager.add(t)
        calls=[]
        def fake_command(task,store,cookie_path=None):
            phase=task.get('phase','primary');calls.append(phase)
            if phase=='primary':
                return [sys.executable,'-c','print("YFILE:C:/fbphoto.jpg")'],'gallery'
            return [sys.executable,'-c','print("YFBDISCOVER:1");print("YFILE:C:/fbvideo.mp4")'],'facebook'
        with patch('app.manager.command',side_effect=fake_command):
            self.manager.pump();wait(lambda:t.get('phase')=='facebook_videos' and t['state']=='queued')
            self.manager.pump();wait(lambda:t['state']=='completed')
        self.assertEqual(calls,['primary','facebook_videos'])
        self.assertEqual(t['engine'],'facebook');self.assertEqual(len(t['files']),2);self.assertEqual(t['facebook_discovered'],1)


    def test_facebook_zero_video_discovery_is_partial_not_success(self):
        t=new_task('https://www.facebook.com/example',self.temp.name,media='auto');self.manager.add(t)
        def fake_command(task,store,cookie_path=None):
            phase=task.get('phase','primary')
            if phase=='primary':
                return [sys.executable,'-c','print("YFILE:C:/fbphoto.jpg")'],'gallery'
            return [sys.executable,'-c','import sys;print("YFBDISCOVER:0");print("[facebook][error] Could not discover profile video links (no-links)");sys.exit(4)'],'facebook'
        with patch('app.manager.command',side_effect=fake_command):
            self.manager.pump();wait(lambda:t.get('phase')=='facebook_videos' and t['state']=='queued')
            self.manager.pump();wait(lambda:t['state']=='partial')
        self.assertEqual(t.get('facebook_discovered'),0)
        self.assertIn('فيديو',t['message'])

    def test_twitter_cursor_is_saved_and_resumed(self):
        t=new_task('https://x.com/example',self.temp.name,media='auto');self.manager.add(t)
        script='import sys;print("[twitter][error] Unable to retrieve Tweets from this timeline");print("[twitter][info] Use \'-o cursor=ABC123/XYZ\' to continue downloading from the current position");sys.exit(4)'
        with patch('app.manager.command',return_value=([sys.executable,'-c',script],'gallery')):
            self.manager.pump();wait(lambda:t.get('twitter_cursor')=='ABC123/XYZ' and t['state']=='queued')
        self.assertEqual(t.get('phase'),'twitter_resume');self.assertEqual(t.get('twitter_resume_count'),1);self.assertGreater(t.get('resume_at',0),time.time())
        self.manager.stop(t,'cancelled')

if __name__=='__main__':unittest.main()
