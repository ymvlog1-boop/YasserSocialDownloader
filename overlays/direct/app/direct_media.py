"""Download one explicitly supplied HTTPS image or video URL, without page extraction."""
import argparse
import ipaddress
import json
import os
import re
import sys
import urllib.request
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

TYPES = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
    'image/webp': '.webp', 'image/avif': '.avif',
    'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov',
    'video/x-matroska': '.mkv', 'video/ogg': '.ogv',
}


def validate_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        if host == 'localhost' or host.endswith('.localhost'):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if re.fullmatch(r'[\d.]+', host):
                raise
    except ValueError:
        raise ValueError('الرابط المباشر يتطلب HTTPS وعنوان موقع عام') from None


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, folder, force=False, opener=None):
    validate_url(url)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(urlsplit(url).path).stem)[:60].strip('_') or 'media'
    key = sha256(url.encode('utf-8')).hexdigest()[:16]
    base = folder / f'{stem}_{key}'
    meta_path = Path(str(base) + '.json')
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    if meta.get('url') != url:
        meta = {}
    if meta.get('complete') and not force and Path(meta['file']).is_file():
        print('YSKIP:already downloaded', flush=True)
        print('YFILE:' + meta['file'], flush=True)
        return meta['file']
    part = Path(str(base) + '.part')
    offset = part.stat().st_size if part.exists() and meta and not force else 0
    headers = {'User-Agent': 'YasserSocialDownloader/1.3.0', 'Accept': 'image/*, video/*'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
        if meta.get('validator'):
            headers['If-Range'] = meta['validator']
    open_url = opener or urllib.request.build_opener(SafeRedirect()).open
    with open_url(urllib.request.Request(url, headers=headers), timeout=30) as response:
        mime = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if mime not in TYPES:
            raise ValueError('الرابط لا يشير مباشرةً إلى صورة أو فيديو مدعوم')
        status = getattr(response, 'status', 200)
        validator = response.headers.get('ETag') or response.headers.get('Last-Modified')
        if status == 206:
            content_range = response.headers.get('Content-Range', '')
            if not offset or not content_range.startswith(f'bytes {offset}-') or mime != meta.get('mime'):
                raise ValueError('تعذر التحقق من جزء التحميل؛ أعد المحاولة بعد حذف الجزء المؤقت')
            if meta.get('validator') and validator and validator != meta['validator']:
                raise ValueError('تغير الملف على الخادم؛ أعد التحميل من البداية')
        elif status != 200:
            raise ValueError(f'استجابة غير متوقعة من الخادم: {status}')
        else:
            offset = 0
        target = str(base) + TYPES[mime]
        meta = {'url': url, 'file': target, 'mime': mime, 'validator': validator, 'complete': False}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        total = response.headers.get('Content-Length')
        total = int(total) + offset if total and total.isdigit() else None
        done = offset
        with part.open('ab' if offset else 'wb') as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                done += len(chunk)
                print('YPROGRESS:' + json.dumps({'downloaded_bytes': done, 'total_bytes': total}), flush=True)
    if total is not None and done != total:
        raise ValueError('التحميل غير مكتمل؛ يمكن استكماله لاحقًا')
    os.replace(part, target)
    meta['complete'] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    print('YFILE:' + target, flush=True)
    return target


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--folder', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--force', action='store_true')
    mode.add_argument('--resume', action='store_true')
    ns = parser.parse_args(args)
    try:
        download(ns.url, ns.folder, force=ns.force)
        return 0
    except Exception as exc:
        print('ERROR: ' + str(exc), file=sys.stderr, flush=True)
        return 1
