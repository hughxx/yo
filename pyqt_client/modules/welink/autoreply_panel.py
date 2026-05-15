"""自动回复面板：群组/用户监听配置 + 关键词规则"""
import json
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialog, QRadioButton,
    QButtonGroup, QMessageBox, QSplitter, QTabWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import store
from modules.welink.autoreply_monitor import AutoReplyMonitor, fetch_recent_conversations
from utils import Worker

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

        form = QTableWidget()
        self._kw_edit = QPlainTextEdit()
        self._kw_edit.setFixedHeight(60)
        self._kw_edit.setPlaceholderText('每行一个关键词，命中任意一个即触发')

        from PyQt5.QtWidgets import QFormLayout
        flay = QFormLayout()
        flay.addRow('关键词:', self._kw_edit)
        lay.addLayout(flay)

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
        self._content_edit.setPlaceholderText('AI 模式：填系统 Prompt\n固定模式：填直接发送的回复内容')
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

        if rule:
            self._kw_edit.setPlainText('\n'.join(rule.get('keywords', [])))
            if rule.get('action') == 'fixed':
                self._rb_fixed.setChecked(True)
            self._content_edit.setPlainText(
                rule.get('prompt', '') if rule.get('action') == 'ai' else rule.get('reply', '')
            )
        self._on_type_changed()

    def _on_type_changed(self):
        self._content_lbl.setText('Prompt:' if self._rb_ai.isChecked() else '固定回复内容:')

    def _on_ok(self):
        if not [k.strip() for k in self._kw_edit.toPlainText().splitlines() if k.strip()]:
            QMessageBox.warning(self, '提示', '关键词不能为空')
            return
        if not self._content_edit.toPlainText().strip():
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
        self._monitor  = None
        self._rules    = []
        self._workers  = []             # 保持 Worker 引用，防止 GC 销毁运行中线程
        self._updating = False          # 防止 itemChanged 误触发
        # 合并后的数据（special + recent）
        self._grp_rows = []             # [{id, name, at_only, special}]
        self._usr_rows = []             # [{account, name, special}]
        self._build_ui()
        self._load_config()
        self._refresh_recent()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        # 状态行
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

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet('background:#ddd;margin:2px 0')
        root.addWidget(sep)

        splitter = QSplitter(Qt.Vertical)

        # ── Tab：群组 / 用户 ──
        tabs = QTabWidget()

        # 群组 Tab
        grp_w = QWidget()
        g_lay = QVBoxLayout(grp_w)
        g_lay.setContentsMargins(0, 4, 0, 0)
        g_lay.setSpacing(4)

        self._grp_table = QTableWidget(0, 3)
        self._grp_table.setHorizontalHeaderLabels(['名称', 'ID', '仅@我'])
        self._grp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._grp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._grp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._grp_table.setColumnWidth(1, 160)
        self._grp_table.setColumnWidth(2, 56)
        self._grp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._grp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grp_table.verticalHeader().setVisible(False)
        self._grp_table.verticalHeader().setDefaultSectionSize(22)
        self._grp_table.setAlternatingRowColors(True)
        self._grp_table.itemChanged.connect(self._on_grp_item_changed)
        g_lay.addWidget(self._grp_table)

        g_btn = QHBoxLayout()
        self._grp_id_edit   = QLineEdit()
        self._grp_id_edit.setPlaceholderText('群组 ID')
        self._grp_id_edit.setFixedWidth(140)
        self._grp_name_edit = QLineEdit()
        self._grp_name_edit.setPlaceholderText('名称（可选）')
        btn_gadd = QPushButton('+ 特别关注')
        btn_gadd.setObjectName('btnSync')
        btn_gadd.setFixedWidth(80)
        btn_gadd.clicked.connect(self._add_special_group)
        btn_gdel = QPushButton('删除')
        btn_gdel.setFixedWidth(48)
        btn_gdel.clicked.connect(self._del_group)
        btn_gref = QPushButton('刷新')
        btn_gref.setFixedWidth(48)
        btn_gref.clicked.connect(self._refresh_recent)
        g_btn.addWidget(self._grp_id_edit)
        g_btn.addWidget(self._grp_name_edit)
        g_btn.addWidget(btn_gadd)
        g_btn.addWidget(btn_gdel)
        g_btn.addStretch()
        g_btn.addWidget(btn_gref)
        g_lay.addLayout(g_btn)
        tabs.addTab(grp_w, '群组')

        # 用户 Tab
        usr_w = QWidget()
        u_lay = QVBoxLayout(usr_w)
        u_lay.setContentsMargins(0, 4, 0, 0)
        u_lay.setSpacing(4)

        self._usr_table = QTableWidget(0, 2)
        self._usr_table.setHorizontalHeaderLabels(['工号', '名称'])
        self._usr_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._usr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._usr_table.setColumnWidth(0, 130)
        self._usr_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._usr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._usr_table.verticalHeader().setVisible(False)
        self._usr_table.verticalHeader().setDefaultSectionSize(22)
        self._usr_table.setAlternatingRowColors(True)
        u_lay.addWidget(self._usr_table)

        u_btn = QHBoxLayout()
        self._usr_acc_edit  = QLineEdit()
        self._usr_acc_edit.setPlaceholderText('工号')
        self._usr_acc_edit.setFixedWidth(120)
        self._usr_name_edit = QLineEdit()
        self._usr_name_edit.setPlaceholderText('名称（可选）')
        btn_uadd = QPushButton('+ 特别关注')
        btn_uadd.setObjectName('btnSync')
        btn_uadd.setFixedWidth(80)
        btn_uadd.clicked.connect(self._add_special_user)
        btn_udel = QPushButton('删除')
        btn_udel.setFixedWidth(48)
        btn_udel.clicked.connect(self._del_user)
        u_btn.addWidget(self._usr_acc_edit)
        u_btn.addWidget(self._usr_name_edit)
        u_btn.addWidget(btn_uadd)
        u_btn.addWidget(btn_udel)
        u_btn.addStretch()
        u_lay.addLayout(u_btn)
        tabs.addTab(usr_w, '用户')

        splitter.addWidget(tabs)

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
        self._rule_table.verticalHeader().setDefaultSectionSize(22)
        self._rule_table.setAlternatingRowColors(True)
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

        splitter.setSizes([200, 160, 100])
        root.addWidget(splitter, stretch=1)

    # ── config ────────────────────────────────────────────────────

    def _load_config(self):
        cfg = _load_cfg()
        self._special_grp_ids  = {g['id']      for g in cfg.get('special_groups', [])}
        self._special_usr_accs = {u['account'] for u in cfg.get('special_users',  [])}
        self._special_grp_map  = {g['id']: g.get('name', g['id']) for g in cfg.get('special_groups', [])}
        self._special_usr_map  = {u['account']: u.get('name', u['account']) for u in cfg.get('special_users', [])}
        self._grp_at_only      = cfg.get('group_at_only', {})
        self._rules            = cfg.get('rules', [])
        self._refresh_rule_table()

    def _collect_config(self) -> dict:
        return {
            'special_groups': [
                {'id': gid, 'name': self._special_grp_map.get(gid, gid)}
                for gid in self._special_grp_ids
            ],
            'special_users': [
                {'account': acc, 'name': self._special_usr_map.get(acc, acc)}
                for acc in self._special_usr_accs
            ],
            'group_at_only': self._grp_at_only,
            'rules': self._rules,
        }

    def _save_config(self):
        _save_cfg(self._collect_config())

    # ── recent conversations ──────────────────────────────────────

    def _refresh_recent(self):
        def _work():
            return fetch_recent_conversations(50)

        def _done(convs):
            grp_seen, usr_seen = set(), set()

            # special 先进列表
            grp_rows = []
            for gid in self._special_grp_ids:
                grp_rows.append({
                    'id':      gid,
                    'name':    self._special_grp_map.get(gid, gid),
                    'at_only': self._grp_at_only.get(gid, True),
                    'special': True,
                })
                grp_seen.add(gid)

            usr_rows = []
            for acc in self._special_usr_accs:
                usr_rows.append({
                    'account': acc,
                    'name':    self._special_usr_map.get(acc, acc),
                    'special': True,
                })
                usr_seen.add(acc)

            # 合并最近会话
            for conv in convs:
                ctype = conv.get('recent_conversation_type', '')
                if ctype == 'CHAT_TYPE_GROUP_MSG':
                    gid  = str(conv.get('group_id', ''))
                    name = conv.get('group_name', gid)
                    if gid and gid not in grp_seen:
                        grp_rows.append({
                            'id':      gid,
                            'name':    name,
                            'at_only': self._grp_at_only.get(gid, True),
                            'special': False,
                        })
                        grp_seen.add(gid)
                elif ctype == 'CHAT_TYPE_P2P_MSG':
                    acc  = conv.get('target_account', '')
                    name = conv.get('target_name', acc)
                    if acc and acc not in usr_seen:
                        usr_rows.append({'account': acc, 'name': name, 'special': False})
                        usr_seen.add(acc)

            self._grp_rows = grp_rows
            self._usr_rows = usr_rows
            self._rebuild_grp_table()
            self._rebuild_usr_table()

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda e: self._append_log(f'刷新最近会话失败: {e}'))
        w.start()
        self._workers.append(w)

    def _rebuild_grp_table(self):
        self._updating = True
        self._grp_table.setRowCount(0)
        for g in self._grp_rows:
            row = self._grp_table.rowCount()
            self._grp_table.insertRow(row)
            name_item = QTableWidgetItem(g['name'])
            id_item   = QTableWidgetItem(g['id'])
            at_item   = QTableWidgetItem()
            at_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            at_item.setCheckState(Qt.Checked if g.get('at_only', True) else Qt.Unchecked)
            if g['special']:
                for item in (name_item, id_item, at_item):
                    item.setForeground(QColor('#008C64'))
            self._grp_table.setItem(row, 0, name_item)
            self._grp_table.setItem(row, 1, id_item)
            self._grp_table.setItem(row, 2, at_item)
        self._updating = False

    def _rebuild_usr_table(self):
        self._usr_table.setRowCount(0)
        for u in self._usr_rows:
            row = self._usr_table.rowCount()
            self._usr_table.insertRow(row)
            acc_item  = QTableWidgetItem(u['account'])
            name_item = QTableWidgetItem(u['name'])
            if u['special']:
                acc_item.setForeground(QColor('#008C64'))
                name_item.setForeground(QColor('#008C64'))
            self._usr_table.setItem(row, 0, acc_item)
            self._usr_table.setItem(row, 1, name_item)

    # ── group operations ─────────────────────────────────────────

    def _on_grp_item_changed(self, item):
        if self._updating or item.column() != 2:
            return
        gid = self._grp_table.item(item.row(), 1)
        if not gid:
            return
        group_id = gid.text()
        if item.checkState() == Qt.Unchecked:
            ret = QMessageBox.warning(
                self, '提示',
                '群聊消息过多时会占用系统资源，请谨慎选择。\n确定取消"仅@我"限制？',
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if ret != QMessageBox.Ok:
                self._updating = True
                item.setCheckState(Qt.Checked)
                self._updating = False
                return
        at_only = item.checkState() == Qt.Checked
        self._grp_at_only[group_id] = at_only
        for g in self._grp_rows:
            if g['id'] == group_id:
                g['at_only'] = at_only
                break
        self._save_config()

    def _add_special_group(self):
        gid   = self._grp_id_edit.text().strip()
        gname = self._grp_name_edit.text().strip() or gid
        if not gid:
            QMessageBox.warning(self, '提示', '群组 ID 不能为空')
            return
        self._special_grp_ids.add(gid)
        self._special_grp_map[gid] = gname
        self._grp_id_edit.clear()
        self._grp_name_edit.clear()
        self._save_config()
        self._refresh_recent()

    def _del_group(self):
        rows = sorted({i.row() for i in self._grp_table.selectedItems()}, reverse=True)
        for r in rows:
            gid = self._grp_table.item(r, 1).text()
            self._special_grp_ids.discard(gid)
            self._special_grp_map.pop(gid, None)
            if r < len(self._grp_rows):
                del self._grp_rows[r]
        if rows:
            self._save_config()
            self._rebuild_grp_table()

    # ── user operations ───────────────────────────────────────────

    def _add_special_user(self):
        acc   = self._usr_acc_edit.text().strip()
        name  = self._usr_name_edit.text().strip() or acc
        if not acc:
            QMessageBox.warning(self, '提示', '工号不能为空')
            return
        self._special_usr_accs.add(acc)
        self._special_usr_map[acc] = name
        self._usr_acc_edit.clear()
        self._usr_name_edit.clear()
        self._save_config()
        self._refresh_recent()

    def _del_user(self):
        rows = sorted({i.row() for i in self._usr_table.selectedItems()}, reverse=True)
        for r in rows:
            acc = self._usr_table.item(r, 0).text()
            self._special_usr_accs.discard(acc)
            self._special_usr_map.pop(acc, None)
            if r < len(self._usr_rows):
                del self._usr_rows[r]
        if rows:
            self._save_config()
            self._rebuild_usr_table()

    # ── rules ─────────────────────────────────────────────────────

    def _refresh_rule_table(self):
        self._rule_table.setRowCount(0)
        for rule in self._rules:
            row = self._rule_table.rowCount()
            self._rule_table.insertRow(row)
            self._rule_table.setItem(row, 0, QTableWidgetItem(', '.join(rule.get('keywords', []))))
            self._rule_table.setItem(row, 1, QTableWidgetItem('AI' if rule.get('action') == 'ai' else '固定'))
            content = rule.get('prompt', '') if rule.get('action') == 'ai' else rule.get('reply', '')
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
        s = store.load_settings()
        groups = [{'id': g['id'], 'name': g['name'], 'at_only': g.get('at_only', True)}
                  for g in self._grp_rows]
        users  = [u['account'] for u in self._usr_rows]
        self._monitor = AutoReplyMonitor(
            groups        = groups,
            users         = users,
            rules         = self._rules,
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
