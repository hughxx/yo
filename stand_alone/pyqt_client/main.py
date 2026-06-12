"""入口"""
import ctypes
import sys
import traceback
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMessageBox
from shell import MainShell, QSS

_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, 'Global\\FuyaoCollectionApp')
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    _app = QApplication(sys.argv)
    QMessageBox.warning(None, '已在运行', '程序已经在运行，请勿重复启动。')
    sys.exit(0)

_LOG = (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent) / 'error.log'


def _hook(exc_type, exc_value, exc_tb):
    msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    with open(_LOG, 'a', encoding='utf-8') as f:
        import datetime
        f.write(f'\n=== {datetime.datetime.now()} ===\n{msg}')
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _hook


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setStyle('Fusion')
    win = MainShell()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
