import tempfile, unittest
from pathlib import Path
from app.core import Store, new_task
from app.backend import command, is_profile_url, prepare_profile_folder, profile_username


class BackendRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.out = str(Path(self.temp.name) / 'out')
    def tearDown(self):
        self.store.db.close(); self.temp.cleanup()
    def make(self, url, media='auto'):
        return new_task(url, self.out, media=media, quality='best', cookies=False)
    def cmd(self, task):
        return command(task, self.store)
    def test_profile_detection(self):
        self.assertTrue(is_profile_url('instagram','https://www.instagram.com/example/'))
        self.assertTrue(is_profile_url('twitter','https://x.com/example'))
        self.assertTrue(is_profile_url('tiktok','https://www.tiktok.com/@example?lang=es'))
        self.assertTrue(is_profile_url('facebook','https://www.facebook.com/example'))
        self.assertFalse(is_profile_url('instagram','https://www.instagram.com/reel/ABC/'))
        self.assertFalse(is_profile_url('twitter','https://x.com/example/status/1'))
        self.assertFalse(is_profile_url('tiktok','https://www.tiktok.com/@example/video/123'))

    def test_profile_username_extraction(self):
        self.assertEqual(profile_username('instagram','https://www.instagram.com/model.one/'),'model.one')
        self.assertEqual(profile_username('twitter','https://x.com/Actor_Name'),'Actor_Name')
        self.assertEqual(profile_username('tiktok','https://www.tiktok.com/@creator?lang=ar'),'creator')
        self.assertEqual(profile_username('facebook','https://www.facebook.com/profile.php?id=12345'),'12345')
        self.assertIsNone(profile_username('instagram','https://www.instagram.com/reel/ABC/'))

    def test_profiles_get_platform_and_username_folders(self):
        cases = [
            ('https://www.instagram.com/model.one/', 'instagram', 'model.one'),
            ('https://x.com/Actor_Name', 'twitter', 'Actor_Name'),
            ('https://www.tiktok.com/@creator?lang=ar', 'tiktok', 'creator'),
            ('https://www.facebook.com/PageName', 'facebook', 'PageName'),
        ]
        for url, platform, username in cases:
            task = self.make(url)
            prepare_profile_folder(task)
            expected = Path(self.out) / platform / username
            self.assertEqual(Path(task['folder']), expected)
            argv, _ = self.cmd(task)
            self.assertIn(str(expected), argv)

    def test_existing_platform_folder_is_not_duplicated(self):
        task = new_task('https://www.instagram.com/example/', str(Path(self.out) / 'instagram'))
        prepare_profile_folder(task)
        self.assertEqual(Path(task['folder']), Path(self.out) / 'instagram' / 'example')

    def test_profile_folder_name_is_windows_safe(self):
        task = self.make('https://x.com/CON')
        prepare_profile_folder(task)
        self.assertEqual(Path(task['folder']).name, 'CON_profile')

    def test_instagram_uses_merged_video_and_disables_audio_attachments(self):
        task = self.make('https://www.instagram.com/example/')
        argv, engine = self.cmd(task)
        self.assertEqual(engine, 'gallery')
        text = ' '.join(argv)
        self.assertIn('extractor.instagram.videos=merged', text)
        self.assertIn('extractor.instagram.audio=false', text)
        self.assertNotIn('m4a', text)

    def test_instagram_video_filter_keeps_final_video(self):
        task = self.make('https://www.instagram.com/example/', 'video')
        argv, _ = self.cmd(task)
        filter_value = argv[argv.index('--filter') + 1]
        self.assertIn('extension in', filter_value)
        self.assertNotIn('m4a', filter_value)
        self.assertIn('extractor.instagram.videos=merged', ' '.join(argv))
    def test_all_profile_urls_stay_gallery_even_video_only(self):
        for url in [
            'https://www.instagram.com/example/', 'https://x.com/example',
            'https://www.tiktok.com/@example?lang=es', 'https://www.facebook.com/example']:
            for media in ('auto','all','images','video'):
                task=self.make(url,media); argv,engine=self.cmd(task)
                self.assertEqual(engine,'gallery',(url,media,argv))
    def test_single_video_uses_ytdlp(self):
        for url in [
            'https://www.instagram.com/reel/ABC/', 'https://x.com/example/status/1',
            'https://www.tiktok.com/@example/video/123']:
            task=self.make(url,'video'); argv,engine=self.cmd(task); self.assertEqual(engine,'video')
    def test_instagram_profile_splits_posts_and_reels(self):
        task=self.make('https://www.instagram.com/example/')
        argv,engine=self.cmd(task); text=' '.join(argv)
        self.assertEqual(engine,'gallery'); self.assertIn('extractor.instagram.include=posts',text)
        task['phase']='instagram_reels'; argv,engine=self.cmd(task); text=' '.join(argv)
        self.assertEqual(engine,'gallery'); self.assertIn('extractor.instagram.include=reels',text)
    def test_tiktok_profile_uses_internal_ytdlp_not_profile_fallback(self):
        argv,engine=self.cmd(self.make('https://www.tiktok.com/@example?lang=es'))
        text=' '.join(argv); self.assertEqual(engine,'gallery'); self.assertIn('extractor.tiktok.posts.ytdl=true',text); self.assertIn('extractor.tiktok.posts.module=yt_dlp',text)
    def test_facebook_video_phase_uses_discovery_engine(self):
        task=self.make('https://www.facebook.com/example'); task['phase']='facebook_videos'
        argv,engine=self.cmd(task); self.assertEqual(engine,'facebook'); self.assertIn('--url',argv); self.assertIn(task['url'],argv)
    def test_legacy_facebook_video_phase_routes_to_discovery_engine(self):
        task=self.make('https://www.facebook.com/example'); task['phase']='facebook_video_ytdlp'
        argv,engine=self.cmd(task); self.assertEqual(engine,'facebook'); self.assertIn('--url',argv)
    def test_tiktok_second_pass_uses_ytdlp(self):
        task=self.make('https://www.tiktok.com/@example?lang=es'); task['phase']='tiktok_ytdlp'
        argv,engine=self.cmd(task); self.assertEqual(engine,'video')

    def test_tiktok_second_pass_avoids_cookies_and_prefers_audio(self):
        task=self.make('https://www.tiktok.com/@example?lang=es'); task['phase']='tiktok_ytdlp'; task['cookies']=True
        argv,engine=command(task,self.store,'C:/temp/cookies.txt'); text=' '.join(argv)
        self.assertEqual(engine,'video')
        self.assertNotIn('--cookies',argv)
        self.assertIn('acodec!=none',text)
        self.assertIn('--merge-output-format',argv)
        self.assertIn('mp4',argv)

    def test_twitter_profile_targets_timeline_and_waits(self):
        task=self.make('https://x.com/example'); argv,engine=self.cmd(task)
        text=' '.join(argv); self.assertEqual(engine,'gallery'); self.assertTrue(argv[-1].endswith('/example/timeline')); self.assertIn('extractor.twitter.ratelimit=wait',text); self.assertIn('extractor.twitter.timeline.strategy=tweets',text)
        task['twitter_cursor']='CUR123'; argv,engine=self.cmd(task); self.assertIn('extractor.twitter.cursor=CUR123',' '.join(argv))

if __name__=='__main__': unittest.main()
