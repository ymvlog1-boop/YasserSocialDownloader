"""Real engines against locally generated, owned test media. No social credentials."""
import functools,hashlib,http.server,json,os,subprocess,sys,tempfile,threading,wave
from pathlib import Path

def run(prefix):
    report={}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);media=root/'media';media.mkdir();out=root/'downloads';out.mkdir()
        with wave.open(str(media/'test.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*8000)
        ff=(Path(prefix[0]).resolve().parent/'_internal'/'tools'/'ffmpeg.exe') if len(prefix)==1 else Path(__file__).resolve().parents[1]/'tools'/'ffmpeg.exe'
        if ff.exists():
            conversion=subprocess.run([str(ff),'-hide_banner','-loglevel','error','-i',str(media/'test.wav'),str(root/'converted.mp3')],capture_output=True,timeout=20)
            assert conversion.returncode==0 and (root/'converted.mp3').stat().st_size>0
            report['ffmpeg']={'audio_conversion':True}
        # A tiny valid PNG owned by the fixture.
        import base64
        (media/'test.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII='))
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(media)))
        threading.Thread(target=server.serve_forever,daemon=True).start();url='http://127.0.0.1:'+str(server.server_port)
        try:
            cases={'video':['--ignore-config','--newline','--print','after_move:YFILE:%(filepath)s','--progress-template','download:YPROGRESS:%(progress)j','-P',str(out),url+'/test.wav'],
                   'gallery':['--config-ignore','--no-input','--no-colors','-D',str(out),'--Print','after:YFILE:{_path}','--Print','skip:YSKIP:{_path}',url+'/test.png']}
            for kind,args in cases.items():
                result=subprocess.run(prefix+['--engine',kind]+args,capture_output=True,timeout=60)
                text=(result.stdout+result.stderr).decode('utf-8',errors='replace')
                assert result.returncode==0,(kind,result.returncode,text)
                assert 'YFILE:' in text,(kind,text)
                original=media/('test.wav' if kind=='video' else 'test.png')
                hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()]
                assert hashlib.sha256(original.read_bytes()).hexdigest() in hashes,(kind,'content differs')
                report[kind]={'exit':result.returncode,'file_hash_verified':True,'file_event':True}
                if kind=='gallery':
                    again=subprocess.run(prefix+['--engine',kind]+args,capture_output=True,timeout=30)
                    assert again.returncode==0 and b'YSKIP:' in again.stdout
                    report[kind]['repeat_skipped']=True
            for kind in cases:
                r=subprocess.run(prefix+['--engine',kind,'--version'],capture_output=True,timeout=20)
                assert r.returncode==0
                report[kind]['version']=r.stdout.decode().strip()
            rejected=subprocess.run(prefix+['--engine','gallery','--config-ignore','https://invalid.invalid/unsupported'],capture_output=True,timeout=15)
            assert rejected.returncode!=0,'gallery errors must reach the parent process'
            report['gallery']['failure_exit_propagated']=True
            if ff.exists():
                sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
                from app.backend import command
                from app.core import Store,new_task
                store=Store(root/'audio-state')
                try:
                    task=new_task('https://facebook.com/test',str(root/'audio-only'),media='video',quality='audio')
                    task['url']=url+'/test.wav'
                    args,_=command(task,store)
                    # Use exactly the application's audio options with the chosen runtime.
                    args=prefix+['--engine','video']+args[4:]
                    location=args.index('--ffmpeg-location') if '--ffmpeg-location' in args else -1
                    if location>=0:args[location+1]=str(ff)
                    result=subprocess.run(args,capture_output=True,timeout=30)
                    assert result.returncode==0,(result.stdout+result.stderr).decode(errors='replace')
                    files=list((root/'audio-only').glob('*.mp3'));assert len(files)==1 and files[0].stat().st_size>0
                    report['audio_only']={'mp3_created':True}
                finally:store.db.close()
        finally:server.shutdown();server.server_close()
    return report

if __name__=='__main__':
    prefix=[sys.argv[1]] if len(sys.argv)>1 else [sys.executable,str(Path(__file__).resolve().parents[1]/'main.py')]
    print(json.dumps(run(prefix),indent=2))
