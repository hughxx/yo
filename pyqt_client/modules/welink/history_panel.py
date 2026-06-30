"""历史聊天记录提取：两种离线方式合一 —— 在线拉取(cli) + 手动导入(zip)。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.welink.extract_panel import ExtractPanel
from modules.welink.manual_panel import ManualExportPanel


class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._online = ExtractPanel()
        self._manual = ManualExportPanel()
        self._tabs.addTab(self._online, '在线拉取')
        self._tabs.addTab(self._manual, '手动导入 (zip)')
        lay.addWidget(self._tabs)

        self._panels = [self._online, self._manual]

    def activate(self):
        for p in self._panels:
            if hasattr(p, 'activate'):
                p.activate()

    def deactivate(self):
        for p in self._panels:
            if hasattr(p, 'deactivate'):
                p.deactivate()

    def on_settings_changed(self, s):
        for p in self._panels:
            if hasattr(p, 'on_settings_changed'):
                p.on_settings_changed(s)
