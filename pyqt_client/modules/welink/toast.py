"""录制中浮窗：右下角常驻、置顶、无边框。显示会话名/首条消息/时长/条数 + 停止。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal


class RecordToast(QWidget):
    stop_clicked = pyqtSignal()

    def __init__(self, conv_name: str, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(300)
        self.setStyleSheet(
            'QWidget{background:#2b2b2b;border:1px solid #444;border-radius:6px;}'
            'QLabel{color:#ddd;background:transparent;border:none;}'
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        title = QLabel(f'● 录制中 · {conv_name}')
        title.setStyleSheet('color:#ff6b6b;font-weight:bold;background:transparent;border:none;')
        self._info = QLabel('已录 00:00 · 0 条')
        self._info.setStyleSheet('color:#aaa;background:transparent;border:none;')
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self._info)
        lay.addLayout(top)

        self._first = QLabel('首条：—')
        self._first.setWordWrap(True)
        self._first.setStyleSheet('color:#bbb;font-size:11px;background:transparent;border:none;')
        lay.addWidget(self._first)

        btn = QPushButton('停止录制')
        btn.setStyleSheet(
            'QPushButton{background:#b71c1c;color:white;border:none;border-radius:3px;padding:5px;}'
            'QPushButton:hover{background:#a01818;}')
        btn.clicked.connect(self.stop_clicked)
        lay.addWidget(btn)

    def update_status(self, count: int, first: str, elapsed_s: int):
        mm, ss = divmod(max(0, int(elapsed_s)), 60)
        self._info.setText(f'已录 {mm:02d}:{ss:02d} · {count} 条')
        if first:
            self._first.setText('首条：' + first.replace('\n', ' ')[:60])

    def show_bottom_right(self):
        self.adjustSize()
        from PyQt5.QtWidgets import QApplication
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 20)
        self.show()
        self.raise_()
