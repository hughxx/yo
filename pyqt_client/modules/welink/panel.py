"""WeLink 群聊录制面板：规则管理 + 后台监听"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QPlainTextEdit, QSplitter,
)
from PyQt5.QtCore import Qt

import backend
import store
from utils import Worker
from modules.welink.monitor import WelinkMonitor


class WelinkPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None
        self._worker  = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        # ── 标题 + 监听控制 ──
        hdr = QHBoxLayout()
        title = QLabel('WeLink 群聊录制')
        title.setStyleSheet('font-size:16px;font-weight:bold;color:#252526')
        hdr.addWidget(title)
        hdr.addStretch()

        self._dot = QLabel('●')
        self._dot.setStyleSheet('color:#ccc;font-size:14px')
        self._status_lbl = QLabel('未运行')
        self._status_lbl.setStyleSheet('color:#888;font-size:11px')

        self._btn_toggle = QPushButton('开始监听')
        self._btn_toggle.setObjectName('btnSync')
        self._btn_toggle.setFixedWidth(80)
        self._btn_toggle.clicked.connect(self._toggle_monitor)

        hdr.addWidget(self._dot)
        hdr.addWidget(self._status_lbl)
        hdr.addSpacing(8)
        hdr.addWidget(self._btn_toggle)
        root.addLayout(hdr)

        # ── 触发提示 ──
        hint = QLabel(
            '触发：群聊中 <b>@机器人名 开始问题记录</b> / <b>@机器人名 结束问题记录</b>'
            '（机器人名在设置中配置）'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            'color:#555;font-size:11px;background:#fffbe6;'
            'padding:4px 10px;border-radius:4px;border:1px solid #ffe58f'
        )
        root.addWidget(hint)

        # ── 规则表 + 日志（上下分割）──
        splitter = QSplitter(Qt.Vertical)

        # 上：规则表
        rule_box = QWidget()
        rule_lay = QVBoxLayout(rule_box)
        rule_lay.setContentsMargins(0, 0, 0, 0)
        rule_lay.setSpacing(4)

        rule_hdr = QHBoxLayout()
        rule_hdr.addWidget(QLabel('监听的群聊'))
        rule_hdr.addStretch()
        btn_refresh = QPushButton('刷新')
        btn_refresh.setFixedWidth(48)
        btn_refresh.clicked.connect(self._load_rules)
        rule_hdr.addWidget(btn_refresh)
        rule_lay.addLayout(rule_hdr)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(['群组 ID', '群组名称', ''])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 180)
        self._table.setColumnWidth(2, 52)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        rule_lay.addWidget(self._table)

        # 添加行
        add_row = QHBoxLayout()
        self._gid_edit   = QLineEdit()
        self._gid_edit.setPlaceholderText('群组 ID（必填）')
        self._gname_edit = QLineEdit()
        self._gname_edit.setPlaceholderText('群组名称（可选）')
        btn_add = QPushButton('+ 添加')
        btn_add.setObjectName('btnSync')
        btn_add.setFixedWidth(64)
        btn_add.clicked.connect(self._add_rule)
        add_row.addWidget(self._gid_edit, 2)
        add_row.addWidget(self._gname_edit, 2)
        add_row.addWidget(btn_add)
        rule_lay.addLayout(add_row)

        splitter.addWidget(rule_box)

        # 下：日志
        log_box = QWidget()
        log_lay = QVBoxLayout(log_box)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(4)
        log_lay.addWidget(QLabel('运行日志'))
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(300)
        self._log_edit.setStyleSheet(
            'background:#1e1e1e;color:#d4d4d4;'
            'font-family:Consolas,monospace;font-size:11px'
        )
        log_lay.addWidget(self._log_edit)
        splitter.addWidget(log_box)

        splitter.setSizes([280, 160])
        root.addWidget(splitter, stretch=1)

    # ── monitor toggle ────────────────────────────────────────────

    def _toggle_monitor(self):
        if self._monitor and self._monitor.isRunning():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        s = store.load_settings()
        backend.set_base(s.get('backendUrl', ''))

        bot_name = s.get('welinkBotName', '云见')
        user_id  = s.get('welinkUserId', '') or s.get('userId', '')
        interval = s.get('welinkPollInterval', 3)
        base_url = s.get('backendUrl', 'http://localhost:8023').rstrip('/')

        self._monitor = WelinkMonitor(
            backend_base  = base_url,
            bot_name      = bot_name,
            user_id       = user_id,
            poll_interval = interval,
        )
        self._monitor.log_signal.connect(self._append_log)
        self._monitor.uploaded_signal.connect(self._on_uploaded)
        self._monitor.start()
        self._set_running(True)

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(3000)
            self._monitor = None
        self._set_running(False)

    def _set_running(self, running: bool):
        if running:
            self._dot.setStyleSheet('color:#008C64;font-size:14px')
            self._status_lbl.setText('监听中')
            self._status_lbl.setStyleSheet('color:#008C64;font-size:11px;font-weight:bold')
            self._btn_toggle.setText('停止监听')
            self._btn_toggle.setObjectName('btnDanger')
        else:
            self._dot.setStyleSheet('color:#ccc;font-size:14px')
            self._status_lbl.setText('未运行')
            self._status_lbl.setStyleSheet('color:#888;font-size:11px')
            self._btn_toggle.setText('开始监听')
            self._btn_toggle.setObjectName('btnSync')
        # 触发样式重绘
        self._btn_toggle.style().unpolish(self._btn_toggle)
        self._btn_toggle.style().polish(self._btn_toggle)

    # ── rules ─────────────────────────────────────────────────────

    def _load_rules(self):
        w = Worker(backend.get_welink_rules)
        w.ok.connect(self._on_rules_loaded)
        w.err.connect(lambda _: None)
        w.start()
        self._worker = w

    def _on_rules_loaded(self, rules: list):
        self._table.setRowCount(0)
        for r in rules:
            self._append_row(r)

    def _append_row(self, rule: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(rule['group_id']))
        self._table.setItem(row, 1, QTableWidgetItem(rule.get('group_name', '')))
        btn = QPushButton('删除')
        btn.setObjectName('btnDanger')
        btn.setFixedSize(48, 22)
        btn.clicked.connect(lambda _, rid=rule['id']: self._delete_rule(rid))
        self._table.setCellWidget(row, 2, btn)
        self._table.setRowHeight(row, 28)

    def _add_rule(self):
        gid   = self._gid_edit.text().strip()
        gname = self._gname_edit.text().strip()
        if not gid:
            QMessageBox.warning(self, '提示', '群组 ID 不能为空')
            return

        w = Worker(backend.add_welink_rule, gid, gname)
        w.ok.connect(self._on_rule_added)
        w.err.connect(lambda e: QMessageBox.warning(self, '添加失败', e))
        w.start()
        self._worker = w

    def _on_rule_added(self, result: dict):
        if 'message' in result and not result.get('id'):
            QMessageBox.warning(self, '添加失败', result['message'])
            return
        self._gid_edit.clear()
        self._gname_edit.clear()
        self._append_row(result)
        # 如果监听已启动，立即刷新规则（monitor 每 60s 拉一次，手动触发快速生效）
        if self._monitor and self._monitor.isRunning():
            self._append_log(f'[规则] 已添加群聊 {result.get("group_id")}，下次轮询生效')

    def _delete_rule(self, rule_id: int):
        w = Worker(backend.delete_welink_rule, rule_id)
        w.ok.connect(lambda _: self._load_rules())
        w.err.connect(lambda e: QMessageBox.warning(self, '删除失败', e))
        w.start()
        self._worker = w

    # ── slots ─────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log_edit.appendPlainText(text)

    def _on_uploaded(self, info: dict):
        if not info.get('duplicate'):
            self._status_lbl.setText(
                f'监听中  |  最近上传: [{info["group_name"]}] {info["count"]} 条'
            )

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self):
        s = store.load_settings()
        backend.set_base(s.get('backendUrl', ''))
        self._load_rules()

    def deactivate(self):
        pass

    def closeEvent(self, event):
        self._stop_monitor()
        super().closeEvent(event)
