"""WeLink 聊天记录模块（占位）"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt


class WelinkPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)

        title = QLabel('WeLink 聊天记录')
        title.setStyleSheet('font-size: 22px; font-weight: bold; color: #333;')
        title.setAlignment(Qt.AlignCenter)

        sub = QLabel('此模块正在开发中，敬请期待。')
        sub.setStyleSheet('font-size: 13px; color: #888; margin-top: 8px;')
        sub.setAlignment(Qt.AlignCenter)

        lay.addWidget(title)
        lay.addWidget(sub)

    def activate(self):
        pass

    def deactivate(self):
        pass
