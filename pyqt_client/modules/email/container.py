"""邮件模块容器：「邮件」+「本地导入」两个页签。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.email.panel import EmailPanel
from modules.email.local_import_panel import LocalImportPanel


class EmailContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._mail = EmailPanel()
        self._local = LocalImportPanel()
        self._tabs.addTab(self._mail, '邮件')
        self._tabs.addTab(self._local, '本地导入')
        self._tabs.currentChanged.connect(self._on_tab)
        lay.addWidget(self._tabs)

    def _on_tab(self, idx):
        if self._tabs.tabText(idx) == '本地导入':
            self._local.refresh()

    # ── 转发壳层生命周期到「邮件」页 ──
    def activate(self):
        self._mail.activate()
        if self._tabs.tabText(self._tabs.currentIndex()) == '本地导入':
            self._local.refresh()

    def deactivate(self):
        self._mail.deactivate()

    def on_settings_changed(self, s: dict):
        self._mail.on_settings_changed(s)
