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
            self.err.emit(str(e))
