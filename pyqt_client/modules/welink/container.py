from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.welink.record_panel import RecordPanel
from modules.welink.extract_panel import ExtractPanel
from modules.welink.panel import WelinkPanel
from modules.welink.autoreply_panel import AutoReplyPanel
from modules.welink.manual_panel import ManualExportPanel


class WelinkContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._record     = RecordPanel()
        self._extract    = ExtractPanel()
        self._recording  = WelinkPanel()
        self._autoreply  = AutoReplyPanel()
        self._manual     = ManualExportPanel()
        self._tabs.addTab(self._record,     '录制')
        self._tabs.addTab(self._extract,    '提取聊天记录')
        self._tabs.addTab(self._recording,  '定位过程记录(旧)')
        self._tabs.addTab(self._autoreply,  '自动回复')
        self._tabs.addTab(self._manual,     '聊天记录手动导出')
        lay.addWidget(self._tabs)

        self._panels = [self._record, self._extract, self._recording, self._autoreply, self._manual]

    def activate(self):
        for p in self._panels:
            if hasattr(p, 'activate'):
                p.activate()

    def deactivate(self):
        for p in self._panels:
            if hasattr(p, 'deactivate'):
                p.deactivate()

    def on_settings_changed(self, s: dict):
        for p in self._panels:
            if hasattr(p, 'on_settings_changed'):
                p.on_settings_changed(s)
