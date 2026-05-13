from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt


class AutoReplyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lbl = QLabel('问题自动回复\n\n敬请期待')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('color:#bbb;font-size:16px')
        lay.addWidget(lbl)

    def activate(self): pass
    def deactivate(self): pass
