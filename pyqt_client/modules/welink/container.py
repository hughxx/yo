from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.welink.record_panel import RecordPanel
from modules.welink.extract_panel import ExtractPanel
from modules.welink.autoreply_panel import AutoReplyPanel


class WelinkContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._record     = RecordPanel()
        self._extract    = ExtractPanel()
        self._autoreply  = AutoReplyPanel()
        self._tabs.addTab(self._record,     '录制')
        self._tabs.addTab(self._extract,    '历史聊天记录提取')
        self._tabs.addTab(self._autoreply,  '自动回复')
        lay.addWidget(self._tabs)

        # 手动导入 / 定时采集 已下线（不常用，待重构再定）；旧命令监听也已退役
        self._panels = [self._record, self._extract, self._autoreply]

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
