"""底部日志区（参考 standalone 的 LogPanel）：追加式只读，支持展开/折叠。"""
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QToolButton, QLabel,
)
from PyQt5.QtGui import QFont


class LogPanel(QWidget):
    def __init__(self, parent=None, height=150):
        super().__init__(parent)
        self._expanded = True
        self._last_msg = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部条：折叠开关 + 最近一条（折叠时显示）+ 清空
        head = QWidget()
        head.setObjectName('logHead')
        head.setStyleSheet('#logHead{background:#2b2b2b;border-top:1px solid #1a1a1a;}')
        hl = QHBoxLayout(head)
        hl.setContentsMargins(8, 2, 8, 2)
        hl.setSpacing(6)

        self._toggle = QToolButton()
        self._toggle.setAutoRaise(True)
        self._toggle.setText('日志 ▾')
        self._toggle.setStyleSheet('QToolButton{color:#ddd;border:none;font-weight:bold;}')
        self._toggle.clicked.connect(self._toggle_log)

        self._last = QLabel('')
        self._last.setStyleSheet('color:#999;')

        self._btn_clear = QToolButton()
        self._btn_clear.setAutoRaise(True)
        self._btn_clear.setText('清空')
        self._btn_clear.setStyleSheet('QToolButton{color:#999;border:none;}')
        self._btn_clear.clicked.connect(self.clear_log)

        hl.addWidget(self._toggle)
        hl.addWidget(self._last, 1)
        hl.addWidget(self._btn_clear)
        lay.addWidget(head)

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setMaximumBlockCount(500)
        self._edit.setFixedHeight(height)
        self._edit.setFont(QFont('Consolas', 9))
        self._edit.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')
        lay.addWidget(self._edit)

    def append(self, msg: str):
        self._last_msg = msg
        ts = datetime.now().strftime('%H:%M:%S')
        self._edit.appendPlainText(f'[{ts}] {msg}')
        self._edit.verticalScrollBar().setValue(self._edit.verticalScrollBar().maximum())
        if not self._expanded:
            self._last.setText(msg)

    def clear_log(self):
        self._edit.clear()
        self._last_msg = ''
        self._last.setText('')

    def _toggle_log(self):
        self._expanded = not self._expanded
        self._edit.setVisible(self._expanded)
        self._toggle.setText('日志 ▾' if self._expanded else '日志 ▸')
        self._last.setText('' if self._expanded else self._last_msg)
