"""入口"""
import ctypes
import datetime
import sys
import traceback
from pathlib import Path

_LOG = (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent) / 'error.log'


def _write_log(msg: str):
    try:
        with open(_LOG, 'a', encoding='utf-8') as f:
            f.write(f'\n=== {datetime.datetime.now()} ===\n{msg}\n')
    except Exception:
        pass


def _hook(exc_type, exc_value, exc_tb):
    _write_log(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _hook

try:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from shell import MainShell, QSS
except Exception:
    _write_log(traceback.format_exc())
    sys.exit(1)

_MUTEX_NAME = 'Global\\FuyaoCollectionApp'
_ERROR_ALREADY_EXISTS = 183


def main():
    try:
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            app = QApplication(sys.argv)
            QMessageBox.warning(None, '已在运行', '程序已经在运行，请勿重复启动。')
            sys.exit(0)

        app = QApplication(sys.argv)
        app.setStyleSheet(QSS)
        app.setStyle('Fusion')
        win = MainShell()
        win.show()
        sys.exit(app.exec_())
    except Exception:
        _write_log(traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
