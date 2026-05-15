"""入口"""
import sys
import traceback
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from shell import MainShell, QSS

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
