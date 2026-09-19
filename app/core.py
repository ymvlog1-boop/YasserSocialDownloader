import json, os, sqlite3, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from http.cookiejar import MozillaCookieJar

PLATFORMS = {'instagram': 'إنستغرام', 'twitter': 'إكس / تويتر', 'facebook': 'فيسبوك', 'tiktok': 'تيك توك'}
DOMAINS = {'instagram.com':'instagram','x.com':'twitter','twitter.com':'twitter','facebook.com':'facebook','fb.watch':'facebook','tiktok.com':'tiktok'}
STATES = {'queued':'بانتظار التحميل','running':'جاري التحميل','paused':'تم الإيقاف مؤقتًا','completed':'تم التحميل بنجاح','partial':'اكتمل جزئيًا','failed':'فشل التحميل','cancelled':'تم الإلغاء','skipped':'محمّل مسبقًا','empty':'لم تُوجد ملفات جديدة'}

def detect(url):
    url=url.strip()
    try:
        if any(ord(c)<32 for c in url):raise ValueError()
        p = urlsplit(url)
        port=p.port
    except ValueError:raise ValueError('الرابط غير صالح') from None
    if p.scheme not in ('http','https') or p.username or p.password or port not in (None,80,443):
        raise ValueError('الرابط غير مدعوم')
    host = (p.hostname or '').lower()
    for domain, platform in DOMAINS.items():
        if host == domain or host.endswith('.'+domain):
            return platform, urlunsplit(('https',host,p.path,p.query,''))
    raise ValueError('الرابط غير مدعوم. استخدم رابطًا من المنصات الأربع.')

def cookie_check(path, platform):
    try:
        jar = MozillaCookieJar(path); jar.load(ignore_discard=True, ignore_expires=True)
        domains = [d for d,p in DOMAINS.items() if p == platform]
        relevant = [c for c in jar if any(c.domain.lstrip('.') == d or c.domain.lstrip('.').endswith('.'+d) for d in domains)]
        if not relevant: return False, 'الملف لا يحتوي كوكيز لهذه المنصة'
        if not any(c.expires is None or c.expires > time.time() for c in relevant): return False, 'انتهت صلاحية الكوكيز'
        return True, 'صالح محليًا — قبول الموقع غير مختبر'
    except Exception:
        return False, 'ملف الكوكيز غير صالح بصيغة Netscape'

def arabic_error(text):
    s = text.lower()
    if 'ip address is blocked' in s:return 'الموقع يرفض عنوان الشبكة الحالي. حاول لاحقًا من اتصال مسموح.'
    if '429' in s or 'rate limit' in s: return 'حدّ الموقع عدد الطلبات. انتظر ثم أعد المحاولة.'
    if any(x in s for x in ('login','cookie','authentication','401','403','private')): return 'يتطلب المحتوى كوكيز صالحة أو صلاحية وصول. اختر ملفًا جديدًا ثم أعد المحاولة.'
    if any(x in s for x in ('no space','permission denied','disk')): return 'تعذر حفظ الملف. تحقق من مساحة القرص وصلاحية المجلد.'
    if any(x in s for x in ('unsupported','not found','404','unavailable','no video')): return 'المحتوى غير متاح أو لا يحتوي فيديو مدعومًا بالمحرك.'
    return 'تعذر إكمال التحميل. تحقق من الاتصال والرابط أو جرّب ملف كوكيز صالحًا.'

class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('YASSER_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'YasserSocialDownloader')
        self.root.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(self.root/'data.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,data TEXT)')
        self.db.commit()
    def get(self,key,default=None):
        row=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value))); self.db.commit()
    def save(self,t):
        self.db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?)',(t['id'],json.dumps(t,ensure_ascii=False))); self.db.commit()
    def tasks(self): return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM tasks ORDER BY rowid')]
    def delete(self,id): self.db.execute('DELETE FROM tasks WHERE id=?',(id,)); self.db.commit()
    def folder(self): return self.get('folder',str(Path.home()/'Downloads'/'Yasser Social Downloader'))

def new_task(url,folder,media='auto',quality='best',cookies=False,force=False):
    platform,url=detect(url)
    return dict(id=uuid.uuid4().hex,url=url,platform=platform,folder=folder,media=media,quality=quality,cookies=cookies,force=force,state='queued',progress=0,files=[],created=time.strftime('%Y-%m-%d %H:%M'),message='',attempt=0)
