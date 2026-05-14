from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.welink.panel import WelinkPanel
from modules.welink.autoreply_panel import AutoReplyPanel


class WelinkContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._recording = WelinkPanel()
        self._autoreply  = AutoReplyPanel()
        self._tabs.addTab(self._recording, '定位过程记录')
        self._tabs.addTab(self._autoreply,  '自动回复')
        lay.addWidget(self._tabs)

    def activate(self):
        self._recording.activate()

    def deactivate(self):
        self._recording.deactivate()

    def on_settings_changed(self, s: dict):
        if hasattr(self._recording, 'on_settings_changed'):
            self._recording.on_settings_changed(s)
