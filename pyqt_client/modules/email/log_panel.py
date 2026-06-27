"""底部日志区（参考 standalone 的 LogPanel）：追加式只读，记录关键事件。"""
from datetime import datetime

from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtGui import QFont


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None, height=120):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(500)
        self.setFixedHeight(height)
        self.setFont(QFont('Consolas', 9))
        self.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')

    def append(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.appendPlainText(f'[{ts}] {msg}')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
