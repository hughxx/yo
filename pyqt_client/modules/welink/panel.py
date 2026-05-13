"""WeLink 群聊录制 — 监听群聊规则管理"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox,
)
from PyQt5.QtCore import Qt

import backend
from utils import Worker


class WelinkPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(10)

        # header row
        hdr = QHBoxLayout()
        title = QLabel('WeLink 群聊录制')
        title.setStyleSheet('font-size:16px;font-weight:bold;color:#252526')
        hdr.addWidget(title)
        hdr.addStretch()
        self._status_dot = QLabel('●')
        self._status_dot.setStyleSheet('color:#ccc;font-size:14px')
        self._status_lbl = QLabel('未连接')
        self._status_lbl.setStyleSheet('color:#888;font-size:11px')
        btn_refresh = QPushButton('刷新')
        btn_refresh.setFixedWidth(54)
        btn_refresh.clicked.connect(self._load_rules)
        hdr.addWidget(self._status_dot)
        hdr.addWidget(self._status_lbl)
        hdr.addSpacing(6)
        hdr.addWidget(btn_refresh)
        root.addLayout(hdr)

        # hint
        hint = QLabel(
            '录制触发：群聊中 <b>@机器人名 开始问题记录</b> / <b>@机器人名 结束问题记录</b>。'
            '后台运行 <code>welink_monitor.py</code> 即可自动监听并上传。'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            'color:#555;font-size:11px;background:#fffbe6;'
            'padding:5px 10px;border-radius:4px;border:1px solid #ffe58f'
        )
        root.addWidget(hint)

        # rules table
        lbl = QLabel('监听的群聊')
        lbl.setStyleSheet('font-weight:bold;font-size:12px')
        root.addWidget(lbl)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(['群组 ID', '群组名称', ''])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(2, 52)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        root.addWidget(self._table, stretch=1)

        # add row
        add_row = QHBoxLayout()
        self._gid_edit  = QLineEdit()
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
        root.addLayout(add_row)

    # ── data ──────────────────────────────────────────────────────

    def _load_rules(self):
        self._set_status(None)

        def _fetch():
            rules = backend.get_welink_rules()
            # also ping
            try:
                import requests, urllib3
                urllib3.disable_warnings()
                requests.get(
                    backend._base + '/api/welink/ping', timeout=4, verify=False
                ).raise_for_status()
                ok = True
            except Exception:
                ok = False
            return rules, ok

        w = Worker(_fetch)
        w.ok.connect(lambda res: self._on_rules_loaded(*res))
        w.err.connect(lambda e: self._set_status(False))
        w.start()
        self._worker = w

    def _on_rules_loaded(self, rules, connected):
        self._rules = rules
        self._set_status(connected)
        self._table.setRowCount(0)
        for r in rules:
            self._append_row(r)

    def _append_row(self, rule: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(rule['group_id']))
        self._table.setItem(row, 1, QTableWidgetItem(rule.get('group_name', '')))

        btn_del = QPushButton('删除')
        btn_del.setObjectName('btnDanger')
        btn_del.setFixedSize(48, 22)
        btn_del.clicked.connect(lambda _, rid=rule['id']: self._delete_rule(rid))
        self._table.setCellWidget(row, 2, btn_del)
        self._table.setRowHeight(row, 28)

    def _add_rule(self):
        gid   = self._gid_edit.text().strip()
        gname = self._gname_edit.text().strip()
        if not gid:
            QMessageBox.warning(self, '提示', '群组 ID 不能为空')
            return

        def _do():
            return backend.add_welink_rule(gid, gname)

        w = Worker(_do)
        w.ok.connect(self._on_rule_added)
        w.err.connect(lambda e: QMessageBox.warning(self, '添加失败', e))
        w.start()
        self._worker = w

    def _on_rule_added(self, result: dict):
        if not result.get('success', True) and 'message' in result:
            QMessageBox.warning(self, '添加失败', result['message'])
            return
        self._gid_edit.clear()
        self._gname_edit.clear()
        self._append_row(result)

    def _delete_rule(self, rule_id: int):
        def _do():
            return backend.delete_welink_rule(rule_id)

        w = Worker(_do)
        w.ok.connect(lambda _: self._load_rules())
        w.err.connect(lambda e: QMessageBox.warning(self, '删除失败', e))
        w.start()
        self._worker = w

    # ── status ────────────────────────────────────────────────────

    def _set_status(self, connected):
        if connected is None:
            self._status_dot.setStyleSheet('color:#ccc;font-size:14px')
            self._status_lbl.setText('连接中…')
        elif connected:
            self._status_dot.setStyleSheet('color:#008C64;font-size:14px')
            self._status_lbl.setText('已连接')
        else:
            self._status_dot.setStyleSheet('color:#c00;font-size:14px')
            self._status_lbl.setText('无法连接后端')

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self):
        self._load_rules()

    def deactivate(self):
        pass
