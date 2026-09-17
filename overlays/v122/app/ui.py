from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame,QStackedWidget,QPlainTextEdit,QGroupBox,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QFileDialog,QMessageBox,QSpinBox,QLineEdit,QProgressBar,QScrollArea)
from .core import PLATFORMS,STATES,detect,new_task,cookie_check
from .backend import prepare_profile_folder
from .manager import DownloadManager
from .style import STYLE

def button(text,fn,primary=False):
    w=QPushButton(text); w.clicked.connect(fn)
    if primary:w.setObjectName('primary')
    return w

def label(text,kind=None):
    w=QLabel(text); w.setWordWrap(True)
    if kind:w.setObjectName(kind)
    return w

class Window(QMainWindow):
    def __init__(self,store):
        super().__init__(); self.store=store; self.manager=DownloadManager(store)
        self.setWindowTitle('Yasser Social Downloader — أداة ياسر لتحميل الوسائط'); self.resize(1240,820); self.setMinimumSize(960,680); self.setStyleSheet(STYLE)
        root=QWidget(); self.setCentralWidget(root); layout=QHBoxLayout(root); layout.setContentsMargins(20,20,20,20); layout.setSpacing(24)
        side=QFrame(); side.setObjectName('sidebar'); side.setFixedWidth(230); nav=QVBoxLayout(side); nav.setContentsMargins(18,24,18,24)
        nav.addWidget(label('YASSER\nSOCIAL DOWNLOADER','brand')); nav.addWidget(label('أداة ياسر لتحميل الوسائط','muted')); nav.addSpacing(30)
        self.pages=QStackedWidget(); layout.addWidget(side); layout.addWidget(self.pages,1); self.nav=[]
        for i,title in enumerate(['⌂  الرئيسية','↓  قائمة التحميل','◷  سجل التحميلات','◈  إدارة الكوكيز','⚙  الإعدادات','ⓘ  حول البرنامج']):
            b=button(title,lambda checked=False,i=i:self.go(i)); b.setCheckable(True); self.nav.append(b); nav.addWidget(b)
        nav.addStretch(); nav.addWidget(label('محلي • دون طلب بيانات الدخول\nWindows 10 / 11  ·  v1.2.2','muted'))
        self.home(); self.queue_page(); self.history_page(); self.cookies_page(); self.settings_page(); self.about_page()
        self.refresh_timer=QTimer(self);self.refresh_timer.setSingleShot(True);self.refresh_timer.setInterval(120);self.refresh_timer.timeout.connect(self.refresh)
        self.manager.changed.connect(self.schedule_refresh); self.go(0); self.refresh()
    def schedule_refresh(self):
        if not self.refresh_timer.isActive():self.refresh_timer.start()
    def page(self,title,subtitle):
        p=QWidget(); p.setObjectName('page'); v=QVBoxLayout(p); v.setContentsMargins(0,8,0,8); v.setSpacing(18); v.addWidget(label(title,'title')); v.addWidget(label(subtitle,'muted'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(p);self.pages.addWidget(scroll);return v
    def go(self,i):
        self.pages.setCurrentIndex(i)
        for j,b in enumerate(self.nav): b.setChecked(i==j)
    def home(self):
        v=self.page('كل وسائطك، في مكان واحد','إنستغرام • إكس / تويتر • فيسبوك • تيك توك')
        v.addWidget(label('ألصق الرابط، ودع الباقي علينا.','brand'))
        self.urls=QPlainTextEdit(); self.urls.setPlaceholderText('ألصق رابط المنشور أو الحساب هنا\nيمكن إضافة عدة روابط، كل رابط في سطر'); self.urls.setLayoutDirection(Qt.LeftToRight); self.urls.setFixedHeight(130); v.addWidget(self.urls)
        self.platform_label=label('جاهز لاستقبال الروابط','muted'); v.addWidget(self.platform_label); self.urls.textChanged.connect(self.detect_input)
        row=QHBoxLayout(); row.addWidget(button('لصق الرابط',lambda:self.urls.setPlainText(QApplication.clipboard().text()))); row.addWidget(button('مسح',self.urls.clear)); row.addStretch(); v.addLayout(row)
        group=QGroupBox('خيارات التحميل'); opt=QVBoxLayout(group); r=QHBoxLayout()
        self.media=QComboBox()
        for text,data in [('تلقائي','auto'),('الفيديو','video'),('الصور','images'),('جميع الوسائط','all')]:self.media.addItem(text,data)
        self.quality=QComboBox()
        for text,data in [('أفضل جودة متاحة','best'),('1080p','1080'),('720p','720'),('480p','480'),('صوت فقط','audio')]:self.quality.addItem(text,data)
        self.media.currentIndexChanged.connect(self.option_state)
        r.addWidget(label('نوع التحميل')); r.addWidget(self.media,1); r.addWidget(label('الجودة')); r.addWidget(self.quality,1); opt.addLayout(r)
        self.use_cookie=QCheckBox('استخدام ملف الكوكيز المحفوظ'); self.use_cookie.setChecked(True); opt.addWidget(self.use_cookie); opt.addWidget(label('مفعّل افتراضيًا للاستقرار. أزل العلامة فقط إذا أردت المحاولة بدون كوكيز.','muted'))
        self.force=QCheckBox('فرض إعادة التنزيل'); opt.addWidget(self.force); v.addWidget(group)
        self.notice=label('الاستكمال يعتمد على دعم الموقع والمحرك. ملفات الحسابات قد تتطلب كوكيز.','muted'); v.addWidget(self.notice)
        r=QHBoxLayout(); r.addWidget(button('تحميل الآن',lambda:self.enqueue(True),True)); r.addWidget(button('إضافة إلى قائمة التحميل',lambda:self.enqueue(False))); r.addWidget(button('فتح مجلد التحميل',lambda:self.open_path(self.store.folder()))); v.addLayout(r); v.addStretch()
        self.option_state()
    def option_state(self):
        self.quality.setEnabled(self.media.currentData()=='video')
    def detect_input(self):
        try:
            platforms={detect(x)[0] for x in self.urls.toPlainText().splitlines() if x.strip()}; self.platform_label.setText('تم التعرف على المنصة: '+ ' • '.join(PLATFORMS[p] for p in platforms) if platforms else 'جاهز لاستقبال الروابط')
        except ValueError:self.platform_label.setText('يوجد رابط غير مدعوم؛ تحقق من الروابط قبل الإضافة.')
        self.option_state()
    def enqueue(self,start):
        lines=[x.strip() for x in self.urls.toPlainText().splitlines() if x.strip()]
        if not lines:return self.info('ألصق رابطًا أولًا.')
        pending=[]
        try:
            for url in lines:
                p,_=detect(url)
                if self.use_cookie.isChecked():
                    ok,msg=cookie_check(self.store.get('cookie_'+p,''),p)
                    if not ok:self.go(3); raise ValueError(PLATFORMS[p]+': '+msg)
                folder=str(Path(self.store.folder())/p) if self.store.get('organize',True) else self.store.folder()
                t=new_task(url,folder,self.media.currentData(),self.quality.currentData() if self.media.currentData()=='video' else 'best',self.use_cookie.isChecked(),self.force.isChecked())
                prepare_profile_folder(t)
                if not start:t['state']='paused'; t['message']='أضيف إلى القائمة؛ اختر استكمال التحميل للبدء.'
                pending.append(t)
        except ValueError as e:return self.info(str(e))
        for t in pending:self.manager.add(t)
        self.urls.clear(); self.go(1)
    def table(self):
        t=QTableWidget(0,5); t.setHorizontalHeaderLabels(['المنصة / الرابط','الحالة','التقدم','الملفات','التاريخ']); t.setSelectionBehavior(QAbstractItemView.SelectRows); t.setSelectionMode(QAbstractItemView.SingleSelection); t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.setAlternatingRowColors(True); t.verticalHeader().hide(); t.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        for col,width in [(1,145),(2,120),(3,65),(4,135)]: t.setColumnWidth(col,width)
        return t
    def queue_page(self):
        v=self.page('قائمة التحميل','تابع المهام وأوقفها أو استكملها. النسبة تخص الملف الجاري عند توفر الحجم.'); self.queue=self.table(); v.addWidget(self.queue,1)
        self.detail=label('اختر مهمة لعرض حالتها','muted'); v.addWidget(self.detail); self.queue.itemSelectionChanged.connect(self.show_detail)
        r=QHBoxLayout()
        for text,action in [('إيقاف مؤقت','pause'),('استكمال / إعادة المحاولة','retry'),('إلغاء','cancel'),('إزالة','remove')]:r.addWidget(button(text,lambda checked=False,a=action:self.action(self.queue,a)))
        v.addLayout(r); r=QHBoxLayout()
        for text,action in [('فتح الملف','file'),('فتح المجلد','folder'),('التفاصيل التقنية','details'),('تغيير وضع الكوكيز','cookie')]:r.addWidget(button(text,lambda checked=False,a=action:self.action(self.queue,a)))
        v.addLayout(r)
    def history_page(self):
        v=self.page('سجل التحميلات','سجل محلي محفوظ على جهازك. حذف السجل لا يحذف ملفات الوسائط.'); self.history=self.table(); v.addWidget(self.history,1); r=QHBoxLayout()
        for text,a in [('فتح الملف','file'),('فتح المجلد','folder'),('إعادة التحميل','retry'),('نسخ الرابط','copy'),('حذف من السجل','remove')]:r.addWidget(button(text,lambda checked=False,a=a:self.action(self.history,a)))
        v.addLayout(r); v.addWidget(button('مسح السجل',self.clear_history))
    def selected(self,table):
        row=table.currentRow()
        if row<0 or table.item(row,0) is None:return None
        id=table.item(row,0).data(Qt.UserRole)
        return next((t for t in self.manager.tasks if t['id']==id),None)
    def action(self,table,a):
        t=self.selected(table)
        if not t:return self.info('اختر مهمة أولًا.')
        if a=='pause':self.manager.stop(t)
        elif a=='cancel':self.manager.stop(t,'cancelled')
        elif a=='retry':
            if t['state'] in ('completed','partial','skipped'):t['force']=True
            self.manager.retry(t)
        elif a=='remove':self.manager.remove(t)
        elif a=='folder':self.open_path(t['folder'])
        elif a=='file':self.open_path(t['files'][-1]) if t['files'] else self.info('لم يسجّل المحرك مسار ملف؛ افتح مجلد التحميل.')
        elif a=='copy':QApplication.clipboard().setText(t['url'])
        elif a=='details':self.info(t.get('message','')+'\n\n'+t.get('diagnostic','لا توجد تفاصيل إضافية.'))
        elif a=='cookie':
            if t['id'] in self.manager.active:return self.info('أوقف المهمة أولًا لتغيير وضع الكوكيز.')
            t['cookies']=not t['cookies']; self.store.save(t); self.info('استخدام ملف الكوكيز' if t['cookies'] else 'بدون كوكيز')
    def clear_history(self):
        if QMessageBox.question(self,'مسح السجل','هل تريد مسح سجل المهام المنتهية؟')==QMessageBox.Yes:
            for t in list(self.manager.tasks):
                if t['state'] in ('completed','partial','failed','cancelled','skipped','empty'):self.manager.remove(t)
    def refresh(self):
        for table,tasks in [(self.queue,self.manager.tasks),(self.history,[t for t in self.manager.tasks if t['state'] in ('completed','partial','failed','cancelled','skipped','empty')])]:
            selected=self.selected(table); id=selected['id'] if selected else None
            table.blockSignals(True); table.setRowCount(len(tasks))
            for row,t in enumerate(tasks):
                values=[PLATFORMS[t['platform']]+'\n\u2066'+t['url']+'\u2069',STATES[t['state']], '',str(len(t['files'])),t['created']]
                for col,value in enumerate(values):
                    item=QTableWidgetItem(value); item.setData(Qt.UserRole,t['id']); item.setToolTip(t.get('message','')); table.setItem(row,col,item)
                bar=QProgressBar(); bar.setLayoutDirection(Qt.LeftToRight)
                if t['state']=='running' and t['progress']<=0:bar.setRange(0,0)
                else:bar.setRange(0,100);bar.setValue(max(0,t['progress']))
                table.setCellWidget(row,2,bar); table.setRowHeight(row,64)
                if id==t['id']:table.selectRow(row)
            table.blockSignals(False)
        self.show_detail()
    def show_detail(self):
        t=self.selected(self.queue); self.detail.setText(t.get('message','') if t else 'اختر مهمة لعرض حالتها')
    def cookies_page(self):
        v=self.page('إدارة ملفات الكوكيز','يُحفظ مسار الملف فقط. الفحص محلي ولا يثبت قبول الجلسة لدى الموقع.'); self.cookie_labels={}
        for p,name in PLATFORMS.items():
            group=QGroupBox(name); g=QVBoxLayout(group); status=label(self.cookie_status(p),'muted'); self.cookie_labels[p]=status; g.addWidget(status); r=QHBoxLayout()
            r.addWidget(button('اختيار / تغيير الملف',lambda checked=False,p=p:self.choose_cookie(p))); r.addWidget(button('فحص الملف',lambda checked=False,p=p:self.check_cookie(p))); r.addWidget(button('إزالة الملف',lambda checked=False,p=p:self.remove_cookie(p))); g.addLayout(r); v.addWidget(group)
        v.addStretch()
    def cookie_status(self,p):
        path=self.store.get('cookie_'+p); return Path(path).name+' — لم يتم اختباره' if path else 'لا يوجد ملف كوكيز محدد'
    def choose_cookie(self,p):
        path,_=QFileDialog.getOpenFileName(self,'اختيار ملف الكوكيز','','Cookies (*.txt);;All files (*)')
        if path:
            ok,msg=cookie_check(path,p)
            if not ok:return self.info(msg)
            self.store.set('cookie_'+p,path); self.cookie_labels[p].setText(Path(path).name+' — '+msg)
    def check_cookie(self,p):self.cookie_labels[p].setText(cookie_check(self.store.get('cookie_'+p,''),p)[1])
    def remove_cookie(self,p):self.store.set('cookie_'+p,None);self.cookie_labels[p].setText('لا يوجد ملف كوكيز محدد')
    def settings_page(self):
        v=self.page('الإعدادات','تفضيلات محفوظة تلقائيًا على جهازك.'); v.addWidget(label('مجلد التحميل الافتراضي')); self.folder=QLineEdit(self.store.folder()); self.folder.setReadOnly(True); self.folder.setLayoutDirection(Qt.LeftToRight); v.addWidget(self.folder); v.addWidget(button('اختيار مجلد التحميل',self.choose_folder))
        org=QCheckBox('تنظيم المنشورات المفردة في مجلد مستقل لكل منصة');org.setChecked(self.store.get('organize',True));org.toggled.connect(lambda x:self.store.set('organize',x));v.addWidget(org)
        v.addWidget(label('تنزيل البروفايلات يُنظّم دائمًا داخل مجلد المنصة ثم اسم المستخدم.','muted'))
        v.addWidget(label('عدد التحميلات المتزامنة')); count=QSpinBox();count.setRange(1,4);count.setValue(self.store.get('concurrent',2));count.valueChanged.connect(lambda x:self.store.set('concurrent',x));v.addWidget(count)
        v.addWidget(label('تحديث البرنامج وأدوات التحميل','brand')); v.addWidget(label('زر واحد يفحص إصدار Yasser Social Downloader نفسه ثم يحدث yt-dlp وgallery-dl. إذا توفر إصلاح جديد للبرنامج سينزله ويتحقق منه ثم يعيد تشغيل التطبيق تلقائيًا، مع بقاء الكوكيز والإعدادات وسجل التحميلات.','muted'))
        self.update_button=button('تحديث البرنامج وأدوات التحميل',self.update_engines);v.addWidget(self.update_button)
        from .updater import engine_versions
        versions=engine_versions(self.store.root)
        self.update_status=label('yt-dlp '+versions['video']+' • gallery-dl '+versions['gallery'],'muted');v.addWidget(self.update_status)
        v.addWidget(button('إصدارات yt-dlp الرسمية',lambda:QDesktopServices.openUrl(QUrl('https://github.com/yt-dlp/yt-dlp/releases'))));v.addWidget(button('إصدارات gallery-dl الرسمية',lambda:QDesktopServices.openUrl(QUrl('https://github.com/mikf/gallery-dl/releases'))));v.addStretch()
    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'اختيار مجلد التحميل',self.store.folder())
        if path:self.store.set('folder',path);self.folder.setText(path)
    def update_engines(self):
        from .updater import FullUpdateWorker
        self.update_button.setEnabled(False);self.update_status.setText('جاري فحص تحديث البرنامج وأدوات التحميل…')
        self.updater=FullUpdateWorker(self.store.root);self.updater.result.connect(self.updated);self.updater.start()
    def updated(self,action,message):
        self.update_button.setEnabled(True);self.update_status.setText(message)
        if action=='app_ready':
            self.info(message)
            from .updater import launch_pending_update
            if launch_pending_update(self.store.root):
                self.manager.shutdown(); QApplication.instance().quit()
    def about_page(self):
        from .version import APP_VERSION
        v=self.page('Yasser Social Downloader','أداة ياسر لتحميل الوسائط • الإصدار '+APP_VERSION);v.addWidget(label('واجهة عربية، وتجربة بسيطة.','brand'));v.addWidget(label('يعالج روابط الحسابات عبر gallery-dl المحدث، ويستخدم yt-dlp للفيديو المنفرد ولتيارات الفيديو التي يستدعيها gallery-dl داخليًا. لا يدعم تجاوز DRM أو المحتوى غير المسموح للحساب.'))
        v.addWidget(label('الإيقاف يوقف عملية التنزيل؛ الاستكمال يعيد تشغيل المحرك باستخدام الأجزاء والأرشيف حيث يتوفر الدعم. لا تُحذف الأجزاء عند الإلغاء.','muted'));v.addWidget(label('استعمل البرنامج لحفظ المحتوى الذي تملك حق الوصول إليه وتنزيله. لا يطلب البرنامج اسم مستخدم أو كلمة مرور ولا يجمع قياسات استخدام.','muted'));v.addStretch()
    def info(self,text):QMessageBox.information(self,'Yasser Social Downloader',text)
    def open_path(self,path):
        p=Path(path)
        if not p.exists():return self.info('المسار غير موجود بعد. يبدأ إنشاء المجلد عند التحميل.')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))
    def closeEvent(self,event):
        if hasattr(self,'updater') and self.updater.isRunning():
            self.info('انتظر اكتمال تحديث المحركات قبل إغلاق البرنامج.');event.ignore();return
        self.manager.shutdown();event.accept()
