import json, sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit


def resource():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def _path_parts(url):
    return [p for p in urlsplit(url).path.split('/') if p]


def is_profile_url(platform, url):
    parts = _path_parts(url)
    if platform == 'instagram':
        return len(parts) == 1 and parts[0] not in ('p', 'reel', 'reels', 'stories')
    if platform == 'twitter':
        return len(parts) == 1 and parts[0] not in ('i', 'search')
    if platform == 'tiktok':
        return len(parts) == 1 and parts[0].startswith('@')
    if platform == 'facebook':
        # Profile/page roots and /videos are profile-like. Individual reel/watch/posts are not.
        lower = [p.lower() for p in parts]
        return not any(p in ('reel', 'reels', 'watch', 'photo.php', 'posts', 'videos.php') for p in lower[1:]) and 'watch' not in lower[:1]
    return False


def _safe_folder_name(value):
    """Return a Windows-safe, human-readable folder name."""
    value = unquote(value or '').strip().lstrip('@')
    value = ''.join('_' if ord(char) < 32 or char in '<>:"/\\|?*' else char for char in value)
    value = ' '.join(value.split()).rstrip(' .')[:80]
    if not value:
        return 'profile'
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{name}{number}' for name in ('COM', 'LPT') for number in range(1, 10)}
    return value + '_profile' if value.upper() in reserved else value


def profile_username(platform, url):
    """Extract a stable username/page identifier from a profile URL."""
    if not is_profile_url(platform, url):
        return None
    parsed = urlsplit(url)
    parts = _path_parts(url)
    if platform == 'tiktok':
        candidate = parts[0].lstrip('@')
    elif platform == 'facebook' and parts and parts[0].lower() == 'profile.php':
        candidate = parse_qs(parsed.query).get('id', ['facebook-profile'])[0]
    elif platform == 'facebook' and parts and parts[0].lower() == 'people' and len(parts) > 1:
        candidate = parts[-1] if parts[-1].isdigit() else parts[1]
    else:
        candidate = parts[0] if parts else platform + '-profile'
    return _safe_folder_name(candidate)


def prepare_profile_folder(task):
    """Isolate every profile download under platform/username."""
    username = profile_username(task['platform'], task['url'])
    if not username:
        return Path(task['folder'])
    if task.get('profile_folder'):
        task['folder'] = task['profile_folder']
        return Path(task['profile_folder'])
    folder = Path(task['folder'])
    if folder.name.casefold() != task['platform'].casefold():
        folder /= task['platform']
    folder /= username
    task['profile_username'] = username
    task['profile_folder'] = str(folder)
    task['folder'] = str(folder)
    return folder


def _twitter_timeline_url(url):
    p = urlsplit(url)
    path = p.path.rstrip('/')
    for suffix in ('/media', '/tweets', '/with_replies', '/timeline'):
        if path.lower().endswith(suffix):
            path = path[:-len(suffix)]
            break
    path += '/timeline'
    return urlunsplit((p.scheme, p.netloc, path, '', ''))


def _facebook_videos_url(url):
    p = urlsplit(url)
    path = p.path.rstrip('/')
    if not path.lower().endswith('/videos'):
        path += '/videos'
    return urlunsplit((p.scheme, p.netloc, path, '', ''))


def _gallery_args(task, store, cookie_path, target_url):
    folder = Path(task['folder'])
    folder.mkdir(parents=True, exist_ok=True)
    archive = str(store.root / ('archive-' + task['id'] + '.sqlite3'))
    args = [
        '--config-ignore', '--no-input', '--no-colors', '--verbose',
        '-D', str(folder),
        '--Print', 'after:YFILE:{_path}',
        '--Print', 'skip:YSKIP:{_path}',
        '--windows-filenames', '-o', 'output.mode=null',
    ]
    if not task['force']:
        args += ['--download-archive', archive]
    else:
        args += ['--no-skip']

    platform = task['platform']
    media = task['media']
    profile = is_profile_url(platform, task['url'])

    # Metadata keys differ across platforms. Prefer the post's own text over
    # generic account titles and image alt text. The application removes the
    # temporary .1 suffix after gallery-dl saves the file.
    names = {
        'twitter': 'content|title|description',
        'instagram': 'description|caption|title',
        'tiktok': 'title|description',
        'facebook': 'caption|content|title|description',
    }
    fields = names.get(platform, 'content|caption|title|description')
    args += [
        '--filename', '{' + fields + '|_lit[منشور]!W:X120//}.{extension}',
        '-o', 'extractor.skip=enumerate',
    ]
    if platform == 'instagram':
        args += [
            # Instagram may expose DASH video and audio as separate streams.  The
            # "merged" mode selects Instagram's progressive video URL so the final
            # file already contains its audio.  Music/audio attachments remain off.
            '-o', 'extractor.instagram.videos=merged',
            '-o', 'extractor.instagram.audio=false',
        ]
        if profile:
            # New Instagram fixes land in gallery-dl dev builds first. Include both feed posts and reels.
            include = 'reels' if task.get('phase') == 'instagram_reels' else 'posts'
            args += ['-o', f'extractor.instagram.include={include}', '-o', 'extractor.instagram.user-strategy=search,web']
    elif platform == 'twitter':
        if profile:
            # Use the timeline extractor because it supports cursor resume. Keep media-only behavior
            # by disabling text tweets and prefer the maintained tweets strategy.
            args += [
                '-o', 'extractor.twitter.text-tweets=false',
                '-o', 'extractor.twitter.timeline.strategy=tweets',
                '-o', 'extractor.twitter.ratelimit=wait',
                '-o', 'extractor.twitter.locked=wait',
            ]
            cursor = task.get('twitter_cursor')
            if cursor:
                args += ['-o', f'extractor.twitter.cursor={cursor}']
    elif platform == 'tiktok':
        if profile:
            args += ['-o', 'extractor.tiktok.user.include=posts']
        # gallery-dl discovers the profile; yt-dlp is used only internally for streams that need it.
        args += [
            '-o', 'extractor.tiktok.photos=true',
            '-o', 'extractor.tiktok.videos=true',
            '-o', 'extractor.tiktok.posts.ytdl=true',
            '-o', 'extractor.tiktok.posts.module=yt_dlp',
        ]
    elif platform == 'facebook':
        # "include" controls profile subcategories. "videos" controls encountered video media.
        args += ['-o', 'extractor.facebook.include=all', '-o', 'extractor.facebook.videos=ytdl']

    video_exts = "('mp4', 'webm', 'mkv', 'mov', 'm4v')"
    filters = []
    if media == 'images':
        filters.append(f'extension not in {video_exts}')
        if platform == 'tiktok':
            args += ['-o', 'extractor.tiktok.videos=false']
        if platform == 'facebook':
            args += ['-o', 'extractor.facebook.videos=false']
    elif media == 'video' and profile:
        # Profile video-only must stay on gallery-dl; yt-dlp cannot reliably treat all profile URLs as playlists.
        filters.append(f'extension in {video_exts}')
        if platform == 'instagram':
            args += ['-o', 'extractor.instagram.include=reels']

    if filters:
        args += ['--filter', ' and '.join(f'({item})' for item in filters)]

    if cookie_path:
        args += ['--cookies', cookie_path]
    return args + ['--', target_url]


def _video_args(task, store, cookie_path, target_url):
    folder = Path(task['folder'])
    folder.mkdir(parents=True, exist_ok=True)
    archive = str(store.root / ('archive-' + task['id'] + '.txt'))
    if task.get('platform') == 'tiktok' and task.get('phase') == 'tiktok_ytdlp':
        # TikTok has had a 2026 site bug where cookie-backed format selection can
        # intermittently choose a video stream without audio. Prefer a muxed format
        # with audio first, then fall back to explicit video+audio merging.
        if task['quality'] == 'best':
            fmt = 'b[acodec!=none]/bv*+ba/b'
        elif task['quality'] == 'audio':
            fmt = 'ba/b[acodec!=none]/b'
        else:
            q = task['quality']
            fmt = f'b[height<={q}][acodec!=none]/bv*[height<={q}]+ba/b[height<={q}]'
    else:
        fmt = 'bv*+ba/b' if task['quality'] == 'best' else 'ba/b' if task['quality'] == 'audio' else 'bv*[height<=' + task['quality'] + ']+ba/b[height<=' + task['quality'] + ']'
    args = [
        '--ignore-config', '--encoding', 'utf-8', '--no-colors', '--newline', '--verbose',
        '--windows-filenames', '--trim-filenames', '160', '--continue', '--no-overwrites',
        '--socket-timeout', '30', '--retries', '3', '-P', str(folder),
        '-o', ('%(description,title|منشور).120s' if task.get('platform') in ('twitter', 'tiktok')
               else '%(title,description|منشور).120s') + '___YID___%(id)s.%(ext)s', '-f', fmt,
        '--progress-template', 'download:YPROGRESS:%(progress)j',
        '--print', 'after_move:YFILE:%(filepath)s',
    ]
    ff = resource() / 'tools' / 'ffmpeg.exe'
    if ff.exists():
        args += ['--ffmpeg-location', str(ff)]
    if task['quality'] == 'audio':
        args += ['--extract-audio', '--audio-format', 'mp3']
    if not task['force']:
        args += ['--download-archive', archive]
    else:
        args += ['--force-overwrites']
    # TikTok/yt-dlp currently has an intermittent site bug where supplying cookies
    # can select a video variant without audio. The first gallery pass may still use
    # cookies for profile discovery, but this recovery pass deliberately avoids them.
    use_cookie = cookie_path and not (task.get('platform') == 'tiktok' and task.get('phase') == 'tiktok_ytdlp')
    if use_cookie:
        args += ['--cookies', cookie_path]
    if task.get('platform') == 'tiktok' and task.get('phase') == 'tiktok_ytdlp':
        args += ['--merge-output-format', 'mp4']
    return args + ['--', target_url]


def command(task, store, cookie_path=None):
    """Return command argv and engine.

    Profile/account URLs are intentionally kept on gallery-dl.  The previous generic
    fallback to yt-dlp was the cause of the repeated ``engine=video`` failures for
    Instagram, X and TikTok profiles.
    """
    prepare_profile_folder(task)

    if task['cookies'] and not cookie_path:
        raise ValueError('تعذر تجهيز نسخة مؤقتة من ملف الكوكيز')

    phase = task.get('phase', 'primary')
    target_url = task['url']
    profile = is_profile_url(task['platform'], task['url'])

    if phase == 'facebook_videos':
        engine = 'facebook'
    elif phase == 'facebook_video_ytdlp':
        # Backward compatibility for tasks saved by v1.0.7. Route them to the new
        # profile-video discovery engine instead of yt-dlp on /videos.
        engine = 'facebook'
    elif phase == 'tiktok_ytdlp':
        engine = 'video'
    elif platform := task.get('platform'):
        if platform == 'twitter' and profile:
            engine = 'gallery'
            target_url = _twitter_timeline_url(task['url'])
        elif profile:
            engine = 'gallery'
        elif task['media'] == 'video':
            engine = 'video'
        else:
            engine = 'gallery'

    prefix = [sys.executable, '--engine', engine] if getattr(sys, 'frozen', False) else [sys.executable, str(resource() / 'main.py'), '--engine', engine]
    external = None
    if engine in ('gallery', 'video'):
        try:
            from .updater import updated_engine
            external = updated_engine(store.root, engine)
        except ModuleNotFoundError as exc:
            # Allows dependency-light routing tests; packaged builds always include PySide6/updater.
            if not (exc.name and exc.name.startswith('PySide6')):
                raise
    if external:
        prefix = [external]

    if engine == 'gallery':
        args = _gallery_args(task, store, cookie_path if task['cookies'] else None, target_url)
    elif engine == 'video':
        args = _video_args(task, store, cookie_path if task['cookies'] else None, target_url)
    else:
        folder = Path(task['folder']); folder.mkdir(parents=True, exist_ok=True)
        args = [
            '--url', task['url'], '--folder', str(folder),
            '--archive', str(store.root / ('archive-' + task['id'] + '-facebook-video.txt')),
            '--quality', task['quality'],
        ]
        if cookie_path and task['cookies']:
            args += ['--cookies', cookie_path]
        if task['force']:
            args += ['--force']
    return prefix + args, engine


def engine_main(kind, args):
    if kind == 'gallery':
        import gallery_dl
        sys.argv = ['gallery-dl'] + args
        raise SystemExit(gallery_dl.main())
    if kind == 'facebook':
        from .facebook_engine import run
        raise SystemExit(run(args))
    import yt_dlp
    yt_dlp.main(args)
