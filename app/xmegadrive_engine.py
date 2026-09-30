import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

try:
    from curl_cffi import requests as http_requests
    CURL_CFFI = True
except ImportError:
    import requests as http_requests
    CURL_CFFI = False


UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36'
VIDEO_PATH_RE = re.compile(r'/(?:videos?|watch)/[^"\'<>\s?#]+', re.I)
MEDIA_URL_RE = re.compile(r'https?://[^"\'<>\s]+?\.(?:m3u8|mp4)(?:\?[^"\'<>\s]*)?', re.I)


def _session(cookiefile=None):
    s = http_requests.Session(impersonate='chrome') if CURL_CFFI else http_requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.8'})
    if cookiefile:
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar(cookiefile)
        jar.load(ignore_discard=True, ignore_expires=True)
        for c in jar:
            s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    return s


def _fetch(session, url):
    r = session.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url


def _links(page_url, text):
    text = html.unescape(text).replace('\\/', '/')
    hrefs = re.findall(r'''(?:href|data-href|data-url)\s*=\s*["']([^"'#]+)''', text, flags=re.I)
    for raw in hrefs:
        yield urljoin(page_url, raw)


def _same_site(hostname, root_host):
    hostname = (hostname or '').lower()
    return hostname == root_host or hostname.endswith('.' + root_host)


def _is_video_url(url, host):
    p = urlsplit(url)
    return _same_site(p.hostname, host) and re.search(r'/(?:videos?|watch)/', p.path, re.I)


def _discover_tag(session, start_url, max_pages=250):
    start = urlsplit(start_url)
    host = (start.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    tag_prefix = start.path.rstrip('/') + '/'
    queue = [start_url]
    seen_pages, videos = set(), []
    while queue and len(seen_pages) < max_pages:
        page = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        sys.stderr.write(f'XMegaDrive: scanning page {len(seen_pages)}: {page}\n')
        try:
            text, final_url = _fetch(session, page)
        except Exception as e:
            sys.stderr.write(f'XMegaDrive: page failed: {type(e).__name__}: {e}\n')
            continue
        for link in _links(final_url, text):
            p = urlsplit(link)
            if _is_video_url(link, host):
                normalized = link.split('#', 1)[0]
                if normalized not in videos:
                    videos.append(normalized)
            elif _same_site(p.hostname, host):
                path = p.path.rstrip('/') + '/'
                same_tag = path.startswith(tag_prefix)
                looks_page = re.search(r'(?:/page/\d+/|/\d+/|[?&](?:page|paged|p)=\d+)', link, re.I)
                if same_tag and looks_page and link not in seen_pages and link not in queue:
                    queue.append(link)
        # Fallback for sites that render relative video paths outside href attributes.
        for match in VIDEO_PATH_RE.findall(text.replace('\\/', '/')):
            link = urljoin(final_url, match)
            if _is_video_url(link, host) and link not in videos:
                videos.append(link)
    return videos


def _format(quality):
    if quality == 'audio':
        return 'ba/b'
    if quality == 'best':
        return 'bv*+ba/b'
    return f'bv*[height<={quality}]+ba/b[height<={quality}]'


def _direct_media(session, page_url):
    try:
        text, _ = _fetch(session, page_url)
    except Exception:
        return []
    cleaned = html.unescape(text).replace('\\/', '/').replace('\\u0026', '&')
    found = []
    for u in MEDIA_URL_RE.findall(cleaned):
        if u not in found:
            found.append(u)
    return found


def _download_one(url, folder, quality, cookiefile=None, force=False, session=None):
    import yt_dlp
    before = {p.resolve() for p in Path(folder).rglob('*') if p.is_file()}

    def progress(d):
        if d.get('status') != 'downloading':
            return
        payload = {
            'downloaded_bytes': d.get('downloaded_bytes') or 0,
            'total_bytes': d.get('total_bytes'),
            'total_bytes_estimate': d.get('total_bytes_estimate'),
            'speed': d.get('speed'),
            'eta': d.get('eta'),
        }
        import json
        print('YPROGRESS:' + json.dumps(payload, ensure_ascii=False), flush=True)

    opts = {
        'format': _format(quality),
        'paths': {'home': str(folder)},
        'outtmpl': '%(title,description|منشور).120s___YID___%(id)s.%(ext)s',
        'windowsfilenames': True,
        'trim_file_name': 160,
        'continuedl': True,
        'overwrites': bool(force),
        'noplaylist': True,
        'retries': 3,
        'socket_timeout': 30,
        'merge_output_format': 'mp4',
        'cookiefile': cookiefile,
        'http_headers': {'User-Agent': UA, 'Referer': url},
        'progress_hooks': [progress],
        'quiet': False,
        'no_warnings': False,
    }
    if quality == 'audio':
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]

    attempts = [url]
    if session is not None:
        for direct in _direct_media(session, url):
            if direct not in attempts:
                attempts.append(direct)

    last = None
    for target in attempts:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([target])
            after = [p.resolve() for p in Path(folder).rglob('*') if p.is_file() and p.resolve() not in before]
            if after:
                for p in after:
                    print('YFILE:' + str(p), flush=True)
                return True
        except Exception as e:
            last = e
            sys.stderr.write(f'XMegaDrive: download attempt failed for {target}: {type(e).__name__}: {e}\n')
    if last:
        raise last
    return False


def _read_archive(path):
    p = Path(path)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()}


def _append_archive(path, url):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(url + '\n')


def run(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--url', required=True)
    ap.add_argument('--folder', required=True)
    ap.add_argument('--archive', required=True)
    ap.add_argument('--quality', default='best')
    ap.add_argument('--cookies')
    ap.add_argument('--force', action='store_true')
    ns = ap.parse_args(argv)

    folder = Path(ns.folder)
    folder.mkdir(parents=True, exist_ok=True)
    session = _session(ns.cookies)
    parts = [p for p in urlsplit(ns.url).path.split('/') if p]
    host = (urlsplit(ns.url).hostname or '').lower().removeprefix('www.')
    is_collection = (len(parts) >= 2 and parts[0].lower() in ('tag', 'tags')) or (host == 'x-fetish.tube' and (not parts or parts[0].lower() in ('models', 'videos')))
    urls = _discover_tag(session, ns.url) if is_collection else [ns.url]
    if not urls:
        sys.stderr.write('Downloader: no video links found on collection page.\n')
        return 2

    done = _read_archive(ns.archive)
    ok = failed = skipped = 0
    for index, video_url in enumerate(urls, 1):
        if not ns.force and video_url in done:
            print('YSKIP:' + video_url, flush=True)
            skipped += 1
            continue
        sys.stderr.write(f'XMegaDrive: downloading {index}/{len(urls)}: {video_url}\n')
        try:
            if _download_one(video_url, folder, ns.quality, ns.cookies, ns.force, session):
                _append_archive(ns.archive, video_url)
                done.add(video_url)
                ok += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    if ok:
        return 0 if failed == 0 else 3
    if skipped and failed == 0:
        return 0
    return 4


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
