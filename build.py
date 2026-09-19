"""Run with the project's build Python environment."""
import subprocess,sys,shutil,os
from pathlib import Path
import imageio_ffmpeg
root=Path(__file__).resolve().parent
(root/'tools').mkdir(exist_ok=True)
shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),root/'tools'/'ffmpeg.exe')
env=os.environ.copy()
# Avoid collecting incompatible DLLs from unrelated software on the build PATH.
env['PATH']=os.pathsep.join([str(Path(sys.executable).parent),sys.base_prefix,str(Path(os.environ['WINDIR'])/'System32'),os.environ['WINDIR']])
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--name','YasserSocialDownloader','--collect-all','yt_dlp','--collect-all','gallery_dl','--add-binary',str(root/'tools'/'ffmpeg.exe')+';tools','--exclude-module','PySide6.QtWebEngineCore','--exclude-module','PySide6.QtWebEngineWidgets',str(root/'main.py')],cwd=root,env=env,check=True)
import PySide6
for dll in Path(PySide6.__file__).parent.glob('*140*.dll'):
    shutil.copy2(dll,root/'dist'/'YasserSocialDownloader'/'_internal'/dll.name)
