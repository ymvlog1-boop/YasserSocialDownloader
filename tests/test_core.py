import tempfile,time,unittest
from pathlib import Path
from app.core import Store,detect,cookie_check,new_task,arabic_error
from app.backend import command

class CoreTests(unittest.TestCase):
    def test_domains(self):
        for url,p in [('https://www.instagram.com/p/a','instagram'),('https://x.com/a/status/1','twitter'),('https://fb.watch/abc','facebook'),('https://vm.tiktok.com/abc','tiktok')]:self.assertEqual(detect(url)[0],p)
        for url in ['https://x.com.evil.com/a','file:///C:/test','https://evil.com/?x.com','https://user:pass@x.com','https://x.com:8888/a']:
            with self.assertRaises(ValueError):detect(url)
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);t=new_task('https://x.com/u/status/1',d);s.save(t);s.set('concurrent',3);s.db.close();s=Store(d)
            self.assertEqual(s.tasks()[0]['url'],t['url']);self.assertEqual(s.get('concurrent'),3);s.delete(t['id']);self.assertEqual(s.tasks(),[]);s.db.close()
    def test_cookie_validation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'cookies.txt';path.write_text('# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t'+str(int(time.time()+3600))+'\tauth_token\tsecret\n')
            self.assertTrue(cookie_check(str(path),'twitter')[0]);self.assertFalse(cookie_check(str(path),'instagram')[0]);path.write_text('bad');self.assertFalse(cookie_check(str(path),'twitter')[0])
    def test_safe_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);t=new_task('https://x.com/u/status/1?arg=$(test)',d,media='video');args,kind=command(t,s)
            self.assertEqual(args[-2],'--');self.assertEqual(args[-1],t['url']);self.assertEqual(kind,'video');self.assertNotIn('--cookies',args);s.db.close()
    def test_errors(self):
        self.assertIn('كوكيز',arabic_error('HTTP 403 login required'));self.assertIn('انتظر',arabic_error('429 rate limit'))

if __name__=='__main__':unittest.main()
