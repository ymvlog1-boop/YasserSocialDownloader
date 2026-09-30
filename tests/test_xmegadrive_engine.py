import unittest
from urllib.parse import urlsplit
from app.xmegadrive_engine import _is_collection_page, _is_video_url


class XMegaDriveDiscoveryTests(unittest.TestCase):
    def test_detail_urls_do_not_include_collection_pages(self):
        host='x-x-x.tube'
        self.assertTrue(_is_video_url('https://x-x-x.tube/videos/490460/title/',host))
        self.assertTrue(_is_video_url('https://x-fetish.tube/video/703801/title/','x-fetish.tube'))
        self.assertFalse(_is_video_url('https://x-x-x.tube/videos/',host))
        self.assertFalse(_is_video_url('https://x-x-x.tube/models/auroraxoxo/videos/',host))
        self.assertFalse(_is_video_url('https://x-x-x.tube/models/auroraxoxo/videos/2/',host))

    def test_model_video_landing_and_all_pages_are_followed(self):
        start=urlsplit('https://x-x-x.tube/models/auroraxoxo/')
        host='x-x-x.tube'
        self.assertTrue(_is_collection_page('https://x-x-x.tube/models/auroraxoxo/videos/?by=post_date',start,host))
        self.assertTrue(_is_collection_page('https://x-x-x.tube/models/auroraxoxo/videos/2/?by=post_date',start,host))
        self.assertFalse(_is_collection_page('https://x-x-x.tube/models/auroraxoxo/videos/?by=rating',start,host))
        self.assertFalse(_is_collection_page('https://x-x-x.tube/models/someone-else/videos/2/',start,host))


if __name__=='__main__': unittest.main()
