"""内联规则编辑器（就近放在邮件页，参考 standalone 的「规则 ▾」）。

云端规则：增删改仍走服务端；启用/禁用本机生效（cloud_mute）。
本地规则：完全本地 CRUD（rules_mod）。
任一改动后发 changed 信号，面板据此重新匹配。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog,
    QLabel, QSpinBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from modules.email import rules as rules_mod
from modules.email import cloud_mute
from modules.email.dialogs import RuleDialog
import backend
from utils import Worker


class RulesEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ns = ''
        self._cloud_rules_data = []
        self._rules_data = []
        self._workers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 8)
        outer.setSpacing(8)

        # ── 云端规则 ──────────────────────────────────
        self._cloud_group = QGroupBox('云端规则（命名空间）')
        cg = QVBoxLayout(self._cloud_group)
        self._cloud_table = self._make_rule_table()
        cg.addWidget(self._cloud_table)
        cr = QHBoxLayout()
        cb_add    = QPushButton('添加')
        cb_edit   = QPushButton('编辑')
        cb_del    = QPushButton('删除')
        cb_toggle = QPushButton('启用/禁用')
        cb_refresh = QPushButton('刷新')
        cb_del.setObjectName('btnDanger')
        for b in (cb_add, cb_edit, cb_del, cb_toggle):
            b.setFixedHeight(24)
            cr.addWidget(b)
        cr.addStretch()
        cb_refresh.setFixedHeight(24)
        cr.addWidget(cb_refresh)
        cg.addLayout(cr)
        outer.addWidget(self._cloud_group)

        cb_add.clicked.connect(self._cloud_rule_add)
        cb_edit.clicked.connect(self._cloud_rule_edit)
        cb_del.clicked.connect(self._cloud_rule_delete)
        cb_toggle.clicked.connect(self._cloud_rule_toggle)
        cb_refresh.clicked.connect(self._load_cloud_rules)

        # ── 本地规则 ──────────────────────────────────
        local_group = QGroupBox('本地规则')
        lg = QVBoxLayout(local_group)
        self._rule_table = self._make_rule_table()
        lg.addWidget(self._rule_table)
        lr = QHBoxLayout()
        btn_add    = QPushButton('添加')
        btn_edit   = QPushButton('编辑')
        btn_del    = QPushButton('删除')
        btn_toggle = QPushButton('启用/禁用')
        btn_del.setObjectName('btnDanger')
        for b in (btn_add, btn_edit, btn_del, btn_toggle):
            b.setFixedHeight(24)
            lr.addWidget(b)
        lr.addStretch()
        lg.addLayout(lr)
        outer.addWidget(local_group)

        btn_add.clicked.connect(self._rule_add)
        btn_edit.clicked.connect(self._rule_edit)
        btn_del.clicked.connect(self._rule_delete)
        btn_toggle.clicked.connect(self._rule_toggle)

    # ── 对外 ──────────────────────────────────────────────
    def set_namespace(self, ns: str):
        self._ns = ns or ''

    def reload(self):
        self._load_cloud_rules()
        self._load_rules()

    @staticmethod
    def _make_rule_table() -> QTableWidget:
        t = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels(['启用', '规则名称', '主题关键词', '正文关键词', '发件人', '逻辑'])
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        t.setColumnWidth(0, 40)
        t.setColumnWidth(1, 110)
        t.setColumnWidth(5, 44)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setMaximumHeight(150)
        return t

    # ── 云端规则 ──────────────────────────────────────────
    def _load_cloud_rules(self):
        ns = self._ns
        self._cloud_group.setTitle(f'云端规则（{ns or "未选择命名空间"}）')
        if not ns:
            self._cloud_rules_data = []
            self._render(self._cloud_table, [])
            return

        def _done(rules):
            self._cloud_rules_data = rules
            self._render(self._cloud_table, cloud_mute.apply(rules))

        w = Worker(backend.get_cloud_rules, ns)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _cloud_rule_add(self):
        if not self._ns:
            QMessageBox.warning(self, '提示', '请先在设置中选择命名空间')
            return
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        d = dlg.result_data()
        w = Worker(backend.add_cloud_rule, self._ns, d['name'], d['keywords'],
                   d['body_keywords'], d['senders'], d['logic'])
        w.ok.connect(lambda _: (self._load_cloud_rules(), self.changed.emit()))
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_edit(self):
        rule = self._selected(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        w = Worker(backend.edit_cloud_rule, rule['id'], dlg.result_data())
        w.ok.connect(lambda _: (self._load_cloud_rules(), self.changed.emit()))
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_delete(self):
        rule = self._selected(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        if QMessageBox.question(self, '确认', f'确定删除云端规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        w = Worker(backend.delete_cloud_rule, rule['id'])
        w.ok.connect(lambda _: (self._load_cloud_rules(), self.changed.emit()))
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_toggle(self):
        rule = self._selected(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        muted = cloud_mute.is_muted(rule['id'])
        action = '启用' if muted else '禁用'
        ret = QMessageBox.question(
            self, '本地启用/禁用',
            f'云端规则的启用/禁用仅在本机生效，不会修改服务端配置，也不影响其他人。\n'
            f'（云端规则的增删改仍走服务端，这里只是本机不想用某条远程规则时的开关。）\n\n'
            f'确定在本机{action}规则「{rule.get("name", "")}」吗？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret != QMessageBox.Yes:
            return
        cloud_mute.toggle(rule['id'])
        self._render(self._cloud_table, cloud_mute.apply(self._cloud_rules_data))
        self.changed.emit()

    # ── 本地规则 ──────────────────────────────────────────
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
        if QMessageBox.question(self, '确认', f'确定删除本地规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        rules_mod.delete(rule['id'])
        self._load_rules()
        self.changed.emit()

    def _rule_toggle(self):
        rule = self._selected(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        rules_mod.edit(rule['id'], {'enabled': not rule['enabled']})
        self._load_rules()
        self.changed.emit()

    # ── 公用 ──────────────────────────────────────────────
    @staticmethod
    def _selected(table: QTableWidget, data: list):
        if not table.selectedItems():
            return None
        row = table.currentRow()
        return data[row] if 0 <= row < len(data) else None

    @staticmethod
    def _render(table: QTableWidget, rules: list):
        table.setRowCount(0)
        for r in rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem('是' if r['enabled'] else '否'))
            table.setItem(row, 1, QTableWidgetItem(r['name']))
            table.setItem(row, 2, QTableWidgetItem(', '.join(r.get('keywords', []))))
            table.setItem(row, 3, QTableWidgetItem(', '.join(r.get('body_keywords', []))))
            table.setItem(row, 4, QTableWidgetItem(', '.join(r.get('senders', []))))
            table.setItem(row, 5, QTableWidgetItem('且' if r['logic'] == 'AND' else '或'))
            if not r['enabled']:
                for col in range(6):
                    it = table.item(row, col)
                    if it:
                        it.setForeground(Qt.gray)


# ── 规则弹窗（点工具栏「规则」打开，不在面板里内联展开）──────
class RulesDialog(QDialog):
    def __init__(self, ns: str, on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('匹配规则')
        self.setMinimumSize(680, 460)
        lay = QVBoxLayout(self)
        self.editor = RulesEditor()
        self.editor.set_namespace(ns)
        if on_changed:
            self.editor.changed.connect(on_changed)
        lay.addWidget(self.editor)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText('关闭')
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        self.editor.reload()


# ── 启动定时弹窗（间隔 + 规则编辑，参考 standalone）──────────
class StartTimerDialog(QDialog):
    def __init__(self, ns: str, scan_count: int, interval: int, on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('启动定时同步（后台批量）')
        self.setMinimumSize(680, 520)
        lay = QVBoxLayout(self)

        tip = QLabel(f'范围 = 左侧勾选的 {scan_count} 个文件夹；按下方启用的规则匹配后推送到服务端。')
        tip.setWordWrap(True)
        tip.setStyleSheet('color:#666;')
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.addWidget(QLabel('每'))
        self._spin = QSpinBox()
        self._spin.setRange(1, 1440)
        self._spin.setValue(max(1, int(interval or 60)))
        self._spin.setSuffix(' 分钟')
        self._spin.setMaximumWidth(110)
        row.addWidget(self._spin)
        row.addWidget(QLabel('自动同步一次'))
        row.addStretch()
        lay.addLayout(row)

        self.editor = RulesEditor()
        self.editor.set_namespace(ns)
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

    def interval(self) -> int:
        return self._spin.value()
