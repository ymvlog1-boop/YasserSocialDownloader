import io
import json
import tempfile
import unittest
from pathlib import Path
from email.message import Message

from app.core import Store, detect, new_task
from app.backend import command
from app.direct_media import download, validate_url


class Response(io.BytesIO):
    def __init__(self, data, status=200, **headers):
        super().__init__(data)
        self.status = status
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key.replace('_', '-')] = str(value)
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class DirectMediaTests(unittest.TestCase):
    URL = 'https://cdn.example.com/photo.jpg?token=abc'

    def test_explicit_routing_and_validation(self):
        with self.assertRaises(ValueError): detect(self.URL)
        self.assertEqual(detect(self.URL, direct=True)[0], 'direct')
        for url in ('http://example.com/a.jpg', 'https://localhost/a.jpg',
                    'https://127.0.0.1/a.jpg', 'https://user:pass@example.com/a.jpg'):
            with self.assertRaises(ValueError): validate_url(url)
        with tempfile.TemporaryDirectory() as root:
            task = new_task(self.URL, root, direct=True)
            store = Store(root)
            argv, engine = command(task, store)
            store.db.close()
            self.assertEqual(engine, 'direct')
            self.assertEqual(argv[-1], '--resume')

    def test_download_skip_and_resume(self):
        with tempfile.TemporaryDirectory() as root:
            requests = []
            def first(req, timeout):
                requests.append(req)
                return Response(b'abc', Content_Type='image/jpeg', Content_Length='3', ETag='v1')
            target = Path(download(self.URL, root, opener=first))
            self.assertEqual(target.read_bytes(), b'abc')
            download(self.URL, root, opener=lambda *_args, **_kwargs: self.fail('duplicate request'))
            meta_path = next(Path(root).glob('*.json'))
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            meta['complete'] = False
            meta_path.write_text(json.dumps(meta), encoding='utf-8')
            Path(str(target).rsplit('.', 1)[0] + '.part').write_bytes(b'ab')
            def second(req, timeout):
                self.assertEqual(req.get_header('Range'), 'bytes=2-')
                self.assertEqual(req.get_header('If-range'), 'v1')
                return Response(b'c', 206, Content_Type='image/jpeg', Content_Length='1', Content_Range='bytes 2-2/3', ETag='v1')
            self.assertEqual(Path(download(self.URL, root, opener=second)).read_bytes(), b'abc')

    def test_rejects_html(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                download(self.URL, root, opener=lambda *_args, **_kwargs: Response(b'<html>', Content_Type='text/html'))


if __name__ == '__main__': unittest.main()
