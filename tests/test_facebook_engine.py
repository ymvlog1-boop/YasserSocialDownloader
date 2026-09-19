import unittest
from app.facebook_engine import _extract_video_urls, _canonical_video_url, _pagination_links

class FacebookDiscoveryTests(unittest.TestCase):
    def test_extracts_common_video_forms_and_deduplicates(self):
        text = r"""
        <a href="https://www.facebook.com/example/videos/123456789012345">one</a>
        <a href="/reel/987654321098765">two</a>
        {"video_id":"555555555555555"}
        https:\/\/www.facebook.com\/watch\/?v=777777777777777
        """
        urls = _extract_video_urls(text)
        self.assertIn('https://www.facebook.com/watch/?v=123456789012345', urls)
        self.assertIn('https://www.facebook.com/reel/987654321098765', urls)
        self.assertIn('https://www.facebook.com/watch/?v=555555555555555', urls)
        self.assertIn('https://www.facebook.com/watch/?v=777777777777777', urls)
        self.assertEqual(len(urls), len(set(urls)))


    def test_extracts_modern_comet_video_nodes(self):
        text = r'''
        {"__typename":"Video","id":"812345678901234","name":"x"}
        {"video":{"id":"823456789012345","__typename":"Video"}}
        {"media":{"__typename":"Video","id":"834567890123456"}}
        '''
        urls = _extract_video_urls(text)
        self.assertIn('https://www.facebook.com/watch/?v=812345678901234', urls)
        self.assertIn('https://www.facebook.com/watch/?v=823456789012345', urls)
        self.assertIn('https://www.facebook.com/watch/?v=834567890123456', urls)

    def test_pagination_is_scoped(self):
        text='<a href="/example/videos?cursor=abc">next</a><a href="https://evil.invalid/x?cursor=z">bad</a>'
        links=_pagination_links('https://www.facebook.com/example/videos',text,'/example')
        self.assertEqual(len(links),1); self.assertIn('cursor=abc',links[0])

    def test_canonical_rejects_non_facebook(self):
        self.assertIsNone(_canonical_video_url('https://example.com/watch/?v=123456'))

if __name__=='__main__': unittest.main()
