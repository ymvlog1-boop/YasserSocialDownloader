"""Short-lived cookie copies keep downloader writes away from the original file."""
import os
import tempfile
from pathlib import Path
from .core import cookie_check

class CookieCopies:
    def __init__(self, root):
        self.root = Path(root) / 'session-cookies'
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {}
        for path in self.root.glob('session-*.txt'):
            self._unlink(path)

    @staticmethod
    def _unlink(path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def create(self, task_id, original, platform):
        valid, message = cookie_check(original, platform)
        if not valid:
            raise ValueError(message)
        self.remove(task_id)
        with tempfile.NamedTemporaryFile(prefix='session-', suffix='.txt', dir=self.root, delete=False) as handle:
            path = Path(handle.name)
            self.paths[task_id] = path
            try:
                handle.write(Path(original).read_bytes())
                if os.name != 'nt':
                    os.chmod(path, 0o600)
            except Exception:
                handle.close()
                self.remove(task_id)
                raise
        return str(path)

    def remove(self, task_id):
        path = self.paths.pop(task_id, None)
        if path:
            self._unlink(path)
