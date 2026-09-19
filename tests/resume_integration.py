"""Verify a real interrupted download issues HTTP Range and retains its bytes."""
import hashlib,http.server,json,sys,tempfile,threading,time,wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication,QEvent
from app.core import Store,new_task
from app.manager import DownloadManager
from app.backend import command

def wait(app,predicate,timeout=30):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        app.processEvents()
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for download state')

def run(executable=None):
    app=QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)/'وسائط-🎬';root.mkdir();source=root/'sample.wav'
        with wave.open(str(source),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\x01\x00'*2_000_000)
        payload=source.read_bytes();ranges=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_HEAD(self):self.respond(False)
            def do_GET(self):self.respond(True)
            def respond(self,body):
                header=self.headers.get('Range','');start=int(header.split('=')[1].split('-')[0]) if header else 0
                if header:ranges.append(start)
                self.send_response(206 if header else 200);self.send_header('Content-Type','audio/wav');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(len(payload)-start))
                if header:self.send_header('Content-Range',f'bytes {start}-{len(payload)-1}/{len(payload)}')
                self.end_headers()
                if body:
                    try:
                        for offset in range(start,len(payload),16384):
                            self.wfile.write(payload[offset:offset+16384]);self.wfile.flush();time.sleep(.01)
                    except (ConnectionError,OSError):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        store=Store(root/'state');manager=DownloadManager(store)
        task=new_task('https://facebook.com/test',str(root/'downloads'),media='video')
        task['url']=f'http://127.0.0.1:{server.server_port}/sample.wav' # Controlled test fixture; UI still restricts supported domains.
        def launch(task,store,cookie_path=None):
            args,kind=command(task,store,cookie_path)
            if executable:args=[str(Path(executable).resolve()),'--engine',kind]+args[4:]
            return args,kind
        try:
            with patch('app.manager.command',side_effect=launch):
                manager.add(task);manager.pump()
                def has_partial():return any(p.stat().st_size>65536 for p in (root/'downloads').glob('*.part'))
                wait(app,has_partial)
                manager.stop(task);wait(app,lambda:task['state']=='paused')
                partial=list((root/'downloads').glob('*.part'))[0].stat().st_size
                manager.retry(task);manager.pump();wait(app,lambda:task['state'] in ('completed','failed','empty'))
                assert task['state']=='completed',task['message']
                actual=Path(task['files'][0]);assert actual.read_bytes()==payload
                assert any(offset>0 for offset in ranges),ranges
                return {'pause_state_saved':True,'partial_bytes':partial,'range_resume':True,'sha256':hashlib.sha256(payload).hexdigest(),'completed':True}
        finally:
            manager.shutdown();manager.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);store.db.close();server.shutdown();server.server_close()

if __name__=='__main__':print(json.dumps(run(sys.argv[1] if len(sys.argv)>1 else None),indent=2))
