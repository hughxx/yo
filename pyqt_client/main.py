"""入口"""
import sys
from PyQt5.QtWidgets import QApplication
from shell import MainShell, QSS


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setStyle('Fusion')
    win = MainShell()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
