import argparse
import html
import re
import sys
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import requests

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36'

_VIDEO_PATTERNS = [
    re.compile(r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/reel/\d+[^\s"\'<>]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/watch/\?v=\d+[^\s"\'<>]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/[^\s"\'<>]+?/videos/\d+[^\s"\'<>]*', re.I),
]
_VIDEO_ID_PATTERNS = [
    re.compile(r'(?i)"video_id"\s*:\s*"?(\d{6,})"?'),
    re.compile(r'(?i)"videoId"\s*:\s*"?(\d{6,})"?'),
    re.compile(r'(?i)video_id[=%3A"\\]+(\d{6,})'),
    re.compile(r'(?is)"__typename"\s*:\s*"Video".{0,500}?"id"\s*:\s*"(\d{6,})"'),
    re.compile(r'(?is)"id"\s*:\s*"(\d{6,})".{0,500}?"__typename"\s*:\s*"Video"'),
    re.compile(r'(?is)"video"\s*:\s*\{.{0,350}?"id"\s*:\s*"(\d{6,})"'),
    re.compile(r'(?is)"media"\s*:\s*\{.{0,350}?"__typename"\s*:\s*"Video".{0,350}?"id"\s*:\s*"(\d{6,})"'),
]
_HREF = re.compile(r'(?i)href=["\']([^"\']+)["\']')


def _profile_parts(url):
    p = urlsplit(url)
    path = p.path.rstrip('/') or '/'
    return p, path


def _seed_urls(url):
    p, path = _profile_parts(url)
    # Facebook's lightweight/mobile endpoints are useful because they often expose
    # pagination as normal links instead of requiring a browser JavaScript runtime.
    seeds = []
    for host in ('www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com'):
        seeds.append(urlunsplit(('https', host, path + '/videos', '', '')))
        seeds.append(urlunsplit(('https', host, path + '/videos_by', '', '')))
        seeds.append(urlunsplit(('https', host, path + '/reels', '', '')))
        seeds.append(urlunsplit(('https', host, path, 'v=videos', '')))
        seeds.append(urlunsplit(('https', host, path, 'sk=videos', '')))
        seeds.append(urlunsplit(('https', host, path, 'sk=reels', '')))
    # preserve exact user URL as a final fallback
    seeds.append(url)
    return list(dict.fromkeys(seeds))


def _load_cookies(session, cookie_path):
    if not cookie_path:
        return
    jar = MozillaCookieJar(cookie_path)
    jar.load(ignore_discard=True, ignore_expires=True)
    session.cookies.update(jar)


def _normalize_text(text):
    text = html.unescape(text)
    text = text.replace('\\u002F', '/').replace('\\/', '/')
    text = text.replace('\\u003A', ':').replace('\\u0026', '&')
    return text


def _canonical_video_url(url):
    url = html.unescape(url).replace('\\u002F', '/').replace('\\/', '/')
    p = urlsplit(url)
    if not p.netloc.lower().endswith('facebook.com'):
        return None
    path = p.path
    m = re.search(r'/reel/(\d+)', path, re.I)
    if m:
        return f'https://www.facebook.com/reel/{m.group(1)}'
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    if path.rstrip('/').lower() == '/watch' and q.get('v', '').isdigit():
        return f'https://www.facebook.com/watch/?v={q["v"]}'
    m = re.search(r'/videos/(\d+)', path, re.I)
    if m:
        return f'https://www.facebook.com/watch/?v={m.group(1)}'
    return None


def _extract_video_urls(text):
    text = _normalize_text(text)
    found = []
    for pattern in _VIDEO_PATTERNS:
        for match in pattern.findall(text):
            url = _canonical_video_url(match)
            if url:
                found.append(url)
    for pattern in _VIDEO_ID_PATTERNS:
        for video_id in pattern.findall(text):
            found.append(f'https://www.facebook.com/watch/?v={video_id}')
    for href in _HREF.findall(text):
        full = urljoin('https://www.facebook.com/', href)
        url = _canonical_video_url(full)
        if url:
            found.append(url)
    return list(dict.fromkeys(found))


def _pagination_links(base_url, text, profile_path):
    text = _normalize_text(text)
    links = []
    for href in _HREF.findall(text):
        full = urljoin(base_url, href)
        p = urlsplit(full)
        if not p.netloc.lower().endswith('facebook.com'):
            continue
        low = full.lower()
        # Follow only likely continuation pages to stay within the requested profile.
        if ('cursor=' in low or 'startindex=' in low or 'after=' in low or 'v=videos' in low or 'sk=videos' in low or 'sk=reels' in low or '/videos' in low or '/reels' in low):
            if profile_path.strip('/').lower() in p.path.lower() or 'cursor=' in low or 'startindex=' in low:
                links.append(full)
    return list(dict.fromkeys(links))


def discover_video_urls(profile_url, cookie_path=None, max_pages=60, timeout=25):
    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
    _load_cookies(session, cookie_path)
    _, profile_path = _profile_parts(profile_url)
    queue = _seed_urls(profile_url)
    seen_pages = set()
    videos = []
    errors = []
    while queue and len(seen_pages) < max_pages:
        url = queue.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code >= 400:
                errors.append(f'HTTP {response.status_code}')
                continue
            text = response.text
            low_text = text.lower()
            if 'login.php' in response.url.lower() or ('log in' in low_text and 'password' in low_text and 'email' in low_text):
                errors.append('facebook-login-required')
            if 'checkpoint' in response.url.lower() or 'temporarily blocked' in low_text:
                errors.append('facebook-checkpoint')
        except requests.RequestException as exc:
            errors.append(type(exc).__name__)
            continue
        for video_url in _extract_video_urls(text):
            if video_url not in videos:
                videos.append(video_url)
        for link in _pagination_links(response.url, text, profile_path):
            if link not in seen_pages and link not in queue:
                queue.append(link)
    return videos, errors


def _quality_format(quality):
    if quality == 'best':
        return 'bv*+ba/b'
    if quality == 'audio':
        return 'ba/b'
    return f'bv*[height<={quality}]+ba/b[height<={quality}]'


def run(args):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--url', required=True)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--quality', default='best')
    parser.add_argument('--cookies')
    parser.add_argument('--force', action='store_true')
    ns = parser.parse_args(args)

    urls, errors = discover_video_urls(ns.url, ns.cookies)
    print(f'YFBDISCOVER:{len(urls)}', flush=True)
    if not urls:
        detail = ','.join(errors[-3:]) if errors else 'no-links'
        print(f'[facebook][error] Could not discover profile video links ({detail})', flush=True)
        return 4

    import yt_dlp
    yargs = [
        '--ignore-config', '--encoding', 'utf-8', '--no-colors', '--newline', '--verbose',
        '--windows-filenames', '--trim-filenames', '160', '--continue', '--no-overwrites',
        '--socket-timeout', '30', '--retries', '5', '-P', ns.folder,
        '-o', '%(title,description|منشور).120s___YID___%(id)s.%(ext)s', '-f', _quality_format(ns.quality),
        '--progress-template', 'download:YPROGRESS:%(progress)j',
        '--print', 'after_move:YFILE:%(filepath)s',
    ]
    if not ns.force:
        yargs += ['--download-archive', ns.archive]
    else:
        yargs += ['--force-overwrites']
    if ns.cookies:
        yargs += ['--cookies', ns.cookies]
    yargs += ['--'] + urls
    try:
        yt_dlp.main(yargs)
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
