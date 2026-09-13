import codecs
import json
import re
import time
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal, QTimer
from .core import arabic_error, cookie_check
from .cookies import CookieCopies
from .backend import command
from .process_tree import ProcessTree


class DownloadManager(QObject):
    changed = Signal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.tasks = store.tasks()
        self.active, self.buffers, self.errors, self.technical = {}, {}, {}, {}
        self.stops, self.trees, self.decoders = {}, {}, {}
        self.cookies = CookieCopies(store.root)
        for task in self.tasks:
            if task['state'] in ('running', 'queued'):
                task.update(state='paused', message='استعد التحميل عند الرغبة؛ تُستكمل الأجزاء حيث يدعم المحرك ذلك.')
                store.save(task)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.pump)
        self.timer.start(600)

    def add(self, task):
        duplicate = any(
            old['url'] == task['url'] and old['media'] == task['media']
            and old['quality'] == task['quality'] and old['folder'] == task['folder']
            and (old['state'] in ('queued', 'running', 'paused') or
                 old['state'] == 'completed' and old['files'] and all(Path(p).is_file() for p in old['files']))
            for old in self.tasks)
        if not task['force'] and duplicate:
            task.update(state='skipped', message='الرابط موجود في القائمة أو ملفاته مكتملة. يمكن فرض إعادة التنزيل من الخيارات.')
        self.tasks.append(task)
        self.store.save(task)
        self.changed.emit()

    def pump(self):
        for task in self.tasks:
            if len(self.active) >= self.store.get('concurrent', 2):
                break
            if task['state'] == 'queued':
                if task.get('resume_at', 0) > time.time():
                    continue
                task.pop('resume_at', None)
                self.start(task)

    def start(self, task):
        task_id = task['id']
        if task_id in self.active:
            return
        try:
            cookie = self.cookies.create(task_id, self.store.get('cookie_' + task['platform']), task['platform']) if task['cookies'] else None
            args, engine = command(task, self.store, cookie_path=cookie)
            process = QProcess(self)
            process.setProcessChannelMode(QProcess.MergedChannels)
            env = QProcessEnvironment.systemEnvironment()
            env.insert('PYTHONIOENCODING', 'utf-8')
            env.insert('PYTHONUTF8', '1')
            process.setProcessEnvironment(env)
            self.active[task_id] = process
            self.buffers[task_id] = ''
            self.errors[task_id] = ''
            self.technical[task_id] = ''
            self.decoders[task_id] = codecs.getincrementaldecoder('utf-8')(errors='replace')
            task.update(engine=engine, state='running', message='جاري الاتصال بالموقع…',
                        attempt=task.get('attempt', 0) + 1, skipped_count=0, attempt_files=0)
            process.started.connect(lambda: self.trees.update({task_id: ProcessTree(process.processId())}))
            process.readyReadStandardOutput.connect(lambda: self.read(task, process))
            process.finished.connect(lambda code, status: self.finished(task, code))
            process.errorOccurred.connect(lambda error: self.process_error(task, error))
            self.store.save(task)
            process.start(args[0], args[1:])
            self.changed.emit()
        except Exception as error:
            self.cookies.remove(task_id)
            process = self.active.pop(task_id, None)
            if process:
                process.kill()
                process.deleteLater()
            task.update(state='failed', message=str(error) if isinstance(error, ValueError) else 'تعذر بدء التنزيل أو إنشاء المجلد.')
            self.store.save(task)
            self.changed.emit()

    def process_error(self, task, error):
        if error == QProcess.FailedToStart:
            self.finished(task, -1)

    def read(self, task, process):
        self.feed(task, bytes(process.readAllStandardOutput()))

    def feed(self, task, data, final=False):
        task_id = task['id']
        decoder = self.decoders.get(task_id)
        if decoder is None:
            return
        text = decoder.decode(data, final=final).replace('\r', '\n')
        pending = self.buffers.get(task_id, '') + text
        lines = pending.split('\n')
        self.buffers[task_id] = lines.pop()
        if final and self.buffers[task_id]:
            lines.append(self.buffers[task_id])
            self.buffers[task_id] = ''
        if len(self.buffers[task_id]) > 2_000_000:
            self.buffers[task_id] = ''
        for line in lines:
            self.parse_line(task, line)
        self.changed.emit()

    def parse_line(self, task, line):
        task_id = task['id']
        if line.startswith('YPROGRESS:'):
            try:
                data = json.loads(line[10:])
                total = data.get('total_bytes') or data.get('total_bytes_estimate')
                done = data.get('downloaded_bytes') or 0
                task['progress'] = min(99, int(done * 100 / total)) if total else -1
                speed, eta = data.get('speed') or 0, data.get('eta')
                task['message'] = f"الحجم المحمّل: {done / 1048576:.1f} MB • السرعة: {speed / 1048576:.1f} MB/s • المتبقي: {eta if eta is not None else '—'} ث"
            except (ValueError, TypeError, AttributeError, OverflowError):
                pass
        elif line.startswith('YFILE:'):
            path = line[6:]
            if path:
                task['attempt_files'] = task.get('attempt_files', 0) + 1
                if path not in task['files']:
                    task['files'].append(path)
                task['message'] = f"عدد الملفات المكتملة: {len(task['files'])}"
                self.store.save(task)
        elif line.startswith('YSKIP:') or any(marker in line for marker in ('has already been recorded in the archive', 'has already been downloaded')):
            task['skipped_count'] = task.get('skipped_count', 0) + 1
        elif line.startswith('YFBDISCOVER:'):
            try:
                count = int(line.split(':', 1)[1])
                task['facebook_discovered'] = count
                task['message'] = f'تم اكتشاف {count} رابط فيديو في فيسبوك؛ جاري التنزيل…' if count else 'لم يتم اكتشاف روابط فيديو في صفحة فيسبوك.'
            except ValueError:
                pass
        elif task.get('platform') == 'twitter' and 'cursor=' in line and ('continue' in line.lower() or '[twitter][info]' in line.lower()):
            match = re.search(r'cursor=([^\s\'"]+)', line)
            if match:
                candidate = match.group(1).rstrip('.,;)]}')
                if candidate:
                    task['twitter_cursor_candidate'] = candidate
        elif line.strip():
            low = line.lower()
            if 'error' in low or 'exception' in low or 'unsupported url' in low:
                self.errors[task_id] = arabic_error(line)
                safe = re.sub(r'https?://\S+', '[URL]', line.strip())
                safe = re.sub(r'(?i)(cookie|authorization|x-csrf-token)\s*[:=]\s*\S+', r'\1=[hidden]', safe)
                self.technical[task_id] = safe[:1200]
            elif not self.errors.get(task_id):
                self.errors[task_id] = arabic_error(line)

    def finished(self, task, code):
        task_id = task['id']
        process = self.active.pop(task_id, None)
        if process is None:
            return
        self.read(task, process)
        self.feed(task, b'', final=True)
        tree = self.trees.pop(task_id, None)
        if tree:
            tree.close()
        self.cookies.remove(task_id)
        stop = self.stops.pop(task_id, None)
        error = self.errors.pop(task_id, '')
        technical = self.technical.pop(task_id, '')
        self.buffers.pop(task_id, None)
        self.decoders.pop(task_id, None)

        profile = __import__('app.backend', fromlist=['is_profile_url']).is_profile_url(task['platform'], task['url'])
        phase = task.get('phase', 'primary')
        diagnostic_phase = phase

        # Platform-specific multi-pass strategy. Instagram/TikTok paths are intentionally unchanged
        # from v1.0.7 because they are working for the user. Facebook now uses a dedicated discovery
        # pass, while X can automatically resume from gallery-dl's logged cursor.
        next_phase = None
        next_message = None
        delayed_resume = False
        if not stop and profile:
            if task['platform'] == 'twitter' and code != 0:
                cursor = task.pop('twitter_cursor_candidate', None)
                previous = task.get('twitter_cursor')
                count = int(task.get('twitter_resume_count', 0))
                if cursor and cursor != previous and count < 12:
                    count += 1
                    task['twitter_cursor'] = cursor
                    task['twitter_resume_count'] = count
                    wait_seconds = min(30 * (2 ** (count - 1)), 300)
                    task['resume_at'] = time.time() + wait_seconds
                    next_phase = 'twitter_resume'
                    next_message = f'توقف X مؤقتًا عند صفحة من الخط الزمني. سيُستكمل تلقائيًا من نفس الموضع بعد {wait_seconds} ثانية…'
                    delayed_resume = True
            if next_phase is None and task['platform'] == 'instagram' and phase == 'primary' and task['media'] in ('auto', 'all', 'video'):
                next_phase, next_message = 'instagram_reels', 'اكتمل فحص منشورات إنستغرام؛ جاري فحص Reels…'
            elif next_phase is None and task['platform'] == 'tiktok' and phase == 'primary' and task['media'] in ('auto', 'all', 'video'):
                next_phase, next_message = 'tiktok_ytdlp', 'اكتمل مرور تيك توك الأول؛ جاري مرور ثانٍ لاستكمال المقاطع الناقصة…'
            elif next_phase is None and task['platform'] == 'facebook' and phase == 'primary' and task['media'] in ('auto', 'all', 'video'):
                next_phase, next_message = 'facebook_videos', 'اكتمل فحص صور فيسبوك؛ جاري اكتشاف روابط الفيديو وتنزيلها…'

        if next_phase:
            task.update(phase=next_phase, state='queued', message=next_message)
        elif stop:
            task.update(state=stop, message='يمكن الاستكمال لاحقًا؛ قد يعيد المحرك بدء الملف الحالي.' if stop == 'paused' else 'تم إلغاء التحميل')
        elif code != 0 and task.get('platform') == 'facebook' and diagnostic_phase in ('facebook_videos','facebook_video_ytdlp') and task.get('facebook_discovered', 0) == 0 and task.get('files'):
            task.update(state='partial', progress=100, message=f"تم تنزيل {len(task['files'])} صورة، لكن لم يتمكن فيسبوك من كشف روابط الفيديو في الصفحة. الصور محفوظة؛ راجع التفاصيل التقنية للفيديو.")
        elif code != 0 and task.get('platform') == 'direct':
            task.update(state='failed', message=error or 'تعذر إكمال الرابط المباشر؛ يمكن استكمال الجزء المحفوظ لاحقًا.')
        elif code != 0 and (task.get('attempt_files') or task.get('files')):
            task.update(state='completed', progress=100, message=f"تم تنزيل {len(task['files'])} ملفًا، مع تحذير من الموقع أثناء متابعة الحساب. راجع التفاصيل التقنية عند الحاجة.")
        elif code != 0:
            task.update(state='failed', message=error or 'تعذر تشغيل محرك التنزيل')
        elif task.get('attempt_files'):
            task.update(state='completed', progress=100, message=f"اكتملت المهمة • الملفات المسجّلة: {len(task['files'])} • المتخطاة: {task.get('skipped_count', 0)}")
        elif task.get('skipped_count'):
            task.update(state='skipped', progress=100, message=f"تم تخطي {task['skipped_count']} ملف لأنه محمّل مسبقًا.")
        elif task.get('files'):
            task.update(state='completed', progress=100, message=f"اكتمل الفحص • الملفات المسجّلة: {len(task['files'])}")
        else:
            task.update(state='empty', progress=0, message='انتهى فحص الرابط دون ملفات جديدة. تحقق من نوع الوسائط والرابط وصلاحية الوصول.')

        task['diagnostic'] = (
            f"platform={task.get('platform')} engine={task.get('engine')} exit={code} "
            f"attempt={task.get('attempt')} phase={diagnostic_phase}"
            + (f"\ncursor_saved=yes resume_count={task.get('twitter_resume_count')}" if delayed_resume else '')
            + (f"\nfacebook_discovered={task.get('facebook_discovered')}" if task.get('platform') == 'facebook' and 'facebook_discovered' in task else '')
            + (f"\n{error}" if error else '')
            + (f"\nsource={technical}" if technical else '')
        )
        self.store.save(task)
        process.deleteLater()
        self.changed.emit()

    def stop(self, task, state='paused'):
        if task['id'] in self.active:
            self.stops[task['id']] = state
            self.active[task['id']].kill()
        elif task['state'] in ('queued', 'paused'):
            task['state'] = state
            self.store.save(task)
            self.changed.emit()

    def retry(self, task):
        if task['id'] not in self.active:
            task.pop('fallback', None)
            task.pop('video_followup', None)
            task.pop('phase', None)
            task.pop('twitter_cursor', None)
            task.pop('twitter_cursor_candidate', None)
            task.pop('twitter_resume_count', None)
            task.pop('resume_at', None)
            task.pop('facebook_discovered', None)
            task.update(state='queued', message='', progress=0)
            self.store.save(task)
            self.changed.emit()

    def remove(self, task):
        if task['id'] not in self.active:
            self.store.delete(task['id'])
            self.tasks.remove(task)
            self.changed.emit()

    def shutdown(self):
        self.timer.stop()
        for task in self.tasks:
            if task['id'] in self.active:
                self.stop(task)
        for process in list(self.active.values()):
            process.waitForFinished(5000)
