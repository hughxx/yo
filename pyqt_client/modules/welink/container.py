from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from modules.welink.record_panel import RecordPanel
from modules.welink.history_panel import HistoryPanel
from modules.welink.schedule_panel import SchedulePanel
from modules.welink.autoreply_panel import AutoReplyPanel


class WelinkContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._record     = RecordPanel()
        self._history    = HistoryPanel()
        self._schedule   = SchedulePanel()
        self._autoreply  = AutoReplyPanel()
        self._tabs.addTab(self._record,     '录制')
        self._tabs.addTab(self._history,    '历史聊天记录提取')   # 在线拉取 + 手动导入
        self._tabs.addTab(self._schedule,   '定时采集')
        self._tabs.addTab(self._autoreply,  '自动回复')
        lay.addWidget(self._tabs)

        # 旧的命令监听(定位过程记录/panel.py)已被 录制+提取+定时 替代，退役不再挂载
        self._panels = [self._record, self._history, self._schedule, self._autoreply]

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
