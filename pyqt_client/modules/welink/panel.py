"""WeLink 聊天录制面板"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QPlainTextEdit, QGroupBox, QFormLayout,
    QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, QTimer

import store
import backend
from modules.welink.monitor import WelinkMonitor


class WelinkPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None  # type: WelinkMonitor | None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # title
        title = QLabel('WeLink 聊天录制')
        title.setStyleSheet('font-size:18px;font-weight:bold;color:#252526')
        root.addWidget(title)

        # config box
        cfg_box = QGroupBox('配置')
        cfg_lay = QFormLayout(cfg_box)
        cfg_lay.setSpacing(8)

        self._bot_name_edit = QLineEdit()
        self._bot_name_edit.setPlaceholderText('例如：云见')
        cfg_lay.addRow('机器人名称 (@):', self._bot_name_edit)

        self._user_id_edit = QLineEdit()
        self._user_id_edit.setPlaceholderText('例如：w00899061')
        cfg_lay.addRow('上传者工号 (upload_by):', self._user_id_edit)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 60)
        self._interval_spin.setSuffix(' 秒')
        cfg_lay.addRow('轮询间隔:', self._interval_spin)

        root.addWidget(cfg_box)

        # control row
        ctrl = QHBoxLayout()

        self._btn_start = QPushButton('开始监听')
        self._btn_start.setObjectName('btnSync')
        self._btn_start.setFixedHeight(32)
        self._btn_start.clicked.connect(self._start_monitor)

        self._btn_stop = QPushButton('停止监听')
        self._btn_stop.setObjectName('btnDanger')
        self._btn_stop.setFixedHeight(32)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_monitor)

        self._status_label = QLabel('未运行')
        self._status_label.setStyleSheet('color:#888')

        ctrl.addWidget(self._btn_start)
        ctrl.addWidget(self._btn_stop)
        ctrl.addSpacing(16)
        ctrl.addWidget(self._status_label)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # usage hint
        hint = QLabel(
            '触发方式：群聊中发送 <b>@{机器人名称} 开始问题记录</b> 和 '
            '<b>@{机器人名称} 结束问题记录</b>，中间的聊天内容将自动上传。'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#555;font-size:11px;background:#fffbe6;'
                           'padding:6px 10px;border-radius:4px;border:1px solid #ffe58f')
        root.addWidget(hint)

        # log area
        log_label = QLabel('运行日志')
        log_label.setStyleSheet('font-weight:bold')
        root.addWidget(log_label)

        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(500)
        self._log_edit.setStyleSheet(
            'background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:11px'
        )
        root.addWidget(self._log_edit, stretch=1)

        self._load_settings()

    # ── settings ──────────────────────────────────────────────────

    def _load_settings(self):
        s = store.load_settings()
        self._bot_name_edit.setText(s.get('welinkBotName', '云见'))
        self._user_id_edit.setText(s.get('welinkUserId', '') or s.get('userId', ''))
        self._interval_spin.setValue(s.get('welinkPollInterval', 3))

    def _save_settings(self):
        s = store.load_settings()
        s['welinkBotName']      = self._bot_name_edit.text().strip() or '云见'
        s['welinkUserId']       = self._user_id_edit.text().strip()
        s['welinkPollInterval'] = self._interval_spin.value()
        store.save_settings(s)

    # ── monitor control ───────────────────────────────────────────

    def _start_monitor(self):
        self._save_settings()
        s = store.load_settings()

        bot_name  = s.get('welinkBotName', '云见')
        user_id   = s.get('welinkUserId', '') or s.get('userId', '')
        interval  = s.get('welinkPollInterval', 3)
        base_url  = s.get('backendUrl', 'http://localhost:8023').rstrip('/')

        self._monitor = WelinkMonitor(
            bot_name      = bot_name,
            user_id       = user_id,
            poll_interval = interval,
            backend_base  = base_url,
        )
        self._monitor.log_signal.connect(self._append_log)
        self._monitor.uploaded_signal.connect(self._on_uploaded)
        self._monitor.start()

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._bot_name_edit.setEnabled(False)
        self._user_id_edit.setEnabled(False)
        self._interval_spin.setEnabled(False)
        self._status_label.setText('运行中…')
        self._status_label.setStyleSheet('color:#008C64;font-weight:bold')

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(3000)
            self._monitor = None

        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._bot_name_edit.setEnabled(True)
        self._user_id_edit.setEnabled(True)
        self._interval_spin.setEnabled(True)
        self._status_label.setText('已停止')
        self._status_label.setStyleSheet('color:#888')

    # ── slots ─────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log_edit.appendPlainText(text)

    def _on_uploaded(self, info: dict):
        group = info.get('group_name', '')
        count = info.get('count', 0)
        dup   = info.get('duplicate', False)
        if not dup:
            self._status_label.setText(f'最近上传: [{group}] {count} 条')

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self):
        pass

    def deactivate(self):
        pass

    def closeEvent(self, event):
        if self._monitor:
            self._monitor.stop()
        super().closeEvent(event)
