"""Self-update the app from the official GitHub release and update download engines."""
import hashlib, json, os, urllib.request, uuid, subprocess, sys, tempfile, zipfile, shutil, time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from packaging.version import Version
from .version import APP_VERSION, UPDATE_REPO, UPDATE_ASSET

SOURCES={
    'video': {'repo':'yt-dlp/yt-dlp-nightly-builds','asset':'yt-dlp.exe'},
    'gallery': {'repo':'gdl-org/builds','asset':'gallery-dl_windows.exe'},
}
USER_AGENT='YasserSocialDownloader/'+APP_VERSION


def _github_json(url, timeout=30):
    req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return json.load(response)


def latest_app_release(timeout=30):
    """Return (version, asset_url, sha256) for our own latest GitHub release."""
    meta=_github_json('https://api.github.com/repos/'+UPDATE_REPO+'/releases/latest',timeout=timeout)
    version=str(meta.get('tag_name','')).lstrip('v')
    Version(version)
    asset=next((a for a in meta.get('assets',[]) if a.get('name')==UPDATE_ASSET),None)
    if asset is None: raise ValueError('الإصدار الجديد لم يوفر حزمة Windows المطلوبة.')
    url=str(asset.get('browser_download_url',''))
    expected='https://github.com/'+UPDATE_REPO+'/releases/download/'
    if not url.startswith(expected): raise ValueError('مصدر تحديث البرنامج غير معتمد.')
    digest=str(asset.get('digest') or '')
    if not digest.startswith('sha256:'): raise ValueError('لم ينشر تحديث البرنامج بصمة SHA-256.')
    return version,url,digest[7:]


def available_app_update(timeout=8):
    """Return the newer app version, or None when this build is current."""
    remote,_,_=latest_app_release(timeout=timeout)
    return remote if Version(remote)>Version(APP_VERSION) else None


def _download_verified(url, sha256, target, max_bytes=700*1024*1024):
    temp=Path(str(target)+'.tmp'); h=hashlib.sha256(); total=0
    try:
        req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
        with urllib.request.urlopen(req,timeout=120) as response,open(temp,'wb') as out:
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>max_bytes: raise ValueError('حجم التحديث غير متوقع.')
                out.write(chunk); h.update(chunk)
        if h.hexdigest().lower()!=sha256.lower(): raise ValueError('فشل التحقق من سلامة تحديث البرنامج.')
        os.replace(temp,target)
    finally:
        if temp.exists(): temp.unlink(missing_ok=True)


def _safe_extract(zpath, dest):
    dest=Path(dest).resolve(); dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            name=info.filename.replace('\\','/')
            if name.startswith('/') or '..' in Path(name).parts: raise ValueError('حزمة التحديث تحتوي مسارًا غير آمن.')
            target=(dest/name).resolve()
            if dest not in target.parents and target!=dest: raise ValueError('حزمة التحديث تحتوي مسارًا غير آمن.')
        zf.extractall(dest)


def _install_dir():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]


def _write_apply_script(staging, install, pid, exe_name):
    """Create a detached Windows cmd script that applies the staged onedir update after exit."""
    script=Path(tempfile.gettempdir())/('YasserSocialDownloader-update-'+uuid.uuid4().hex+'.cmd')
    # Data lives under LOCALAPPDATA, so the install folder can be replaced safely.
    body='''@echo off\r\nsetlocal\r\nset "SRC={src}"\r\nset "DST={dst}"\r\n:wait\r\ntasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\nif not errorlevel 1 (timeout /t 1 /nobreak >NUL & goto wait)\r\nrobocopy "%SRC%" "%DST%" /MIR /R:5 /W:1 >NUL\r\nset "RC=%ERRORLEVEL%"\r\nif %RC% GEQ 8 goto fail\r\nstart "" "%DST%\\{exe}"\r\nrd /s /q "%SRC%" >NUL 2>NUL\r\ndel "%~f0"\r\nexit /b 0\r\n:fail\r\nstart "" "%DST%\\{exe}"\r\nexit /b %RC%\r\n'''.format(src=str(Path(staging).resolve()),dst=str(Path(install).resolve()),pid=int(pid),exe=exe_name)
    script.write_text(body,encoding='utf-8')
    return script


class FullUpdateWorker(QThread):
    result=Signal(str,str) # action, message: none|engines|app_ready|error
    def __init__(self,root): super().__init__(); self.root=Path(root)
    def run(self):
        try:
            # First update the application itself. If no app release is newer, repair engines.
            if getattr(sys,'frozen',False):
                remote,url,digest=latest_app_release()
                if Version(remote)>Version(APP_VERSION):
                    work=self.root/'app-update'; shutil.rmtree(work,ignore_errors=True); work.mkdir(parents=True,exist_ok=True)
                    package=work/'update.zip'; _download_verified(url,digest,package)
                    staging=work/'staging'; _safe_extract(package,staging)
                    # Release ZIP contains the application folder contents at its root.
                    exe=staging/'YasserSocialDownloader.exe'
                    if not exe.exists(): raise ValueError('حزمة التحديث لا تحتوي ملف تشغيل صالحًا.')
                    check=subprocess.run([str(exe),'--version-check'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if check.returncode!=0: raise ValueError('تعذر التحقق من الإصدار الجديد قبل التثبيت.')
                    script=_write_apply_script(staging,_install_dir(),os.getpid(),'YasserSocialDownloader.exe')
                    self.root.joinpath('pending-update.json').write_text(json.dumps({'version':remote,'script':str(script)},ensure_ascii=False),encoding='utf-8')
                    self.result.emit('app_ready','تم تنزيل الإصدار '+remote+' والتحقق منه. سيُغلق البرنامج ويثبّت التحديث ثم يفتح تلقائيًا.')
                    return
            ok,msg=_update_engines(self.root)
            self.result.emit('engines' if ok else 'error',msg)
        except Exception as e:
            self.result.emit('error','تعذر تحديث البرنامج. بقيت النسخة الحالية كما هي. '+(str(e) if isinstance(e,ValueError) else 'تحقق من الاتصال وحاول لاحقًا.'))


class AppUpdateCheckWorker(QThread):
    """Check for an app release without downloading or changing any files."""
    result=Signal(str,str) # action, version/message: available|current|error
    def run(self):
        try:
            if not getattr(sys,'frozen',False):
                self.result.emit('current','')
                return
            remote=available_app_update()
            self.result.emit('available' if remote else 'current',remote or '')
        except Exception:
            # Startup checks stay silent when offline. Manual update remains available.
            self.result.emit('error','')


class UpdateWorker(QThread):
    """Backward-compatible engine-only worker used by tests/older UI paths."""
    result=Signal(bool,str)
    def __init__(self,root): super().__init__(); self.root=Path(root)
    def run(self):
        ok,msg=_update_engines(self.root); self.result.emit(ok,msg)


def _update_engines(root):
    created=[]
    try:
        root=Path(root);dest=root/'engines';dest.mkdir(exist_ok=True)
        updates={};versions=engine_versions(root);changed=False;current=dest/'current.json'
        if current.exists():
            try:
                previous=json.loads(current.read_text(encoding='utf-8'))
                updates={kind:entry for kind,entry in previous.items() if kind in SOURCES and updated_engine(root,kind)}
            except (ValueError,AttributeError): pass
        for kind,source in SOURCES.items():
            repo,name=source['repo'],source['asset']
            meta=_github_json('https://api.github.com/repos/'+repo+'/releases/latest')
            remote_version=str(meta['tag_name']).lstrip('v')
            if Version(remote_version)<=Version(str(versions[kind]).lstrip('v')): continue
            asset=next((a for a in meta['assets'] if a['name']==name),None)
            if asset is None: raise ValueError('الإصدار الجديد لم يوفر ملف Windows الرسمي بعد.')
            digest=asset.get('digest') or ''
            if not digest.startswith('sha256:'): raise ValueError('لم ينشر المصدر بصمة تحقق SHA-256 لهذا الإصدار.')
            url=asset['browser_download_url']
            if not url.startswith('https://github.com/'+repo+'/releases/download/'): raise ValueError('مصدر تحديث غير معتمد.')
            target=dest/(kind+'-'+uuid.uuid4().hex+'.exe'); _download_verified(url,digest[7:],target,max_bytes=150*1024*1024);created.append(target)
            check=subprocess.run([str(target),'--version'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if check.returncode!=0 or not check.stdout.strip(): raise ValueError('تعذر تشغيل محرك التحديث؛ لن يتم تفعيله.')
            updates[kind]={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'version':remote_version};changed=True
        if changed:
            temp=dest/'current.tmp';temp.write_text(json.dumps(updates),encoding='utf-8');os.replace(temp,current)
        return True,('تم تحديث البرنامج وأدوات التحميل المتاحة والتحقق منها.' if changed else 'البرنامج وأدوات التحميل محدثة ولا يلزم تنزيل شيء جديد.')
    except Exception as e:
        for path in created:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        return False,'تعذر تحديث أدوات التحميل؛ بقيت المحركات الحالية سليمة. '+(str(e) if isinstance(e,ValueError) else 'تحقق من الاتصال أو حاول لاحقًا.')


def launch_pending_update(root):
    pending=Path(root)/'pending-update.json'
    if not pending.exists(): return False
    try:
        data=json.loads(pending.read_text(encoding='utf-8')); script=Path(data['script'])
        if not script.exists(): raise ValueError()
        flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'DETACHED_PROCESS',0)|getattr(subprocess,'CREATE_NO_WINDOW',0)
        subprocess.Popen(['cmd.exe','/c',str(script)],creationflags=flags,close_fds=True)
        return True
    except Exception:
        return False
    finally:
        pending.unlink(missing_ok=True)


def updated_engine(root,kind):
    manifest=Path(root)/'engines'/'current.json'
    if not manifest.exists():return None
    try:
        entry=json.loads(manifest.read_text(encoding='utf-8'))[kind];path=Path(entry['path']).resolve()
        if path.parent!=(Path(root)/'engines').resolve():return None
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:return None
        return str(path)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def engine_versions(root):
    from yt_dlp.version import __version__ as video
    from gallery_dl.version import __version__ as gallery
    versions={'video':video,'gallery':gallery};manifest=Path(root)/'engines'/'current.json'
    if manifest.exists():
        try:
            entries=json.loads(manifest.read_text(encoding='utf-8'))
            for kind in versions:
                if updated_engine(root,kind):
                    candidate=entries[kind]['version'];Version(candidate);versions[kind]=candidate
        except (OSError,ValueError,KeyError,TypeError):pass
    return versions
