"""自动回复面板：群组配置 + 关键词规则（AI 或固定回复）"""
import json
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QRadioButton, QButtonGroup, QMessageBox, QSplitter,
)
from PyQt5.QtCore import Qt

import store
from modules.welink.autoreply_monitor import AutoReplyMonitor

_CONFIG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', '..', '.welink_autoreply.json')
)


def _load_cfg() -> dict:
    try:
        with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(cfg: dict):
    with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── 规则编辑弹窗 ──────────────────────────────────────────────────

class _RuleDialog(QDialog):
    def __init__(self, rule: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑规则' if rule else '添加规则')
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)

        self._kw_edit = QPlainTextEdit()
        self._kw_edit.setFixedHeight(60)
        self._kw_edit.setPlaceholderText('每行一个关键词，命中任意一个即触发')
        form.addRow('关键词:', self._kw_edit)
        lay.addLayout(form)

        # AI / 固定
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel('回复类型:'))
        self._rb_ai    = QRadioButton('AI 回复')
        self._rb_fixed = QRadioButton('固定回复')
        self._rb_group = QButtonGroup(self)
        self._rb_group.addButton(self._rb_ai,    0)
        self._rb_group.addButton(self._rb_fixed, 1)
        self._rb_ai.setChecked(True)
        type_row.addWidget(self._rb_ai)
        type_row.addWidget(self._rb_fixed)
        type_row.addStretch()
        lay.addLayout(type_row)

        self._content_lbl = QLabel('Prompt:')
        lay.addWidget(self._content_lbl)
        self._content_edit = QPlainTextEdit()
        self._content_edit.setFixedHeight(80)
        self._content_edit.setPlaceholderText(
            'AI 模式：填系统 Prompt\n固定模式：填直接发送的回复内容'
        )
        lay.addWidget(self._content_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton('取消')
        btn_ok     = QPushButton('确定')
        btn_ok.setObjectName('btnSync')
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        self._rb_ai.toggled.connect(self._on_type_changed)

        # 填入已有数据
        if rule:
            self._kw_edit.setPlainText('\n'.join(rule.get('keywords', [])))
            if rule.get('action') == 'fixed':
                self._rb_fixed.setChecked(True)
            self._content_edit.setPlainText(
                rule.get('prompt', '') if rule.get('action') == 'ai'
                else rule.get('reply', '')
            )
        self._on_type_changed()

    def _on_type_changed(self):
        is_ai = self._rb_ai.isChecked()
        self._content_lbl.setText('Prompt:' if is_ai else '固定回复内容:')

    def _on_ok(self):
        kws = [k.strip() for k in self._kw_edit.toPlainText().splitlines() if k.strip()]
        if not kws:
            QMessageBox.warning(self, '提示', '关键词不能为空')
            return
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, '提示', '回复内容 / Prompt 不能为空')
            return
        self.accept()

    def get_rule(self) -> dict:
        kws     = [k.strip() for k in self._kw_edit.toPlainText().splitlines() if k.strip()]
        content = self._content_edit.toPlainText().strip()
        if self._rb_ai.isChecked():
            return {'keywords': kws, 'action': 'ai',    'prompt': content}
        else:
            return {'keywords': kws, 'action': 'fixed', 'reply':  content}


# ── 主面板 ────────────────────────────────────────────────────────

class AutoReplyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None
        self._rules   = []   # list of rule dicts
        self._build_ui()
        self._load_config()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        # ── 状态行 ──
        hdr = QHBoxLayout()
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

        # ── 机器人工号 ──
        form = QFormLayout()
        form.setSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)
        self._bot_id_edit = QLineEdit()
        self._bot_id_edit.setPlaceholderText('机器人自身工号（群聊 @ 检测 & 过滤自发消息）')
        form.addRow('机器人工号:', self._bot_id_edit)
        root.addLayout(form)

        _sep = QLabel()
        _sep.setFixedHeight(1)
        _sep.setStyleSheet('background:#ddd;margin:2px 0')
        root.addWidget(_sep)

        # ── 上下分区 ──
        splitter = QSplitter(Qt.Vertical)

        # ── 配置群组（全量监听）──
        grp_box = QWidget()
        g_lay = QVBoxLayout(grp_box)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.setSpacing(4)
        lbl_grp = QLabel('全量监听群组（未在此列表的群仅响应 @ 我）')
        lbl_grp.setStyleSheet('font-size:11px')
        g_lay.addWidget(lbl_grp)

        self._grp_table = QTableWidget(0, 2)
        self._grp_table.setHorizontalHeaderLabels(['群组 ID', '名称'])
        self._grp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._grp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._grp_table.setColumnWidth(0, 180)
        self._grp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._grp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grp_table.verticalHeader().setVisible(False)
        self._grp_table.setAlternatingRowColors(True)
        self._grp_table.verticalHeader().setDefaultSectionSize(22)
        g_lay.addWidget(self._grp_table)

        g_add = QHBoxLayout()
        self._grp_id_edit   = QLineEdit()
        self._grp_id_edit.setPlaceholderText('群组 ID')
        self._grp_name_edit = QLineEdit()
        self._grp_name_edit.setPlaceholderText('名称')
        btn_gadd = QPushButton('+ 添加')
        btn_gadd.setObjectName('btnSync')
        btn_gadd.setFixedWidth(60)
        btn_gadd.clicked.connect(self._add_group)
        btn_gdel = QPushButton('删除')
        btn_gdel.setFixedWidth(48)
        btn_gdel.clicked.connect(self._del_group)
        g_add.addWidget(self._grp_id_edit, 2)
        g_add.addWidget(self._grp_name_edit, 2)
        g_add.addWidget(btn_gadd)
        g_add.addWidget(btn_gdel)
        g_lay.addLayout(g_add)
        splitter.addWidget(grp_box)

        # ── 关键词规则 ──
        rule_box = QWidget()
        r_lay = QVBoxLayout(rule_box)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(4)
        r_lay.addWidget(QLabel('关键词规则'))

        self._rule_table = QTableWidget(0, 3)
        self._rule_table.setHorizontalHeaderLabels(['关键词', '类型', '内容'])
        self._rule_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._rule_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._rule_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._rule_table.setColumnWidth(0, 150)
        self._rule_table.setColumnWidth(1, 56)
        self._rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rule_table.verticalHeader().setVisible(False)
        self._rule_table.setAlternatingRowColors(True)
        self._rule_table.verticalHeader().setDefaultSectionSize(22)
        self._rule_table.doubleClicked.connect(self._edit_rule)
        r_lay.addWidget(self._rule_table)

        r_btn = QHBoxLayout()
        btn_radd  = QPushButton('+ 添加规则')
        btn_radd.setObjectName('btnSync')
        btn_radd.setFixedWidth(80)
        btn_radd.clicked.connect(self._add_rule)
        btn_redit = QPushButton('编辑')
        btn_redit.setFixedWidth(48)
        btn_redit.clicked.connect(self._edit_rule)
        btn_rdel  = QPushButton('删除')
        btn_rdel.setFixedWidth(48)
        btn_rdel.clicked.connect(self._del_rule)
        r_btn.addWidget(btn_radd)
        r_btn.addWidget(btn_redit)
        r_btn.addWidget(btn_rdel)
        r_btn.addStretch()
        r_lay.addLayout(r_btn)
        splitter.addWidget(rule_box)

        # ── 日志 ──
        log_box = QWidget()
        l_lay = QVBoxLayout(log_box)
        l_lay.setContentsMargins(0, 0, 0, 0)
        l_lay.setSpacing(4)
        l_lay.addWidget(QLabel('运行日志'))
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(300)
        self._log_edit.setStyleSheet(
            'background:#1e1e1e;color:#d4d4d4;'
            'font-family:Consolas,monospace;font-size:11px'
        )
        l_lay.addWidget(self._log_edit)
        splitter.addWidget(log_box)

        splitter.setSizes([160, 180, 120])
        root.addWidget(splitter, stretch=1)

    # ── config ────────────────────────────────────────────────────

    def _load_config(self):
        cfg = _load_cfg()
        self._bot_id_edit.setText(cfg.get('botId', ''))

        self._grp_table.setRowCount(0)
        for g in cfg.get('groups', []):
            self._append_group_row(g)

        self._rules = cfg.get('rules', [])
        self._refresh_rule_table()

    def _collect_config(self) -> dict:
        groups = []
        for row in range(self._grp_table.rowCount()):
            groups.append({
                'id':   self._grp_table.item(row, 0).text(),
                'name': self._grp_table.item(row, 1).text(),
            })
        return {
            'botId':  self._bot_id_edit.text().strip(),
            'groups': groups,
            'rules':  self._rules,
        }

    def _save_config(self):
        _save_cfg(self._collect_config())

    # ── groups ────────────────────────────────────────────────────

    def _append_group_row(self, g: dict):
        row = self._grp_table.rowCount()
        self._grp_table.insertRow(row)
        self._grp_table.setItem(row, 0, QTableWidgetItem(g.get('id', '')))
        self._grp_table.setItem(row, 1, QTableWidgetItem(g.get('name', '')))

    def _add_group(self):
        gid   = self._grp_id_edit.text().strip()
        gname = self._grp_name_edit.text().strip()
        if not gid:
            QMessageBox.warning(self, '提示', '群组 ID 不能为空')
            return
        self._append_group_row({'id': gid, 'name': gname or gid})
        self._grp_id_edit.clear()
        self._grp_name_edit.clear()
        self._save_config()

    def _del_group(self):
        rows = sorted({i.row() for i in self._grp_table.selectedItems()}, reverse=True)
        for r in rows:
            self._grp_table.removeRow(r)
        if rows:
            self._save_config()

    # ── rules ─────────────────────────────────────────────────────

    def _refresh_rule_table(self):
        self._rule_table.setRowCount(0)
        for rule in self._rules:
            row = self._rule_table.rowCount()
            self._rule_table.insertRow(row)
            kw_text = ', '.join(rule.get('keywords', []))
            type_text = 'AI回复' if rule.get('action') == 'ai' else '固定回复'
            content = rule.get('prompt', '') if rule.get('action') == 'ai' \
                      else rule.get('reply', '')
            self._rule_table.setItem(row, 0, QTableWidgetItem(kw_text))
            self._rule_table.setItem(row, 1, QTableWidgetItem(type_text))
            self._rule_table.setItem(row, 2, QTableWidgetItem(content[:80]))

    def _add_rule(self):
        dlg = _RuleDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._rules.append(dlg.get_rule())
            self._refresh_rule_table()
            self._save_config()

    def _edit_rule(self):
        rows = list({i.row() for i in self._rule_table.selectedItems()})
        if not rows:
            return
        row = rows[0]
        dlg = _RuleDialog(rule=self._rules[row], parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._rules[row] = dlg.get_rule()
            self._refresh_rule_table()
            self._save_config()

    def _del_rule(self):
        rows = sorted({i.row() for i in self._rule_table.selectedItems()}, reverse=True)
        for r in rows:
            del self._rules[r]
        if rows:
            self._refresh_rule_table()
            self._save_config()

    # ── monitor ───────────────────────────────────────────────────

    def _toggle_monitor(self):
        if self._monitor and self._monitor.isRunning():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        self._save_config()
        cfg = _load_cfg()
        s   = store.load_settings()

        self._monitor = AutoReplyMonitor(
            bot_id        = cfg.get('botId', ''),
            groups        = cfg.get('groups', []),
            rules         = cfg.get('rules', []),
            backend_base  = s.get('backendUrl', 'http://localhost:8023'),
            poll_interval = s.get('welinkPollInterval', 5),
        )
        self._monitor.log_signal.connect(self._append_log)
        self._monitor.start()
        self._set_running(True)

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(3000)
            self._monitor = None
        self._set_running(False)

    def _set_running(self, running: bool):
        self._bot_id_edit.setEnabled(not running)
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

    def _append_log(self, text: str):
        self._log_edit.appendPlainText(text)

    def activate(self): pass
    def deactivate(self): pass

    def closeEvent(self, event):
        self._stop_monitor()
        super().closeEvent(event)
