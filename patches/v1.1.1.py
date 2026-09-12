from pathlib import Path

# Version
p=Path('app/version.py'); s=p.read_text(encoding='utf-8'); s=s.replace("APP_VERSION = '1.1.0'","APP_VERSION = '1.1.1'"); p.write_text(s,encoding='utf-8')

# TikTok: profile discovery keeps photos in gallery-dl, videos are downloaded only in strict-audio yt-dlp pass.
p=Path('app/backend.py'); s=p.read_text(encoding='utf-8')
old="""        if profile:\n            args += ['-o', 'extractor.tiktok.user.include=posts']\n        # gallery-dl discovers the profile; yt-dlp is used only internally for streams that need it.\n        args += [\n            '-o', 'extractor.tiktok.photos=true',\n            '-o', 'extractor.tiktok.videos=true',\n            '-o', 'extractor.tiktok.posts.ytdl=true',\n            '-o', 'extractor.tiktok.posts.module=yt_dlp',\n        ]"""
new="""        if profile:\n            args += ['-o', 'extractor.tiktok.user.include=posts']\n        # Profile videos are handled only by the dedicated yt-dlp pass. This prevents\n        # a silent stream from being archived by gallery-dl before audio validation.\n        args += [\n            '-o', 'extractor.tiktok.photos=true',\n            '-o', f'extractor.tiktok.videos={\"false\" if profile else \"true\"}',\n            '-o', 'extractor.tiktok.posts.ytdl=false' if profile else 'extractor.tiktok.posts.ytdl=true',\n            '-o', 'extractor.tiktok.posts.module=yt_dlp',\n        ]"""
if old not in s: raise SystemExit('backend TikTok block not found')
s=s.replace(old,new)
s=s.replace("fmt = 'b[acodec!=none]/bv*+ba/b'","fmt = 'bv*[acodec=none]+ba/b[acodec!=none]'")
s=s.replace("fmt = 'ba/b[acodec!=none]/b'","fmt = 'ba/b[acodec!=none]'")
s=s.replace("fmt = f'b[height<={q}][acodec!=none]/bv*[height<={q}]+ba/b[height<={q}]'","fmt = f'bv*[height<={q}][acodec=none]+ba/b[height<={q}][acodec!=none]'")
p.write_text(s,encoding='utf-8')

# Facebook: after static HTML, try yt-dlp playlist discovery and then rendered Edge DOM.
p=Path('app/facebook_engine.py'); s=p.read_text(encoding='utf-8')
s=s.replace('import sys\n', 'import sys\nimport os\nimport subprocess\nimport tempfile\n')
insert=r'''

def _edge_candidates():
    paths=[]
    for base in (os.environ.get('PROGRAMFILES(X86)'),os.environ.get('PROGRAMFILES'),os.environ.get('LOCALAPPDATA')):
        if base: paths.append(Path(base)/'Microsoft'/'Edge'/'Application'/'msedge.exe')
    return [p for p in paths if p.exists()]


def _discover_with_edge(profile_url, timeout=40):
    edges=_edge_candidates()
    if not edges: return [],['edge-not-found']
    errors=[]; found=[]
    for target in _seed_urls(profile_url)[:8]:
        try:
            with tempfile.TemporaryDirectory(prefix='ysd-fb-edge-') as profile:
                proc=subprocess.run([str(edges[0]),'--headless=new','--disable-gpu','--disable-extensions','--no-first-run','--no-default-browser-check','--disable-background-networking','--user-data-dir='+profile,'--dump-dom',target],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                for u in _extract_video_urls(proc.stdout or ''):
                    if u not in found: found.append(u)
                if found: break
                if proc.returncode: errors.append('edge-exit-'+str(proc.returncode))
        except subprocess.TimeoutExpired: errors.append('edge-timeout')
        except OSError as exc: errors.append(type(exc).__name__)
    return found,errors


def _discover_with_ytdlp(profile_url, cookie_path=None):
    try: import yt_dlp
    except Exception: return [],['ytdlp-unavailable']
    found=[]; errors=[]
    opts={'quiet':True,'no_warnings':True,'skip_download':True,'extract_flat':True,'ignoreerrors':True}
    if cookie_path: opts['cookiefile']=cookie_path
    for target in _seed_urls(profile_url)[:8]:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(target,download=False)
            stack=[info] if info else []
            while stack:
                node=stack.pop()
                if not isinstance(node,dict): continue
                if node.get('entries'): stack.extend(x for x in node['entries'] if x)
                for key in ('webpage_url','url','original_url'):
                    value=node.get(key)
                    if isinstance(value,str):
                        canon=_canonical_video_url(value)
                        if canon and canon not in found: found.append(canon)
                vid=str(node.get('id') or '')
                if vid.isdigit() and len(vid)>=6:
                    u='https://www.facebook.com/watch/?v='+vid
                    if u not in found: found.append(u)
            if found: break
        except Exception as exc: errors.append(type(exc).__name__)
    return found,errors
'''
marker='def _quality_format(quality):\n'
if marker not in s: raise SystemExit('facebook marker not found')
s=s.replace(marker,insert+'\n'+marker)
old="""    urls, errors = discover_video_urls(ns.url, ns.cookies)\n    print(f'YFBDISCOVER:{len(urls)}', flush=True)\n    if not urls:\n        detail = ','.join(errors[-3:]) if errors else 'no-links'\n        print(f'[facebook][error] Could not discover profile video links ({detail})', flush=True)\n        return 4\n"""
new="""    urls, errors = discover_video_urls(ns.url, ns.cookies)\n    if not urls:\n        more, err = _discover_with_ytdlp(ns.url, ns.cookies)\n        urls.extend(u for u in more if u not in urls); errors.extend(err)\n    if not urls:\n        more, err = _discover_with_edge(ns.url)\n        urls.extend(u for u in more if u not in urls); errors.extend(err)\n    print(f'YFBDISCOVER:{len(urls)}', flush=True)\n    if not urls:\n        detail = ','.join(errors[-5:]) if errors else 'no-links'\n        print(f'[facebook][error] Could not discover profile video links ({detail})', flush=True)\n        return 4\n"""
if old not in s: raise SystemExit('facebook run block not found')
s=s.replace(old,new); p.write_text(s,encoding='utf-8')

# About page contact info.
p=Path('app/ui.py'); s=p.read_text(encoding='utf-8')
old="""        v.addWidget(label('الإيقاف يوقف عملية التنزيل؛ الاستكمال يعيد تشغيل المحرك باستخدام الأجزاء والأرشيف حيث يتوفر الدعم. لا تُحذف الأجزاء عند الإلغاء.','muted'));v.addWidget(label('استعمل البرنامج لحفظ المحتوى الذي تملك حق الوصول إليه وتنزيله. لا يطلب البرنامج اسم مستخدم أو كلمة مرور ولا يجمع قياسات استخدام.','muted'));v.addStretch()"""
new="""        v.addWidget(label('الإيقاف يوقف عملية التنزيل؛ الاستكمال يعيد تشغيل المحرك باستخدام الأجزاء والأرشيف حيث يتوفر الدعم. لا تُحذف الأجزاء عند الإلغاء.','muted'));v.addWidget(label('استعمل البرنامج لحفظ المحتوى الذي تملك حق الوصول إليه وتنزيله. لا يطلب البرنامج اسم مستخدم أو كلمة مرور ولا يجمع قياسات استخدام.','muted'))\n        v.addWidget(label('التواصل','brand'));v.addWidget(label('واتساب: 07721754555 • فيسبوك: المصور ياسر الطائي','muted'))\n        r=QHBoxLayout();r.addWidget(button('فتح واتساب',lambda:QDesktopServices.openUrl(QUrl('https://wa.me/9647721754555'))));r.addWidget(button('فتح صفحة المصور ياسر الطائي',lambda:QDesktopServices.openUrl(QUrl('https://www.facebook.com/id13201'))));v.addLayout(r);v.addStretch()"""
if old not in s: raise SystemExit('ui about block not found')
s=s.replace(old,new); p.write_text(s,encoding='utf-8')

# Tests for the new routing behavior.
p=Path('tests/test_backend_routing.py'); s=p.read_text(encoding='utf-8')
s=s.replace("self.assertEqual(engine,'gallery'); self.assertIn('extractor.tiktok.posts.ytdl=true',text); self.assertIn('extractor.tiktok.posts.module=yt_dlp',text)","self.assertEqual(engine,'gallery'); self.assertIn('extractor.tiktok.videos=false',text); self.assertIn('extractor.tiktok.posts.ytdl=false',text); self.assertIn('extractor.tiktok.posts.module=yt_dlp',text)")
p.write_text(s,encoding='utf-8')
