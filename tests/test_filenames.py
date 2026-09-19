import tempfile
import unittest
from pathlib import Path

from gallery_dl.formatter import parse
from app.backend import command
from app.core import Store, new_task
from app.filenames import clean_gallery_suffix, clean_video_suffix


class FilenameTests(unittest.TestCase):
    def test_gallery_prefers_post_text_and_falls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            for url, metadata, expected in (
                ('https://x.com/user/status/900', {'content': 'نص التغريدة', 'extension': 'jpg'}, 'نص التغريدة.jpg'),
                ('https://instagram.com/p/test', {'caption': 'صورة التخرج', 'extension': 'jpg'}, 'صورة التخرج.jpg'),
                ('https://www.tiktok.com/@user', {'description': 'فيديو تيك توك', 'extension': 'mp4'}, 'فيديو تيك توك.mp4'),
            ):
                args, _ = command(new_task(url, folder), store)
                formatter = parse(args[args.index('--filename') + 1])
                self.assertEqual(formatter.format_map(metadata), expected)
                self.assertIn('extractor.skip=enumerate', args)
                self.assertEqual(formatter.format_map({'extension': 'jpg'}), 'منشور.jpg')
            store.db.close()

    def test_rename_only_when_gallery_adds_collision_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'العنوان.1.jpg'
            first.write_bytes(b'first')
            self.assertEqual(Path(clean_gallery_suffix(first)), Path(folder) / 'العنوان.jpg')
            second = Path(folder) / 'العنوان.1.jpg'
            second.write_bytes(b'second')
            self.assertEqual(Path(clean_gallery_suffix(second)), Path(folder) / 'العنوان (2).jpg')
            self.assertEqual((Path(folder) / 'العنوان.jpg').read_bytes(), b'first')
            self.assertEqual((Path(folder) / 'العنوان (2).jpg').read_bytes(), b'second')

    def test_ytdlp_prefers_tweet_and_tiktok_description(self):
        import yt_dlp
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            for url in ('https://x.com/user/status/900', 'https://www.tiktok.com/@user/video/900'):
                args, _ = command(new_task(url, folder, media='video'), store)
                template = args[args.index('-o') + 1]
                with yt_dlp.YoutubeDL({'outtmpl': template, 'windowsfilenames': True}) as ydl:
                    name = ydl.prepare_filename({'id': '900', 'title': 'username - 900',
                                                 'description': 'عنوان المنشور', 'ext': 'mp4'})
                self.assertEqual(name, 'عنوان المنشور___YID___900.mp4')
            store.db.close()

    def test_video_names_only_get_a_number_on_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'عنوان المنشور___YID___900.mp4'
            first.write_bytes(b'first')
            self.assertEqual(Path(clean_video_suffix(first)), Path(folder) / 'عنوان المنشور.mp4')
            second = Path(folder) / 'عنوان المنشور___YID___901.mp4'
            second.write_bytes(b'second')
            self.assertEqual(Path(clean_video_suffix(second)), Path(folder) / 'عنوان المنشور (2).mp4')
            self.assertEqual((Path(folder) / 'عنوان المنشور.mp4').read_bytes(), b'first')
            self.assertEqual((Path(folder) / 'عنوان المنشور (2).mp4').read_bytes(), b'second')

    def test_generated_tiktok_id_is_not_shown_as_post_title(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'TikTok video #123___YID___123.mp4'
            source.write_bytes(b'video')
            self.assertEqual(Path(clean_video_suffix(source)).name, 'منشور.mp4')
            source = Path(folder) / 'TikTok video #456.1.mp4'
            source.write_bytes(b'other video')
            self.assertEqual(Path(clean_gallery_suffix(source)).name, 'منشور (2).mp4')
