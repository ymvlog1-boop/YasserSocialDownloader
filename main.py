import os, sys
from pathlib import Path

def main():
    if '--version-check' in sys.argv:
        from app.version import APP_VERSION
        print(APP_VERSION); return
    if len(sys.argv)>2 and sys.argv[1]=='--engine':
        # Windowed builds have no console streams. Reopen inherited QProcess pipes.
        if sys.stdout is None: sys.stdout=open(1,'w',encoding='utf-8',errors='replace',buffering=1,closefd=False)
        if sys.stderr is None: sys.stderr=open(2,'w',encoding='utf-8',errors='replace',buffering=1,closefd=False)
        for stream in (sys.stdout,sys.stderr):
            if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
        from app.backend import engine_main
        try:engine_main(sys.argv[2],sys.argv[3:])
        except Exception as error:
            sys.stderr.write('ERROR: engine failure ('+type(error).__name__+')\n');sys.exit(1)
        return
    from PySide6.QtCore import Qt,QTimer,QLockFile
    from PySide6.QtWidgets import QApplication,QMessageBox
    from app.core import Store
    app=QApplication(sys.argv);app.setApplicationName('Yasser Social Downloader');app.setLayoutDirection(Qt.RightToLeft)
    try:
        store=Store(); lock=QLockFile(str(store.root/'app.lock'));lock.setStaleLockTime(0)
        if not lock.tryLock(100):QMessageBox.information(None,'أداة ياسر','البرنامج مفتوح بالفعل.');return
        from app.ui import Window
        window=Window(store);window.show()
        if '--smoke-test' in sys.argv:
            def finish():
                target=Path(os.environ.get('YASSER_TEST_OUTPUT',str(store.root)));target.mkdir(parents=True,exist_ok=True)
                window.grab().save(str(target/'interface.png'))
                for i in range(1,window.pages.count()):
                    window.go(i);app.processEvents();window.grab().save(str(target/('page-'+str(i)+'.png')))
                (target/'smoke.txt').write_text('PASS: window visible; RTL='+str(window.layoutDirection()==Qt.RightToLeft)+'; pages='+str(window.pages.count()),encoding='utf-8')
                window.close()
            QTimer.singleShot(2000,finish)
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        target=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YasserSocialDownloader';target.mkdir(parents=True,exist_ok=True)
        (target/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        QMessageBox.critical(None,'تعذر بدء أداة ياسر','تعذر بدء البرنامج. أعد استخراج ملفات التطبيق إلى مجلد قابل للكتابة.\nنوع الخطأ: '+type(e).__name__)

if __name__=='__main__':
    try:main()
    except Exception:
        import ctypes,traceback
        target=Path(os.environ.get('YASSER_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YasserSocialDownloader')
        target.mkdir(parents=True,exist_ok=True);(target/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None,'تعذر تشغيل البرنامج. أعد استخراج الحزمة كاملة. تم حفظ تقرير بدء التشغيل.','أداة ياسر',16)
