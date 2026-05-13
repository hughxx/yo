"""WeLink 群聊录制面板：规则管理 + 后台监听"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QPlainTextEdit, QSplitter,
    QFormLayout, QDialog,
)
from PyQt5.QtCore import Qt

import backend
import store
from utils import Worker
from modules.welink.monitor import WelinkMonitor

_CONFIRM_KEYWORD = '接口人已知晓'


class _ConfirmDialog(QDialog):
    """添加/删除共享规则前的确认弹窗，需用户手动输入关键词。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('确认操作')
        self.setFixedWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        warn = QLabel('⚠ 监听规则属于<b>共享资源</b>，修改将影响所有监听用户。')
        warn.setWordWrap(True)
        warn.setStyleSheet('color:#333;padding:6px;background:#fff8e1;'
                           'border:1px solid #ffe082;border-radius:4px')
        lay.addWidget(warn)

        lay.addWidget(QLabel(f'请在下方输入 <b>{_CONFIRM_KEYWORD}</b> 后点击确认：'))
        self._input = QLineEdit()
        self._input.setPlaceholderText(_CONFIRM_KEYWORD)
        lay.addWidget(self._input)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton('取消')
        self._btn_ok     = QPushButton('确认')
        self._btn_ok.setObjectName('btnSync')
        self._btn_ok.setEnabled(False)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_ok)
        lay.addLayout(btn_row)

        self._input.textChanged.connect(
            lambda t: self._btn_ok.setEnabled(t == _CONFIRM_KEYWORD)
        )
        self._btn_ok.clicked.connect(self.accept)
        self._btn_cancel.clicked.connect(self.reject)

    @staticmethod
    def ask(parent=None) -> bool:
        return _ConfirmDialog(parent).exec_() == QDialog.Accepted


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

        # ── 触发命令配置 ──
        form = QFormLayout()
        form.setSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)
        self._start_cmd_edit = QLineEdit()
        self._end_cmd_edit   = QLineEdit()
        form.addRow('开始命令:', self._start_cmd_edit)
        form.addRow('结束命令:', self._end_cmd_edit)
        root.addLayout(form)

        # ── 规则表 + 日志（上下分割）──
        splitter = QSplitter(Qt.Vertical)

        # 上：规则表
        rule_box = QWidget()
        rule_lay = QVBoxLayout(rule_box)
        rule_lay.setContentsMargins(0, 0, 0, 0)
        rule_lay.setSpacing(4)
        rule_lay.addWidget(QLabel('监听的群聊'))

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(['群组 ID', '群组名称', ''])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 180)
        self._table.setColumnWidth(2, 44)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setDefaultSectionSize(24)
        rule_lay.addWidget(self._table)

        # 添加行
        add_row = QHBoxLayout()
        self._gid_edit   = QLineEdit()
        self._gid_edit.setPlaceholderText('群组 ID（必填）')
        self._gname_edit = QLineEdit()
        self._gname_edit.setPlaceholderText('群组名称（必填）')
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

        self._load_config()

    # ── config ────────────────────────────────────────────────────

    def _load_config(self):
        s = store.load_settings()
        self._start_cmd_edit.setText(s.get('welinkStartCmd', '@云见 开始定位'))
        self._end_cmd_edit.setText(s.get('welinkEndCmd',   '@云见 结束定位'))

    def _save_config(self):
        s = store.load_settings()
        s['welinkStartCmd'] = self._start_cmd_edit.text().strip()
        s['welinkEndCmd']   = self._end_cmd_edit.text().strip()
        store.save_settings(s)

    # ── monitor toggle ────────────────────────────────────────────

    def _toggle_monitor(self):
        if self._monitor and self._monitor.isRunning():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        self._save_config()
        s = store.load_settings()
        backend.set_base(s.get('backendUrl', ''))

        self._monitor = WelinkMonitor(
            backend_base  = s.get('backendUrl', 'http://localhost:8023').rstrip('/'),
            start_cmd     = s.get('welinkStartCmd', '@云见 开始定位'),
            end_cmd       = s.get('welinkEndCmd',   '@云见 结束定位'),
            user_id       = s.get('welinkUserId', '') or s.get('userId', ''),
            poll_interval = s.get('welinkPollInterval', 3),
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
        editable = not running
        self._start_cmd_edit.setEnabled(editable)
        self._end_cmd_edit.setEnabled(editable)
        if running:
            self._dot.setStyleSheet('color:#008C64;font-size:14px')
            self._status_lbl.setText('监听中')
            self._status_lbl.setStyleSheet('color:#008C64;font-size:11px;font-weight:bold')
            self._btn_toggle.setText('停止监听')
            self._btn_toggle.setObjectName('btnDanger')
        else:
            self._dot.setStyleSheet('color:#ccc;font-size:14px')
            self._status_lbl.setText('未运行')
            self._status_lbl.setStyleSheet('color:#888;font-size:11px;font-weight:normal')
            self._btn_toggle.setText('开始监听')
            self._btn_toggle.setObjectName('btnSync')
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

        id_item = QTableWidgetItem(rule['group_id'])
        id_item.setData(Qt.UserRole, rule['id'])   # 存 rule_id
        self._table.setItem(row, 0, id_item)
        self._table.setItem(row, 1, QTableWidgetItem(rule.get('group_name', '')))

        btn = QPushButton('×')
        btn.setObjectName('btnDanger')
        btn.setFixedSize(36, 20)
        btn.setStyleSheet('font-size:13px;padding:0;min-height:0;border-radius:2px')
        btn.clicked.connect(lambda _, rid=rule['id'], gid=rule['group_id']: self._delete_rule(rid, gid))
        self._table.setCellWidget(row, 2, btn)

    def _add_rule(self):
        gid   = self._gid_edit.text().strip()
        gname = self._gname_edit.text().strip()
        if not gid or not gname:
            QMessageBox.warning(self, '提示', '群组 ID 和群组名称均不能为空')
            return

        if not _ConfirmDialog.ask(self):
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

    def _delete_rule(self, rule_id: int, group_id: str):
        if not _ConfirmDialog.ask(self):
            return

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
                f'监听中  |  最近: [{info["group_name"]}] {info["count"]} 条'
            )

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self):
        s = store.load_settings()
        backend.set_base(s.get('backendUrl', ''))
        self._load_config()
        self._load_rules()

    def deactivate(self):
        pass

    def closeEvent(self, event):
        self._stop_monitor()
        super().closeEvent(event)
