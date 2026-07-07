"""规则编辑器：规则(白名单) + 黑名单。最终处理集合 = 规则集合 − 黑名单集合。
只本地、无云端；规则只增/删/改，不启用/禁用。任一改动发 changed 信号。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog,
    QLabel, QSpinBox, QDialogButtonBox, QRadioButton, QButtonGroup, QTimeEdit, QToolButton,
)
from PyQt5.QtCore import Qt, QTime, pyqtSignal

from modules.email import rules as rules_mod
from modules.email.dialogs import RuleDialog


_RULE_HELP = (
    '规则（白名单）\n\n'
    '命中任一条规则的邮件会被纳入处理。每条规则可按：\n'
    '· 主题关键词 / 正文关键词 / 发件人 匹配\n'
    '· 逻辑 OR = 任一类命中即算；AND = 配置的各类都要命中\n'
    '关键词走 Outlook 搜索（整词前缀，与搜索框一致）。'
)
_BLACK_HELP = (
    '黑名单\n\n'
    '在规则命中的基础上，再命中黑名单的邮件会被排除。\n'
    '最终处理集合 = 规则集合 − 黑名单集合。\n'
    '匹配方式与规则相同（主题/正文/发件人 + OR/AND）。'
)


def _help_btn(text: str) -> QToolButton:
    b = QToolButton()
    b.setText('?')
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip(text)
    b.setStyleSheet('QToolButton{color:#5e7ce0;font-weight:bold;border:1px solid #5e7ce0;'
                    'border-radius:8px;min-width:16px;max-width:16px;min-height:16px;max-height:16px;}')
    b.clicked.connect(lambda: QMessageBox.information(b, '说明', text))
    return b


class RulesEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules_data = []
        self._black_data = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 8)
        outer.setSpacing(8)

        self._rule_table  = self._make_table()
        self._black_table = self._make_table()
        outer.addWidget(self._section('规则', _RULE_HELP, self._rule_table,
                                      self._rule_add, self._rule_edit, self._rule_delete))
        outer.addWidget(self._section('黑名单', _BLACK_HELP, self._black_table,
                                      self._black_add, self._black_edit, self._black_delete))

    def _section(self, title, help_text, table, on_add, on_edit, on_del) -> QGroupBox:
        gb = QGroupBox()
        v = QVBoxLayout(gb)
        head = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet('font-weight:bold;')
        head.addWidget(lbl)
        head.addWidget(_help_btn(help_text))
        head.addStretch()
        v.addLayout(head)
        v.addWidget(table)
        row = QHBoxLayout()
        b_add, b_edit, b_del = QPushButton('添加'), QPushButton('编辑'), QPushButton('删除')
        b_del.setObjectName('btnDanger')
        for b in (b_add, b_edit, b_del):
            b.setFixedHeight(24)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        b_add.clicked.connect(on_add)
        b_edit.clicked.connect(on_edit)
        b_del.clicked.connect(on_del)
        return gb

    # ── 对外 ──────────────────────────────────────────────
    def set_namespace(self, ns):    # 兼容旧调用：已无云端，空实现
        pass

    def reload(self):
        self._load_rules()
        self._load_black()

    # ── 公用 ──────────────────────────────────────────────
    @staticmethod
    def _make_table() -> QTableWidget:
        t = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels(['规则名称', '主题关键词', '正文关键词', '发件人', '逻辑'])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setColumnWidth(0, 120)
        t.setColumnWidth(4, 44)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setMaximumHeight(150)
        return t

    @staticmethod
    def _render(table: QTableWidget, rules: list):
        table.setRowCount(0)
        for r in rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(r.get('name', '')))
            table.setItem(row, 1, QTableWidgetItem(', '.join(r.get('keywords', []))))
            table.setItem(row, 2, QTableWidgetItem(', '.join(r.get('body_keywords', []))))
            table.setItem(row, 3, QTableWidgetItem(', '.join(r.get('senders', []))))
            table.setItem(row, 4, QTableWidgetItem('且' if r.get('logic') == 'AND' else '或'))

    @staticmethod
    def _selected(table: QTableWidget, data: list):
        if not table.selectedItems():
            return None
        row = table.currentRow()
        return data[row] if 0 <= row < len(data) else None

    # ── 规则（白名单） ─────────────────────────────────────
    def _load_rules(self):
        self._rules_data = rules_mod.load()
        self._render(self._rule_table, self._rules_data)

    def _rule_add(self):
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        d = dlg.result_data()
        rules_mod.add(d['name'], d['keywords'], d['body_keywords'], d['senders'], d['logic'])
        self._load_rules()
        self.changed.emit()

    def _rule_edit(self):
        rule = self._selected(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        rules_mod.edit(rule['id'], dlg.result_data())
        self._load_rules()
        self.changed.emit()

    def _rule_delete(self):
        rule = self._selected(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        if QMessageBox.question(self, '确认', f'确定删除规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        rules_mod.delete(rule['id'])
        self._load_rules()
        self.changed.emit()

    # ── 黑名单 ─────────────────────────────────────────────
    def _load_black(self):
        self._black_data = rules_mod.load_blacklist()
        self._render(self._black_table, self._black_data)

    def _black_add(self):
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        d = dlg.result_data()
        rules_mod.add_blacklist(d['name'], d['keywords'], d['body_keywords'], d['senders'], d['logic'])
        self._load_black()
        self.changed.emit()

    def _black_edit(self):
        rule = self._selected(self._black_table, self._black_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条黑名单')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        rules_mod.edit_blacklist(rule['id'], dlg.result_data())
        self._load_black()
        self.changed.emit()

    def _black_delete(self):
        rule = self._selected(self._black_table, self._black_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条黑名单')
            return
        if QMessageBox.question(self, '确认', f'确定删除黑名单「{rule["name"]}」？') != QMessageBox.Yes:
            return
        rules_mod.delete_blacklist(rule['id'])
        self._load_black()
        self.changed.emit()


# ── 规则弹窗（点工具栏「规则」打开）──────────────────────────
class RulesDialog(QDialog):
    def __init__(self, ns: str = '', on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('规则 / 黑名单')
        self.setMinimumSize(700, 520)
        lay = QVBoxLayout(self)
        self.editor = RulesEditor()
        if on_changed:
            self.editor.changed.connect(on_changed)
        lay.addWidget(self.editor)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText('关闭')
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        self.editor.reload()


# ── 启动定时弹窗（间隔/每天某时刻 + 规则编辑）────────────────
class StartTimerDialog(QDialog):
    def __init__(self, ns: str, scan_count: int, interval: int,
                 daily_time: str = '09:00', mode: str = 'interval',
                 on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('启动定时同步（后台批量）')
        self.setMinimumSize(700, 560)
        lay = QVBoxLayout(self)

        tip = QLabel(f'范围 = 左侧勾选的 {scan_count} 个文件夹；按下方规则匹配（再减去黑名单）后推送到服务端。')
        tip.setWordWrap(True)
        tip.setStyleSheet('color:#666;')
        lay.addWidget(tip)

        grp = QButtonGroup(self)

        row1 = QHBoxLayout()
        self._rb_interval = QRadioButton('每隔')
        grp.addButton(self._rb_interval)
        self._spin = QSpinBox()
        self._spin.setButtonSymbols(QSpinBox.NoButtons)
        self._spin.setRange(1, 1440)
        self._spin.setValue(max(1, int(interval or 60)))
        self._spin.setSuffix(' 分钟')
        self._spin.setMaximumWidth(110)
        row1.addWidget(self._rb_interval)
        row1.addWidget(self._spin)
        row1.addWidget(QLabel('自动同步一次'))
        row1.addStretch()
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self._rb_daily = QRadioButton('每天')
        grp.addButton(self._rb_daily)
        self._time = QTimeEdit()
        self._time.setDisplayFormat('HH:mm')
        self._time.setMaximumWidth(110)
        try:
            hh, mm = (daily_time or '09:00').split(':')
            self._time.setTime(QTime(int(hh), int(mm)))
        except Exception:
            self._time.setTime(QTime(9, 0))
        row2.addWidget(self._rb_daily)
        row2.addWidget(self._time)
        row2.addWidget(QLabel('自动同步一次'))
        row2.addStretch()
        lay.addLayout(row2)

        if mode == 'daily':
            self._rb_daily.setChecked(True)
        else:
            self._rb_interval.setChecked(True)
        self._rb_interval.toggled.connect(self._sync_enabled)
        self._sync_enabled()

        self.editor = RulesEditor()
        if on_changed:
            self.editor.changed.connect(on_changed)
        lay.addWidget(self.editor, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('启动定时')
        btns.button(QDialogButtonBox.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.editor.reload()

    def _sync_enabled(self):
        on_interval = self._rb_interval.isChecked()
        self._spin.setEnabled(on_interval)
        self._time.setEnabled(not on_interval)

    def mode(self) -> str:
        return 'interval' if self._rb_interval.isChecked() else 'daily'

    def interval(self) -> int:
        return self._spin.value()

    def daily_time(self) -> str:
        return self._time.time().toString('HH:mm')
