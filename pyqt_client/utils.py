"""共用工具"""
from PyQt5.QtCore import QThread, pyqtSignal


class Worker(QThread):
    ok  = pyqtSignal(object)
    err = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._a, self._kw = fn, args, kwargs

    def run(self):
        try:
            self.ok.emit(self._fn(*self._a, **self._kw))
        except Exception as e:
            import traceback, datetime
            from pathlib import Path
            tb = traceback.format_exc()
            log = Path.home() / 'email_assistant_error.log'
            with open(log, 'a', encoding='utf-8') as f:
                f.write(f'\n=== {datetime.datetime.now()} ===\n{tb}')
            self.err.emit(str(e))
